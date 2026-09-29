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
