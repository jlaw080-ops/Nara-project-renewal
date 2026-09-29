"""로그인 계정. 비밀번호는 scrypt 해시로만 두고, 실패가 쌓이면 잠근다."""

import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta

from werkzeug.security import check_password_hash, generate_password_hash

MIN_PASSWORD = 10
LOCK_ATTEMPTS = 5
LOCK_WINDOW = timedelta(minutes=15)
BAD_LOGIN = "이메일 또는 비밀번호가 맞지 않습니다"
LOCKED = "잠시 뒤 다시 시도하세요"
_METHOD = "scrypt"
# 없는 이메일에도 해시 비교를 한 번 해 응답 시간으로 계정 유무가 드러나지 않게 한다.
_DUMMY_HASH = generate_password_hash("not-a-real-password", method=_METHOD)


@dataclass(frozen=True)
class User:
    id: int
    email: str
    name: str
    must_change: bool


def normalize_email(raw: str) -> str:
    return (raw or "").strip().lower()


def _hash(password: str) -> str:
    return generate_password_hash(password, method=_METHOD)


def _temp_password() -> str:
    return secrets.token_urlsafe(12)  # 16자


def _find(conn: sqlite3.Connection, address: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM app_user WHERE email = ?", (address,)).fetchone()


def add_user(conn: sqlite3.Connection, email: str, name: str, now: str) -> str:
    """계정을 만들고 임시 비밀번호를 돌려준다. 첫 로그인에서 바꾸게 한다."""
    address = normalize_email(email)
    if "@" not in address or len(address) > 254:
        raise ValueError(f"이메일 형식이 아니다: {email!r}")
    if _find(conn, address) is not None:
        raise ValueError(f"이미 있는 계정이다: {address}")
    temp = _temp_password()
    conn.execute(
        "INSERT INTO app_user (email, name, password_hash, must_change, active, created_at) "
        "VALUES (?, ?, ?, 1, 1, ?)",
        (address, name.strip(), _hash(temp), now),
    )
    conn.commit()
    return temp


def reset_password(conn: sqlite3.Connection, email: str, now: str) -> str:
    """임시 비밀번호를 다시 만들고 잠금을 푼다."""
    address = normalize_email(email)
    if _find(conn, address) is None:
        raise ValueError(f"없는 계정이다: {address}")
    temp = _temp_password()
    conn.execute(
        "UPDATE app_user SET password_hash = ?, must_change = 1 WHERE email = ?",
        (_hash(temp), address),
    )
    conn.execute("DELETE FROM login_attempt WHERE email = ?", (address,))
    conn.commit()
    return temp


def set_active(conn: sqlite3.Connection, email: str, active: bool) -> None:
    address = normalize_email(email)
    if _find(conn, address) is None:
        raise ValueError(f"없는 계정이다: {address}")
    conn.execute("UPDATE app_user SET active = ? WHERE email = ?", (int(active), address))
    conn.commit()


def list_users(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT email, name, active, last_login_at FROM app_user ORDER BY email"
    ).fetchall()


def _user(row: sqlite3.Row) -> User:
    return User(row["id"], row["email"], row["name"], bool(row["must_change"]))


def get_user(conn: sqlite3.Connection, user_id: int) -> User | None:
    """사용 중인 계정만. 중지된 계정의 세션은 여기서 끊긴다."""
    row = conn.execute("SELECT * FROM app_user WHERE id = ? AND active = 1", (user_id,)).fetchone()
    return _user(row) if row is not None else None


def _locked(conn: sqlite3.Connection, address: str, now: datetime) -> bool:
    since = (now - LOCK_WINDOW).isoformat(timespec="seconds")
    failures = conn.execute(
        "SELECT COUNT(*) FROM login_attempt WHERE email = ? AND ok = 0 AND at >= ?",
        (address, since),
    ).fetchone()[0]
    return failures >= LOCK_ATTEMPTS


def authenticate(
    conn: sqlite3.Connection, email: str, password: str, now: datetime
) -> tuple[User | None, str | None]:
    """(사용자, None) 또는 (None, 화면에 보일 문구).

    비밀번호는 친 그대로 비교한다 — 다듬으면 만든 비밀번호로 로그인이 안 된다.
    """
    address = normalize_email(email)
    stamp = now.isoformat(timespec="seconds")
    if _locked(conn, address, now):
        return None, LOCKED
    row = _find(conn, address)
    stored = row["password_hash"] if row is not None else _DUMMY_HASH
    ok = check_password_hash(stored, password) and row is not None and bool(row["active"])
    if ok:
        conn.execute("DELETE FROM login_attempt WHERE email = ? AND ok = 0", (address,))
        conn.execute("UPDATE app_user SET last_login_at = ? WHERE id = ?", (stamp, row["id"]))
    conn.execute(
        "INSERT INTO login_attempt (email, ok, at) VALUES (?, ?, ?)", (address, int(ok), stamp)
    )
    conn.commit()
    return (_user(row), None) if ok else (None, BAD_LOGIN)


def change_password(
    conn: sqlite3.Connection, user_id: int, current: str, new: str, now: str
) -> str | None:
    """바꾸면 None, 못 바꾸면 화면에 보일 문구."""
    row = conn.execute("SELECT password_hash FROM app_user WHERE id = ?", (user_id,)).fetchone()
    if row is None or not check_password_hash(row["password_hash"], current):
        return "지금 비밀번호가 맞지 않습니다"
    if len(new) < MIN_PASSWORD:
        return f"비밀번호는 {MIN_PASSWORD}자 이상이어야 합니다"
    if check_password_hash(row["password_hash"], new):
        return "지금 비밀번호와 달라야 합니다"
    conn.execute(
        "UPDATE app_user SET password_hash = ?, must_change = 0 WHERE id = ?",
        (_hash(new), user_id),
    )
    conn.commit()
    return None
