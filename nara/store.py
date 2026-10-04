"""수집한 공고·기관·사업을 DB에 쓰는 경로."""

import json
import sqlite3

from nara.config import Settings
from nara.filters import is_focus_org
from nara.g2b.list_api import NoticeItem

WEEKDAY_GROUPS = 5


def upsert_org(
    conn: sqlite3.Connection, name: str, settings: Settings, now: str, commit: bool = True
) -> int:
    """수요기관을 등록하고 id를 돌려준다. 이미 있으면 그대로 둔다.

    commit=False면 부른 쪽 트랜잭션에 묶는다(설치계획서 한 행을 한 번에 커밋).
    """
    row = conn.execute("SELECT id FROM org WHERE name = ?", (name,)).fetchone()
    if row:
        return row["id"]
    focus = is_focus_org(name, settings)
    cursor = conn.execute(
        "INSERT INTO org (name, tier, weekday_group, added_at) VALUES (?, ?, ?, ?)",
        (name, "focus" if focus else "rest", None, now),
    )
    org_id = cursor.lastrowid
    if not focus:
        conn.execute(
            "UPDATE org SET weekday_group = ? WHERE id = ?",
            (org_id % WEEKDAY_GROUPS + 1, org_id),
        )
    if commit:
        conn.commit()
    return org_id


def promote_focus_orgs(conn: sqlite3.Connection, settings: Settings) -> int:
    """설정에 나중에 더한 관심기관을 관심으로 올린다. 올린 기관 수를 돌려준다.

    upsert_org는 이미 있는 기관을 건드리지 않는다. 그래서 관심기관을 설정에 더해도 전에
    비관심으로 등록된 기관은 그대로 남아 낙찰·진행현황·실행부서 조회에서 빠진다.
    """
    rows = conn.execute("SELECT id, name FROM org WHERE tier = 'rest'").fetchall()
    ids = [row["id"] for row in rows if is_focus_org(row["name"], settings)]
    for org_id in ids:
        conn.execute("UPDATE org SET tier = 'focus', weekday_group = NULL WHERE id = ?", (org_id,))
    if ids:
        conn.commit()
    return len(ids)


def ensure_project(
    conn: sqlite3.Connection, org_id: int, name: str, source: str, now: str, commit: bool = True
) -> int:
    """같은 기관에 같은 이름의 사업이 있으면 그것을, 없으면 새로 만든다."""
    row = conn.execute(
        "SELECT id FROM project WHERE org_id = ? AND name = ?", (org_id, name)
    ).fetchone()
    if row:
        return row["id"]
    cursor = conn.execute(
        "INSERT INTO project (org_id, name, source, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        (org_id, name, source, now, now),
    )
    if commit:
        conn.commit()
    return cursor.lastrowid


def upsert_notice(
    conn: sqlite3.Connection,
    item: NoticeItem,
    org_id: int,
    project_id: int,
    now: str,
) -> bool:
    """공고를 넣거나 원본만 갱신한다. 새로 넣었으면 True."""
    existing = conn.execute(
        "SELECT project_id FROM notice WHERE bid_no = ?", (item.bid_no,)
    ).fetchone()
    values = (
        org_id,
        item.bid_ord,
        item.org_name,
        item.title,
        item.kind,
        item.notice_date,
        item.open_date,
        item.close_date,
        item.url,
        item.budget_krw,
        item.budget_basis,
        item.officer_name,
        item.officer_tel,
        json.dumps(item.raw, ensure_ascii=False),
        now,
    )
    if existing:
        # 사업 연결은 건드리지 않는다. 사람이 바꿔 놓았을 수 있다.
        conn.execute(
            "UPDATE notice SET org_id=?, bid_ord=?, org_name=?, title=?, kind=?, "
            "notice_date=?, open_date=?, close_date=?, url=?, budget_krw=?, "
            "budget_basis=?, officer_name=?, officer_tel=?, raw_json=?, "
            "collected_at=? WHERE bid_no=?",
            (*values, item.bid_no),
        )
        conn.commit()
        return False

    conn.execute(
        "INSERT INTO notice (bid_no, project_id, org_id, bid_ord, org_name, title, kind, "
        "notice_date, open_date, close_date, url, budget_krw, budget_basis, "
        "officer_name, officer_tel, raw_json, collected_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (item.bid_no, project_id, *values),
    )
    conn.commit()
    return True


def last_run(conn: sqlite3.Connection, command: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM run_log WHERE command = ? ORDER BY id DESC LIMIT 1", (command,)
    ).fetchone()
