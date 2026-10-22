"""수집 슬롯 — 원 명세의 스케줄표, 한 단계가 죽어도 다음 단계, 겹치지 않기."""

from datetime import datetime, timedelta

import pytest
from typer.testing import CliRunner

from nara import cli
from nara.db import connect, migrate
from nara.slot import LOCK_KEY, Step, acquire, plan, release

T0 = datetime(2026, 9, 28, 9, 0, 0)


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "s.db")
    migrate(c)
    return c


def test_morning_and_afternoon_slots_follow_the_schedule():
    for slot in ("09", "15"):
        assert plan(slot, 1) == [
            Step("collect", {"days": 3}),
            Step("enrich award", {"tier": "focus", "group": None}),
            Step("enrich status", {"tier": "focus"}),
            Step("enrich dept", {"tier": "focus", "group": None}),
        ]


def test_noon_slot_checks_awards_for_todays_weekday_group():
    assert plan("12", 3) == [
        Step("collect", {"days": 3}),
        Step("enrich award", {"tier": "rest", "group": 3}),
        Step("enrich dept", {"tier": "rest", "group": 3}),
    ]


def test_noon_slot_on_a_weekend_only_collects():
    """요일 그룹은 월~금 다섯이다. 토·일에는 낙찰 조회할 그룹이 없다."""
    assert plan("12", 6) == [Step("collect", {"days": 3})]
    assert plan("12", 7) == [Step("collect", {"days": 3})]


def test_an_unknown_slot_is_refused():
    with pytest.raises(ValueError):
        plan("10", 1)


def test_two_slots_do_not_run_at_once(conn):
    assert acquire(conn, T0) is True
    assert acquire(conn, T0 + timedelta(minutes=30)) is False
    release(conn)
    assert acquire(conn, T0 + timedelta(minutes=31)) is True


def test_a_lock_left_by_a_crashed_slot_expires(conn):
    """슬롯이 도중에 죽으면 표시가 남는다. 영영 멈추면 안 된다."""
    assert acquire(conn, T0) is True
    assert acquire(conn, T0 + timedelta(hours=2, minutes=1)) is True


def _fake_runners(monkeypatch, calls, fail=()):
    def make(name):
        def run(**kwargs):
            calls.append(name)
            if name in fail:
                raise RuntimeError(f"{name} 고장")

        return run

    for name in ("collect", "enrich award", "enrich status", "enrich dept"):
        monkeypatch.setitem(cli._STEP_RUNNERS, name, make(name))


def test_run_slot_keeps_going_after_a_failed_step(tmp_path, monkeypatch):
    calls = []
    _fake_runners(monkeypatch, calls, fail={"enrich award"})
    db = tmp_path / "r.db"
    result = CliRunner().invoke(cli.app, ["run", "slot", "09", "--db", str(db)])
    assert calls == ["collect", "enrich award", "enrich status", "enrich dept"]
    assert result.exit_code == 1
    assert "enrich award" in result.output
    c = connect(db)
    assert c.execute("SELECT 1 FROM app_state WHERE key = ?", (LOCK_KEY,)).fetchone() is None
    c.close()


def test_run_slot_skips_when_another_slot_is_running(tmp_path, monkeypatch):
    calls = []
    _fake_runners(monkeypatch, calls)
    db = tmp_path / "r.db"
    c = connect(db)
    migrate(c)
    acquire(c, datetime.now())
    c.close()
    result = CliRunner().invoke(cli.app, ["run", "slot", "15", "--db", str(db)])
    assert result.exit_code == 1
    assert calls == []
    c = connect(db)
    row = c.execute("SELECT status, message FROM run_log WHERE command = 'run slot'").fetchone()
    c.close()
    assert row["status"] == "partial"
    assert "앞 슬롯" in row["message"]


def test_is_locked_follows_the_lock_age(tmp_path):
    from nara.slot import is_locked

    conn = connect(tmp_path / "l.db")
    migrate(conn)
    assert is_locked(conn, T0) is False
    acquire(conn, T0)
    assert is_locked(conn, T0 + timedelta(minutes=30)) is True
    assert is_locked(conn, T0 + timedelta(hours=2, minutes=1)) is False


def test_run_steps_runs_only_the_chosen_steps_in_pipeline_order(tmp_path, monkeypatch):
    calls = []
    _fake_runners(monkeypatch, calls)
    db = tmp_path / "r.db"
    args = ["run", "steps", "--step", "dept", "--step", "collect", "--db", str(db)]
    result = CliRunner().invoke(cli.app, args)
    assert result.exit_code == 0, result.output
    assert calls == ["collect", "enrich dept"]
    c = connect(db)
    assert c.execute("SELECT 1 FROM app_state WHERE key = ?", (LOCK_KEY,)).fetchone() is None
    row = c.execute("SELECT status, args FROM run_log WHERE command = 'run steps'").fetchone()
    c.close()
    assert (row["status"], row["args"]) == ("ok", "collect dept")


def test_run_steps_refuses_an_unknown_step_and_a_running_slot(tmp_path, monkeypatch):
    calls = []
    _fake_runners(monkeypatch, calls)
    db = tmp_path / "r.db"
    result = CliRunner().invoke(cli.app, ["run", "steps", "--step", "backup", "--db", str(db)])
    assert result.exit_code == 1 and calls == []
    c = connect(db)
    migrate(c)
    acquire(c, datetime.now())
    c.close()
    result = CliRunner().invoke(cli.app, ["run", "steps", "--step", "collect", "--db", str(db)])
    assert result.exit_code == 1 and calls == []
    assert "돌고 있" in result.output


def test_run_project_refreshes_one_project_through_the_three_lookups(tmp_path, monkeypatch):
    seen = []
    for name in ("enrich_award", "enrich_status", "enrich_dept"):
        monkeypatch.setattr(cli, name, lambda name=name, **kw: seen.append((name, kw["project"])))
    db = tmp_path / "r.db"
    result = CliRunner().invoke(cli.app, ["run", "project", "7", "--db", str(db)])
    assert result.exit_code == 0, result.output
    assert seen == [("enrich_award", 7), ("enrich_status", 7), ("enrich_dept", 7)]
    c = connect(db)
    row = c.execute("SELECT status, args FROM run_log WHERE command = 'run project'").fetchone()
    assert c.execute("SELECT 1 FROM app_state WHERE key = ?", (LOCK_KEY,)).fetchone() is None
    c.close()
    assert (row["status"], row["args"]) == ("ok", "7")


def test_step_runners_call_the_real_enrich_commands_without_typer_defaults(tmp_path, monkeypatch):
    """명령 함수를 Typer 없이 직접 부르면 안 넘긴 인자는 Typer 기본값 객체가 된다.

    2026-10-11 20:03 '지금 실행'이 `--project <OptionInfo>`로 터졌다. 가짜 runner가 아니라
    실제 enrich 명령 함수를 거쳐 run_log에 남는 인자까지 본다.
    """
    from nara.config import Secrets
    from nara.dept import DeptRun
    from nara.status import StatusRun

    seen = {}

    def fake_awards(*args, **kw):
        seen["award"] = kw.get("project_id", "missing")
        return 0

    def fake_statuses(*args, **kw):
        seen["status"] = kw.get("project_id", "missing")
        return StatusRun()

    def fake_depts(*args, **kw):
        seen["dept"] = kw.get("project_id", "missing")
        return DeptRun()

    monkeypatch.setattr(cli, "update_awards", fake_awards)
    monkeypatch.setattr(cli, "update_statuses", fake_statuses)
    monkeypatch.setattr(cli, "update_depts", fake_depts)
    secrets = Secrets(
        g2b_api_key="g", naver_client_id=None, naver_client_secret=None, anthropic_api_key=None
    )
    monkeypatch.setattr(cli, "load_secrets", lambda path: secrets)
    db = tmp_path / "r.db"
    args = ["run", "steps", "--step", "award", "--step", "status", "--step", "dept"]
    result = CliRunner().invoke(cli.app, [*args, "--db", str(db)])
    assert result.exit_code == 0, result.output
    assert seen == {"award": None, "status": None, "dept": None}
    c = connect(db)
    rows = c.execute(
        "SELECT command, args, status FROM run_log WHERE command LIKE 'enrich %' ORDER BY id"
    ).fetchall()
    c.close()
    assert [tuple(r) for r in rows] == [
        ("enrich award", "--tier focus", "ok"),
        ("enrich status", "--tier focus", "ok"),
        ("enrich dept", "--tier focus", "ok"),
    ]


def test_run_project_calls_the_real_enrich_commands_without_typer_defaults(tmp_path, monkeypatch):
    """상세의 '이 사업 다시 조회'. 2026-10-22 08:39 세 단계가 모두 '--tier는 focus | rest | all 중
    하나여야 한다'로 실패했다 — run_project가 tier 등을 안 넘겨 Typer 기본값 객체가 들어갔다."""
    from nara.config import Secrets
    from nara.dept import DeptRun
    from nara.status import StatusRun

    seen = {}

    def fake_awards(*args, **kw):
        seen["award"] = kw
        return 0

    def fake_statuses(*args, **kw):
        seen["status"] = kw
        return StatusRun()

    def fake_depts(*args, **kw):
        seen["dept"] = kw
        return DeptRun()

    monkeypatch.setattr(cli, "update_awards", fake_awards)
    monkeypatch.setattr(cli, "update_statuses", fake_statuses)
    monkeypatch.setattr(cli, "update_depts", fake_depts)
    secrets = Secrets(
        g2b_api_key="g", naver_client_id=None, naver_client_secret=None, anthropic_api_key=None
    )
    monkeypatch.setattr(cli, "load_secrets", lambda path: secrets)
    db = tmp_path / "r.db"
    result = CliRunner().invoke(cli.app, ["run", "project", "82", "--db", str(db)])
    assert result.exit_code == 0, result.output
    assert {k: v["project_id"] for k, v in seen.items()} == {"award": 82, "status": 82, "dept": 82}
    c = connect(db)
    rows = c.execute(
        "SELECT command, args, status FROM run_log WHERE command LIKE 'enrich %' ORDER BY id"
    ).fetchall()
    c.close()
    assert [tuple(r) for r in rows] == [
        ("enrich award", "--tier all --project 82", "ok"),
        ("enrich status", "--tier all --project 82", "ok"),
        ("enrich dept", "--tier all --project 82", "ok"),
    ]
