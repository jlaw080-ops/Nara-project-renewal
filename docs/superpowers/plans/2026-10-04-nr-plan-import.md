# 신재생에너지센터 설치계획서 가져오기 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 크롬 확장 프로그램이 보낸 설치계획서를 나라 앱이 받아 사업과 짝을 짓고 신재생 계획·일정·주소·실행부서를 채운다. 짝이 없으면 새 사업을 만든다.

**Architecture:** 토큰으로 인증하는 `POST /api/nr-plans`가 행을 받아 `nr_plan` 표에 저장한다. `nara/nr_match.py`(순수 함수)가 기관·건물명·주소로 후보를 매기고, `nara/nr_apply.py`가 연결·새 사업 생성·반영을 맡는다. 사람은 `/nr` 화면에서 애매한 건을 고른다. 에너지원·형식 목록은 코드 상수에서 `energy_kind` 표로 옮겨 새 종류를 단가 없이 받을 수 있게 한다.

**Tech Stack:** Python 3.14, Flask, SQLite(WAL), Typer, pytest, ruff(줄 100자), uv.

**Spec:** `docs/superpowers/specs/2026-10-04-nr-plan-import-design.md`

## Global Constraints

- 작업 공간: `C:/Users/jlaw8/dev/Nara-project-renewal-nr` (브랜치 `feat/nr-plan-import`). 처음 한 번 `uv sync`.
- 테스트 명령: `uv run --no-sync pytest -q -o addopts="" <경로>`. 전체: `uv run --no-sync pytest -q -o addopts=""`.
- 린트: `uv run --no-sync ruff check nara tests && uv run --no-sync ruff format --check nara tests` (줄 100자).
- 저장소가 공개다. 실제 토큰·전화번호·이메일을 코드와 테스트에 넣지 않는다. 테스트 토큰은 `"test-import-token"`, 이메일은 `example.com`.
- 화면 문구·주석·커밋 메시지는 한국어. 기존 코드의 말투(‘-다’ 주석, 짧은 문장)를 따른다.
- 커밋 메시지 끝에 `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- 사람이 웹에서 고친 값(`sheet_memory.edited_on_web`이 True)은 설치계획서가 덮지 않는다.
- 받는 주소 한 번에 200행, 본문 1MB(`1024 * 1024`). 토큰은 `.env`의 `NARA_IMPORT_TOKEN`.
- 짝 찾기 기준: 자동 연결 `≥ 0.8` 이고 2등과 `≥ 0.2` 차이, 새 사업 `< 0.4`, 주소 도로명 일치 `+0.1`.
- `match_state` 값: `pending` · `auto` · `new` · `human` · `ignored`.
- `decided_by`·`entered_by`·`project.source`의 새 값은 모두 `'nr'`.

## Review Focus

1. 설치계획서의 에너지원 표를 못 읽어 `energy`가 빈 배열로 온 경우 — 기존 신재생 계획을 지우지 않아야 한다. (Task 5 `test_an_empty_energy_list_does_not_wipe_the_plan`)
2. 한 사업에 건물 두 개의 설치계획서가 연결된 경우 — 두 계획의 용량을 합쳐 보여야 하고, 나중 것이 앞의 것을 지우면 안 된다. (Task 5 `test_two_buildings_on_one_project_add_up`)
3. 사람이 무시한 설치계획서가 다시 들어온 경우 — 무시가 유지되고 아무 사업에도 반영되지 않아야 한다. (Task 5 `test_an_ignored_plan_stays_ignored_when_sent_again`)
4. 인증 헤더가 `bearer`(소문자)·앞뒤 공백·다른 토큰이거나 본문이 JSON이 아닌 경우 — 401·400으로 거절하고 500이 나면 안 된다. (Task 6 `test_the_token_must_match_exactly`, `test_a_body_that_is_not_json_is_400`)
5. 수집(예약 작업)이 DB를 쓰는 중에 확장 프로그램이 보낸 경우 — 503과 다시 보내라는 메시지를 돌려주고 아무것도 반쯤 쓰지 않아야 한다. (Task 6 `test_a_busy_database_answers_503`)

---

## 파일 구성

| 파일 | 책임 | 작업 |
|---|---|---|
| `nara/schema.sql` | `energy_kind`·`nr_plan` 표 | 수정 |
| `nara/energy.py` | 에너지원·형식 목록 읽기(`load_kinds`), 찾거나 더하기(`kind_for`) | 수정 |
| `nara/config.py` | `Settings.nr_org_aliases`, `Secrets.import_token` | 수정 |
| `nara/cli.py` | `serve`가 토큰·설정을 앱에 넘김 | 수정 |
| `nara/nr_plan.py` | 받은 행 검사(`parse_nr_row`)와 저장(`save_nr_plan`) | 새로 |
| `nara/nr_match.py` | 기관·이름 정규화, 후보 점수, 판정 | 새로 |
| `nara/nr_apply.py` | 받기 흐름(`ingest`), 반영(`apply_plans`), 사람 연결·무시 | 새로 |
| `nara/migrate_sheets.py` | 시트가 설치계획서 신재생 값을 덮지 않게 | 수정 |
| `nara/web/edit.py` | 입력 검사가 DB 목록을 받게 | 수정 |
| `nara/web/data.py` | 단가 목록·설치계획 조회 | 수정 |
| `nara/web/app.py` | 받는 주소, `/nr` 화면, 목록 전달 | 수정 |
| `nara/web/templates/*.html` | `nr_list.html`·`nr_detail.html` 새로, `detail`·`list`·`base`·`prices` 수정 | 수정·새로 |
| `tests/test_nr_plan.py`, `tests/test_nr_match.py`, `tests/test_nr_apply.py`, `tests/test_web_nr.py` | 새 테스트 | 새로 |

---

### Task 1: 에너지원·형식 목록을 `energy_kind` 표로 옮기기

**Files:**
- Modify: `nara/schema.sql`, `nara/energy.py`, `nara/web/edit.py:140-187`, `nara/web/data.py:205-232`, `nara/web/app.py`, `nara/web/templates/detail.html`, `nara/web/templates/prices.html`
- Test: `tests/test_energy.py`, `tests/test_web_edit.py`, `tests/test_web.py`, `tests/test_db.py`

**Interfaces:**
- Produces: `nara.energy.load_kinds(conn: sqlite3.Connection) -> list[EnergyKind]` (sort 순), `nara.energy.kind_for(conn, source: str, form: str) -> EnergyKind` (없으면 단가 없이 추가, 커밋은 호출자), `ENERGY_KINDS`는 시드 상수로 남는다. `kind_of`는 지운다.
- Produces: `edit.check_energy(sources, kinds, capacities, known: Mapping[str, EnergyKind]) -> Checked`, `edit.check_prices(codes, prices, current: Mapping[str, int | None]) -> Checked`.

- [ ] **Step 1: 실패하는 테스트 쓰기**

`tests/test_db.py`의 `EXPECTED_TABLES`에 `"energy_kind",`를 더한다.

`tests/test_energy.py` — import 줄을 바꾸고 `test_kind_of_names_the_source_and_form_of_a_stored_code`를 지운 뒤 끝에 더한다:

```python
from nara.db import connect, migrate
from nara.energy import (
    ENERGY_KINDS,
    EnergyItem,
    EnergyKind,
    estimate_cost,
    kind_for,
    load_kinds,
    parse_energy_plan,
)


def _db(tmp_path):
    conn = connect(tmp_path / "k.db")
    migrate(conn)
    return conn


def test_load_kinds_starts_with_the_six_sheet_kinds(tmp_path):
    assert load_kinds(_db(tmp_path)) == list(ENERGY_KINDS)


def test_kind_for_reads_the_sheet_wording_of_an_existing_kind(tmp_path):
    """설치계획서는 PV를 '태양광 고정식'으로 적는다. 새 종류로 만들면 단가가 빠진다."""
    conn = _db(tmp_path)
    assert kind_for(conn, "태양광", "고정식").code == "PV"
    assert kind_for(conn, "지열", "수직밀폐형").code == "지열"
    assert len(load_kinds(conn)) == 6


def test_kind_for_adds_an_unknown_kind_without_a_price(tmp_path):
    conn = _db(tmp_path)
    kind = kind_for(conn, "태양열", "평판형")
    assert kind == EnergyKind("태양열", "평판형", "태양열 평판형")
    assert load_kinds(conn)[-1] == kind
    price = conn.execute(
        "SELECT 1 FROM energy_unit_price WHERE source_type = ?", (kind.code,)
    ).fetchone()
    assert price is None
    assert kind_for(conn, "태양열", "평판형") == kind
    assert len(load_kinds(conn)) == 7


def test_kind_for_does_not_read_another_solar_form_as_pv(tmp_path):
    """'태양광'만 보고 PV로 읽으면 추적식에 고정식 단가가 붙는다."""
    assert kind_for(_db(tmp_path), "태양광", "추적식").code == "태양광 추적식"
```

`tests/test_web_edit.py` — check 함수 테스트를 새 서명으로 바꾼다. 기존 `check_energy(...)` 호출 네 곳에 마지막 인자 `KNOWN`을, `check_prices(...)` 두 곳에 `CURRENT_PRICES`를 넘기고 아래를 더한다:

```python
from nara.energy import ENERGY_KINDS, EnergyItem

KNOWN = {k.code: k for k in ENERGY_KINDS}
CURRENT_PRICES = {
    "BIPV": 5_000_000, "PV": 2_500_000, "집광채광": 1_000_000,
    "지열": 2_500_000, "PEMFC": 32_000_000, "SOFC": 98_250_000,
}  # fmt: skip


def test_check_energy_accepts_a_kind_added_from_an_installation_plan():
    known = {**KNOWN, "태양열 평판형": EnergyKind("태양열", "평판형", "태양열 평판형")}
    checked = check_energy(["태양열"], ["태양열 평판형"], ["12"], known)
    assert checked.values["items"] == [EnergyItem("태양열 평판형", 12.0)]


def test_check_prices_lets_a_new_kind_stay_unpriced():
    """단가 없는 새 종류 때문에 다른 단가를 저장하지 못하면 안 된다."""
    current = {**CURRENT_PRICES, "태양열 평판형": None}
    checked = check_prices(["PV", "태양열 평판형"], ["2,600,000", ""], current)
    assert checked.ok
    assert checked.values["prices"] == {"PV": 2_600_000}
```

(`EnergyKind`도 `nara.energy`에서 import 한다.) `test_check_prices_rejects_blank_fractional_and_unknown`의 기대값은 그대로다 — PV는 단가가 있으므로 빈칸이 오류다.

`tests/test_web.py`에 더한다:

```python
def _add_kind(path, source, form):
    conn = connect(path)
    from nara.energy import kind_for

    kind_for(conn, source, form)
    conn.commit()
    conn.close()


def test_a_kind_added_later_shows_in_the_form_and_the_price_page(world):
    path, ids = world
    _add_kind(path, "태양열", "평판형")
    client = _client(path)
    form = _text(client.get(f"/project/{ids['gym']}?edit=energy"))
    assert '<option value="태양열">태양열</option>' in form
    assert 'data-source="태양열" data-price="">평판형</option>' in form
    prices = _text(client.get("/prices"))
    assert "<td>태양열</td><td>평판형</td>" in prices
    assert "단가 없음" in prices
```

- [ ] **Step 2: 실패 확인**

Run: `uv run --no-sync pytest -q -o addopts="" tests/test_energy.py tests/test_web_edit.py tests/test_web.py tests/test_db.py`
Expected: 모음 단계 ImportError (`kind_for`·`load_kinds` 없음).

- [ ] **Step 3: 구현**

`nara/schema.sql` — `energy_unit_price` 시드 아래에 더한다:

```sql
-- 입력 화면의 에너지원·형식 목록. 설치계획서에서 새 종류가 오면 단가 없이 더한다.
CREATE TABLE IF NOT EXISTS energy_kind (
  code   TEXT PRIMARY KEY,   -- energy_plan·energy_unit_price의 source_type
  source TEXT NOT NULL,      -- 에너지원
  form   TEXT NOT NULL,      -- 형식
  sort   INTEGER NOT NULL,
  UNIQUE (source, form)
);
INSERT OR IGNORE INTO energy_kind (code, source, form, sort) VALUES
  ('BIPV',     '태양광',   'BIPV',       10),
  ('PV',       '태양광',   'PV',         20),
  ('집광채광', '태양광',   '집광채광',   30),
  ('지열',     '지열',     '수직밀폐형', 40),
  ('PEMFC',    '연료전지', 'PEMFC',      50),
  ('SOFC',     '연료전지', 'SOFC',       60);
```

`nara/energy.py` — `import sqlite3`을 더하고, `_BY_CODE`와 `kind_of`를 지운 뒤 `_ALIASES` 정의 **아래**에 더한다. `ENERGY_KINDS` 주석은 "처음 목록(시드). 실제 목록은 energy_kind 표다."로 바꾼다.

```python
_ALIAS_CODES = dict(_ALIASES)


def _kind(row: sqlite3.Row) -> EnergyKind:
    return EnergyKind(row["source"], row["form"], row["code"])


def load_kinds(conn: sqlite3.Connection) -> list[EnergyKind]:
    rows = conn.execute("SELECT code, source, form FROM energy_kind ORDER BY sort, code")
    return [_kind(r) for r in rows]


def kind_for(conn: sqlite3.Connection, source: str, form: str) -> EnergyKind:
    """(에너지원, 형식)의 종류. 목록에 없으면 단가 없이 더한다. 커밋은 부른 쪽이 한다.

    시트 표기('태양광 고정식')는 정확히 같을 때만 기존 종류로 읽는다 —
    '태양광'만 보고 PV로 읽으면 추적식 같은 다른 형식에 PV 단가가 붙는다.
    """
    source, form = source.strip(), form.strip()
    row = conn.execute(
        "SELECT code, source, form FROM energy_kind WHERE source = ? AND form = ?", (source, form)
    ).fetchone()
    if row is None and (alias := _ALIAS_CODES.get(f"{source} {form}")):
        row = conn.execute(
            "SELECT code, source, form FROM energy_kind WHERE code = ?", (alias,)
        ).fetchone()
    if row is not None:
        return _kind(row)
    code = f"{source} {form}".strip()
    sort = conn.execute("SELECT COALESCE(MAX(sort), 0) + 10 FROM energy_kind").fetchone()[0]
    conn.execute(
        "INSERT OR IGNORE INTO energy_kind (code, source, form, sort) VALUES (?, ?, ?, ?)",
        (code, source, form, sort),
    )
    return EnergyKind(source, form, code)
```

`nara/web/edit.py` — `from nara.energy import EnergyItem, kind_of`를 `from nara.energy import EnergyItem, EnergyKind`로 바꾸고 두 함수를 바꾼다:

```python
def check_energy(
    sources: list[str], kinds: list[str], capacities: list[str], known: Mapping[str, EnergyKind]
) -> Checked:
    """줄마다 에너지원·형식·용량. 셋 다 빈 줄은 건너뛴다 — 빈 줄로 줄을 지운다.

    형식(kinds)의 값은 저장할 이름(PV 등)이다. known(energy_kind 표)에 있고
    고른 에너지원의 형식이어야 한다.
    """
    items: list[EnergyItem] = []
    errors: dict[str, str] = {}
    seen: set[str] = set()
    rows = zip_longest(sources, kinds, capacities, fillvalue="")
    for i, (raw_source, raw_kind, raw_capacity) in enumerate(rows):
        source, code, capacity_text = raw_source.strip(), raw_kind.strip(), raw_capacity.strip()
        if not source and not code and not capacity_text:
            continue
        if not source:
            errors[f"source-{i}"] = "에너지원을 고르세요"
            continue
        kind = known.get(code)
        if kind is None or kind.source != source:
            errors[f"kind-{i}"] = "형식을 고르세요"
            continue
        if code in seen:
            errors[f"kind-{i}"] = "같은 형식이 두 줄입니다"
            continue
        capacity = _positive(capacity_text, errors, f"capacity-{i}")
        if capacity is None:
            errors.setdefault(f"capacity-{i}", "0보다 큰 숫자로 적으세요")
            continue
        seen.add(code)
        items.append(EnergyItem(code, capacity))
    return Checked({"items": items}, errors)


def check_prices(
    codes: list[str], prices: list[str], current: Mapping[str, int | None]
) -> Checked:
    """단가(원/kW). 1 이상의 정수. 아직 단가가 없는 종류는 비워 둘 수 있다."""
    values: dict[str, int] = {}
    errors: dict[str, str] = {}
    for code, raw in zip_longest(codes, prices, fillvalue=""):
        if code not in current:
            errors["_form"] = "모르는 에너지원이 있습니다"
            continue
        text = raw.strip().replace(",", "")
        if not text and current[code] is None:
            continue
        if not text.isdigit() or int(text) < 1:
            errors[f"price-{code}"] = "1 이상의 정수로 적으세요"
            continue
        values[code] = int(text)
    return Checked({"prices": values}, errors)
```

`nara/web/data.py` — import를 `from nara.energy import EnergyItem, EnergyKind, estimate_cost, load_kinds`로 바꾸고 `unit_prices`의 `for kind in ENERGY_KINDS:`를 `for kind in load_kinds(conn):`로 바꾼다.

`nara/web/app.py`:
- import를 `from nara.energy import EnergyKind, load_kinds`로 바꾼다. `ENERGY_SOURCES` 상수와 `add_template_global` 두 줄을 지운다.
- 헬퍼를 더한다:

```python
def _kinds() -> dict[str, EnergyKind]:
    """이 요청의 에너지원·형식 목록. 순서를 지킨다(dict는 넣은 순서)."""
    return {k.code: k for k in load_kinds(get_conn())}
```

- `_check`의 마지막 줄: `return edit.check_energy(form.getlist("source"), form.getlist("kind"), form.getlist("capacity"), _kinds())`
- `_energy_rows`의 `kind = kind_of(e.source_type)`를 `kind = known.get(e.source_type)`로 바꾸고, 함수 첫 줄에 `known = _kinds()`를 둔다.
- `_render_detail`의 `energy_sources=ENERGY_SOURCES,` 자리에:

```python
            energy_kinds=list(_kinds().values()),
            kinds_by_code=_kinds(),
            energy_sources=list(dict.fromkeys(k.source for k in _kinds().values())),
```

- `prices()`의 `edit.check_prices(form.getlist("code"), form.getlist("price"))`를 `edit.check_prices(form.getlist("code"), form.getlist("price"), {r.kind.code: r.price for r in rows})`로 바꾼다.

`nara/web/templates/detail.html` — 신재생 표의 `{% set k = kind_of(e.source_type) %}`를 `{% set k = kinds_by_code.get(e.source_type) %}`로 바꾼다. (`energy_kinds`·`energy_sources`는 같은 이름으로 넘어오므로 폼은 그대로다.)

`nara/web/templates/prices.html` — 단가 입력 칸 뒤, 오류 표시 앞에 `{% if r.price is none %} <span class="muted">단가 없음</span>{% endif %}`를 더한다.

- [ ] **Step 4: 통과 확인**

Run: `uv run --no-sync pytest -q -o addopts=""`
Expected: 전부 통과. `grep -rn "kind_of\|ENERGY_SOURCES" nara/web`가 아무것도 찾지 않는다(`nara/doctext.py`의 `kind_of`는 다른 함수다).

- [ ] **Step 5: 커밋**

```bash
git add nara/schema.sql nara/energy.py nara/web tests
git commit -m "refactor: 에너지원·형식 목록을 energy_kind 표로 옮긴다

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: 토큰·기관 별칭 설정을 앱까지 잇기

**Files:**
- Modify: `nara/config.py`, `nara/cli.py:130-160,184-187`, `nara/web/app.py` (`create_app`)
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `Secrets.import_token: str | None` (`.env`의 `NARA_IMPORT_TOKEN`), `Settings.nr_org_aliases: tuple[tuple[str, str], ...]` (`config.toml`의 `[nr.org_aliases]` 표), `create_app(db_path, secret_key, host=None, lan_hosts=(), import_token=None, settings=None)` → `app.config["IMPORT_TOKEN"]`, `app.config["SETTINGS"]`.

- [ ] **Step 1: 실패하는 테스트 쓰기** (`tests/test_config.py` 끝)

```python
def test_load_secrets_reads_the_import_token(tmp_path):
    env = tmp_path / ".env"
    env.write_text("NARA_IMPORT_TOKEN=test-import-token\n", encoding="utf-8")
    assert load_secrets(env).import_token == "test-import-token"


def test_load_settings_reads_org_aliases_for_installation_plans(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text(
        (REPO_ROOT / "config.toml").read_text(encoding="utf-8")
        + '\n[nr.org_aliases]\n"전라북도교육청" = "전북특별자치도교육청"\n',
        encoding="utf-8",
    )
    settings = load_settings(config)
    assert settings.nr_org_aliases == (("전라북도교육청", "전북특별자치도교육청"),)


def test_load_settings_has_no_org_aliases_by_default():
    assert load_settings(REPO_ROOT / "config.toml").nr_org_aliases == ()
```

- [ ] **Step 2: 실패 확인**

Run: `uv run --no-sync pytest -q -o addopts="" tests/test_config.py`
Expected: FAIL — `AttributeError: 'Secrets' object has no attribute 'import_token'`.

- [ ] **Step 3: 구현**

`nara/config.py`:
- `Settings`에 마지막 칸 `nr_org_aliases: tuple[tuple[str, str], ...] = ()` (주석: `# 설치계획서 기관명 → 나라 앱 기관명. 자동 규칙으로 안 되는 것만`).
- `load_settings`의 `Settings(...)`에 `nr_org_aliases=tuple(data.get("nr", {}).get("org_aliases", {}).items()),`.
- `Secrets`에 `import_token: str | None = None`, `load_secrets`에 `import_token=pick("NARA_IMPORT_TOKEN"),`.

`nara/web/app.py` `create_app` 서명 끝에 `import_token: str | None = None, settings: Settings | None = None,`를 더하고(`from nara.config import Settings`), `app.config["WRITE_TIMEOUT"] = ...` 아래에:

```python
    # 확장 프로그램이 설치계획서를 보내는 주소용. 토큰이 없으면 그 주소를 끈다.
    app.config["IMPORT_TOKEN"] = import_token
    app.config["SETTINGS"] = settings
```

`nara/cli.py`:
- `serve`에 옵션 `config: Path = typer.Option(DEFAULT_CONFIG, help="설정 파일"),`를 더하고, `migrate` 뒤에 `settings = load_settings(config)`.
- `create_app(db, secret_key=secrets.secret_key, host=secrets.host)`을 `create_app(db, secret_key=secrets.secret_key, host=secrets.host, import_token=secrets.import_token, settings=settings)`로.
- `_serve_lan(db, secrets.secret_key, secrets.host, port)`를 `_serve_lan(db, secrets, settings, port)`로 바꾸고, `_serve_lan`을:

```python
def _serve_lan(db: Path, secrets: Secrets, settings: Settings, port: int) -> None:
    primary, hosts = _lan_addresses()
    web = create_app(
        db,
        secret_key=secrets.secret_key,
        host=secrets.host,
        lan_hosts=hosts,
        import_token=secrets.import_token,
        settings=settings,
    )
```

(`Secrets`·`Settings`를 `nara.config`에서 import. 이미 다른 import가 있으면 그 줄에 더한다.)

- [ ] **Step 4: 통과 확인**

Run: `uv run --no-sync pytest -q -o addopts="" tests/test_config.py tests/test_web.py tests/test_cli.py`
Expected: 전부 통과 (`serve` 테스트는 `Flask.run`을 막아 두었으므로 그대로 돈다).

- [ ] **Step 5: 커밋**

```bash
git add nara/config.py nara/cli.py nara/web/app.py tests/test_config.py
git commit -m "feat: 설치계획서 받기용 토큰·기관 별칭 설정을 앱에 잇는다

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: 받은 행 검사와 `nr_plan` 저장

**Files:**
- Create: `nara/nr_plan.py`, `tests/test_nr_plan.py`
- Modify: `nara/schema.sql`, `tests/test_db.py` (`EXPECTED_TABLES`에 `"nr_plan",`)

**Interfaces:**
- Produces: `NrEnergy(source: str, form: str, capacity_kw: float)`, `NrRow(key, org, name, addr, start: str | None, end: str | None, dept, energy: tuple[NrEnergy, ...])`, `parse_nr_row(raw: object) -> NrRow | str`(문자열이면 오류 사유), `save_nr_plan(conn, row: NrRow, now: str) -> tuple[int, str]`(`created`·`updated`·`unchanged`, 커밋은 호출자), `load_energy(text: str | None) -> tuple[NrEnergy, ...]`.

- [ ] **Step 1: 실패하는 테스트 쓰기** (`tests/test_nr_plan.py`)

```python
"""설치계획서 받은 행 — 검사와 저장."""

import pytest

from nara.db import connect, migrate
from nara.nr_plan import NrEnergy, NrRow, load_energy, parse_nr_row, save_nr_plan

NOW = "2026-10-04T09:00:00"
RAW = {
    "key": "2026-001",
    "org": "전라북도 완주군",
    "name": "완주 다목적체육관",
    "addr": "전북특별자치도 완주군 봉동읍 완주로 1",
    "start": "2027-03-01",
    "end": "2028-06-30",
    "dept": "체육진흥과",
    "energy": [{"source": "지열", "form": "수직밀폐형", "capacity_kw": 336.06}],
}


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "p.db")
    migrate(c)
    return c


def test_parse_nr_row_reads_a_full_row():
    row = parse_nr_row(RAW)
    assert row == NrRow(
        "2026-001", "전라북도 완주군", "완주 다목적체육관",
        "전북특별자치도 완주군 봉동읍 완주로 1", "2027-03-01", "2028-06-30", "체육진흥과",
        (NrEnergy("지열", "수직밀폐형", 336.06),),
    )  # fmt: skip


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"key": ""}, "key·org·name은 꼭 있어야 합니다"),
        ({"org": None}, "key·org·name은 꼭 있어야 합니다"),
        ({"start": "2027.03.01"}, "착공 날짜는 YYYY-MM-DD로 보내세요: 2027.03.01"),
        ({"end": "2028-02-30"}, "준공 날짜는 YYYY-MM-DD로 보내세요: 2028-02-30"),
        ({"energy": "지열 336"}, "energy는 배열이어야 합니다"),
        ({"energy": [{"source": "지열", "form": "", "capacity_kw": "336"}]},
         "용량은 0보다 큰 수여야 합니다: 지열"),
        ({"energy": [{"source": "지열", "form": "", "capacity_kw": float("nan")}]},
         "용량은 0보다 큰 수여야 합니다: 지열"),
        ({"energy": [{"source": "", "form": "x", "capacity_kw": 1}]}, "energy에 에너지원이 없습니다"),
    ],
)  # fmt: skip
def test_parse_nr_row_names_what_is_wrong(change, reason):
    assert parse_nr_row({**RAW, **change}) == reason


def test_parse_nr_row_refuses_a_non_object():
    assert parse_nr_row(["2026-001"]) == "행은 객체여야 합니다"


def test_parse_nr_row_cuts_long_text_and_allows_missing_dates():
    row = parse_nr_row({**RAW, "name": "가" * 500, "start": "", "end": None, "energy": None})
    assert len(row.name) == 200
    assert (row.start, row.end, row.energy) == (None, None, ())


def test_save_nr_plan_creates_then_reports_unchanged_then_updates(conn):
    row = parse_nr_row(RAW)
    plan_id, saved = save_nr_plan(conn, row, NOW)
    assert saved == "created"
    assert save_nr_plan(conn, row, "2026-10-05T09:00:00") == (plan_id, "unchanged")
    changed = parse_nr_row({**RAW, "end": "2028-12-31"})
    assert save_nr_plan(conn, changed, "2026-10-06T09:00:00") == (plan_id, "updated")
    stored = conn.execute("SELECT * FROM nr_plan").fetchall()
    assert len(stored) == 1
    assert stored[0]["end_date"] == "2028-12-31"
    assert stored[0]["received_at"] == NOW
    assert stored[0]["updated_at"] == "2026-10-06T09:00:00"
    assert stored[0]["match_state"] == "pending"
    assert load_energy(stored[0]["energy_json"]) == (NrEnergy("지열", "수직밀폐형", 336.06),)
```

- [ ] **Step 2: 실패 확인**

Run: `uv run --no-sync pytest -q -o addopts="" tests/test_nr_plan.py`
Expected: ImportError (`nara.nr_plan` 없음).

- [ ] **Step 3: 구현**

`nara/schema.sql` 끝에:

```sql
-- 신재생에너지센터 설치계획서. 크롬 확장 프로그램이 보낸 원문을 신청번호(key)마다 한 줄로 둔다.
CREATE TABLE IF NOT EXISTS nr_plan (
  id            INTEGER PRIMARY KEY,
  key           TEXT NOT NULL UNIQUE,              -- 신청번호, 작성중이면 기관명+건물명
  org_name      TEXT NOT NULL,
  building_name TEXT NOT NULL,
  address       TEXT,
  start_date    TEXT,
  end_date      TEXT,
  dept          TEXT,                              -- 의무기관 담당자 부서
  energy_json   TEXT NOT NULL DEFAULT '[]',        -- [{source, form, capacity_kw}]
  received_at   TEXT NOT NULL,
  updated_at    TEXT NOT NULL,
  project_id    INTEGER REFERENCES project(id),
  match_state   TEXT NOT NULL DEFAULT 'pending',   -- pending|auto|new|human|ignored
  match_score   REAL,
  skipped       TEXT                               -- 웹 수정 때문에 반영하지 않은 칸, 쉼표로
);
CREATE INDEX IF NOT EXISTS idx_nr_plan_project ON nr_plan(project_id);
```

`nara/nr_plan.py`:

```python
"""신재생에너지센터 설치계획서 — 받은 행 검사와 저장. 짝 찾기·반영은 nr_apply가 한다."""

import json
import math
import sqlite3
from dataclasses import dataclass
from datetime import date

TEXT_LIMIT = 200


@dataclass(frozen=True)
class NrEnergy:
    source: str
    form: str
    capacity_kw: float


@dataclass(frozen=True)
class NrRow:
    key: str
    org: str
    name: str
    addr: str
    start: str | None
    end: str | None
    dept: str
    energy: tuple[NrEnergy, ...]


def _text(raw: object) -> str:
    return raw.strip()[:TEXT_LIMIT] if isinstance(raw, str) else ""


def _iso(raw: object, label: str) -> str | None:
    """'YYYY-MM-DD'이고 실제로 있는 날짜만. date.fromisoformat은 '20270301'도 받는다."""
    text = _text(raw)
    if not text:
        return None
    try:
        if len(text) != 10:
            raise ValueError
        return date.fromisoformat(text).isoformat()
    except ValueError:
        raise ValueError(f"{label} 날짜는 YYYY-MM-DD로 보내세요: {text}") from None


def _energy(raw: object) -> tuple[NrEnergy, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ValueError("energy는 배열이어야 합니다")
    out = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("energy 항목은 객체여야 합니다")
        source, form = _text(item.get("source")), _text(item.get("form"))
        if not source:
            raise ValueError("energy에 에너지원이 없습니다")
        cap = item.get("capacity_kw")
        # bool은 int의 하위형이라 True가 1로 들어온다. 문자열 '336'도 받지 않는다.
        if isinstance(cap, bool) or not isinstance(cap, int | float):
            cap = math.nan
        if not math.isfinite(cap) or cap <= 0:
            raise ValueError(f"용량은 0보다 큰 수여야 합니다: {source} {form}".rstrip())
        out.append(NrEnergy(source, form, float(cap)))
    return tuple(out)


def parse_nr_row(raw: object) -> NrRow | str:
    """받은 행 하나. 못 쓰면 이유 문자열을 돌려준다 — 그 행만 버리고 나머지는 받는다."""
    if not isinstance(raw, dict):
        return "행은 객체여야 합니다"
    key, org, name = _text(raw.get("key")), _text(raw.get("org")), _text(raw.get("name"))
    if not key or not org or not name:
        return "key·org·name은 꼭 있어야 합니다"
    try:
        return NrRow(
            key,
            org,
            name,
            _text(raw.get("addr")),
            _iso(raw.get("start"), "착공"),
            _iso(raw.get("end"), "준공"),
            _text(raw.get("dept")),
            _energy(raw.get("energy")),
        )
    except ValueError as exc:
        return str(exc)


def energy_json(energy: tuple[NrEnergy, ...]) -> str:
    items = [{"source": e.source, "form": e.form, "capacity_kw": e.capacity_kw} for e in energy]
    return json.dumps(items, ensure_ascii=False)


def load_energy(text: str | None) -> tuple[NrEnergy, ...]:
    return tuple(
        NrEnergy(d["source"], d["form"], float(d["capacity_kw"])) for d in json.loads(text or "[]")
    )


_FIELDS = (
    "org_name", "building_name", "address", "start_date", "end_date", "dept", "energy_json",
)  # fmt: skip


def _values(row: NrRow) -> tuple:
    return (row.org, row.name, row.addr, row.start, row.end, row.dept, energy_json(row.energy))


def save_nr_plan(conn: sqlite3.Connection, row: NrRow, now: str) -> tuple[int, str]:
    """key마다 한 줄. 같은 값이 다시 오면 손대지 않는다. 커밋은 부른 쪽이 한다."""
    cols = ", ".join(_FIELDS)
    old = conn.execute(f"SELECT id, {cols} FROM nr_plan WHERE key = ?", (row.key,)).fetchone()
    values = _values(row)
    if old is None:
        cursor = conn.execute(
            f"INSERT INTO nr_plan (key, {cols}, received_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (row.key, *values, now, now),
        )
        return cursor.lastrowid, "created"
    if tuple(old[f] for f in _FIELDS) == values:
        return old["id"], "unchanged"
    sets = ", ".join(f"{f} = ?" for f in _FIELDS)
    conn.execute(
        f"UPDATE nr_plan SET {sets}, updated_at = ? WHERE id = ?", (*values, now, old["id"])
    )
    return old["id"], "updated"
```

- [ ] **Step 4: 통과 확인**

Run: `uv run --no-sync pytest -q -o addopts="" tests/test_nr_plan.py tests/test_db.py`
Expected: 전부 통과.

- [ ] **Step 5: 커밋**

```bash
git add nara/schema.sql nara/nr_plan.py tests/test_nr_plan.py tests/test_db.py
git commit -m "feat: 설치계획서 행을 검사해 nr_plan에 저장한다

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: 짝 찾기 (`nara/nr_match.py`)

**Files:**
- Create: `nara/nr_match.py`, `tests/test_nr_match.py`

**Interfaces:**
- Produces: `canonical_org(name: str, aliases: Mapping[str, str] | None = None) -> str`, `org_key(name, aliases=None) -> str`, `name_key(name: str, org_name: str = "") -> str`, `name_score(a: str, b: str) -> float`, `Candidate(project_id: int, name: str, org_name: str, score: float)`, `candidates(conn, org: str, name: str, addr: str, aliases=None, limit=5) -> list[Candidate]`, `Decision(state: str, project_id: int | None, score: float | None)`, `decide(cands: list[Candidate]) -> Decision`. 상수 `AUTO_SCORE = 0.8`, `AUTO_MARGIN = 0.2`, `NEW_BELOW = 0.4`, `ADDRESS_BONUS = 0.1`.

- [ ] **Step 1: 실패하는 테스트 쓰기** (`tests/test_nr_match.py`)

```python
"""설치계획서 ↔ 사업 짝 찾기."""

from pathlib import Path

import pytest

from nara.config import load_settings
from nara.db import connect, migrate
from nara.nr_match import (
    Candidate,
    Decision,
    candidates,
    canonical_org,
    decide,
    name_key,
    name_score,
    org_key,
)
from nara.store import ensure_project, upsert_org

SETTINGS = load_settings(Path(__file__).resolve().parents[1] / "config.toml")
NOW = "2026-10-04T09:00:00"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("전라북도 완주군", "전북특별자치도 완주군"),
        ("강원도 강릉시", "강원특별자치도 강릉시"),
        ("제주도 서귀포시", "제주특별자치도 서귀포시"),
        ("서울특별시 서초구청", "서울특별시 서초구"),
        ("부산광역시청", "부산광역시"),
        ("  경기도   수원시 ", "경기도 수원시"),
        ("강원도교육청", "강원특별자치도교육청"),
        ("전북특별자치도 완주군", "전북특별자치도 완주군"),
    ],
)
def test_canonical_org_follows_renamed_regions_and_drops_the_office_suffix(raw, expected):
    assert canonical_org(raw) == expected


def test_canonical_org_prefers_a_configured_alias():
    aliases = {"전라북도교육청": "전북특별자치도교육청"}
    assert canonical_org("전라북도교육청", aliases) == "전북특별자치도교육청"


def test_org_key_ignores_spaces():
    assert org_key("서울특별시 서초구청") == org_key("서울특별시서초구")


@pytest.mark.parametrize(
    ("name", "org", "expected"),
    [
        ("완주군 다목적체육관 건립 설계용역", "전북특별자치도 완주군", "다목적체육관"),
        ("완주 다목적체육관", "전라북도 완주군", "다목적체육관"),
        ("[수의시담] 서초 청소년센터 신축공사 설계공모", "서울특별시 서초구", "청소년센터"),
        ("공공도서관", "", "공공도서관"),
    ],
)
def test_name_key_drops_procurement_words_and_the_town_name(name, org, expected):
    assert name_key(name, org) == expected


def test_name_score_ranks_equal_contained_and_unrelated_names():
    assert name_score("다목적체육관", "다목적체육관") == 1.0
    assert name_score("봉동다목적체육관", "다목적체육관") == 0.9
    assert name_score("다목적체육관", "공공도서관") < 0.4
    assert name_score("", "다목적체육관") == 0.0


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "m.db")
    migrate(c)
    return c


def _project(conn, org, name, address=None):
    org_id = upsert_org(conn, org, SETTINGS, NOW)
    pid = ensure_project(conn, org_id, name, "g2b", NOW)
    conn.execute("UPDATE project SET address = ? WHERE id = ?", (address, pid))
    conn.commit()
    return pid


def test_candidates_find_the_project_under_the_renamed_org(conn):
    gym = _project(conn, "전북특별자치도 완주군", "완주군 다목적체육관 건립 설계용역")
    _project(conn, "전북특별자치도 완주군", "완주군 공공도서관 건립 설계용역")
    _project(conn, "경기도 수원시", "수원 다목적체육관 설계용역")
    found = candidates(conn, "전라북도 완주군", "완주 다목적체육관", "")
    assert found[0] == Candidate(gym, "완주군 다목적체육관 건립 설계용역", "전북특별자치도 완주군", 1.0)
    assert all(c.org_name == "전북특별자치도 완주군" for c in found)


def test_a_matching_road_name_adds_to_the_score(conn):
    _project(conn, "서울특별시 서초구", "서초 복합문화센터 설계용역", "서울특별시 서초구 반포대로 10")
    plain = candidates(conn, "서울특별시 서초구청", "서초 문화센터", "")[0].score
    road = candidates(conn, "서울특별시 서초구청", "서초 문화센터", "서초구 반포대로 12")[0].score
    assert road == pytest.approx(min(1.0, plain + 0.1))


def test_decide_links_only_a_clear_winner():
    assert decide([Candidate(1, "a", "o", 0.9), Candidate(2, "b", "o", 0.5)]) == Decision(
        "auto", 1, 0.9
    )
    assert decide([Candidate(1, "a", "o", 0.9), Candidate(2, "b", "o", 0.8)]).state == "pending"
    assert decide([Candidate(1, "a", "o", 0.6)]).state == "pending"
    assert decide([Candidate(1, "a", "o", 0.3)]) == Decision("new", None, 0.3)
    assert decide([]) == Decision("new", None, None)
```

- [ ] **Step 2: 실패 확인**

Run: `uv run --no-sync pytest -q -o addopts="" tests/test_nr_match.py`
Expected: ImportError.

- [ ] **Step 3: 구현** (`nara/nr_match.py`)

```python
"""설치계획서와 사업의 짝 찾기. DB는 후보를 읽을 때만 쓴다.

기준 값은 실제 설치계획서로 만든 정답표(tests/fixtures/nr_answer_key.json)로 맞춘다.
"""

import re
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass

AUTO_SCORE = 0.8
AUTO_MARGIN = 0.2
NEW_BELOW = 0.4
ADDRESS_BONUS = 0.1

# 2023~2024년에 이름이 바뀐 광역 지자체. 설치계획서 기관명에는 옛 이름이 남아 있다
# (실측: 관심기관 71곳 중 이름이 같은 곳 16곳 — '전라북도 완주군', '강원도 강릉시').
_REGION_RENAMES = (
    ("전라북도", "전북특별자치도"),
    ("강원도", "강원특별자치도"),
    ("제주도", "제주특별자치도"),
)
# '서초구청'·'부산광역시청'의 '청'. '교육청'은 앞 글자가 시·군·구가 아니라 남는다.
_OFFICE = re.compile(r"(?<=[시군구])청$")
_BRACKET = re.compile(r"[\[(（【][^\])）】]*[\])）】]")
# 사업명(공고명)에 붙는 조달·공사 낱말. 여기서부터 뒤를 버린다.
_CUT = ("설계", "용역", "공모", "공고", "입찰", "건립", "신축", "증축", "리모델링", "공사", "사업")
_PUNCT = re.compile(r"[\s·,.\-_/]")
_ROAD = re.compile(r"\S+(?:로|길)(?=\s|\d|$)")


def canonical_org(name: str, aliases: Mapping[str, str] | None = None) -> str:
    text = " ".join((name or "").split())
    if aliases and text in aliases:
        return aliases[text]
    for old, new in _REGION_RENAMES:
        if text.startswith(old):
            text = new + text[len(old) :]
            break
    return _OFFICE.sub("", text)


def org_key(name: str, aliases: Mapping[str, str] | None = None) -> str:
    return canonical_org(name, aliases).replace(" ", "")


def name_key(name: str, org_name: str = "") -> str:
    """비교용 이름. 조달 낱말 뒤를 자르고 맨 앞의 시·군·구 이름을 뗀다.

    '완주군 다목적체육관 건립 설계용역'과 '완주 다목적체육관'이 둘 다 '다목적체육관'이 된다.
    """
    text = _BRACKET.sub(" ", name or "")
    cut = min((i for m in _CUT if (i := text.find(m)) > 0), default=-1)
    if cut > 0:
        text = text[:cut]
    words = text.split()
    org_words = canonical_org(org_name).split()
    town = org_words[-1] if org_words else ""
    stem = town[:-1] if len(town) > 2 and town[-1] in "시군구" else town
    if len(words) > 1 and town and words[0] in (town, stem):
        words = words[1:]
    key = _PUNCT.sub("", "".join(words))
    return key if len(key) >= 2 else _PUNCT.sub("", _BRACKET.sub("", name or ""))


def _bigrams(text: str) -> set[str]:
    return {text[i : i + 2] for i in range(len(text) - 1)} or {text}


def name_score(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if min(len(a), len(b)) >= 4 and (a in b or b in a):
        return 0.9
    x, y = _bigrams(a), _bigrams(b)
    return len(x & y) / len(x | y)


def same_road(a: str | None, b: str | None) -> bool:
    return bool(set(_ROAD.findall(a or "")) & set(_ROAD.findall(b or "")))


@dataclass(frozen=True)
class Candidate:
    project_id: int
    name: str
    org_name: str
    score: float


@dataclass(frozen=True)
class Decision:
    state: str  # auto | new | pending
    project_id: int | None
    score: float | None


def candidates(
    conn: sqlite3.Connection,
    org: str,
    name: str,
    addr: str,
    aliases: Mapping[str, str] | None = None,
    limit: int = 5,
) -> list[Candidate]:
    """같은 기관(정규화 뒤)의 사업을 점수 순으로. 숨긴 사업도 넣는다."""
    key = org_key(org, aliases)
    orgs = {
        r["id"]: r["name"]
        for r in conn.execute("SELECT id, name FROM org")
        if org_key(r["name"], aliases) == key
    }
    if not orgs:
        return []
    mine = name_key(name, org)
    marks = ", ".join("?" * len(orgs))
    rows = conn.execute(
        f"SELECT id, org_id, name, address FROM project WHERE org_id IN ({marks})", list(orgs)
    ).fetchall()
    found = []
    for r in rows:
        score = name_score(mine, name_key(r["name"], orgs[r["org_id"]]))
        if score > 0 and same_road(addr, r["address"]):
            score = min(1.0, score + ADDRESS_BONUS)
        found.append(Candidate(r["id"], r["name"], orgs[r["org_id"]], round(score, 3)))
    found.sort(key=lambda c: (-c.score, c.project_id))
    return found[:limit]


def decide(cands: list[Candidate]) -> Decision:
    if not cands or cands[0].score < NEW_BELOW:
        return Decision("new", None, cands[0].score if cands else None)
    top = cands[0]
    second = cands[1].score if len(cands) > 1 else 0.0
    if top.score >= AUTO_SCORE and top.score - second >= AUTO_MARGIN:
        return Decision("auto", top.project_id, top.score)
    return Decision("pending", None, top.score)
```

- [ ] **Step 4: 통과 확인**

Run: `uv run --no-sync pytest -q -o addopts="" tests/test_nr_match.py`
Expected: 전부 통과. 실패하는 이름 사례가 있으면 테스트 기대값이 아니라 정규화 규칙을 고친다. 규칙을 바꿨으면 ledger에 Ruling으로 남긴다.

- [ ] **Step 5: 커밋**

```bash
git add nara/nr_match.py tests/test_nr_match.py
git commit -m "feat: 설치계획서와 사업의 짝을 기관·이름·도로명으로 찾는다

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: 받기 흐름과 반영 (`nara/nr_apply.py`)

**Files:**
- Create: `nara/nr_apply.py`, `tests/test_nr_apply.py`
- Modify: `nara/migrate_sheets.py:204-237` (`_apply_energy`), `tests/test_migrate_sheets.py`

**Interfaces:**
- Consumes: `parse_nr_row`, `save_nr_plan`, `load_energy` (Task 3); `candidates`, `decide`, `canonical_org`, `org_key` (Task 4); `kind_for` (Task 1); `Settings.nr_org_aliases` (Task 2); `nara.runlog.RunCounters`.
- Produces: `RowResult(key: str, saved: str, match: str | None = None, project_id: int | None = None, error: str | None = None)`; `ingest(conn, raw_rows: list, settings: Settings, now: str, counters: RunCounters | None = None) -> list[RowResult]` (`saved`는 `created|updated|unchanged|invalid`, `match`는 `linked|new_project|pending|ignored`); `apply_plans(conn, project_id: int, now: str) -> list[str]`(건너뛴 칸); `link_plan(conn, plan_id: int, project_id: int | None, settings, now) -> int`(None이면 새 사업, 없는 id면 `LookupError`); `ignore_plan(conn, plan_id: int) -> None`(없으면 `LookupError`). `NR_SNIPPET = "설치계획서 의무기관 담당자 부서"`.

- [ ] **Step 1: 실패하는 테스트 쓰기** (`tests/test_nr_apply.py`)

```python
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
    org = conn.execute("SELECT org_id FROM project WHERE id = ?", (gym,)).fetchone()[0]
    ensure_project(conn, org, "완주군 다목적체육관 리모델링 설계용역", "g2b", NOW)
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
    org = conn.execute("SELECT org_id FROM project WHERE id = ?", (gym,)).fetchone()[0]
    ensure_project(conn, org, "완주군 다목적체육관 리모델링 설계용역", "g2b", NOW)
    ingest(conn, [_row()], SETTINGS, NOW)
    plan = conn.execute("SELECT id FROM nr_plan").fetchone()[0]
    ignore_plan(conn, plan)
    [result] = ingest(conn, [_row(end="2029-01-01")], SETTINGS, LATER)
    assert (result.saved, result.match, result.project_id) == ("updated", "ignored", None)
    assert _energy(conn, gym) == []


def test_a_person_can_link_or_start_a_new_project(db):
    conn, gym = db
    org = conn.execute("SELECT org_id FROM project WHERE id = ?", (gym,)).fetchone()[0]
    ensure_project(conn, org, "완주군 다목적체육관 리모델링 설계용역", "g2b", NOW)
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
    conn, gym = db
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
```

`tests/test_migrate_sheets.py` 끝에(그 파일의 import에 `ImportStats`, `_apply_energy`, `EnergyItem`, `connect`, `migrate`, `upsert_org`, `ensure_project`, `load_settings`가 없으면 더한다):

```python
def test_the_sheet_does_not_overwrite_energy_from_an_installation_plan(tmp_path):
    """설치계획서는 기관이 공단에 낸 공식 자료다. 시트 값이 덮으면 안 된다."""
    conn = connect(tmp_path / "s.db")
    migrate(conn)
    settings = load_settings(Path(__file__).resolve().parents[1] / "config.toml")
    org = upsert_org(conn, "전북특별자치도 완주군", settings, "2026-10-04T09:00:00")
    pid = ensure_project(conn, org, "체육관", "nr", "2026-10-04T09:00:00")
    conn.execute(
        "INSERT INTO energy_plan (project_id, source_type, capacity_kw, entered_by, updated_at) "
        "VALUES (?, '지열', 300, 'nr', '2026-10-04T09:00:00')",
        (pid,),
    )
    _apply_energy(conn, pid, "체육관", [EnergyItem("PV", 10.0)], "2026-10-04T10:00:00", ImportStats())
    rows = conn.execute("SELECT source_type, entered_by FROM energy_plan").fetchall()
    assert [tuple(r) for r in rows] == [("지열", "nr")]
```

- [ ] **Step 2: 실패 확인**

Run: `uv run --no-sync pytest -q -o addopts="" tests/test_nr_apply.py tests/test_migrate_sheets.py`
Expected: `test_nr_apply.py`는 ImportError, 시트 테스트는 `[("PV", "imported")]`가 나와 FAIL.

- [ ] **Step 3: 구현**

`nara/migrate_sheets.py` `_apply_energy` — `current = energy_value(...)` 줄 바로 앞에 넣는다:

```python
    # 설치계획서에서 온 값은 공식 자료라 시트가 덮지 않는다(nr_apply).
    from_plan = conn.execute(
        "SELECT 1 FROM energy_plan WHERE project_id = ? AND entered_by = 'nr' LIMIT 1",
        (project_id,),
    ).fetchone()
    if from_plan:
        remember(conn, project_id, "energy", text, now)
        return
```

`nara/nr_apply.py`:

```python
"""설치계획서 받기 흐름 — 저장, 짝 찾기, 새 사업, 반영.

반영 원칙: 사람이 웹에서 고친 칸은 덮지 않고 skipped에 남긴다(edited_on_web).
"""

import sqlite3
from dataclasses import dataclass

from nara.config import Settings
from nara.energy import kind_for
from nara.nr_match import candidates, canonical_org, decide, org_key
from nara.nr_plan import load_energy, parse_nr_row, save_nr_plan
from nara.runlog import RunCounters
from nara.sheet_memory import edited_on_web
from nara.store import ensure_project, upsert_org

NR_SNIPPET = "설치계획서 의무기관 담당자 부서"
LINKED = ("auto", "new", "human")
MATCH_RESULTS = {
    "auto": "linked",
    "human": "linked",
    "new": "new_project",
    "pending": "pending",
    "ignored": "ignored",
}
_PROJECT_FIELDS = ("address", "start_date", "end_date")


@dataclass(frozen=True)
class RowResult:
    key: str
    saved: str  # created | updated | unchanged | invalid
    match: str | None = None  # linked | new_project | pending | ignored
    project_id: int | None = None
    error: str | None = None


def _plans(conn: sqlite3.Connection, project_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM nr_plan WHERE project_id = ? AND match_state IN ('auto', 'new', 'human') "
        "ORDER BY updated_at DESC, id DESC",
        (project_id,),
    ).fetchall()


def _apply_energy(
    conn: sqlite3.Connection, pid: int, plans: list[sqlite3.Row], now: str, skipped: list[str]
) -> None:
    """연결된 설치계획서들의 용량을 종류별로 합친다. 한 사업에 건물이 여럿일 수 있다."""
    totals: dict[str, float] = {}
    for plan in plans:
        for e in load_energy(plan["energy_json"]):
            code = kind_for(conn, e.source, e.form).code
            totals[code] = round(totals.get(code, 0.0) + e.capacity_kw, 3)
    if not totals:
        return  # 에너지원 표를 못 읽은 설치계획서가 있던 계획을 지우지 않는다
    rows = conn.execute(
        "SELECT source_type, capacity_kw FROM energy_plan WHERE project_id = ?", (pid,)
    )
    if {r["source_type"]: r["capacity_kw"] for r in rows} == totals:
        return
    if edited_on_web(conn, pid, "energy"):
        skipped.append("energy")
        return
    conn.execute("DELETE FROM energy_plan WHERE project_id = ?", (pid,))
    for code, capacity in totals.items():
        conn.execute(
            "INSERT INTO energy_plan (project_id, source_type, capacity_kw, entered_by, "
            "updated_at) VALUES (?, ?, ?, 'nr', ?)",
            (pid, code, capacity, now),
        )


def _apply_dept(
    conn: sqlite3.Connection, pid: int, dept: str | None, now: str, skipped: list[str]
) -> None:
    if not dept:
        return
    latest = conn.execute(
        "SELECT exec_dept, decided_by FROM dept_check WHERE project_id = ? AND confirmed = 1 "
        "AND COALESCE(exec_dept, '') != '' ORDER BY id DESC LIMIT 1",
        (pid,),
    ).fetchone()
    if latest and latest["decided_by"] == "human":
        if latest["exec_dept"] != dept:
            skipped.append("exec_dept")
        return
    if latest and latest["decided_by"] == "nr" and latest["exec_dept"] == dept:
        return
    conn.execute(
        "INSERT INTO dept_check (project_id, exec_dept, snippet, confirmed, decided_by, "
        "checked_at) VALUES (?, ?, ?, 1, 'nr', ?)",
        (pid, dept, NR_SNIPPET, now),
    )


def apply_plans(conn: sqlite3.Connection, project_id: int, now: str) -> list[str]:
    """그 사업에 연결된 설치계획서를 반영한다. 건너뛴 칸 이름을 돌려준다. 커밋은 부른 쪽이."""
    plans = _plans(conn, project_id)
    if not plans:
        return []
    skipped: list[str] = []
    _apply_energy(conn, project_id, plans, now, skipped)
    latest = plans[0]
    project = conn.execute(
        "SELECT address, start_date, end_date FROM project WHERE id = ?", (project_id,)
    ).fetchone()
    for field in _PROJECT_FIELDS:
        value = latest[field]
        if not value or value == project[field]:
            continue
        if edited_on_web(conn, project_id, field):
            skipped.append(field)
            continue
        # field는 위의 고정 목록에서만 온다.
        conn.execute(
            f"UPDATE project SET {field} = ?, updated_at = ? WHERE id = ?",
            (value, now, project_id),
        )
    _apply_dept(conn, project_id, latest["dept"], now, skipped)
    conn.execute(
        "UPDATE nr_plan SET skipped = ? WHERE project_id = ?",
        (",".join(skipped) or None, project_id),
    )
    return skipped


def _new_project(
    conn: sqlite3.Connection, plan: sqlite3.Row, settings: Settings, now: str
) -> int:
    aliases = dict(settings.nr_org_aliases)
    key = org_key(plan["org_name"], aliases)
    org_id = next(
        (
            r["id"]
            for r in conn.execute("SELECT id, name FROM org ORDER BY id")
            if org_key(r["name"], aliases) == key
        ),
        None,
    )
    if org_id is None:
        org_id = upsert_org(conn, canonical_org(plan["org_name"], aliases), settings, now)
    return ensure_project(conn, org_id, plan["building_name"], "nr", now)


def ingest(
    conn: sqlite3.Connection,
    raw_rows: list,
    settings: Settings,
    now: str,
    counters: RunCounters | None = None,
) -> list[RowResult]:
    """받은 행마다 저장 → (확인 필요면) 짝 찾기 → 반영. 행마다 커밋한다."""
    counters = counters or RunCounters()
    aliases = dict(settings.nr_org_aliases)
    results = []
    for raw in raw_rows:
        row = parse_nr_row(raw)
        if isinstance(row, str):
            key = raw.get("key") if isinstance(raw, dict) else None
            results.append(RowResult(key if isinstance(key, str) else "", "invalid", error=row))
            counters.failed += 1
            continue
        plan_id, saved = save_nr_plan(conn, row, now)
        plan = conn.execute("SELECT * FROM nr_plan WHERE id = ?", (plan_id,)).fetchone()
        state, pid = plan["match_state"], plan["project_id"]
        if state == "pending":
            decision = decide(candidates(conn, row.org, row.name, row.addr, aliases))
            state = decision.state
            pid = decision.project_id
            if state == "new":
                pid = _new_project(conn, plan, settings, now)
            conn.execute(
                "UPDATE nr_plan SET match_state = ?, match_score = ?, project_id = ? WHERE id = ?",
                (state, decision.score, pid, plan_id),
            )
        if pid is not None and state in LINKED:
            apply_plans(conn, pid, now)
        conn.commit()
        counters.processed += 1
        counters.updated += saved != "unchanged"
        results.append(RowResult(row.key, saved, MATCH_RESULTS[state], pid))
    return results


def link_plan(
    conn: sqlite3.Connection,
    plan_id: int,
    project_id: int | None,
    settings: Settings,
    now: str,
) -> int:
    """사람이 연결한다. project_id가 None이면 새 사업을 만든다. 연결한 사업 id를 돌려준다."""
    plan = conn.execute("SELECT * FROM nr_plan WHERE id = ?", (plan_id,)).fetchone()
    if plan is None:
        raise LookupError(f"설치계획서 {plan_id}")
    if project_id is None:
        project_id = _new_project(conn, plan, settings, now)
    elif conn.execute("SELECT 1 FROM project WHERE id = ?", (project_id,)).fetchone() is None:
        raise LookupError(f"사업 {project_id}")
    conn.execute(
        "UPDATE nr_plan SET match_state = 'human', project_id = ? WHERE id = ?",
        (project_id, plan_id),
    )
    apply_plans(conn, project_id, now)
    conn.commit()
    return project_id


def ignore_plan(conn: sqlite3.Connection, plan_id: int) -> None:
    """무시한다. 이미 반영한 값은 되돌리지 않는다 — 사람이 상세 화면에서 고친다."""
    cursor = conn.execute(
        "UPDATE nr_plan SET match_state = 'ignored', project_id = NULL WHERE id = ?", (plan_id,)
    )
    if cursor.rowcount == 0:
        raise LookupError(f"설치계획서 {plan_id}")
    conn.commit()
```

- [ ] **Step 4: 통과 확인**

Run: `uv run --no-sync pytest -q -o addopts="" tests/test_nr_apply.py tests/test_migrate_sheets.py`
Expected: 전부 통과.

- [ ] **Step 5: 커밋**

```bash
git add nara/nr_apply.py nara/migrate_sheets.py tests/test_nr_apply.py tests/test_migrate_sheets.py
git commit -m "feat: 설치계획서를 사업에 연결·반영하고 없으면 새 사업을 만든다

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: 받는 주소 `POST /api/nr-plans`

**Files:**
- Modify: `nara/web/app.py`
- Create: `tests/test_web_nr.py`

**Interfaces:**
- Consumes: `ingest`, `RowResult` (Task 5), `app.config["IMPORT_TOKEN"]`·`["SETTINGS"]` (Task 2), `nara.runlog.run_log`.
- Produces: `POST /api/nr-plans` → `{"ok": true, "results": [RowResult as dict]}`; `GET /api/nr-plans/ping` → `{"ok": true}`. 엔드포인트 이름 `nr_import`·`nr_ping`. 상수 `NR_MAX_ROWS = 200`, `MAX_BODY = 1024 * 1024`.

- [ ] **Step 1: 실패하는 테스트 쓰기** (`tests/test_web_nr.py`)

```python
"""설치계획서 받는 주소 — 확장 프로그램이 부른다. 로그인 대신 토큰."""

import sqlite3
from pathlib import Path

import pytest

from nara.config import load_settings
from nara.db import connect, migrate
from nara.store import ensure_project, upsert_org
from nara.web.app import create_app

SETTINGS = load_settings(Path(__file__).resolve().parents[1] / "config.toml")
TOKEN = "test-import-token"
NOW = "2026-10-04T09:00:00"
ROW = {
    "key": "2026-001",
    "org": "전라북도 완주군",
    "name": "완주 다목적체육관",
    "addr": "",
    "start": "2027-03-01",
    "end": "2028-06-30",
    "dept": "체육진흥과",
    "energy": [{"source": "지열", "form": "수직밀폐형", "capacity_kw": 336.06}],
}


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "w.db"
    conn = connect(path)
    migrate(conn)
    org = upsert_org(conn, "전북특별자치도 완주군", SETTINGS, NOW)
    pid = ensure_project(conn, org, "완주군 다목적체육관 건립 설계용역", "g2b", NOW)
    conn.close()
    return path, pid


def _client(path, token=TOKEN, **config):
    app = create_app(path, secret_key="test-secret", import_token=token, settings=SETTINGS)
    app.testing = True
    app.config.update(config)
    return app.test_client()


def _send(client, body, auth=f"Bearer {TOKEN}", **headers):
    if auth is not None:
        headers["Authorization"] = auth
    return client.post("/api/nr-plans", json=body, headers=headers)


def _count(path, table):
    conn = sqlite3.connect(path)
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


def test_a_plan_with_the_right_token_is_saved_and_linked(db):
    path, pid = db
    resp = _send(_client(path), {"rows": [ROW]})
    assert resp.status_code == 200
    assert resp.get_json() == {
        "ok": True,
        "results": [
            {"key": "2026-001", "saved": "created", "match": "linked", "project_id": pid,
             "error": None}
        ],
    }  # fmt: skip
    assert _count(path, "energy_plan") == 1
    conn = sqlite3.connect(path)
    run = conn.execute("SELECT command, processed FROM run_log ORDER BY id DESC").fetchone()
    conn.close()
    assert run == ("nr import", 1)


@pytest.mark.parametrize(
    "auth", [None, "Bearer wrong", f"bearer {TOKEN}", f"Bearer  {TOKEN}", f"Bearer {TOKEN} ", TOKEN]
)
def test_the_token_must_match_exactly(db, auth):
    path, _ = db
    assert _send(_client(path), {"rows": [ROW]}, auth=auth).status_code == 401
    assert _count(path, "nr_plan") == 0


def test_without_a_configured_token_the_address_does_not_exist(db):
    path, _ = db
    client = _client(path, token=None)
    assert _send(client, {"rows": [ROW]}).status_code == 404
    assert client.get("/api/nr-plans/ping").status_code == 404


def test_ping_answers_with_the_token_only(db):
    path, _ = db
    client = _client(path)
    ok = client.get("/api/nr-plans/ping", headers={"Authorization": f"Bearer {TOKEN}"})
    assert (ok.status_code, ok.get_json()) == (200, {"ok": True})
    assert client.get("/api/nr-plans/ping").status_code == 401


def test_another_origin_is_fine_with_the_token(db):
    """확장 프로그램의 요청은 Origin이 chrome-extension://이다. 같은 출처 검사에서 뺀다."""
    path, _ = db
    resp = _send(_client(path), {"rows": [ROW]}, Origin="chrome-extension://abc")
    assert resp.status_code == 200


def test_a_body_that_is_not_json_is_400(db):
    path, _ = db
    client = _client(path)
    headers = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}
    assert client.post("/api/nr-plans", data="{not json", headers=headers).status_code == 400
    assert _send(client, {"row": [ROW]}).status_code == 400
    assert _send(client, ["2026-001"]).status_code == 400


def test_too_many_rows_or_too_big_a_body_is_413(db):
    path, _ = db
    client = _client(path)
    assert _send(client, {"rows": [ROW] * 201}).status_code == 413
    big = {"rows": [{**ROW, "addr": "가" * (1024 * 1024)}]}
    assert _send(client, big).status_code == 413
    assert _count(path, "nr_plan") == 0


def test_a_busy_database_answers_503(db):
    path, _ = db
    client = _client(path, WRITE_TIMEOUT=0.2)
    blocker = sqlite3.connect(path)
    blocker.execute("BEGIN IMMEDIATE")
    try:
        resp = _send(client, {"rows": [ROW]})
    finally:
        blocker.rollback()
        blocker.close()
    assert resp.status_code == 503
    assert resp.get_json()["ok"] is False
    assert _count(path, "nr_plan") == 0
```

- [ ] **Step 2: 실패 확인**

Run: `uv run --no-sync pytest -q -o addopts="" tests/test_web_nr.py`
Expected: 404 (주소 없음)로 FAIL.

- [ ] **Step 3: 구현** (`nara/web/app.py`)

import에 `import hmac`, `from dataclasses import asdict, replace`(이미 `replace`가 있으면 그 줄에 `asdict`만), `from nara.nr_apply import ingest`, `from nara.runlog import run_log`.

상수:

```python
NR_MAX_ROWS = 200
MAX_BODY = 1024 * 1024
# 확장 프로그램이 부르는 주소. 로그인·같은 출처 검사 대신 토큰으로 막는다.
API_ENDPOINTS = {"nr_import", "nr_ping"}
PUBLIC_ENDPOINTS = {"login", "static", *API_ENDPOINTS}
```

(기존 `PUBLIC_ENDPOINTS = {"login", "static"}` 줄을 위 줄로 바꾼다.)

헬퍼:

```python
def _check_token() -> None:
    """Authorization: Bearer <토큰>이 정확히 같아야 한다. 토큰이 없으면 주소 자체가 없다."""
    token = current_app.config.get("IMPORT_TOKEN")
    if not token:
        abort(404)
    sent = request.headers.get("Authorization", "")
    if not hmac.compare_digest(sent.encode(), f"Bearer {token}".encode()):
        abort(401)
```

`create_app` 안:
- `app.config["SETTINGS"] = settings` 아래에 `app.config["MAX_CONTENT_LENGTH"] = MAX_BODY`.
- `_guard_writes`를:

```python
    @app.before_request
    def _guard_writes():
        if request.endpoint in API_ENDPOINTS:
            return None
        if request.method == "POST" and not _same_origin():
            abort(403)
        return None
```

- 라우트(예: `/hide` 앞):

```python
    @app.get("/api/nr-plans/ping")
    def nr_ping():
        _check_token()
        return {"ok": True}

    @app.post("/api/nr-plans")
    def nr_import():
        _check_token()
        if (request.content_length or 0) > MAX_BODY:
            return {"ok": False, "error": "본문이 1MB를 넘습니다"}, 413
        body = request.get_json(silent=True)
        rows = body.get("rows") if isinstance(body, dict) else None
        if not isinstance(rows, list):
            return {"ok": False, "error": "rows 배열이 없습니다"}, 400
        if len(rows) > NR_MAX_ROWS:
            return {"ok": False, "error": f"한 번에 {NR_MAX_ROWS}행까지 받습니다"}, 413
        settings = current_app.config.get("SETTINGS")
        if settings is None:
            return {"ok": False, "error": "설정 파일을 읽지 못해 받을 수 없습니다"}, 500
        now = datetime.now().isoformat(timespec="seconds")
        try:
            with closing(_rw_conn()) as conn, run_log(conn, "nr import", f"{len(rows)}행") as c:
                results = ingest(conn, rows, settings, now, c)
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc):
                raise
            return {"ok": False, "error": BUSY_MESSAGE}, 503
        return {"ok": True, "results": [asdict(r) for r in results]}
```

주의: 503 시험에서 `run_log`의 INSERT가 잠금에 먼저 걸린다. 그래서 아무 행도 남지 않는다. 기대가 맞지 않으면 원인을 확인한 뒤 Ruling으로 남긴다.

- [ ] **Step 4: 통과 확인**

Run: `uv run --no-sync pytest -q -o addopts="" tests/test_web_nr.py tests/test_web.py`
Expected: 전부 통과. 기존 `test_a_post_from_another_site_is_refused`도 그대로 통과해야 한다(일반 화면의 출처 검사는 유지).

- [ ] **Step 5: 커밋**

```bash
git add nara/web/app.py tests/test_web_nr.py
git commit -m "feat: 확장 프로그램이 설치계획서를 보내는 받는 주소를 연다

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: 설치계획 화면(`/nr`)과 상세·목록 표시

**Files:**
- Modify: `nara/web/data.py`, `nara/web/app.py`, `nara/web/templates/base.html`, `nara/web/templates/list.html`, `nara/web/templates/detail.html`, `tests/test_web.py`
- Create: `nara/web/templates/nr_list.html`, `nara/web/templates/nr_detail.html`

**Interfaces:**
- Consumes: `ingest`, `link_plan`, `ignore_plan` (Task 5), `candidates` (Task 4), `load_energy` (Task 3).
- Produces: `data.NR_STATE_LABELS: dict[str, str]`, `data.nr_counts(conn) -> dict[str, int]`, `data.nr_rows(conn, state: str) -> list[sqlite3.Row]`, `data.nr_plan_detail(conn, plan_id: int) -> sqlite3.Row | None`, `ProjectDetail.nr_plans: list[sqlite3.Row]`. 라우트 `nr_list`(GET `/nr`), `nr_detail`(GET `/nr/<id>`), `nr_link`(POST `/nr/<id>/link`), `nr_ignore`(POST `/nr/<id>/ignore`).

- [ ] **Step 1: 실패하는 테스트 쓰기** (`tests/test_web.py`)

`_app`이 설정을 넘기게 바꾼다: `app = create_app(path, secret_key=SECRET, settings=SETTINGS)`. 끝에 더한다:

```python
from nara.nr_apply import ingest as nr_ingest

NR_ROW = {
    "key": "2026-001",
    "org": "전라북도 완주군",
    "name": "완주 다목적체육관",
    "addr": "",
    "start": "2027-03-01",
    "end": "2028-06-30",
    "dept": "체육진흥과",
    "energy": [{"source": "지열", "form": "수직밀폐형", "capacity_kw": 336.06}],
}


def _nr(path, *rows):
    conn = connect(path)
    try:
        return nr_ingest(conn, list(rows), SETTINGS, NOW)
    finally:
        conn.close()


def _plan_id(path, key):
    conn = connect(path)
    try:
        return conn.execute("SELECT id FROM nr_plan WHERE key = ?", (key,)).fetchone()[0]
    finally:
        conn.close()


def test_a_linked_plan_shows_on_the_project_page(world):
    path, ids = world
    [result] = _nr(path, NR_ROW)
    assert result.project_id == ids["gym"]
    page = _text(_client(path).get(f"/project/{ids['gym']}"))
    assert "<h2>설치계획서</h2>" in page
    assert "2026-001" in page and "지열 수직밀폐형 336.06 kW" in page
    assert "설치계획서" in page and "체육진흥과" in page


def test_a_pending_plan_is_counted_on_the_list_and_listed_on_the_plan_page(world):
    path, ids = world
    conn = connect(path)
    org = conn.execute("SELECT org_id FROM project WHERE id = ?", (ids["gym"],)).fetchone()[0]
    ensure_project(conn, org, "완주군 다목적체육관 리모델링", "g2b", NOW)
    conn.close()
    _nr(path, NR_ROW)
    client = _client(path)
    assert "설치계획 확인 필요 1건" in _text(client.get("/"))
    plans = _text(client.get("/nr"))
    assert "완주 다목적체육관" in plans and "확인 필요" in plans
    assert 'href="/nr"' in _text(client.get("/prices"))


def test_a_person_links_a_pending_plan_from_its_page(world):
    path, ids = world
    conn = connect(path)
    org = conn.execute("SELECT org_id FROM project WHERE id = ?", (ids["gym"],)).fetchone()[0]
    ensure_project(conn, org, "완주군 다목적체육관 리모델링", "g2b", NOW)
    conn.close()
    _nr(path, NR_ROW)
    plan = _plan_id(path, "2026-001")
    client = _client(path)
    page = _text(client.get(f"/nr/{plan}"))
    assert f'name="project_id" value="{ids["gym"]}"' in page
    resp = _post(client, f"/nr/{plan}/link", {"project_id": str(ids["gym"])})
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith(f"/project/{ids['gym']}")
    assert "지열 수직밀폐형 336.06 kW" in _text(client.get(f"/project/{ids['gym']}"))


def test_a_person_can_ignore_a_plan_or_make_a_new_project(world):
    path, _ = world
    _nr(path, {**NR_ROW, "key": "2026-002", "name": "봉동 체험관"})
    plan = _plan_id(path, "2026-002")
    client = _client(path)
    resp = _post(client, f"/nr/{plan}/link", {"new": "1"})
    assert resp.status_code == 302
    assert "봉동 체험관" in _text(client.get(resp.headers["Location"]))
    assert _post(client, f"/nr/{plan}/ignore", {}).status_code == 302
    assert "봉동 체험관" in _text(client.get("/nr?state=ignored"))


def test_plan_actions_refuse_bad_ids_and_other_sites(world):
    path, _ = world
    _nr(path, NR_ROW)
    plan = _plan_id(path, "2026-001")
    client = _client(path)
    assert client.get("/nr/99999").status_code == 404
    assert _post(client, "/nr/99999/ignore", {}).status_code == 404
    assert _post(client, f"/nr/{plan}/link", {"project_id": "99999"}).status_code == 404
    resp = _post(client, f"/nr/{plan}/link", {"project_id": "abc"})
    assert resp.status_code == 302 and resp.headers["Location"].endswith(f"/nr/{plan}")
    evil = _post(client, f"/nr/{plan}/ignore", {}, origin="http://evil.example")
    assert evil.status_code == 403
```

- [ ] **Step 2: 실패 확인**

Run: `uv run --no-sync pytest -q -o addopts="" tests/test_web.py -k "plan"`
Expected: FAIL (`/nr` 404, 상세에 설치계획서 칸 없음).

- [ ] **Step 3: 구현**

`nara/web/data.py`:

```python
DECIDED_BY_LABELS["nr"] = "설치계획서"  # 사전 정의 안에 "nr": "설치계획서", 줄로 넣는다

NR_STATE_LABELS = {
    "pending": "확인 필요",
    "auto": "자동 연결",
    "new": "새 사업",
    "human": "사람 연결",
    "ignored": "무시",
}


def nr_counts(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute("SELECT match_state, COUNT(*) FROM nr_plan GROUP BY match_state")
    return {r[0]: r[1] for r in rows}


_NR_SELECT = (
    "SELECT n.*, p.name AS project_name FROM nr_plan n "
    "LEFT JOIN project p ON p.id = n.project_id "
)


def nr_rows(conn: sqlite3.Connection, state: str) -> list[sqlite3.Row]:
    return conn.execute(
        _NR_SELECT + "WHERE n.match_state = ? ORDER BY n.updated_at DESC, n.id DESC LIMIT ?",
        (state, LIST_LIMIT),
    ).fetchall()


def nr_plan_detail(conn: sqlite3.Connection, plan_id: int) -> sqlite3.Row | None:
    if plan_id > _SQLITE_MAX_INT:
        return None
    return conn.execute(_NR_SELECT + "WHERE n.id = ?", (plan_id,)).fetchone()
```

(`LIST_LIMIT`는 `nara.web.query`에서 import. `DECIDED_BY_LABELS`는 정의 안에 `"nr": "설치계획서",` 줄을 넣는다 — 위 첫 줄은 설명용이다.)

`ProjectDetail`에 `nr_plans: list = ()`를 더하고, `project_detail`의 `return ProjectDetail(...)`에 `nr_plans=conn.execute("SELECT * FROM nr_plan WHERE project_id = ? ORDER BY updated_at DESC, id DESC", (project_id,)).fetchall(),`를 넣는다.

`nara/web/app.py` — import에 `from nara.nr_apply import ignore_plan, link_plan`, `from nara.nr_match import candidates`, `from nara.nr_plan import load_energy`, data에서 `NR_STATE_LABELS, nr_counts, nr_plan_detail, nr_rows`. `create_app` 안에 `app.add_template_global(load_energy, "load_energy")`. `index()`의 `render_template`에 `nr_pending=nr_counts(conn).get("pending", 0),`. 라우트:

```python
    @app.get("/nr")
    def nr_list():
        state = request.args.get("state", "pending")
        if state not in NR_STATE_LABELS:
            state = "pending"
        conn = get_conn()
        return render_template(
            "nr_list.html",
            rows=nr_rows(conn, state),
            state=state,
            counts=nr_counts(conn),
            labels=NR_STATE_LABELS,
        )

    @app.get("/nr/<int:plan_id>")
    def nr_detail(plan_id: int):
        conn = get_conn()
        plan = nr_plan_detail(conn, plan_id)
        if plan is None:
            abort(404)
        settings = current_app.config.get("SETTINGS")
        aliases = dict(settings.nr_org_aliases) if settings else {}
        found = candidates(
            conn, plan["org_name"], plan["building_name"], plan["address"] or "", aliases
        )
        return render_template(
            "nr_detail.html", plan=plan, candidates=found, labels=NR_STATE_LABELS
        )

    def _nr_write(plan_id: int, action):
        """설치계획서 쓰기 공통. 잠금이면 이유를 띄우고 그 설치계획서로 돌아간다."""
        settings = current_app.config.get("SETTINGS")
        if settings is None:
            abort(503)
        now = datetime.now().isoformat(timespec="seconds")
        try:
            with closing(_rw_conn()) as conn:
                return action(conn, settings, now)
        except LookupError:
            abort(404)
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc):
                raise
            flash(BUSY_MESSAGE)
            return redirect(url_for("nr_detail", plan_id=plan_id))

    @app.post("/nr/<int:plan_id>/link")
    def nr_link(plan_id: int):
        raw = request.form.get("project_id", "").strip()
        if request.form.get("new"):
            target = None
        elif raw.isdigit() and int(raw) <= MAX_ID:
            target = int(raw)
        else:
            flash("연결할 사업 번호를 숫자로 적으세요")
            return redirect(url_for("nr_detail", plan_id=plan_id))

        def act(conn, settings, now):
            pid = link_plan(conn, plan_id, target, settings, now)
            flash("설치계획서를 이 사업에 연결했습니다")
            return redirect(url_for("detail", project_id=pid))

        return _nr_write(plan_id, act)

    @app.post("/nr/<int:plan_id>/ignore")
    def nr_ignore(plan_id: int):
        def act(conn, settings, now):
            ignore_plan(conn, plan_id)
            flash("설치계획서를 무시했습니다")
            return redirect(url_for("nr_list"))

        return _nr_write(plan_id, act)
```

`nara/web/templates/base.html` — 위쪽 메뉴의 `단가 관리` 링크 뒤에 ` · <a href="{{ url_for('nr_list') }}">설치계획</a>`.

`nara/web/templates/list.html` — 결과 건수 `<p>` 앞에:

```html
{% if nr_pending %}<p class="saved"><a href="{{ url_for('nr_list') }}">설치계획 확인 필요 {{ nr_pending }}건</a></p>{% endif %}
```

`nara/web/templates/detail.html` — `수정 이력` 제목 앞에:

```html
<h2>설치계획서</h2>
{% if d.nr_plans %}
<div class="table-wrap"><table>
<thead><tr><th>신청번호</th><th>건물명</th><th>담당부서</th><th>에너지원</th><th>받은 때</th><th>상태</th></tr></thead>
<tbody>
{% for n in d.nr_plans %}
<tr><td><a href="{{ url_for('nr_detail', plan_id=n.id) }}">{{ n.key }}</a></td><td>{{ n.building_name }}</td><td>{{ n.dept|dash }}</td>
<td>{% for e in load_energy(n.energy_json) %}{{ e.source }} {{ e.form }} {{ e.capacity_kw }} kW{% if not loop.last %}<br>{% endif %}{% else %}—{% endfor %}</td>
<td>{{ n.updated_at[:10] }}</td>
<td>{{ n.match_state }}{% if n.skipped %} <span class="bad">웹에서 고친 값이 있어 반영하지 않음: {{ n.skipped }}</span>{% endif %}</td></tr>
{% endfor %}
</tbody>
</table></div>
{% else %}
<p class="muted">연결된 설치계획서가 없습니다</p>
{% endif %}
```

`nara/web/templates/nr_list.html`:

```html
{% extends "base.html" %}
{% block title %}설치계획{% endblock %}
{% block body %}
<h1>설치계획</h1>
<p class="muted">크롬 확장 프로그램이 신재생에너지센터에서 보낸 설치계획서입니다. 확인 필요 건은 사업을 골라 연결하세요.</p>
<p>{% for key, label in labels.items() %}<a href="{{ url_for('nr_list', state=key) }}"{% if key == state %} aria-current="page"{% endif %}>{{ label }} {{ counts.get(key, 0) }}</a>{% if not loop.last %} · {% endif %}{% endfor %}</p>
<div class="table-wrap"><table>
<thead><tr><th>기관명</th><th>건물명</th><th>준공예정일</th><th>연결된 사업</th><th>점수</th><th>받은 때</th></tr></thead>
<tbody>
{% for n in rows %}
<tr><td>{{ n.org_name }}</td><td><a href="{{ url_for('nr_detail', plan_id=n.id) }}">{{ n.building_name }}</a></td>
<td>{{ n.end_date|dash }}</td>
<td>{% if n.project_id %}<a href="{{ url_for('detail', project_id=n.project_id) }}">{{ n.project_name }}</a>{% else %}—{% endif %}</td>
<td>{{ '%.2f'|format(n.match_score) if n.match_score is not none else '—' }}</td><td>{{ n.updated_at[:10] }}</td></tr>
{% else %}
<tr><td colspan="6" class="muted">{{ labels[state] }} 설치계획서가 없습니다</td></tr>
{% endfor %}
</tbody>
</table></div>
{% endblock %}
```

`nara/web/templates/nr_detail.html`:

```html
{% extends "base.html" %}
{% block title %}{{ plan.building_name }}{% endblock %}
{% block body %}
<p><a href="{{ url_for('nr_list', state=plan.match_state) }}">← 설치계획 목록</a></p>
<h1>{{ plan.building_name }}</h1>
<p class="muted">{{ plan.org_name }} · 신청번호 {{ plan.key }} · {{ labels[plan.match_state] }}{% if plan.project_id %} · 연결: <a href="{{ url_for('detail', project_id=plan.project_id) }}">{{ plan.project_name }}</a>{% endif %}</p>
<div class="table-wrap"><table>
<tr><th>주소</th><td>{{ plan.address|dash }}</td></tr>
<tr><th>착공예정일</th><td>{{ plan.start_date|dash }}</td></tr>
<tr><th>준공예정일</th><td>{{ plan.end_date|dash }}</td></tr>
<tr><th>담당부서</th><td>{{ plan.dept|dash }}</td></tr>
<tr><th>에너지원</th><td>{% for e in load_energy(plan.energy_json) %}{{ e.source }} {{ e.form }} {{ e.capacity_kw }} kW{% if not loop.last %}<br>{% endif %}{% else %}—{% endfor %}</td></tr>
</table></div>

<h2>연결할 사업</h2>
<div class="table-wrap"><table>
<thead><tr><th>사업</th><th>기관</th><th>점수</th><th></th></tr></thead>
<tbody>
{% for c in candidates %}
<tr><td><a href="{{ url_for('detail', project_id=c.project_id) }}">{{ c.name }}</a></td><td>{{ c.org_name }}</td><td>{{ '%.2f'|format(c.score) }}</td>
<td><form method="post" class="inline" action="{{ url_for('nr_link', plan_id=plan.id) }}"><input type="hidden" name="project_id" value="{{ c.project_id }}"><button type="submit">이 사업과 연결</button></form></td></tr>
{% else %}
<tr><td colspan="4" class="muted">같은 기관의 사업이 없습니다</td></tr>
{% endfor %}
</tbody>
</table></div>
<form method="post" class="hide-one" action="{{ url_for('nr_link', plan_id=plan.id) }}">
  <label>사업 번호로 연결 <input type="text" name="project_id" inputmode="numeric"></label>
  <button type="submit">연결</button>
</form>
<p>
<form method="post" class="inline" action="{{ url_for('nr_link', plan_id=plan.id) }}"><input type="hidden" name="new" value="1"><button type="submit">새 사업으로 추가</button></form>
<form method="post" class="inline" action="{{ url_for('nr_ignore', plan_id=plan.id) }}"><button type="submit">무시</button></form>
</p>
{% endblock %}
```

- [ ] **Step 4: 통과 확인**

Run: `uv run --no-sync pytest -q -o addopts=""`
Expected: 전부 통과. 린트도 통과.

- [ ] **Step 5: 브라우저 확인 (DB 복사본)**

원본 DB를 스크래치 폴더에 복사하고, 테스트 사용자와 `.env`(`NARA_SECRET_KEY`, `NARA_IMPORT_TOKEN=test-import-token`)를 만든다. 그다음 `.venv/Scripts/nara.exe serve --db <복사본> --env <복사본 .env> --port 8765`로 띄운다. `curl`로 `NR_ROW` 두 건(짝 있는 것·없는 것)을 보낸 뒤 확인한다:
- `/nr` 목록
- 상세 연결 화면
- 사업 상세의 설치계획서 칸

확인이 끝나면 임시 서버를 끈다.

- [ ] **Step 6: 커밋**

```bash
git add nara/web tests/test_web.py
git commit -m "feat: 설치계획 화면에서 연결·새 사업·무시를 고른다

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: 실제 설치계획서로 기준 맞추기 (자료 필요)

**선행 조건:** 사용자가 확장 프로그램 설정 페이지의 "수집 결과 복사"로 실제 설치계획서 20건 이상을 준다. 자료가 없으면 이 Task는 건너뛰고 ledger에 `Task 8: blocked — 실제 자료 없음`을 남긴다.

**Files:**
- Create: `tests/fixtures/nr_answer_key.json`, `tests/test_nr_answer_key.py`

- [ ] **Step 1: 정답표 만들기**

받은 행마다 원본 DB에서 같은 사업을 사람이 확인해 적는다. 기관명·건물명·주소는 공공기관 공개 정보다. 담당자 이름·전화번호는 넣지 않는다.

```json
[
  {"org": "전라북도 완주군", "name": "완주 다목적체육관", "addr": "",
   "projects": [{"org": "전북특별자치도 완주군", "name": "완주군 다목적체육관 건립 설계용역"}],
   "expected": "완주군 다목적체육관 건립 설계용역"}
]
```

`expected`가 `null`이면 새 사업이 정답이다.

- [ ] **Step 2: 시험 쓰기**

```python
"""실제 설치계획서로 만든 정답표. 짝 찾기 기준(0.8·0.2·0.4)을 바꾸면 여기서 확인한다."""

import json
from pathlib import Path

import pytest

from nara.config import load_settings
from nara.db import connect, migrate
from nara.nr_match import candidates, decide
from nara.store import ensure_project, upsert_org

ROOT = Path(__file__).resolve().parent
SETTINGS = load_settings(ROOT.parent / "config.toml")
CASES = json.loads((ROOT / "fixtures" / "nr_answer_key.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_matching_follows_the_answer_key(tmp_path, case):
    conn = connect(tmp_path / "k.db")
    migrate(conn)
    ids = {}
    for p in case["projects"]:
        org = upsert_org(conn, p["org"], SETTINGS, "2026-10-04T09:00:00")
        ids[p["name"]] = ensure_project(conn, org, p["name"], "g2b", "2026-10-04T09:00:00")
    decision = decide(candidates(conn, case["org"], case["name"], case["addr"]))
    if case["expected"] is None:
        assert decision.state == "new"
    else:
        assert decision.state in ("auto", "pending")
        assert decision.state == "auto", f"확인 필요로 빠짐: 점수 {decision.score}"
        assert decision.project_id == ids[case["expected"]]
```

- [ ] **Step 3: 돌려 보고 규칙·기준 고치기**

Run: `uv run --no-sync pytest -q -o addopts="" tests/test_nr_answer_key.py`

틀린 건마다 `nr_match.py`의 정규화(`_CUT`, `_REGION_RENAMES`) 또는 상수를 고친다. 자동 연결이 틀린 짝을 고르는 일(오연결)은 0건이어야 한다. 확인 필요로 빠지는 건 허용하되 건수를 보고한다. 바꾼 값은 Ruling으로 남긴다.

- [ ] **Step 4: 커밋**

```bash
git add tests/fixtures/nr_answer_key.json tests/test_nr_answer_key.py nara/nr_match.py
git commit -m "test: 실제 설치계획서 정답표로 짝 찾기 기준을 맞춘다

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## 범위 밖 — 확장 프로그램 변경 (다른 저장소 `jlaw080-ops/energyAgency-reneaablePlan`)

나라 앱 쪽이 병합된 뒤 그 저장소에서 따로 계획하고 PR로 낸다. 할 일:

1. `manifest.json`: `"optional_host_permissions": ["http://127.0.0.1/*", "http://localhost/*", "http://*/*", "https://*/*"]`를 더한다. 설정 저장 때 입력한 주소에 대해서만 `chrome.permissions.request`로 권한을 받는다. 버전은 `1.5.0`.
2. `options.html/.js`: "5. 나라 앱으로 보내기" 칸(나라 앱 주소·토큰·[연결 테스트])을 둔다. 연결 테스트는 `GET {주소}/api/nr-plans/ping`. 값은 `chrome.storage.sync`의 `naraUrl`·`naraToken`.
3. `background.js`: `{type: 'nara-send', rows}` 메시지를 받아 `POST {naraUrl}/api/nr-plans`(헤더 `Authorization: Bearer {naraToken}`)로 보내고 응답을 돌려준다.
4. `crawl.js`: `getEnergy()`가 문자열과 함께 `{source, form, capacity_kw}` 배열도 만든다. 한 건을 마칠 때 `naraUrl`이 있으면 `{key, org, name, addr, start, end, dept, energy}`를 보낸다. 날짜는 `fmtDate`를 거친 `YYYY-MM-DD`, 용량은 쉼표를 뗀 수다. 시트 연결이 있으면 시트에도 그대로 쓴다. 작업 기록에 나라 앱 결과(`linked|new_project|pending|invalid`)를 남긴다.
5. `test/run-crawl.mjs`: 보내기 본문 모양과 실패 시 중지 동작을 시험한다.
6. README 7장에 나라 앱 연결 방법을 더한다.

## 실행 뒤 운영 안내 (사용자에게 전달)

- `.env`에 `NARA_IMPORT_TOKEN=<긴 무작위 값>`을 넣고 서버를 다시 띄운다. 값은 `python -c "import secrets; print(secrets.token_urlsafe(32))"`로 만든다.
- 확장 프로그램 설정의 "나라 앱으로 보내기"에 서버 주소와 같은 토큰을 넣는다.
