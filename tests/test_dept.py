"""실행부서 조회 흐름 — 받기·읽기·판정·기록, 다시 볼 때와 멈출 때."""

import io
import json
import sqlite3
import zipfile

import httpx
import pytest
from typer.testing import CliRunner

from nara import cli
from nara.config import Secrets
from nara.db import connect, migrate
from nara.dept import (
    NOTE_DOWNLOAD_FAILED,
    NOTE_LLM_UNVERIFIED,
    NOTE_MANUAL,
    NOTE_NO_FILES,
    NOTE_RULE_CANDIDATE,
    DeptRun,
    pending_dept_projects,
    update_depts,
)
from nara.dept_rules import DeptAnswer, StaffContact
from nara.g2b.attach import probe_url
from nara.runlog import RunCounters

NOW = "2026-09-30T09:00:00"
KEYED = Secrets(
    g2b_api_key="g", naver_client_id=None, naver_client_secret=None, anthropic_api_key="k"
)
KEYLESS = Secrets(
    g2b_api_key="g", naver_client_id=None, naver_client_secret=None, anthropic_api_key=None
)
ONE = "나. 사업관련 문의: 문화관광과 관광팀 (063-000-0001)\n가. 계약관련 문의: 재무과"
TWO = "사업관련 문의: 건축과\n설계서 열람 문의: 도시재생과\n계약관련 문의: 재무과"


def _hwpx(text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        paras = "".join(f"<hp:p><hp:t>{line}</hp:t></hp:p>" for line in text.split("\n"))
        z.writestr("Contents/section0.xml", paras)
    return buf.getvalue()


def _raw(bid_no, name="공고문.hwpx"):
    raw = {f"ntceSpecFileNm{i}": "" for i in range(1, 11)}
    raw |= {f"ntceSpecDocUrl{i}": "" for i in range(1, 11)}
    raw["ntceSpecFileNm1"], raw["ntceSpecDocUrl1"] = name, probe_url(bid_no, "000", 1)
    return json.dumps(raw, ensure_ascii=False)


@pytest.fixture
def db(tmp_path):
    conn = connect(tmp_path / "n.db")
    migrate(conn)
    conn.execute(
        "INSERT INTO org (id, name, tier, weekday_group, added_at) "
        "VALUES (1, '관심군', 'focus', NULL, ?), (2, '비관심시', 'rest', 3, ?)",
        (NOW, NOW),
    )
    conn.commit()
    return conn


def _project(conn, pid, org_id=1, bid_no=None, notice_date="2026-09-01", raw=True):
    conn.execute(
        "INSERT INTO project (id, org_id, name, source, created_at, updated_at) "
        "VALUES (?, ?, ?, 'g2b', ?, ?)",
        (pid, org_id, f"사업{pid}", NOW, NOW),
    )
    if bid_no:
        _notice(conn, pid, org_id, bid_no, notice_date, raw)
    conn.commit()


def _notice(conn, pid, org_id, bid_no, notice_date, raw=True):
    conn.execute(
        "INSERT INTO notice (bid_no, bid_ord, project_id, org_id, org_name, title, notice_date, "
        "raw_json, collected_at) VALUES (?, '000', ?, ?, '기관', '공고', ?, ?, ?)",
        (bid_no, pid, org_id, notice_date, _raw(bid_no) if raw else None, NOW),
    )
    conn.commit()


def _server(
    texts: dict[str, str],
    fail: set[str] = frozenset(),
    calls: list | None = None,
    broken: set[str] = frozenset(),
):
    """공고번호별 공고문. fail은 연결 불가, broken은 나라장터가 500을 준다."""

    def handler(request: httpx.Request) -> httpx.Response:
        bid_no = request.url.params["bidPbancNo"]
        seq = int(request.url.params["fileSeq"])
        if calls is not None:
            calls.append((bid_no, seq))
        if bid_no in fail:
            raise httpx.ConnectError("down")
        if bid_no in broken:
            return httpx.Response(500)
        if seq == 1 and bid_no in texts:
            return httpx.Response(
                200,
                headers={
                    "content-disposition": "attachment;filename=%EA%B3%B5%EA%B3%A0%EB%AC%B8.hwpx"
                },
                content=_hwpx(texts[bid_no]),
            )
        return httpx.Response(422, json={"ErrorMsg": "없음"})

    return httpx.Client(transport=httpx.MockTransport(handler))


def _run(conn, root, client, secrets=KEYLESS, asker=None, **kw):
    counters = RunCounters()
    run = update_depts(
        conn,
        client,
        secrets,
        root,
        kw.pop("tier", None),
        kw.pop("group", None),
        kw.pop("limit", 300),
        counters,
        asker=asker or (lambda s, e: None),
        sleep=lambda s: None,
        **kw,
    )
    return run, counters


def _rows(conn, pid):
    return [
        dict(r)
        for r in conn.execute(
            "SELECT exec_dept, contract_dept, decided_by, confirmed, note, source_file, bid_no "
            "FROM dept_check WHERE project_id = ? ORDER BY id",
            (pid,),
        )
    ]


def test_one_clear_candidate_is_confirmed_by_rule_and_the_file_is_kept(db, tmp_path):
    root = tmp_path / "attachments"
    _project(db, 1, bid_no="B1")
    run, counters = _run(db, root, _server({"B1": ONE}))
    [row] = _rows(db, 1)
    assert (row["exec_dept"], row["contract_dept"], row["decided_by"], row["confirmed"]) == (
        "문화관광과",
        "재무과",
        "rule",
        1,
    )
    assert row["source_file"] == "B1/1_공고문.hwpx"
    assert (root / "B1" / "1_공고문.hwpx").is_file()
    assert "문화관광과" in (root / "B1" / "1_공고문.hwpx.txt").read_text(encoding="utf-8")
    assert (run.confirmed_rule, counters.updated) == (1, 1)


def test_a_verified_claude_answer_is_confirmed(db, tmp_path):
    _project(db, 1, bid_no="B1")
    asker = lambda s, e: DeptAnswer("도시재생과", "재무과", "설계서 열람 문의: 도시재생과")  # noqa: E731
    run, _ = _run(db, tmp_path / "a", _server({"B1": TWO}), KEYED, asker)
    [row] = _rows(db, 1)
    assert (row["exec_dept"], row["decided_by"], row["confirmed"]) == ("도시재생과", "llm", 1)
    assert run.confirmed_llm == 1


def test_an_unverified_answer_leaves_candidates_for_review(db, tmp_path):
    _project(db, 1, bid_no="B1")
    asker = lambda s, e: DeptAnswer("문화예술과", None, "문화예술과에서 담당합니다")  # noqa: E731
    run, _ = _run(db, tmp_path / "a", _server({"B1": TWO}), KEYED, asker)
    rows = _rows(db, 1)
    assert all(r["confirmed"] == 0 for r in rows)
    assert {(r["exec_dept"], r["note"]) for r in rows} == {
        ("문화예술과", NOTE_LLM_UNVERIFIED),
        ("건축과", NOTE_RULE_CANDIDATE),
        ("도시재생과", NOTE_RULE_CANDIDATE),
    }
    assert run.review == 1


def test_without_a_key_rule_candidates_wait_for_review(db, tmp_path):
    _project(db, 1, bid_no="B1")
    run, _ = _run(db, tmp_path / "a", _server({"B1": TWO}))
    assert sorted(r["exec_dept"] for r in _rows(db, 1)) == ["건축과", "도시재생과"]
    assert (run.review, run.asked_llm) == (1, 0)


def test_nothing_found_is_recorded_with_a_reason(db, tmp_path):
    _project(db, 1, bid_no="B1")
    _project(db, 2, bid_no="B2", raw=False)  # 원본 없음 + 서버에 파일 없음 = 첨부 없음
    _run(db, tmp_path / "a", _server({"B1": "계약관련 문의: 재무과"}))
    # 키 없이 못 찾은 건도 키가 생기면 Claude에 다시 묻는다
    assert _rows(db, 1)[0]["note"] == "공고문에 계약부서만 있음 · Claude 확인 전"
    assert _rows(db, 1)[0]["exec_dept"] is None
    assert _rows(db, 2)[0]["note"] == NOTE_NO_FILES


def test_old_notices_without_raw_data_are_probed(db, tmp_path):
    _project(db, 1, bid_no="B1", raw=False)
    calls: list = []
    _run(db, tmp_path / "a", _server({"B1": ONE}, calls=calls))
    assert _rows(db, 1)[0]["exec_dept"] == "문화관광과"
    assert calls == [("B1", 1), ("B1", 2), ("B1", 1)]  # 이름 확인 1·2, 받기 1


def test_confirmed_departments_are_left_alone(db, tmp_path):
    _project(db, 1, bid_no="B1")
    _project(db, 2, bid_no="B2")
    db.execute(
        "INSERT INTO dept_check (project_id, exec_dept, decided_by, checked_at) "
        "VALUES (1, '건축과', 'imported', ?), (2, '행정과', 'human', ?)",
        (NOW, NOW),
    )
    db.commit()
    calls: list = []
    run, _ = _run(db, tmp_path / "a", _server({"B1": ONE, "B2": ONE}, calls=calls))
    assert run.checked == 0 and calls == []


def test_a_project_is_looked_up_again_only_when_a_newer_notice_arrives(db, tmp_path):
    """수집이 최근 공고를 날마다 다시 받아 수집 시각이 바뀌어도 다시 받지 않는다."""
    _project(db, 1, bid_no="B1")
    server = _server({"B1": TWO, "B2": ONE})
    _run(db, tmp_path / "a", server)
    db.execute("UPDATE notice SET collected_at = '2026-10-01T09:00:00'")
    db.commit()
    assert pending_dept_projects(db, None, None, 300) == []
    _notice(db, 1, 1, "B2", "2026-09-20")  # 재공고
    run, _ = _run(db, tmp_path / "a", server)
    assert run.checked == 1
    assert _rows(db, 1)[-1]["exec_dept"] == "문화관광과"


def test_download_failures_are_retried_then_left_for_a_person(db, tmp_path):
    _project(db, 1, bid_no="B1")
    down = _server({}, broken={"B1"})
    for _ in range(3):
        run, counters = _run(db, tmp_path / "a", down)
        assert run.failed == 1 and counters.failed == 1
    notes = [r["note"] for r in _rows(db, 1)]
    assert notes == [NOTE_DOWNLOAD_FAILED, NOTE_DOWNLOAD_FAILED, NOTE_MANUAL]
    assert pending_dept_projects(db, None, None, 300) == []


def test_a_network_outage_does_not_use_up_the_retries(db, tmp_path):
    """PC가 하루 오프라인이어도 사업이 '수동 확인'으로 빠지지 않는다.

    연결 실패는 공고 탓이 아니다.
    """
    _project(db, 1, bid_no="B1")
    down = _server({}, fail={"B1"})
    for _ in range(3):
        run, counters = _run(db, tmp_path / "a", down)
        assert run.failed == 1 and counters.failed == 1
    assert NOTE_MANUAL not in [r["note"] for r in _rows(db, 1)]
    assert [r["id"] for r in pending_dept_projects(db, None, None, 300)] == [1]


def test_an_error_page_on_an_old_notice_is_a_download_failure(db, tmp_path):
    """옛 공고의 첫 순번이 오류면 '첨부 없음'이 아니다 — 그렇게 적으면 다시 보지 않는다."""
    _project(db, 1, bid_no="B1", raw=False)
    _run(db, tmp_path / "a", _server({}, broken={"B1"}))
    assert _rows(db, 1)[0]["note"] == NOTE_DOWNLOAD_FAILED


def test_projects_left_without_claude_are_asked_once_a_key_arrives(db, tmp_path):
    """키 없이 돈 사업은 후보로 남는다. 키를 넣으면 받아 둔 첨부로 다시 묻는다."""
    root = tmp_path / "a"
    _project(db, 1, bid_no="B1")
    calls: list = []
    server = _server({"B1": TWO}, calls=calls)
    _run(db, root, server)
    assert pending_dept_projects(db, None, None, 300) == []
    assert [r["id"] for r in pending_dept_projects(db, None, None, 300, can_ask=True)] == [1]
    asker = lambda s, e: DeptAnswer("도시재생과", None, "설계서 열람 문의: 도시재생과")  # noqa: E731
    run, _ = _run(db, root, server, KEYED, asker)
    assert run.confirmed_llm == 1
    assert calls == [("B1", 1)]  # 첨부는 다시 받지 않았다
    assert pending_dept_projects(db, None, None, 300, can_ask=True) == []


def test_an_unanswered_claude_call_is_asked_again(db, tmp_path):
    """400·429·시간 초과로 답을 못 받은 건은 영영 후보로 남지 않는다."""
    _project(db, 1, bid_no="B1")
    run, _ = _run(db, tmp_path / "a", _server({"B1": TWO}), KEYED, lambda s, e: None)
    assert (run.asked_llm, run.llm_unanswered) == (1, 1)
    assert [r["id"] for r in pending_dept_projects(db, None, None, 300, can_ask=True)] == [1]


def test_a_claude_answer_that_fails_the_check_is_not_asked_again(db, tmp_path):
    _project(db, 1, bid_no="B1")
    asker = lambda s, e: DeptAnswer("문화예술과", None, "문화예술과에서 담당합니다")  # noqa: E731
    _run(db, tmp_path / "a", _server({"B1": TWO}), KEYED, asker)
    assert pending_dept_projects(db, None, None, 300, can_ask=True) == []


def test_the_database_is_free_while_claude_is_thinking(db, tmp_path):
    """Claude 호출은 30초를 넘길 수 있다. 그동안 웹 저장이 잠금에 막히면 안 된다."""
    _project(db, 1, bid_no="B1")
    free = []

    def asker(secrets, excerpt):
        other = sqlite3.connect(tmp_path / "n.db", timeout=0)
        try:
            other.execute("BEGIN IMMEDIATE")
            other.rollback()
            free.append(True)
        except sqlite3.OperationalError:
            free.append(False)
        finally:
            other.close()
        return None

    _run(db, tmp_path / "a", _server({"B1": TWO}), KEYED, asker)
    assert free == [True]


def test_saved_files_are_read_again_without_downloading(db, tmp_path):
    root = tmp_path / "a"
    _project(db, 1, bid_no="B1")
    (root / "B1").mkdir(parents=True)
    (root / "B1" / "1_공고문.hwpx").write_bytes(b"x")
    (root / "B1" / "1_공고문.hwpx.txt").write_text(ONE, encoding="utf-8")
    db.execute(
        "INSERT INTO attachment (bid_no, seq, filename, path, text_path, status, attempts, "
        "downloaded_at) VALUES ('B1', 1, '공고문.hwpx', 'B1/1_공고문.hwpx', "
        "'B1/1_공고문.hwpx.txt', 'ok', 1, ?)",
        (NOW,),
    )
    db.commit()
    calls: list = []
    _run(db, root, _server({}, calls=calls))
    assert calls == []
    assert _rows(db, 1)[0]["exec_dept"] == "문화관광과"


def test_tier_and_group_select_the_projects(db, tmp_path):
    _project(db, 1, org_id=1, bid_no="B1")
    _project(db, 2, org_id=2, bid_no="B2")
    assert [r["id"] for r in pending_dept_projects(db, "rest", 3, 300)] == [2]
    assert [r["id"] for r in pending_dept_projects(db, "focus", None, 300)] == [1]
    assert pending_dept_projects(db, "rest", 4, 300) == []


def test_the_time_budget_stops_the_run(db, tmp_path):
    for pid in (1, 2, 3):
        _project(db, pid, bid_no=f"B{pid}")
    ticks = iter([0, 0, 100, 2000, 2000, 2000])
    run, _ = _run(db, tmp_path / "a", _server({}), budget_seconds=1200, now_fn=lambda: next(ticks))
    assert run.stopped_early and run.checked == 2


def test_enrich_dept_command_reports_and_logs(tmp_path, monkeypatch):
    db_path = tmp_path / "data" / "n.db"
    conn = connect(db_path)
    migrate(conn)
    conn.close()
    seen = {}

    def fake(conn, client, secrets, root, tier, group, limit, counters, asker, budget_seconds):
        seen.update(root=root, tier=tier, group=group, budget=budget_seconds)
        counters.processed = 3
        return DeptRun(checked=3, confirmed_rule=1, confirmed_llm=1, review=1)

    monkeypatch.setattr(cli, "update_depts", fake)
    result = CliRunner().invoke(
        cli.app, ["enrich", "dept", "--tier", "rest", "--group", "2", "--db", str(db_path)]
    )
    assert result.exit_code == 0, result.output
    assert "실행부서 — 조회 3건 / 확정 규칙 1·Claude 1 / 검토 필요 1 / 못 찾음 0 / 실패 0" in (
        result.output
    )
    assert seen == {
        "root": tmp_path / "data" / "attachments",
        "tier": "rest",
        "group": 2,
        "budget": 1200,
    }
    conn = connect(db_path)
    assert (
        conn.execute("SELECT status FROM run_log WHERE command = 'enrich dept'").fetchone()[0]
        == "ok"
    )


def test_enrich_dept_reports_claude_calls_and_warns_when_none_answer(tmp_path, monkeypatch):
    """키를 처음 넣은 날 요청 모양이 틀려 전부 400이면, 그 사실이 요약에 보여야 한다."""
    db_path = tmp_path / "n.db"
    conn = connect(db_path)
    migrate(conn)
    conn.close()

    def fake(conn, client, secrets, root, tier, group, limit, counters, asker, budget_seconds):
        counters.processed = 2
        return DeptRun(checked=2, review=2, asked_llm=2, llm_unanswered=2)

    monkeypatch.setattr(cli, "update_depts", fake)
    result = CliRunner().invoke(cli.app, ["enrich", "dept", "--db", str(db_path)])
    assert result.exit_code == 0, result.output
    assert "Claude에 물은 건 2건 중 답을 못 받은 건 2건" in result.output


def test_enrich_dept_refuses_an_unknown_tier(tmp_path):
    result = CliRunner().invoke(
        cli.app, ["enrich", "dept", "--tier", "x", "--db", str(tmp_path / "n.db")]
    )
    assert result.exit_code == 1


def test_hidden_projects_are_not_looked_up(db):
    """숨긴 사업은 첨부를 받지 않는다. 숨김을 풀면 다시 대상이 된다."""
    _project(db, 1, bid_no="B1")
    _project(db, 2, bid_no="B2")
    db.execute("UPDATE project SET hidden_at = ? WHERE id = 2", (NOW,))
    db.commit()
    assert [r["id"] for r in pending_dept_projects(db, None, None, 300)] == [1]
    db.execute("UPDATE project SET hidden_at = NULL WHERE id = 2")
    db.commit()
    assert [r["id"] for r in pending_dept_projects(db, None, None, 300)] == [1, 2]


def _contact(conn, org_id, dept):
    row = conn.execute(
        "SELECT staff_name, staff_position, staff_tel, auto_fields, updated_by "
        "FROM dept_contact WHERE org_id = ? AND dept = ?",
        (org_id, dept),
    ).fetchone()
    return tuple(row) if row else None


def test_a_rule_confirmed_department_fills_the_staff_number_from_the_notice(db, tmp_path):
    _project(db, 1, bid_no="B1")
    run, _ = _run(db, tmp_path / "a", _server({"B1": ONE}))
    assert _contact(db, 1, "문화관광과") == (None, None, "063-000-0001", "staff_tel", None)
    assert run.contacts_filled == 1


def test_a_claude_confirmed_department_fills_only_verified_staff(db, tmp_path):
    _project(db, 1, bid_no="B1")
    text = TWO + "\n도시재생과 박영희 주무관 ☎ 063-000-0002"
    answer = DeptAnswer(
        "도시재생과", "재무과", "설계서 열람 문의: 도시재생과",
        staff=StaffContact("박영희", "과장", "063-000-9999"),
    )  # fmt: skip
    run, _ = _run(db, tmp_path / "a", _server({"B1": text}), KEYED, lambda s, e: answer)
    # 규칙이 먼저 읽고(이름·직위·번호 모두 원문에 있음), Claude의 틀린 직위·번호는 버린다
    assert _contact(db, 1, "도시재생과") == (
        "박영희",
        "주무관",
        "063-000-0002",
        "staff_name,staff_position,staff_tel",
        None,
    )
    assert run.contacts_filled == 1


def test_auto_fill_never_overwrites_a_value_a_person_entered(db, tmp_path):
    db.execute(
        "INSERT INTO dept_contact (org_id, dept, staff_tel, updated_at) "
        "VALUES (1, '문화관광과', '063-000-7777', ?)",
        (NOW,),
    )
    db.commit()
    _project(db, 1, bid_no="B1")
    run, _ = _run(db, tmp_path / "a", _server({"B1": ONE}))
    # auto_fields가 비어 있으면 사람이 넣은 값이다 — 그대로 둔다
    assert _contact(db, 1, "문화관광과") == (None, None, "063-000-7777", None, None)
    assert run.contacts_filled == 0


def _confirm_dept(conn, pid, dept, decided_by="human"):
    conn.execute(
        "INSERT INTO dept_check (project_id, exec_dept, decided_by, confirmed, checked_at) "
        "VALUES (?, ?, ?, 1, ?)",
        (pid, dept, decided_by, NOW),
    )
    conn.commit()


def test_saved_notices_fill_contacts_for_already_confirmed_departments(db, tmp_path):
    from nara.dept import fill_saved_contacts

    _project(db, 1, bid_no="B1")
    _run(db, tmp_path / "a", _server({"B1": ONE}))  # 받아 둔다 + 규칙 확정
    db.execute("DELETE FROM dept_contact")  # 자동 채움 전 상태로
    _project(db, 2, bid_no="B2")  # 사람이 확정한 사업, 첨부 없음
    _confirm_dept(db, 2, "건축과")
    db.commit()
    preview = fill_saved_contacts(db, tmp_path / "a", dry_run=True)
    assert [(p[0], p[1], p[2], p[3]) for p in preview] == [
        ("관심군", "문화관광과", 1, ["staff_tel"])
    ]
    assert db.execute("SELECT COUNT(*) FROM dept_contact").fetchone()[0] == 0
    done = fill_saved_contacts(db, tmp_path / "a", dry_run=False)
    assert len(done) == 1
    assert _contact(db, 1, "문화관광과") == (None, None, "063-000-0001", "staff_tel", None)
    assert fill_saved_contacts(db, tmp_path / "a", dry_run=False) == []  # 이미 찼다


def test_enrich_contacts_command_previews_then_fills(tmp_path, monkeypatch):
    db_path = tmp_path / "data" / "n.db"
    conn = connect(db_path)
    migrate(conn)
    conn.close()
    seen = []

    def fake(conn, root, dry_run):
        seen.append((root, dry_run))
        staff = StaffContact(None, None, "063-000-0001")
        return [("관심군", "문화관광과", 1, ["staff_tel"], staff)]

    monkeypatch.setattr(cli, "fill_saved_contacts", fake)
    result = CliRunner().invoke(cli.app, ["enrich", "contacts", "--dry-run", "--db", str(db_path)])
    assert result.exit_code == 0, result.output
    assert "관심군 문화관광과 #1: staff_tel=063-000-0001" in result.output
    assert "미리보기 1건 — 실제로 채우려면 --dry-run 없이" in result.output
    result = CliRunner().invoke(cli.app, ["enrich", "contacts", "--db", str(db_path)])
    assert "연락처 1건을 채웠습니다" in result.output
    attach = tmp_path / "data" / "attachments"
    assert seen == [(attach, True), (attach, False)]
