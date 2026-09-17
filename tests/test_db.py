from nara.db import connect, migrate

EXPECTED_TABLES = {
    "org",
    "project",
    "notice",
    "award",
    "status_check",
    "dept_check",
    "attachment",
    "energy_plan",
    "energy_unit_price",
    "run_log",
    "app_state",
}


def test_migrate_creates_every_table(tmp_path):
    conn = connect(tmp_path / "test.db")
    migrate(conn)
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert EXPECTED_TABLES <= names


def test_migrate_is_idempotent(tmp_path):
    conn = connect(tmp_path / "test.db")
    first = migrate(conn)
    second = migrate(conn)
    assert first == second


def test_migrate_seeds_unit_prices(tmp_path):
    conn = connect(tmp_path / "test.db")
    migrate(conn)
    rows = dict(conn.execute("SELECT source_type, price_per_kw FROM energy_unit_price"))
    assert rows == {
        "BIPV": 5_000_000,
        "PV": 2_500_000,
        "지열": 2_500_000,
        "PEMFC": 32_000_000,
        "SOFC": 98_250_000,
    }


def test_foreign_keys_are_enforced(tmp_path):
    conn = connect(tmp_path / "test.db")
    migrate(conn)
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
