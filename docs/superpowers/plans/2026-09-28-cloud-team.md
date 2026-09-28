# 클라우드 배포·로그인·팀 공유(3단계) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 조회·입력 화면에 사람별 로그인·동시 수정 확인을 붙이고, 수집 슬롯·백업 명령과 서버 설치 파일을 만들어 무료 클라우드 서버 한 대에서 팀이 쓰게 한다.

**Architecture:** 계정·로그인 규칙은 `nara/auth.py`, 수집 순서와 겹침 방지는 `nara/slot.py`, 백업은 `nara/backup.py`가 맡는다. 셋 다 DB·파일만 알고 HTTP를 모른다. 웹은 `create_app(db_path, secret_key, host)`로 서명 키와 서버 주소를 받아 로그인 검사·세션·프록시 설정을 건다. 서버 설치는 `deploy/`의 systemd·Caddy 파일과 `setup.md`가 맡는다.

**Tech Stack:** Python 3.14, SQLite, Flask 3.1.3(Werkzeug scrypt 해시·ProxyFix), waitress(새 의존성), Typer, pytest, ruff, systemd, Caddy, rclone.

**Spec:** `docs/superpowers/specs/2026-09-28-cloud-team-design.md`

## Global Constraints

- 비밀값(`G2B_API_KEY`, `ANTHROPIC_API_KEY`, `NARA_SECRET_KEY`, `NARA_HOST`, `NARA_BACKUP_REMOTE`)은 `.env`에만 둔다. 저장소(공개)의 어떤 파일에도 값을 적지 않는다
- 세션 서명 키가 없으면 앱이 뜨지 않는다. 기본값으로 대신하지 않는다
- 비밀번호는 Werkzeug `generate_password_hash(..., method="scrypt")`로만 저장한다
- 새 비밀번호 10자 이상. 같은 이메일로 15분 안에 실패 5번이면 15분 잠금
- 로그인 실패 문구는 하나: "이메일 또는 비밀번호가 맞지 않습니다". 잠금만 "잠시 뒤 다시 시도하세요"
- 세션 쿠키: `HttpOnly`, `SameSite=Lax`, `Secure`(서버 주소가 있을 때), 14일
- 조회는 계속 `mode=ro` 연결, 저장·로그인 기록은 `mode=rw` 연결
- 앱은 `127.0.0.1`에만 연다. 밖에서는 Caddy를 거쳐 HTTPS로만 들어온다
- 코드 스타일: ruff line-length 100, 규칙 E·F·I·UP·B. 테스트는 `PYTHONIOENCODING=utf-8 uv run pytest`
- 커밋 메시지는 한국어 `<type>: <설명>`, 끝에 `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`
- 원본 `data/nara.db`와 사용자 `.env`에는 쓰지 않는다. 실데이터 확인은 사본과 임시 `.env`로 한다

## Review Focus

1. **로그인 뒤 돌아갈 주소(`next`)가 바깥 주소**(`//evil.example`, `https://evil.example`, `/\evil.example`) — 기대: 목록으로 보낸다. 로그인 화면이 남의 사이트로 튕기는 발판이 되면 안 된다 → Task 3
2. **Caddy 뒤에서 요청이 http로 들어온다** — 브라우저 `Origin`은 `https://…`인데 앱이 보는 주소는 `http://…`라 같은 출처 확인이 모든 저장을 403으로 막는다. 기대: `X-Forwarded-Proto: https`를 믿어 저장된다 → Task 3
3. **비밀번호에 앞뒤 공백·한글** — 기대: 친 그대로 비교한다. 몰래 잘라내면 만든 비밀번호로 로그인이 안 된다 → Task 1
4. **백업하는 동안 수집이 쓰는 중** — 기대: 백업이 깨지지 않고, 아직 커밋되지 않은 줄은 들어가지 않는다 → Task 7
5. **슬롯이 도중에 죽어 겹침 표시가 남는다** — 기대: 2시간이 지나면 다음 슬롯이 표시를 무시하고 돈다. 영영 멈추면 안 된다 → Task 6

---

## 파일 구조

| 파일 | 책임 |
|---|---|
| `pyproject.toml` | `docs/`를 ruff 대상에서 뺀다, `waitress` 의존성 |
| `nara/schema.sql`, `nara/db.py` | `app_user`·`login_attempt` 표, `edit_log.user_id` 칸(옛 DB는 `ALTER`) |
| `nara/config.py` | `Secrets`에 `secret_key`·`host`·`backup_remote` |
| `nara/auth.py` (새) | 계정 추가·재발급·중지·목록, 로그인, 비밀번호 바꾸기 |
| `nara/slot.py` (새) | 슬롯 단계 순서, 겹침 표시 |
| `nara/backup.py` (새) | 백업본 만들기·정리·올리기 |
| `nara/cli.py` | `user`·`run slot`·`backup` 명령, `serve --env --production` |
| `nara/web/app.py` | 로그인·로그아웃·비밀번호 바꾸기, 로그인 검사, 세션·프록시 설정, 누가·버전 확인 |
| `nara/web/edit.py` | 저장에 `user_id`, 잠금 해제 기록, 버전 표시·마지막 수정자 |
| `nara/web/data.py` | 수정 이력에 이름, 단계에 백업 |
| `nara/web/templates/*.html` | 로그인·비밀번호 화면, 머리의 이름·로그아웃, 폼의 버전, 이력의 "누가" |
| `deploy/*` (새) | systemd 서비스·타이머, Caddyfile, `update.sh`, `setup.md` |
| `tests/test_auth.py`·`test_slot.py`·`test_backup.py` (새), `tests/test_web.py`·`test_web_edit.py` | 테스트 |

---

### Task 1: 계정 표와 로그인 규칙

**Files:**
- Modify: `pyproject.toml`, `nara/schema.sql`, `nara/db.py`, `nara/config.py`
- Create: `nara/auth.py`, `tests/test_auth.py`

**Interfaces:**
- Produces (`nara.auth`): `MIN_PASSWORD = 10`, `LOCK_ATTEMPTS = 5`, `LOCK_WINDOW = timedelta(minutes=15)`, `BAD_LOGIN`, `LOCKED`, `@dataclass(frozen=True) User(id, email, name, must_change)`, `normalize_email(raw) -> str`, `add_user(conn, email, name, now: str) -> str`(임시 비밀번호), `reset_password(conn, email, now: str) -> str`, `set_active(conn, email, active: bool) -> None`, `list_users(conn) -> list[Row]`, `get_user(conn, user_id) -> User | None`, `authenticate(conn, email, password, now: datetime) -> tuple[User | None, str | None]`, `change_password(conn, user_id, current, new, now: str) -> str | None`(오류 문구)
- Produces (`nara.config.Secrets`): `secret_key`, `host`, `backup_remote` — 기본값 None
- Produces (DB): `app_user`, `login_attempt`, `edit_log.user_id`

- [ ] **Step 1: ruff가 문서를 건드리지 않게 한다**

`pyproject.toml`의 `[tool.ruff]` 표에 한 줄을 더한다(`target-version = "py314"` 아래):

```toml
# 계획 문서의 코드 조각을 ruff가 고쳐 쓰면 뜻이 바뀐다(2단계 Task 7에서 실제로 깨졌다).
extend-exclude = ["docs"]
```

- [ ] **Step 2: 실패하는 테스트를 쓴다**

`tests/test_auth.py`:

```python
"""로그인 계정 — 비밀번호는 해시로만, 실패가 쌓이면 잠근다."""

from datetime import datetime, timedelta

import pytest

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
    assert authenticate(conn, "kim@example.com", "correct horse 1", T0 + timedelta(seconds=7))[
        1
    ] is None


def test_change_password_rules(conn):
    temp = add_user(conn, "kim@example.com", "김", NOW)
    uid = conn.execute("SELECT id FROM app_user").fetchone()[0]
    assert change_password(conn, uid, "wrong", "long enough 1", NOW) == "지금 비밀번호가 맞지 않습니다"
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
```

- [ ] **Step 3: 실패를 확인한다**

Run: `PYTHONIOENCODING=utf-8 uv run pytest tests/test_auth.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'nara.auth'`

- [ ] **Step 4: 표를 더한다**

`nara/schema.sql`의 `CREATE TABLE IF NOT EXISTS edit_log (` 표에서 `edited_at  TEXT NOT NULL` 줄을 이것으로 바꾼다:

```sql
  edited_at  TEXT NOT NULL,
  user_id    INTEGER REFERENCES app_user(id)
```

같은 파일의 `INSERT OR IGNORE INTO energy_unit_price` 줄 **위**에 더한다:

```sql
CREATE TABLE IF NOT EXISTS app_user (
  id            INTEGER PRIMARY KEY,
  email         TEXT NOT NULL UNIQUE,
  name          TEXT NOT NULL,
  password_hash TEXT NOT NULL,
  must_change   INTEGER NOT NULL DEFAULT 1,
  active        INTEGER NOT NULL DEFAULT 1,
  created_at    TEXT NOT NULL,
  last_login_at TEXT
);

CREATE TABLE IF NOT EXISTS login_attempt (
  id    INTEGER PRIMARY KEY,
  email TEXT NOT NULL,
  ok    INTEGER NOT NULL,
  at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_login_email ON login_attempt(email, at);

```

`nara/db.py`의 `migrate`에서 `conn.executescript(sql)` 바로 아래에 더한다:

```python
    # CREATE TABLE IF NOT EXISTS는 이미 있는 표에 칸을 더하지 않는다. 2단계 때 만든 DB용.
    _add_column(conn, "edit_log", "user_id", "INTEGER REFERENCES app_user(id)")
```

`migrate` 위에 함수를 더한다:

```python
def _add_column(conn: sqlite3.Connection, table: str, column: str, decl: str) -> None:
    """표에 칸이 없으면 더한다. table·column은 이 파일의 고정 값만 받는다."""
    columns = [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
```

`nara/config.py`의 `Secrets`에서 `anthropic_api_key: str | None` 아래에 더한다:

```python
    secret_key: str | None = None
    host: str | None = None
    backup_remote: str | None = None
```

`load_secrets`의 `anthropic_api_key=pick("ANTHROPIC_API_KEY"),` 아래에 더한다:

```python
        secret_key=pick("NARA_SECRET_KEY"),
        host=pick("NARA_HOST"),
        backup_remote=pick("NARA_BACKUP_REMOTE"),
```

- [ ] **Step 5: 계정 모듈을 만든다**

`nara/auth.py`:

```python
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
    row = conn.execute(
        "SELECT * FROM app_user WHERE id = ? AND active = 1", (user_id,)
    ).fetchone()
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
```

- [ ] **Step 6: 통과를 확인한다**

Run: `PYTHONIOENCODING=utf-8 uv run pytest tests/test_auth.py -v`
Expected: PASS (11개)

- [ ] **Step 7: 전체 검사**

```bash
uv run ruff check --fix .
uv run ruff format .
PYTHONIOENCODING=utf-8 uv run pytest -q
uv run ruff check .
uv run ruff format --check .
```

- [ ] **Step 8: 커밋**

```bash
git add pyproject.toml nara/schema.sql nara/db.py nara/config.py nara/auth.py tests/test_auth.py
git commit -m "feat: 로그인 계정 — 비밀번호는 해시로만, 실패가 쌓이면 잠근다

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: 계정 관리 명령

**Files:**
- Modify: `nara/cli.py`
- Modify: `tests/test_auth.py`

**Interfaces:**
- Consumes: Task 1의 `add_user`, `reset_password`, `set_active`, `list_users`, `normalize_email`
- Produces: `nara user add <이메일> --name <이름>`, `nara user reset <이메일>`, `nara user disable <이메일>`, `nara user list` (모두 `--db`)

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_auth.py`의 import 묶음에 더한다:

```python
from typer.testing import CliRunner

from nara.cli import app as cli_app
```

파일 끝에 더한다:

```python
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
```

- [ ] **Step 2: 실패를 확인한다**

Run: `PYTHONIOENCODING=utf-8 uv run pytest tests/test_auth.py -v -k user_commands`
Expected: FAIL — `No such command 'user'`로 exit 2

- [ ] **Step 3: 구현한다**

`nara/cli.py`의 import 묶음에 더한다:

```python
from nara.auth import add_user, list_users, normalize_email, reset_password, set_active
```

`migrate_app = typer.Typer(` 줄 **위**에 더한다:

```python
user_app = typer.Typer(help="로그인 계정을 관리한다")
app.add_typer(user_app, name="user")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _fail(exc: ValueError) -> typer.Exit:
    typer.echo(str(exc), err=True)
    return typer.Exit(code=1)


@user_app.command("add")
def user_add(
    email: str = typer.Argument(..., help="로그인 이메일"),
    name: str = typer.Option(..., help="화면에 보일 이름"),
    db: Path = typer.Option(DEFAULT_DB),
) -> None:
    """계정을 만들고 임시 비밀번호를 한 번만 보인다."""
    conn = _open_db(db)
    try:
        temp = add_user(conn, email, name, _now())
    except ValueError as exc:
        raise _fail(exc) from exc
    typer.echo(f"계정을 만들었다: {normalize_email(email)}")
    typer.echo(f"임시 비밀번호(한 번만 보인다): {temp}")
    typer.echo("첫 로그인에서 비밀번호를 바꾸게 된다.")


@user_app.command("reset")
def user_reset(
    email: str = typer.Argument(...),
    db: Path = typer.Option(DEFAULT_DB),
) -> None:
    """임시 비밀번호를 다시 만들고 잠금을 푼다."""
    conn = _open_db(db)
    try:
        temp = reset_password(conn, email, _now())
    except ValueError as exc:
        raise _fail(exc) from exc
    typer.echo(f"임시 비밀번호(한 번만 보인다): {temp}")


@user_app.command("disable")
def user_disable(
    email: str = typer.Argument(...),
    db: Path = typer.Option(DEFAULT_DB),
) -> None:
    """로그인을 막는다. 수정 기록은 남긴다."""
    conn = _open_db(db)
    try:
        set_active(conn, email, False)
    except ValueError as exc:
        raise _fail(exc) from exc
    typer.echo(f"사용 중지: {normalize_email(email)}")


@user_app.command("list")
def user_list(db: Path = typer.Option(DEFAULT_DB)) -> None:
    """계정 목록."""
    conn = _open_db(db)
    for row in list_users(conn):
        state = "사용" if row["active"] else "사용 중지"
        last = row["last_login_at"] or "로그인 기록 없음"
        typer.echo(f"{row['email']}\t{row['name']}\t{state}\t{last}")
```

- [ ] **Step 4: 통과를 확인한다**

Run: `PYTHONIOENCODING=utf-8 uv run pytest tests/test_auth.py -v`
Expected: PASS (13개)

- [ ] **Step 5: 전체 검사**

```bash
uv run ruff check --fix .
uv run ruff format .
PYTHONIOENCODING=utf-8 uv run pytest -q
uv run ruff check .
uv run ruff format --check .
```

- [ ] **Step 6: 커밋**

```bash
git add nara/cli.py tests/test_auth.py
git commit -m "feat: nara user — 계정 추가·재발급·중지·목록

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: 웹 로그인

**Files:**
- Modify: `nara/web/app.py`, `nara/web/templates/base.html`
- Create: `nara/web/templates/login.html`, `nara/web/templates/password.html`
- Modify: `tests/test_web.py`

**Interfaces:**
- Consumes: Task 1의 `auth` 모듈
- Produces: `create_app(db_path: Path, secret_key: str, host: str | None = None) -> Flask`. 라우트 `login`(`GET·POST /login`), `logout`(`POST /logout`), `change_password`(`GET·POST /password`). 요청 중 `g.user: auth.User`

- [ ] **Step 1: 테스트 도우미를 로그인하게 바꾼다**

`tests/test_web.py`의 import 묶음에 더한다:

```python
from werkzeug.security import generate_password_hash

from nara.auth import BAD_LOGIN, LOCKED, add_user
```

`_client` 함수 **전체**를 이것으로 바꾼다:

```python
SECRET = "test-secret-key"
TEST_EMAIL = "tester@example.com"
TEST_PASSWORD = "correct horse battery"
ORIGIN = {"Origin": "http://localhost"}


def _ensure_user(path, email=TEST_EMAIL, name="시험", password=TEST_PASSWORD):
    conn = connect(path)
    try:
        if not conn.execute("SELECT 1 FROM app_user WHERE email = ?", (email,)).fetchone():
            add_user(conn, email, name, NOW)
        conn.execute(
            "UPDATE app_user SET password_hash = ?, must_change = 0 WHERE email = ?",
            (generate_password_hash(password, method="scrypt"), email),
        )
        conn.commit()
    finally:
        conn.close()


def _app(path, **config):
    app = create_app(path, secret_key=SECRET)
    app.testing = True
    app.config.update(config)
    return app


def _login(client, path, email=TEST_EMAIL, password=TEST_PASSWORD):
    if path.exists():  # 없는 DB에 connect하면 파일이 생긴다
        _ensure_user(path, email=email, password=password)
    return client.post("/login", data={"email": email, "password": password}, headers=ORIGIN)


def _client(path, **config):
    client = _app(path, **config).test_client()
    _login(client, path)
    return client
```

`test_the_app_opens_the_database_read_only` 안의 `app = create_app(world[0])`를 `app = _app(world[0])`로 바꾼다.

`test_saving_while_the_collector_writes_keeps_the_input` 안의 다음 네 줄

```python
    app = create_app(path)
    app.testing = True
    app.config["WRITE_TIMEOUT"] = 0.2
    blocker = sqlite3.connect(path)
```

을 이것으로 바꾸고, 같은 테스트의 `app.test_client()`를 `client`로 바꾼다:

```python
    client = _client(path, WRITE_TIMEOUT=0.2)
    blocker = sqlite3.connect(path)
```

`test_release_while_the_collector_writes_says_so` 안의 다음 네 줄

```python
    app = create_app(path)
    app.testing = True
    app.config["WRITE_TIMEOUT"] = 0.2
    client = app.test_client()
```

을 `    client = _client(path, WRITE_TIMEOUT=0.2)` 한 줄로 바꾼다.

- [ ] **Step 2: 실패하는 테스트를 쓴다**

`tests/test_web.py` 끝에 더한다:

```python
def test_every_page_asks_for_login_first(world):
    path, ids = world
    client = _app(path).test_client()
    for url in ("/", f"/project/{ids['gym']}"):
        resp = client.get(url)
        assert resp.status_code == 302
        assert resp.headers["Location"].startswith("/login")
    post = client.post(f"/project/{ids['gym']}/edit/info", data={}, headers=ORIGIN)
    assert post.status_code == 302


def test_login_failures_share_one_message(world):
    path, _ = world
    _ensure_user(path)
    client = _app(path).test_client()
    for email, password in ((TEST_EMAIL, "wrong one"), ("nobody@example.com", TEST_PASSWORD)):
        resp = client.post("/login", data={"email": email, "password": password}, headers=ORIGIN)
        assert resp.status_code == 401
        assert BAD_LOGIN in _text(resp)


def test_login_locks_after_five_failures(world):
    path, _ = world
    _ensure_user(path)
    client = _app(path).test_client()
    for _ in range(5):
        client.post("/login", data={"email": TEST_EMAIL, "password": "x"}, headers=ORIGIN)
    assert LOCKED in _text(_login(client, path))


def test_login_goes_back_to_the_page_only_inside_this_site(world):
    """로그인 화면이 남의 사이트로 튕기는 발판이 되면 안 된다."""
    path, ids = world
    _ensure_user(path)
    inside = f"/project/{ids['gym']}"
    for nxt, expected in (
        (inside, inside),
        ("//evil.example", "/"),
        ("https://evil.example", "/"),
        ("/\\evil.example", "/"),
    ):
        client = _app(path).test_client()
        resp = client.post(
            "/login",
            data={"email": TEST_EMAIL, "password": TEST_PASSWORD, "next": nxt},
            headers=ORIGIN,
        )
        assert resp.headers["Location"] == expected, nxt


def test_a_temporary_password_must_be_changed_first(world):
    path, _ = world
    conn = connect(path)
    temp = add_user(conn, "new@example.com", "신입", NOW)
    conn.close()
    client = _app(path).test_client()
    client.post("/login", data={"email": "new@example.com", "password": temp}, headers=ORIGIN)
    assert client.get("/").headers["Location"] == "/password"
    resp = client.post(
        "/password",
        data={"current": temp, "new": "brand new pass", "confirm": "brand new pass"},
        headers=ORIGIN,
    )
    assert resp.status_code == 302
    assert client.get("/").status_code == 200


def test_password_form_explains_a_mismatch(world):
    path, _ = world
    client = _client(path)
    resp = client.post(
        "/password",
        data={"current": TEST_PASSWORD, "new": "long enough 1", "confirm": "long enough 2"},
        headers=ORIGIN,
    )
    assert resp.status_code == 422
    assert "새 비밀번호 두 칸이 다릅니다" in _text(resp)


def test_logout_ends_the_session(world):
    path, _ = world
    client = _client(path)
    assert client.get("/").status_code == 200
    assert "시험" in _text(client.get("/"))
    client.post("/logout", headers=ORIGIN)
    assert client.get("/").status_code == 302


def test_a_disabled_account_loses_its_session(world):
    path, _ = world
    client = _client(path)
    conn = connect(path)
    conn.execute("UPDATE app_user SET active = 0")
    conn.commit()
    conn.close()
    assert client.get("/").status_code == 302


def test_the_app_refuses_to_start_without_a_secret_key(world):
    with pytest.raises(ValueError, match="NARA_SECRET_KEY"):
        create_app(world[0], secret_key="")


def test_behind_caddy_https_origin_is_accepted(world):
    """Caddy 뒤에서는 요청이 http로 들어온다. https Origin과 어긋나면 모든 저장이 403이 된다."""
    path, _ = world
    _ensure_user(path)
    app = create_app(path, secret_key=SECRET, host="nara.example.org")
    app.testing = True
    client = app.test_client()
    resp = client.post(
        "/login",
        data={"email": TEST_EMAIL, "password": TEST_PASSWORD},
        headers={
            "Host": "nara.example.org",
            "Origin": "https://nara.example.org",
            "X-Forwarded-Proto": "https",
        },
    )
    assert resp.status_code == 302
    assert "Secure" in resp.headers["Set-Cookie"]
```

- [ ] **Step 3: 실패를 확인한다**

Run: `PYTHONIOENCODING=utf-8 uv run pytest tests/test_web.py -v`
Expected: FAIL — `TypeError: create_app() got an unexpected keyword argument 'secret_key'`

- [ ] **Step 4: 앱에 로그인을 붙인다**

`nara/web/app.py`의 import 묶음에서 다음 세 줄을 바꾼다:

```python
from datetime import datetime, timedelta
```

```python
from flask import (
    Flask,
    abort,
    current_app,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.middleware.proxy_fix import ProxyFix

from nara import auth
```

(`from datetime import datetime` 줄과 `from flask import Flask, abort, ...` 줄을 위 내용으로 바꾼다.)

`BLANK_ENERGY_ROWS = 3` 아래에 더한다:

```python
SESSION_LIFETIME = timedelta(days=14)
PUBLIC_ENDPOINTS = {"login", "static"}
PASSWORD_ENDPOINTS = {"change_password", "logout"}
```

`_same_origin` 아래에 더한다:

```python
def _safe_next(raw: str | None) -> str:
    """로그인 뒤 돌아갈 곳. 이 사이트 안의 경로만 받는다."""
    target = (raw or "").strip()
    if target.startswith("/") and not target.startswith(("//", "/\\")):
        return target
    return "/"


def _current_user() -> auth.User | None:
    uid = session.get("uid")
    if not isinstance(uid, int):
        return None
    return auth.get_user(get_conn(), uid)


def _rw_conn() -> sqlite3.Connection:
    return open_readwrite(current_app.config["DB_PATH"], current_app.config["WRITE_TIMEOUT"])
```

`create_app`의 첫 부분을 이렇게 바꾼다. 시그니처와 `app.config["WRITE_TIMEOUT"] = BUSY_TIMEOUT_SECONDS` 줄까지:

```python
def create_app(db_path: Path, secret_key: str, host: str | None = None) -> Flask:
    if not secret_key:
        raise ValueError("세션 서명 키가 없다 — .env의 NARA_SECRET_KEY를 채운다")
    app = Flask(__name__)
    app.secret_key = secret_key
    app.config["DB_PATH"] = Path(db_path)
    app.add_template_filter(_dash, "dash")
    app.add_template_filter(_won, "won")
    # DNS 리바인딩으로 외부 페이지가 이 화면을 읽지 못하게 한다.
    app.config["TRUSTED_HOSTS"] = ["127.0.0.1", "localhost", *([host] if host else [])]
    app.config["WRITE_TIMEOUT"] = BUSY_TIMEOUT_SECONDS
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=bool(host),
        PERMANENT_SESSION_LIFETIME=SESSION_LIFETIME,
    )
    if host:
        # Caddy 뒤에서는 요청이 http로 들어온다. 브라우저 Origin은 https라 그대로 두면
        # 같은 출처 확인이 모든 저장을 막는다. Caddy 한 단만 믿는다.
        app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1)
```

`_guard_writes` 함수 아래에 더한다:

```python
    @app.before_request
    def _require_login():
        if request.endpoint in PUBLIC_ENDPOINTS:
            return None
        user = _current_user()
        if user is None:
            session.clear()
            nxt = request.full_path.rstrip("?") if request.method == "GET" else None
            return redirect(url_for("login", next=nxt))
        g.user = user
        if user.must_change and request.endpoint not in PASSWORD_ENDPOINTS:
            return redirect(url_for("change_password"))
        return None

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "GET":
            nxt = request.args.get("next", "")
            return render_template("login.html", email="", error=None, next=nxt)
        email = request.form.get("email", "")
        with closing(_rw_conn()) as conn:
            user, error = auth.authenticate(
                conn, email, request.form.get("password", ""), datetime.now()
            )
        if user is None:
            nxt = request.form.get("next", "")
            return render_template("login.html", email=email, error=error, next=nxt), 401
        session.clear()
        session.permanent = True
        session["uid"] = user.id
        return redirect(_safe_next(request.form.get("next")))

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.route("/password", methods=["GET", "POST"])
    def change_password():
        if request.method == "GET":
            return render_template("password.html", error=None)
        new = request.form.get("new", "")
        if new != request.form.get("confirm", ""):
            return render_template("password.html", error="새 비밀번호 두 칸이 다릅니다"), 422
        with closing(_rw_conn()) as conn:
            error = auth.change_password(
                conn,
                g.user.id,
                request.form.get("current", ""),
                new,
                datetime.now().isoformat(timespec="seconds"),
            )
        if error:
            return render_template("password.html", error=error), 422
        return redirect(url_for("index"))
```

- [ ] **Step 5: 화면을 더한다**

`nara/web/templates/login.html`:

```html
{% extends "base.html" %}
{% block title %}로그인{% endblock %}
{% block body %}
<h1>로그인</h1>
{% if error %}<p class="bad">{{ error }}</p>{% endif %}
<form method="post" class="edit-form" action="{{ url_for('login') }}">
  <input type="hidden" name="next" value="{{ next }}">
  <label>이메일 <input type="text" name="email" value="{{ email }}" autocomplete="username" inputmode="email"></label>
  <label>비밀번호 <input type="password" name="password" autocomplete="current-password"></label>
  <p><button type="submit">로그인</button></p>
</form>
<p class="muted">계정이 없거나 비밀번호를 잊었으면 관리자에게 요청하세요.</p>
{% endblock %}
```

`nara/web/templates/password.html`:

```html
{% extends "base.html" %}
{% block title %}비밀번호 바꾸기{% endblock %}
{% block body %}
<h1>비밀번호 바꾸기</h1>
{% if g.user and g.user.must_change %}<p class="saved">임시 비밀번호로 들어왔습니다. 새 비밀번호를 정하세요.</p>{% endif %}
{% if error %}<p class="bad">{{ error }}</p>{% endif %}
<form method="post" class="edit-form" action="{{ url_for('change_password') }}">
  <label>지금 비밀번호 <input type="password" name="current" autocomplete="current-password"></label>
  <label>새 비밀번호 <span class="muted">10자 이상</span> <input type="password" name="new" autocomplete="new-password"></label>
  <label>새 비밀번호 확인 <input type="password" name="confirm" autocomplete="new-password"></label>
  <p><button type="submit">바꾸기</button></p>
</form>
{% endblock %}
```

`nara/web/templates/base.html`의 `input[type=search], input[type=date], input[type=text], button {`를 `input[type=search], input[type=date], input[type=text], input[type=password], button {`로 바꾼다. 그리고 `<body>` 바로 아래에 더한다:

```html
{% if g.user %}
<p class="account muted">{{ g.user.name }} · <a href="{{ url_for('change_password') }}">비밀번호 바꾸기</a>
  <form method="post" class="inline" action="{{ url_for('logout') }}"><button type="submit">로그아웃</button></form></p>
{% endif %}
```

`.saved { ... }` 줄 아래에 더한다:

```css
  .account { display: flex; gap: 8px; align-items: center; justify-content: flex-end; margin: 0; }
```

- [ ] **Step 6: 통과를 확인한다**

Run: `PYTHONIOENCODING=utf-8 uv run pytest tests/test_web.py -v`
Expected: `serve` 테스트 3개를 뺀 전부 PASS(1·2단계 테스트는 로그인한 도우미로 그대로 통과). `serve` 테스트는 `create_app`이 서명 키를 요구해 실패한다 — Task 8이 고친다. 이 단계에서는 `-k "not serve"`로 확인한다:

Run: `PYTHONIOENCODING=utf-8 uv run pytest tests/test_web.py -q -k "not serve"`
Expected: PASS

- [ ] **Step 7: `serve`가 서명 키를 넘기게 한다(최소)**

`nara/cli.py`의 `serve`에서 `create_app(db).run(...)` 줄을 이것으로 바꾼다. Task 8이 `--env`와 서버 모드를 더한다:

```python
    secrets = load_secrets(DEFAULT_ENV)
    if not secrets.secret_key:
        typer.echo("NARA_SECRET_KEY가 .env에 없다 — 세션 서명 키 없이는 띄우지 않는다", err=True)
        raise typer.Exit(code=1)
    web = create_app(db, secret_key=secrets.secret_key, host=secrets.host)
    web.run(host="127.0.0.1", port=port, debug=False)
```

`tests/test_web.py`의 `test_serve_binds_to_this_computer_only_without_the_debugger`와 `test_serve_prepares_the_new_tables_on_an_older_database`에 `monkeypatch.setattr("nara.cli.DEFAULT_ENV", _env_file(tmp_path))`를 더해 임시 `.env`를 쓰게 한다. 두 테스트의 인자에 `tmp_path`를 더하고, `_client` 위에 도우미를 둔다:

```python
def _env_file(tmp_path, **values):
    path = tmp_path / ".env"
    pairs = {"NARA_SECRET_KEY": "test-secret-key", **values}
    path.write_text("".join(f"{k}={v}\n" for k, v in pairs.items()), encoding="utf-8")
    return path
```

Run: `PYTHONIOENCODING=utf-8 uv run pytest tests/test_web.py -v`
Expected: PASS 전부

- [ ] **Step 8: 전체 검사**

```bash
uv run ruff check --fix .
uv run ruff format .
PYTHONIOENCODING=utf-8 uv run pytest -q
uv run ruff check .
uv run ruff format --check .
```

- [ ] **Step 9: 커밋**

```bash
git add nara/web/app.py nara/web/templates nara/cli.py tests/test_web.py
git commit -m "feat: 웹 로그인 — 로그인하지 않으면 모든 화면이 로그인으로 간다

세션은 서명 쿠키이고 서명 키가 없으면 앱이 뜨지 않는다. 로그인 뒤 돌아갈
주소는 이 사이트 안만 받는다. Caddy 뒤에서는 https Origin을 받도록
X-Forwarded-Proto를 한 단만 믿는다. 임시 비밀번호로 들어오면 먼저
비밀번호를 바꾸게 한다.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: 누가 고쳤나

**Files:**
- Modify: `nara/web/edit.py`, `nara/web/app.py`, `nara/web/data.py`, `nara/sheet_memory.py`, `nara/web/templates/detail.html`
- Modify: `tests/test_web.py`

**Interfaces:**
- Consumes: Task 3의 `g.user`
- Produces: `save_info/save_verdict/save_dept/save_energy/release_verdict`에 마지막 인자 `user_id: int | None = None`. 잠금 해제는 `edit_log`에 칸 `verdict_release`로 남는다. `ProjectDetail.edits` 행에 `user_name`

잠금 해제를 칸 `verdict`로 남기면 2단계의 `edited_on_web("verdict")`가 참이 되어, 다음 시트 판정 변경이 거짓 충돌로 보고된다. 그래서 칸 이름을 따로 둔다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_web.py` 끝에 더한다:

```python
def _tester_id(path):
    conn = connect(path)
    uid = conn.execute("SELECT id FROM app_user WHERE email = ?", (TEST_EMAIL,)).fetchone()[0]
    conn.close()
    return uid


def test_every_web_change_records_who_made_it(world):
    path, ids = world
    client = _client(path)
    url = f"/project/{ids['gym']}"
    _post(client, f"/project/{ids['culture']}/edit/info", _info(floor_area="500"))
    _post(client, f"{url}/edit/verdict", {"verdict": BUILDING, "reason": "현장 확인"})
    _post(client, f"{url}/release", {})
    conn = connect(path)
    rows = conn.execute("SELECT field, user_id FROM edit_log ORDER BY id").fetchall()
    conn.close()
    uid = _tester_id(path)
    assert [tuple(r) for r in rows] == [
        ("floor_area", uid),
        ("verdict", uid),
        ("verdict_release", uid),
    ]


def test_edit_history_shows_names_and_marks_older_records(world):
    path, ids = world
    client = _client(path)
    conn = connect(path)
    conn.execute(
        "INSERT INTO edit_log (project_id, field, old_value, new_value, edited_at) "
        "VALUES (?, 'note', NULL, '옛 기록', '2026-09-27T09:00:00')",
        (ids["culture"],),
    )
    conn.commit()
    conn.close()
    _post(client, f"/project/{ids['culture']}/edit/info", _info(floor_area="500"))
    text = _text(client.get(f"/project/{ids['culture']}"))
    assert "시험" in text
    assert "(2단계 기록)" in text
```

- [ ] **Step 2: 실패를 확인한다**

Run: `PYTHONIOENCODING=utf-8 uv run pytest tests/test_web.py -v -k "who_made_it or shows_names"`
Expected: FAIL — `user_id`가 None

- [ ] **Step 3: 저장 함수에 사용자를 싣는다**

`nara/web/edit.py`의 `_log` 함수 **전체**를 바꾼다:

```python
def _log(
    conn: sqlite3.Connection,
    project_id: int,
    field: str,
    old: object,
    new: object,
    now: str,
    user_id: int | None = None,
) -> None:
    conn.execute(
        "INSERT INTO edit_log (project_id, field, old_value, new_value, edited_at, user_id) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (project_id, field, canonical(old) or None, canonical(new) or None, now, user_id),
    )
```

같은 파일의 다섯 저장 함수를 이렇게 고친다:

- `save_info(conn, project_id, values, now)` → `save_info(conn, project_id, values, now, user_id: int | None = None)`, 안의 `_log(conn, project_id, field, current[field], new, now)`를 `_log(conn, project_id, field, current[field], new, now, user_id)`로
- `save_verdict(conn, project_id, verdict, reason, now)` → 마지막에 `user_id: int | None = None`, 안의 `_log(...)` 호출 끝에 `, user_id`
- `save_dept(...)` → 같다
- `save_energy(...)` → 같다
- `release_verdict(conn, project_id, now)` → `release_verdict(conn, project_id, now, user_id: int | None = None)`. `with conn:` 블록 안 `INSERT` 아래에 더한다:

```python
        # 칸 이름을 verdict와 나눈다. verdict로 남기면 다음 시트 판정 변경이 웹 충돌로 보고된다.
        _log(conn, project_id, "verdict_release", latest["verdict"], latest["verdict"], now, user_id)
```

`nara/sheet_memory.py`의 `FIELD_LABELS`에 `"energy": "신재생",` 아래 한 줄을 더한다:

```python
    "verdict_release": "잠금 해제",
```

`nara/web/app.py`의 `_save` 함수 **전체**를 바꾼다:

```python
def _save(section: str, conn: sqlite3.Connection, project_id: int, values: dict) -> list[str]:
    now = datetime.now().isoformat(timespec="seconds")
    uid = g.user.id
    if section == "info":
        return edit.save_info(conn, project_id, values, now, uid)
    if section == "verdict":
        return edit.save_verdict(conn, project_id, values["verdict"], values["reason"], now, uid)
    if section == "dept":
        return edit.save_dept(conn, project_id, values["exec_dept"], values["snippet"], now, uid)
    return edit.save_energy(conn, project_id, values["items"], now, uid)
```

`release` 라우트의 `released = edit.release_verdict(conn, project_id, now)`를 `released = edit.release_verdict(conn, project_id, now, g.user.id)`로 바꾼다.

`nara/web/data.py`의 수정 이력 조회문을 바꾼다:

```python
            "SELECT e.edited_at, e.field, e.old_value, e.new_value, u.name AS user_name "
            "FROM edit_log e LEFT JOIN app_user u ON u.id = e.user_id "
            "WHERE e.project_id = ? ORDER BY e.edited_at DESC, e.id DESC",
```

(`"SELECT edited_at, field, old_value, new_value FROM edit_log "`와 `"WHERE project_id = ? ORDER BY edited_at DESC, id DESC",` 두 줄을 위 세 줄로.)

`nara/web/templates/detail.html`의 수정 이력 표에서 `<thead><tr><th>시각</th><th>칸</th>`를 `<thead><tr><th>시각</th><th>누가</th><th>칸</th>`로, `<tr><td>{{ e.edited_at }}</td><td>{{ e.label }}</td>`를 `<tr><td>{{ e.edited_at }}</td><td>{{ e.user_name or '(2단계 기록)' }}</td><td>{{ e.label }}</td>`로 바꾼다.

- [ ] **Step 4: 통과를 확인한다**

Run: `PYTHONIOENCODING=utf-8 uv run pytest tests/test_web.py tests/test_web_edit.py tests/test_migrate_sheets.py -v`
Expected: PASS 전부

- [ ] **Step 5: 전체 검사**

```bash
uv run ruff check --fix .
uv run ruff format .
PYTHONIOENCODING=utf-8 uv run pytest -q
uv run ruff check .
uv run ruff format --check .
```

- [ ] **Step 6: 커밋**

```bash
git add nara/web nara/sheet_memory.py tests/test_web.py
git commit -m "feat: 수정 기록에 누가 고쳤는지 남긴다

잠금 해제도 남긴다. 칸 이름은 verdict_release로 나눴다 — verdict로 남기면
다음 시트 판정 변경이 웹 충돌로 잘못 보고된다. 2단계 때 쌓인 기록은
'(2단계 기록)'으로 보인다.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: 동시 수정 확인

**Files:**
- Modify: `nara/web/edit.py`, `nara/web/app.py`, `nara/web/templates/detail.html`
- Modify: `tests/test_web.py`

**Interfaces:**
- Consumes: Task 4의 `edit_log.user_id`
- Produces (`nara.web.edit`): `SECTION_FIELDS: dict[str, tuple[str, ...]]`, `version_of(conn, project_id: int, section: str) -> str`, `last_editor(conn, project_id: int, section: str) -> str | None`

버전 표시가 없는 요청(업데이트 전에 열어 둔 화면)은 검사하지 않는다. 스펙은 "폼의 것과 다르면"이라고 했다. 표시가 없으면 비교할 것이 없다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_web.py` 끝에 더한다:

```python
def _version(client, project_id, section):
    page = _text(client.get(f"/project/{project_id}?edit={section}"))
    return re.search(r'name="version" value="([0-9a-f]+)"', page).group(1)


def test_a_second_save_on_a_stale_form_is_refused(world):
    """두 사람이 같은 묶음을 연 뒤 차례로 저장하면 나중 사람의 저장이 조용히 덮으면 안 된다."""
    path, ids = world
    pid = ids["culture"]
    first = _client(path)
    _ensure_user(path, email="peer@example.com", name="동료")
    second = _app(path).test_client()
    _login(second, path, email="peer@example.com")
    stale = _version(first, pid, "info")
    fresh = _version(second, pid, "info")
    ok = _post(second, f"/project/{pid}/edit/info", {**_info(floor_area="100"), "version": fresh})
    assert ok.status_code == 302
    resp = _post(first, f"/project/{pid}/edit/info", {**_info(floor_area="200"), "version": stale})
    assert resp.status_code == 409
    text = _text(resp)
    assert "그사이 동료님이 고쳤습니다" in text
    assert 'value="200"' in text
    conn = connect(path)
    assert conn.execute("SELECT floor_area FROM project WHERE id = ?", (pid,)).fetchone()[0] == 100
    conn.close()


def test_a_change_by_collection_is_reported_without_a_name(world):
    path, ids = world
    pid = ids["gym"]
    client = _client(path)
    stale = _version(client, pid, "verdict")
    _verdict_conn = connect(path)
    _verdict(_verdict_conn, pid, BUILDING, when="2026-09-29T09:00:00", decided_by="news")
    _verdict_conn.commit()
    _verdict_conn.close()
    resp = _post(
        client,
        f"/project/{pid}/edit/verdict",
        {"verdict": DONE, "reason": "준공식", "version": stale},
    )
    assert resp.status_code == 409
    assert "그사이 값이 바뀌었습니다" in _text(resp)


def test_a_fresh_version_saves_normally(world):
    path, ids = world
    pid = ids["gym"]
    client = _client(path)
    version = _version(client, pid, "energy")
    resp = client.post(
        f"/project/{pid}/edit/energy",
        data={"source": ["PV"], "capacity": ["20"], "version": version},
        headers=ORIGIN,
    )
    assert resp.status_code == 302
```

- [ ] **Step 2: 실패를 확인한다**

Run: `PYTHONIOENCODING=utf-8 uv run pytest tests/test_web.py -v -k "stale_form or by_collection or fresh_version"`
Expected: FAIL — 폼에 `version` 칸이 없어 `AttributeError: 'NoneType' object has no attribute 'group'`

- [ ] **Step 3: 버전 표시를 만든다**

`nara/web/edit.py`의 import 묶음 맨 위에 `import hashlib`을 더하고, 파일 끝에 더한다:

```python
SECTION_FIELDS = {
    "info": PROJECT_FIELDS,
    "verdict": ("verdict", "verdict_release"),
    "dept": ("exec_dept",),
    "energy": ("energy",),
}


def version_of(conn: sqlite3.Connection, project_id: int, section: str) -> str:
    """그 묶음의 지금 값으로 만든 짧은 표시. 폼을 연 뒤 값이 바뀌면 달라진다."""
    if section == "info":
        row = conn.execute(
            f"SELECT {', '.join(PROJECT_FIELDS)} FROM project WHERE id = ?", (project_id,)
        ).fetchone()
        parts = [canonical(row[f]) for f in PROJECT_FIELDS] if row else []
    elif section == "verdict":
        latest = _latest_row_id(conn, "status_check", project_id, "")
        parts = [latest]
    elif section == "dept":
        parts = [_latest_row_id(conn, "dept_check", project_id, "AND COALESCE(exec_dept, '') != ''")]
    else:
        rows = conn.execute(
            "SELECT source_type, capacity_kw FROM energy_plan WHERE project_id = ?", (project_id,)
        ).fetchall()
        parts = [energy_value(EnergyItem(r["source_type"], r["capacity_kw"]) for r in rows)]
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:16]


def _latest_row_id(conn: sqlite3.Connection, table: str, project_id: int, extra: str) -> str:
    # table·extra는 위의 고정 값만 받는다.
    row = conn.execute(
        f"SELECT id FROM {table} WHERE project_id = ? {extra} "
        "ORDER BY checked_at DESC, id DESC LIMIT 1",
        (project_id,),
    ).fetchone()
    return str(row[0]) if row else ""


def last_editor(conn: sqlite3.Connection, project_id: int, section: str) -> str | None:
    """그 묶음을 가장 최근에 웹에서 고친 사람의 이름. 기록이 없으면 None."""
    fields = SECTION_FIELDS[section]
    row = conn.execute(
        f"SELECT u.name FROM edit_log e JOIN app_user u ON u.id = e.user_id "
        f"WHERE e.project_id = ? AND e.field IN ({', '.join('?' * len(fields))}) "
        "ORDER BY e.edited_at DESC, e.id DESC LIMIT 1",
        (project_id, *fields),
    ).fetchone()
    return row[0] if row else None
```

- [ ] **Step 4: 저장 전에 비교한다**

`nara/web/app.py`에 상수를 더한다(`BUSY_MESSAGE` 아래):

```python
CONFLICT_BY = "그사이 {}님이 고쳤습니다. 지금 값을 확인하고 다시 저장하세요"
CONFLICT = "그사이 값이 바뀌었습니다. 지금 값을 확인하고 다시 저장하세요"
```

`_render_detail`의 `render_template(` 인자에 한 줄을 더한다(`energy_rows=_energy_rows(d, posted),` 아래):

```python
            versions={s: edit.version_of(get_conn(), d.project["id"], s) for s in EDIT_SECTIONS},
```

`save` 라우트의 `try:` 블록을 이것으로 바꾼다:

```python
        try:
            with closing(_rw_conn()) as conn:
                sent = request.form.get("version")
                if sent is not None and sent != edit.version_of(conn, project_id, section):
                    who = edit.last_editor(conn, project_id, section)
                    message = CONFLICT_BY.format(who) if who else CONFLICT
                    fresh = project_detail(get_conn(), project_id)
                    return _render_detail(fresh, section, {"_form": message}, 409)
                changed = _save(section, conn, project_id, checked.values)
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc):
                raise
            return _render_detail(d, section, {"_form": BUSY_MESSAGE}, 503)
```

`nara/web/templates/detail.html`의 네 폼 여는 줄 바로 아래에 버전 칸을 더한다. 예를 들어 `section='info') }}">` 뒤 줄에:

```html
  <input type="hidden" name="version" value="{{ versions['info'] }}">
```

`verdict`·`dept`·`energy` 폼에도 같은 줄을 각 묶음 이름으로 더한다.

- [ ] **Step 5: 통과를 확인한다**

Run: `PYTHONIOENCODING=utf-8 uv run pytest tests/test_web.py -v`
Expected: PASS 전부

- [ ] **Step 6: 전체 검사**

```bash
uv run ruff check --fix .
uv run ruff format .
PYTHONIOENCODING=utf-8 uv run pytest -q
uv run ruff check .
uv run ruff format --check .
```

- [ ] **Step 7: 커밋**

```bash
git add nara/web tests/test_web.py
git commit -m "feat: 동시 수정 확인 — 폼을 연 뒤 값이 바뀌었으면 저장하지 않고 알린다

폼에 그 묶음의 버전 표시를 숨겨 두고 저장할 때 비교한다. 다르면 409로
'그사이 ○○님이 고쳤습니다'와 지금 값을 보이고 내 입력은 남긴다. 수집이
바꾼 경우에는 이름 없이 알린다.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: 수집 슬롯

**Files:**
- Create: `nara/slot.py`, `tests/test_slot.py`
- Modify: `nara/cli.py`

**Interfaces:**
- Produces (`nara.slot`): `SLOTS = ("09", "12", "15")`, `LOCK_KEY = "slot_running"`, `LOCK_MAX_AGE = timedelta(hours=2)`, `@dataclass(frozen=True) Step(name: str, options: dict)`, `plan(slot: str, weekday: int) -> list[Step]`, `acquire(conn, now: datetime) -> bool`, `release(conn) -> None`
- Produces (`nara.cli`): `nara run slot <09|12|15>`, `_STEP_RUNNERS: dict[str, Callable]`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_slot.py`:

```python
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
        ]


def test_noon_slot_checks_awards_for_todays_weekday_group():
    assert plan("12", 3) == [
        Step("collect", {"days": 3}),
        Step("enrich award", {"tier": "rest", "group": 3}),
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

    for name in ("collect", "enrich award", "enrich status"):
        monkeypatch.setitem(cli._STEP_RUNNERS, name, make(name))


def test_run_slot_keeps_going_after_a_failed_step(tmp_path, monkeypatch):
    calls = []
    _fake_runners(monkeypatch, calls, fail={"enrich award"})
    db = tmp_path / "r.db"
    result = CliRunner().invoke(cli.app, ["run", "slot", "09", "--db", str(db)])
    assert calls == ["collect", "enrich award", "enrich status"]
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
    row = c.execute(
        "SELECT status, message FROM run_log WHERE command = 'run slot'"
    ).fetchone()
    c.close()
    assert row["status"] == "partial"
    assert "앞 슬롯" in row["message"]
```

- [ ] **Step 2: 실패를 확인한다**

Run: `PYTHONIOENCODING=utf-8 uv run pytest tests/test_slot.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'nara.slot'`

- [ ] **Step 3: 슬롯 모듈을 만든다**

`nara/slot.py`:

```python
"""하루 세 번 도는 수집 순서와 겹침 방지. 원 명세의 스케줄표를 옮긴다."""

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta

SLOTS = ("09", "12", "15")
LOCK_KEY = "slot_running"
# 가장 긴 슬롯(수집 + 낙찰 + 진행현황 예산 20분)보다 넉넉히. 죽은 슬롯의 표시는 이만큼 뒤 풀린다.
LOCK_MAX_AGE = timedelta(hours=2)


@dataclass(frozen=True)
class Step:
    name: str  # run_log의 명령 이름과 같다
    options: dict


def plan(slot: str, weekday: int) -> list[Step]:
    """weekday는 date.isoweekday() — 월 1 ~ 일 7."""
    if slot not in SLOTS:
        raise ValueError(f"슬롯은 {' | '.join(SLOTS)} 중 하나다: {slot!r}")
    steps = [Step("collect", {"days": 3})]
    if slot == "12":
        # 비관심 기관은 월~금 다섯 그룹이다. 주말에는 낙찰 조회할 그룹이 없다.
        if weekday <= 5:
            steps.append(Step("enrich award", {"tier": "rest", "group": weekday}))
        return steps
    steps.append(Step("enrich award", {"tier": "focus", "group": None}))
    steps.append(Step("enrich status", {"tier": "focus"}))
    return steps


def acquire(conn: sqlite3.Connection, now: datetime) -> bool:
    """겹침 표시를 건다. 다른 슬롯이 돌고 있으면 False.

    BEGIN IMMEDIATE로 읽기와 쓰기를 한 번에 잡아 두 슬롯이 동시에 걸지 못하게 한다.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute("SELECT value FROM app_state WHERE key = ?", (LOCK_KEY,)).fetchone()
        if row is not None and now - datetime.fromisoformat(row[0]) < LOCK_MAX_AGE:
            conn.rollback()
            return False
        conn.execute(
            "INSERT INTO app_state (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (LOCK_KEY, now.isoformat(timespec="seconds")),
        )
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise


def release(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM app_state WHERE key = ?", (LOCK_KEY,))
    conn.commit()
```

- [ ] **Step 4: 명령을 더한다**

`nara/cli.py`의 import 묶음에 더한다:

```python
from collections.abc import Callable

from nara.slot import SLOTS
from nara.slot import acquire as acquire_slot
from nara.slot import plan as slot_plan
from nara.slot import release as release_slot
```

`migrate_app = typer.Typer(` 줄 **위**에 더한다:

```python
# 슬롯 단계 이름 → 지금 명령. 테스트가 가짜로 바꿔 끼운다.
_STEP_RUNNERS: dict[str, Callable[..., None]] = {
    "collect": lambda db, config, days: collect(days=days, db=db, config=config),
    "enrich award": lambda db, config, tier, group: enrich_award(
        tier=tier, group=group, limit=300, db=db
    ),
    "enrich status": lambda db, config, tier: enrich_status(
        tier=tier, limit=300, budget=1200, db=db
    ),
}

run_app = typer.Typer(help="예약 실행")
app.add_typer(run_app, name="run")


@run_app.command("slot")
def run_slot(
    slot: str = typer.Argument(..., help="09 | 12 | 15"),
    db: Path = typer.Option(DEFAULT_DB),
    config: Path = typer.Option(DEFAULT_CONFIG),
) -> None:
    """그 시각에 할 일을 순서대로 돌린다. 한 단계가 실패해도 다음 단계를 돈다."""
    if slot not in SLOTS:
        typer.echo(f"슬롯은 {' | '.join(SLOTS)} 중 하나다: {slot!r}", err=True)
        raise typer.Exit(code=1)
    conn = _open_db(db)
    now = datetime.now()
    if not acquire_slot(conn, now):
        stamp = now.isoformat(timespec="seconds")
        conn.execute(
            "INSERT INTO run_log (command, args, started_at, finished_at, status, message) "
            "VALUES ('run slot', ?, ?, ?, 'partial', '앞 슬롯이 돌고 있어 건너뜀')",
            (slot, stamp, stamp),
        )
        conn.commit()
        typer.echo("앞 슬롯이 아직 돌고 있다 — 이번 회차는 건너뛴다", err=True)
        raise typer.Exit(code=1)
    failed: list[str] = []
    try:
        for step in slot_plan(slot, date.today().isoweekday()):
            try:
                _STEP_RUNNERS[step.name](db=db, config=config, **step.options)
            except typer.Exit as exc:
                if exc.exit_code:
                    failed.append(step.name)
            except Exception as exc:  # 한 단계가 죽어도 다음 단계를 돈다
                failed.append(step.name)
                typer.echo(f"{step.name} 실패: {exc}", err=True)
    finally:
        release_slot(conn)
    if failed:
        typer.echo(f"실패한 단계: {', '.join(failed)}", err=True)
        raise typer.Exit(code=1)
    typer.echo(f"슬롯 {slot} 완료")
```

- [ ] **Step 5: 통과를 확인한다**

Run: `PYTHONIOENCODING=utf-8 uv run pytest tests/test_slot.py -v`
Expected: PASS (8개)

- [ ] **Step 6: 전체 검사**

```bash
uv run ruff check --fix .
uv run ruff format .
PYTHONIOENCODING=utf-8 uv run pytest -q
uv run ruff check .
uv run ruff format --check .
```

- [ ] **Step 7: 커밋**

```bash
git add nara/slot.py nara/cli.py tests/test_slot.py
git commit -m "feat: nara run slot — 하루 세 번 수집 순서, 한 단계가 죽어도 다음 단계

원 명세의 스케줄표다. 12시는 오늘 요일 그룹의 낙찰만 보고 주말에는
건너뛴다. 두 슬롯이 겹치지 않게 app_state에 표시를 걸고, 죽은 슬롯의
표시는 2시간 뒤 풀린다.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: 백업

**Files:**
- Create: `nara/backup.py`, `tests/test_backup.py`
- Modify: `nara/cli.py`, `nara/web/data.py`, `tests/test_web.py`

**Interfaces:**
- Produces (`nara.backup`): `KEEP_LOCAL_DAYS = 7`, `KEEP_REMOTE = "30d"`, `make_backup(db_path: Path, out_dir: Path, today: date) -> Path`, `prune_local(out_dir: Path, today: date, keep_days: int = KEEP_LOCAL_DAYS) -> list[Path]`, `upload(packed: Path, remote: str, run: Callable = subprocess.run) -> None`
- Produces (`nara.cli`): `nara backup [--db] [--out data/backup] [--env .env]`
- Produces (`nara.web.data`): `PIPELINE_STAGES`에 `("backup", "백업")`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_backup.py`:

```python
"""백업 — 쓰는 중에도 깨지지 않는 복사본, 서버 밖으로 보내기."""

import gzip
import sqlite3
from datetime import date

import pytest
from typer.testing import CliRunner

from nara import cli
from nara.backup import make_backup, prune_local, upload
from nara.db import connect, migrate

TODAY = date(2026, 9, 28)


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "n.db"
    c = connect(path)
    migrate(c)
    c.execute("INSERT INTO app_state (key, value) VALUES ('marker', 'committed')")
    c.commit()
    c.close()
    return path


def _open_packed(packed, tmp_path):
    raw = tmp_path / "restored.db"
    raw.write_bytes(gzip.decompress(packed.read_bytes()))
    return sqlite3.connect(raw)


def test_backup_is_a_compressed_database_that_opens(db, tmp_path):
    packed = make_backup(db, tmp_path / "out", TODAY)
    assert packed.name == "nara-20260928.db.gz"
    restored = _open_packed(packed, tmp_path)
    assert restored.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert restored.execute("SELECT value FROM app_state WHERE key = 'marker'").fetchone()[0] == (
        "committed"
    )
    restored.close()
    assert not (tmp_path / "out" / "nara-20260928.db").exists()


def test_backup_while_collection_writes_leaves_out_uncommitted_rows(db, tmp_path):
    """수집이 쓰는 도중에 백업해도 깨지지 않고, 커밋 전 줄은 들어가지 않는다."""
    writer = sqlite3.connect(db)
    writer.execute("BEGIN IMMEDIATE")
    writer.execute("INSERT INTO app_state (key, value) VALUES ('pending', 'x')")
    try:
        packed = make_backup(db, tmp_path / "out", TODAY)
    finally:
        writer.rollback()
        writer.close()
    restored = _open_packed(packed, tmp_path)
    assert restored.execute("SELECT 1 FROM app_state WHERE key = 'pending'").fetchone() is None
    restored.close()


def test_prune_keeps_the_last_seven_days(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    for day in ("20260920", "20260921", "20260922", "20260928"):
        (out / f"nara-{day}.db.gz").write_bytes(b"x")
    (out / "other.txt").write_text("keep")
    removed = prune_local(out, TODAY)
    assert sorted(p.name for p in removed) == ["nara-20260920.db.gz", "nara-20260921.db.gz"]
    assert (out / "other.txt").exists()


def test_upload_copies_then_trims_the_remote(tmp_path):
    calls = []
    upload(tmp_path / "nara-20260928.db.gz", "gdrive:nara-backup", run=lambda a, check: calls.append(a))
    assert calls == [
        ["rclone", "copy", str(tmp_path / "nara-20260928.db.gz"), "gdrive:nara-backup"],
        ["rclone", "delete", "gdrive:nara-backup", "--min-age", "30d"],
    ]


def _env(tmp_path, **values):
    path = tmp_path / ".env"
    path.write_text("".join(f"{k}={v}\n" for k, v in values.items()), encoding="utf-8")
    return path


def _last_backup(db):
    c = connect(db)
    row = c.execute(
        "SELECT status FROM run_log WHERE command = 'backup' ORDER BY id DESC"
    ).fetchone()
    c.close()
    return row["status"]


def test_backup_without_a_remote_keeps_a_local_copy_and_says_partial(db, tmp_path):
    out = tmp_path / "out"
    result = CliRunner().invoke(
        cli.app, ["backup", "--db", str(db), "--out", str(out), "--env", str(_env(tmp_path))]
    )
    assert result.exit_code == 1
    assert "NARA_BACKUP_REMOTE" in result.output
    assert list(out.glob("nara-*.db.gz"))
    assert _last_backup(db) == "partial"


def test_backup_with_a_remote_uploads(db, tmp_path, monkeypatch):
    sent = []
    monkeypatch.setattr(cli, "upload_backup", lambda packed, remote: sent.append(remote))
    env = _env(tmp_path, NARA_BACKUP_REMOTE="gdrive:nara-backup")
    result = CliRunner().invoke(
        cli.app, ["backup", "--db", str(db), "--out", str(tmp_path / "out"), "--env", str(env)]
    )
    assert result.exit_code == 0, result.output
    assert sent == ["gdrive:nara-backup"]
    assert _last_backup(db) == "ok"
```

`tests/test_web.py`에서 백업 단계를 반영한다:

- `test_last_runs_names_every_stage_even_one_that_never_ran`의 `["수집", "낙찰 조회", "진행현황"]`를 `["수집", "낙찰 조회", "진행현황", "백업"]`으로
- `test_last_runs_reports_the_latest_run_of_each_stage`의 `{"수집", "낙찰 조회", "진행현황"}`를 `{"수집", "낙찰 조회", "진행현황", "백업"}`으로

- [ ] **Step 2: 실패를 확인한다**

Run: `PYTHONIOENCODING=utf-8 uv run pytest tests/test_backup.py tests/test_web.py -v -k "backup or last_runs"`
Expected: FAIL — `ModuleNotFoundError: No module named 'nara.backup'`

- [ ] **Step 3: 백업 모듈을 만든다**

`nara/backup.py`:

```python
"""DB 백업. SQLite 백업 API로 쓰는 중에도 깨지지 않는 복사본을 만들어 서버 밖으로 보낸다."""

import gzip
import shutil
import sqlite3
import subprocess
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path

from nara.web.data import open_readonly

KEEP_LOCAL_DAYS = 7
KEEP_REMOTE = "30d"


def make_backup(db_path: Path, out_dir: Path, today: date) -> Path:
    """nara-YYYYMMDD.db.gz를 만든다. 무결성 검사를 통과한 것만 남긴다."""
    out_dir.mkdir(parents=True, exist_ok=True)
    raw = out_dir / f"nara-{today:%Y%m%d}.db"
    source = open_readonly(db_path)
    target = sqlite3.connect(raw)
    try:
        source.backup(target)
        result = target.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        source.close()
        target.close()
    if result != "ok":
        raw.unlink()
        raise RuntimeError(f"백업본 무결성 검사 실패: {result}")
    packed = raw.with_name(raw.name + ".gz")
    with raw.open("rb") as fin, gzip.open(packed, "wb") as fout:
        shutil.copyfileobj(fin, fout)
    raw.unlink()
    return packed


def prune_local(out_dir: Path, today: date, keep_days: int = KEEP_LOCAL_DAYS) -> list[Path]:
    """서버 안에는 최근 keep_days일만 남긴다. 이름이 백업 꼴이 아닌 파일은 건드리지 않는다."""
    removed = []
    for path in out_dir.glob("nara-*.db.gz"):
        try:
            day = datetime.strptime(path.name[5:13], "%Y%m%d").date()
        except ValueError:
            continue
        if (today - day).days >= keep_days:
            path.unlink()
            removed.append(path)
    return removed


def upload(packed: Path, remote: str, run: Callable = subprocess.run) -> None:
    """rclone으로 올리고, 원격에서 30일 지난 백업을 지운다."""
    run(["rclone", "copy", str(packed), remote], check=True)
    run(["rclone", "delete", remote, "--min-age", KEEP_REMOTE], check=True)
```

- [ ] **Step 4: 명령과 단계를 더한다**

`nara/cli.py`의 import 묶음에 더한다:

```python
import subprocess

from nara.backup import make_backup, prune_local
from nara.backup import upload as upload_backup
```

`migrate_app = typer.Typer(` 줄 **위**에 더한다:

```python
@app.command()
def backup(
    db: Path = typer.Option(DEFAULT_DB),
    out: Path = typer.Option(Path("data/backup"), help="서버 안 보관 폴더"),
    env: Path = typer.Option(DEFAULT_ENV, help="비밀값 파일"),
) -> None:
    """DB 백업본을 만들고 서버 밖(NARA_BACKUP_REMOTE)으로 보낸다."""
    if not db.exists():
        typer.echo(f"DB 파일이 없다: {db}", err=True)
        raise typer.Exit(code=1)
    remote = load_secrets(env).backup_remote
    conn = _open_db(db)
    today = date.today()
    with run_log(conn, "backup", str(out)) as counters:
        packed = make_backup(db, out, today)
        prune_local(out, today)
        counters.processed = 1
        if not remote:
            counters.failed = 1
            typer.echo("NARA_BACKUP_REMOTE가 .env에 없어 서버 안에만 남겼다", err=True)
        else:
            try:
                upload_backup(packed, remote)
                counters.updated = 1
            except (OSError, subprocess.CalledProcessError) as exc:
                counters.failed = 1
                typer.echo(f"서버 밖으로 보내지 못했다: {exc}", err=True)
    typer.echo(f"백업: {packed}")
    if counters.failed:
        raise typer.Exit(code=1)
```

`nara/web/data.py`의 `PIPELINE_STAGES`에 `("enrich status", "진행현황"),` 아래 한 줄을 더한다:

```python
    ("backup", "백업"),
```

- [ ] **Step 5: 통과를 확인한다**

Run: `PYTHONIOENCODING=utf-8 uv run pytest tests/test_backup.py tests/test_web.py -v`
Expected: PASS 전부(`test_backup.py` 7개)

- [ ] **Step 6: 전체 검사**

```bash
uv run ruff check --fix .
uv run ruff format .
PYTHONIOENCODING=utf-8 uv run pytest -q
uv run ruff check .
uv run ruff format --check .
```

- [ ] **Step 7: 커밋**

```bash
git add nara/backup.py nara/cli.py nara/web/data.py tests/test_backup.py tests/test_web.py
git commit -m "feat: nara backup — 쓰는 중에도 깨지지 않는 백업을 서버 밖으로

SQLite 백업 API로 복사하고 무결성 검사를 통과한 것만 압축해 남긴다.
rclone으로 올리고 원격은 30일, 서버 안은 7일만 둔다. 보낼 곳이 없거나
실패하면 partial로 남기고 목록 머리의 '백업'이 빨갛게 보인다.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: 서버 실행·설치 파일·실데이터 확인·검수

**Files:**
- Modify: `pyproject.toml`, `uv.lock` (`uv add waitress`), `nara/cli.py` (`serve`), `README.md`
- Create: `deploy/nara-web.service`, `deploy/nara-slot@.service`, `deploy/nara-slot-09.timer`, `deploy/nara-slot-12.timer`, `deploy/nara-slot-15.timer`, `deploy/nara-backup.service`, `deploy/nara-backup.timer`, `deploy/Caddyfile`, `deploy/update.sh`, `deploy/setup.md`
- Modify: `tests/test_web.py`

**Interfaces:**
- Produces: `nara serve [--port] [--db] [--env] [--production]`. `--production`은 waitress로 `127.0.0.1:<port>`에 띄운다

- [ ] **Step 1: waitress를 더한다**

```bash
uv add waitress
PYTHONIOENCODING=utf-8 uv run python -c "import waitress; from importlib.metadata import version; print(version('waitress'))"
```

Expected: 버전이 찍힌다. 설치가 실패하면 멈추고 보고한다

- [ ] **Step 2: 실패하는 테스트를 쓴다**

`tests/test_web.py` 끝에 더한다:

```python
def test_serve_refuses_to_start_without_a_secret_key(world, tmp_path):
    env = tmp_path / "empty.env"
    env.write_text("", encoding="utf-8")
    result = CliRunner().invoke(cli_app, ["serve", "--db", str(world[0]), "--env", str(env)])
    assert result.exit_code == 1
    assert "NARA_SECRET_KEY" in result.output


def test_serve_production_uses_waitress_on_this_computer_only(world, tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr("nara.cli.waitress_serve", lambda app, **kw: seen.update(kw))
    env = _env_file(tmp_path, NARA_HOST="nara.example.org")
    result = CliRunner().invoke(
        cli_app,
        ["serve", "--db", str(world[0]), "--env", str(env), "--production", "--port", "8000"],
    )
    assert result.exit_code == 0, result.output
    assert (seen["host"], seen["port"]) == ("127.0.0.1", 8000)


def test_deploy_files_hold_no_secret_values():
    """저장소는 공개다. 배포 파일에는 이름만 있고 값은 없다."""
    root = Path(__file__).resolve().parents[1] / "deploy"
    text = "\n".join(p.read_text(encoding="utf-8") for p in root.iterdir() if p.is_file())
    for name in ("G2B_API_KEY", "ANTHROPIC_API_KEY", "NARA_SECRET_KEY"):
        assert not re.search(rf"{name}\s*=\s*\S", text), name
```

그리고 Task 3에서 `DEFAULT_ENV`를 바꿔 끼운 `serve` 테스트 두 개를 `--env` 인자로 바꾼다: `monkeypatch.setattr("nara.cli.DEFAULT_ENV", _env_file(tmp_path))` 줄을 지우고, `CliRunner().invoke(cli_app, ["serve", ...])`의 인자 목록에 `"--env", str(_env_file(tmp_path))`를 더한다.

- [ ] **Step 3: 실패를 확인한다**

Run: `PYTHONIOENCODING=utf-8 uv run pytest tests/test_web.py -v -k "serve or deploy"`
Expected: FAIL — `--env`·`--production` 옵션 없음(exit 2), `deploy` 폴더 없음

- [ ] **Step 4: `serve`를 고친다**

`nara/cli.py`의 import 묶음에 `from waitress import serve as waitress_serve`를 더하고, `serve` 함수 **전체**를 바꾼다:

```python
@app.command()
def serve(
    port: int = typer.Option(8000, min=1, max=65535, help="포트"),
    db: Path = typer.Option(DEFAULT_DB, help="SQLite 경로"),
    env: Path = typer.Option(DEFAULT_ENV, help="비밀값 파일"),
    production: bool = typer.Option(False, "--production", help="서버용: waitress로 띄운다"),
) -> None:
    """조회·입력 화면을 띄운다. 이 컴퓨터(127.0.0.1)에서만 열리고 밖은 Caddy가 잇는다."""
    # _open_db를 쓰지 않는다. 없는 파일이면 위에서 멈춰야 한다 — doctor와 같은 이유.
    if not db.exists():
        typer.echo(f"DB 파일이 없다: {db}", err=True)
        raise typer.Exit(code=1)
    secrets = load_secrets(env)
    if not secrets.secret_key:
        typer.echo("NARA_SECRET_KEY가 .env에 없다 — 세션 서명 키 없이는 띄우지 않는다", err=True)
        raise typer.Exit(code=1)
    # 새 표가 없으면 만든다. 파일이 있으니 새 DB를 만들지는 않는다.
    conn = connect(db)
    migrate(conn)
    conn.close()
    web = create_app(db, secret_key=secrets.secret_key, host=secrets.host)
    if production:
        typer.echo(f"서버 모드: 127.0.0.1:{port} (밖은 Caddy가 https로 잇는다)")
        waitress_serve(web, host="127.0.0.1", port=port, threads=8)
        return
    typer.echo(f"조회 화면: http://127.0.0.1:{port}  (끄려면 Ctrl+C)")
    # debug=True는 브라우저에서 코드를 실행하는 디버거를 연다. 로컬이어도 켜지 않는다.
    web.run(host="127.0.0.1", port=port, debug=False)
```

- [ ] **Step 5: 설치 파일을 만든다**

`deploy/nara-web.service`:

```ini
[Unit]
Description=nara 조회·입력 화면
After=network-online.target
Wants=network-online.target

[Service]
User=nara
WorkingDirectory=/srv/nara
ExecStart=/home/nara/.local/bin/uv run nara serve --production --db /srv/nara/data/nara.db --env /srv/nara/.env
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

`deploy/nara-slot@.service`:

```ini
[Unit]
Description=nara 수집 슬롯 %i

[Service]
Type=oneshot
User=nara
WorkingDirectory=/srv/nara
Environment=PYTHONIOENCODING=utf-8
ExecStart=/home/nara/.local/bin/uv run nara run slot %i --db /srv/nara/data/nara.db
```

`deploy/nara-slot-09.timer`:

```ini
[Unit]
Description=nara 수집 09시

[Timer]
OnCalendar=*-*-* 09:00:00
Persistent=true
Unit=nara-slot@09.service

[Install]
WantedBy=timers.target
```

`deploy/nara-slot-12.timer`는 위에서 `09`를 `12`로, `deploy/nara-slot-15.timer`는 `15`로 바꾼 같은 내용이다(세 파일 모두 만든다).

`deploy/nara-backup.service`:

```ini
[Unit]
Description=nara DB 백업

[Service]
Type=oneshot
User=nara
WorkingDirectory=/srv/nara
ExecStart=/home/nara/.local/bin/uv run nara backup --db /srv/nara/data/nara.db --out /srv/nara/backup --env /srv/nara/.env
```

`deploy/nara-backup.timer`:

```ini
[Unit]
Description=nara DB 백업 03시

[Timer]
OnCalendar=*-*-* 03:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

`deploy/Caddyfile`:

```
# 첫 줄의 주소를 DuckDNS에서 받은 주소로 바꾼다. 인증서는 Caddy가 자동으로 받는다.
nara-energinno.duckdns.org {
	encode gzip
	reverse_proxy 127.0.0.1:8000
}
```

`deploy/update.sh`:

```bash
#!/usr/bin/env bash
# 서버에서 새 코드를 받아 다시 띄운다. nara 사용자로 /srv/nara에서 실행한다.
set -euo pipefail
cd /srv/nara
git pull --ff-only
/home/nara/.local/bin/uv sync --frozen
sudo systemctl restart nara-web
echo "갱신 완료: $(git log --oneline -1)"
```

`deploy/setup.md` — 순서와 점검 목록. 아래 전문을 그대로 쓴다:

````markdown
# 서버 설치 (Oracle Cloud 서울, 상시 무료)

사람이 해야 하는 일(계정·카드 인증)과 서버에서 칠 명령을 순서대로 적는다. 비밀값은
어디에도 적지 않는다 — `/srv/nara/.env`에만 둔다.

## 1. 계정과 서버 (사람)

1. Oracle Cloud 가입. 홈 리전은 **South Korea Central (Seoul)**. 춘천은 ARM 무료 대상이 아니다
2. Compute → Instance 만들기: 이미지 Ubuntu 24.04, 모양 `VM.Standard.A1.Flex` 1 OCPU·6GB(무료 한도 2 OCPU·12GB 안)
   - "Out of capacity"가 나오면 시간을 두고 다시 만든다
3. 공개 SSH 키를 넣고 만든다. 공인 IP를 적어 둔다
4. VCN 보안 목록에 들어오는 TCP 80·443을 연다
5. DuckDNS(duckdns.org)에 로그인해 주소 하나를 만들고 위 공인 IP를 넣는다

## 2. 서버 준비

```bash
sudo timedatectl set-timezone Asia/Seoul
sudo apt update && sudo apt -y upgrade
sudo apt -y install git sqlite3 rclone debian-keyring debian-archive-keyring apt-transport-https curl
# Ubuntu 방화벽(iptables)에도 80·443을 연다 — Oracle 이미지는 기본으로 막아 둔다
sudo iptables -I INPUT 6 -p tcp --dport 80 -j ACCEPT
sudo iptables -I INPUT 6 -p tcp --dport 443 -j ACCEPT
sudo netfilter-persistent save
sudo useradd --create-home --shell /bin/bash nara
sudo mkdir -p /srv/nara && sudo chown nara:nara /srv/nara
```

Caddy 설치: https://caddyserver.com/docs/install#debian-ubuntu-raspbian 의 명령을 그대로 친다.

## 3. 앱

```bash
sudo -iu nara
curl -LsSf https://astral.sh/uv/install.sh | sh
git clone https://github.com/jlaw080-ops/Nara-project-renewal.git /srv/nara
cd /srv/nara && ~/.local/bin/uv sync --frozen
mkdir -p data backup
```

`.env`를 만든다(값은 직접 넣는다):

```bash
python3 -c "import secrets; print('NARA_SECRET_KEY=' + secrets.token_urlsafe(32))" > /srv/nara/.env
echo "NARA_HOST=<DuckDNS 주소>" >> /srv/nara/.env
echo "NARA_BACKUP_REMOTE=gdrive:nara-backup" >> /srv/nara/.env
nano /srv/nara/.env   # G2B_API_KEY, ANTHROPIC_API_KEY 줄을 더한다
chmod 600 /srv/nara/.env
```

## 4. DB 옮기기

사용자 PC에서(수집을 끈 뒤):

```bash
sqlite3 data/nara.db ".backup data/nara-upload.db"
scp data/nara-upload.db ubuntu@<공인 IP>:/tmp/nara.db
```

서버에서:

```bash
sudo mv /tmp/nara.db /srv/nara/data/nara.db && sudo chown nara:nara /srv/nara/data/nara.db
sudo -iu nara bash -c "cd /srv/nara && ~/.local/bin/uv run nara user add <이메일> --name <이름> --db data/nara.db"
```

사용자 PC의 작업 스케줄러에서 nara 수집 작업을 끈다. 두 곳에서 수집하면 결과가 엇갈린다.

## 5. 서비스·예약·Caddy

```bash
sudo cp /srv/nara/deploy/*.service /srv/nara/deploy/*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now nara-web nara-slot-09.timer nara-slot-12.timer nara-slot-15.timer nara-backup.timer
sudo cp /srv/nara/deploy/Caddyfile /etc/caddy/Caddyfile
sudo nano /etc/caddy/Caddyfile   # 첫 줄 주소를 DuckDNS 주소로
sudo systemctl reload caddy
```

## 6. 백업 보낼 곳 (rclone ↔ 구글 드라이브)

```bash
sudo -iu nara rclone config   # n → 이름 gdrive → drive → 안내대로(브라우저 인증은 PC에서 rclone authorize "drive")
sudo -iu nara bash -c "cd /srv/nara && ~/.local/bin/uv run nara backup --db data/nara.db --out backup --env .env"
```

## 7. 점검 목록

- [ ] `https://<DuckDNS 주소>`가 자물쇠와 함께 로그인 화면을 연다
- [ ] 로그인 → 임시 비밀번호 바꾸기 → 목록 249건 전후가 보인다
- [ ] 상세에서 비고를 고치면 수정 이력에 내 이름이 보인다
- [ ] `systemctl list-timers | grep nara`에 슬롯 셋과 백업이 다음 실행 시각과 함께 보인다
- [ ] 다음 날 목록 머리에서 수집·낙찰·진행현황·백업이 모두 정상이다
- [ ] 구글 드라이브 `nara-backup/`에 `nara-YYYYMMDD.db.gz`가 쌓인다
- [ ] `timedatectl`의 Time zone이 Asia/Seoul이다(12시 슬롯의 요일이 여기서 정해진다)

## 갱신

```bash
sudo -iu nara /srv/nara/deploy/update.sh
```

## 복구

1. 구글 드라이브에서 원하는 날짜의 `nara-YYYYMMDD.db.gz`를 받는다
2. `gunzip`으로 풀어 `/srv/nara/data/nara.db`로 둔다(지금 파일은 옆에 옮겨 둔다)
3. `sudo systemctl restart nara-web`
````

- [ ] **Step 6: README를 고친다**

`README.md`의 `## 쓰는 법` 코드 블록 아래 문단 뒤에 더한다:

```markdown
### 로그인과 서버

화면은 로그인해야 열린다. `.env`에 `NARA_SECRET_KEY`(무작위 긴 글자)를 넣고
`uv run nara user add <이메일> --name <이름>`으로 계정을 만든다. 임시 비밀번호는 한 번만
보이고, 첫 로그인에서 바꾼다.

서버 설치는 [deploy/setup.md](deploy/setup.md)에 있다. 서버에서는 `nara run slot 09|12|15`가
하루 세 번 수집하고 `nara backup`이 매일 백업한다.
```

- [ ] **Step 7: 통과를 확인한다**

Run: `PYTHONIOENCODING=utf-8 uv run pytest tests/test_web.py -v`
Expected: PASS 전부

- [ ] **Step 8: 전체 검사**

```bash
uv run ruff check --fix .
uv run ruff format .
PYTHONIOENCODING=utf-8 uv run pytest -q
uv run ruff check .
uv run ruff format --check .
```

- [ ] **Step 9: 실데이터 사본으로 확인한다**

사본 DB와 임시 `.env`로 서버 모드를 띄운다. 사용자 `.env`와 원본 DB는 건드리지 않는다:

```bash
T="$(cygpath -w ~/AppData/Local/Temp/claude)"
PYTHONIOENCODING=utf-8 uv run python -c "import sqlite3; s=sqlite3.connect('file:data/nara.db?mode=ro', uri=True); d=sqlite3.connect(r'$T\\cloud.db'); s.backup(d); d.close()"
printf 'NARA_SECRET_KEY=local-check-key\n' > "$T/cloud.env"
PYTHONIOENCODING=utf-8 uv run nara user add me@example.com --name 확인용 --db "$T\\cloud.db"
PYTHONIOENCODING=utf-8 uv run nara serve --production --db "$T\\cloud.db" --env "$T\\cloud.env" --port 8767
```

마지막 명령은 백그라운드로 띄운다. 그 뒤 httpx로 확인한다: 로그인 전 `/`가 `/login`으로 302, 임시 비밀번호 로그인 → `/password`로 302, 비밀번호 바꾸기 → 목록 200·`249건 중 249건`, 상세 36의 비고 저장 → 수정 이력에 "확인용". `nara backup --db <사본> --out <임시 폴더> --env <임시 env>`가 exit 1(보낼 곳 없음)이고 `.db.gz`가 풀어서 열린다. **기대와 다르면 멈추고 보고한다.** 끝나면 서버를 끈다.

- [ ] **Step 10: 디자인 검수(hallmark)**

로그인·비밀번호 바꾸기 화면과 머리의 이름·로그아웃 줄을 1·2단계와 같은 방법으로 검수한다(웹 열, 320px 넘침 측정, 색·폰트는 기록만). `critical`·`major` 0이 될 때까지 템플릿을 고치고 Step 8을 다시 돌린다.

- [ ] **Step 11: 커밋**

```bash
git add pyproject.toml uv.lock nara/cli.py README.md deploy tests/test_web.py nara/web/templates
git commit -m "feat: 서버 실행과 설치 파일 — waitress, systemd 슬롯·백업, Caddy, 설치 순서

nara serve --production은 waitress로 127.0.0.1에만 띄우고 밖은 Caddy가
https로 잇는다. 세션 서명 키가 없으면 띄우지 않는다. 배포 파일에는 비밀값의
이름만 있다. setup.md에 계정 만들기부터 복구까지의 순서와 점검 목록을 적었다.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## 스펙 대응

| 스펙 요구 | 작업 |
|---|---|
| `app_user`·`login_attempt`, `edit_log.user_id` | Task 1 |
| scrypt 해시, 10자, 15분 5회 잠금, 실패 문구 하나 | Task 1 |
| `nara user add/reset/disable/list` | Task 2 |
| 로그인하지 않으면 로그인 화면, 임시 비밀번호 → 바꾸기 강제, 세션 쿠키 설정, 로그아웃 | Task 3 |
| 서명 키 없으면 앱이 뜨지 않음 | Task 3, Task 8 |
| `TRUSTED_HOSTS`에 `NARA_HOST` | Task 3 |
| 저장·판정·부서·신재생·잠금 해제의 `user_id`, 이력의 이름, "(2단계 기록)" | Task 4 |
| 동시 수정: 버전 표시, 409, 이름/무명 문구, 입력 유지 | Task 5 |
| `nara run slot` 스케줄표, 주말 12시, 실패 뒤 계속, 겹침 방지 | Task 6 |
| `nara backup` 백업 API·무결성·gzip·rclone·보관 기간·`partial`, 목록 머리 백업 단계 | Task 7 |
| Caddy·waitress·systemd·`.env`·`update.sh`·`setup.md`·복구·옮기기 | Task 8 |
| 1·2단계 테스트 전부 통과 | 전 작업의 전체 검사 |

**스펙에 없는데 더한 것:**
- **ProxyFix(`x_proto=1`)** — Caddy 뒤에서 https Origin이 같은 출처 확인과 어긋나 모든 저장이 403이 되는 것을 막는다(Task 3)
- **로그인 뒤 돌아갈 주소 검사** — 로그인 화면이 남의 사이트로 튕기는 발판이 되지 않게 한다(Task 3)
- **없는 이메일에도 해시 비교** — 응답 시간으로 계정 유무가 드러나지 않게 한다(Task 1)
- **성공하면 실패 기록을 지운다** — 성공 사이사이의 실수로 잠기지 않게 한다(Task 1)
- **잠금 해제의 칸 이름 `verdict_release`** — 스펙은 `verdict`로 적었다. 그대로 두면 2단계 시트 이관이 거짓 충돌을 보고한다(Task 4)
- **버전 표시가 없는 요청은 검사하지 않는다** — 업데이트 전에 열어 둔 화면에는 비교할 표시가 없다(Task 5)
- **`docs/`를 ruff 대상에서 뺀다** — 2단계에서 ruff가 계획 문서의 코드 조각을 고쳐 써 뜻이 바뀌었다(Task 1)
