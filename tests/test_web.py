"""웹 조회 화면 — DB가 필요한 테스트."""

import html
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from nara.config import load_settings
from nara.db import connect, migrate
from nara.store import ensure_project, upsert_org
from nara.verdict import BEFORE, BUILDING, DONE, UNKNOWN
from nara.web.app import create_app, get_conn
from nara.web.data import (
    DatabaseMissing,
    last_runs,
    list_projects,
    open_readonly,
    org_options,
    project_detail,
    safe_url,
)
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


def _detail(path, project_id):
    with closing(open_readonly(path)) as conn:
        return project_detail(conn, project_id)


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


def test_project_detail_is_none_for_an_unknown_id(world):
    assert _detail(world[0], 999999) is None


def test_project_detail_lists_every_notice_newest_first_with_awards(world):
    """재공고가 있으면 무슨 일이 있었는지 상세에서 다 보여야 한다. 목록은 최신 하나만 보인다."""
    path, ids = world
    d = _detail(path, ids["welfare"])
    assert [n["bid_no"] for n in d.notices] == ["N2B", "N2A"]
    assert d.notices[0]["winner"] == "가건축"
    assert d.notices[1]["winner"] is None
    assert d.project["org_name"] == "전북특별자치도 완주군"


def test_project_detail_shows_the_whole_verdict_history_newest_first(world):
    """status_check는 쌓이는 표인데 파이프라인은 최신 한 줄만 쓴다. 이력은 여기서 처음 보인다."""
    path, ids = world
    conn = connect(path)
    _verdict(
        conn,
        ids["gym"],
        BUILDING,
        when="2026-09-25T09:00:00",
        decided_by="news",
        reason="착공·기공식 보도",
    )
    conn.commit()
    conn.close()
    d = _detail(path, ids["gym"])
    assert [(h.verdict, h.decided_by) for h in d.history] == [(BUILDING, "뉴스"), (BEFORE, "규칙")]
    assert d.history[0].reason == "착공·기공식 보도"


def test_project_detail_shows_an_unfamiliar_decider_as_is(world):
    """모르는 값을 지우지 않는다. 그대로 보여야 무엇이 들어왔는지 안다."""
    path, ids = world
    conn = connect(path)
    _verdict(conn, ids["culture"], UNKNOWN, decided_by="robot")
    conn.commit()
    conn.close()
    assert _detail(path, ids["culture"]).history[0].decided_by == "robot"


def test_project_detail_reads_the_evidence_url(world):
    path, ids = world
    conn = connect(path)
    _verdict(conn, ids["culture"], BUILDING, evidence_json='{"url": "https://news.example.com/1"}')
    conn.commit()
    conn.close()
    assert _detail(path, ids["culture"]).history[0].evidence_url == "https://news.example.com/1"


def test_project_detail_survives_broken_evidence_json(world):
    """근거가 깨졌다고 상세 화면이 죽으면 그 사업의 나머지 자료까지 못 본다."""
    path, ids = world
    conn = connect(path)
    for i, raw in enumerate(['{"url": ', '["https://x"]', '{"url": 3}', "{}", None]):
        _verdict(
            conn,
            ids["culture"],
            UNKNOWN,
            when=f"2026-09-2{i}T09:00:00",
            reason=f"r{i}",
            evidence_json=raw,
        )
    conn.commit()
    conn.close()
    d = _detail(path, ids["culture"])
    assert len(d.history) == 5
    assert all(h.evidence_url == "" for h in d.history)


def test_project_detail_never_links_a_script_url(world):
    """자동 이스케이프는 href의 'javascript:'를 막지 못한다. 근거는 뉴스·LLM에서 온다."""
    path, ids = world
    conn = connect(path)
    _verdict(conn, ids["culture"], BUILDING, evidence_json='{"url": "javascript:alert(1)"}')
    conn.execute("UPDATE notice SET url = ? WHERE bid_no = 'N6'", (" JavaScript:alert(1)",))
    conn.commit()
    conn.close()
    d = _detail(path, ids["culture"])
    assert d.history[0].evidence_url == ""
    assert d.notices[0]["url"] == ""


def test_safe_url_keeps_web_addresses_only():
    assert safe_url("https://a.kr/x") == "https://a.kr/x"
    assert safe_url("HTTP://A.KR") == "HTTP://A.KR"
    for bad in ("javascript:alert(1)", "data:text/html,x", "//evil.example", "ftp://x", "", None):
        assert safe_url(bad) == "", bad


def test_project_detail_prices_energy_and_names_what_it_could_not_price(world):
    """estimate_cost는 단가표에 없는 에너지원을 빼고 합한다. 합계만 보이면 왜 적은지 모른다."""
    path, ids = world
    conn = connect(path)
    for source, kw in (("PV", 20.0), ("풍력", 10.0)):
        conn.execute(
            "INSERT INTO energy_plan (project_id, source_type, capacity_kw, entered_by, "
            "updated_at) VALUES (?, ?, ?, 'imported', ?)",
            (ids["gym"], source, kw, NOW),
        )
    conn.commit()
    conn.close()
    d = _detail(path, ids["gym"])
    assert [(e.source_type, e.cost) for e in d.energy] == [("PV", 50_000_000), ("풍력", None)]
    assert d.energy_total == 50_000_000
    assert d.energy_unpriced == ["풍력"]


def test_project_detail_lists_departments_newest_first(world):
    path, ids = world
    conn = connect(path)
    for when, dept in (
        ("2026-09-01T00:00:00", "체육진흥과"),
        ("2026-09-10T00:00:00", "문화체육과"),
    ):
        conn.execute(
            "INSERT INTO dept_check (project_id, exec_dept, decided_by, checked_at) "
            "VALUES (?, ?, 'imported', ?)",
            (ids["gym"], dept, when),
        )
    conn.commit()
    conn.close()
    assert [r["exec_dept"] for r in _detail(path, ids["gym"]).depts] == ["문화체육과", "체육진흥과"]


def _run(conn, command, status, started_at):
    conn.execute(
        "INSERT INTO run_log (command, started_at, status) VALUES (?, ?, ?)",
        (command, started_at, status),
    )


def test_last_runs_names_every_stage_even_one_that_never_ran(world):
    """한 번도 돌지 않은 단계가 화면에서 사라지면 '멈춘 줄 모르는' 사고가 그대로다."""
    with closing(open_readonly(world[0])) as conn:
        runs = last_runs(conn)
    assert [r.label for r in runs] == ["수집", "소급 수집", "낙찰 조회", "진행현황"]
    for r in runs:
        assert (r.started_at, r.status_label, r.healthy) == (None, "실행 기록 없음", False)


def test_last_runs_reports_the_latest_run_of_each_stage(world):
    path, _ = world
    conn = connect(path)
    _run(conn, "collect", "ok", "2026-09-20T06:10:00")
    _run(conn, "collect", "partial", "2026-09-26T06:10:00")
    _run(conn, "enrich award", "ok", "2026-09-26T06:14:00")
    _run(conn, "enrich status", "error", "2026-09-26T06:20:00")
    _run(conn, "backfill", None, "2026-09-26T07:00:00")
    _run(conn, "migrate tsv", "ok", "2026-09-26T08:00:00")
    conn.commit()
    conn.close()
    with closing(open_readonly(path)) as conn:
        runs = {r.label: r for r in last_runs(conn)}
    assert (runs["수집"].started_at, runs["수집"].status_label) == (
        "2026-09-26T06:10:00",
        "일부 실패",
    )
    assert runs["수집"].healthy is False
    assert (runs["낙찰 조회"].status_label, runs["낙찰 조회"].healthy) == ("정상", True)
    assert runs["진행현황"].status_label == "실패"
    # 프로세스가 죽으면 run_log의 마무리가 돌지 못해 status가 비어 남는다
    assert runs["소급 수집"].status_label == "끝나지 않음"
    # 이관은 파이프라인 단계가 아니다
    assert set(runs) == {"수집", "소급 수집", "낙찰 조회", "진행현황"}


def test_org_options_puts_focus_orgs_first(world):
    with closing(open_readonly(world[0])) as conn:
        names = [o["name"] for o in org_options(conn)]
    assert names == ["전북특별자치도 완주군", "경기도 성남시"]


def _client(path):
    app = create_app(path)
    app.testing = True
    return app.test_client()


def _text(resp):
    return resp.get_data(as_text=True)


def _header_link(text, label):
    """열 머리 링크의 쿼리 인자. 템플릿은 &를 &amp;로 이스케이프한다."""
    href = re.search(rf'href="([^"]*)">{label}</a>', text).group(1)
    return parse_qs(urlsplit(html.unescape(href)).query)


def test_list_page_shows_every_project_and_the_counts(world):
    resp = _client(world[0]).get("/")
    assert resp.status_code == 200
    text = _text(resp)
    assert "6건 중 6건" in text
    for name in (
        "완주군 다목적체육관",
        "완주군 종합사회복지관",
        "성남시 박물관",
        "완주 풍류체험관",
        "여수동 100% 친환경 센터",
        "성남시 문화복합시설",
    ):
        assert name in text


def test_list_page_shows_why_a_row_matched_by_notice_title(world):
    """목록엔 사업명만 보인다. 공고명으로만 걸린 행은 왜 걸렸는지 적어야 한다."""
    assert "공고명: 성남시 체육관 리모델링" in _text(_client(world[0]).get("/?q=체육"))


def test_list_page_says_how_many_sheet_projects_a_date_filter_dropped(world):
    text = _text(_client(world[0]).get("/?from=2026-01-01"))
    assert "6건 중 3건" in text
    assert "공고가 없는 사업 2건이 제외되었습니다" in text


def test_list_page_explains_ignored_input_instead_of_failing(world):
    resp = _client(world[0]).get("/?from=어제&sort=evil&org=abc")
    assert resp.status_code == 200
    text = _text(resp)
    assert "시작일 형식이 맞지 않아 무시했습니다" in text
    assert "쓸 수 없어 공고일로 바꿨습니다" in text
    assert "쓸 수 없어 무시했습니다" in text


def test_sort_links_keep_the_conditions_and_flip_the_current_column(world):
    """URL이 곧 상태다. 열 머리를 눌러도 걸어 둔 조건이 남아야 한다."""
    client = _client(world[0])
    text = _text(client.get("/?q=성남"))
    # 다른 열을 누르면 그 열의 오름차순으로 간다
    assert _header_link(text, "사업명") == {"q": ["성남"], "sort": ["name"], "desc": ["0"]}
    # 지금 정렬 중인 열을 누르면 방향이 뒤집힌다
    text = _text(client.get("/?q=성남&sort=notice_date&desc=0"))
    assert _header_link(text, "공고일")["desc"] == ["1"]


def test_list_page_marks_a_stage_that_never_ran(world):
    assert "실행 기록 없음" in _text(_client(world[0]).get("/"))


def test_detail_page_shows_all_notices_and_the_history(world):
    path, ids = world
    text = _text(_client(path).get(f"/project/{ids['welfare']}"))
    assert "공고 2건" in text
    assert "완주군 종합사회복지관 설계용역(재공고)" in text
    assert "가건축" in text
    assert "규칙" in text


def test_detail_page_is_404_for_an_unknown_or_non_numeric_id(world):
    client = _client(world[0])
    assert client.get("/project/999999").status_code == 404
    assert client.get("/project/abc").status_code == 404


def test_pages_escape_markup_that_comes_from_the_data(world):
    """사업명·기사 제목은 밖에서 온 글이다. 그대로 그리면 스크립트가 실행된다."""
    path, _ = world
    conn = connect(path)
    org_id = upsert_org(conn, "전북특별자치도 완주군", SETTINGS, NOW)
    project_id = ensure_project(conn, org_id, "<script>alert(1)</script>", "manual", NOW)
    conn.close()
    client = _client(path)
    for url in ("/", f"/project/{project_id}"):
        text = _text(client.get(url))
        assert "&lt;script&gt;" in text
        assert "<script" not in text


def test_detail_page_does_not_link_a_script_url(world):
    path, ids = world
    conn = connect(path)
    _verdict(conn, ids["culture"], BUILDING, evidence_json='{"url": "javascript:alert(1)"}')
    conn.commit()
    conn.close()
    assert "javascript:" not in _text(_client(path).get(f"/project/{ids['culture']}")).lower()


def test_the_app_opens_the_database_read_only(world):
    """스펙: 앱이 연 연결로 INSERT를 시도해 거부되는 것을 확인한다.

    누군가 open_readonly를 connect로 바꾸면 이 테스트가 깨진다.
    """
    app = create_app(world[0])
    with app.app_context():
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            get_conn().execute("INSERT INTO app_state (key, value) VALUES ('x', 'y')")


def test_a_missing_database_is_reported_not_crashed(tmp_path):
    """서버를 띄운 뒤 DB 파일이 사라진 경우다. 추적 화면 대신 이유를 말한다."""
    resp = _client(tmp_path / "gone.db").get("/")
    assert resp.status_code == 503
    assert "DB 파일이 없다" in _text(resp)
    assert not (tmp_path / "gone.db").exists()
