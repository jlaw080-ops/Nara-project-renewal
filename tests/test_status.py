from pathlib import Path

import pytest

from nara.config import Secrets, load_settings
from nara.db import connect, migrate
from nara.naver import SearchResult
from nara.status import judge_project, pending_status_projects
from nara.store import ensure_project, upsert_org
from nara.verdict import BEFORE, BUILDING, UNKNOWN, Article

SETTINGS = load_settings(Path(__file__).resolve().parents[1] / "config.toml")
NOW = "2026-09-18T09:00:00"
SECRETS = Secrets(
    g2b_api_key="x", naver_client_id=None, naver_client_secret=None, anthropic_api_key=None
)


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "test.db")
    migrate(c)
    return c


def _project(conn, org_name, name):
    org_id = upsert_org(conn, org_name, SETTINGS, NOW)
    return ensure_project(conn, org_id, name, "manual", NOW)


def _checked(conn, project_id, when, verdict="미확인"):
    conn.execute(
        "INSERT INTO status_check (project_id, verdict, decided_by, checked_at) "
        "VALUES (?, ?, 'rule', ?)",
        (project_id, verdict, when),
    )
    conn.commit()


def test_pending_prefers_projects_never_checked(conn):
    old = _project(conn, "전북특별자치도 완주군", "본 적 있는 사업")
    fresh = _project(conn, "전북특별자치도 완주군", "한 번도 안 본 사업")
    _checked(conn, old, "2026-09-01T09:00:00")

    rows = pending_status_projects(conn, tier=None, limit=10)

    assert rows[0]["id"] == fresh


def test_pending_orders_older_checks_first(conn):
    recent = _project(conn, "전북특별자치도 완주군", "최근에 본 사업")
    stale = _project(conn, "전북특별자치도 완주군", "오래전에 본 사업")
    _checked(conn, recent, "2026-09-17T09:00:00")
    _checked(conn, stale, "2026-08-01T09:00:00")

    rows = pending_status_projects(conn, tier=None, limit=10)

    assert [r["id"] for r in rows] == [stale, recent]


def test_pending_filters_by_tier(conn):
    focus = _project(conn, "전북특별자치도 완주군", "관심 기관 사업")
    _project(conn, "강원특별자치도 양양군", "비관심 기관 사업")

    rows = pending_status_projects(conn, tier="focus", limit=10)

    assert [r["id"] for r in rows] == [focus]


def test_pending_honours_limit(conn):
    for i in range(5):
        _project(conn, "전북특별자치도 완주군", f"사업 {i}")
    assert len(pending_status_projects(conn, tier=None, limit=2)) == 2


def test_pending_rejects_nonpositive_limit(conn):
    """limit 0이면 조용히 '대상 0건'으로 끝나 조용한 날과 구분되지 않는다."""
    with pytest.raises(ValueError):
        pending_status_projects(conn, tier=None, limit=0)


def test_pending_carries_the_dates_the_judgment_needs(conn):
    project_id = _project(conn, "전북특별자치도 완주군", "사업")
    conn.execute(
        "UPDATE project SET start_date = ?, end_date = ? WHERE id = ?",
        ("2027-03-01", "2029-01-30", project_id),
    )
    conn.commit()

    row = pending_status_projects(conn, tier=None, limit=10)[0]

    assert row["start_date"] == "2027-03-01"
    assert row["end_date"] == "2029-01-30"
    assert row["name"] == "사업"


def _no_search(*args, **kwargs):
    return SearchResult(note="네이버 검색 키가 없어 뉴스 검색을 건너뛰었다")


def _no_llm(*args, **kwargs):
    return None


def _row(conn, project_id):
    return conn.execute(
        "SELECT p.id, p.name, p.start_date, p.end_date, o.name AS org_name "
        "FROM project p JOIN org o ON o.id = p.org_id WHERE p.id = ?",
        (project_id,),
    ).fetchone()


def test_judge_falls_back_to_rules_when_search_is_unavailable(conn):
    project_id = _project(conn, "전북특별자치도 완주군", "사업")
    got = judge_project(
        conn, _row(conn, project_id), SECRETS, "2026-09-18", search=_no_search, adjudicator=_no_llm
    )
    assert got.decided_by == "rule"
    assert got.verdict in (BEFORE, UNKNOWN)


def test_judge_says_it_skipped_the_news_search(conn):
    """검색을 안 했다는 사실이 근거에 남아야 한다. 조용히 넘어가지 않는다."""
    project_id = _project(conn, "전북특별자치도 완주군", "사업")
    got = judge_project(
        conn, _row(conn, project_id), SECRETS, "2026-09-18", search=_no_search, adjudicator=_no_llm
    )
    assert "건너뛰" in got.reason


def test_judge_uses_news_when_it_finds_evidence(conn):
    project_id = _project(conn, "전북특별자치도 완주군", "완주군 종합사회복지관")
    found = SearchResult(
        articles=[Article("완주군 종합사회복지관 기공식", "", "https://n/1", "2026-08-28")],
        searched=True,
    )
    got = judge_project(
        conn,
        _row(conn, project_id),
        SECRETS,
        "2026-09-18",
        search=lambda *a, **k: found,
        adjudicator=_no_llm,
    )
    assert got.verdict == BUILDING
    assert got.decided_by == "news"
    assert got.evidence_url == "https://n/1"


def test_judge_asks_the_llm_only_when_the_news_read_is_ambiguous(conn):
    project_id = _project(conn, "전북특별자치도 완주군", "완주군 다목적체육관")
    found = SearchResult(
        articles=[
            Article("완주군 다목적체육관 2026년 9월 착공 예정", "", "https://n/2", "2026-08-01")
        ],
        searched=True,
    )
    asked = []

    def adjudicator(*args, **kwargs):
        asked.append(True)
        return BEFORE, "기사가 예정이라고 적었다"

    got = judge_project(
        conn,
        _row(conn, project_id),
        SECRETS,
        "2026-09-18",
        search=lambda *a, **k: found,
        adjudicator=adjudicator,
    )
    assert asked
    assert got.decided_by == "llm"
    assert got.verdict == BEFORE


def test_judge_does_not_ask_the_llm_when_the_news_read_is_clear(conn):
    project_id = _project(conn, "전북특별자치도 완주군", "완주군 종합사회복지관")
    found = SearchResult(
        articles=[Article("완주군 종합사회복지관 기공식", "", "https://n/1", "2026-08-28")],
        searched=True,
    )
    asked = []

    def adjudicator(*args, **kwargs):
        asked.append(True)
        return BEFORE, "불려서는 안 된다"

    judge_project(
        conn,
        _row(conn, project_id),
        SECRETS,
        "2026-09-18",
        search=lambda *a, **k: found,
        adjudicator=adjudicator,
    )
    assert not asked


def test_judge_stays_unknown_when_the_llm_cannot_answer(conn):
    project_id = _project(conn, "전북특별자치도 완주군", "완주군 다목적체육관")
    found = SearchResult(
        articles=[
            Article("완주군 다목적체육관 2026년 9월 착공 예정", "", "https://n/2", "2026-08-01")
        ],
        searched=True,
    )
    got = judge_project(
        conn,
        _row(conn, project_id),
        SECRETS,
        "2026-09-18",
        search=lambda *a, **k: found,
        adjudicator=_no_llm,
    )
    assert got.verdict == UNKNOWN
    assert got.decided_by == "news"


def test_judge_records_the_date_conflict_in_the_reason(conn):
    project_id = _project(conn, "전북특별자치도 완주군", "사업")
    conn.execute("UPDATE project SET start_date = '2025-11-03' WHERE id = ?", (project_id,))
    conn.commit()
    got = judge_project(
        conn, _row(conn, project_id), SECRETS, "2026-09-18", search=_no_search, adjudicator=_no_llm
    )
    assert "2025-11-03" in got.reason


def test_judge_never_changes_the_project_dates(conn):
    """불일치를 기록할 뿐 시트 값을 고치지 않는다."""
    project_id = _project(conn, "전북특별자치도 완주군", "사업")
    conn.execute("UPDATE project SET start_date = '2025-11-03' WHERE id = ?", (project_id,))
    conn.commit()
    judge_project(
        conn, _row(conn, project_id), SECRETS, "2026-09-18", search=_no_search, adjudicator=_no_llm
    )
    after = conn.execute("SELECT start_date FROM project WHERE id = ?", (project_id,)).fetchone()
    assert after["start_date"] == "2025-11-03"
