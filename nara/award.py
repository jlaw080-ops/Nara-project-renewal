"""낙찰업체 조회 흐름."""

import json
import sqlite3
from datetime import datetime

import httpx

from nara.g2b.award_api import fetch_award
from nara.g2b.common import G2BError
from nara.runlog import RunCounters


def pending_award_bid_nos(
    conn: sqlite3.Connection,
    today: str,
    tier: str | None,
    weekday_group: int | None,
    limit: int,
) -> list[str]:
    """개찰이 지났고 낙찰업체가 아직 없는 공고번호."""
    sql = [
        "SELECT n.bid_no FROM notice n",
        "JOIN org o ON o.id = n.org_id",
        "LEFT JOIN award a ON a.bid_no = n.bid_no",
        "WHERE a.bid_no IS NULL",
        "  AND n.open_date != '' AND n.open_date <= ?",
    ]
    params: list = [today]
    if tier:
        sql.append("  AND o.tier = ?")
        params.append(tier)
    if weekday_group is not None:
        sql.append("  AND o.weekday_group = ?")
        params.append(weekday_group)
    sql.append("ORDER BY n.open_date LIMIT ?")
    params.append(limit)
    return [r["bid_no"] for r in conn.execute("\n".join(sql), params)]


def update_awards(
    conn: sqlite3.Connection,
    client: httpx.Client,
    api_key: str,
    today: str,
    tier: str | None,
    weekday_group: int | None,
    limit: int,
    counters: RunCounters,
) -> int:
    """낙찰업체가 비어 있는 공고를 조회해 채운다. 기록한 건수를 돌려준다."""
    now = datetime.now().isoformat(timespec="seconds")
    updated = 0
    for bid_no in pending_award_bid_nos(conn, today, tier, weekday_group, limit):
        counters.processed += 1
        try:
            award = fetch_award(client, api_key, bid_no)
        except G2BError, httpx.HTTPError:
            # 한 건이 실패해도 나머지는 계속 본다. 일시적 네트워크 오류 하나가
            # 그 회차의 남은 대기 건을 통째로 날리지 않게 한다.
            counters.failed += 1
            continue
        if award is None:
            continue
        cursor = conn.execute(
            "INSERT OR IGNORE INTO award (bid_no, winner, award_date, raw_json, checked_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                bid_no,
                award.winner,
                award.award_date,
                json.dumps(award.raw, ensure_ascii=False),
                now,
            ),
        )
        conn.commit()
        if cursor.rowcount == 1:
            updated += 1
            counters.updated += 1
    return updated
