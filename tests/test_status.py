from pathlib import Path

import pytest

from nara.config import Secrets, load_settings
from nara.db import connect, migrate
from nara.g2b.list_api import NoticeItem
from nara.naver import SearchResult
from nara.status import judge_project, pending_status_projects
from nara.store import ensure_project, upsert_notice, upsert_org
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


def _add_notice(conn, project_id, bid_no, open_date):
    """rule_verdict가 개찰 근거로 볼 수 있도록 공고를 하나 붙인다.

    tests/test_award.py의 _add_notice와 같은 구성 — 판정에 필요한 필드만
    채운다.
    """
    org_id = conn.execute("SELECT org_id FROM project WHERE id = ?", (project_id,)).fetchone()[0]
    item = NoticeItem(
        bid_no=bid_no,
        bid_ord="0",
        org_name="",
        title="공고",
        service_div="기술용역",
        kind="등록공고",
        notice_date=open_date,
        open_date=open_date,
        close_date=open_date,
        url="",
        budget_krw=None,
        budget_basis="",
        officer_name="",
        officer_tel="",
        raw={},
    )
    upsert_notice(conn, item, org_id, project_id, NOW)


def _add_award(conn, bid_no, winner, award_date="2026-08-10"):
    conn.execute(
        "INSERT INTO award (bid_no, winner, award_date, checked_at) VALUES (?, ?, ?, ?)",
        (bid_no, winner, award_date, NOW),
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
    """개찰일이 지나 규칙이 '착공 전'이라 판정했는데 시트 착공일도 지났으면
    불일치를 사유에 남긴다(date_conflict의 BEFORE 분기)."""
    project_id = _project(conn, "전북특별자치도 완주군", "사업")
    _add_notice(conn, project_id, "R1", open_date="2025-10-20")
    conn.execute("UPDATE project SET start_date = '2025-11-03' WHERE id = ?", (project_id,))
    conn.commit()
    got = judge_project(
        conn, _row(conn, project_id), SECRETS, "2026-09-18", search=_no_search, adjudicator=_no_llm
    )
    assert got.verdict == BEFORE
    assert "2025-11-03" in got.reason


def test_judge_records_no_conflict_when_verdict_stays_unknown_despite_a_past_start_date(conn):
    """미확인엔 근거가 없다 — 대조할 보도가 없으면 시트 착공일이 지났어도
    불일치를 만들지 않는다(R26). 공고가 아예 없는 사업은 개찰 근거도 없어
    '착공 전' 자체를 주장하지 않으므로 date_conflict가 볼 것이 없다."""
    project_id = _project(conn, "전북특별자치도 완주군", "사업")
    conn.execute("UPDATE project SET start_date = '2025-11-03' WHERE id = ?", (project_id,))
    conn.commit()
    got = judge_project(
        conn, _row(conn, project_id), SECRETS, "2026-09-18", search=_no_search, adjudicator=_no_llm
    )
    assert got.verdict == UNKNOWN
    assert "2025-11-03" not in got.reason


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


# --- F1/F2 (R27/R28): 진짜 0건 검색과 무관한 기사가 기존 판정을 지우면 안 된다 ---


def test_judge_distinguishes_skip_zero_result_and_failure_in_the_reason(conn):
    """검색을 안 한 것·검색했는데 진짜 0건·검색이 실패한 것은 사유에서 서로
    다르게 보여야 한다(F1). 셋 다 '개찰일 없음'만 남으면 성공한 조회가
    실패한 조회보다 못한 취급을 받는다."""
    project_id = _project(conn, "전북특별자치도 완주군", "사업")

    skipped = judge_project(
        conn, _row(conn, project_id), SECRETS, "2026-09-18", search=_no_search, adjudicator=_no_llm
    )
    zero_result = judge_project(
        conn,
        _row(conn, project_id),
        SECRETS,
        "2026-09-18",
        search=lambda *a, **k: SearchResult(articles=[], searched=True),
        adjudicator=_no_llm,
    )
    failed = judge_project(
        conn,
        _row(conn, project_id),
        SECRETS,
        "2026-09-18",
        search=lambda *a, **k: SearchResult(note="뉴스 검색 실패: HTTP 429"),
        adjudicator=_no_llm,
    )

    assert skipped.reason == "개찰일 없음 (네이버 검색 키가 없어 뉴스 검색을 건너뛰었다)"
    assert zero_result.reason == "개찰일 없음 (뉴스: 검색 결과 없음)"
    assert failed.reason == "개찰일 없음 (뉴스 검색 실패: HTTP 429)"
    assert len({skipped.reason, zero_result.reason, failed.reason}) == 3


def test_judge_keeps_the_rule_verdict_when_search_is_skipped(conn):
    """DB가 이미 아는 사실(낙찰업체 기록됨)은 검색을 안 했다고 사라지지
    않는다 — 회귀 확인용 대조군."""
    project_id = _project(conn, "전북특별자치도 완주군", "사업")
    _add_notice(conn, project_id, "R1", open_date="2026-08-01")
    _add_award(conn, "R1", "가건축")

    got = judge_project(
        conn, _row(conn, project_id), SECRETS, "2026-09-18", search=_no_search, adjudicator=_no_llm
    )

    assert got.verdict == BEFORE
    assert got.decided_by == "rule"


def test_judge_does_not_let_an_irrelevant_article_erase_a_known_fact(conn):
    """무관한 기사 한 건 때문에 낙찰업체 기록이라는 사실이 미확인으로
    지워지면 안 된다(F2). 뉴스가 아무 신호도 못 찾았으면 규칙 판정을
    유지하되, 뉴스를 확인했다는 사실은 사유에 남긴다."""
    project_id = _project(conn, "전북특별자치도 완주군", "사업")
    _add_notice(conn, project_id, "R1", open_date="2026-08-01")
    _add_award(conn, "R1", "가건축")
    found = SearchResult(
        articles=[
            Article("완주군수 신년사", "새해 인사말씀 드립니다", "https://n/9", "2026-01-01")
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

    assert got.verdict == BEFORE
    assert got.decided_by == "rule"
    assert "뉴스: 관련 신호 없음" in got.reason


def test_judge_keeps_the_rule_verdict_on_a_genuine_zero_result_search(conn):
    """진짜 0건도 마찬가지다 — 검색은 했지만 아무것도 안 나온 것이지, 이미
    기록된 낙찰 사실을 뒤집을 근거가 아니다(F2)."""
    project_id = _project(conn, "전북특별자치도 완주군", "사업")
    _add_notice(conn, project_id, "R1", open_date="2026-08-01")
    _add_award(conn, "R1", "가건축")

    got = judge_project(
        conn,
        _row(conn, project_id),
        SECRETS,
        "2026-09-18",
        search=lambda *a, **k: SearchResult(articles=[], searched=True),
        adjudicator=_no_llm,
    )

    assert got.verdict == BEFORE
    assert got.decided_by == "rule"
    assert "뉴스: 검색 결과 없음" in got.reason


# --- F3 (R29): 재공고가 이미 지난 개찰을 가리면 안 된다 ---


def test_judge_prefers_the_most_recent_past_opening_over_a_future_retender(conn):
    """유찰 후 재공고는 흔하다. MAX(open_date)로 고르면 아직 열리지 않은
    재공고의 미래 개찰일에 가려 이미 지난 개찰(그리고 그 유찰 사실)이
    사라진다."""
    project_id = _project(conn, "전북특별자치도 완주군", "사업")
    _add_notice(conn, project_id, "R1", open_date="2025-01-01")
    _add_notice(conn, project_id, "R2", open_date="2026-12-01")

    got = judge_project(
        conn, _row(conn, project_id), SECRETS, "2026-09-18", search=_no_search, adjudicator=_no_llm
    )

    assert got.verdict == BEFORE
    assert "개찰일이 지났고 낙찰업체 미확인 — 설계 단계" in got.reason
    assert "건너뛰" in got.reason
