"""설치계획서 받기 → 짝 찾기 → 반영."""

from pathlib import Path

import pytest

from nara.config import load_settings
from nara.db import connect, migrate
from nara.nr_apply import NR_SNIPPET, RowResult, ignore_plan, ingest, link_plan
from nara.runlog import RunCounters
from nara.store import ensure_project, upsert_org

SETTINGS = load_settings(Path(__file__).resolve().parents[1] / "config.toml")
NOW = "2026-10-04T09:00:00"
LATER = "2026-10-05T09:00:00"


def _row(**change):
    base = {
        "key": "2026-001",
        "org": "전라북도 완주군",
        "name": "완주 다목적체육관",
        "addr": "전북특별자치도 완주군 봉동읍 완주로 1",
        "start": "2027-03-01",
        "end": "2028-06-30",
        "dept": "체육진흥과",
        "energy": [{"source": "지열", "form": "수직밀폐형", "capacity_kw": 336.06}],
    }
    return {**base, **change}


@pytest.fixture
def db(tmp_path):
    conn = connect(tmp_path / "a.db")
    migrate(conn)
    org = upsert_org(conn, "전북특별자치도 완주군", SETTINGS, NOW)
    gym = ensure_project(conn, org, "완주군 다목적체육관 건립 설계용역", "g2b", NOW)
    return conn, gym


def _energy(conn, pid):
    rows = conn.execute(
        "SELECT source_type, capacity_kw, entered_by FROM energy_plan WHERE project_id = ? "
        "ORDER BY source_type",
        (pid,),
    ).fetchall()
    return [tuple(r) for r in rows]


def _depts(conn, pid):
    rows = conn.execute(
        "SELECT exec_dept, decided_by, snippet FROM dept_check WHERE project_id = ? ORDER BY id",
        (pid,),
    ).fetchall()
    return [tuple(r) for r in rows]


def _web_edit(conn, pid, field):
    conn.execute(
        "INSERT INTO edit_log (project_id, field, old_value, new_value, edited_at) "
        "VALUES (?, ?, NULL, 'x', ?)",
        (pid, field, NOW),
    )
    conn.commit()


def _second_gym(conn, gym):
    org = conn.execute("SELECT org_id FROM project WHERE id = ?", (gym,)).fetchone()[0]
    ensure_project(conn, org, "완주군 다목적체육관 리모델링 설계용역", "g2b", NOW)


def test_a_clear_match_is_linked_and_filled_in(db):
    conn, gym = db
    counters = RunCounters()
    results = ingest(conn, [_row()], SETTINGS, NOW, counters)
    assert results == [RowResult("2026-001", "created", "linked", gym)]
    assert _energy(conn, gym) == [("지열", 336.06, "nr")]
    assert _depts(conn, gym) == [("체육진흥과", "nr", NR_SNIPPET)]
    project = conn.execute("SELECT address, start_date, end_date FROM project WHERE id = ?", (gym,))
    assert tuple(project.fetchone()) == (
        "전북특별자치도 완주군 봉동읍 완주로 1", "2027-03-01", "2028-06-30",
    )  # fmt: skip
    assert (counters.processed, counters.updated, counters.failed) == (1, 1, 0)


def test_sending_the_same_plan_again_changes_nothing(db):
    conn, gym = db
    ingest(conn, [_row()], SETTINGS, NOW)
    assert ingest(conn, [_row()], SETTINGS, LATER) == [
        RowResult("2026-001", "unchanged", "linked", gym)
    ]
    assert len(_energy(conn, gym)) == 1
    assert len(_depts(conn, gym)) == 1


def test_an_unknown_building_becomes_a_new_project(db):
    conn, _ = db
    [result] = ingest(conn, [_row(key="2026-002", name="봉동 공공도서관")], SETTINGS, NOW)
    assert (result.saved, result.match) == ("created", "new_project")
    project = conn.execute(
        "SELECT p.name, p.source, o.name AS org FROM project p JOIN org o ON o.id = p.org_id "
        "WHERE p.id = ?",
        (result.project_id,),
    ).fetchone()
    assert tuple(project) == ("봉동 공공도서관", "nr", "전북특별자치도 완주군")


def test_a_new_org_is_created_under_its_current_name(db):
    conn, _ = db
    [result] = ingest(conn, [_row(key="2026-003", org="강원도 강릉시")], SETTINGS, NOW)
    org = conn.execute(
        "SELECT o.name FROM project p JOIN org o ON o.id = p.org_id WHERE p.id = ?",
        (result.project_id,),
    ).fetchone()
    assert org[0] == "강원특별자치도 강릉시"


def test_an_unclear_match_waits_for_a_person(db):
    conn, gym = db
    _second_gym(conn, gym)
    [result] = ingest(conn, [_row()], SETTINGS, NOW)
    assert (result.match, result.project_id) == ("pending", None)
    assert _energy(conn, gym) == []


def test_a_web_edit_is_kept_and_reported(db):
    conn, gym = db
    conn.execute(
        "INSERT INTO energy_plan (project_id, source_type, capacity_kw, entered_by, updated_at) "
        "VALUES (?, 'PV', 20, 'human', ?)",
        (gym, NOW),
    )
    _web_edit(conn, gym, "energy")
    _web_edit(conn, gym, "start_date")
    ingest(conn, [_row()], SETTINGS, NOW)
    assert _energy(conn, gym) == [("PV", 20.0, "human")]
    skipped = conn.execute("SELECT skipped FROM nr_plan").fetchone()[0]
    assert skipped == "energy,start_date"
    end = conn.execute("SELECT end_date FROM project WHERE id = ?", (gym,)).fetchone()[0]
    assert end == "2028-06-30"


def test_a_department_chosen_by_a_person_is_kept(db):
    conn, gym = db
    conn.execute(
        "INSERT INTO dept_check (project_id, exec_dept, confirmed, decided_by, checked_at) "
        "VALUES (?, '건축과', 1, 'human', ?)",
        (gym, NOW),
    )
    conn.commit()
    ingest(conn, [_row()], SETTINGS, NOW)
    assert _depts(conn, gym) == [("건축과", "human", None)]
    assert "exec_dept" in conn.execute("SELECT skipped FROM nr_plan").fetchone()[0]


def test_an_empty_energy_list_does_not_wipe_the_plan(db):
    """에너지원 표를 못 읽은 설치계획서가 있던 계획을 지우면 안 된다."""
    conn, gym = db
    ingest(conn, [_row()], SETTINGS, NOW)
    ingest(conn, [_row(energy=[])], SETTINGS, LATER)
    assert _energy(conn, gym) == [("지열", 336.06, "nr")]


def test_two_buildings_on_one_project_add_up(db):
    conn, gym = db
    ingest(conn, [_row()], SETTINGS, NOW)
    second = _row(
        key="2026-009",
        name="완주 다목적체육관 별관",
        energy=[
            {"source": "지열", "form": "수직밀폐형", "capacity_kw": 100},
            {"source": "태양광", "form": "고정식", "capacity_kw": 30},
        ],
    )
    [result] = ingest(conn, [second], SETTINGS, NOW)
    plan = conn.execute("SELECT id FROM nr_plan WHERE key = '2026-009'").fetchone()[0]
    if result.match != "linked":
        link_plan(conn, plan, gym, SETTINGS, NOW)
    assert _energy(conn, gym) == [("PV", 30.0, "nr"), ("지열", 436.06, "nr")]


def test_an_unknown_energy_kind_is_added_without_a_price(db):
    conn, gym = db
    energy = [{"source": "태양열", "form": "평판형", "capacity_kw": 12}]
    ingest(conn, [_row(energy=energy)], SETTINGS, NOW)
    assert _energy(conn, gym) == [("태양열 평판형", 12.0, "nr")]
    kind = conn.execute("SELECT source, form FROM energy_kind WHERE code = '태양열 평판형'")
    assert tuple(kind.fetchone()) == ("태양열", "평판형")


def test_an_ignored_plan_stays_ignored_when_sent_again(db):
    conn, gym = db
    _second_gym(conn, gym)
    ingest(conn, [_row()], SETTINGS, NOW)
    plan = conn.execute("SELECT id FROM nr_plan").fetchone()[0]
    ignore_plan(conn, plan)
    [result] = ingest(conn, [_row(end="2029-01-01")], SETTINGS, LATER)
    assert (result.saved, result.match, result.project_id) == ("updated", "ignored", None)
    assert _energy(conn, gym) == []


def test_a_person_can_link_or_start_a_new_project(db):
    conn, gym = db
    _second_gym(conn, gym)
    ingest(conn, [_row()], SETTINGS, NOW)
    plan = conn.execute("SELECT id FROM nr_plan").fetchone()[0]
    assert link_plan(conn, plan, gym, SETTINGS, NOW) == gym
    assert conn.execute("SELECT match_state FROM nr_plan").fetchone()[0] == "human"
    assert _energy(conn, gym) == [("지열", 336.06, "nr")]
    new_id = link_plan(conn, plan, None, SETTINGS, NOW)
    assert new_id != gym
    assert conn.execute("SELECT source FROM project WHERE id = ?", (new_id,)).fetchone()[0] == "nr"


def test_linking_to_a_missing_project_or_plan_is_refused(db):
    conn, _ = db
    ingest(conn, [_row()], SETTINGS, NOW)
    plan = conn.execute("SELECT id FROM nr_plan").fetchone()[0]
    with pytest.raises(LookupError):
        link_plan(conn, plan, 99999, SETTINGS, NOW)
    with pytest.raises(LookupError):
        link_plan(conn, 99999, None, SETTINGS, NOW)
    with pytest.raises(LookupError):
        ignore_plan(conn, 99999)


def test_a_bad_row_is_reported_and_the_rest_are_kept(db):
    conn, _ = db
    counters = RunCounters()
    results = ingest(conn, [_row(start="내년"), _row()], SETTINGS, NOW, counters)
    assert results[0] == RowResult(
        "2026-001", "invalid", error="착공 날짜는 YYYY-MM-DD로 보내세요: 내년"
    )
    assert results[1].saved == "created"
    assert counters.failed == 1


def test_a_hidden_project_is_filled_in_but_stays_hidden(db):
    conn, gym = db
    conn.execute("UPDATE project SET hidden_at = ? WHERE id = ?", (NOW, gym))
    conn.commit()
    ingest(conn, [_row()], SETTINGS, NOW)
    assert _energy(conn, gym) == [("지열", 336.06, "nr")]
    assert conn.execute("SELECT hidden_at FROM project WHERE id = ?", (gym,)).fetchone()[0] == NOW
