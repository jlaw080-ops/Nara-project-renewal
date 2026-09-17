"""수집 흐름 — API에서 받아 필터를 거쳐 DB에 넣는다."""

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import httpx

from nara.config import Settings
from nara.filters import org_passes, title_passes
from nara.g2b.list_api import NoticeItem, iter_notices
from nara.runlog import RunCounters
from nara.store import ensure_project, upsert_notice, upsert_org


def _accepts(item: NoticeItem, settings: Settings) -> bool:
    if item.service_div != settings.service_div_name:
        return False
    if settings.skip_cancelled and "취소" in item.kind:
        return False
    if not item.bid_no:
        return False
    return title_passes(item.title, settings) and org_passes(item.org_name, settings)


def collect_range(
    conn: sqlite3.Connection,
    client: httpx.Client,
    api_key: str,
    settings: Settings,
    begin: datetime,
    end: datetime,
    counters: RunCounters,
) -> int:
    """기간 안의 공고를 수집한다. 새로 넣은 건수를 돌려준다."""
    now = datetime.now().isoformat(timespec="seconds")
    added = 0
    for item in iter_notices(client, api_key, begin, end):
        counters.processed += 1
        if not _accepts(item, settings):
            continue
        org_id = upsert_org(conn, item.org_name, settings, now)
        project_id = ensure_project(conn, org_id, item.title, "g2b", now)
        if upsert_notice(conn, item, org_id, project_id, now):
            added += 1
            counters.updated += 1
    return added


CURSOR_KEY = "backfill_cursor"


@dataclass(frozen=True)
class BackfillResult:
    added: int
    cursor: str
    done: bool


def _get_state(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM app_state WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def _set_state(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO app_state (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    conn.commit()


def backfill(
    conn: sqlite3.Connection,
    client: httpx.Client,
    api_key: str,
    settings: Settings,
    days_back: int,
    chunk_days: int,
    counters: RunCounters,
    now: datetime | None = None,
    max_chunks: int | None = None,
) -> BackfillResult:
    """과거 공고를 기간을 쪼개 과거에서 현재 방향으로 수집한다."""
    # CLI는 min=1로 막지만 이 함수는 직접 부를 수 있다. chunk_days가 0 이하면
    # cursor가 전진하지 않아 while 루프가 끝나지 않는다.
    if chunk_days < 1:
        raise ValueError(f"chunk_days는 1 이상이어야 한다: {chunk_days}")
    if days_back < 1:
        raise ValueError(f"days_back은 1 이상이어야 한다: {days_back}")
    now = now or datetime.now()
    floor = (now - timedelta(days=days_back)).date()
    saved = _get_state(conn, CURSOR_KEY)
    cursor = date.fromisoformat(saved) if saved else floor
    cursor = max(cursor, floor)

    added = 0
    chunks = 0
    while cursor < now.date():
        if max_chunks is not None and chunks >= max_chunks:
            _set_state(conn, CURSOR_KEY, cursor.isoformat())
            return BackfillResult(added, cursor.isoformat(), done=False)
        chunk_end = min(cursor + timedelta(days=chunk_days), now.date())
        added += collect_range(
            conn, client, api_key, settings,
            datetime.combine(cursor, datetime.min.time()),
            datetime.combine(chunk_end, datetime.min.time()),
            counters,
        )
        cursor = chunk_end
        chunks += 1
        _set_state(conn, CURSOR_KEY, cursor.isoformat())

    conn.execute("DELETE FROM app_state WHERE key = ?", (CURSOR_KEY,))
    conn.commit()
    return BackfillResult(added, cursor.isoformat(), done=True)
