"""수집 흐름 — API에서 받아 필터를 거쳐 DB에 넣는다."""

import sqlite3
from datetime import datetime

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
