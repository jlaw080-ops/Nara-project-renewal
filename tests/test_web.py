"""웹 조회 화면 — DB가 필요한 테스트."""

import html
import re
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from flask import Flask
from typer.testing import CliRunner
from werkzeug.security import generate_password_hash

from nara.auth import BAD_LOGIN, LOCKED, add_user
from nara.cli import app as cli_app
from nara.config import load_settings
from nara.db import connect, migrate
from nara.store import ensure_project, upsert_org
from nara.verdict import BEFORE, BUILDING, DONE, UNKNOWN
from nara.web import edit
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
RUNS_NOW = datetime(2026, 9, 27, 9, 0, 0)


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


def _dept(conn, project_id, dept, when, decided_by="imported", confirmed=1, note=None):
    conn.execute(
        "INSERT INTO dept_check (project_id, exec_dept, decided_by, confirmed, note, "
        "checked_at) VALUES (?, ?, ?, ?, ?, ?)",
        (project_id, dept, decided_by, confirmed, note, when),
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
        runs = last_runs(conn, now=RUNS_NOW)
    assert [r.label for r in runs] == ["수집", "낙찰 조회", "진행현황", "실행부서", "백업"]
    for r in runs:
        assert (r.started_at, r.status_label, r.healthy) == (None, "실행 기록 없음", False)


def test_last_runs_reports_the_latest_run_of_each_stage(world):
    path, _ = world
    conn = connect(path)
    _run(conn, "collect", "ok", "2026-09-20T06:10:00")
    _run(conn, "collect", "partial", "2026-09-26T06:10:00")
    _run(conn, "enrich award", "ok", "2026-09-26T06:14:00")
    _run(conn, "enrich status", None, "2026-09-26T06:20:00")
    _run(conn, "backfill", "error", "2026-09-26T07:00:00")
    _run(conn, "migrate tsv", "ok", "2026-09-26T08:00:00")
    conn.commit()
    conn.close()
    with closing(open_readonly(path)) as conn:
        runs = {r.label: r for r in last_runs(conn, now=RUNS_NOW)}
    assert (runs["수집"].started_at, runs["수집"].status_label) == (
        "2026-09-26T06:10:00",
        "일부 실패",
    )
    assert runs["수집"].healthy is False
    assert (runs["낙찰 조회"].status_label, runs["낙찰 조회"].healthy) == ("정상", True)
    # 프로세스가 죽으면 run_log의 마무리가 돌지 못해 status가 비어 남는다
    assert runs["진행현황"].status_label == "끝나지 않음"
    # 이관은 파이프라인 단계가 아니다. 소급 수집은 사람이 한 번 돌리는 일이라
    # 스케줄 감시 대상이 아니다 — 넣으면 늘 빨갛게 떠 경고를 무시하게 만든다
    assert set(runs) == {"수집", "낙찰 조회", "진행현황", "실행부서", "백업"}


def test_last_runs_flags_a_scheduled_stage_that_stopped_running(world):
    """스케줄러가 멈추면 run_log에 새 줄이 안 생긴다. 상태만 보면 열흘 전 '정상'이 계속 정상이다.

    72시간은 금요일 15시 뒤 월요일 9시(66시간)를 멈춤으로 잘못 알리지 않는 한계다.
    """
    path, _ = world
    conn = connect(path)
    _run(conn, "collect", "ok", "2026-09-17T18:10:54")
    _run(conn, "enrich award", "ok", "2026-09-24T09:00:00")
    _run(conn, "enrich status", "ok", "2026-09-24T08:59:00")
    conn.commit()
    conn.close()
    with closing(open_readonly(path)) as conn:
        runs = {r.label: r for r in last_runs(conn, now=RUNS_NOW)}
    assert runs["수집"].healthy is False
    assert runs["수집"].status_label == "정상 · 3일 넘게 실행 없음"
    assert (runs["낙찰 조회"].healthy, runs["낙찰 조회"].status_label) == (True, "정상")
    assert runs["진행현황"].healthy is False


def test_org_options_puts_focus_orgs_first(world):
    with closing(open_readonly(world[0])) as conn:
        names = [o["name"] for o in org_options(conn)]
    assert names == ["전북특별자치도 완주군", "경기도 성남시"]


SECRET = "test-secret-key"
TEST_EMAIL = "tester@example.com"
TEST_PASSWORD = "correct horse battery"
ORIGIN = {"Origin": "http://localhost"}


def _ensure_user(path, email=TEST_EMAIL, name="시험", password=TEST_PASSWORD):
    conn = connect(path)
    try:
        if not conn.execute("SELECT 1 FROM app_user WHERE email = ?", (email,)).fetchone():
            add_user(conn, email, name, NOW)
        conn.execute(
            "UPDATE app_user SET password_hash = ?, must_change = 0 WHERE email = ?",
            (generate_password_hash(password, method="scrypt"), email),
        )
        conn.commit()
    finally:
        conn.close()


def _app(path, **config):
    app = create_app(path, secret_key=SECRET)
    app.testing = True
    app.config.update(config)
    return app


def _login(client, path, email=TEST_EMAIL, password=TEST_PASSWORD):
    if path.exists():  # 없는 DB에 connect하면 파일이 생긴다
        _ensure_user(path, email=email, password=password)
    return client.post("/login", data={"email": email, "password": password}, headers=ORIGIN)


def _env_file(tmp_path, **values):
    path = tmp_path / ".env"
    pairs = {"NARA_SECRET_KEY": "test-secret-key", **values}
    path.write_text("".join(f"{k}={v}\n" for k, v in pairs.items()), encoding="utf-8")
    return path


def _client(path, **config):
    client = _app(path, **config).test_client()
    _login(client, path)
    return client


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
    # SQLite 정수 범위를 넘으면 바인딩에서 터져 500이 된다
    assert client.get("/project/99999999999999999999").status_code == 404


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
    app = _app(world[0])
    with app.app_context():
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            get_conn().execute("INSERT INTO app_state (key, value) VALUES ('x', 'y')")


def test_a_missing_database_is_reported_not_crashed(tmp_path):
    """서버를 띄운 뒤 DB 파일이 사라진 경우다. 추적 화면 대신 이유를 말한다."""
    resp = _client(tmp_path / "gone.db").get("/")
    assert resp.status_code == 503
    assert "DB 파일이 없다" in _text(resp)
    assert not (tmp_path / "gone.db").exists()


def test_serve_refuses_a_missing_database(tmp_path):
    """오타 난 경로에 빈 DB를 만들고 '0건'을 보이면 안 된다."""
    missing = tmp_path / "gone.db"
    result = CliRunner().invoke(cli_app, ["serve", "--db", str(missing)])
    assert result.exit_code == 1
    assert "DB 파일이 없다" in result.output
    assert not missing.exists()


def test_serve_binds_to_this_computer_only_without_the_debugger(world, monkeypatch, tmp_path):
    """127.0.0.1 밖에 열면 3단계 전에 외부에 노출된다.

    debug=True는 브라우저에서 파이썬 코드를 실행하는 디버거를 연다.
    """
    seen = {}
    monkeypatch.setattr(Flask, "run", lambda self, **kw: seen.update(kw))
    result = CliRunner().invoke(
        cli_app,
        ["serve", "--db", str(world[0]), "--port", "8123", "--env", str(_env_file(tmp_path))],
    )
    assert result.exit_code == 0, result.output
    assert seen == {"host": "127.0.0.1", "port": 8123, "debug": False}


def test_serve_rejects_an_out_of_range_port(world):
    result = CliRunner().invoke(cli_app, ["serve", "--db", str(world[0]), "--port", "70000"])
    assert result.exit_code != 0


def test_list_page_marks_the_column_it_is_sorted_by(world):
    """열 머리만 보고 지금 무엇으로 어느 방향 정렬 중인지 알 수 있어야 한다."""
    text = _text(_client(world[0]).get("/?sort=name&desc=0"))
    assert re.search(r'<th aria-sort="ascending"><a href="[^"]*">사업명</a>', text)
    assert text.count("aria-sort=") == 1


def _post(client, url, data, origin="http://localhost"):
    headers = {"Origin": origin} if origin else {}
    return client.post(url, data=data, headers=headers)


def _info(**changes):
    base = {
        key: ""
        for key in (
            "address",
            "start_date",
            "end_date",
            "floor_area",
            "zeb_grade",
            "re_ratio",
            "etc_cert",
            "guide_equip",
            "note",
        )
    }
    return {**base, **changes}


def test_edit_link_opens_the_form_for_that_section_only(world):
    path, ids = world
    text = _text(_client(path).get(f"/project/{ids['culture']}?edit=info"))
    assert 'name="floor_area"' in text
    assert 'name="reason"' not in text


def test_saving_info_redirects_and_says_what_changed(world):
    path, ids = world
    client = _client(path)
    resp = _post(client, f"/project/{ids['culture']}/edit/info", _info(floor_area="1,234.5"))
    assert resp.status_code == 302
    text = _text(client.get(resp.headers["Location"]))
    assert "바꾼 칸: 연면적" in text
    assert "수정 이력 1건" in text


def test_invalid_info_is_shown_again_with_the_input_and_the_reason(world):
    path, ids = world
    resp = _post(
        _client(path),
        f"/project/{ids['culture']}/edit/info",
        _info(start_date="2026-05-01", end_date="2026-04-01"),
    )
    assert resp.status_code == 422
    text = _text(resp)
    assert "준공일이 착공일보다 빠릅니다" in text
    assert 'value="2026-05-01"' in text


def test_a_human_verdict_is_marked_locked_and_release_unlocks_it(world):
    path, ids = world
    client = _client(path)
    url = f"/project/{ids['gym']}"
    _post(client, f"{url}/edit/verdict", {"verdict": BUILDING, "reason": "현장 확인"})
    assert "자동 판정이 이 사업을 건너뜁니다" in _text(client.get(url))
    assert "(사람)" in _text(client.get("/?q=다목적체육관"))
    assert _post(client, f"{url}/release", {}).status_code == 302
    text = _text(client.get(url))
    assert "자동 판정이 이 사업을 건너뜁니다" not in text
    assert "잠금 해제" in text


def test_department_can_be_picked_from_a_candidate(world):
    path, ids = world
    conn = connect(path)
    cid = conn.execute(
        "INSERT INTO dept_check (project_id, exec_dept, snippet, decided_by, checked_at) "
        "VALUES (?, '체육진흥과', '부서장 홍길동', 'imported', ?)",
        (ids["gym"], NOW),
    ).lastrowid
    conn.commit()
    conn.close()
    client = _client(path)
    _post(client, f"/project/{ids['gym']}/edit/dept", {"pick": str(cid), "exec_dept": ""})
    conn = connect(path)
    row = conn.execute(
        "SELECT exec_dept, decided_by FROM dept_check ORDER BY id DESC LIMIT 1"
    ).fetchone()
    conn.close()
    assert tuple(row) == ("체육진흥과", "human")


def test_energy_form_adds_and_removes_lines(world):
    path, ids = world
    client = _client(path)
    url = f"/project/{ids['gym']}/edit/energy"
    client.post(
        url,
        data={"source": ["PV", "지열", ""], "capacity": ["20", "10", ""]},
        headers={"Origin": "http://localhost"},
    )
    client.post(
        url,
        data={"source": ["PV", ""], "capacity": ["20", ""]},
        headers={"Origin": "http://localhost"},
    )
    conn = connect(path)
    rows = conn.execute(
        "SELECT source_type FROM energy_plan WHERE project_id = ?", (ids["gym"],)
    ).fetchall()
    conn.close()
    assert [r[0] for r in rows] == ["PV"]


def test_a_post_from_another_site_is_refused(world):
    """다른 웹사이트가 내 브라우저로 127.0.0.1에 저장을 보내는 공격(CSRF)이다."""
    path, ids = world
    client = _client(path)
    url = f"/project/{ids['culture']}/edit/info"
    assert _post(client, url, _info(note="x"), origin="http://evil.example").status_code == 403
    assert _post(client, url, _info(note="x"), origin=None).status_code == 403
    same = client.post(url, data=_info(note="x"), headers={"Sec-Fetch-Site": "same-origin"})
    assert same.status_code == 302


def test_an_unknown_host_is_refused(world):
    """DNS 리바인딩으로 외부 페이지가 이 화면을 읽는 것을 막는다."""
    assert _client(world[0]).get("/", headers={"Host": "evil.example"}).status_code == 400


def test_an_unknown_edit_section_is_404(world):
    path, ids = world
    assert _post(_client(path), f"/project/{ids['gym']}/edit/evil", {}).status_code == 404


def test_saving_while_the_collector_writes_keeps_the_input(world):
    path, ids = world
    client = _client(path, WRITE_TIMEOUT=0.2)
    blocker = sqlite3.connect(path)
    blocker.execute("BEGIN IMMEDIATE")
    try:
        resp = _post(client, f"/project/{ids['culture']}/edit/info", _info(floor_area="777"))
    finally:
        blocker.rollback()
        blocker.close()
    assert resp.status_code == 503
    text = _text(resp)
    assert "수집이 DB를 쓰고 있습니다" in text
    assert 'value="777"' in text


def test_serve_prepares_the_new_tables_on_an_older_database(world, monkeypatch, tmp_path):
    """1단계 때 만든 DB에는 수정 기록 표가 없다. 저장하면 500이 난다."""
    path, _ = world
    conn = connect(path)
    conn.execute("DROP TABLE edit_log")
    conn.commit()
    conn.close()
    monkeypatch.setattr(Flask, "run", lambda self, **kw: None)
    env = str(_env_file(tmp_path))
    result = CliRunner().invoke(cli_app, ["serve", "--db", str(path), "--env", env])
    assert result.exit_code == 0, result.output
    conn = connect(path)
    assert conn.execute("SELECT COUNT(*) FROM edit_log").fetchone()[0] == 0
    conn.close()


def test_release_while_the_collector_writes_says_so(world):
    path, ids = world
    client = _client(path, WRITE_TIMEOUT=0.2)
    url = f"/project/{ids['gym']}"
    _post(client, f"{url}/edit/verdict", {"verdict": BUILDING, "reason": "현장 확인"})
    blocker = sqlite3.connect(path)
    blocker.execute("BEGIN IMMEDIATE")
    try:
        resp = _post(client, f"{url}/release", {})
    finally:
        blocker.rollback()
        blocker.close()
    assert resp.status_code == 503
    assert "수집이 DB를 쓰고 있습니다" in _text(resp)


def test_release_does_not_claim_success_when_nothing_was_locked(world):
    path, ids = world
    client = _client(path)
    resp = _post(client, f"/project/{ids['gym']}/release", {})
    assert "released" not in resp.headers["Location"]


def test_every_page_asks_for_login_first(world):
    path, ids = world
    client = _app(path).test_client()
    for url in ("/", f"/project/{ids['gym']}"):
        resp = client.get(url)
        assert resp.status_code == 302
        assert resp.headers["Location"].startswith("/login")
    post = client.post(f"/project/{ids['gym']}/edit/info", data={}, headers=ORIGIN)
    assert post.status_code == 302


def test_login_failures_share_one_message(world):
    path, _ = world
    _ensure_user(path)
    client = _app(path).test_client()
    for email, password in ((TEST_EMAIL, "wrong one"), ("nobody@example.com", TEST_PASSWORD)):
        resp = client.post("/login", data={"email": email, "password": password}, headers=ORIGIN)
        assert resp.status_code == 401
        assert BAD_LOGIN in _text(resp)


def test_login_locks_after_five_failures(world):
    path, _ = world
    _ensure_user(path)
    client = _app(path).test_client()
    for _ in range(5):
        client.post("/login", data={"email": TEST_EMAIL, "password": "x"}, headers=ORIGIN)
    assert LOCKED in _text(_login(client, path))


def test_login_goes_back_to_the_page_only_inside_this_site(world):
    """로그인 화면이 남의 사이트로 튕기는 발판이 되면 안 된다."""
    path, ids = world
    _ensure_user(path)
    inside = f"/project/{ids['gym']}"
    for nxt, expected in (
        (inside, inside),
        ("//evil.example", "/"),
        ("https://evil.example", "/"),
        ("/\\evil.example", "/"),
    ):
        client = _app(path).test_client()
        resp = client.post(
            "/login",
            data={"email": TEST_EMAIL, "password": TEST_PASSWORD, "next": nxt},
            headers=ORIGIN,
        )
        assert resp.headers["Location"] == expected, nxt


def test_a_temporary_password_must_be_changed_first(world):
    path, _ = world
    conn = connect(path)
    temp = add_user(conn, "new@example.com", "신입", NOW)
    conn.close()
    client = _app(path).test_client()
    client.post("/login", data={"email": "new@example.com", "password": temp}, headers=ORIGIN)
    assert client.get("/").headers["Location"] == "/password"
    resp = client.post(
        "/password",
        data={"current": temp, "new": "brand new pass", "confirm": "brand new pass"},
        headers=ORIGIN,
    )
    assert resp.status_code == 302
    assert client.get("/").status_code == 200


def test_password_form_explains_a_mismatch(world):
    path, _ = world
    client = _client(path)
    resp = client.post(
        "/password",
        data={"current": TEST_PASSWORD, "new": "long enough 1", "confirm": "long enough 2"},
        headers=ORIGIN,
    )
    assert resp.status_code == 422
    assert "새 비밀번호 두 칸이 다릅니다" in _text(resp)


def test_logout_ends_the_session(world):
    path, _ = world
    client = _client(path)
    assert client.get("/").status_code == 200
    assert "시험" in _text(client.get("/"))
    client.post("/logout", headers=ORIGIN)
    assert client.get("/").status_code == 302


def test_a_disabled_account_loses_its_session(world):
    path, _ = world
    client = _client(path)
    conn = connect(path)
    conn.execute("UPDATE app_user SET active = 0")
    conn.commit()
    conn.close()
    assert client.get("/").status_code == 302


def test_the_app_refuses_to_start_without_a_secret_key(world):
    with pytest.raises(ValueError, match="NARA_SECRET_KEY"):
        create_app(world[0], secret_key="")


def test_behind_caddy_https_origin_is_accepted(world):
    """Caddy 뒤에서는 요청이 http로 들어온다. https Origin과 어긋나면 모든 저장이 403이 된다."""
    path, _ = world
    _ensure_user(path)
    app = create_app(path, secret_key=SECRET, host="nara.example.org")
    app.testing = True
    client = app.test_client()
    resp = client.post(
        "/login",
        data={"email": TEST_EMAIL, "password": TEST_PASSWORD},
        headers={
            "Host": "nara.example.org",
            "Origin": "https://nara.example.org",
            "X-Forwarded-Proto": "https",
        },
    )
    assert resp.status_code == 302
    assert "Secure" in resp.headers["Set-Cookie"]


def _tester_id(path):
    conn = connect(path)
    uid = conn.execute("SELECT id FROM app_user WHERE email = ?", (TEST_EMAIL,)).fetchone()[0]
    conn.close()
    return uid


def test_every_web_change_records_who_made_it(world):
    path, ids = world
    client = _client(path)
    url = f"/project/{ids['gym']}"
    _post(client, f"/project/{ids['culture']}/edit/info", _info(floor_area="500"))
    _post(client, f"{url}/edit/verdict", {"verdict": BUILDING, "reason": "현장 확인"})
    _post(client, f"{url}/release", {})
    conn = connect(path)
    rows = conn.execute("SELECT field, user_id FROM edit_log ORDER BY id").fetchall()
    conn.close()
    uid = _tester_id(path)
    assert [tuple(r) for r in rows] == [
        ("floor_area", uid),
        ("verdict", uid),
        ("verdict_release", uid),
    ]


def test_edit_history_shows_names_and_marks_older_records(world):
    path, ids = world
    client = _client(path)
    conn = connect(path)
    conn.execute(
        "INSERT INTO edit_log (project_id, field, old_value, new_value, edited_at) "
        "VALUES (?, 'note', NULL, '옛 기록', '2026-09-27T09:00:00')",
        (ids["culture"],),
    )
    conn.commit()
    conn.close()
    _post(client, f"/project/{ids['culture']}/edit/info", _info(floor_area="500"))
    text = _text(client.get(f"/project/{ids['culture']}"))
    assert "시험" in text
    assert "(2단계 기록)" in text


def _version(client, project_id, section):
    page = _text(client.get(f"/project/{project_id}?edit={section}"))
    return re.search(r'name="version" value="([0-9a-f]+)"', page).group(1)


def test_a_second_save_on_a_stale_form_is_refused(world):
    """두 사람이 같은 묶음을 연 뒤 차례로 저장하면 나중 사람의 저장이 조용히 덮으면 안 된다."""
    path, ids = world
    pid = ids["culture"]
    first = _client(path)
    _ensure_user(path, email="peer@example.com", name="동료")
    second = _app(path).test_client()
    _login(second, path, email="peer@example.com")
    stale = _version(first, pid, "info")
    fresh = _version(second, pid, "info")
    ok = _post(second, f"/project/{pid}/edit/info", {**_info(floor_area="100"), "version": fresh})
    assert ok.status_code == 302
    resp = _post(first, f"/project/{pid}/edit/info", {**_info(floor_area="200"), "version": stale})
    assert resp.status_code == 409
    text = _text(resp)
    assert "그사이 동료님이 고쳤습니다" in text
    assert 'value="200"' in text
    conn = connect(path)
    assert conn.execute("SELECT floor_area FROM project WHERE id = ?", (pid,)).fetchone()[0] == 100
    conn.close()


def test_a_change_by_collection_is_reported_without_a_name(world):
    path, ids = world
    pid = ids["gym"]
    client = _client(path)
    stale = _version(client, pid, "verdict")
    _verdict_conn = connect(path)
    _verdict(_verdict_conn, pid, BUILDING, when="2026-09-29T09:00:00", decided_by="news")
    _verdict_conn.commit()
    _verdict_conn.close()
    resp = _post(
        client,
        f"/project/{pid}/edit/verdict",
        {"verdict": DONE, "reason": "준공식", "version": stale},
    )
    assert resp.status_code == 409
    assert "그사이 값이 바뀌었습니다" in _text(resp)


def test_a_fresh_version_saves_normally(world):
    path, ids = world
    pid = ids["gym"]
    client = _client(path)
    version = _version(client, pid, "energy")
    resp = client.post(
        f"/project/{pid}/edit/energy",
        data={"source": ["PV"], "capacity": ["20"], "version": version},
        headers=ORIGIN,
    )
    assert resp.status_code == 302


def test_serve_refuses_to_start_without_a_secret_key(world, tmp_path):
    env = tmp_path / "empty.env"
    env.write_text("", encoding="utf-8")
    result = CliRunner().invoke(cli_app, ["serve", "--db", str(world[0]), "--env", str(env)])
    assert result.exit_code == 1
    assert "NARA_SECRET_KEY" in result.output


def test_serve_production_uses_waitress_on_this_computer_only(world, tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr("nara.cli.waitress_serve", lambda app, **kw: seen.update(kw))
    env = _env_file(tmp_path, NARA_HOST="nara.example.org")
    result = CliRunner().invoke(
        cli_app,
        ["serve", "--db", str(world[0]), "--env", str(env), "--production", "--port", "8000"],
    )
    assert result.exit_code == 0, result.output
    assert (seen["host"], seen["port"]) == ("127.0.0.1", 8000)


def test_deploy_files_hold_no_secret_values():
    """저장소는 공개다. 배포 파일에는 이름만 있고 값은 없다."""
    root = Path(__file__).resolve().parents[1] / "deploy"
    text = "\n".join(p.read_text(encoding="utf-8") for p in root.iterdir() if p.is_file())
    for name in ("G2B_API_KEY", "ANTHROPIC_API_KEY", "NARA_SECRET_KEY"):
        # 값처럼 생긴 글자(8자 이상 영숫자)만 잡는다. 만드는 명령 안의 이름은 괜찮다.
        assert not re.search(rf"{name}\s*=\s*[A-Za-z0-9_\-]{{8,}}", text), name


def test_the_version_is_compared_inside_the_write_lock(world, monkeypatch):
    """비교와 저장 사이에 다른 사람이 끼면 나중 저장이 조용히 덮는다.

    쓰기 잠금 안에서 비교해야 한다.
    """
    path, ids = world
    client = _client(path)
    version = _version(client, ids["culture"], "info")
    seen = []
    real = edit.version_of

    def spy(conn, project_id, section):
        seen.append(conn.in_transaction)
        return real(conn, project_id, section)

    monkeypatch.setattr(edit, "version_of", spy)
    _post(
        client,
        f"/project/{ids['culture']}/edit/info",
        {**_info(floor_area="5"), "version": version},
    )
    assert seen[-1] is True


LAN_IP = "192.168.0.10"


def test_serve_lan_opens_to_the_office_network_and_shows_the_address(world, tmp_path, monkeypatch):
    """사내망 공유: 다른 PC가 들어올 수 있게 열고, 알려 줄 주소를 보인다."""
    seen = {}
    monkeypatch.setattr("nara.cli.waitress_serve", lambda app, **kw: seen.update(kw, app=app))
    monkeypatch.setattr("nara.cli._lan_addresses", lambda: (LAN_IP, ["my-pc", LAN_IP]))
    env = str(_env_file(tmp_path))
    result = CliRunner().invoke(
        cli_app, ["serve", "--db", str(world[0]), "--env", env, "--lan", "--port", "8000"]
    )
    assert result.exit_code == 0, result.output
    assert (seen["host"], seen["port"]) == ("0.0.0.0", 8000)
    assert f"http://{LAN_IP}:8000" in result.output
    assert set(seen["app"].config["TRUSTED_HOSTS"]) >= {"my-pc", LAN_IP}


def _lan_client(path):
    _ensure_user(path)
    app = create_app(path, secret_key=SECRET, lan_hosts=["my-pc", LAN_IP])
    app.testing = True
    return app.test_client()


def test_a_colleague_can_log_in_over_the_office_network(world):
    """사내망은 http다. 쿠키에 Secure가 붙으면 브라우저가 쿠키를 버려 로그인이 안 된다."""
    path, _ = world
    client = _lan_client(path)
    lan = {"Host": f"{LAN_IP}:8000", "Origin": f"http://{LAN_IP}:8000"}
    resp = client.post("/login", data={"email": TEST_EMAIL, "password": TEST_PASSWORD}, headers=lan)
    assert resp.status_code == 302
    assert "Secure" not in resp.headers["Set-Cookie"]
    assert client.get("/", headers={"Host": f"{LAN_IP}:8000"}).status_code == 200


def test_the_office_network_mode_still_refuses_other_host_names(world):
    """DNS 리바인딩 방어는 사내망 공유에서도 그대로다."""
    client = _lan_client(world[0])
    assert client.get("/login", headers={"Host": "evil.example"}).status_code == 400


def test_a_candidate_is_never_shown_as_the_department(world):
    """자동 조회가 남긴 후보가 확정값처럼 목록에 뜨면 안 된다."""
    path, ids = world
    conn = connect(path)
    _dept(conn, ids["gym"], "건축과", "2026-09-01T09:00:00")
    _dept(conn, ids["gym"], "문화관광과", "2026-09-28T09:00:00", "rule", confirmed=0)
    _dept(conn, ids["culture"], "도시재생과", "2026-09-28T09:00:00", "rule", confirmed=0)
    conn.commit()
    conn.close()
    rows = {r["id"]: r for r in _list(path).rows}
    assert rows[ids["gym"]]["exec_dept"] == "건축과"
    assert rows[ids["culture"]]["exec_dept"] is None


def test_a_new_candidate_does_not_block_a_save_in_progress(world):
    """폼을 연 사이 자동 조회가 후보를 남겨도 확정값은 그대로라 저장이 막히면 안 된다."""
    path, ids = world
    client = _client(path)
    version = _version(client, ids["gym"], "dept")
    conn = connect(path)
    _dept(conn, ids["gym"], "문화관광과", "2026-09-28T09:00:00", "rule", confirmed=0)
    conn.commit()
    conn.close()
    resp = client.post(
        f"/project/{ids['gym']}/edit/dept",
        data={"exec_dept": "건축과", "snippet": "", "version": version},
        headers=ORIGIN,
    )
    assert resp.status_code == 302


def test_a_project_with_only_candidates_is_marked_for_review(world):
    path, ids = world
    conn = connect(path)
    _dept(conn, ids["culture"], "도시재생과", "2026-09-28T09:00:00", "rule", confirmed=0)
    _dept(conn, ids["gym"], "건축과", "2026-09-01T09:00:00")
    _dept(conn, ids["gym"], "문화관광과", "2026-09-28T09:00:00", "rule", confirmed=0)
    conn.commit()
    conn.close()
    client = _client(path)
    rows = {r["id"]: r for r in _list(path).rows}
    assert rows[ids["culture"]]["dept_review"] and not rows[ids["gym"]]["dept_review"]
    only = _list(path, dept_review=True).rows
    assert [r["id"] for r in only] == [ids["culture"]]
    text = _text(client.get("/?dept=review"))
    assert "검토 필요" in text and "실행부서 검토 필요" in text


def test_detail_shows_candidates_with_their_source_and_reason(world):
    path, ids = world
    conn = connect(path)
    conn.execute(
        "INSERT INTO dept_check (project_id, exec_dept, snippet, source_file, decided_by, "
        "confirmed, note, checked_at) VALUES (?, '도시재생과', '설계서 열람 문의: 도시재생과', "
        "'N6/1_공고문.hwpx', 'rule', 0, '규칙 후보', '2026-09-28T09:00:00')",
        (ids["culture"],),
    )
    conn.execute(
        "INSERT INTO dept_check (project_id, decided_by, confirmed, note, checked_at) "
        "VALUES (?, 'rule', 0, '첨부 없음', '2026-09-27T09:00:00')",
        (ids["culture"],),
    )
    conn.commit()
    conn.close()
    text = _text(_client(path).get(f"/project/{ids['culture']}"))
    for expected in ("도시재생과", "후보", "규칙", "N6/1_공고문.hwpx", "규칙 후보", "첨부 없음"):
        assert expected in text


def _attachment(path, rel, filename="공고문.pdf", body=b"%PDF-1.4 test"):
    root = path.parent / "attachments"
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(body)
    conn = connect(path)
    cur = conn.execute(
        "INSERT INTO attachment (bid_no, seq, filename, path, status, attempts, downloaded_at) "
        "VALUES ('N6', 1, ?, ?, 'ok', 1, '2026-09-28T09:00:00')",
        (filename, rel),
    )
    conn.commit()
    conn.close()
    return cur.lastrowid


def test_a_saved_attachment_is_listed_and_downloads(world):
    path, ids = world
    aid = _attachment(path, "N6/1_공고문.pdf")
    client = _client(path)
    assert "공고문.pdf" in _text(client.get(f"/project/{ids['culture']}"))
    resp = client.get(f"/attachment/{aid}")
    assert resp.status_code == 200
    assert resp.data == b"%PDF-1.4 test"
    assert "attachment" in resp.headers["Content-Disposition"]


def test_attachment_download_needs_login(world):
    path, _ = world
    aid = _attachment(path, "N6/1_공고문.pdf")
    assert _app(path).test_client().get(f"/attachment/{aid}").status_code == 302


def test_attachment_download_never_leaves_the_folder(world):
    """DB에 적힌 경로가 폴더 밖을 가리켜도 내주면 안 된다."""
    path, _ = world
    aid = _attachment(path, "N6/1_공고문.pdf")
    conn = connect(path)
    conn.execute("UPDATE attachment SET path = '../w.db' WHERE id = ?", (aid,))
    conn.commit()
    conn.close()
    client = _client(path)
    assert client.get(f"/attachment/{aid}").status_code == 404
    assert client.get("/attachment/999999").status_code == 404
