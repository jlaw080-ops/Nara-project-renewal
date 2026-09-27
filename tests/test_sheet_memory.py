"""시트 재이관의 기억 — 도입 때 지금 DB 값을 지난 이관 값으로 삼는다."""

from pathlib import Path

import pytest

from nara.config import load_settings
from nara.db import connect, migrate
from nara.sheet_memory import (
    SEEDED_KEY,
    energy_value,
    last_value,
    seed,
    verdict_value,
)
from nara.store import ensure_project, upsert_org

SETTINGS = load_settings(Path(__file__).resolve().parents[1] / "config.toml")
NOW = "2026-09-28T09:00:00"


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "t.db")
    migrate(c)
    # migrate가 빈 DB에서 이미 한 번 채웠다. 자료를 넣고 다시 채워 보려고 표시를 지운다.
    c.execute("DELETE FROM app_state WHERE key = ?", (SEEDED_KEY,))
    c.commit()
    return c


def _project(conn, name="완주 체육관 증축", **fields):
    org_id = upsert_org(conn, "전북특별자치도 완주군", SETTINGS, NOW)
    project_id = ensure_project(conn, org_id, name, "manual", NOW)
    for key, value in fields.items():
        conn.execute(f"UPDATE project SET {key} = ? WHERE id = ?", (value, project_id))
    return project_id


def test_migrate_creates_the_new_tables_and_marks_the_seed_done(tmp_path):
    c = connect(tmp_path / "m.db")
    migrate(c)
    assert c.execute("SELECT 1 FROM app_state WHERE key = ?", (SEEDED_KEY,)).fetchone()
    assert c.execute("SELECT COUNT(*) FROM edit_log").fetchone()[0] == 0
    assert c.execute("SELECT COUNT(*) FROM sheet_memory").fetchone()[0] == 0


def test_seed_remembers_the_current_project_values(conn):
    """도입 전에는 웹 수정이 없으므로 지금 값이 곧 지난 이관 값이다."""
    pid = _project(conn, start_date="2026-03-01", floor_area=1234.5, note="예정공사비: 10억")
    seed(conn, NOW)
    assert last_value(conn, pid, "start_date") == "2026-03-01"
    assert last_value(conn, pid, "floor_area") == "1234.5"
    assert last_value(conn, pid, "note") == "예정공사비: 10억"
    assert last_value(conn, pid, "address") is None


def test_seed_runs_only_once(conn):
    """두 번째로 채우면 그사이 웹에서 고친 값을 '지난 이관 값'으로 착각한다."""
    _project(conn, address="완주군 봉동읍")
    assert seed(conn, NOW) == 1
    assert seed(conn, NOW) == 0


def test_seed_takes_the_latest_imported_verdict_and_ignores_machine_ones(conn):
    pid = _project(conn)
    rows = (
        ("착공 전(설계 단계)", "낙찰", "imported", "2026-09-01T00:00:00"),
        ("시공 중", "기공식", "imported", "2026-09-02T00:00:00"),
        ("준공 완료", "", "news", "2026-09-03T00:00:00"),
    )
    for verdict, reason, by, when in rows:
        conn.execute(
            "INSERT INTO status_check (project_id, verdict, reason, decided_by, checked_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (pid, verdict, reason, by, when),
        )
    seed(conn, NOW)
    assert last_value(conn, pid, "verdict") == verdict_value("시공 중", "기공식")


def test_seed_takes_the_latest_imported_department_with_a_name(conn):
    pid = _project(conn)
    for dept, when in (("체육진흥과", "2026-09-01T00:00:00"), ("", "2026-09-02T00:00:00")):
        conn.execute(
            "INSERT INTO dept_check (project_id, exec_dept, decided_by, checked_at) "
            "VALUES (?, ?, 'imported', ?)",
            (pid, dept, when),
        )
    seed(conn, NOW)
    assert last_value(conn, pid, "exec_dept") == "체육진흥과"


def test_seed_remembers_energy_as_one_sorted_line(conn):
    pid = _project(conn)
    for source, kw in (("지열", 10.0), ("PV", 21.96)):
        conn.execute(
            "INSERT INTO energy_plan (project_id, source_type, capacity_kw, entered_by, "
            "updated_at) VALUES (?, ?, ?, 'imported', ?)",
            (pid, source, kw, NOW),
        )
    seed(conn, NOW)
    assert last_value(conn, pid, "energy") == "PV 21.96, 지열 10"


def test_energy_value_keeps_small_differences():
    """용량을 반올림해 비교하면 1234.567과 1234.57이 같은 값이 된다."""
    from nara.energy import EnergyItem

    assert energy_value([EnergyItem("PV", 1234.567)]) != energy_value([EnergyItem("PV", 1234.57)])
