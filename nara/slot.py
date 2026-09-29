"""하루 세 번 도는 수집 순서와 겹침 방지. 원 명세의 스케줄표를 옮긴다."""

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta

SLOTS = ("09", "12", "15")
LOCK_KEY = "slot_running"
# 가장 긴 슬롯(수집 + 낙찰 + 진행현황 20분 + 실행부서 20분)보다 넉넉히.
# 죽은 슬롯의 표시는 이만큼 뒤 풀린다.
LOCK_MAX_AGE = timedelta(hours=2)


@dataclass(frozen=True)
class Step:
    name: str  # run_log의 명령 이름과 같다
    options: dict


def plan(slot: str, weekday: int) -> list[Step]:
    """weekday는 date.isoweekday() — 월 1 ~ 일 7."""
    if slot not in SLOTS:
        raise ValueError(f"슬롯은 {' | '.join(SLOTS)} 중 하나다: {slot!r}")
    steps = [Step("collect", {"days": 3})]
    if slot == "12":
        # 비관심 기관은 월~금 다섯 그룹이다. 주말에는 낙찰 조회할 그룹이 없다.
        if weekday <= 5:
            steps.append(Step("enrich award", {"tier": "rest", "group": weekday}))
            steps.append(Step("enrich dept", {"tier": "rest", "group": weekday}))
        return steps
    steps.append(Step("enrich award", {"tier": "focus", "group": None}))
    steps.append(Step("enrich status", {"tier": "focus"}))
    steps.append(Step("enrich dept", {"tier": "focus", "group": None}))
    return steps


def acquire(conn: sqlite3.Connection, now: datetime) -> bool:
    """겹침 표시를 건다. 다른 슬롯이 돌고 있으면 False.

    BEGIN IMMEDIATE로 읽기와 쓰기를 한 번에 잡아 두 슬롯이 동시에 걸지 못하게 한다.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute("SELECT value FROM app_state WHERE key = ?", (LOCK_KEY,)).fetchone()
        if row is not None and now - datetime.fromisoformat(row[0]) < LOCK_MAX_AGE:
            conn.rollback()
            return False
        conn.execute(
            "INSERT INTO app_state (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (LOCK_KEY, now.isoformat(timespec="seconds")),
        )
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise


def release(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM app_state WHERE key = ?", (LOCK_KEY,))
    conn.commit()
