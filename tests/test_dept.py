"""실행부서 조회 흐름 — 받기·읽기·판정·기록, 다시 볼 때와 멈출 때."""

import io
import json
import zipfile

import httpx
import pytest

from nara.config import Secrets
from nara.db import connect, migrate
from nara.dept import (
    NOTE_DOWNLOAD_FAILED,
    NOTE_LLM_UNVERIFIED,
    NOTE_MANUAL,
    NOTE_NO_FILES,
    NOTE_RULE_CANDIDATE,
    pending_dept_projects,
    update_depts,
)
from nara.dept_rules import DeptAnswer
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


def _server(texts: dict[str, str], fail: set[str] = frozenset(), calls: list | None = None):
    """공고번호별 공고문. fail에 든 공고번호는 네트워크 오류."""

    def handler(request: httpx.Request) -> httpx.Response:
        bid_no = request.url.params["bidPbancNo"]
        seq = int(request.url.params["fileSeq"])
        if calls is not None:
            calls.append((bid_no, seq))
        if bid_no in fail:
            raise httpx.ConnectError("down")
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
    assert _rows(db, 1)[0]["note"] == "공고문에 계약부서만 있음"
    assert _rows(db, 1)[0]["exec_dept"] is None
    assert _rows(db, 2)[0]["note"] == NOTE_NO_FILES


def test_old_notices_without_raw_data_are_probed(db, tmp_path):
    _project(db, 1, bid_no="B1", raw=False)
    calls: list = []
    _run(db, tmp_path / "a", _server({"B1": ONE}, calls=calls))
    assert _rows(db, 1)[0]["exec_dept"] == "문화관광과"
    assert calls == [("B1", 1), ("B1", 2)]


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
    down = _server({}, fail={"B1"})
    for _ in range(3):
        run, counters = _run(db, tmp_path / "a", down)
        assert run.failed == 1 and counters.failed == 1
    notes = [r["note"] for r in _rows(db, 1)]
    assert notes == [NOTE_DOWNLOAD_FAILED, NOTE_DOWNLOAD_FAILED, NOTE_MANUAL]
    assert pending_dept_projects(db, None, None, 300) == []


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
