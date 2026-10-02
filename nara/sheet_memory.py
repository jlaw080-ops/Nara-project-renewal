"""시트 재이관의 '지난번 시트 값' 기억.

TSV에는 칸별 수정 시각이 없다. 그래서 시트 칸이 팀원이 고친 값인지 옛 값이
그냥 남은 것인지 구분하려면 지난 이관 때 값을 기억해 두고 비교해야 한다.
기억이 없으면 옛 시트 값이 웹 입력을 이관할 때마다 되돌린다.
"""

import sqlite3
from collections.abc import Iterable

from nara.energy import EnergyItem

PROJECT_FIELDS = (
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
FIELD_LABELS = {
    "address": "주소",
    "start_date": "착공일",
    "end_date": "준공일",
    "floor_area": "연면적",
    "zeb_grade": "ZEB 등급",
    "re_ratio": "신재생 비율",
    "etc_cert": "기타 인증",
    "guide_equip": "관급 장비",
    "note": "비고",
    "verdict": "진행현황",
    "exec_dept": "실행부서",
    "energy": "신재생",
    "verdict_release": "잠금 해제",
    "hidden": "숨김",
}
SEEDED_KEY = "sheet_memory_seeded"


def canonical(value: object) -> str:
    """비교용 글자. None은 빈 글자. 실수는 str() 그대로 — 반올림하면 다른 값이 같아진다."""
    return "" if value is None else str(value).strip()


def verdict_value(verdict: str, reason: str | None) -> str:
    return f"{verdict}|{reason or ''}"


def energy_value(items: Iterable[EnergyItem]) -> str:
    ordered = sorted(items, key=lambda i: i.source_type)
    return ", ".join(f"{i.source_type} {i.capacity_kw:.10g}" for i in ordered)


def last_value(conn: sqlite3.Connection, project_id: int, field: str) -> str | None:
    row = conn.execute(
        "SELECT value FROM sheet_memory WHERE project_id = ? AND field = ?",
        (project_id, field),
    ).fetchone()
    return row[0] if row else None


def remember(conn: sqlite3.Connection, project_id: int, field: str, value: str, now: str) -> None:
    conn.execute(
        "INSERT INTO sheet_memory (project_id, field, value, imported_at) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(project_id, field) DO UPDATE SET "
        "value = excluded.value, imported_at = excluded.imported_at",
        (project_id, field, value, now),
    )


def edited_on_web(conn: sqlite3.Connection, project_id: int, field: str) -> bool:
    """지난 이관 뒤에 웹에서 고친 적이 있나.

    '한 번이라도 고쳤나'로 보면 웹 수정 뒤 시트가 두 번 바뀔 때 두 번째도
    웹 충돌로 보고한다 — 그때는 시트 값을 시트 값으로 덮는 것이다.
    같은 초는 웹 수정으로 친다.
    """
    edited = conn.execute(
        "SELECT MAX(edited_at) FROM edit_log WHERE project_id = ? AND field = ?",
        (project_id, field),
    ).fetchone()[0]
    if edited is None:
        return False
    since = conn.execute(
        "SELECT imported_at FROM sheet_memory WHERE project_id = ? AND field = ?",
        (project_id, field),
    ).fetchone()
    return since is None or edited >= since[0]


def _seed_rows(conn: sqlite3.Connection) -> list[tuple[int, str, str]]:
    found: list[tuple[int, str, str]] = []
    for row in conn.execute(f"SELECT id, {', '.join(PROJECT_FIELDS)} FROM project").fetchall():
        for field in PROJECT_FIELDS:
            if text := canonical(row[field]):
                found.append((row["id"], field, text))
    for row in conn.execute(
        "SELECT s.project_id, s.verdict, s.reason FROM status_check s "
        "WHERE s.decided_by = 'imported' AND s.id = (SELECT MAX(t.id) FROM status_check t "
        "WHERE t.project_id = s.project_id AND t.decided_by = 'imported')"
    ).fetchall():
        found.append((row[0], "verdict", verdict_value(row[1], row[2])))
    for row in conn.execute(
        "SELECT d.project_id, d.exec_dept FROM dept_check d "
        "WHERE d.id = (SELECT MAX(e.id) FROM dept_check e WHERE e.project_id = d.project_id "
        "AND e.decided_by = 'imported' AND COALESCE(e.exec_dept, '') != '')"
    ).fetchall():
        found.append((row[0], "exec_dept", row[1]))
    energy: dict[int, list[EnergyItem]] = {}
    for row in conn.execute(
        "SELECT project_id, source_type, capacity_kw FROM energy_plan WHERE entered_by = 'imported'"
    ).fetchall():
        energy.setdefault(row[0], []).append(EnergyItem(row[1], row[2]))
    found.extend((pid, "energy", energy_value(items)) for pid, items in energy.items())
    return found


def seed(conn: sqlite3.Connection, now: str) -> int:
    """도입 때 한 번, 지금 DB 값을 지난 이관 값으로 채운다. 이미 채웠으면 0.

    두 번 채우면 그사이 웹에서 고친 값을 '시트 값'으로 착각한다.
    """
    if conn.execute("SELECT 1 FROM app_state WHERE key = ?", (SEEDED_KEY,)).fetchone():
        return 0
    rows = _seed_rows(conn)
    for project_id, field, value in rows:
        remember(conn, project_id, field, value, now)
    conn.execute("INSERT INTO app_state (key, value) VALUES (?, ?)", (SEEDED_KEY, now))
    conn.commit()
    return len(rows)
