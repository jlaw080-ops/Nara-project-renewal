from nara.db import attachments_dir, connect, migrate

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
    "energy_kind",
    "nr_plan",
    "dept_contact",
    "setting_item",
    "setting_log",
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
        "집광채광": 1_000_000,
    }


def test_foreign_keys_are_enforced(tmp_path):
    conn = connect(tmp_path / "test.db")
    migrate(conn)
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_migrate_adds_the_lookup_columns_to_an_older_database(tmp_path):
    """3단계 때 만든 DB에는 확정 여부 칸이 없다. 옛 줄은 확정으로 남아야 한다."""
    conn = connect(tmp_path / "old.db")
    migrate(conn)
    conn.execute("DROP TABLE dept_check")
    conn.execute(
        "CREATE TABLE dept_check (id INTEGER PRIMARY KEY, bid_no TEXT, project_id INTEGER, "
        "exec_dept TEXT, contract_dept TEXT, head_tel TEXT, snippet TEXT, source_file TEXT, "
        "decided_by TEXT NOT NULL, checked_at TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT INTO dept_check (project_id, exec_dept, decided_by, checked_at) "
        "VALUES (1, '건축과', 'imported', '2026-09-01T09:00:00')"
    )
    conn.execute("DROP TABLE attachment")
    conn.execute(
        "CREATE TABLE attachment (id INTEGER PRIMARY KEY, bid_no TEXT NOT NULL, "
        "filename TEXT NOT NULL, path TEXT, sha256 TEXT, text_path TEXT, "
        "status TEXT NOT NULL DEFAULT 'ok', attempts INTEGER NOT NULL DEFAULT 0, "
        "downloaded_at TEXT)"
    )
    conn.commit()
    migrate(conn)
    assert tuple(conn.execute("SELECT confirmed, note FROM dept_check").fetchone()) == (1, None)
    assert "seq" in [r[1] for r in conn.execute("PRAGMA table_info(attachment)")]


def test_attachments_live_next_to_the_database(tmp_path):
    assert attachments_dir(tmp_path / "data" / "nara.db") == tmp_path / "data" / "attachments"
