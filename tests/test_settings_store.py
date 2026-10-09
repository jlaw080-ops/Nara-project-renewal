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


def test_collect_reads_a_keyword_added_on_the_web(tmp_path):
    """서버를 다시 띄우지 않아도 다음 수집부터 반영된다는 약속."""
    from nara.cli import _load_settings

    c = connect(tmp_path / "c.db")
    migrate(c)
    config = Path(__file__).resolve().parents[1] / "config.toml"
    _load_settings(c, config)
    c.execute(
        "INSERT INTO setting_item (kind, value, added_at) VALUES ('title_excluded', '체육관', ?)",
        (NOW,),
    )
    c.commit()
    assert "체육관" in _load_settings(c, config).title_excluded


def test_the_web_app_seeds_at_start_and_reads_settings_per_request(tmp_path):
    """웹에서 바꾼 별칭이 서버를 다시 띄우지 않아도 다음 설치계획서 받기에 쓰인다."""
    from nara.web.app import _settings, create_app, get_conn

    path = tmp_path / "w.db"
    c = connect(path)
    migrate(c)
    c.close()
    app = create_app(path, secret_key="test-secret", settings=BASE)
    c = connect(path)
    assert is_seeded(c)
    c.execute(
        "INSERT INTO setting_item (kind, value, target, added_at) "
        "VALUES ('nr_alias', '시험군청', '전북특별자치도 완주군', ?)",
        (NOW,),
    )
    c.commit()
    c.close()
    with app.app_context():
        assert ("시험군청", "전북특별자치도 완주군") in _settings(get_conn()).nr_org_aliases
