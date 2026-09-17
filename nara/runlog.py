"""CLI 실행을 run_log 표에 남긴다."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime


@dataclass
class RunCounters:
    processed: int = 0
    updated: int = 0
    failed: int = 0


@contextmanager
def run_log(conn: sqlite3.Connection, command: str, args: str = "") -> Iterator[RunCounters]:
    cursor = conn.execute(
        "INSERT INTO run_log (command, args, started_at) VALUES (?, ?, ?)",
        (command, args, datetime.now().isoformat(timespec="seconds")),
    )
    run_id = cursor.lastrowid
    conn.commit()
    counters = RunCounters()
    try:
        yield counters
    except Exception as exc:
        _finish(conn, run_id, counters, "error", str(exc))
        raise
    status = "partial" if counters.failed else "ok"
    _finish(conn, run_id, counters, status, None)


def _finish(conn, run_id: int, counters: RunCounters, status: str, message: str | None) -> None:
    conn.execute(
        "UPDATE run_log SET finished_at = ?, processed = ?, updated = ?, failed = ?, "
        "status = ?, message = ? WHERE id = ?",
        (
            datetime.now().isoformat(timespec="seconds"),
            counters.processed,
            counters.updated,
            counters.failed,
            status,
            message,
            run_id,
        ),
    )
    conn.commit()
