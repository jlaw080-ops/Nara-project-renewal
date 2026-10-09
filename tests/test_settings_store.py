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


from nara.settings_store import StaleSettings, apply_change, plan_change, recent_log  # noqa: E402
from nara.store import ensure_project, upsert_org  # noqa: E402


def _world(conn):
    """공고가 있는 사업 둘(체육관·문화관), 공고 없는 사업 하나, 관심기관 둘."""
    seed_settings(conn, BASE, NOW)
    wanju = upsert_org(conn, "전북특별자치도 완주군", BASE, NOW)
    yongin = upsert_org(conn, "경기도 용인시", BASE, NOW)
    ids = {}
    for key, org, name, title in (
        ("gym", wanju, "완주 체육관", "완주 체육관 건립 설계용역"),
        ("hall", yongin, "용인 문화관", "용인 문화관 건축설계 및 공사관리 용역"),
    ):
        ids[key] = ensure_project(conn, org, name, "g2b", NOW)
        org_name = conn.execute("SELECT name FROM org WHERE id = ?", (org,)).fetchone()[0]
        conn.execute(
            "INSERT INTO notice (bid_no, project_id, org_id, org_name, title, notice_date, "
            "collected_at) VALUES (?, ?, ?, ?, ?, '2026-09-01', ?)",
            (key, ids[key], org, org_name, title, NOW),
        )
    ids["manual"] = ensure_project(conn, wanju, "완주 공사관리 센터", "manual", NOW)
    conn.commit()
    return ids, wanju, yongin


def test_preview_lists_only_projects_the_change_newly_blocks(conn):
    """이미 다른 이유로 걸린 사업이나 공고 없는 사업은 끌어오지 않는다."""
    ids, _, _ = _world(conn)
    plan = plan_change(conn, BASE, Change(adds=(("title_excluded", "공사관리", None),)))
    assert [(h.project_id, h.reason) for h in plan.hide] == [
        (ids["hall"], "설정 변경: 제외 키워드 '공사관리'")
    ]
    assert plan.widened is False


def test_preview_flags_a_widening_change(conn):
    _world(conn)
    plan = plan_change(conn, BASE, Change(removes=(("title_excluded", "감리"),)))
    assert plan.widened is True and plan.hide == ()


def test_preview_lists_orgs_leaving_and_joining_the_focus_list(conn):
    _, _, yongin = _world(conn)
    trial = upsert_org(conn, "경기도 시험시", BASE, NOW)
    plan = plan_change(
        conn,
        BASE,
        Change(adds=(("focus_org", "시험시", None),), removes=(("focus_org", "용인시"),)),
    )
    assert [(m.org_id, m.projects) for m in plan.demote] == [(yongin, 1)]
    assert [m.org_id for m in plan.promote] == [trial]


def test_apply_hides_only_checked_candidates_and_moves_orgs(conn):
    ids, _, yongin = _world(conn)
    change = Change(
        adds=(("title_excluded", "공사관리", None),), removes=(("focus_org", "용인시"),)
    )
    plan = plan_change(conn, BASE, change)
    done = apply_change(conn, plan, {ids["hall"], ids["gym"]}, None, NOW)
    assert done == {"items": 2, "hidden": 1, "demoted": 1, "promoted": 0}
    row = conn.execute(
        "SELECT hidden_at, hidden_reason FROM project WHERE id = ?", (ids["hall"],)
    ).fetchone()
    assert row[0] == NOW and row[1] == "설정 변경: 제외 키워드 '공사관리'"
    gym = conn.execute("SELECT hidden_at FROM project WHERE id = ?", (ids["gym"],)).fetchone()
    assert gym[0] is None  # 후보가 아니면 체크해도 숨기지 않는다
    org = conn.execute("SELECT tier, weekday_group FROM org WHERE id = ?", (yongin,)).fetchone()
    assert tuple(org) == ("rest", yongin % 5 + 1)
    got = current_settings(conn, BASE)
    assert "공사관리" in got.title_excluded and "용인시" not in got.focus_orgs
    # 뺀 것을 먼저 기록하고 더한 것을 나중에 기록한다. 최근 것이 위.
    assert [r["action"] for r in recent_log(conn)][:2] == ["add", "remove"]


def test_apply_refuses_when_settings_changed_after_the_preview(conn):
    """두 사람이 동시에 고칠 때 한쪽 변경이 조용히 사라지면 안 된다."""
    _world(conn)
    plan = plan_change(conn, BASE, Change(adds=(("title_excluded", "공사관리", None),)))
    conn.execute(
        "INSERT INTO setting_item (kind, value, added_at) VALUES ('org_excluded', '다른사람', ?)",
        (NOW,),
    )
    conn.commit()
    with pytest.raises(StaleSettings):
        apply_change(conn, plan, set(), None, NOW)
    assert "공사관리" not in current_settings(conn, BASE).title_excluded


def test_apply_rolls_everything_back_when_one_write_fails(conn):
    ids, _, yongin = _world(conn)
    change = Change(
        adds=(("title_excluded", "공사관리", None),), removes=(("focus_org", "용인시"),)
    )
    plan = plan_change(conn, BASE, change)
    conn.execute(
        "CREATE TRIGGER boom BEFORE UPDATE OF tier ON org BEGIN SELECT RAISE(ABORT, 'boom'); END"
    )
    with pytest.raises(sqlite3.DatabaseError):
        apply_change(conn, plan, {ids["hall"]}, None, NOW)
    hall = conn.execute("SELECT hidden_at FROM project WHERE id = ?", (ids["hall"],)).fetchone()
    assert hall[0] is None
    assert conn.execute("SELECT tier FROM org WHERE id = ?", (yongin,)).fetchone()[0] == "focus"
    assert "공사관리" not in current_settings(conn, BASE).title_excluded


def test_an_alias_is_retargeted_by_removing_and_re_adding_it_in_one_save():
    """체크해서 빼고 같은 이름을 새 대상으로 적으면 바꾸기다. 별칭이 사라지면 안 된다."""
    current = {**CURRENT, "nr_alias": {"가군청"}}
    checked = check_settings(
        MultiDict({"remove_nr_alias": "가군청", "add_nr_alias": "가군청 = 새군"}), current
    )
    assert checked.values["change"].removes == (("nr_alias", "가군청"),)
    assert checked.values["change"].adds == (("nr_alias", "가군청", "새군"),)


def test_re_adding_an_existing_alias_without_removing_it_says_how_to_retarget():
    """조용히 버리면 '바뀐 것이 없습니다'만 보여 사람이 헷갈린다."""
    current = {**CURRENT, "nr_alias": {"가군청"}}
    checked = check_settings(MultiDict({"add_nr_alias": "가군청 = 새군"}), current)
    assert checked.errors == {
        "nr_alias": "이미 있는 별칭입니다: 가군청 — "
        "대상을 바꾸려면 기존 값을 체크하고 함께 저장하세요"
    }
