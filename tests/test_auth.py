"""로그인 계정 — 비밀번호는 해시로만, 실패가 쌓이면 잠근다."""

from datetime import datetime, timedelta

import pytest
from typer.testing import CliRunner

from nara.auth import (
    BAD_LOGIN,
    LOCKED,
    add_user,
    authenticate,
    change_password,
    get_user,
    list_users,
    reset_password,
    set_active,
)
from nara.cli import app as cli_app
from nara.db import connect, migrate

NOW = "2026-09-28T09:00:00"
T0 = datetime(2026, 9, 28, 9, 0, 0)


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "a.db")
    migrate(c)
    return c


def _ready(conn, email="kim@example.com", password="correct horse 1"):
    """임시 비밀번호로 만든 뒤 사용자가 비밀번호를 바꾼 상태."""
    temp = add_user(conn, email, "김지헌", NOW)
    uid = conn.execute("SELECT id FROM app_user WHERE email = ?", (email,)).fetchone()[0]
    assert change_password(conn, uid, temp, password, NOW) is None
    return uid


def test_add_user_stores_only_a_hash_and_asks_for_a_new_password(conn):
    temp = add_user(conn, " Kim@Example.com ", "김지헌", NOW)
    row = conn.execute("SELECT email, password_hash, must_change FROM app_user").fetchone()
    assert row["email"] == "kim@example.com"
    assert temp not in row["password_hash"]
    assert row["password_hash"].startswith("scrypt:")
    assert row["must_change"] == 1
    assert len(temp) == 16


def test_add_user_refuses_a_duplicate_and_a_non_email(conn):
    add_user(conn, "kim@example.com", "김", NOW)
    with pytest.raises(ValueError, match="이미"):
        add_user(conn, "KIM@example.com", "김", NOW)
    with pytest.raises(ValueError, match="이메일"):
        add_user(conn, "kim", "김", NOW)


def test_authenticate_accepts_the_right_password(conn):
    uid = _ready(conn)
    user, error = authenticate(conn, "KIM@example.com", "correct horse 1", T0)
    assert error is None
    assert (user.id, user.must_change) == (uid, False)


def test_authenticate_uses_one_message_for_every_failure(conn):
    """어떤 이메일이 등록됐는지 드러나지 않게 한다."""
    _ready(conn)
    _ready(conn, "off@example.com")
    set_active(conn, "off@example.com", False)
    for email, password in (
        ("kim@example.com", "wrong password"),
        ("nobody@example.com", "correct horse 1"),
        ("off@example.com", "correct horse 1"),
    ):
        assert authenticate(conn, email, password, T0) == (None, BAD_LOGIN)


def test_authenticate_compares_the_password_exactly(conn):
    """앞뒤 공백·한글을 몰래 다듬으면 만든 비밀번호로 로그인이 안 된다."""
    _ready(conn, password=" 한글 비밀번호 12 ")
    assert authenticate(conn, "kim@example.com", " 한글 비밀번호 12 ", T0)[1] is None
    assert authenticate(conn, "kim@example.com", "한글 비밀번호 12", T0)[1] == BAD_LOGIN


def test_five_failures_in_fifteen_minutes_lock_the_email(conn):
    _ready(conn)
    for i in range(5):
        authenticate(conn, "kim@example.com", "wrong", T0 + timedelta(minutes=i))
    assert authenticate(conn, "kim@example.com", "correct horse 1", T0 + timedelta(minutes=5)) == (
        None,
        LOCKED,
    )
    later = T0 + timedelta(minutes=4, seconds=1) + timedelta(minutes=15)
    assert authenticate(conn, "kim@example.com", "correct horse 1", later)[1] is None


def test_a_success_clears_earlier_failures(conn):
    _ready(conn)
    for i in range(4):
        authenticate(conn, "kim@example.com", "wrong", T0 + timedelta(seconds=i))
    authenticate(conn, "kim@example.com", "correct horse 1", T0 + timedelta(seconds=5))
    authenticate(conn, "kim@example.com", "wrong", T0 + timedelta(seconds=6))
    assert (
        authenticate(conn, "kim@example.com", "correct horse 1", T0 + timedelta(seconds=7))[1]
        is None
    )


def test_change_password_rules(conn):
    temp = add_user(conn, "kim@example.com", "김", NOW)
    uid = conn.execute("SELECT id FROM app_user").fetchone()[0]
    assert (
        change_password(conn, uid, "wrong", "long enough 1", NOW) == "지금 비밀번호가 맞지 않습니다"
    )
    assert change_password(conn, uid, temp, "short", NOW) == "비밀번호는 10자 이상이어야 합니다"
    assert change_password(conn, uid, temp, temp, NOW) == "지금 비밀번호와 달라야 합니다"
    assert change_password(conn, uid, temp, "long enough 1", NOW) is None
    assert get_user(conn, uid).must_change is False


def test_reset_gives_a_new_temporary_password_and_unlocks(conn):
    _ready(conn)
    for i in range(5):
        authenticate(conn, "kim@example.com", "wrong", T0 + timedelta(seconds=i))
    temp = reset_password(conn, "kim@example.com", NOW)
    user, error = authenticate(conn, "kim@example.com", temp, T0 + timedelta(seconds=10))
    assert error is None
    assert user.must_change is True


def test_get_user_ignores_a_disabled_account(conn):
    uid = _ready(conn)
    set_active(conn, "kim@example.com", False)
    assert get_user(conn, uid) is None
    assert [r["email"] for r in list_users(conn)] == ["kim@example.com"]


def test_migrate_adds_the_user_column_to_an_older_edit_log(tmp_path):
    """2단계 때 만든 DB의 edit_log에는 user_id가 없다."""
    c = connect(tmp_path / "old.db")
    migrate(c)
    c.execute("DROP TABLE edit_log")
    c.execute(
        "CREATE TABLE edit_log (id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL, "
        "field TEXT NOT NULL, old_value TEXT, new_value TEXT, edited_at TEXT NOT NULL)"
    )
    c.commit()
    migrate(c)
    columns = [r[1] for r in c.execute("PRAGMA table_info(edit_log)")]
    assert "user_id" in columns


def _cli(*args):
    return CliRunner().invoke(cli_app, list(args))


def test_user_commands_add_list_reset_and_disable(tmp_path):
    db = str(tmp_path / "u.db")
    added = _cli("user", "add", "Kim@Example.com", "--name", "김지헌", "--db", db)
    assert added.exit_code == 0, added.output
    assert "임시 비밀번호" in added.output
    listed = _cli("user", "list", "--db", db)
    assert "kim@example.com" in listed.output
    assert "김지헌" in listed.output
    assert _cli("user", "reset", "kim@example.com", "--db", db).exit_code == 0
    assert _cli("user", "disable", "kim@example.com", "--db", db).exit_code == 0
    assert "사용 중지" in _cli("user", "list", "--db", db).output


def test_user_commands_explain_a_failure(tmp_path):
    db = str(tmp_path / "u.db")
    _cli("user", "add", "kim@example.com", "--name", "김", "--db", db)
    dup = _cli("user", "add", "kim@example.com", "--name", "김", "--db", db)
    assert dup.exit_code == 1
    assert "이미" in dup.output
    missing = _cli("user", "reset", "nobody@example.com", "--db", db)
    assert missing.exit_code == 1
    assert "없는 계정" in missing.output
