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


from werkzeug.datastructures import MultiDict  # noqa: E402

from nara.settings_store import Change  # noqa: E402
from nara.web.edit import check_settings  # noqa: E402

CURRENT = {
    k: set()
    for k in (
        "title_required", "title_excluded", "org_excluded",
        "focus_org", "focus_exact_org", "nr_alias",
    )
}  # fmt: skip


def _check(current=None, **form):
    return check_settings(MultiDict(form), current or {**CURRENT, "title_excluded": {"감리"}})


def test_check_settings_keeps_inner_spaces_and_drops_blank_and_duplicate_lines():
    checked = _check(add_title_excluded=" 제설 전진기지 \n\n제설 전진기지\n감리\n")
    assert checked.ok
    assert checked.values["change"].adds == (("title_excluded", "제설 전진기지", None),)


def test_check_settings_rejects_short_and_long_values():
    assert _check(add_org_excluded="감").errors == {
        "org_excluded": "키워드는 2자 이상이어야 합니다: 감"
    }
    assert _check(add_focus_org="가" * 51).errors == {"focus_org": "50자까지 적을 수 있습니다"}


def test_check_settings_splits_an_alias_at_the_first_equals_sign():
    checked = _check(add_nr_alias="서초구청 = 서울특별시 서초구\n가군청=나=다")
    assert checked.values["change"].adds == (
        ("nr_alias", "서초구청", "서울특별시 서초구"),
        ("nr_alias", "가군청", "나=다"),
    )
    bad = _check(add_nr_alias="서초구청")
    assert bad.errors == {"nr_alias": "`설치계획서 기관명 = 나라 앱 기관명` 꼴로 적으세요"}


def test_check_settings_ignores_removing_a_value_that_is_already_gone():
    """다른 사람이 먼저 뺀 값이면 오류 없이 넘어간다."""
    checked = _check(remove_title_excluded=["감리", "없는값"])
    assert checked.values["change"].removes == (("title_excluded", "감리"),)


def test_check_settings_warns_when_every_required_keyword_goes():
    current = {**CURRENT, "title_required": {"설계"}}
    checked = check_settings(MultiDict({"remove_title_required": "설계"}), current)
    assert checked.ok
    assert checked.values["warnings"] == ["제목 필수 키워드가 없으면 모든 용역을 수집합니다"]


def test_change_apply_to_removes_then_appends():
    change = Change(
        adds=(("title_excluded", "체육", None), ("nr_alias", "가군청", "가군")),
        removes=(("title_excluded", "감리"),),
    )
    got = change.apply_to(BASE)
    assert "감리" not in got.title_excluded and got.title_excluded[-1] == "체육"
    assert ("가군청", "가군") in got.nr_org_aliases
    assert Change().empty and not change.empty
