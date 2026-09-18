from pathlib import Path

import pytest

from nara.config import load_settings
from nara.db import connect, migrate
from nara.status import pending_status_projects
from nara.store import ensure_project, upsert_org

SETTINGS = load_settings(Path(__file__).resolve().parents[1] / "config.toml")
NOW = "2026-09-18T09:00:00"


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "test.db")
    migrate(c)
    return c


def _project(conn, org_name, name):
    org_id = upsert_org(conn, org_name, SETTINGS, NOW)
    return ensure_project(conn, org_id, name, "manual", NOW)


def _checked(conn, project_id, when, verdict="미확인"):
    conn.execute(
        "INSERT INTO status_check (project_id, verdict, decided_by, checked_at) "
        "VALUES (?, ?, 'rule', ?)",
        (project_id, verdict, when),
    )
    conn.commit()


def test_pending_prefers_projects_never_checked(conn):
    old = _project(conn, "전북특별자치도 완주군", "본 적 있는 사업")
    fresh = _project(conn, "전북특별자치도 완주군", "한 번도 안 본 사업")
    _checked(conn, old, "2026-09-01T09:00:00")

    rows = pending_status_projects(conn, tier=None, limit=10)

    assert rows[0]["id"] == fresh


def test_pending_orders_older_checks_first(conn):
    recent = _project(conn, "전북특별자치도 완주군", "최근에 본 사업")
    stale = _project(conn, "전북특별자치도 완주군", "오래전에 본 사업")
    _checked(conn, recent, "2026-09-17T09:00:00")
    _checked(conn, stale, "2026-08-01T09:00:00")

    rows = pending_status_projects(conn, tier=None, limit=10)

    assert [r["id"] for r in rows] == [stale, recent]


def test_pending_filters_by_tier(conn):
    focus = _project(conn, "전북특별자치도 완주군", "관심 기관 사업")
    _project(conn, "강원특별자치도 양양군", "비관심 기관 사업")

    rows = pending_status_projects(conn, tier="focus", limit=10)

    assert [r["id"] for r in rows] == [focus]


def test_pending_honours_limit(conn):
    for i in range(5):
        _project(conn, "전북특별자치도 완주군", f"사업 {i}")
    assert len(pending_status_projects(conn, tier=None, limit=2)) == 2


def test_pending_rejects_nonpositive_limit(conn):
    """limit 0이면 조용히 '대상 0건'으로 끝나 조용한 날과 구분되지 않는다."""
    with pytest.raises(ValueError):
        pending_status_projects(conn, tier=None, limit=0)


def test_pending_carries_the_dates_the_judgment_needs(conn):
    project_id = _project(conn, "전북특별자치도 완주군", "사업")
    conn.execute(
        "UPDATE project SET start_date = ?, end_date = ? WHERE id = ?",
        ("2027-03-01", "2029-01-30", project_id),
    )
    conn.commit()

    row = pending_status_projects(conn, tier=None, limit=10)[0]

    assert row["start_date"] == "2027-03-01"
    assert row["end_date"] == "2029-01-30"
    assert row["name"] == "사업"
