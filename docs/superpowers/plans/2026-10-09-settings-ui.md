# 웹 설정 화면 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 수집 키워드·관심기관·설치계획서 기관 별칭을 DB로 옮기고, 웹 설정 화면에서 확인 후 저장하게 한다.

**Architecture:** 새 모듈 `nara/settings_store.py`가 설정 표(`setting_item`·`setting_log`)의 처음 옮기기·읽기·변경 미리보기·반영을 맡는다. 코드 전체가 쓰는 `Settings` 데이터 모양은 그대로 두고, CLI와 웹이 파일 대신 `current_settings(conn, base)`로 읽는다. 웹은 `/settings`(보기·입력) → `/settings/preview`(확인) → `/settings/apply`(한 트랜잭션 반영) 세 단계다.

**Tech Stack:** Python 3.14, SQLite, Flask/Jinja, Typer, pytest, ruff(줄 100). 실행은 `uv run --no-sync`.

**Spec:** `docs/superpowers/specs/2026-10-09-settings-ui-design.md`

## Global Constraints

- 정본은 웹 설정 화면이다. `settings_seeded`가 남은 뒤에는 `config.toml` 목록을 다시 읽지 않는다.
- 관리 종류(kind): `title_required | title_excluded | org_excluded | focus_org | focus_exact_org | nr_alias`.
- `service_div_name`·`skip_cancelled`는 `config.toml`에 남긴다.
- 키워드·기관명은 2자 이상, 50자 이하. 앞뒤 공백만 지우고 안쪽 공백은 그대로 둔다.
- 숨길 사업 후보의 기본값은 체크 안 함이다. 숨김 사유는 `설정 변경: 제외 키워드 '감리'` 꼴로 남긴다.
- 관심에서 내린 기관: `tier = 'rest'`, `weekday_group = id % 5 + 1`. 올린 기관: `tier = 'focus'`, `weekday_group = NULL`.
- 확인 저장은 한 트랜잭션이다. 확인 화면 뒤 설정이 바뀌었으면 거부하고 "그사이 설정이 바뀌었습니다. 다시 확인하세요"를 띄운다.
- 오류 문구는 그대로 쓴다: "키워드는 2자 이상이어야 합니다: {값}", "50자까지 적을 수 있습니다", "`설치계획서 기관명 = 나라 앱 기관명` 꼴로 적으세요", 경고 "제목 필수 키워드가 없으면 모든 용역을 수집합니다", "바뀐 것이 없습니다", 안내 "전에 걸러진 공고는 다시 수집해야 들어옵니다(`nara backfill`)".
- 쓰기 요청은 기존 `_guard_writes`를 거친다. DB 잠김은 `BUSY_MESSAGE`로 503.
- 기존 테스트는 모두 통과해야 한다.

## Review Focus

- 안쪽 공백이 있는 키워드("제설 전진기지")는 공백을 지우지 않고 그대로 저장돼야 한다 → Task 3 테스트.
- 별칭 줄에 `=`가 여러 개면 첫 `=`에서만 나눈다 → Task 3 테스트.
- 이미 없어진 값을 빼라는 요청(다른 사람이 먼저 뺌)은 오류 없이 무시한다 → Task 3 테스트.
- 확인 저장 요청에 후보 목록에 없던 사업 번호를 넣어도 그 사업은 숨기지 않는다 → Task 5 테스트.
- 아직 옮기기 전인 DB를 읽기 전용으로 열면 파일 값(`base`)을 그대로 돌려준다 → Task 1 테스트.

## File Structure

| 파일 | 역할 |
|---|---|
| `nara/schema.sql` (수정) | `setting_item`·`setting_log` 표 |
| `nara/settings_store.py` (새) | 옮기기·읽기·지문·`Change`·미리보기·반영 |
| `nara/web/edit.py` (수정) | 입력 검사 `check_settings`, 숨김 내부 함수 `mark_hidden` 분리 |
| `nara/cli.py` (수정) | `_load_settings(conn, config)`로 DB 설정 읽기 |
| `nara/web/app.py` (수정) | 시작 때 옮기기, 요청마다 설정 읽기, `/settings` 세 경로 |
| `nara/web/templates/settings.html` (새) | 설정 화면 |
| `nara/web/templates/settings_preview.html` (새) | 확인 화면 |
| `nara/web/templates/base.html` (수정) | 상단 메뉴 "설정" |
| `config.toml` (수정) | 머리 주석 |
| `tests/test_settings_store.py` (새) | 저장소 테스트 |
| `tests/test_web_settings.py` (새) | 화면 테스트 |

---

### Task 1: 설정 표, 처음 옮기기, 읽기

**Files:**
- Modify: `nara/schema.sql` (끝에 추가)
- Create: `nara/settings_store.py`
- Test: `tests/test_settings_store.py`

**Interfaces:**
- Produces:
  - `KINDS: tuple[str, ...]`, `LABELS: dict[str, str]`
  - `seed_settings(conn, base: Settings, now: str) -> bool`
  - `is_seeded(conn) -> bool`
  - `current_settings(conn, base: Settings) -> Settings`
  - `items(conn, kind: str) -> list[sqlite3.Row]` (칸: kind, value, target, added_at, added_by)
  - `fingerprint(conn) -> str`

- [ ] **Step 1: Write the failing test**

`tests/test_settings_store.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --no-sync pytest -q -o addopts="" tests/test_settings_store.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'nara.settings_store'`

- [ ] **Step 3: Write minimal implementation**

`nara/schema.sql` 끝에 추가:

```sql

-- 웹 설정 화면이 정본. 처음 한 번만 config.toml 목록을 옮겨 채운다(app_state.settings_seeded).
CREATE TABLE IF NOT EXISTS setting_item (
  kind      TEXT NOT NULL,   -- title_required | title_excluded | org_excluded
                             -- | focus_org | focus_exact_org | nr_alias
  value     TEXT NOT NULL,   -- 키워드·기관명. nr_alias면 설치계획서 쪽 기관명
  target    TEXT,            -- nr_alias일 때만: 나라 앱 기관명
  added_at  TEXT NOT NULL,
  added_by  INTEGER REFERENCES app_user(id),
  PRIMARY KEY (kind, value)
);

CREATE TABLE IF NOT EXISTS setting_log (
  id        INTEGER PRIMARY KEY,
  at        TEXT NOT NULL,
  user_id   INTEGER REFERENCES app_user(id),
  kind      TEXT NOT NULL,
  action    TEXT NOT NULL,   -- add | remove | seed
  value     TEXT NOT NULL,
  target    TEXT
);
```

`nara/settings_store.py`:

```python
"""웹 설정 화면이 정본인 수집·관심기관 설정. 처음 한 번만 config.toml 목록을 옮긴다."""

import hashlib
import sqlite3
from dataclasses import replace

from nara.config import Settings

KINDS = (
    "title_required", "title_excluded", "org_excluded",
    "focus_org", "focus_exact_org", "nr_alias",
)  # fmt: skip
LABELS = {
    "title_required": "제목 필수 키워드",
    "title_excluded": "제목 제외 키워드",
    "org_excluded": "기관 제외 키워드",
    "focus_org": "관심기관 (이름에 포함)",
    "focus_exact_org": "관심기관 (이름이 정확히 같음)",
    "nr_alias": "설치계획서 기관 별칭",
}
# kind → Settings 칸. nr_alias는 (value, target) 쌍이라 따로 다룬다.
FIELDS = {
    "title_required": "title_required",
    "title_excluded": "title_excluded",
    "org_excluded": "org_excluded",
    "focus_org": "focus_orgs",
    "focus_exact_org": "focus_exact_orgs",
}
SEEDED_KEY = "settings_seeded"


def _pairs(settings: Settings) -> list[tuple[str, str, str | None]]:
    rows = [(kind, v, None) for kind, attr in FIELDS.items() for v in getattr(settings, attr)]
    return rows + [("nr_alias", a, b) for a, b in settings.nr_org_aliases]


def is_seeded(conn: sqlite3.Connection) -> bool:
    return (
        conn.execute("SELECT 1 FROM app_state WHERE key = ?", (SEEDED_KEY,)).fetchone()
        is not None
    )


def seed_settings(conn: sqlite3.Connection, base: Settings, now: str) -> bool:
    """처음 한 번만 파일 목록을 DB로 옮긴다. 옮겼으면 True."""
    if is_seeded(conn):
        return False
    with conn:
        for kind, value, target in _pairs(base):
            cur = conn.execute(
                "INSERT OR IGNORE INTO setting_item (kind, value, target, added_at) "
                "VALUES (?, ?, ?, ?)",
                (kind, value, target, now),
            )
            if cur.rowcount:
                conn.execute(
                    "INSERT INTO setting_log (at, kind, action, value, target) "
                    "VALUES (?, ?, 'seed', ?, ?)",
                    (now, kind, value, target),
                )
        conn.execute(
            "INSERT OR IGNORE INTO app_state (key, value) VALUES (?, ?)", (SEEDED_KEY, now)
        )
    return True


def items(conn: sqlite3.Connection, kind: str) -> list[sqlite3.Row]:
    """넣은 순서대로. 파일에서 옮긴 순서가 화면에도 그대로 보인다."""
    cur = conn.cursor()
    cur.row_factory = sqlite3.Row  # 부른 쪽 연결의 row_factory는 건드리지 않는다
    return cur.execute(
        "SELECT kind, value, target, added_at, added_by FROM setting_item "
        "WHERE kind = ? ORDER BY rowid",
        (kind,),
    ).fetchall()


def current_settings(conn: sqlite3.Connection, base: Settings) -> Settings:
    """DB 목록으로 base의 목록 칸을 바꾼다. 아직 옮기기 전이면 base 그대로."""
    if not is_seeded(conn):
        return base
    lists = {attr: tuple(r["value"] for r in items(conn, kind)) for kind, attr in FIELDS.items()}
    aliases = tuple((r["value"], r["target"]) for r in items(conn, "nr_alias"))
    return replace(base, **lists, nr_org_aliases=aliases)


def fingerprint(conn: sqlite3.Connection) -> str:
    """지금 설정 전체의 지문. 확인 화면 뒤 누가 바꿨는지 가린다."""
    rows = conn.execute(
        "SELECT kind, value, COALESCE(target, '') FROM setting_item ORDER BY kind, value"
    ).fetchall()
    text = "\n".join("\t".join(r) for r in rows)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --no-sync pytest -q -o addopts="" tests/test_settings_store.py tests/test_db.py`
Expected: PASS. `tests/test_db.py`가 표 목록을 확인하면 그 목록에 `"setting_item", "setting_log"`를 더한다(`dept_contact` 줄 다음).

- [ ] **Step 5: Commit**

```bash
git add nara/schema.sql nara/settings_store.py tests/test_settings_store.py tests/test_db.py
git commit -m "feat: 설정 목록을 DB로 옮기고 DB에서 읽는다"
```

---

### Task 2: 수집 명령과 웹 서버가 DB 설정을 읽는다

**Files:**
- Modify: `nara/cli.py` (`collect`, `backfill`, `migrate_tsv`, `serve`)
- Modify: `nara/web/app.py` (`create_app`, `nr_import`, `nr_detail`, `_nr_write`)
- Test: `tests/test_settings_store.py`

**Interfaces:**
- Consumes: `seed_settings`, `current_settings` (Task 1)
- Produces:
  - `nara.cli._load_settings(conn, config: Path) -> Settings`
  - `nara.web.app._settings(conn) -> Settings | None` (요청마다)

- [ ] **Step 1: Write the failing tests**

`tests/test_settings_store.py` 끝에 추가:

```python
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
```

같은 파일 끝에 하나 더(웹 서버가 시작 때 옮기고 요청마다 읽는지):

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --no-sync pytest -q -o addopts="" tests/test_settings_store.py`
Expected: FAIL — `ImportError: cannot import name '_load_settings'`와 `cannot import name '_settings'`.

- [ ] **Step 3: Write minimal implementation**

`nara/cli.py` — import에 `from nara.settings_store import current_settings, seed_settings` 추가, `_open_db` 아래에:

```python
def _load_settings(conn, config: Path) -> Settings:
    """파일은 처음 옮길 때와 기술 설정(service_div_name 등)에만 쓴다. 목록은 DB가 정본."""
    base = load_settings(config)
    seed_settings(conn, base, datetime.now().isoformat(timespec="seconds"))
    return current_settings(conn, base)
```

- `collect`: `settings = load_settings(config)` 줄을 지우고, `conn = _open_db(db)` 다음 줄에 `settings = _load_settings(conn, config)`. API 키 확인은 DB를 열기 전 그대로 둔다.
- `backfill`: 같은 방식.
- `migrate_tsv`: `settings = load_settings(config)`를 지우고 `conn = _open_db(db)` 다음에 `settings = _load_settings(conn, config)`.
- `serve`: 그대로 둔다(`settings = load_settings(config)`를 base로 `create_app`에 넘기고, 옮기기는 `create_app`이 한다).

`nara/web/app.py` — import에 `from nara.settings_store import current_settings, seed_settings` 추가. `create_app`의 `app.config["SETTINGS"] = settings` 다음에:

```python
    # 설정 목록은 DB가 정본이다. 처음 띄울 때 한 번 파일 목록을 옮긴다.
    # 없는 DB 파일은 만들지 않는다(DatabaseMissing 안내가 먼저다).
    if settings is not None and Path(db_path).exists():
        with closing(open_readwrite(Path(db_path), BUSY_TIMEOUT_SECONDS)) as conn:
            seed_settings(conn, settings, datetime.now().isoformat(timespec="seconds"))
```

모듈 수준 함수(`_rw_conn` 근처):

```python
def _settings(conn: sqlite3.Connection) -> Settings | None:
    """요청마다 DB에서 읽는다. 설정 화면에서 바꾸면 서버를 다시 띄우지 않아도 쓰인다."""
    base = current_app.config.get("SETTINGS")
    return current_settings(conn, base) if base is not None else None
```

- `nr_import`: `settings = current_app.config.get("SETTINGS")`와 그 `None` 확인을 `with` 안으로 옮긴다:

```python
        if current_app.config.get("SETTINGS") is None:
            return {"ok": False, "error": "설정 파일을 읽지 못해 받을 수 없습니다"}, 500
        now = datetime.now().isoformat(timespec="seconds")
        try:
            with closing(_rw_conn()) as conn, run_log(conn, "nr import", f"{len(rows)}행") as c:
                results = ingest(conn, rows, _settings(conn), now, c)
```

- `nr_detail`: `settings = current_app.config.get("SETTINGS")`를 `settings = _settings(conn)`으로.
- `_nr_write`: `None` 확인은 `current_app.config.get("SETTINGS")`로 두고, `return action(conn, settings, now)`를 `return action(conn, _settings(conn), now)`로.

`open_readwrite`·`closing`·`datetime`은 app.py에 이미 import돼 있다(`_rw_conn`이 쓴다).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --no-sync pytest -q -o addopts="" tests/test_settings_store.py tests/test_web_nr.py tests/test_collect.py tests/test_cli.py tests/test_web.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add nara/cli.py nara/web/app.py tests/test_settings_store.py
git commit -m "feat: 수집 명령과 웹 서버가 설정을 DB에서 읽는다"
```

---

### Task 3: 바꿀 값 입력 검사

**Files:**
- Modify: `nara/settings_store.py` (`Change` 추가)
- Modify: `nara/web/edit.py` (`check_settings` 추가)
- Test: `tests/test_settings_store.py`

**Interfaces:**
- Consumes: `KINDS`, `items` (Task 1)
- Produces:
  - `Change(adds: tuple[tuple[str, str, str | None], ...], removes: tuple[tuple[str, str], ...])`, `Change.empty -> bool`, `Change.apply_to(settings: Settings) -> Settings`
  - `edit.check_settings(form: MultiDict, current: dict[str, set[str]]) -> Checked` — `values = {"change": Change, "warnings": list[str]}`, `errors: dict[kind, str]`

- [ ] **Step 1: Write the failing test**

`tests/test_settings_store.py` 끝에 추가:

```python
from werkzeug.datastructures import MultiDict

from nara.settings_store import Change
from nara.web.edit import check_settings

CURRENT = {k: set() for k in (
    "title_required", "title_excluded", "org_excluded",
    "focus_org", "focus_exact_org", "nr_alias",
)}  # fmt: skip


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
    checked = _check(add_nr_alias="서초구청 = 서울특별시 서초구\n가=나=다")
    assert checked.values["change"].adds == (
        ("nr_alias", "서초구청", "서울특별시 서초구"),
        ("nr_alias", "가", "나=다"),
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --no-sync pytest -q -o addopts="" tests/test_settings_store.py`
Expected: FAIL — `ImportError: cannot import name 'Change'`

- [ ] **Step 3: Write minimal implementation**

`nara/settings_store.py`에 추가(`from dataclasses import dataclass, replace`로 import 수정):

```python
@dataclass(frozen=True)
class Change:
    adds: tuple[tuple[str, str, str | None], ...] = ()  # (kind, value, target)
    removes: tuple[tuple[str, str], ...] = ()  # (kind, value)

    @property
    def empty(self) -> bool:
        return not self.adds and not self.removes

    def apply_to(self, settings: Settings) -> Settings:
        """빼고 나서 더한다. 더한 값은 목록 끝에 붙는다."""
        gone = set(self.removes)
        lists = {}
        for kind, attr in FIELDS.items():
            kept = [v for v in getattr(settings, attr) if (kind, v) not in gone]
            kept += [v for k, v, _ in self.adds if k == kind and v not in kept]
            lists[attr] = tuple(kept)
        aliases = [(a, b) for a, b in settings.nr_org_aliases if ("nr_alias", a) not in gone]
        aliases += [(v, t) for k, v, t in self.adds if k == "nr_alias"]
        return replace(settings, **lists, nr_org_aliases=tuple(aliases))
```

`nara/web/edit.py`에 추가(맨 위 import에 `from nara.settings_store import KINDS, Change`; `Mapping`이 이미 있으면 그대로):

```python
SETTING_MIN = 2
SETTING_LIMIT = 50
ALIAS_FORMAT = "`설치계획서 기관명 = 나라 앱 기관명` 꼴로 적으세요"
NO_REQUIRED = "제목 필수 키워드가 없으면 모든 용역을 수집합니다"


def _setting_error(value: str) -> str | None:
    if len(value) < SETTING_MIN:
        return f"키워드는 2자 이상이어야 합니다: {value}"
    if len(value) > SETTING_LIMIT:
        return f"{SETTING_LIMIT}자까지 적을 수 있습니다"
    return None


def _setting_lines(kind: str, raw: str) -> tuple[list[tuple[str, str | None]], str | None]:
    """한 줄에 하나. 앞뒤 공백만 지운다 — '제설 전진기지'의 안쪽 공백은 키워드의 일부다."""
    out: list[tuple[str, str | None]] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        target = None
        if kind == "nr_alias":
            value, sep, target = (part.strip() for part in line.partition("="))
            if not sep or not value or not target:
                return [], ALIAS_FORMAT
            line = value
        error = _setting_error(line) or (target and _setting_error(target))
        if error:
            return [], error
        if all(v != line for v, _ in out):
            out.append((line, target))
    return out, None


def check_settings(form, current: Mapping[str, set[str]]) -> Checked:
    """설정 화면 입력. 이미 있는 값을 더하거나 없는 값을 빼는 것은 오류가 아니라 무시한다."""
    adds: list[tuple[str, str, str | None]] = []
    removes: list[tuple[str, str]] = []
    errors: dict[str, str] = {}
    for kind in KINDS:
        lines, error = _setting_lines(kind, form.get(f"add_{kind}", ""))
        if error:
            errors[kind] = error
            continue
        adds += [(kind, v, t) for v, t in lines if v not in current[kind]]
        removes += [(kind, v) for v in form.getlist(f"remove_{kind}") if v in current[kind]]
    warnings = []
    left = (current["title_required"] - {v for k, v in removes if k == "title_required"}) | {
        v for k, v, _ in adds if k == "title_required"
    }
    if current["title_required"] and not left:
        warnings.append(NO_REQUIRED)
    change = Change(tuple(adds), tuple(removes))
    return Checked({"change": change, "warnings": warnings}, errors)
```

`nara.settings_store`가 `nara.web`을 import하지 않으므로 순환 import는 없다.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --no-sync pytest -q -o addopts="" tests/test_settings_store.py tests/test_web_edit.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add nara/settings_store.py nara/web/edit.py tests/test_settings_store.py
git commit -m "feat: 설정 화면 입력을 검사해 바꿀 값을 만든다"
```

---

### Task 4: 저장 전 미리보기와 한 트랜잭션 반영

**Files:**
- Modify: `nara/settings_store.py` (`Plan`, `plan_change`, `apply_change`, `StaleSettings`, `recent_log`)
- Modify: `nara/web/edit.py` (`mark_hidden` 분리)
- Test: `tests/test_settings_store.py`

**Interfaces:**
- Consumes: `Change`, `fingerprint`, `current_settings`, `seed_settings` (Task 1·3); `filters.title_passes`, `filters.org_passes`, `filters.is_focus_org`; `store.WEEKDAY_GROUPS`
- Produces:
  - `HideCandidate(project_id: int, name: str, org_name: str, reason: str)`
  - `OrgMove(org_id: int, name: str, projects: int)`
  - `Plan(change: Change, hide: tuple[HideCandidate, ...], demote: tuple[OrgMove, ...], promote: tuple[OrgMove, ...], widened: bool, fingerprint: str)`
  - `plan_change(conn, base: Settings, change: Change) -> Plan`
  - `apply_change(conn, plan: Plan, hide_ids: set[int], user_id: int | None, now: str) -> dict[str, int]` — 키 `"items"`, `"hidden"`, `"demoted"`, `"promoted"`
  - `StaleSettings(Exception)`
  - `recent_log(conn, limit: int = 50) -> list[sqlite3.Row]` (칸: at, user_name, kind, action, value, target)
  - `edit.mark_hidden(conn, project_ids, reason, now, user_id) -> int` (트랜잭션을 열지 않음)

- [ ] **Step 1: Write the failing test**

`tests/test_settings_store.py` 끝에 추가:

```python
from nara.settings_store import StaleSettings, apply_change, plan_change, recent_log
from nara.store import ensure_project, upsert_org


def _world(conn):
    """공고가 있는 사업 둘(감리·체육관), 공고 없는 사업 하나, 관심기관 둘."""
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
    _, wanju, yongin = _world(conn)
    seongnam = upsert_org(conn, "경기도 시험시", BASE, NOW)
    plan = plan_change(
        conn,
        BASE,
        Change(adds=(("focus_org", "시험시", None),), removes=(("focus_org", "용인시"),)),
    )
    assert [(m.org_id, m.projects) for m in plan.demote] == [(yongin, 1)]
    assert [m.org_id for m in plan.promote] == [seongnam]


def test_apply_hides_only_checked_candidates_and_moves_orgs(conn):
    ids, _, yongin = _world(conn)
    change = Change(adds=(("title_excluded", "공사관리", None),), removes=(("focus_org", "용인시"),))
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
    change = Change(adds=(("title_excluded", "공사관리", None),), removes=(("focus_org", "용인시"),))
    plan = plan_change(conn, BASE, change)
    conn.execute(
        "CREATE TRIGGER boom BEFORE INSERT ON setting_log "
        "WHEN NEW.action = 'remove' BEGIN SELECT RAISE(ABORT, 'boom'); END"
    )
    with pytest.raises(sqlite3.DatabaseError):
        apply_change(conn, plan, {ids["hall"]}, None, NOW)
    hall = conn.execute("SELECT hidden_at FROM project WHERE id = ?", (ids["hall"],)).fetchone()
    assert hall[0] is None
    assert conn.execute("SELECT tier FROM org WHERE id = ?", (yongin,)).fetchone()[0] == "focus"
    assert "공사관리" not in current_settings(conn, BASE).title_excluded
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --no-sync pytest -q -o addopts="" tests/test_settings_store.py`
Expected: FAIL — `ImportError: cannot import name 'StaleSettings'`

- [ ] **Step 3: Write minimal implementation**

`nara/web/edit.py` — `hide_projects`의 몸통을 트랜잭션 없는 함수로 뺀다:

```python
def mark_hidden(
    conn: sqlite3.Connection,
    project_ids: list[int],
    reason: str,
    now: str,
    user_id: int | None = None,
) -> int:
    """트랜잭션을 열지 않는다 — 설정 저장처럼 부른 쪽이 한 번에 커밋할 때 쓴다."""
    reason = reason.strip()[:TEXT_LIMIT] or None
    hidden = 0
    for pid in project_ids:
        cur = conn.execute(
            "UPDATE project SET hidden_at = ?, hidden_by = ?, hidden_reason = ? "
            "WHERE id = ? AND hidden_at IS NULL",
            (now, user_id, reason, pid),
        )
        if cur.rowcount:
            _log(conn, pid, "hidden", None, _hidden_label(reason), now, user_id)
            hidden += 1
    return hidden


def hide_projects(
    conn: sqlite3.Connection,
    project_ids: list[int],
    reason: str,
    now: str,
    user_id: int | None = None,
) -> int:
    """목록에서 숨긴다. 이미 숨긴 사업·없는 id는 건드리지 않는다. 숨긴 건수를 돌려준다."""
    with conn:
        return mark_hidden(conn, project_ids, reason, now, user_id)
```

`nara/settings_store.py`에 추가(맨 위 import에 `from nara.filters import is_focus_org, org_passes, title_passes`, `from nara.store import WEEKDAY_GROUPS`):

```python
class StaleSettings(Exception):
    """확인 화면을 띄운 뒤 다른 사람이 설정을 바꿨다."""


@dataclass(frozen=True)
class HideCandidate:
    project_id: int
    name: str
    org_name: str
    reason: str


@dataclass(frozen=True)
class OrgMove:
    org_id: int
    name: str
    projects: int


@dataclass(frozen=True)
class Plan:
    change: Change
    hide: tuple[HideCandidate, ...]
    demote: tuple[OrgMove, ...]
    promote: tuple[OrgMove, ...]
    widened: bool
    fingerprint: str


def _first_hit(text: str, words: list[str]) -> str | None:
    return next((w for w in words if w in text), None)


def _hide_candidates(conn, before: Settings, after: Settings, change: Change):
    """바뀌기 전에는 통과했고 바뀐 뒤에는 막히는 사업만. 공고 없는 사업은 제목으로 고르지 않는다."""
    new_title = [v for k, v, _ in change.adds if k == "title_excluded"]
    gone_required = [v for k, v in change.removes if k == "title_required"]
    new_org = [v for k, v, _ in change.adds if k == "org_excluded"]
    rows = conn.execute(
        "SELECT p.id, p.name, o.name AS org_name, n.title FROM project p "
        "JOIN org o ON o.id = p.org_id LEFT JOIN notice n ON n.project_id = p.id "
        "WHERE p.hidden_at IS NULL ORDER BY o.name, p.id"
    ).fetchall()
    projects: dict[int, dict] = {}
    for r in rows:
        p = projects.setdefault(r[0], {"name": r[1], "org": r[2], "titles": []})
        if r[3]:
            p["titles"].append(r[3])
    found = []
    for pid, p in projects.items():
        reason = None
        if org_passes(p["org"], before) and not org_passes(p["org"], after):
            reason = f"설정 변경: 기관 제외 키워드 '{_first_hit(p['org'], new_org)}'"
        elif (
            p["titles"]
            and any(title_passes(t, before) for t in p["titles"])
            and not any(title_passes(t, after) for t in p["titles"])
        ):
            hit = next(filter(None, (_first_hit(t, new_title) for t in p["titles"])), None)
            reason = (
                f"설정 변경: 제외 키워드 '{hit}'"
                if hit
                else f"설정 변경: 필수 키워드 '{', '.join(gone_required)}' 뺌"
            )
        if reason:
            found.append(HideCandidate(pid, p["name"], p["org"], reason))
    return tuple(found)


def _org_moves(conn, before: Settings, after: Settings):
    demote, promote = [], []
    for r in conn.execute(
        "SELECT o.id, o.name, o.tier, COUNT(p.id) FROM org o "
        "LEFT JOIN project p ON p.org_id = o.id AND p.hidden_at IS NULL "
        "GROUP BY o.id ORDER BY o.name"
    ):
        was, now = is_focus_org(r[1], before), is_focus_org(r[1], after)
        if r[2] == "focus" and was and not now:
            demote.append(OrgMove(r[0], r[1], r[3]))
        elif r[2] == "rest" and now:
            promote.append(OrgMove(r[0], r[1], r[3]))
    return tuple(demote), tuple(promote)


def plan_change(conn: sqlite3.Connection, base: Settings, change: Change) -> Plan:
    """저장 전 확인 화면. DB를 바꾸지 않는다."""
    before = current_settings(conn, base)
    after = change.apply_to(before)
    demote, promote = _org_moves(conn, before, after)
    widened = any(k in ("title_excluded", "org_excluded") for k, _ in change.removes) or any(
        k == "title_required" for k, _, _ in change.adds
    )
    return Plan(
        change,
        _hide_candidates(conn, before, after, change),
        demote,
        promote,
        widened,
        fingerprint(conn),
    )


def apply_change(
    conn: sqlite3.Connection, plan: Plan, hide_ids: set[int], user_id: int | None, now: str
) -> dict[str, int]:
    """설정·숨김·관심 조정·기록을 한 트랜잭션으로. 확인 화면 뒤 설정이 바뀌었으면 거부한다."""
    from nara.web.edit import mark_hidden  # 웹 숨김과 같은 기록을 남긴다

    if fingerprint(conn) != plan.fingerprint:
        raise StaleSettings
    done = {"items": 0, "hidden": 0, "demoted": 0, "promoted": 0}
    with conn:
        for kind, value in plan.change.removes:
            conn.execute("DELETE FROM setting_item WHERE kind = ? AND value = ?", (kind, value))
            conn.execute(
                "INSERT INTO setting_log (at, user_id, kind, action, value) "
                "VALUES (?, ?, ?, 'remove', ?)",
                (now, user_id, kind, value),
            )
            done["items"] += 1
        for kind, value, target in plan.change.adds:
            conn.execute(
                "INSERT INTO setting_item (kind, value, target, added_at, added_by) "
                "VALUES (?, ?, ?, ?, ?)",
                (kind, value, target, now, user_id),
            )
            conn.execute(
                "INSERT INTO setting_log (at, user_id, kind, action, value, target) "
                "VALUES (?, ?, ?, 'add', ?, ?)",
                (now, user_id, kind, value, target),
            )
            done["items"] += 1
        for c in plan.hide:
            if c.project_id in hide_ids:
                done["hidden"] += mark_hidden(conn, [c.project_id], c.reason, now, user_id)
        for m in plan.demote:
            conn.execute(
                "UPDATE org SET tier = 'rest', weekday_group = ? WHERE id = ?",
                (m.org_id % WEEKDAY_GROUPS + 1, m.org_id),
            )
            done["demoted"] += 1
        for m in plan.promote:
            conn.execute(
                "UPDATE org SET tier = 'focus', weekday_group = NULL WHERE id = ?", (m.org_id,)
            )
            done["promoted"] += 1
    return done


def recent_log(conn: sqlite3.Connection, limit: int = 50) -> list[sqlite3.Row]:
    cur = conn.cursor()
    cur.row_factory = sqlite3.Row
    return cur.execute(
        "SELECT l.at, u.name AS user_name, l.kind, l.action, l.value, l.target "
        "FROM setting_log l LEFT JOIN app_user u ON u.id = l.user_id "
        "WHERE l.action != 'seed' ORDER BY l.id DESC LIMIT ?",
        (limit,),
    ).fetchall()
```

`mark_hidden`을 함수 안에서 import하는 이유: `nara.web.edit`가 `nara.settings_store`를 import하므로 모듈 수준에서 서로 부르면 순환한다(Task 3).

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --no-sync pytest -q -o addopts="" tests/test_settings_store.py tests/test_web.py -k "settings or hide or hidden"`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add nara/settings_store.py nara/web/edit.py tests/test_settings_store.py
git commit -m "feat: 설정 변경의 영향을 미리 보고 한 번에 반영한다"
```

---

### Task 5: 설정 화면·확인 화면

**Files:**
- Create: `nara/web/templates/settings.html`, `nara/web/templates/settings_preview.html`
- Modify: `nara/web/app.py` (`/settings`, `/settings/preview`, `/settings/apply`), `nara/web/templates/base.html` (메뉴)
- Modify: `config.toml` (머리 주석)
- Test: `tests/test_web_settings.py`

**Interfaces:**
- Consumes: `KINDS`, `LABELS`, `items`, `recent_log`, `plan_change`, `apply_change`, `StaleSettings`, `Change` (Task 1·3·4); `edit.check_settings` (Task 3); `_settings` (Task 2)
- Produces: 경로 `settings`(GET), `settings_preview`(POST), `settings_apply`(POST)

- [ ] **Step 1: Write the failing test**

`tests/test_web_settings.py`:

```python
import re
import sqlite3

from tests.test_web import _client, _post, _text, world  # noqa: F401 — world는 픽스처


def test_the_settings_page_lists_every_kind_with_current_values(world):
    path, _ = world
    text = _text(_client(path).get("/settings"))
    for label in ("제목 필수 키워드", "제목 제외 키워드", "기관 제외 키워드", "설치계획서 기관 별칭"):
        assert label in text
    assert 'name="remove_title_excluded" value="감리"' in text
    assert 'href="/settings"' in text  # 상단 메뉴
    assert 'class="setting-search"' in text  # 115개짜리 제외 키워드 목록은 검색으로 거른다


def test_preview_then_apply_hides_only_checked_candidates(world):
    path, ids = world
    client = _client(path)
    form = {"add_title_excluded": "다목적"}
    preview = _post(client, "/settings/preview", form)
    text = _text(preview)
    assert preview.status_code == 200
    assert "완주군 다목적체육관" in text  # 공고 '완주군 다목적체육관 건립 설계용역'
    assert f'name="hide" value="{ids["gym"]}">' in text  # 기본값 체크 안 함
    fp = re.search(r'name="fingerprint" value="([0-9a-f]+)"', text).group(1)
    resp = _post(
        client,
        "/settings/apply",
        {**form, "fingerprint": fp, "hide": [str(ids["gym"]), str(ids["museum"])]},
    )
    assert resp.status_code == 302
    c = sqlite3.connect(path)
    hidden = dict(c.execute("SELECT id, hidden_reason FROM project WHERE hidden_at IS NOT NULL"))
    c.close()
    assert hidden == {ids["gym"]: "설정 변경: 제외 키워드 '다목적'"}  # 후보 아닌 박물관은 그대로
    assert 'value="다목적"' in _text(client.get("/settings"))


def test_apply_after_someone_else_saved_shows_the_preview_again(world):
    path, _ = world
    client = _client(path)
    form = {"add_org_excluded": "시험청"}
    fp = re.search(
        r'name="fingerprint" value="([0-9a-f]+)"', _text(_post(client, "/settings/preview", form))
    ).group(1)
    c = sqlite3.connect(path)
    c.execute(
        "INSERT INTO setting_item (kind, value, added_at) VALUES ('org_excluded', '먼저청', 'x')"
    )
    c.commit()
    c.close()
    resp = _post(client, "/settings/apply", {**form, "fingerprint": fp})
    assert resp.status_code == 409
    assert "그사이 설정이 바뀌었습니다. 다시 확인하세요" in _text(resp)


def test_a_bad_line_is_shown_again_with_the_reason(world):
    path, _ = world
    resp = _post(_client(path), "/settings/preview", {"add_org_excluded": "감\n교육원"})
    assert resp.status_code == 422
    text = _text(resp)
    assert "키워드는 2자 이상이어야 합니다: 감" in text and "교육원" in text


def test_nothing_changed_says_so(world):
    path, _ = world
    client = _client(path)
    resp = _post(client, "/settings/preview", {"add_title_excluded": "감리"})
    assert resp.status_code == 302
    assert "바뀐 것이 없습니다" in _text(client.get(resp.headers["Location"]))


def test_settings_writes_refuse_another_site(world):
    path, _ = world
    client = _client(path)
    for url in ("/settings/preview", "/settings/apply"):
        resp = _post(client, url, {"add_org_excluded": "시험청"}, origin="http://evil.example")
        assert resp.status_code == 403
```

주: `tests/test_web.py`의 `world` 픽스처와 도우미를 그대로 가져다 쓴다. 도우미가 `tests` 패키지로 import되지 않으면(`tests/__init__.py`가 없으면) `conftest.py`로 옮기지 말고, 이 테스트들을 `tests/test_web.py` 끝에 넣는다.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --no-sync pytest -q -o addopts="" tests/test_web_settings.py`
Expected: FAIL — `/settings` 404, `href="/settings"` 없음

- [ ] **Step 3: Write minimal implementation**

`nara/web/app.py` — import에 `from nara import settings_store`, `from werkzeug.datastructures import MultiDict` 추가. 경로(`prices` 다음):

```python
    def _setting_items(conn) -> dict[str, list]:
        return {k: settings_store.items(conn, k) for k in settings_store.KINDS}

    def _render_settings(form: MultiDict, errors, status=200):
        conn = get_conn()
        return render_template(
            "settings.html",
            kinds=settings_store.KINDS,
            labels=settings_store.LABELS,
            values=_setting_items(conn),
            log=settings_store.recent_log(conn),
            form=form,
            errors=errors,
        ), status

    def _setting_plan():
        """폼을 검사하고 미리보기를 만든다. (plan, warnings) 또는 (오류 응답, None)."""
        conn = get_conn()
        current = {k: {r["value"] for r in v} for k, v in _setting_items(conn).items()}
        checked = edit.check_settings(request.form, current)
        if not checked.ok:
            return _render_settings(request.form, checked.errors, 422), None
        change = checked.values["change"]
        if change.empty:
            flash("바뀐 것이 없습니다")
            return redirect(url_for("settings")), None
        base = current_app.config["SETTINGS"]
        plan = settings_store.plan_change(conn, base, change)
        return plan, checked.values["warnings"]

    def _render_preview(plan, warnings, message=None, status=200):
        return render_template(
            "settings_preview.html",
            plan=plan,
            warnings=warnings,
            labels=settings_store.LABELS,
            form=request.form,
            kinds=settings_store.KINDS,
            message=message,
        ), status

    @app.get("/settings")
    def settings():
        return _render_settings(MultiDict(), {})

    @app.post("/settings/preview")
    def settings_preview():
        plan, warnings = _setting_plan()
        if warnings is None:
            return plan
        return _render_preview(plan, warnings)

    @app.post("/settings/apply")
    def settings_apply():
        plan, warnings = _setting_plan()
        if warnings is None:
            return plan
        stale = "그사이 설정이 바뀌었습니다. 다시 확인하세요"
        if request.form.get("fingerprint") != plan.fingerprint:
            return _render_preview(plan, warnings, stale, 409)
        hide_ids = {int(v) for v in request.form.getlist("hide") if v.isdigit()}
        now = datetime.now().isoformat(timespec="seconds")
        try:
            with closing(_rw_conn()) as conn:
                done = settings_store.apply_change(conn, plan, hide_ids, g.user.id, now)
        except settings_store.StaleSettings:
            return _render_preview(plan, warnings, stale, 409)
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc):
                raise
            return _render_preview(plan, warnings, BUSY_MESSAGE, 503)
        flash(
            f"설정 {done['items']}건을 바꿨습니다 — 숨김 {done['hidden']}건, "
            f"관심 내림 {done['demoted']}곳, 관심 올림 {done['promoted']}곳"
        )
        return redirect(url_for("settings"))
```

`apply_change`가 후보에 없는 번호를 무시하는 것은 Task 4 구현(후보를 돌며 `hide_ids`에 있는 것만 숨김)이 보장한다.

`nara/web/templates/base.html` 메뉴 줄에서 `<a href="{{ url_for('prices') }}">단가 관리</a> · ` 다음에 `<a href="{{ url_for('settings') }}">설정</a> · `를 넣는다.

`nara/web/templates/settings.html`:

```html
{% extends "base.html" %}
{% block body %}
<h1>설정</h1>
<p class="muted">여기가 정본입니다. 저장하면 다음 수집부터 쓰입니다. 저장 전에 이미 모은 사업에 미칠 영향을 먼저 보여 줍니다.</p>
{% if errors._form %}<p class="bad">{{ errors._form }}</p>{% endif %}
<form method="post" action="{{ url_for('settings_preview') }}">
{% for kind in kinds %}
<fieldset class="setting">
  <legend>{{ labels[kind] }} <span class="muted">{{ values[kind]|length }}개</span></legend>
  {% if errors[kind] %}<p class="bad">{{ errors[kind] }}</p>{% endif %}
  {% if values[kind]|length > 10 %}<input type="search" class="setting-search" placeholder="값 검색" aria-label="{{ labels[kind] }} 검색" autocomplete="off">{% endif %}
  <div class="setting-values">
  {% for r in values[kind] %}
    <label><input type="checkbox" name="remove_{{ kind }}" value="{{ r.value }}"{% if r.value in form.getlist('remove_' ~ kind) %} checked{% endif %}> {{ r.value }}{% if r.target %} → {{ r.target }}{% endif %}</label>
  {% else %}
    <span class="muted">비어 있음</span>
  {% endfor %}
  </div>
  <label>더할 값 (한 줄에 하나{% if kind == 'nr_alias' %}, <code>설치계획서 기관명 = 나라 앱 기관명</code>{% endif %})
    <textarea name="add_{{ kind }}" rows="3">{{ form.get('add_' ~ kind, '') }}</textarea>
  </label>
  <p class="muted">체크한 값은 뺍니다.</p>
</fieldset>
{% endfor %}
<button type="submit">저장 (확인 화면으로)</button>
</form>

<h2>최근 변경</h2>
<div class="table-wrap"><table>
<thead><tr><th>때</th><th>사람</th><th>종류</th><th>변경</th><th>값</th></tr></thead>
<tbody>
{% for r in log %}
<tr><td>{{ r.at }}</td><td>{{ r.user_name|dash }}</td><td>{{ labels[r.kind] }}</td><td>{{ '더함' if r.action == 'add' else '뺌' }}</td><td>{{ r.value }}{% if r.target %} → {{ r.target }}{% endif %}</td></tr>
{% else %}
<tr><td colspan="5" class="muted">아직 바꾼 기록이 없습니다</td></tr>
{% endfor %}
</tbody>
</table></div>
<script>
document.querySelectorAll(".setting-search").forEach(function (box) {
  box.addEventListener("input", function () {
    var q = box.value.replace(/\s+/g, "");
    box.parentElement.querySelectorAll(".setting-values label").forEach(function (l) {
      l.hidden = q !== "" && l.textContent.replace(/\s+/g, "").indexOf(q) < 0;
    });
  });
});
</script>
{% endblock %}
```

검색창 이름(`name`)이 없으므로 폼으로 보내지지 않는다. `base.html`의 `.org-list label[hidden]` 규칙과 같게 `.setting-values label[hidden] { display: none; }`도 스타일에 더한다.

`nara/web/templates/settings_preview.html`:

```html
{% extends "base.html" %}
{% block body %}
<h1>설정 변경 확인</h1>
{% if message %}<p class="bad">{{ message }}</p>{% endif %}
{% for w in warnings %}<p class="bad">{{ w }}</p>{% endfor %}
<form method="post" action="{{ url_for('settings_apply') }}">
  {% for kind in kinds %}
    {% for v in form.getlist('remove_' ~ kind) %}<input type="hidden" name="remove_{{ kind }}" value="{{ v }}">{% endfor %}
    <input type="hidden" name="add_{{ kind }}" value="{{ form.get('add_' ~ kind, '') }}">
  {% endfor %}
  <input type="hidden" name="fingerprint" value="{{ plan.fingerprint }}">

  <h2>바뀌는 값</h2>
  <ul>
  {% for kind in kinds %}
    {% set added = plan.change.adds|selectattr(0, 'equalto', kind)|list %}
    {% set gone = plan.change.removes|selectattr(0, 'equalto', kind)|list %}
    {% if added or gone %}
    <li>{{ labels[kind] }} —
      {% if added %}더함: {% for a in added %}{{ a[1] }}{% if a[2] %} → {{ a[2] }}{% endif %}{% if not loop.last %}, {% endif %}{% endfor %}{% endif %}
      {% if added and gone %} / {% endif %}
      {% if gone %}뺌: {{ gone|map(attribute=1)|join(', ') }}{% endif %}
    </li>
    {% endif %}
  {% endfor %}
  </ul>

  {% if plan.widened %}<p class="muted">전에 걸러진 공고는 다시 수집해야 들어옵니다(<code>nara backfill</code>)</p>{% endif %}

  {% if plan.hide %}
  <h2>이미 수집된 사업 중 {{ plan.hide|length }}건이 걸립니다</h2>
  <p class="muted">숨길 사업만 체크하세요. 체크하지 않은 사업은 그대로 둡니다. 숨긴 사업은 "숨긴 사업"에서 되돌릴 수 있습니다.</p>
  <label><input type="checkbox" id="hide-all"> 모두 선택</label>
  <div class="table-wrap"><table>
  <thead><tr><th>숨김</th><th>수요기관</th><th>사업</th><th>걸린 이유</th></tr></thead>
  <tbody>
  {% for c in plan.hide %}
  <tr><td><input type="checkbox" name="hide" value="{{ c.project_id }}"></td><td>{{ c.org_name }}</td><td><a href="{{ url_for('detail', project_id=c.project_id) }}" target="_blank" rel="noopener">{{ c.name }}</a></td><td>{{ c.reason }}</td></tr>
  {% endfor %}
  </tbody></table></div>
  {% endif %}

  {% if plan.demote %}
  <h2>관심에서 빠질 기관 {{ plan.demote|length }}곳 (사업 {{ plan.demote|sum(attribute='projects') }}건)</h2>
  <p class="muted">일반 기관이 되어 요일별로 조회합니다. 사업과 판정 기록은 그대로입니다.</p>
  <ul>{% for m in plan.demote %}<li>{{ m.name }} ({{ m.projects }}건)</li>{% endfor %}</ul>
  {% endif %}
  {% if plan.promote %}
  <h2>관심으로 올릴 기관 {{ plan.promote|length }}곳</h2>
  <ul>{% for m in plan.promote %}<li>{{ m.name }}</li>{% endfor %}</ul>
  {% endif %}

  <button type="submit">확인 저장</button>
  <a href="{{ url_for('settings') }}">취소</a>
</form>
<script>
(function () {
  var all = document.getElementById("hide-all");
  if (!all) return;
  all.addEventListener("change", function (e) {
    document.querySelectorAll('input[name=hide]').forEach(function (b) { b.checked = e.target.checked; });
  });
})();
</script>
{% endblock %}
```

`base.html` 스타일(`form.filters label` 줄 근처)에 추가:

```css
  fieldset.setting { border: 1px solid var(--field-line); padding: 8px; margin: 0 0 12px; }
  .setting-values { display: flex; flex-wrap: wrap; gap: 4px 12px; max-height: 12rem; overflow-y: auto; margin-bottom: 8px; }
  fieldset.setting textarea { width: 100%; box-sizing: border-box; }
  .setting-values label[hidden] { display: none; }
```

`config.toml` 머리 주석 두 줄(`# 이 파일의 값은 스프레드시트 ...`, `# 시트가 정본이다 ...`)을 다음으로 바꾼다:

```toml
# 아래 목록(키워드·관심기관·별칭)은 처음 한 번 DB로 옮기는 초기값이다(2026-10-09).
# 정본은 웹 설정 화면(/settings)이다. 여기를 고쳐도 이미 옮긴 DB에는 반영되지 않는다.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --no-sync pytest -q -o addopts="" tests/test_web_settings.py tests/test_web.py`
Expected: PASS. 그다음 `uv run --no-sync ruff check nara tests && uv run --no-sync ruff format --check nara tests`, 마지막으로 전체 `uv run --no-sync pytest -q -o addopts=""`.

- [ ] **Step 5: Commit**

```bash
git add nara/web/app.py nara/web/templates/settings.html nara/web/templates/settings_preview.html nara/web/templates/base.html config.toml tests/test_web_settings.py
git commit -m "feat: 웹 설정 화면에서 키워드·관심기관·별칭을 확인 후 저장한다"
```

---

## 실제 DB 적용 (실행자 메모)

병합 후 서버를 처음 띄우거나 수집이 처음 돌 때 `config.toml` 목록이 DB로 옮겨진다. 실제 `data/nara.db`에서는 옮기기 전에 백업을 남긴다(`nara backup` 또는 `sqlite3` backup API). 백업과 병합·푸시는 사용자 확인 뒤에 한다.
