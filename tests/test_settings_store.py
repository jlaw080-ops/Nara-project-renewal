import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from nara.config import load_settings
from nara.db import connect, migrate
from nara.settings_store import current_settings, fingerprint, is_seeded, items, seed_settings

BASE = load_settings(Path(__file__).resolve().parents[1] / "config.toml")
NOW = "2026-10-09T09:00:00"


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "s.db")
    migrate(c)
    return c


def test_seeding_copies_the_file_lists_once(conn):
    """실행할 때마다 옮기면 키워드가 끝없이 늘어난다."""
    assert seed_settings(conn, BASE, NOW) is True
    assert seed_settings(conn, BASE, NOW) is False
    values = [r["value"] for r in items(conn, "title_excluded")]
    assert values == list(BASE.title_excluded)
    assert current_settings(conn, BASE) == BASE
    logged = conn.execute("SELECT COUNT(*) FROM setting_log WHERE action = 'seed'").fetchone()[0]
    total = conn.execute("SELECT COUNT(*) FROM setting_item").fetchone()[0]
    assert logged == total > 0


def test_emptied_lists_do_not_come_back_from_the_file(conn):
    """정본은 웹이다. 다 지워도 파일 값으로 되살아나면 안 된다."""
    seed_settings(conn, BASE, NOW)
    conn.execute("DELETE FROM setting_item WHERE kind = 'org_excluded'")
    conn.commit()
    seed_settings(conn, BASE, NOW)
    assert current_settings(conn, BASE).org_excluded == ()


def test_db_values_replace_only_the_managed_lists(conn):
    seed_settings(conn, BASE, NOW)
    conn.execute(
        "INSERT INTO setting_item (kind, value, target, added_at) "
        "VALUES ('nr_alias', '서초구청', '서울특별시 서초구', ?)",
        (NOW,),
    )
    conn.commit()
    other = replace(BASE, service_div_name="다른값", skip_cancelled=False)
    got = current_settings(conn, other)
    assert ("서초구청", "서울특별시 서초구") in got.nr_org_aliases
    assert got.service_div_name == "다른값" and got.skip_cancelled is False


def test_an_unseeded_read_only_db_falls_back_to_the_file(tmp_path):
    path = tmp_path / "ro.db"
    c = connect(path)
    migrate(c)
    c.close()
    ro = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    ro.row_factory = sqlite3.Row
    assert is_seeded(ro) is False
    assert current_settings(ro, BASE) == BASE


def test_fingerprint_changes_when_any_value_changes(conn):
    seed_settings(conn, BASE, NOW)
    before = fingerprint(conn)
    conn.execute("DELETE FROM setting_item WHERE kind = 'title_excluded' AND value = '감리'")
    conn.commit()
    assert fingerprint(conn) != before
