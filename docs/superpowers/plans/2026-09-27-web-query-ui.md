# 웹 조회 화면 1단계 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 수집한 사업을 브라우저에서 조회하는 로컬 읽기 전용 화면(`nara serve`)을 만든다.

**Architecture:** Flask 서버가 HTML을 그려 보낸다. 조회 조건은 URL 쿼리스트링에 담긴다. `nara/web/query.py`(DB·HTTP를 모르는 순수 함수)가 URL 인자를 검증된 조건과 SQL로 바꾸고, `nara/web/data.py`가 DB를 읽기 전용으로 열어 실행한다. `nara/web/app.py`는 요청을 받아 넘기고 템플릿을 그리는 일만 한다.

**Tech Stack:** Python 3.14, uv, Flask 3.1(Jinja2 포함), stdlib `sqlite3`, Typer, pytest, ruff

**Spec:** `docs/superpowers/specs/2026-09-27-web-query-ui-design.md`

## Global Constraints

- Python `>=3.14`, `uv`로 실행한다. 새 의존성은 `flask` 하나뿐이다
- ruff: `line-length = 100`, 규칙 `E, F, I, UP, B`. `uv run ruff check .`와 `uv run ruff format --check .`가 깨끗해야 한다. **ruff는 Markdown 안의 파이썬 코드 블록도 포맷한다** — 이 계획 문서도 검사 대상이다
- 판정 어휘 네 개는 `nara.verdict`의 `BEFORE`·`BUILDING`·`DONE`·`UNKNOWN`을 import해서 쓴다. 문자열로 다시 치지 않는다 — 이관된 152행과 바이트 단위로 같아야 한다
- 웹 계층은 DB를 **읽기 전용**으로만 연다(`open_readonly`). 웹 계층에서 `nara.db.connect`를 쓰지 않는다
- 서버는 `127.0.0.1`에만 묶는다. `debug=False`
- SQL에 들어가는 모든 사용자 값은 `?` 자리표시자로 넘긴다. 정렬 기준은 허용 목록으로만 받는다
- Jinja2 자동 이스케이프를 끄지 않는다. 링크(`href`)에는 `http`·`https` 주소만 넣는다
- 값이 없는 칸은 빈 칸이 아니라 `—`로 보인다
- **조용히 빠지는 것이 없어야 한다.** 무시한 입력, 조건 때문에 빠진 사업, 상한으로 잘린 결과는 결과 머리에 적는다
- 테스트는 망에 나가지 않는다
- Windows 콘솔은 cp949다. 한글이 나오는 명령은 `PYTHONIOENCODING=utf-8`을 붙여 실행한다. 깨진 한글을 보고 판단하지 않는다
- `data/nara.db` 원본에 쓰지 않는다. 실데이터 확인은 사본으로 한다
- 저장소는 공개(public)다. `.env`와 자격 증명을 커밋하지 않는다
- 커밋 메시지는 한국어 `<type>: <설명>`, 본문에 왜 그렇게 했는지 적고 끝에 `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`을 붙인다
- 맡은 작업의 파일 밖은 건드리지 않는다

## Review Focus

스펙이 말하지 않았지만 실제로 들어올 입력 가운데 사람을 물 가능성이 높은 다섯이다. 각 테스트는 해당 작업에 들어 있다.

1. **DB 경로에 공백·`#`이 있다** — 업무 파일이 `ENERGINNO Dropbox` 아래에 있다. 실측: `#`이 든 경로를 URI에 그대로 넣으면 SQLite가 그 뒤를 조각으로 잘라 **엉뚱한 빈 DB를 열고** 오류 대신 "no such table"만 낸다. 기대: 그 파일이 제대로 열린다 → Task 1
2. **근거 URL이 `javascript:`로 시작한다** — 근거는 뉴스·LLM에서 온다. 자동 이스케이프는 href의 스킴을 막지 못한다. 기대: 링크로 나가지 않는다 → Task 4
3. **시작일이 끝일보다 늦다** — 기대: 빈 표만 덩그러니 보이지 않고 이유가 적힌다 → Task 2
4. **수요기관 값이 숫자가 아니거나 너무 크다**(`org=abc`, 20자리) — 기대: 500 오류가 아니라 무시하고 그 사실을 적는다. 20자리 정수는 SQLite 정수 범위를 넘어 바인딩에서 터진다 → Task 2
5. **`evidence_json`이 깨졌다**(잘린 JSON, 리스트, url이 숫자) — 기대: 상세 화면이 죽지 않고 근거만 비운다 → Task 4

## 파일 구조

| 파일 | 책임 |
|---|---|
| `nara/web/__init__.py` | 패키지 표시 |
| `nara/web/query.py` | 조건 해석·직렬화·SQL 생성. DB도 HTTP도 모른다 |
| `nara/web/data.py` | 읽기 전용 열기, 목록·상세·실행 기록·기관 목록 조회 |
| `nara/web/app.py` | Flask 앱. 라우트 둘과 템플릿 필터 |
| `nara/web/templates/base.html` · `list.html` · `detail.html` | 화면 |
| `nara/cli.py` | `serve` 명령 |
| `tests/test_web_query.py` | `query.py` 테스트. DB 없이 |
| `tests/test_web.py` | DB가 필요한 테스트 전부. `data.py`·라우트·`serve` |

스펙의 구조에서 달라진 점이 하나 있다. **`data.py`를 더했다.** 스펙은 `query.py`를 "DB도 HTTP도 모르는 순수 함수"로, `app.py`를 "얇게"로 정했다. 그러면 SQL을 실행할 자리가 둘 중 어디에도 없다. 두 성질을 지키려고 파일을 하나 더 둔다.

`tests/conftest.py`는 만들지 않는다. 이 저장소는 테스트 파일마다 도우미를 두는 관례다.

---

### Task 1: 뼈대·의존성·읽기 전용 열기

이 계획의 첫 작업이다. 스펙은 "Flask가 Python 3.14에서 설치되는지 구현 계획의 첫 작업에서 확인한다"고 정했다. 이 작업은 1단계의 핵심 안전장치(읽기 전용)도 함께 세운다.

**Files:**
- Modify: `pyproject.toml`, `uv.lock` (`uv add flask`가 고친다)
- Create: `nara/web/__init__.py`
- Create: `nara/web/data.py`
- Create: `tests/test_web.py`

**Interfaces:**
- Produces: `nara.web.data.DatabaseMissing(FileNotFoundError)`
- Produces: `nara.web.data.open_readonly(db_path: Path) -> sqlite3.Connection` — `row_factory`는 `sqlite3.Row`

- [ ] **Step 1: Flask를 더하고 3.14에서 설치되는지 확인한다**

```bash
uv add flask
PYTHONIOENCODING=utf-8 uv run python -c "import flask, sys; from importlib.metadata import version; print(version('flask'), sys.version)"
```

Expected: `3.1.x 3.14.x ...` — 계획 작성 때 실측은 `3.1.3 3.14.3`이었다. `flask.__version__`은 쓰지 않는다. Flask 3.2에서 없어진다는 경고가 뜬다

**설치나 import가 실패하면 여기서 멈추고 BLOCKED로 보고한다.** 스펙의 대안(FastAPI + Jinja2)으로 바꿀지는 이 작업이 정하지 않는다.

- [ ] **Step 2: 패키지 파일을 만든다**

`nara/web/__init__.py`:

```python
"""웹 조회 화면. 1단계는 읽기 전용이다."""
```

- [ ] **Step 3: 실패하는 테스트를 쓴다**

`tests/test_web.py`:

```python
"""웹 조회 화면 — DB가 필요한 테스트."""

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from nara.db import connect, migrate
from nara.web.data import DatabaseMissing, open_readonly


def _make_db(path: Path) -> Path:
    conn = connect(path)
    migrate(conn)
    conn.close()
    return path


def test_open_readonly_refuses_writes(tmp_path):
    """1단계는 읽기 전용이다. 화면에 버그가 있어도 자료를 바꿀 수 없어야 한다."""
    with closing(open_readonly(_make_db(tmp_path / "t.db"))) as conn:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            conn.execute("INSERT INTO app_state (key, value) VALUES ('x', 'y')")


def test_open_readonly_does_not_create_a_missing_file(tmp_path):
    """오타 난 경로에 빈 DB를 만들면 '자료 0건'이 정상으로 보인다."""
    missing = tmp_path / "nope.db"
    with pytest.raises(DatabaseMissing):
        open_readonly(missing)
    assert not missing.exists()


def test_open_readonly_opens_a_path_with_space_and_hash(tmp_path):
    """실측: '#'을 URI에 그대로 넣으면 SQLite가 그 뒤를 잘라 엉뚱한 빈 DB를 연다.

    오류가 아니라 'no such table'만 난다. 업무 파일은 공백이 든 폴더
    ('ENERGINNO Dropbox')에 있다.
    """
    folder = tmp_path / "sp ace #dir"
    folder.mkdir()
    with closing(open_readonly(_make_db(folder / "n a#ra.db"))) as conn:
        assert conn.execute("SELECT value FROM app_state").fetchone()[0] == "1"


def test_open_readonly_returns_rows_by_column_name(tmp_path):
    with closing(open_readonly(_make_db(tmp_path / "t.db"))) as conn:
        row = conn.execute("SELECT key FROM app_state").fetchone()
    assert row["key"] == "schema_version"
```

- [ ] **Step 4: 실패를 확인한다**

Run: `PYTHONIOENCODING=utf-8 uv run pytest tests/test_web.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'nara.web.data'`

- [ ] **Step 5: 최소 구현**

`nara/web/data.py`:

```python
"""웹 조회 화면이 읽는 자료. DB는 읽기 전용으로만 연다."""

import sqlite3
from pathlib import Path
from urllib.parse import quote


class DatabaseMissing(FileNotFoundError):
    """DB 파일이 없다. 빈 DB를 새로 만들지 않고 멈춘다."""


def open_readonly(db_path: Path) -> sqlite3.Connection:
    """읽기 전용 연결을 연다.

    `nara.db.connect`를 쓰지 않는다. 그 함수는 폴더를 만들고 일반 모드로 열어
    없는 파일을 새로 만든다 — 오타 난 경로가 '자료 0건'으로 조용히 보인다.

    경로는 URL 인코딩한다. '#'이 든 경로를 URI에 그대로 넣으면 SQLite가 그
    뒤를 조각으로 잘라 엉뚱한 DB를 열고, 오류 대신 'no such table'만 낸다.
    """
    if not db_path.exists():
        raise DatabaseMissing(f"DB 파일이 없다: {db_path}")
    uri = f"file:{quote(db_path.resolve().as_posix(), safe='/:')}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn
```

- [ ] **Step 6: 통과를 확인한다**

Run: `PYTHONIOENCODING=utf-8 uv run pytest tests/test_web.py -v`
Expected: PASS (4개)

- [ ] **Step 7: 전체 검사**

```bash
uv run ruff check --fix .
uv run ruff format .
PYTHONIOENCODING=utf-8 uv run pytest -q
uv run ruff check .
uv run ruff format --check .
```

Expected: 전부 통과

- [ ] **Step 8: 커밋**

```bash
git add pyproject.toml uv.lock nara/web/__init__.py nara/web/data.py tests/test_web.py
git commit -m "feat: 웹 조회 화면 뼈대 — DB를 읽기 전용으로만 연다

1단계는 조회 전용이다. 화면에 버그가 있어도 자료를 바꿀 수 없게
mode=ro로 연다. nara.db.connect를 쓰지 않는 이유는 그 함수가 없는
파일을 새로 만들기 때문이다 — 오타 난 경로가 '자료 0건'으로 보인다.

경로는 URL 인코딩한다. 실측으로 '#'이 든 경로를 URI에 그대로 넣으면
SQLite가 그 뒤를 조각으로 잘라 엉뚱한 빈 DB를 열고, 오류 대신
'no such table'만 냈다. 업무 파일은 공백이 든 폴더에 있다.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: 조회 조건 해석과 되돌리기

URL 인자는 사용자 입력이다. 이 작업이 그것을 검증된 조건(`Filters`)으로 바꾸는 경계다. 못 쓰는 값은 버리되 **무엇을 왜 버렸는지 `notes`로 돌려준다** — 스펙은 오류 화면을 띄우지 말라고 했고, 이 도구는 조용히 빠뜨리지 말라고 한다.

**Files:**
- Create: `nara/web/query.py`
- Create: `tests/test_web_query.py`

**Interfaces:**
- Consumes: `nara.verdict`의 `BEFORE`, `BUILDING`, `DONE`, `UNKNOWN`
- Produces:
  - `SORT_KEYS: tuple[str, ...] = ("org", "name", "notice_date", "open_date", "verdict")`
  - `DEFAULT_SORT = "notice_date"`
  - `NO_VERDICT = "판정 전"`
  - `VERDICT_CHOICES = (BEFORE, BUILDING, DONE, UNKNOWN, NO_VERDICT)`
  - `@dataclass(frozen=True) class Filters` — 필드 `orgs: tuple[int, ...]`, `focus_only: bool`, `q: str`, `date_from: str`, `date_to: str`, `verdicts: tuple[str, ...]`, `sort: str`, `desc: bool`, 속성 `has_date: bool`
  - `parse_filters(args: Mapping[str, list[str]]) -> tuple[Filters, list[str]]`
  - `to_args(f: Filters) -> dict[str, list[str]]` — `parse_filters`와 짝

`args`는 `{"org": ["3", "7"], "q": ["체육관"]}` 꼴이다. Flask의 `request.args`를 이 꼴로 바꾸는 일은 Task 6이 한다. 이 파일은 Flask를 모른다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_web_query.py`:

```python
"""웹 조회 조건 — DB 없이 확인한다."""

from nara.verdict import BEFORE, BUILDING, UNKNOWN
from nara.web.query import DEFAULT_SORT, NO_VERDICT, Filters, parse_filters, to_args


def test_parse_filters_defaults_to_newest_notice_first():
    f, notes = parse_filters({})
    assert f == Filters()
    assert (f.sort, f.desc) == ("notice_date", True)
    assert notes == []


def test_parse_filters_keeps_several_orgs_once_each():
    f, _ = parse_filters({"org": ["3", "7", "3"]})
    assert f.orgs == (3, 7)


def test_parse_filters_ignores_an_unusable_org_and_says_so():
    """'abc'는 숫자가 아니고, '²'는 isdigit()이 참인데 int()가 실패하고,
    20자리는 SQLite 정수 범위를 넘어 바인딩에서 터진다. 셋 다 500이 아니라 안내다.
    """
    f, notes = parse_filters({"org": ["3", "abc", "²", "99999999999999999999"]})
    assert f.orgs == (3,)
    assert len(notes) == 3
    assert all("수요기관" in n for n in notes)


def test_parse_filters_treats_a_blank_search_as_no_search():
    """공백 한 칸 때문에 모든 행이 걸러지면 안 된다."""
    assert parse_filters({"q": ["   "]})[0].q == ""
    assert parse_filters({"q": ["  체육관 "]})[0].q == "체육관"


def test_parse_filters_keeps_valid_dates():
    f, notes = parse_filters({"from": ["2026-01-01"], "to": ["2026-06-30"]})
    assert (f.date_from, f.date_to) == ("2026-01-01", "2026-06-30")
    assert notes == []


def test_parse_filters_ignores_a_malformed_date_and_says_so():
    """'20260101'은 date.fromisoformat이 받아들이지만 DB는 'YYYY-MM-DD' 문자열로
    비교한다. 다른 꼴이 들어오면 비교가 조용히 어긋난다.
    """
    for bad in ("어제", "2026-02-30", "20260101", "2026-1-1"):
        f, notes = parse_filters({"from": [bad]})
        assert f.date_from == "", bad
        assert notes == ["시작일 형식이 맞지 않아 무시했습니다"], bad


def test_parse_filters_explains_a_reversed_range():
    """시작일이 끝일보다 늦으면 결과가 비는 이유를 적는다. 날짜를 몰래 바꾸지 않는다."""
    f, notes = parse_filters({"from": ["2026-06-30"], "to": ["2026-01-01"]})
    assert (f.date_from, f.date_to) == ("2026-06-30", "2026-01-01")
    assert notes == ["시작일이 끝일보다 늦어 걸리는 사업이 없습니다"]


def test_parse_filters_keeps_known_verdicts_and_no_verdict():
    f, notes = parse_filters({"verdict": [BEFORE, NO_VERDICT, BEFORE]})
    assert f.verdicts == (BEFORE, NO_VERDICT)
    assert notes == []


def test_parse_filters_ignores_an_unknown_verdict_and_says_so():
    f, notes = parse_filters({"verdict": ["착공전"]})  # 괄호가 빠진 오타
    assert f.verdicts == ()
    assert len(notes) == 1


def test_parse_filters_falls_back_on_an_unknown_sort_and_says_so():
    """사용자 입력을 ORDER BY에 그대로 붙이면 주입 구멍이 된다."""
    f, notes = parse_filters({"sort": ["name; DROP TABLE project"]})
    assert f.sort == DEFAULT_SORT
    assert len(notes) == 1


def test_parse_filters_reads_the_direction():
    assert parse_filters({"desc": ["0"]})[0].desc is False
    assert parse_filters({"desc": ["1"]})[0].desc is True


def test_to_args_round_trips_through_parse_filters():
    """URL이 곧 상태다. 열 머리를 눌러 정렬을 바꿔도 걸어 둔 조건이 남아야 한다."""
    cases = [
        Filters(),
        Filters(
            orgs=(3, 7),
            focus_only=True,
            q="체육관",
            date_from="2026-01-01",
            date_to="2026-06-30",
            verdicts=(BUILDING, NO_VERDICT),
            sort="verdict",
            desc=False,
        ),
        Filters(q="100%", verdicts=(UNKNOWN,)),
    ]
    for f in cases:
        assert parse_filters(to_args(f)) == (f, [])
```

- [ ] **Step 2: 실패를 확인한다**

Run: `PYTHONIOENCODING=utf-8 uv run pytest tests/test_web_query.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'nara.web.query'`

- [ ] **Step 3: 최소 구현**

`nara/web/query.py`:

```python
"""조회 조건을 해석하고 SQL로 바꾼다. DB도 HTTP도 모른다."""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date

from nara.verdict import BEFORE, BUILDING, DONE, UNKNOWN

SORT_KEYS = ("org", "name", "notice_date", "open_date", "verdict")
DEFAULT_SORT = "notice_date"
NO_VERDICT = "판정 전"
VERDICT_CHOICES = (BEFORE, BUILDING, DONE, UNKNOWN, NO_VERDICT)

_ISO_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
# 18자리까지만 받는다. 그보다 크면 SQLite 정수 범위(2^63-1)를 넘어 바인딩에서 터진다.
_ORG_ID = re.compile(r"[0-9]{1,18}")


@dataclass(frozen=True)
class Filters:
    orgs: tuple[int, ...] = ()
    focus_only: bool = False
    q: str = ""
    date_from: str = ""
    date_to: str = ""
    verdicts: tuple[str, ...] = ()
    sort: str = DEFAULT_SORT
    desc: bool = True

    @property
    def has_date(self) -> bool:
        return bool(self.date_from or self.date_to)


def _first(args: Mapping[str, list[str]], key: str) -> str:
    values = args.get(key) or []
    return values[0] if values else ""


def _iso_date(raw: str) -> str | None:
    """'YYYY-MM-DD'이고 실제로 있는 날짜면 그대로, 아니면 None.

    date.fromisoformat만 쓰면 '20260101'도 받아들인다. DB는 'YYYY-MM-DD'
    문자열로 비교하므로 다른 꼴이 들어오면 비교가 조용히 어긋난다.
    """
    if not _ISO_DATE.fullmatch(raw):
        return None
    try:
        date.fromisoformat(raw)
    except ValueError:
        return None
    return raw


def _parse_orgs(raw_values: list[str], notes: list[str]) -> tuple[int, ...]:
    orgs: list[int] = []
    for raw in raw_values:
        # isdigit()은 '²'에도 참이다. 그 뒤의 int()가 터진다. ASCII 숫자만 받는다.
        if not _ORG_ID.fullmatch(raw):
            notes.append(f"수요기관 값 '{raw}'은 쓸 수 없어 무시했습니다")
        elif int(raw) not in orgs:
            orgs.append(int(raw))
    return tuple(orgs)


def _parse_dates(args: Mapping[str, list[str]], notes: list[str]) -> tuple[str, str]:
    found = {"from": "", "to": ""}
    for key, label in (("from", "시작일"), ("to", "끝일")):
        raw = _first(args, key).strip()
        if not raw:
            continue
        value = _iso_date(raw)
        if value is None:
            notes.append(f"{label} 형식이 맞지 않아 무시했습니다")
        else:
            found[key] = value
    if found["from"] and found["to"] and found["from"] > found["to"]:
        notes.append("시작일이 끝일보다 늦어 걸리는 사업이 없습니다")
    return found["from"], found["to"]


def _parse_verdicts(raw_values: list[str], notes: list[str]) -> tuple[str, ...]:
    verdicts: list[str] = []
    for raw in raw_values:
        if raw not in VERDICT_CHOICES:
            notes.append(f"진행현황 값 '{raw}'은 알 수 없어 무시했습니다")
        elif raw not in verdicts:
            verdicts.append(raw)
    return tuple(verdicts)


def _parse_sort(raw: str, notes: list[str]) -> str:
    if not raw:
        return DEFAULT_SORT
    if raw not in SORT_KEYS:
        notes.append(f"정렬 기준 '{raw}'은 쓸 수 없어 공고일로 바꿨습니다")
        return DEFAULT_SORT
    return raw


def parse_filters(args: Mapping[str, list[str]]) -> tuple[Filters, list[str]]:
    """URL 인자를 조회 조건으로 바꾼다.

    못 쓰는 값은 버리고 그 사실을 notes에 적는다. 오류 화면을 띄우지 않지만
    조용히 버리지도 않는다 — 무엇을 왜 무시했는지 결과 머리에 나온다.
    """
    notes: list[str] = []
    orgs = _parse_orgs(args.get("org") or [], notes)
    date_from, date_to = _parse_dates(args, notes)
    verdicts = _parse_verdicts(args.get("verdict") or [], notes)
    sort = _parse_sort(_first(args, "sort"), notes)
    filters = Filters(
        orgs=orgs,
        focus_only=_first(args, "focus") == "1",
        q=_first(args, "q").strip(),
        date_from=date_from,
        date_to=date_to,
        verdicts=verdicts,
        sort=sort,
        desc=_first(args, "desc") != "0",
    )
    return filters, notes


def to_args(f: Filters) -> dict[str, list[str]]:
    """조회 조건을 URL 인자로 되돌린다. parse_filters와 짝이다.

    열 머리를 눌러 정렬만 바꿔도 걸어 둔 조건이 그대로 남아야 한다.
    """
    args: dict[str, list[str]] = {}
    if f.orgs:
        args["org"] = [str(i) for i in f.orgs]
    if f.focus_only:
        args["focus"] = ["1"]
    if f.q:
        args["q"] = [f.q]
    if f.date_from:
        args["from"] = [f.date_from]
    if f.date_to:
        args["to"] = [f.date_to]
    if f.verdicts:
        args["verdict"] = list(f.verdicts)
    args["sort"] = [f.sort]
    args["desc"] = ["1" if f.desc else "0"]
    return args
```

- [ ] **Step 4: 통과를 확인한다**

Run: `PYTHONIOENCODING=utf-8 uv run pytest tests/test_web_query.py -v`
Expected: PASS (12개)

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
git add nara/web/query.py tests/test_web_query.py
git commit -m "feat: 조회 조건 해석 — 못 쓰는 값은 버리고 버린 사실을 적는다

URL 인자는 사용자 입력이다. 이 파일이 그것을 검증된 조건으로 바꾸는
경계다. 스펙은 오류 화면을 띄우지 말라고 했고, 이 도구는 조용히
빠뜨리지 말라고 한다. 그래서 버린 값은 notes로 돌려준다.

정렬 기준은 허용 목록으로만 받는다. 날짜는 'YYYY-MM-DD'만 받는다 —
DB가 문자열로 비교하므로 '20260101'이 들어오면 조용히 어긋난다.
수요기관 값은 ASCII 숫자 18자리까지만 받는다. '²'는 isdigit()이
참인데 int()가 실패하고, 20자리는 SQLite 정수 범위를 넘는다.

to_args는 parse_filters와 짝이다. 열 머리를 눌러도 조건이 남는다.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---
### Task 3: 목록 조회

행은 사업 하나다. 사업마다 가장 최근 공고·판정·실행부서를 하나씩 붙인다. SQL은 `query.py`가 만들고(순수 함수), `data.py`가 실행한다. **SQL 문자열 자체를 단언하는 테스트는 쓰지 않는다** — 구현을 바꾸면 깨지고 동작은 확인하지 못한다. 대신 순수 쪽은 "사용자 값이 SQL 문장에 들어가지 않는다"와 "자리표시자와 인자 수가 맞는다"를, DB 쪽은 "어떤 행이 어떤 순서로 걸리는가"를 확인한다.

**Files:**
- Modify: `nara/web/query.py` (SQL 생성 추가)
- Modify: `nara/web/data.py` (`list_projects` 추가)
- Modify: `tests/test_web_query.py`, `tests/test_web.py`

**Interfaces:**
- Consumes: Task 2의 `Filters`, `NO_VERDICT`, `DEFAULT_SORT`
- Produces (`query.py`):
  - `LIST_LIMIT = 1000`
  - `like_pattern(text: str) -> str`
  - `build_list_query(f: Filters) -> tuple[str, list]` — 행 열: `id, org_name, name, notice_title, notice_date, open_date, verdict, winner, exec_dept, zeb_grade, matched_title`
  - `build_count_query(f: Filters) -> tuple[str, list]`
  - `build_excluded_query(f: Filters) -> tuple[str, list] | None` — 기간 조건이 없으면 `None`
- Produces (`data.py`):
  - `@dataclass(frozen=True) class ListResult` — `rows: list[sqlite3.Row]`, `total: int`, `matched: int`, `excluded_no_notice: int | None`, `truncated: bool`
  - `list_projects(conn: sqlite3.Connection, f: Filters) -> ListResult`

**한 가지 해석:** 스펙은 실행부서를 "그 사업의 `dept_check` 중 가장 최근 것의 `exec_dept`"라고 했다. 가장 최근 조회에서 부서를 못 찾아 빈 값이 들어왔을 때 앞서 찾은 부서를 지우면 안 되므로, **부서 이름이 있는 줄 가운데 가장 최근 것**으로 읽는다. 테스트로 박는다.

- [ ] **Step 1: 순수 쪽 실패하는 테스트를 쓴다**

`tests/test_web_query.py`의 import 줄을 넓힌다(ruff I001 — import는 파일 머리에 한 묶음으로):

```python
from nara.verdict import BEFORE, BUILDING, UNKNOWN
from nara.web.query import (
    DEFAULT_SORT,
    NO_VERDICT,
    Filters,
    build_count_query,
    build_excluded_query,
    build_list_query,
    like_pattern,
    parse_filters,
    to_args,
)
```

파일 끝에 더한다:

```python
def test_like_pattern_takes_percent_and_underscore_literally():
    """'100%'를 찾을 때 %가 와일드카드면 모든 행이 걸린다."""
    assert like_pattern("100%") == "%100\\%%"
    assert like_pattern("a_b") == "%a\\_b%"
    assert like_pattern("c\\d") == "%c\\\\d%"


def test_user_input_never_enters_the_sql_text():
    """검색어는 전부 자리표시자로 넘어간다. 문장에 이어 붙이면 주입 구멍이다."""
    evil = "'; DROP TABLE project; --"
    f = Filters(q=evil, date_from="2026-01-01", verdicts=(BEFORE,))
    for sql, params in (build_list_query(f), build_count_query(f), build_excluded_query(f)):
        assert "DROP" not in sql
        assert any(evil in str(p) for p in params)


def test_sort_falls_back_even_when_filters_bypass_parsing():
    """SQL을 만드는 쪽도 정렬 값을 믿지 않는다. Filters는 parse_filters 없이도 만들 수 있다."""
    sql, _ = build_list_query(Filters(sort="name; DROP TABLE project"))
    assert "DROP" not in sql


def test_placeholders_and_params_line_up():
    """'?' 개수와 인자 수가 어긋나면 값이 엉뚱한 자리에 묶인다 — 오류 없이."""
    combos = [
        Filters(),
        Filters(q="체육", sort="verdict"),
        Filters(
            orgs=(1, 2),
            focus_only=True,
            q="관",
            date_from="2026-01-01",
            date_to="2026-12-31",
            verdicts=(BEFORE, NO_VERDICT),
            sort="verdict",
            desc=False,
        ),
        Filters(verdicts=(NO_VERDICT,)),
    ]
    for f in combos:
        for built in (build_list_query(f), build_count_query(f), build_excluded_query(f)):
            if built is None:
                continue
            sql, params = built
            assert sql.count("?") == len(params), f


def test_excluded_query_exists_only_with_a_date_condition():
    assert build_excluded_query(Filters(q="관")) is None
    assert build_excluded_query(Filters(date_from="2026-01-01")) is not None
```

- [ ] **Step 2: 실패를 확인한다**

Run: `PYTHONIOENCODING=utf-8 uv run pytest tests/test_web_query.py -v`
Expected: FAIL — `ImportError: cannot import name 'build_count_query'`

- [ ] **Step 3: SQL 생성을 구현한다**

`nara/web/query.py` 끝에 더한다:

```python
LIST_LIMIT = 1000

# 사업마다 가장 최근 공고·판정·실행부서를 하나씩 고른다. 판정 순서는
# 파이프라인 전체가 쓰는 규칙(checked_at 내림차순, 같으면 id)과 같다.
# 실행부서는 이름이 있는 줄만 본다 — 최근 조회가 빈 값이어도 앞서 찾은 부서를
# 지우지 않는다.
_LATEST = """
WITH ln AS (
    SELECT n.project_id, n.bid_no, n.title, n.notice_date, n.open_date,
           ROW_NUMBER() OVER (
               PARTITION BY n.project_id
               ORDER BY COALESCE(n.notice_date, '') DESC, n.bid_no DESC
           ) AS rn
    FROM notice n
    WHERE n.project_id IS NOT NULL
),
ls AS (
    SELECT s.project_id, s.verdict,
           ROW_NUMBER() OVER (
               PARTITION BY s.project_id ORDER BY s.checked_at DESC, s.id DESC
           ) AS rn
    FROM status_check s
),
ld AS (
    SELECT d.project_id, d.exec_dept,
           ROW_NUMBER() OVER (
               PARTITION BY d.project_id ORDER BY d.checked_at DESC, d.id DESC
           ) AS rn
    FROM dept_check d
    WHERE d.project_id IS NOT NULL AND COALESCE(d.exec_dept, '') != ''
)
"""

_FROM = """
FROM project p
JOIN org o ON o.id = p.org_id
LEFT JOIN ln ON ln.project_id = p.id AND ln.rn = 1
LEFT JOIN ls ON ls.project_id = p.id AND ls.rn = 1
LEFT JOIN ld ON ld.project_id = p.id AND ld.rn = 1
LEFT JOIN award a ON a.bid_no = ln.bid_no
"""

_ORDER_EXPR = {
    "org": "o.name",
    "name": "p.name",
    "notice_date": "NULLIF(ln.notice_date, '')",
    "open_date": "NULLIF(ln.open_date, '')",
    # 가나다순이면 '미확인·시공 중·준공 완료·착공 전'이 된다. 단계순으로 매긴다.
    "verdict": "CASE ls.verdict WHEN ? THEN 1 WHEN ? THEN 2 WHEN ? THEN 3 WHEN ? THEN 4 END",
}
_STAGE_ORDER = (BEFORE, BUILDING, DONE, UNKNOWN)
_ESCAPE = "ESCAPE '\\'"


def like_pattern(text: str) -> str:
    """LIKE용 '%…%'. 사용자가 친 %·_·\\는 글자 그대로 찾는다.

    '100%'를 찾을 때 %가 와일드카드면 모든 행이 걸린다.
    """
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _where(f: Filters, include_dates: bool) -> tuple[str, list]:
    clauses: list[str] = []
    params: list = []
    if f.orgs:
        clauses.append(f"p.org_id IN ({', '.join('?' * len(f.orgs))})")
        params.extend(f.orgs)
    if f.focus_only:
        clauses.append("o.tier = 'focus'")
    if f.q:
        # 공고명만 찾으면 시트에서 이관한 사업(공고 없음)은 이름으로 영영 못 찾는다.
        clauses.append(f"(p.name LIKE ? {_ESCAPE} OR ln.title LIKE ? {_ESCAPE})")
        params.extend([like_pattern(f.q)] * 2)
    # 기간은 행에 보이는 그 공고의 공고일로 거른다. 공고 없는 사업은 여기서 빠진다.
    if include_dates and f.date_from:
        clauses.append("ln.notice_date >= ?")
        params.append(f.date_from)
    if include_dates and f.date_to:
        clauses.append("ln.notice_date <= ?")
        params.append(f.date_to)
    if f.verdicts:
        known = [v for v in f.verdicts if v != NO_VERDICT]
        parts: list[str] = []
        if known:
            parts.append(f"ls.verdict IN ({', '.join('?' * len(known))})")
            params.extend(known)
        if NO_VERDICT in f.verdicts:
            parts.append("ls.verdict IS NULL")
        clauses.append(f"({' OR '.join(parts)})")
    return (" WHERE " + " AND ".join(clauses)) if clauses else "", params


def _order(f: Filters) -> tuple[str, list]:
    # 정렬 값을 여기서도 믿지 않는다. Filters는 parse_filters 없이도 만들 수 있다.
    key = f.sort if f.sort in _ORDER_EXPR else DEFAULT_SORT
    expr = _ORDER_EXPR[key]
    direction = "DESC" if f.desc else "ASC"
    # 값이 없는 행은 방향과 관계없이 맨 뒤. 같으면 id로 순서를 고정한다 —
    # 새로고침할 때마다 순서가 바뀌면 안 된다. expr이 두 번 나오므로 인자도 두 벌이다.
    sql = f" ORDER BY ({expr}) IS NULL, {expr} {direction}, p.id"
    params = list(_STAGE_ORDER) * 2 if key == "verdict" else []
    return sql, params


def build_list_query(f: Filters) -> tuple[str, list]:
    """목록 SQL과 인자. 자리표시자의 순서와 인자의 순서가 같아야 한다."""
    matched_sql, matched_params = "NULL", []
    if f.q:
        # 목록엔 사업명만 보인다. 공고명으로만 걸린 행은 그 공고명을 함께 돌려준다.
        matched_sql = (
            f"CASE WHEN p.name NOT LIKE ? {_ESCAPE} AND ln.title LIKE ? {_ESCAPE} THEN ln.title END"
        )
        matched_params = [like_pattern(f.q)] * 2
    where_sql, where_params = _where(f, include_dates=True)
    order_sql, order_params = _order(f)
    sql = (
        _LATEST
        + "SELECT p.id, o.name AS org_name, p.name, ln.title AS notice_title, "
        + "ln.notice_date, ln.open_date, ls.verdict, a.winner, ld.exec_dept, p.zeb_grade, "
        + f"{matched_sql} AS matched_title"
        + _FROM
        + where_sql
        + order_sql
        + " LIMIT ?"
    )
    return sql, [*matched_params, *where_params, *order_params, LIST_LIMIT]


def build_count_query(f: Filters) -> tuple[str, list]:
    where_sql, params = _where(f, include_dates=True)
    return _LATEST + "SELECT COUNT(*)" + _FROM + where_sql, params


def build_excluded_query(f: Filters) -> tuple[str, list] | None:
    """기간 조건 때문에 빠진 '공고 없는 사업' 수. 기간 조건이 없으면 None.

    고정값 95가 아니다. 그때의 다른 조건에 걸리는 공고 없는 사업만 센다.
    """
    if not f.has_date:
        return None
    where_sql, params = _where(f, include_dates=False)
    joiner = " AND " if where_sql else " WHERE "
    sql = _LATEST + "SELECT COUNT(*)" + _FROM + where_sql + joiner + "ln.bid_no IS NULL"
    return sql, params
```

- [ ] **Step 4: 순수 쪽 통과를 확인한다**

Run: `PYTHONIOENCODING=utf-8 uv run pytest tests/test_web_query.py -v`
Expected: PASS (17개)

- [ ] **Step 5: DB 쪽 실패하는 테스트를 쓴다**

`tests/test_web.py`의 import 묶음을 이렇게 넓힌다:

```python
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from nara.config import load_settings
from nara.db import connect, migrate
from nara.store import ensure_project, upsert_org
from nara.verdict import BEFORE, BUILDING, DONE, UNKNOWN
from nara.web.data import DatabaseMissing, list_projects, open_readonly
from nara.web.query import NO_VERDICT, Filters
```

`_make_db` 바로 아래에 도우미와 픽스처를 더한다:

```python
SETTINGS = load_settings(Path(__file__).resolve().parents[1] / "config.toml")
NOW = "2026-09-27T09:00:00"


def _org(conn, name, tier):
    org_id = upsert_org(conn, name, SETTINGS, NOW)
    # 설정 파일의 관심기관 목록과 무관하게 테스트가 tier를 정한다.
    conn.execute("UPDATE org SET tier = ? WHERE id = ?", (tier, org_id))
    return org_id


def _project(conn, org_id, name, source="g2b"):
    return ensure_project(conn, org_id, name, source, NOW)


def _notice(conn, project_id, org_id, bid_no, title, notice_date):
    conn.execute(
        "INSERT INTO notice (bid_no, project_id, org_id, org_name, title, notice_date, "
        "open_date, collected_at) VALUES (?, ?, ?, (SELECT name FROM org WHERE id = ?), "
        "?, ?, ?, ?)",
        (bid_no, project_id, org_id, org_id, title, notice_date, notice_date, NOW),
    )


def _award(conn, bid_no, winner, award_date):
    conn.execute(
        "INSERT INTO award (bid_no, winner, award_date, checked_at) VALUES (?, ?, ?, ?)",
        (bid_no, winner, award_date, NOW),
    )


def _verdict(
    conn,
    project_id,
    verdict,
    when="2026-09-20T09:00:00",
    decided_by="rule",
    reason="",
    evidence_json=None,
):
    conn.execute(
        "INSERT INTO status_check (project_id, verdict, reason, decided_by, evidence_json, "
        "checked_at) VALUES (?, ?, ?, ?, ?, ?)",
        (project_id, verdict, reason, decided_by, evidence_json, when),
    )


@pytest.fixture
def world(tmp_path):
    """실제 모양을 줄인 DB. 공고 있는 사업·재공고·시트 이관(공고 없음)·판정 전을 다 담는다."""
    path = tmp_path / "w.db"
    conn = connect(path)
    migrate(conn)
    wanju = _org(conn, "전북특별자치도 완주군", "focus")
    seongnam = _org(conn, "경기도 성남시", "rest")
    ids = {}

    ids["gym"] = _project(conn, wanju, "완주군 다목적체육관")
    _notice(conn, ids["gym"], wanju, "N1", "완주군 다목적체육관 건립 설계용역", "2026-03-10")
    _verdict(conn, ids["gym"], BEFORE)

    ids["welfare"] = _project(conn, wanju, "완주군 종합사회복지관")
    _notice(conn, ids["welfare"], wanju, "N2A", "완주군 종합사회복지관 설계용역", "2026-01-05")
    _notice(
        conn, ids["welfare"], wanju, "N2B", "완주군 종합사회복지관 설계용역(재공고)", "2026-02-20"
    )
    _award(conn, "N2B", "가건축", "2026-03-01")
    _verdict(conn, ids["welfare"], BUILDING)

    ids["museum"] = _project(conn, seongnam, "성남시 박물관")
    _notice(
        conn,
        ids["museum"],
        seongnam,
        "N3",
        "성남시 박물관 건립공사 설계의도구현 용역",
        "2025-11-01",
    )
    _verdict(conn, ids["museum"], DONE)

    ids["sheet_unknown"] = _project(conn, wanju, "완주 풍류체험관", source="manual")
    _verdict(conn, ids["sheet_unknown"], UNKNOWN, decided_by="imported")

    ids["sheet_new"] = _project(conn, seongnam, "여수동 100% 친환경 센터", source="manual")

    ids["culture"] = _project(conn, seongnam, "성남시 문화복합시설")
    _notice(conn, ids["culture"], seongnam, "N6", "성남시 체육관 리모델링", "2026-04-01")

    conn.commit()
    conn.close()
    return path, ids


def _list(path, **kw):
    with closing(open_readonly(path)) as conn:
        return list_projects(conn, Filters(**kw))


def _names(result):
    return [row["name"] for row in result.rows]
```

파일 끝에 테스트를 더한다:

```python
def test_list_puts_the_newest_notice_first_and_sheet_projects_last(world):
    """기본은 공고일 내림차순. 공고 없는 사업은 방향과 관계없이 맨 뒤, 그 안에서는 id순."""
    result = _list(world[0])
    assert _names(result) == [
        "성남시 문화복합시설",
        "완주군 다목적체육관",
        "완주군 종합사회복지관",
        "성남시 박물관",
        "완주 풍류체험관",
        "여수동 100% 친환경 센터",
    ]
    assert (result.total, result.matched, result.excluded_no_notice) == (6, 6, None)
    assert result.truncated is False


def test_list_shows_a_renoticed_project_once_with_its_latest_notice(world):
    """유찰 재공고가 있어도 목록엔 한 줄. 붙는 공고·낙찰업체는 최신 공고의 것이다."""
    path, ids = world
    rows = [r for r in _list(path).rows if r["id"] == ids["welfare"]]
    assert len(rows) == 1
    assert rows[0]["notice_date"] == "2026-02-20"
    assert rows[0]["notice_title"] == "완주군 종합사회복지관 설계용역(재공고)"
    assert rows[0]["winner"] == "가건축"


def test_date_filter_drops_projects_without_a_notice_and_counts_them(world):
    """시트에서 이관한 사업은 공고일이 없어 기간 조건에서 빠진다. 빠진 수를 알려야 한다."""
    result = _list(world[0], date_from="2026-01-01")
    assert _names(result) == ["성남시 문화복합시설", "완주군 다목적체육관", "완주군 종합사회복지관"]
    assert result.excluded_no_notice == 2


def test_excluded_count_follows_the_other_conditions(world):
    """고정값이 아니다. 다른 조건에 걸리는 공고 없는 사업만 센다."""
    path, _ = world
    with closing(open_readonly(path)) as conn:
        seongnam = conn.execute("SELECT id FROM org WHERE name = '경기도 성남시'").fetchone()[0]
    result = _list(path, date_from="2026-01-01", orgs=(seongnam,))
    assert _names(result) == ["성남시 문화복합시설"]
    assert result.excluded_no_notice == 1


def test_date_filter_uses_the_notice_that_is_shown(world):
    """보이는 공고와 거른 공고가 다르면 '1월 조건인데 왜 2월 공고가 보이지'가 된다.

    종합사회복지관의 옛 공고(1월 5일)는 기간 안이지만 보이는 공고는 2월 20일이다.
    """
    assert _names(_list(world[0], date_to="2026-01-31")) == ["성남시 박물관"]


def test_search_finds_project_name_and_notice_title(world):
    """공고명으로만 걸린 행은 그 공고명을 함께 돌려준다 — 목록엔 사업명만 보인다."""
    path, ids = world
    rows = {r["id"]: r for r in _list(path, q="체육").rows}
    assert set(rows) == {ids["gym"], ids["culture"]}
    assert rows[ids["gym"]]["matched_title"] is None
    assert rows[ids["culture"]]["matched_title"] == "성남시 체육관 리모델링"


def test_search_finds_a_sheet_project_by_its_name(world):
    """공고명만 찾으면 시트에서 이관한 95건은 이름으로 영영 못 찾는다."""
    assert _names(_list(world[0], q="풍류")) == ["완주 풍류체험관"]


def test_search_takes_percent_literally(world):
    assert _names(_list(world[0], q="100%")) == ["여수동 100% 친환경 센터"]
    assert _names(_list(world[0], q="%")) == ["여수동 100% 친환경 센터"]


def test_verdict_filter_includes_projects_not_yet_judged(world):
    path, _ = world
    assert _names(_list(path, verdicts=(BEFORE,))) == ["완주군 다목적체육관"]
    assert _names(_list(path, verdicts=(NO_VERDICT,))) == [
        "성남시 문화복합시설",
        "여수동 100% 친환경 센터",
    ]
    assert _names(_list(path, verdicts=(BUILDING, NO_VERDICT))) == [
        "성남시 문화복합시설",
        "완주군 종합사회복지관",
        "여수동 100% 친환경 센터",
    ]


def test_verdict_sort_follows_the_stages_and_keeps_unjudged_last(world):
    """가나다순이면 '미확인·시공 중·준공 완료·착공 전'이 된다.

    '판정 전'을 단계에 넣으면 내림차순에서 맨 앞으로 올라와 판정된 사업을 가린다.
    """
    path, _ = world
    assert _names(_list(path, sort="verdict", desc=False)) == [
        "완주군 다목적체육관",
        "완주군 종합사회복지관",
        "성남시 박물관",
        "완주 풍류체험관",
        "여수동 100% 친환경 센터",
        "성남시 문화복합시설",
    ]
    assert _names(_list(path, sort="verdict", desc=True)) == [
        "완주 풍류체험관",
        "성남시 박물관",
        "완주군 종합사회복지관",
        "완주군 다목적체육관",
        "여수동 100% 친환경 센터",
        "성남시 문화복합시설",
    ]


def test_focus_only_keeps_focus_orgs(world):
    assert _names(_list(world[0], focus_only=True)) == [
        "완주군 다목적체육관",
        "완주군 종합사회복지관",
        "완주 풍류체험관",
    ]


def test_list_reports_truncation_instead_of_dropping_rows_silently(world, monkeypatch):
    monkeypatch.setattr("nara.web.query.LIST_LIMIT", 2)
    result = _list(world[0])
    assert len(result.rows) == 2
    assert result.matched == 6
    assert result.truncated is True


def test_list_keeps_the_last_department_that_had_a_name(world):
    """가장 최근 조회에서 부서를 못 찾았다고 앞서 찾은 부서를 지우지 않는다."""
    path, ids = world
    conn = connect(path)
    for when, dept in (("2026-09-01T00:00:00", "체육진흥과"), ("2026-09-10T00:00:00", "")):
        conn.execute(
            "INSERT INTO dept_check (project_id, exec_dept, decided_by, checked_at) "
            "VALUES (?, ?, 'imported', ?)",
            (ids["gym"], dept, when),
        )
    conn.commit()
    conn.close()
    row = next(r for r in _list(path).rows if r["id"] == ids["gym"])
    assert row["exec_dept"] == "체육진흥과"
```

- [ ] **Step 6: 실패를 확인한다**

Run: `PYTHONIOENCODING=utf-8 uv run pytest tests/test_web.py -v`
Expected: FAIL — `ImportError: cannot import name 'list_projects'`

- [ ] **Step 7: 실행 쪽을 구현한다**

`nara/web/data.py`의 import 묶음을 넓힌다:

```python
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from nara.web.query import (
    Filters,
    build_count_query,
    build_excluded_query,
    build_list_query,
)
```

파일 끝에 더한다:

```python
@dataclass(frozen=True)
class ListResult:
    rows: list[sqlite3.Row]
    total: int
    matched: int
    excluded_no_notice: int | None
    truncated: bool


def list_projects(conn: sqlite3.Connection, f: Filters) -> ListResult:
    """조건에 걸리는 사업을 고른다. 행은 사업 하나, 공고는 가장 최근 것 하나다.

    matched는 상한과 관계없는 진짜 건수다. rows가 그보다 적으면 잘린 것이고,
    그 사실을 truncated로 돌려준다 — 화면이 "1,000건만 표시합니다"라고 적는다.
    """
    total = conn.execute("SELECT COUNT(*) FROM project").fetchone()[0]
    matched = conn.execute(*build_count_query(f)).fetchone()[0]
    rows = conn.execute(*build_list_query(f)).fetchall()
    excluded_query = build_excluded_query(f)
    excluded = conn.execute(*excluded_query).fetchone()[0] if excluded_query else None
    return ListResult(rows, total, matched, excluded, matched > len(rows))
```

- [ ] **Step 8: 통과를 확인한다**

Run: `PYTHONIOENCODING=utf-8 uv run pytest tests/test_web.py tests/test_web_query.py -v`
Expected: PASS (`test_web.py` 17개, `test_web_query.py` 17개)

- [ ] **Step 9: 전체 검사**

```bash
uv run ruff check --fix .
uv run ruff format .
PYTHONIOENCODING=utf-8 uv run pytest -q
uv run ruff check .
uv run ruff format --check .
```

- [ ] **Step 10: 커밋**

```bash
git add nara/web/query.py nara/web/data.py tests/test_web_query.py tests/test_web.py
git commit -m "feat: 목록 조회 — 사업 한 줄에 최근 공고·판정·부서를 붙인다

행은 사업 하나다. 유찰 재공고가 있어도 한 줄로 나오고 최신 공고를 붙인다.

기간은 행에 보이는 그 공고의 공고일로 거른다. 공고 없는 사업(시트 이관분)은
기간 조건에서 빠지며, 그때의 다른 조건에 걸리는 수만큼 센다 — 고정값 95가
아니다. 이름 검색은 공고명과 사업명을 함께 찾는다. 공고명만 찾으면 시트
이관분은 이름으로 영영 못 찾는다.

진행현황은 단계순으로 정렬한다. 판정 전인 사업은 방향과 관계없이 맨 뒤다.
정렬 기준은 SQL을 만드는 쪽에서도 믿지 않는다. 검색어의 %·_는 글자 그대로
찾는다. 상한을 넘으면 잘린 사실을 돌려준다.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: 상세 조회

한 사업의 전부다. 스펙이 적은 대로 **진행현황 이력 전체와 공고 전부**는 지금 어디에서도 볼 수 없다. 근거 URL은 뉴스·LLM에서 오므로 믿지 않는다 — 링크에는 `http`·`https`만 넣는다.

**Files:**
- Modify: `nara/web/data.py`
- Modify: `tests/test_web.py`

**Interfaces:**
- Consumes: 기존 `nara.energy.EnergyItem`, `nara.energy.estimate_cost(items, prices) -> dict[str, int]`
- Produces:
  - `DECIDED_BY_LABELS: dict[str, str]`
  - `safe_url(url: str | None) -> str` — `http`·`https`가 아니면 `""`
  - `@dataclass(frozen=True) class StatusEntry` — `checked_at: str`, `verdict: str`, `decided_by: str`(화면용 말), `reason: str`, `evidence_url: str`
  - `@dataclass(frozen=True) class EnergyLine` — `source_type: str`, `capacity_kw: float`, `cost: int | None`
  - `@dataclass(frozen=True) class ProjectDetail` — `project: sqlite3.Row`(`org_name` 열 포함), `notices: list[dict]`(`url`은 `safe_url`을 거친 값), `history: list[StatusEntry]`, `depts: list[sqlite3.Row]`, `energy: list[EnergyLine]`, `energy_total: int`, `energy_unpriced: list[str]`
  - `project_detail(conn: sqlite3.Connection, project_id: int) -> ProjectDetail | None`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_web.py`의 `nara.web.data` import 줄을 넓힌다:

```python
from nara.web.data import (
    DatabaseMissing,
    list_projects,
    open_readonly,
    project_detail,
    safe_url,
)
```

`_names` 아래에 도우미를 더한다:

```python
def _detail(path, project_id):
    with closing(open_readonly(path)) as conn:
        return project_detail(conn, project_id)
```

파일 끝에 테스트를 더한다:

```python
def test_project_detail_is_none_for_an_unknown_id(world):
    assert _detail(world[0], 999999) is None


def test_project_detail_lists_every_notice_newest_first_with_awards(world):
    """재공고가 있으면 무슨 일이 있었는지 상세에서 다 보여야 한다. 목록은 최신 하나만 보인다."""
    path, ids = world
    d = _detail(path, ids["welfare"])
    assert [n["bid_no"] for n in d.notices] == ["N2B", "N2A"]
    assert d.notices[0]["winner"] == "가건축"
    assert d.notices[1]["winner"] is None
    assert d.project["org_name"] == "전북특별자치도 완주군"


def test_project_detail_shows_the_whole_verdict_history_newest_first(world):
    """status_check는 쌓이는 표인데 파이프라인은 최신 한 줄만 쓴다. 이력은 여기서 처음 보인다."""
    path, ids = world
    conn = connect(path)
    _verdict(
        conn,
        ids["gym"],
        BUILDING,
        when="2026-09-25T09:00:00",
        decided_by="news",
        reason="착공·기공식 보도",
    )
    conn.commit()
    conn.close()
    d = _detail(path, ids["gym"])
    assert [(h.verdict, h.decided_by) for h in d.history] == [(BUILDING, "뉴스"), (BEFORE, "규칙")]
    assert d.history[0].reason == "착공·기공식 보도"


def test_project_detail_shows_an_unfamiliar_decider_as_is(world):
    """모르는 값을 지우지 않는다. 그대로 보여야 무엇이 들어왔는지 안다."""
    path, ids = world
    conn = connect(path)
    _verdict(conn, ids["culture"], UNKNOWN, decided_by="robot")
    conn.commit()
    conn.close()
    assert _detail(path, ids["culture"]).history[0].decided_by == "robot"


def test_project_detail_reads_the_evidence_url(world):
    path, ids = world
    conn = connect(path)
    _verdict(conn, ids["culture"], BUILDING, evidence_json='{"url": "https://news.example.com/1"}')
    conn.commit()
    conn.close()
    assert _detail(path, ids["culture"]).history[0].evidence_url == "https://news.example.com/1"


def test_project_detail_survives_broken_evidence_json(world):
    """근거가 깨졌다고 상세 화면이 죽으면 그 사업의 나머지 자료까지 못 본다."""
    path, ids = world
    conn = connect(path)
    for i, raw in enumerate(['{"url": ', '["https://x"]', '{"url": 3}', "{}", None]):
        _verdict(
            conn,
            ids["culture"],
            UNKNOWN,
            when=f"2026-09-2{i}T09:00:00",
            reason=f"r{i}",
            evidence_json=raw,
        )
    conn.commit()
    conn.close()
    d = _detail(path, ids["culture"])
    assert len(d.history) == 5
    assert all(h.evidence_url == "" for h in d.history)


def test_project_detail_never_links_a_script_url(world):
    """자동 이스케이프는 href의 'javascript:'를 막지 못한다. 근거는 뉴스·LLM에서 온다."""
    path, ids = world
    conn = connect(path)
    _verdict(conn, ids["culture"], BUILDING, evidence_json='{"url": "javascript:alert(1)"}')
    conn.execute("UPDATE notice SET url = ? WHERE bid_no = 'N6'", (" JavaScript:alert(1)",))
    conn.commit()
    conn.close()
    d = _detail(path, ids["culture"])
    assert d.history[0].evidence_url == ""
    assert d.notices[0]["url"] == ""


def test_safe_url_keeps_web_addresses_only():
    assert safe_url("https://a.kr/x") == "https://a.kr/x"
    assert safe_url("HTTP://A.KR") == "HTTP://A.KR"
    for bad in ("javascript:alert(1)", "data:text/html,x", "//evil.example", "ftp://x", "", None):
        assert safe_url(bad) == "", bad


def test_project_detail_prices_energy_and_names_what_it_could_not_price(world):
    """estimate_cost는 단가표에 없는 에너지원을 빼고 합한다. 합계만 보이면 왜 적은지 모른다."""
    path, ids = world
    conn = connect(path)
    for source, kw in (("PV", 20.0), ("풍력", 10.0)):
        conn.execute(
            "INSERT INTO energy_plan (project_id, source_type, capacity_kw, entered_by, "
            "updated_at) VALUES (?, ?, ?, 'imported', ?)",
            (ids["gym"], source, kw, NOW),
        )
    conn.commit()
    conn.close()
    d = _detail(path, ids["gym"])
    assert [(e.source_type, e.cost) for e in d.energy] == [("PV", 50_000_000), ("풍력", None)]
    assert d.energy_total == 50_000_000
    assert d.energy_unpriced == ["풍력"]


def test_project_detail_lists_departments_newest_first(world):
    path, ids = world
    conn = connect(path)
    for when, dept in (
        ("2026-09-01T00:00:00", "체육진흥과"),
        ("2026-09-10T00:00:00", "문화체육과"),
    ):
        conn.execute(
            "INSERT INTO dept_check (project_id, exec_dept, decided_by, checked_at) "
            "VALUES (?, ?, 'imported', ?)",
            (ids["gym"], dept, when),
        )
    conn.commit()
    conn.close()
    assert [r["exec_dept"] for r in _detail(path, ids["gym"]).depts] == ["문화체육과", "체육진흥과"]
```

- [ ] **Step 2: 실패를 확인한다**

Run: `PYTHONIOENCODING=utf-8 uv run pytest tests/test_web.py -v`
Expected: FAIL — `ImportError: cannot import name 'project_detail'`

- [ ] **Step 3: 최소 구현**

`nara/web/data.py`의 import 묶음을 넓힌다:

```python
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from nara.energy import EnergyItem, estimate_cost
from nara.web.query import (
    Filters,
    build_count_query,
    build_excluded_query,
    build_list_query,
)
```

파일 끝에 더한다:

```python
DECIDED_BY_LABELS = {
    "imported": "시트 이관",
    "rule": "규칙",
    "news": "뉴스",
    "llm": "LLM",
    "human": "사람",
}


@dataclass(frozen=True)
class StatusEntry:
    checked_at: str
    verdict: str
    decided_by: str
    reason: str
    evidence_url: str


@dataclass(frozen=True)
class EnergyLine:
    source_type: str
    capacity_kw: float
    cost: int | None


@dataclass(frozen=True)
class ProjectDetail:
    project: sqlite3.Row
    notices: list[dict]
    history: list[StatusEntry]
    depts: list[sqlite3.Row]
    energy: list[EnergyLine]
    energy_total: int
    energy_unpriced: list[str]


def safe_url(url: str | None) -> str:
    """http·https 주소만 링크로 쓴다.

    자동 이스케이프는 'javascript:' 주소를 막지 못한다 — href에 들어가면
    누르는 순간 실행된다. 근거 URL은 뉴스·LLM에서 오므로 믿지 않는다.
    """
    text = (url or "").strip()
    return text if text.lower().startswith(("http://", "https://")) else ""


def _evidence_url(raw: str | None) -> str:
    """evidence_json의 url. 깨진 JSON이나 url 없음은 빈 문자열 — 화면이 죽지 않는다."""
    if not raw:
        return ""
    try:
        data = json.loads(raw)
    except ValueError:
        return ""
    url = data.get("url") if isinstance(data, dict) else None
    return safe_url(url) if isinstance(url, str) else ""


def _history(conn: sqlite3.Connection, project_id: int) -> list[StatusEntry]:
    rows = conn.execute(
        "SELECT checked_at, verdict, decided_by, reason, evidence_json FROM status_check "
        "WHERE project_id = ? ORDER BY checked_at DESC, id DESC",
        (project_id,),
    )
    return [
        StatusEntry(
            checked_at=row["checked_at"],
            verdict=row["verdict"],
            decided_by=DECIDED_BY_LABELS.get(row["decided_by"], row["decided_by"]),
            reason=row["reason"] or "",
            evidence_url=_evidence_url(row["evidence_json"]),
        )
        for row in rows
    ]


def _energy(conn: sqlite3.Connection, project_id: int) -> tuple[list[EnergyLine], int, list[str]]:
    """예상가는 기존 estimate_cost로 센다.

    그 함수는 단가표에 없는 에너지원을 빼고 합한다. 빠진 에너지원을 따로 돌려줘
    화면이 합계 옆에 적게 한다 — 합계만 보이면 금액이 왜 적은지 알 수 없다.
    """
    prices = {
        row["source_type"]: row["price_per_kw"]
        for row in conn.execute("SELECT source_type, price_per_kw FROM energy_unit_price")
    }
    items = [
        EnergyItem(row["source_type"], row["capacity_kw"])
        for row in conn.execute(
            "SELECT source_type, capacity_kw FROM energy_plan WHERE project_id = ? ORDER BY id",
            (project_id,),
        )
    ]
    lines = [
        EnergyLine(i.source_type, i.capacity_kw, estimate_cost([i], prices).get(i.source_type))
        for i in items
    ]
    total = sum(estimate_cost(items, prices).values())
    unpriced = sorted({i.source_type for i in items if i.source_type not in prices})
    return lines, total, unpriced


def project_detail(conn: sqlite3.Connection, project_id: int) -> ProjectDetail | None:
    """한 사업의 전부. 없는 id면 None."""
    project = conn.execute(
        "SELECT p.*, o.name AS org_name FROM project p JOIN org o ON o.id = p.org_id "
        "WHERE p.id = ?",
        (project_id,),
    ).fetchone()
    if project is None:
        return None
    notices = [
        {**dict(row), "url": safe_url(row["url"])}
        for row in conn.execute(
            "SELECT n.bid_no, n.title, n.notice_date, n.open_date, n.close_date, "
            "n.budget_krw, n.officer_name, n.officer_tel, n.url, a.winner, a.award_date "
            "FROM notice n LEFT JOIN award a ON a.bid_no = n.bid_no "
            "WHERE n.project_id = ? "
            "ORDER BY COALESCE(n.notice_date, '') DESC, n.bid_no DESC",
            (project_id,),
        )
    ]
    depts = conn.execute(
        "SELECT exec_dept, contract_dept, snippet, source_file, checked_at FROM dept_check "
        "WHERE project_id = ? ORDER BY checked_at DESC, id DESC",
        (project_id,),
    ).fetchall()
    energy, energy_total, energy_unpriced = _energy(conn, project_id)
    return ProjectDetail(
        project=project,
        notices=notices,
        history=_history(conn, project_id),
        depts=depts,
        energy=energy,
        energy_total=energy_total,
        energy_unpriced=energy_unpriced,
    )
```

- [ ] **Step 4: 통과를 확인한다**

Run: `PYTHONIOENCODING=utf-8 uv run pytest tests/test_web.py -v`
Expected: PASS (27개)

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
git add nara/web/data.py tests/test_web.py
git commit -m "feat: 상세 조회 — 판정 이력 전체와 공고 전부를 보인다

status_check는 쌓이는 표인데 파이프라인은 최신 한 줄만 쓴다. 사람이 조사한
판정과 기계가 내린 판정, 그리고 판정이 언제 바뀌었는지가 여기서 처음 보인다.
유찰 재공고가 있으면 공고도 전부 보인다.

근거 URL은 뉴스·LLM에서 온다. 자동 이스케이프는 href의 'javascript:'를
막지 못하므로 http·https만 링크로 쓴다. 깨진 evidence_json은 근거만 비우고
화면은 그대로 그린다.

신재생 예상가는 기존 estimate_cost로 센다. 그 함수는 단가표에 없는
에너지원을 빼고 합하므로, 빠진 에너지원을 따로 돌려준다.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---
### Task 5: 실행 기록과 기관 목록

목록 맨 위에 파이프라인 단계별 마지막 실행을 보인다. 원 명세가 핵심 위험으로 꼽은 "자동 실행이 조용히 멈추는 것"을 보이는 장치다. 실측으로 실제 DB에는 `enrich status` 실행 기록이 한 번도 없다 — 화면에 "실행 기록 없음"이 떠야 맞다.

`run_log`는 실행을 시작할 때 `status` 없이 한 줄을 넣고 끝날 때 채운다(`nara/runlog.py`). 프로세스가 죽으면 마무리가 돌지 못해 `status`가 비어 남는다. 이 상태를 "끝나지 않음"으로 보인다.

**Files:**
- Modify: `nara/web/data.py`
- Modify: `tests/test_web.py`

**Interfaces:**
- Consumes: 기존 `nara.store.last_run(conn, command) -> sqlite3.Row | None`
- Produces:
  - `PIPELINE_STAGES: tuple[tuple[str, str], ...]` — `(명령, 화면 이름)` 네 쌍
  - `@dataclass(frozen=True) class StageRun` — `label: str`, `started_at: str | None`, `status_label: str`, `healthy: bool`
  - `last_runs(conn: sqlite3.Connection) -> list[StageRun]`
  - `org_options(conn: sqlite3.Connection) -> list[sqlite3.Row]` — 열 `id, name, tier`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_web.py`의 `nara.web.data` import를 넓힌다:

```python
from nara.web.data import (
    DatabaseMissing,
    last_runs,
    list_projects,
    open_readonly,
    org_options,
    project_detail,
    safe_url,
)
```

파일 끝에 더한다:

```python
def _run(conn, command, status, started_at):
    conn.execute(
        "INSERT INTO run_log (command, started_at, status) VALUES (?, ?, ?)",
        (command, started_at, status),
    )


def test_last_runs_names_every_stage_even_one_that_never_ran(world):
    """한 번도 돌지 않은 단계가 화면에서 사라지면 '멈춘 줄 모르는' 사고가 그대로다."""
    with closing(open_readonly(world[0])) as conn:
        runs = last_runs(conn)
    assert [r.label for r in runs] == ["수집", "소급 수집", "낙찰 조회", "진행현황"]
    for r in runs:
        assert (r.started_at, r.status_label, r.healthy) == (None, "실행 기록 없음", False)


def test_last_runs_reports_the_latest_run_of_each_stage(world):
    path, _ = world
    conn = connect(path)
    _run(conn, "collect", "ok", "2026-09-20T06:10:00")
    _run(conn, "collect", "partial", "2026-09-26T06:10:00")
    _run(conn, "enrich award", "ok", "2026-09-26T06:14:00")
    _run(conn, "enrich status", "error", "2026-09-26T06:20:00")
    _run(conn, "backfill", None, "2026-09-26T07:00:00")
    _run(conn, "migrate tsv", "ok", "2026-09-26T08:00:00")
    conn.commit()
    conn.close()
    with closing(open_readonly(path)) as conn:
        runs = {r.label: r for r in last_runs(conn)}
    assert (runs["수집"].started_at, runs["수집"].status_label) == (
        "2026-09-26T06:10:00",
        "일부 실패",
    )
    assert runs["수집"].healthy is False
    assert (runs["낙찰 조회"].status_label, runs["낙찰 조회"].healthy) == ("정상", True)
    assert runs["진행현황"].status_label == "실패"
    # 프로세스가 죽으면 run_log의 마무리가 돌지 못해 status가 비어 남는다
    assert runs["소급 수집"].status_label == "끝나지 않음"
    # 이관은 파이프라인 단계가 아니다
    assert set(runs) == {"수집", "소급 수집", "낙찰 조회", "진행현황"}


def test_org_options_puts_focus_orgs_first(world):
    with closing(open_readonly(world[0])) as conn:
        names = [o["name"] for o in org_options(conn)]
    assert names == ["전북특별자치도 완주군", "경기도 성남시"]
```

- [ ] **Step 2: 실패를 확인한다**

Run: `PYTHONIOENCODING=utf-8 uv run pytest tests/test_web.py -v`
Expected: FAIL — `ImportError: cannot import name 'last_runs'`

- [ ] **Step 3: 최소 구현**

`nara/web/data.py`의 import 묶음에 한 줄을 더한다(`nara.energy` 줄 아래):

```python
from nara.store import last_run
```

파일 끝에 더한다:

```python
PIPELINE_STAGES = (
    ("collect", "수집"),
    ("backfill", "소급 수집"),
    ("enrich award", "낙찰 조회"),
    ("enrich status", "진행현황"),
)
_STATUS_LABELS = {"ok": "정상", "partial": "일부 실패", "error": "실패"}


@dataclass(frozen=True)
class StageRun:
    label: str
    started_at: str | None
    status_label: str
    healthy: bool


def _status_label(status: str | None) -> str:
    # run_log는 시작할 때 status 없이 넣고 끝날 때 채운다. 비어 있으면 끝나지 않은 실행이다.
    if status is None:
        return "끝나지 않음"
    return _STATUS_LABELS.get(status, status)


def last_runs(conn: sqlite3.Connection) -> list[StageRun]:
    """파이프라인 단계마다 가장 최근 실행.

    원 명세가 핵심 위험으로 꼽은 '자동 실행이 조용히 멈추는 것'을 목록 맨 위에
    보이는 장치다. 한 번도 돌지 않은 단계도 빠뜨리지 않는다.
    """
    runs = []
    for command, label in PIPELINE_STAGES:
        row = last_run(conn, command)
        if row is None:
            runs.append(StageRun(label, None, "실행 기록 없음", False))
        else:
            status = row["status"]
            runs.append(StageRun(label, row["started_at"], _status_label(status), status == "ok"))
    return runs


def org_options(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """수요기관 선택 목록. 관심기관을 먼저, 그 안에서는 이름순."""
    return conn.execute(
        "SELECT id, name, tier FROM org ORDER BY tier = 'focus' DESC, name"
    ).fetchall()
```

- [ ] **Step 4: 통과를 확인한다**

Run: `PYTHONIOENCODING=utf-8 uv run pytest tests/test_web.py -v`
Expected: PASS (30개)

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
git add nara/web/data.py tests/test_web.py
git commit -m "feat: 단계별 마지막 실행 — 수집이 멈추면 화면 맨 위에 보인다

원 명세가 핵심 위험으로 꼽은 것은 자동 실행이 조용히 멈추는 것이다.
수집·소급 수집·낙찰 조회·진행현황의 마지막 실행과 상태를 보인다.

한 번도 돌지 않은 단계도 '실행 기록 없음'으로 남긴다. run_log는 시작할 때
status 없이 넣고 끝날 때 채우므로, 프로세스가 죽으면 status가 비어 남는다 —
이것을 '끝나지 않음'으로 보인다.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Flask 앱 — 목록·상세 화면

두 라우트를 한 작업에서 만든다. 목록의 사업명은 상세로, 상세는 목록으로 링크하므로(`url_for`) 한쪽만 있으면 다른 쪽이 `BuildError`로 깨진다.

**Files:**
- Create: `nara/web/app.py`
- Create: `nara/web/templates/base.html`
- Create: `nara/web/templates/list.html`
- Create: `nara/web/templates/detail.html`
- Modify: `tests/test_web.py`

**Interfaces:**
- Consumes: Task 1~5의 `open_readonly`, `DatabaseMissing`, `list_projects`, `project_detail`, `last_runs`, `org_options`, `parse_filters`, `to_args`, `SORT_KEYS`, `VERDICT_CHOICES`, `NO_VERDICT`
- Produces:
  - `create_app(db_path: Path) -> flask.Flask` — 라우트 `index`(`GET /`), `detail`(`GET /project/<int:project_id>`)
  - `get_conn() -> sqlite3.Connection` — 요청마다 읽기 전용 연결 하나. 요청이 끝나면 닫는다
  - 템플릿 필터 `dash`(값 없음 → `—`), `won`(정수 → `1,234원`)

**연결을 요청마다 여는 이유:** Flask 개발 서버는 요청을 스레드로 나눠 처리한다. `sqlite3` 연결은 만든 스레드에서만 쓸 수 있다. 요청마다 열고 `teardown_appcontext`에서 닫으면 이 제약에 걸리지 않는다. 249행 규모에서 여는 비용은 무시할 만하다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_web.py`의 import 묶음에 더한다. 순서는 전체 검사 단계의 `ruff check --fix`가 맞춘다:

```python
import html
import re
from urllib.parse import parse_qs, urlsplit

from nara.web.app import create_app, get_conn
```

파일 끝에 더한다:

```python
def _client(path):
    app = create_app(path)
    app.testing = True
    return app.test_client()


def _text(resp):
    return resp.get_data(as_text=True)


def _header_link(text, label):
    """열 머리 링크의 쿼리 인자. 템플릿은 &를 &amp;로 이스케이프한다."""
    href = re.search(rf'href="([^"]*)">{label}</a>', text).group(1)
    return parse_qs(urlsplit(html.unescape(href)).query)


def test_list_page_shows_every_project_and_the_counts(world):
    resp = _client(world[0]).get("/")
    assert resp.status_code == 200
    text = _text(resp)
    assert "6건 중 6건" in text
    for name in (
        "완주군 다목적체육관",
        "완주군 종합사회복지관",
        "성남시 박물관",
        "완주 풍류체험관",
        "여수동 100% 친환경 센터",
        "성남시 문화복합시설",
    ):
        assert name in text


def test_list_page_shows_why_a_row_matched_by_notice_title(world):
    """목록엔 사업명만 보인다. 공고명으로만 걸린 행은 왜 걸렸는지 적어야 한다."""
    assert "공고명: 성남시 체육관 리모델링" in _text(_client(world[0]).get("/?q=체육"))


def test_list_page_says_how_many_sheet_projects_a_date_filter_dropped(world):
    text = _text(_client(world[0]).get("/?from=2026-01-01"))
    assert "6건 중 3건" in text
    assert "공고가 없는 사업 2건이 제외되었습니다" in text


def test_list_page_explains_ignored_input_instead_of_failing(world):
    resp = _client(world[0]).get("/?from=어제&sort=evil&org=abc")
    assert resp.status_code == 200
    text = _text(resp)
    assert "시작일 형식이 맞지 않아 무시했습니다" in text
    assert "쓸 수 없어 공고일로 바꿨습니다" in text
    assert "쓸 수 없어 무시했습니다" in text


def test_sort_links_keep_the_conditions_and_flip_the_current_column(world):
    """URL이 곧 상태다. 열 머리를 눌러도 걸어 둔 조건이 남아야 한다."""
    client = _client(world[0])
    text = _text(client.get("/?q=성남"))
    # 다른 열을 누르면 그 열의 오름차순으로 간다
    assert _header_link(text, "사업명") == {"q": ["성남"], "sort": ["name"], "desc": ["0"]}
    # 지금 정렬 중인 열을 누르면 방향이 뒤집힌다
    text = _text(client.get("/?q=성남&sort=notice_date&desc=0"))
    assert _header_link(text, "공고일")["desc"] == ["1"]


def test_list_page_marks_a_stage_that_never_ran(world):
    assert "실행 기록 없음" in _text(_client(world[0]).get("/"))


def test_detail_page_shows_all_notices_and_the_history(world):
    path, ids = world
    text = _text(_client(path).get(f"/project/{ids['welfare']}"))
    assert "공고 2건" in text
    assert "완주군 종합사회복지관 설계용역(재공고)" in text
    assert "가건축" in text
    assert "규칙" in text


def test_detail_page_is_404_for_an_unknown_or_non_numeric_id(world):
    client = _client(world[0])
    assert client.get("/project/999999").status_code == 404
    assert client.get("/project/abc").status_code == 404


def test_pages_escape_markup_that_comes_from_the_data(world):
    """사업명·기사 제목은 밖에서 온 글이다. 그대로 그리면 스크립트가 실행된다."""
    path, _ = world
    conn = connect(path)
    org_id = upsert_org(conn, "전북특별자치도 완주군", SETTINGS, NOW)
    project_id = ensure_project(conn, org_id, "<script>alert(1)</script>", "manual", NOW)
    conn.close()
    client = _client(path)
    for url in ("/", f"/project/{project_id}"):
        text = _text(client.get(url))
        assert "&lt;script&gt;" in text
        assert "<script" not in text


def test_detail_page_does_not_link_a_script_url(world):
    path, ids = world
    conn = connect(path)
    _verdict(conn, ids["culture"], BUILDING, evidence_json='{"url": "javascript:alert(1)"}')
    conn.commit()
    conn.close()
    assert "javascript:" not in _text(_client(path).get(f"/project/{ids['culture']}")).lower()


def test_the_app_opens_the_database_read_only(world):
    """스펙: 앱이 연 연결로 INSERT를 시도해 거부되는 것을 확인한다.

    누군가 open_readonly를 connect로 바꾸면 이 테스트가 깨진다.
    """
    app = create_app(world[0])
    with app.app_context():
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            get_conn().execute("INSERT INTO app_state (key, value) VALUES ('x', 'y')")


def test_a_missing_database_is_reported_not_crashed(tmp_path):
    """서버를 띄운 뒤 DB 파일이 사라진 경우다. 추적 화면 대신 이유를 말한다."""
    resp = _client(tmp_path / "gone.db").get("/")
    assert resp.status_code == 503
    assert "DB 파일이 없다" in _text(resp)
    assert not (tmp_path / "gone.db").exists()
```

- [ ] **Step 2: 실패를 확인한다**

Run: `PYTHONIOENCODING=utf-8 uv run pytest tests/test_web.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'nara.web.app'`

- [ ] **Step 3: 앱을 만든다**

`nara/web/app.py`:

```python
"""웹 조회 화면. 요청을 받아 query·data에 넘기고 템플릿을 그린다."""

import sqlite3
from dataclasses import replace
from pathlib import Path

from flask import Flask, abort, current_app, g, render_template, request, url_for

from nara.web.data import (
    DatabaseMissing,
    last_runs,
    list_projects,
    open_readonly,
    org_options,
    project_detail,
)
from nara.web.query import (
    NO_VERDICT,
    SORT_KEYS,
    VERDICT_CHOICES,
    Filters,
    parse_filters,
    to_args,
)


def get_conn() -> sqlite3.Connection:
    """요청마다 읽기 전용 연결 하나. sqlite3 연결은 만든 스레드에서만 쓸 수 있다."""
    if "conn" not in g:
        g.conn = open_readonly(current_app.config["DB_PATH"])
    return g.conn


def _dash(value):
    return "—" if value is None or value == "" else value


def _won(value):
    return "—" if value is None or value == "" else f"{int(value):,}원"


def _conditions(f: Filters, org_names: dict[int, str]) -> list[str]:
    """결과 머리에 되풀이할 조건. 없는 기관 id도 지우지 않고 그대로 보인다."""
    parts = [org_names.get(i, f"없는 기관 #{i}") for i in f.orgs]
    if f.focus_only:
        parts.append("관심기관만")
    if f.q:
        parts.append(f'"{f.q}"')
    if f.has_date:
        parts.append(f"공고일 {f.date_from}~{f.date_to}")
    parts.extend(f.verdicts)
    return parts


def _sort_links(f: Filters) -> dict[str, str]:
    """열 머리 링크. 지금 정렬 중인 열이면 방향을 뒤집고, 다른 열이면 오름차순으로 간다."""
    links = {}
    for key in SORT_KEYS:
        desc = (not f.desc) if key == f.sort else False
        links[key] = url_for("index", **to_args(replace(f, sort=key, desc=desc)))
    return links


def create_app(db_path: Path) -> Flask:
    app = Flask(__name__)
    app.config["DB_PATH"] = Path(db_path)
    app.add_template_filter(_dash, "dash")
    app.add_template_filter(_won, "won")

    @app.teardown_appcontext
    def _close(_exc):
        conn = g.pop("conn", None)
        if conn is not None:
            conn.close()

    @app.errorhandler(DatabaseMissing)
    def _missing(exc):
        # 서버를 띄운 뒤 DB 파일이 사라진 경우다. 추적 화면 대신 이유를 말한다.
        return str(exc), 503, {"Content-Type": "text/plain; charset=utf-8"}

    @app.get("/")
    def index():
        f, notes = parse_filters({k: request.args.getlist(k) for k in request.args})
        conn = get_conn()
        orgs = org_options(conn)
        return render_template(
            "list.html",
            f=f,
            notes=notes,
            result=list_projects(conn, f),
            runs=last_runs(conn),
            orgs=orgs,
            conditions=_conditions(f, {o["id"]: o["name"] for o in orgs}),
            sort_links=_sort_links(f),
            verdict_choices=VERDICT_CHOICES,
            no_verdict=NO_VERDICT,
        )

    @app.get("/project/<int:project_id>")
    def detail(project_id: int):
        d = project_detail(get_conn(), project_id)
        if d is None:
            abort(404)
        return render_template("detail.html", d=d)

    return app
```

- [ ] **Step 4: 템플릿을 만든다**

`nara/web/templates/base.html`:

```html
<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{% block title %}사업 조회{% endblock %} · 나라</title>
<style>
  :root {
    --fg: #1a1a1a; --muted: #666; --line: #ddd; --bad: #b00020;
    --bg: #fff; --head: #f5f5f5; --link: #0b57d0;
  }
  body {
    font-family: "Malgun Gothic", "Apple SD Gothic Neo", sans-serif;
    color: var(--fg); background: var(--bg); margin: 16px; font-size: 14px;
  }
  a { color: var(--link); }
  table { border-collapse: collapse; width: 100%; }
  th, td { border-bottom: 1px solid var(--line); padding: 6px 8px; text-align: left; vertical-align: top; }
  th { background: var(--head); white-space: nowrap; }
  .muted { color: var(--muted); font-size: 12px; }
  .bad { color: var(--bad); font-weight: bold; }
  .notes li { color: var(--bad); }
  .runs { margin: 0 0 12px; }
  form.filters { display: flex; flex-wrap: wrap; gap: 12px; align-items: flex-end; margin: 12px 0; }
  form.filters label { display: flex; flex-direction: column; gap: 4px; }
</style>
</head>
<body>
{% block body %}{% endblock %}
</body>
</html>
```

`nara/web/templates/list.html`:

```html
{% extends "base.html" %}
{% block body %}
<h1>사업 조회</h1>

<p class="runs">
{% for r in runs %}
  <span class="{{ '' if r.healthy else 'bad' }}">{{ r.label }} {{ r.started_at|dash }} {{ r.status_label }}</span>{% if not loop.last %} · {% endif %}
{% endfor %}
</p>

<form class="filters" method="get" action="{{ url_for('index') }}">
  <label>수요기관
    <select name="org" multiple size="6">
      {% for o in orgs %}
      <option value="{{ o.id }}"{% if o.id in f.orgs %} selected{% endif %}>{{ o.name }}{% if o.tier == 'focus' %} ★{% endif %}</option>
      {% endfor %}
    </select>
  </label>
  <label>관심기관
    <span><input type="checkbox" name="focus" value="1"{% if f.focus_only %} checked{% endif %}> 관심기관만</span>
  </label>
  <label>이름 검색
    <input type="search" name="q" value="{{ f.q }}" placeholder="공고명 또는 사업명">
  </label>
  <label>공고일 시작 <input type="date" name="from" value="{{ f.date_from }}"></label>
  <label>공고일 끝 <input type="date" name="to" value="{{ f.date_to }}"></label>
  <label>진행현황
    <select name="verdict" multiple size="5">
      {% for v in verdict_choices %}
      <option value="{{ v }}"{% if v in f.verdicts %} selected{% endif %}>{{ v }}</option>
      {% endfor %}
    </select>
  </label>
  <input type="hidden" name="sort" value="{{ f.sort }}">
  <input type="hidden" name="desc" value="{{ '1' if f.desc else '0' }}">
  <button type="submit">조회</button>
  <a href="{{ url_for('index') }}">조건 지우기</a>
</form>

<p><strong>{{ result.total }}건 중 {{ result.matched }}건</strong>
{% if conditions %}<span class="muted">조건: {{ conditions|join(' · ') }}</span>{% endif %}</p>
{% if result.excluded_no_notice %}
<p class="muted">공고일 조건이 걸려 공고가 없는 사업 {{ result.excluded_no_notice }}건이 제외되었습니다</p>
{% endif %}
{% if result.truncated %}
<p class="bad">{{ result.rows|length }}건만 표시합니다. 조건을 좁혀 주세요</p>
{% endif %}
{% if notes %}
<ul class="notes">{% for n in notes %}<li>{{ n }}</li>{% endfor %}</ul>
{% endif %}

<table>
<thead><tr>
  <th><a href="{{ sort_links.org }}">수요기관</a></th>
  <th><a href="{{ sort_links.name }}">사업명</a></th>
  <th><a href="{{ sort_links.notice_date }}">공고일</a></th>
  <th><a href="{{ sort_links.open_date }}">개찰일</a></th>
  <th><a href="{{ sort_links.verdict }}">진행현황</a></th>
  <th>낙찰업체</th>
  <th>실행부서</th>
  <th>ZEB</th>
</tr></thead>
<tbody>
{% for r in result.rows %}
<tr>
  <td>{{ r.org_name }}</td>
  <td><a href="{{ url_for('detail', project_id=r.id) }}">{{ r.name }}</a>
    {% if r.matched_title %}<div class="muted">공고명: {{ r.matched_title }}</div>{% endif %}</td>
  <td>{{ r.notice_date|dash }}</td>
  <td>{{ r.open_date|dash }}</td>
  <td>{{ r.verdict or no_verdict }}</td>
  <td>{{ r.winner|dash }}</td>
  <td>{{ r.exec_dept|dash }}</td>
  <td>{{ r.zeb_grade|dash }}</td>
</tr>
{% else %}
<tr><td colspan="8" class="muted">조건에 맞는 사업이 없습니다</td></tr>
{% endfor %}
</tbody>
</table>
{% endblock %}
```

`nara/web/templates/detail.html`:

```html
{% extends "base.html" %}
{% block title %}{{ d.project.name }}{% endblock %}
{% block body %}
<p><a href="{{ url_for('index') }}">← 목록으로</a></p>
<h1>{{ d.project.name }}</h1>
<p class="muted">{{ d.project.org_name }} · 출처 {{ d.project.source }}</p>

<h2>사업</h2>
<table>
  <tr><th>주소</th><td>{{ d.project.address|dash }}</td></tr>
  <tr><th>착공일</th><td>{{ d.project.start_date|dash }}</td></tr>
  <tr><th>준공일</th><td>{{ d.project.end_date|dash }}</td></tr>
  <tr><th>연면적</th><td>{{ d.project.floor_area|dash }}</td></tr>
  <tr><th>ZEB 등급</th><td>{{ d.project.zeb_grade|dash }}</td></tr>
  <tr><th>신재생 비율</th><td>{{ d.project.re_ratio|dash }}</td></tr>
  <tr><th>기타 인증</th><td>{{ d.project.etc_cert|dash }}</td></tr>
  <tr><th>관급 장비</th><td>{{ d.project.guide_equip|dash }}</td></tr>
  <tr><th>비고</th><td>{{ d.project.note|dash }}</td></tr>
</table>

<h2>공고 {{ d.notices|length }}건</h2>
{% if d.notices %}
<table>
<thead><tr><th>공고명</th><th>공고일</th><th>개찰일</th><th>마감일</th><th>예산</th><th>담당자</th><th>낙찰업체</th><th>낙찰일</th></tr></thead>
<tbody>
{% for n in d.notices %}
<tr>
  <td>{% if n.url %}<a href="{{ n.url }}" rel="noopener noreferrer" target="_blank">{{ n.title }}</a>{% else %}{{ n.title }}{% endif %}</td>
  <td>{{ n.notice_date|dash }}</td>
  <td>{{ n.open_date|dash }}</td>
  <td>{{ n.close_date|dash }}</td>
  <td>{{ n.budget_krw|won }}</td>
  <td>{{ n.officer_name|dash }}{% if n.officer_tel %} <span class="muted">{{ n.officer_tel }}</span>{% endif %}</td>
  <td>{{ n.winner|dash }}</td>
  <td>{{ n.award_date|dash }}</td>
</tr>
{% endfor %}
</tbody>
</table>
{% else %}
<p class="muted">공고가 없습니다{% if d.project.source == 'manual' %} — 시트에서 이관한 사업입니다{% endif %}</p>
{% endif %}

<h2>진행현황 이력 {{ d.history|length }}건</h2>
{% if d.history %}
<table>
<thead><tr><th>시각</th><th>판정</th><th>판정 주체</th><th>사유</th><th>근거</th></tr></thead>
<tbody>
{% for h in d.history %}
<tr>
  <td>{{ h.checked_at }}</td>
  <td>{{ h.verdict }}</td>
  <td>{{ h.decided_by }}</td>
  <td>{{ h.reason|dash }}</td>
  <td>{% if h.evidence_url %}<a href="{{ h.evidence_url }}" rel="noopener noreferrer" target="_blank">기사</a>{% else %}—{% endif %}</td>
</tr>
{% endfor %}
</tbody>
</table>
{% else %}
<p class="muted">판정 전입니다</p>
{% endif %}

<h2>실행부서</h2>
{% if d.depts %}
<table>
<thead><tr><th>실행부서</th><th>계약부서</th><th>근거 문장</th><th>출처</th><th>조회 시각</th></tr></thead>
<tbody>
{% for p in d.depts %}
<tr>
  <td>{{ p.exec_dept|dash }}</td>
  <td>{{ p.contract_dept|dash }}</td>
  <td>{{ p.snippet|dash }}</td>
  <td>{{ p.source_file|dash }}</td>
  <td>{{ p.checked_at }}</td>
</tr>
{% endfor %}
</tbody>
</table>
{% else %}
<p class="muted">실행부서 조회 기록이 없습니다</p>
{% endif %}

<h2>신재생 계획</h2>
{% if d.energy %}
<table>
<thead><tr><th>에너지원</th><th>용량</th><th>예상가</th></tr></thead>
<tbody>
{% for e in d.energy %}
<tr><td>{{ e.source_type }}</td><td>{{ e.capacity_kw }} kW</td><td>{{ e.cost|won }}</td></tr>
{% endfor %}
</tbody>
</table>
<p>합계 {{ d.energy_total|won }}{% if d.energy_unpriced %}
<span class="bad"> — 단가가 없어 합계에서 빠짐: {{ d.energy_unpriced|join(', ') }}</span>{% endif %}</p>
{% else %}
<p class="muted">신재생 계획이 없습니다</p>
{% endif %}
{% endblock %}
```

- [ ] **Step 5: 통과를 확인한다**

Run: `PYTHONIOENCODING=utf-8 uv run pytest tests/test_web.py -v`
Expected: PASS (42개)

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
git add nara/web/app.py nara/web/templates tests/test_web.py
git commit -m "feat: 웹 조회 화면 — 목록과 상세

목록은 결과 머리에 전체·걸린 건수와 조건을 늘 되풀이한다. 무시한 입력,
기간 조건으로 빠진 공고 없는 사업, 상한으로 잘린 결과를 적는다. 맨 위에는
파이프라인 단계별 마지막 실행이 보인다.

열 머리 링크는 걸어 둔 조건을 그대로 싣는다 — URL이 곧 상태다.

연결은 요청마다 읽기 전용으로 연다. sqlite3 연결은 만든 스레드에서만 쓸 수
있고 개발 서버는 요청을 스레드로 나눈다. 서버를 띄운 뒤 DB가 사라지면
추적 화면 대신 503과 이유를 돌려준다.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---
### Task 7: `serve` 명령·README·실데이터 확인·디자인 검수

**Files:**
- Modify: `nara/cli.py`
- Modify: `README.md`
- Modify: `tests/test_web.py`

**Interfaces:**
- Consumes: Task 6의 `create_app(db_path: Path) -> flask.Flask`
- Produces: CLI 명령 `nara serve [--port 8000] [--db data/nara.db]`

`serve`는 기존 `_open_db`를 쓰지 않는다. 그 함수는 `migrate`를 돌려 없는 파일을 새로 만든다 — `doctor`가 같은 이유로 `_open_db`를 피한다(`nara/cli.py`의 `doctor` 주석).

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_web.py`의 import 묶음에 더한다:

```python
from flask import Flask
from typer.testing import CliRunner

from nara.cli import app as cli_app
```

파일 끝에 더한다:

```python
def test_serve_refuses_a_missing_database(tmp_path):
    """오타 난 경로에 빈 DB를 만들고 '0건'을 보이면 안 된다."""
    missing = tmp_path / "gone.db"
    result = CliRunner().invoke(cli_app, ["serve", "--db", str(missing)])
    assert result.exit_code == 1
    assert "DB 파일이 없다" in result.output
    assert not missing.exists()


def test_serve_binds_to_this_computer_only_without_the_debugger(world, monkeypatch):
    """127.0.0.1 밖에 열면 3단계 전에 외부에 노출된다.

    debug=True는 브라우저에서 파이썬 코드를 실행하는 디버거를 연다.
    """
    seen = {}
    monkeypatch.setattr(Flask, "run", lambda self, **kw: seen.update(kw))
    result = CliRunner().invoke(cli_app, ["serve", "--db", str(world[0]), "--port", "8123"])
    assert result.exit_code == 0, result.output
    assert seen == {"host": "127.0.0.1", "port": 8123, "debug": False}


def test_serve_rejects_an_out_of_range_port(world):
    result = CliRunner().invoke(cli_app, ["serve", "--db", str(world[0]), "--port", "70000"])
    assert result.exit_code != 0
```

- [ ] **Step 2: 실패를 확인한다**

Run: `PYTHONIOENCODING=utf-8 uv run pytest tests/test_web.py -v -k serve`
Expected: FAIL — `serve` 명령이 없어 exit_code 2

- [ ] **Step 3: 명령을 더한다**

`nara/cli.py`의 import 묶음에 더한다. 순서는 전체 검사 단계의 `ruff check --fix`가 맞춘다:

```python
from nara.web.app import create_app
```

`doctor` 명령 바로 아래, `enrich_app = typer.Typer(...)` 위에 더한다:

```python
@app.command()
def serve(
    port: int = typer.Option(8000, min=1, max=65535, help="포트"),
    db: Path = typer.Option(DEFAULT_DB, help="SQLite 경로"),
) -> None:
    """조회 화면을 띄운다. 이 컴퓨터(127.0.0.1)에서만 열리고 읽기 전용이다."""
    # _open_db를 쓰지 않는다. migrate가 없는 파일을 새로 만든다 — doctor와 같은 이유.
    if not db.exists():
        typer.echo(f"DB 파일이 없다: {db}", err=True)
        raise typer.Exit(code=1)
    typer.echo(f"조회 화면: http://127.0.0.1:{port}  (끄려면 Ctrl+C)")
    # debug=True는 브라우저에서 코드를 실행하는 디버거를 연다. 로컬이어도 켜지 않는다.
    create_app(db).run(host="127.0.0.1", port=port, debug=False)
```

- [ ] **Step 4: 통과를 확인한다**

Run: `PYTHONIOENCODING=utf-8 uv run pytest tests/test_web.py -v`
Expected: PASS (45개)

- [ ] **Step 5: README를 고친다**

`README.md`의 `## 쓰는 법` 코드 블록을 이렇게 바꾼다. `enrich status`는 이미 있던 명령인데 README에 빠져 있었다.

```bash
uv run nara collect --days 3                          # 최근 3일 수집
uv run nara backfill --days 365                        # 과거 1년 소급 (중단해도 이어짐)
uv run nara enrich award --tier focus                   # 낙찰업체 조회
uv run nara enrich status                               # 진행현황 판정 (구글 뉴스, 키 불필요)
uv run nara migrate tsv <파일> --tab 전북특별자치도      # 기존 시트 이관
uv run nara doctor                                      # 데이터 점검
uv run nara serve                                       # 조회 화면 → http://127.0.0.1:8000
```

- [ ] **Step 6: 전체 검사**

```bash
uv run ruff check --fix .
uv run ruff format .
PYTHONIOENCODING=utf-8 uv run pytest -q
uv run ruff check .
uv run ruff format --check .
```

- [ ] **Step 7: 실데이터로 띄워 본다**

원본에 쓰지 않도록 사본으로 띄운다. 서버는 백그라운드로 돌리고, 확인이 끝나면 반드시 끈다.

```bash
T="$(cygpath -w ~/AppData/Local/Temp/claude)"
cp data/nara.db "$T/serve.db"
PYTHONIOENCODING=utf-8 uv run nara serve --db "$T\\serve.db" --port 8765
```

위 명령은 백그라운드로 실행한다. 서버가 뜬 뒤 다른 셸에서:

```bash
T="$(cygpath -w ~/AppData/Local/Temp/claude)"
curl -s "http://127.0.0.1:8765/" -o "$T/page_list.html"
curl -s "http://127.0.0.1:8765/?from=2026-01-01" -o "$T/page_from.html"
curl -s "http://127.0.0.1:8765/?q=%EC%B2%B4%EC%9C%A1%EA%B4%80" -o "$T/page_q.html"
curl -s "http://127.0.0.1:8765/?sort=verdict&desc=0" -o "$T/page_verdict.html"
curl -s -o /dev/null -w "%{http_code}\n" "http://127.0.0.1:8765/project/999999"
PYTHONIOENCODING=utf-8 uv run python - "$T" <<'PY'
import re, sys, pathlib
t = pathlib.Path(sys.argv[1])
for name in ("page_list", "page_from", "page_q", "page_verdict"):
    text = (t / f"{name}.html").read_text(encoding="utf-8")
    head = re.search(r"<strong>(.*?)</strong>", text).group(1)
    dropped = re.search(r"공고가 없는 사업 (\d+)건", text)
    sys.stdout.buffer.write(
        f"{name}: {head}  제외 {dropped.group(1) if dropped else '-'}건\n".encode("utf-8")
    )
PY
```

기대하는 값:

| 화면 | 기대 |
|---|---|
| `page_list` | `249건 중 249건`, 제외 `-` |
| `page_from` | 걸린 건수가 249보다 적고, **제외 `95`건** — 공고 없는 시트 이관분 전부 |
| `page_q` | 걸린 건수가 0보다 크다 |
| `page_verdict` | 200으로 그려진다 |
| `/project/999999` | `404` |

계획을 쓸 때(2026-09-27) 이 계획의 코드를 조립해 실데이터 사본으로 실제로 띄워 본 값이다: `page_from`은 `249건 중 134건`·제외 `95건`, `page_q`는 `249건 중 4건`, 실행 기록 줄은 `소급 수집 — 실행 기록 없음 · 진행현황 — 실행 기록 없음`. 그 뒤 수집을 돌렸다면 숫자가 달라질 수 있다. 그때는 제외 건수를 이 값과 비교한다:

```bash
PYTHONIOENCODING=utf-8 uv run python -c "import sqlite3; c = sqlite3.connect('file:data/nara.db?mode=ro', uri=True); print(c.execute('SELECT COUNT(*) FROM project p WHERE NOT EXISTS (SELECT 1 FROM notice n WHERE n.project_id = p.id)').fetchone()[0])"
```

그리고 `page_list.html`에 `실행 기록 없음`이 있어야 한다 — 실제 DB에는 `enrich status` 실행 기록이 없다. 있는 행 하나의 상세(`/project/<id>`)도 열어 판정 이력이 보이는지 확인한다. 끝나면 서버를 끈다.

**기대와 다르면 멈추고 보고한다.** 숫자를 맞추려고 코드를 고치지 않는다.

- [ ] **Step 8: 디자인 검수(hallmark)**

사용자 전역 규칙(`~/.claude/rules/design-review.md`)이 직접 만든 HTML 화면을 검수 대상으로 정한다. Step 7에서 받은 `page_list.html`과 상세 화면 하나를 파일로 저장해 검수한다.

- `Skill({"skill": "hallmark"})`로 `hallmark audit <파일>`을 돌린다. `audit`은 읽기 전용이다 — hallmark가 파일을 고치게 두지 않는다
- 로드는 `references/verbs/audit.md`, `references/anti-patterns.md`, `references/slop-test.md`만 한다
- 판정 기준은 규칙 파일의 **웹 열**이다(웹 UI이므로 모바일 반응형·`:focus-visible`·상호작용 상태가 적용된다)
- 잠긴 브랜드 디자인 시스템은 없다. hallmark가 색·폰트를 바꾸라고 하면 **지적만 기록하고 적용하지 않는다**
- `critical`·`major`가 0이 될 때까지 템플릿(`base.html`·`list.html`·`detail.html`)을 고치고 다시 검수한다. 같은 `critical`이 3회 뒤에도 남으면 멈추고 보고한다
- 고친 뒤에는 Step 6의 전체 검사를 다시 돌린다

보고에 다음 세 줄을 넣는다:

```
hallmark 검수: critical 0 · major 0 · minor N (면제 M건 제외)
수정 반영: <무엇을 고쳤는지 한 줄>
남은 minor: <항목>
```

- [ ] **Step 9: 커밋**

```bash
git add nara/cli.py README.md tests/test_web.py nara/web/templates
git commit -m "feat: nara serve — 이 컴퓨터에서만 열리는 읽기 전용 조회 화면

127.0.0.1에만 묶고 debug를 켜지 않는다. 밖에 열면 3단계 전에 외부에
노출되고, 디버거는 브라우저에서 코드를 실행하게 한다.

DB 파일이 없으면 멈춘다. _open_db는 migrate로 빈 파일을 새로 만들므로
쓰지 않는다 — doctor와 같은 이유다.

README에 serve와, 있던 명령인데 빠져 있던 enrich status를 더했다.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## 스펙 대응

| 스펙 요구 | 작업 |
|---|---|
| 행 = 사업, 가장 최근 공고 하나를 붙임 | Task 3 |
| 진행현황·낙찰업체·실행부서를 붙이는 규칙 | Task 3 |
| 판정 없는 사업은 "판정 전" | Task 3(필터·정렬), Task 6(표시) |
| 기간은 보이는 공고의 공고일로 거름 | Task 3 |
| 기간 조건 시 공고 없는 사업 제외, 건수는 그때 셈 | Task 3, Task 6 |
| 단계별 마지막 실행, 실행 기록 없음 | Task 5, Task 6 |
| 목록 8열, 값 없으면 `—` | Task 6 |
| 조건 여섯(수요기관 다중·관심기관·이름·기간 둘·진행현황) | Task 2, Task 3 |
| 조건끼리 AND, 같은 조건 안은 OR | Task 3 |
| 이름 검색이 공고명·사업명 양쪽, 공고명으로만 걸리면 공고명 표시 | Task 3, Task 6 |
| 검색어 `%`·`_`를 글자 그대로 | Task 3 |
| 잘못된 날짜는 무시하고 적음 | Task 2, Task 6 |
| 정렬 다섯, 기본 공고일 내림차순, 열 머리로 전환·뒤집기 | Task 2, Task 3, Task 6 |
| 진행현황 단계순, 값 없는 행은 맨 뒤, 같으면 id | Task 3 |
| 정렬 허용 목록 밖은 기본값으로 바꾸고 적음 | Task 2 |
| 결과 머리: 건수·조건·제외·1,000건 상한 | Task 3, Task 6 |
| 상세 여섯 묶음, 공고·이력 전부 | Task 4, Task 6 |
| 신재생 예상가(`estimate_cost`)와 빠진 에너지원 | Task 4, Task 6 |
| 판정 주체를 사람이 읽을 말로 | Task 4 |
| 근거 URL은 `evidence_json`의 `url`, 없으면 안 적음 | Task 4 |
| 없는 id는 404 | Task 6 |
| 안전장치: `mode=ro` | Task 1, Task 6 |
| 안전장치: 정렬 허용 목록·자리표시자·`LIKE ESCAPE` | Task 2, Task 3 |
| 안전장치: 자동 이스케이프 | Task 6 |
| 안전장치: `127.0.0.1`에만 묶음 | Task 7 |
| 테스트: 읽기 전용을 앱의 연결로 확인 | Task 6 |
| 테스트: 망에 나가지 않음 | 전 작업(외부 호출 없음) |
| 실행: `nara serve`, `--port`·`--db` | Task 7 |
| 확인할 것: Flask가 3.14에서 설치되는가 | Task 1 Step 1 |

**스펙에 없는데 더한 것:** `data.py`(위 파일 구조 참조), 링크 스킴 제한(`safe_url`), `debug=False`, 서버를 띄운 뒤 DB가 사라진 경우의 503. 앞의 셋은 스펙의 안전장치가 겨냥한 위험을 스펙이 적은 방법만으로는 다 막지 못해서 더했다. 마지막은 "조용히 빠지는 것이 없어야 한다"를 따른 것이다.

**스펙과 어긋난 점 하나:** 스펙의 "원 명세 대비 달라진 점" 표는 수요기관을 "원 명세를 따른다"고 적으면서 원 명세의 **검색**을 빠뜨렸다. 이 계획은 적힌 대로 다중선택만 만든다. 브라우저의 선택 목록은 글자를 치면 그 글자로 시작하는 기관으로 이동하지만, 목록 안에서 걸러 보이는 검색은 아니다. 69곳이라 쓸 만하지만 원 명세와는 다르다.
