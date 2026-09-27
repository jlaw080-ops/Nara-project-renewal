"""웹 조회 화면 — DB가 필요한 테스트."""

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from nara.config import load_settings
from nara.db import connect, migrate
from nara.store import ensure_project, upsert_org
from nara.verdict import BEFORE, BUILDING, DONE, UNKNOWN
from nara.web.data import DatabaseMissing, list_projects, open_readonly
from nara.web.query import NO_VERDICT, Filters


def _make_db(path: Path) -> Path:
    conn = connect(path)
    migrate(conn)
    conn.close()
    return path


SETTINGS = load_settings(Path(__file__).resolve().parents[1] / "config.toml")
NOW = "2026-09-27T09:00:00"


def _org(conn, name, tier):
    org_id = upsert_org(conn, name, SETTINGS, NOW)
    # 설정 파일의 관심기관 목록과 무관하게 테스트가 tier를 정한다.
    conn.execute("UPDATE org SET tier = ? WHERE id = ?", (tier, org_id))
    return org_id


def _project(conn, org_id, name, source="g2b"):
    return ensure_project(conn, org_id, name, source, NOW)


def _notice(conn, project_id, org_id, bid_no, title, notice_date):
    conn.execute(
        "INSERT INTO notice (bid_no, project_id, org_id, org_name, title, notice_date, "
        "open_date, collected_at) VALUES (?, ?, ?, (SELECT name FROM org WHERE id = ?), "
        "?, ?, ?, ?)",
        (bid_no, project_id, org_id, org_id, title, notice_date, notice_date, NOW),
    )


def _award(conn, bid_no, winner, award_date):
    conn.execute(
        "INSERT INTO award (bid_no, winner, award_date, checked_at) VALUES (?, ?, ?, ?)",
        (bid_no, winner, award_date, NOW),
    )


def _verdict(
    conn,
    project_id,
    verdict,
    when="2026-09-20T09:00:00",
    decided_by="rule",
    reason="",
    evidence_json=None,
):
    conn.execute(
        "INSERT INTO status_check (project_id, verdict, reason, decided_by, evidence_json, "
        "checked_at) VALUES (?, ?, ?, ?, ?, ?)",
        (project_id, verdict, reason, decided_by, evidence_json, when),
    )


@pytest.fixture
def world(tmp_path):
    """실제 모양을 줄인 DB. 공고 있는 사업·재공고·시트 이관(공고 없음)·판정 전을 다 담는다."""
    path = tmp_path / "w.db"
    conn = connect(path)
    migrate(conn)
    wanju = _org(conn, "전북특별자치도 완주군", "focus")
    seongnam = _org(conn, "경기도 성남시", "rest")
    ids = {}

    ids["gym"] = _project(conn, wanju, "완주군 다목적체육관")
    _notice(conn, ids["gym"], wanju, "N1", "완주군 다목적체육관 건립 설계용역", "2026-03-10")
    _verdict(conn, ids["gym"], BEFORE)

    ids["welfare"] = _project(conn, wanju, "완주군 종합사회복지관")
    _notice(conn, ids["welfare"], wanju, "N2A", "완주군 종합사회복지관 설계용역", "2026-01-05")
    _notice(
        conn, ids["welfare"], wanju, "N2B", "완주군 종합사회복지관 설계용역(재공고)", "2026-02-20"
    )
    _award(conn, "N2B", "가건축", "2026-03-01")
    _verdict(conn, ids["welfare"], BUILDING)

    ids["museum"] = _project(conn, seongnam, "성남시 박물관")
    _notice(
        conn,
        ids["museum"],
        seongnam,
        "N3",
        "성남시 박물관 건립공사 설계의도구현 용역",
        "2025-11-01",
    )
    _verdict(conn, ids["museum"], DONE)

    ids["sheet_unknown"] = _project(conn, wanju, "완주 풍류체험관", source="manual")
    _verdict(conn, ids["sheet_unknown"], UNKNOWN, decided_by="imported")

    ids["sheet_new"] = _project(conn, seongnam, "여수동 100% 친환경 센터", source="manual")

    ids["culture"] = _project(conn, seongnam, "성남시 문화복합시설")
    _notice(conn, ids["culture"], seongnam, "N6", "성남시 체육관 리모델링", "2026-04-01")

    conn.commit()
    conn.close()
    return path, ids


def _list(path, **kw):
    with closing(open_readonly(path)) as conn:
        return list_projects(conn, Filters(**kw))


def _names(result):
    return [row["name"] for row in result.rows]


def test_open_readonly_refuses_writes(tmp_path):
    """1단계는 읽기 전용이다. 화면에 버그가 있어도 자료를 바꿀 수 없어야 한다."""
    with closing(open_readonly(_make_db(tmp_path / "t.db"))) as conn:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            conn.execute("INSERT INTO app_state (key, value) VALUES ('x', 'y')")


def test_open_readonly_does_not_create_a_missing_file(tmp_path):
    """오타 난 경로에 빈 DB를 만들면 '자료 0건'이 정상으로 보인다."""
    missing = tmp_path / "nope.db"
    with pytest.raises(DatabaseMissing):
        open_readonly(missing)
    assert not missing.exists()


def test_open_readonly_opens_a_path_with_space_and_hash(tmp_path):
    """실측: '#'을 URI에 그대로 넣으면 SQLite가 그 뒤를 잘라 엉뚱한 빈 DB를 연다.

    오류가 아니라 'no such table'만 난다. 업무 파일은 공백이 든 폴더
    ('ENERGINNO Dropbox')에 있다.
    """
    folder = tmp_path / "sp ace #dir"
    folder.mkdir()
    with closing(open_readonly(_make_db(folder / "n a#ra.db"))) as conn:
        assert conn.execute("SELECT value FROM app_state").fetchone()[0] == "1"


def test_open_readonly_returns_rows_by_column_name(tmp_path):
    with closing(open_readonly(_make_db(tmp_path / "t.db"))) as conn:
        row = conn.execute("SELECT key FROM app_state").fetchone()
    assert row["key"] == "schema_version"


def test_list_puts_the_newest_notice_first_and_sheet_projects_last(world):
    """기본은 공고일 내림차순. 공고 없는 사업은 방향과 관계없이 맨 뒤, 그 안에서는 id순."""
    result = _list(world[0])
    assert _names(result) == [
        "성남시 문화복합시설",
        "완주군 다목적체육관",
        "완주군 종합사회복지관",
        "성남시 박물관",
        "완주 풍류체험관",
        "여수동 100% 친환경 센터",
    ]
    assert (result.total, result.matched, result.excluded_no_notice) == (6, 6, None)
    assert result.truncated is False


def test_list_shows_a_renoticed_project_once_with_its_latest_notice(world):
    """유찰 재공고가 있어도 목록엔 한 줄. 붙는 공고·낙찰업체는 최신 공고의 것이다."""
    path, ids = world
    rows = [r for r in _list(path).rows if r["id"] == ids["welfare"]]
    assert len(rows) == 1
    assert rows[0]["notice_date"] == "2026-02-20"
    assert rows[0]["notice_title"] == "완주군 종합사회복지관 설계용역(재공고)"
    assert rows[0]["winner"] == "가건축"


def test_date_filter_drops_projects_without_a_notice_and_counts_them(world):
    """시트에서 이관한 사업은 공고일이 없어 기간 조건에서 빠진다. 빠진 수를 알려야 한다."""
    result = _list(world[0], date_from="2026-01-01")
    assert _names(result) == ["성남시 문화복합시설", "완주군 다목적체육관", "완주군 종합사회복지관"]
    assert result.excluded_no_notice == 2


def test_excluded_count_follows_the_other_conditions(world):
    """고정값이 아니다. 다른 조건에 걸리는 공고 없는 사업만 센다."""
    path, _ = world
    with closing(open_readonly(path)) as conn:
        seongnam = conn.execute("SELECT id FROM org WHERE name = '경기도 성남시'").fetchone()[0]
    result = _list(path, date_from="2026-01-01", orgs=(seongnam,))
    assert _names(result) == ["성남시 문화복합시설"]
    assert result.excluded_no_notice == 1


def test_date_filter_uses_the_notice_that_is_shown(world):
    """보이는 공고와 거른 공고가 다르면 '1월 조건인데 왜 2월 공고가 보이지'가 된다.

    종합사회복지관의 옛 공고(1월 5일)는 기간 안이지만 보이는 공고는 2월 20일이다.
    """
    assert _names(_list(world[0], date_to="2026-01-31")) == ["성남시 박물관"]


def test_search_finds_project_name_and_notice_title(world):
    """공고명으로만 걸린 행은 그 공고명을 함께 돌려준다 — 목록엔 사업명만 보인다."""
    path, ids = world
    rows = {r["id"]: r for r in _list(path, q="체육").rows}
    assert set(rows) == {ids["gym"], ids["culture"]}
    assert rows[ids["gym"]]["matched_title"] is None
    assert rows[ids["culture"]]["matched_title"] == "성남시 체육관 리모델링"


def test_search_finds_a_sheet_project_by_its_name(world):
    """공고명만 찾으면 시트에서 이관한 95건은 이름으로 영영 못 찾는다."""
    assert _names(_list(world[0], q="풍류")) == ["완주 풍류체험관"]


def test_search_takes_percent_literally(world):
    assert _names(_list(world[0], q="100%")) == ["여수동 100% 친환경 센터"]
    assert _names(_list(world[0], q="%")) == ["여수동 100% 친환경 센터"]


def test_verdict_filter_includes_projects_not_yet_judged(world):
    path, _ = world
    assert _names(_list(path, verdicts=(BEFORE,))) == ["완주군 다목적체육관"]
    assert _names(_list(path, verdicts=(NO_VERDICT,))) == [
        "성남시 문화복합시설",
        "여수동 100% 친환경 센터",
    ]
    assert _names(_list(path, verdicts=(BUILDING, NO_VERDICT))) == [
        "성남시 문화복합시설",
        "완주군 종합사회복지관",
        "여수동 100% 친환경 센터",
    ]


def test_verdict_sort_follows_the_stages_and_keeps_unjudged_last(world):
    """가나다순이면 '미확인·시공 중·준공 완료·착공 전'이 된다.

    '판정 전'을 단계에 넣으면 내림차순에서 맨 앞으로 올라와 판정된 사업을 가린다.
    """
    path, _ = world
    assert _names(_list(path, sort="verdict", desc=False)) == [
        "완주군 다목적체육관",
        "완주군 종합사회복지관",
        "성남시 박물관",
        "완주 풍류체험관",
        "여수동 100% 친환경 센터",
        "성남시 문화복합시설",
    ]
    assert _names(_list(path, sort="verdict", desc=True)) == [
        "완주 풍류체험관",
        "성남시 박물관",
        "완주군 종합사회복지관",
        "완주군 다목적체육관",
        "여수동 100% 친환경 센터",
        "성남시 문화복합시설",
    ]


def test_focus_only_keeps_focus_orgs(world):
    assert _names(_list(world[0], focus_only=True)) == [
        "완주군 다목적체육관",
        "완주군 종합사회복지관",
        "완주 풍류체험관",
    ]


def test_list_reports_truncation_instead_of_dropping_rows_silently(world, monkeypatch):
    monkeypatch.setattr("nara.web.query.LIST_LIMIT", 2)
    result = _list(world[0])
    assert len(result.rows) == 2
    assert result.matched == 6
    assert result.truncated is True


def test_list_keeps_the_last_department_that_had_a_name(world):
    """가장 최근 조회에서 부서를 못 찾았다고 앞서 찾은 부서를 지우지 않는다."""
    path, ids = world
    conn = connect(path)
    for when, dept in (("2026-09-01T00:00:00", "체육진흥과"), ("2026-09-10T00:00:00", "")):
        conn.execute(
            "INSERT INTO dept_check (project_id, exec_dept, decided_by, checked_at) "
            "VALUES (?, ?, 'imported', ?)",
            (ids["gym"], dept, when),
        )
    conn.commit()
    conn.close()
    row = next(r for r in _list(path).rows if r["id"] == ids["gym"])
    assert row["exec_dept"] == "체육진흥과"
