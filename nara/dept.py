"""실행부서 조회 흐름. 첨부를 받아 읽고, 규칙과 Claude로 부서를 찾아 기록한다.

확정된 부서(시트·사람·자동 확정)가 있는 사업은 보지 않는다. 한 번 본 사업은
가장 최근 공고번호가 바뀌었거나, 지난번이 다운로드 실패였거나, 지난번에 Claude
답을 받지 못했고 지금은 키가 있을 때만 다시 본다. 수집이 최근 3일 공고를 날마다
다시 받아 collected_at이 바뀌므로 시각이 아니라 공고번호로 비교한다.
"""

import hashlib
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import httpx

from nara.config import Secrets
from nara.dept_rules import (
    Candidate,
    DeptAnswer,
    decide_by_rule,
    excerpt_for_llm,
    find_candidates,
    find_contract_dept,
    squash,
    verify_answer,
)
from nara.doctext import extract_text
from nara.g2b.attach import AttachError, Download, gather, safe_name
from nara.runlog import RunCounters

BUDGET_SECONDS = 1200
MAX_DOWNLOAD_FAILURES = 3
NOTE_RULE_CANDIDATE = "규칙 후보"
NOTE_LLM_UNVERIFIED = "Claude 답이 원문과 맞지 않음"
NOTE_NO_FILES = "첨부 없음"
NOTE_READ_FAILED = "첨부를 읽지 못함"
NOTE_CONTRACT_ONLY = "공고문에 계약부서만 있음"
NOTE_NOT_FOUND = "공고문에서 실행부서를 찾지 못함"
NOTE_DOWNLOAD_FAILED = "다운로드 실패"
NOTE_MANUAL = "수동 확인"
# 키가 없었거나 Claude가 답하지 않은 회차의 사유 끝에 붙는다. 키가 생기면 다시 묻는다.
CLAUDE_PENDING = "Claude 확인 전"
_AUTO = "decided_by IN ('rule', 'llm')"

Asker = Callable[[Secrets, str], DeptAnswer | None]


@dataclass
class DeptRun:
    checked: int = 0
    confirmed_rule: int = 0
    confirmed_llm: int = 0
    review: int = 0
    not_found: int = 0
    failed: int = 0
    asked_llm: int = 0
    llm_unanswered: int = 0
    stopped_early: bool = False


@dataclass(frozen=True)
class _Doc:
    path: str  # 첨부 폴더 기준 경로. dept_check.source_file에 남는다
    text: str


def _newest_bid(conn: sqlite3.Connection, project_id: int) -> str | None:
    row = conn.execute(
        "SELECT bid_no FROM notice WHERE project_id = ? "
        "ORDER BY COALESCE(notice_date, '') DESC, bid_no DESC LIMIT 1",
        (project_id,),
    ).fetchone()
    return row[0] if row else None


def _last_auto(conn: sqlite3.Connection, project_id: int) -> sqlite3.Row | None:
    return conn.execute(
        f"SELECT bid_no, note FROM dept_check WHERE project_id = ? AND {_AUTO} "
        "ORDER BY checked_at DESC, id DESC LIMIT 1",
        (project_id,),
    ).fetchone()


def _due(conn: sqlite3.Connection, project_id: int, can_ask: bool) -> bool:
    newest = _newest_bid(conn, project_id)
    if newest is None:
        return False
    last = _last_auto(conn, project_id)
    if last is None:
        return True
    note = last["note"] or ""
    if can_ask and note.endswith(CLAUDE_PENDING):
        return True
    return last["bid_no"] != newest or note == NOTE_DOWNLOAD_FAILED


def pending_dept_projects(
    conn: sqlite3.Connection,
    tier: str | None,
    group: int | None,
    limit: int,
    can_ask: bool = False,
) -> list[sqlite3.Row]:
    """확정 부서가 없고 다시 볼 이유가 있는 사업. 한 번도 안 본 사업부터."""
    sql = [
        "SELECT p.id, p.name,",
        f"  (SELECT MAX(d.checked_at) FROM dept_check d WHERE d.project_id = p.id AND {_AUTO})",
        "    AS last_auto",
        "FROM project p JOIN org o ON o.id = p.org_id",
        "WHERE p.hidden_at IS NULL",
        "  AND EXISTS (SELECT 1 FROM notice n WHERE n.project_id = p.id)",
        "  AND NOT EXISTS (SELECT 1 FROM dept_check d WHERE d.project_id = p.id",
        "                  AND d.confirmed = 1 AND COALESCE(d.exec_dept, '') != '')",
    ]
    params: list[object] = []
    if tier:
        sql.append("  AND o.tier = ?")
        params.append(tier)
    if group is not None:
        sql.append("  AND o.weekday_group = ?")
        params.append(group)
    sql.append("ORDER BY last_auto IS NOT NULL, last_auto, p.id")
    rows = conn.execute("\n".join(sql), params).fetchall()
    return [row for row in rows if _due(conn, row["id"], can_ask)][:limit]


def _record(
    conn: sqlite3.Connection,
    project_id: int,
    bid_no: str,
    now: str,
    *,
    exec_dept: str | None = None,
    contract_dept: str | None = None,
    snippet: str | None = None,
    source_file: str | None = None,
    decided_by: str = "rule",
    confirmed: int = 0,
    note: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO dept_check (project_id, bid_no, exec_dept, contract_dept, snippet, "
        "source_file, decided_by, confirmed, note, checked_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            project_id,
            bid_no,
            exec_dept,
            contract_dept,
            snippet,
            source_file,
            decided_by,
            confirmed,
            note,
            now,
        ),
    )


def _save(conn: sqlite3.Connection, root: Path, bid_no: str, d: Download, now: str) -> _Doc:
    rel = f"{safe_name(bid_no)}/{d.seq}_{d.name}"
    (root / rel).parent.mkdir(parents=True, exist_ok=True)
    (root / rel).write_bytes(d.content)
    text = extract_text(d.content)
    (root / f"{rel}.txt").write_text(text, encoding="utf-8")
    conn.execute(
        "INSERT INTO attachment (bid_no, seq, filename, path, sha256, text_path, status, "
        "attempts, downloaded_at) VALUES (?, ?, ?, ?, ?, ?, 'ok', 1, ?)",
        (bid_no, d.seq, d.name, rel, hashlib.sha256(d.content).hexdigest(), f"{rel}.txt", now),
    )
    return _Doc(rel, text)


def _documents(
    conn: sqlite3.Connection,
    client: httpx.Client,
    root: Path,
    notice: sqlite3.Row,
    now: str,
    sleep: Callable[[float], None],
) -> list[_Doc]:
    saved = conn.execute(
        "SELECT path, text_path FROM attachment WHERE bid_no = ? AND status = 'ok' ORDER BY seq",
        (notice["bid_no"],),
    ).fetchall()
    if saved:
        return [_Doc(r["path"], (root / r["text_path"]).read_text(encoding="utf-8")) for r in saved]
    downloads = gather(client, notice["bid_no"], notice["bid_ord"], notice["raw_json"], sleep)
    docs = [_save(conn, root, notice["bid_no"], d, now) for d in downloads]
    # 받은 첨부는 그 자체로 유효하다. 곧바로 커밋해 Claude를 기다리는 동안(30초 넘게)
    # 쓰기 잠금을 쥐지 않는다 — 웹 저장은 5초만 기다린다.
    conn.commit()
    return docs


def _recent_failures(conn: sqlite3.Connection, project_id: int, marker: str) -> int:
    notes = conn.execute(
        f"SELECT note FROM dept_check WHERE project_id = ? AND {_AUTO} AND bid_no = ? "
        "ORDER BY checked_at DESC, id DESC",
        (project_id, marker),
    ).fetchall()
    count = 0
    for (note,) in notes:
        if note != NOTE_DOWNLOAD_FAILED:
            break
        count += 1
    return count


def _first_candidates(docs: list[_Doc]) -> tuple[list[Candidate], str | None]:
    """공고문에서 먼저 찾고, 없으면 과업지시서·지침서를 본다."""
    for doc in docs:
        found = find_candidates(doc.text)
        if found:
            return found, doc.path
    return [], None


def _source_of(docs: list[_Doc], quote: str) -> str | None:
    needle = squash(quote)
    return next((d.path for d in docs if needle in squash(d.text)), None)


def _process(
    conn: sqlite3.Connection,
    client: httpx.Client,
    secrets: Secrets,
    root: Path,
    project_id: int,
    asker: Asker,
    now: str,
    sleep: Callable[[float], None],
    run: DeptRun,
) -> None:
    notices = conn.execute(
        "SELECT bid_no, bid_ord, raw_json FROM notice WHERE project_id = ? "
        "ORDER BY COALESCE(notice_date, '') DESC, bid_no DESC",
        (project_id,),
    ).fetchall()
    marker = notices[0]["bid_no"]
    docs: list[_Doc] = []
    try:
        for notice in notices:
            docs = _documents(conn, client, root, notice, now, sleep)
            if docs:
                break
    except httpx.ConnectError, httpx.ConnectTimeout:
        # 나라장터에 닿지 못했다. 공고 탓이 아니니 세 번 한도를 쓰지 않는다 — PC가
        # 하루 오프라인이면 기다리던 사업이 전부 '수동 확인'으로 빠진다. 기록 없이 둔다.
        run.failed += 1
        return
    except httpx.HTTPError, AttachError, OSError:
        failures = _recent_failures(conn, project_id, marker) + 1
        note = NOTE_MANUAL if failures >= MAX_DOWNLOAD_FAILURES else NOTE_DOWNLOAD_FAILED
        _record(conn, project_id, marker, now, note=note)
        run.failed += 1
        return

    if not docs:
        _record(conn, project_id, marker, now, note=NOTE_NO_FILES)
        run.not_found += 1
        return
    readable = [d for d in docs if d.text.strip()]
    if not readable:
        _record(conn, project_id, marker, now, note=NOTE_READ_FAILED)
        run.not_found += 1
        return

    full_text = "\n".join(d.text for d in readable)
    contract = find_contract_dept(full_text)
    candidates, source = _first_candidates(readable)
    chosen = decide_by_rule(candidates)
    if chosen is not None:
        _record(
            conn,
            project_id,
            marker,
            now,
            exec_dept=chosen.name,
            contract_dept=contract,
            snippet=chosen.snippet,
            source_file=source,
            confirmed=1,
        )
        run.confirmed_rule += 1
        return

    answer = None
    if secrets.anthropic_api_key:
        run.asked_llm += 1
        answer = asker(secrets, excerpt_for_llm(full_text))
        if answer is None:
            run.llm_unanswered += 1
    # 키가 없었거나 답을 못 받았으면 사유 끝에 적어 둔다. 키가 생기면 받아 둔 첨부로 다시 묻는다.
    tail = f" · {CLAUDE_PENDING}" if answer is None else ""
    if answer is not None and verify_answer(full_text, answer):
        _record(
            conn,
            project_id,
            marker,
            now,
            exec_dept=answer.exec_dept,
            contract_dept=answer.contract_dept or contract,
            snippet=answer.quote,
            source_file=_source_of(readable, answer.quote),
            decided_by="llm",
            confirmed=1,
        )
        run.confirmed_llm += 1
        return

    if answer is not None and answer.exec_dept:
        _record(
            conn,
            project_id,
            marker,
            now,
            exec_dept=answer.exec_dept,
            contract_dept=contract,
            snippet=answer.quote,
            decided_by="llm",
            note=NOTE_LLM_UNVERIFIED,
        )
    for c in candidates:
        _record(
            conn,
            project_id,
            marker,
            now,
            exec_dept=c.name,
            contract_dept=contract,
            snippet=c.snippet,
            source_file=source,
            note=NOTE_RULE_CANDIDATE + tail,
        )
    if candidates or (answer is not None and answer.exec_dept):
        run.review += 1
        return
    note = (NOTE_CONTRACT_ONLY if contract else NOTE_NOT_FOUND) + tail
    _record(conn, project_id, marker, now, contract_dept=contract, note=note)
    run.not_found += 1


def update_depts(
    conn: sqlite3.Connection,
    client: httpx.Client,
    secrets: Secrets,
    attach_root: Path,
    tier: str | None,
    group: int | None,
    limit: int,
    counters: RunCounters,
    asker: Asker,
    budget_seconds: int = BUDGET_SECONDS,
    now_fn: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> DeptRun:
    """대상을 돌며 부서를 찾는다. 사업마다 커밋해 중간에 멈춰도 거기까지는 남는다."""
    run = DeptRun()
    started = now_fn()
    can_ask = bool(secrets.anthropic_api_key)
    for row in pending_dept_projects(conn, tier, group, limit, can_ask):
        if now_fn() - started > budget_seconds:
            run.stopped_early = True
            break
        counters.processed += 1
        run.checked += 1
        failed_before = run.failed
        now = datetime.now().isoformat(timespec="seconds")
        try:
            _process(conn, client, secrets, attach_root, row["id"], asker, now, sleep, run)
        except sqlite3.Error:
            raise  # 저장 계층이 망가졌다. 사업 한 건의 실패가 아니다
        except Exception:
            # 한 건이 터져도 나머지를 본다. 기록이 없으니 다음 회차에 다시 본다.
            conn.rollback()
            run.failed += 1
        conn.commit()
        if run.failed > failed_before:
            counters.failed += 1
    counters.updated = run.confirmed_rule + run.confirmed_llm
    return run
