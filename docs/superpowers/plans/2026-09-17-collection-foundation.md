# 수집 기반과 기존 데이터 이관 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 나라장터 설계용역 공고를 전국에서 모아 SQLite에 쌓고 낙찰업체까지 채우며, 기존 구글시트 전 탭을 이관한다.

**Architecture:** 파이썬 CLI 한 덩어리. 순수 함수(필터·파서)와 입출력(API·DB)을 파일로 분리해 테스트가 네트워크 없이 돌게 한다. DB는 sqlite3 표준 라이브러리에 스키마 파일과 단순 마이그레이션 러너를 얹는다. ORM은 쓰지 않는다.

**Tech Stack:** Python 3.14, uv, typer(CLI), httpx(HTTP), sqlite3(표준), pytest, ruff

**Spec:** `docs/superpowers/specs/2026-09-17-nara-collector-design.md`

## Global Constraints

- Python 3.14 이상. 패키지 관리는 `uv`
- 모든 텍스트 파일 UTF-8
- 날짜는 DB에 ISO `YYYY-MM-DD` 문자열로 저장한다. 화면 표기 변환은 별도 함수
- 자격 증명은 `.env`에서만 읽는다. 저장소에 올리지 않는다(`.gitignore` 등록 완료)
- 테스트는 네트워크를 타지 않는다. HTTP는 `httpx.MockTransport`로 대체한다
- 제외 키워드와 관심 기관 초기값은 스펙 문서의 값을 그대로 쓴다
- 커밋 메시지는 `<type>: <설명>` 형식. 타입은 feat·fix·refactor·docs·test·chore
- 테스트 커버리지 80% 이상

---

## 파일 구조

| 파일 | 책임 |
|---|---|
| `pyproject.toml` | 패키지·의존성·pytest·ruff 설정 |
| `config.toml` | 제외 키워드, 관심 기관, 수집 상수 |
| `nara/cli.py` | CLI 진입점. 명령 정의만 하고 로직은 다른 모듈에 위임 |
| `nara/config.py` | `Settings`·`Secrets` 로딩 |
| `nara/dates.py` | 날짜 문자열 정규화 |
| `nara/filters.py` | 제목·수요기관 필터 (순수 함수) |
| `nara/db.py` | 연결·마이그레이션 |
| `nara/schema.sql` | 테이블 정의 |
| `nara/store.py` | DB 읽기·쓰기 (SQL은 여기에만) |
| `nara/runlog.py` | 실행 기록 |
| `nara/g2b/list_api.py` | 입찰공고 목록 API |
| `nara/g2b/award_api.py` | 낙찰정보 API |
| `nara/collect.py` | 수집·백필 흐름 |
| `nara/award.py` | 낙찰 조회 흐름 |
| `nara/doctor.py` | 데이터 점검 |
| `nara/sheets_tsv.py` | 구글 TSV 읽기 (줄 분할 병합) |
| `nara/energy.py` | 설치계획내용 파서·예상가 계산 |
| `nara/migrate_sheets.py` | 시트 → DB 이관 |

### 주요 인터페이스

```python
# nara/config.py
@dataclass(frozen=True)
class Settings:
    title_required: tuple[str, ...]
    title_excluded: tuple[str, ...]
    org_excluded: tuple[str, ...]
    focus_orgs: tuple[str, ...]
    service_div_name: str
    skip_cancelled: bool

# nara/g2b/list_api.py
@dataclass(frozen=True)
class NoticeItem:
    bid_no: str; bid_ord: str; org_name: str; title: str
    service_div: str; kind: str
    notice_date: str; open_date: str; close_date: str   # ISO
    url: str
    budget_krw: int | None; budget_basis: str
    officer_name: str; officer_tel: str
    raw: dict

# nara/g2b/award_api.py
@dataclass(frozen=True)
class AwardItem:
    winner: str; award_date: str; raw: dict

# nara/energy.py
@dataclass(frozen=True)
class EnergyItem:
    source_type: str; capacity_kw: float
```

---

### Task 1: 프로젝트 뼈대와 CLI 진입점

**Files:**
- Create: `pyproject.toml`
- Create: `nara/__init__.py`
- Create: `nara/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: 없음
- Produces: `nara.cli.app` (typer.Typer), `nara.__version__: str`

- [ ] **Step 1: pyproject.toml을 직접 쓴다**

`uv init`을 쓰지 않는다. `uv init --package`는 `src/nara/` 배치와 `uv_build` 백엔드를 만드는데, 이 계획의 모든 경로는 평면 `nara/`를 전제한다. 또 저장소에 이미 있는 `.gitignore`를 건드린다.

`pyproject.toml`:

```toml
[project]
name = "nara"
version = "0.1.0"
description = "나라장터 설계용역 공고 수집·조사 도구"
requires-python = ">=3.14"
dependencies = ["typer", "httpx"]

[project.scripts]
nara = "nara.cli:app"

[build-system]
requires = ["uv_build>=0.12.5,<0.13.0"]
build-backend = "uv_build"

[tool.uv.build-backend]
# 평면 배치. 기본값은 "src"라 이 줄이 없으면 nara 패키지를 찾지 못한다.
module-root = ""

[dependency-groups]
dev = ["pytest", "pytest-cov", "ruff"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"

[tool.ruff]
line-length = 100
target-version = "py314"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]
```

- [ ] **Step 2: 의존성 설치**

```bash
uv sync
```

Expected: `.venv`가 생기고 typer·httpx·pytest·ruff가 들어온다. `uv.lock`이 만들어진다.

- [ ] **Step 3: 실패하는 테스트 작성**

`tests/test_cli.py`:

```python
from typer.testing import CliRunner

from nara import __version__
from nara.cli import app


def test_version_command_prints_package_version():
    result = CliRunner().invoke(app, ["version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout
```

- [ ] **Step 4: 테스트가 실패하는지 확인**

Run: `uv run pytest tests/test_cli.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'nara.cli'`

- [ ] **Step 5: 최소 구현**

`nara/__init__.py`:

```python
__version__ = "0.1.0"
```

`nara/cli.py`:

```python
import typer

from nara import __version__

app = typer.Typer(help="나라장터 설계용역 수집·조사 도구")


@app.command()
def version() -> None:
    """버전을 출력한다."""
    typer.echo(f"nara {__version__}")


if __name__ == "__main__":
    app()
```

- [ ] **Step 6: 테스트 통과 확인**

Run: `uv run pytest tests/test_cli.py -v`
Expected: PASS

- [ ] **Step 7: 설치된 CLI가 도는지 확인**

Run: `uv run nara version`
Expected: `nara 0.1.0`

평면 배치가 먹었는지 함께 본다. `ModuleNotFoundError: No module named 'nara'`가 나오면 `[tool.uv.build-backend] module-root = ""`가 빠진 것이다.

- [ ] **Step 8: 커밋**

```bash
git add pyproject.toml uv.lock nara/__init__.py nara/cli.py tests/test_cli.py
git commit -m "feat: 프로젝트 뼈대와 CLI 진입점"
```

---

### Task 2: 날짜 정규화

**Files:**
- Create: `nara/dates.py`
- Test: `tests/test_dates.py`

**Interfaces:**
- Consumes: 없음
- Produces: `to_iso_date(value: str) -> str`, `to_display_date(iso: str) -> str`

API가 주는 날짜는 `202609151030`(12자리)·`20260915`(8자리)·`2026-09-15 10:30:00` 세 가지 형태로 온다. DB에는 ISO 한 가지로만 넣는다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_dates.py`:

```python
import pytest

from nara.dates import to_display_date, to_iso_date


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("202609151030", "2026-09-15"),
        ("20260915", "2026-09-15"),
        ("2026-09-15 10:30:00", "2026-09-15"),
        ("2026.09.15", "2026-09-15"),
        ("", ""),
        ("미정", ""),
    ],
)
def test_to_iso_date_normalises_known_shapes(raw, expected):
    assert to_iso_date(raw) == expected


def test_to_display_date_uses_dots():
    assert to_display_date("2026-09-15") == "2026.09.15"


def test_to_display_date_passes_through_empty():
    assert to_display_date("") == ""
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `uv run pytest tests/test_dates.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'nara.dates'`

- [ ] **Step 3: 최소 구현**

`nara/dates.py`:

```python
"""API가 주는 여러 날짜 표기를 ISO 한 가지로 모은다."""

import re

_DIGITS = re.compile(r"^(\d{4})(\d{2})(\d{2})")
_SEPARATED = re.compile(r"^(\d{4})[-./](\d{1,2})[-./](\d{1,2})")


def to_iso_date(value: str) -> str:
    """'202609151030' · '20260915' · '2026-09-15 10:30:00' → '2026-09-15'."""
    s = (value or "").strip()
    if not s:
        return ""
    if m := _DIGITS.match(s):
        year, month, day = m.groups()
    elif m := _SEPARATED.match(s):
        year, month, day = m.groups()
    else:
        return ""
    return f"{year}-{int(month):02d}-{int(day):02d}"


def to_display_date(iso: str) -> str:
    """'2026-09-15' → '2026.09.15'. 시트 표기에 맞춘다."""
    return iso.replace("-", ".") if iso else ""
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_dates.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: 커밋**

```bash
git add nara/dates.py tests/test_dates.py
git commit -m "feat: 날짜 문자열 ISO 정규화"
```

---

### Task 3: 설정 로딩

**Files:**
- Create: `config.toml`
- Create: `nara/config.py`
- Create: `.env.example`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: 없음
- Produces: `Settings`, `Secrets`, `load_settings(path: Path) -> Settings`, `load_secrets(env_path: Path | None) -> Secrets`

> **키워드 출처에 대한 사전 판정 (컨트롤러가 이미 확인함 — 다시 조사하지 말 것)**
>
> Apps Script는 키워드를 코드에 두지 않는다. 스프레드시트 `설정` 탭에서 읽고,
> 그 탭이 없을 때만 `DEFAULT_SETTINGS` 상수를 쓴다. 디스크의 `Code.gs`(2026-06-19판)
> 기본값과 스펙 값을 대조한 결과는 이렇다.
>
> | 항목 | Code.gs 기본값 | 아래 config.toml | 판정 |
> |---|---|---|---|
> | 제목 필수 | `['설계']` | 같음 | 일치 |
> | 제목 제외 | 62개 | 68개 (＋상수관·제방·관망·관광지·풍수해·진입로) | 스펙을 따른다 |
> | 수요기관 제외 | 3개 (교육청·교육지원청·개발공사) | 7개 (＋상하수도사업소·공사·경찰청·의료원) | 스펙을 따른다 |
> | 관심 기관 | 16개, 어간 표기(`용인`·`평택`) | 19개, 전체 표기(`용인시`·`평택시`, ＋영천시·남양주시·의왕시) | 스펙을 따른다 |
>
> **아래 값을 그대로 쓴다.** 디스크의 Code.gs는 6월판이고, 스펙은 사용자가 9월에
> 붙여넣은 현행 스크립트에서 뽑아 승인한 것이다. 계획의 Global Constraints도
> "스펙 문서의 값을 그대로 쓴다"로 못박고 있다. 살아 있는 `설정` 탭과의 최종 대조는
> 사용자가 있는 Task 15에서 한다.

- [ ] **Step 1: 설정 파일 작성**


`config.toml` — 확인한 값으로 쓴다:

```toml
[collect]
service_div_name = "기술용역"
skip_cancelled = true
title_required = ["설계"]
title_excluded = [
  "안전점검", "감리", "소방", "전기", "통신", "화장실", "하수관", "건설사업관리",
  "도로", "조사", "진단", "발굴", "기숙사", "개선", "육교", "하수처리", "저수지",
  "교체", "상수도", "하수도", "국도", "수도정비", "관세척", "오염저감", "옥상방수",
  "하천", "영향평가", "성능평가", "검교정", "내진", "배수", "보수정비", "환경개선",
  "교통안전", "산불진화", "슬레이트", "정밀점검", "차고지", "영농편의", "석면",
  "지하수", "폐기물", "용수도", "컨설팅", "하자점검", "타당성", "지방하천", "VE",
  "배관망", "인테리어", "녹지", "개보수", "BF", "측량", "등산로", "철거", "수리시설",
  "가설", "숲길", "트레일", "재해방지", "조림", "상수관", "제방", "관망", "관광지",
  "풍수해", "진입로",
]
org_excluded = ["교육청", "교육지원청", "개발공사", "상하수도사업소", "공사", "경찰청", "의료원"]

[focus]
orgs = [
  "용인시", "영천시", "남양주시", "부산광역시", "대전광역시", "성남시", "의왕시",
  "수원시", "화성시", "평택시", "안성시", "하남시", "군포시", "시흥시", "오산시",
  "파주시", "전라북도", "전북특별자치도", "전주시",
]
```

`.env.example`:

```
G2B_API_KEY=
NAVER_CLIENT_ID=
NAVER_CLIENT_SECRET=
ANTHROPIC_API_KEY=
GOOGLE_SERVICE_ACCOUNT_JSON=
```

- [ ] **Step 2: 실패하는 테스트 작성**

`tests/test_config.py`:

```python
from pathlib import Path

from nara.config import load_secrets, load_settings

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_load_settings_reads_repo_config():
    settings = load_settings(REPO_ROOT / "config.toml")
    assert settings.title_required == ("설계",)
    assert "감리" in settings.title_excluded
    assert "교육청" in settings.org_excluded
    assert "전북특별자치도" in settings.focus_orgs
    assert settings.service_div_name == "기술용역"
    assert settings.skip_cancelled is True


def test_load_settings_keeps_every_focus_org():
    """목록이 잘려서 들어오지 않았는지 본다.

    확인해야 하는 것은 '목록이 잘리지 않았다'이다. 위 판정 표대로 관심 기관 19개,
    제목 제외 68개를 config.toml에 그대로 옮겼으면 그대로 통과한다.
    """
    settings = load_settings(REPO_ROOT / "config.toml")
    assert len(settings.focus_orgs) == 19
    assert len(settings.title_excluded) == 68
    assert len(settings.org_excluded) == 7


def test_load_secrets_reads_env_file(tmp_path):
    env = tmp_path / ".env"
    env.write_text("G2B_API_KEY=abc123\nNAVER_CLIENT_ID=\n", encoding="utf-8")
    secrets = load_secrets(env)
    assert secrets.g2b_api_key == "abc123"
    assert secrets.naver_client_id is None


def test_load_secrets_returns_none_when_file_missing(tmp_path):
    secrets = load_secrets(tmp_path / "nope.env")
    assert secrets.g2b_api_key is None
```

- [ ] **Step 3: 테스트가 실패하는지 확인**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'nara.config'`

- [ ] **Step 4: 최소 구현**

`nara/config.py`:

```python
"""설정과 자격 증명을 읽는다. 설정은 config.toml, 자격 증명은 .env."""

import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    title_required: tuple[str, ...]
    title_excluded: tuple[str, ...]
    org_excluded: tuple[str, ...]
    focus_orgs: tuple[str, ...]
    service_div_name: str
    skip_cancelled: bool


@dataclass(frozen=True)
class Secrets:
    g2b_api_key: str | None
    naver_client_id: str | None
    naver_client_secret: str | None
    anthropic_api_key: str | None


def load_settings(path: Path) -> Settings:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    collect = data.get("collect", {})
    focus = data.get("focus", {})
    return Settings(
        title_required=tuple(collect.get("title_required", [])),
        title_excluded=tuple(collect.get("title_excluded", [])),
        org_excluded=tuple(collect.get("org_excluded", [])),
        focus_orgs=tuple(focus.get("orgs", [])),
        service_div_name=collect.get("service_div_name", "기술용역"),
        skip_cancelled=bool(collect.get("skip_cancelled", True)),
    )


def _read_env(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    pairs = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        pairs[key.strip()] = value.strip()
    return pairs


def load_secrets(env_path: Path | None = None) -> Secrets:
    raw = _read_env(env_path) if env_path else {}
    pick = lambda key: raw.get(key) or None  # noqa: E731
    return Secrets(
        g2b_api_key=pick("G2B_API_KEY"),
        naver_client_id=pick("NAVER_CLIENT_ID"),
        naver_client_secret=pick("NAVER_CLIENT_SECRET"),
        anthropic_api_key=pick("ANTHROPIC_API_KEY"),
    )
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `uv run pytest tests/test_config.py -v`
Expected: PASS (4 passed)

- [ ] **Step 6: 커밋**

```bash
git add config.toml .env.example nara/config.py tests/test_config.py
git commit -m "feat: 설정·자격 증명 로딩"
```

---

### Task 4: 공고 필터

**Files:**
- Create: `nara/filters.py`
- Test: `tests/test_filters.py`

**Interfaces:**
- Consumes: `nara.config.Settings`
- Produces: `title_passes(title, settings) -> bool`, `org_passes(org, settings) -> bool`, `is_focus_org(org, settings) -> bool`

테스트 입력은 2026-09-16 작업에서 실제로 시트에 들어왔거나 걸러진 공고명을 쓴다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_filters.py`:

```python
from pathlib import Path

import pytest

from nara.config import load_settings
from nara.filters import is_focus_org, org_passes, title_passes

SETTINGS = load_settings(Path(__file__).resolve().parents[1] / "config.toml")


@pytest.mark.parametrize(
    "title",
    [
        "고창군 유아친화형 국민체육센터 건립사업 기본 및 실시설계 설계공모",
        "김제시 청소년 복합문화공간 조성사업 건축설계공모",
        "익산 청년문화센터 건립 건축설계 공모",
    ],
)
def test_title_passes_for_building_design_notices(title):
    assert title_passes(title, SETTINGS) is True


def test_title_passes_when_a_near_miss_keyword_appears():
    """제외어는 부분 문자열로만 걸린다. '숲길'은 제외어지만 '도시숲'은 아니다."""
    assert title_passes("2026년 도시숲 조성사업 실시설계 용역", SETTINGS) is True


def test_title_passes_when_keyword_is_a_prefix_only():
    """'보수정비'가 제외어이고 '보수보강'은 아니다."""
    assert title_passes("부곡과선교 보수보강공사 실시설계용역", SETTINGS) is True


@pytest.mark.parametrize(
    "title",
    [
        "남천동 주차타워 건립공사 감리용역",           # 감리
        "학교 기숙사 신축 실시설계용역",               # 기숙사
        "OO지구 지방하천 정비 실시설계",               # 지방하천
        "상수도 관망 정비 실시설계용역",               # 상수도
    ],
)
def test_title_rejected_by_excluded_keyword(title):
    assert title_passes(title, SETTINGS) is False


def test_title_rejected_when_required_keyword_absent():
    assert title_passes("체육관 건립공사 입찰공고", SETTINGS) is False


def test_title_rejected_when_empty():
    assert title_passes("", SETTINGS) is False


@pytest.mark.parametrize(
    "org",
    ["전북특별자치도 완주군", "경기도 용인시", "전북특별자치도 산림환경연구원"],
)
def test_org_passes_for_ordinary_agencies(org):
    assert org_passes(org, SETTINGS) is True


@pytest.mark.parametrize(
    "org",
    ["전북특별자치도교육청", "용인도시공사", "경기도 성남시 상하수도사업소", "충남지방경찰청"],
)
def test_org_rejected_by_excluded_keyword(org):
    assert org_passes(org, SETTINGS) is False


@pytest.mark.parametrize(
    ("org", "expected"),
    [
        ("전북특별자치도 완주군", True),
        ("경기도 용인시 처인구", True),
        ("전라북도 전주시", True),
        ("충청북도 제천시", False),
        ("경상남도 김해시", False),
    ],
)
def test_is_focus_org_matches_by_substring(org, expected):
    assert is_focus_org(org, SETTINGS) is expected
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `uv run pytest tests/test_filters.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'nara.filters'`

- [ ] **Step 3: 최소 구현**

`nara/filters.py`:

```python
"""공고를 받아들일지 결정하는 순수 함수들."""

from nara.config import Settings


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(k and k in text for k in keywords)


def title_passes(title: str, settings: Settings) -> bool:
    """제목 필수 키워드를 하나라도 포함하고 제외 키워드를 하나도 포함하지 않으면 통과."""
    s = (title or "").strip()
    if not s:
        return False
    if settings.title_required and not _contains_any(s, settings.title_required):
        return False
    return not _contains_any(s, settings.title_excluded)


def org_passes(org: str, settings: Settings) -> bool:
    """수요기관 제외 키워드를 포함하지 않으면 통과. 포함 필터는 두지 않는다(전국 수집)."""
    s = (org or "").strip()
    if not s:
        return False
    return not _contains_any(s, settings.org_excluded)


def is_focus_org(org: str, settings: Settings) -> bool:
    """관심 기관 목록의 이름이 수요기관 문자열에 들어 있으면 관심 기관."""
    return _contains_any((org or "").strip(), settings.focus_orgs)
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_filters.py -v`
Expected: PASS

`용인도시공사`가 제외되는 것은 제외어 `공사` 때문이다. 이것은 기존 Apps Script와 같은 동작이며 의도한 결과다.

- [ ] **Step 5: 커밋**

```bash
git add nara/filters.py tests/test_filters.py
git commit -m "feat: 제목·수요기관 필터"
```

---

### Task 5: DB 스키마와 마이그레이션

**Files:**
- Create: `nara/schema.sql`
- Create: `nara/db.py`
- Test: `tests/test_db.py`

`pyproject.toml`은 건드리지 않는다. Task 1에서 이미 맞춰 놨다.

**Interfaces:**
- Consumes: 없음
- Produces: `connect(db_path: Path) -> sqlite3.Connection`, `migrate(conn) -> int`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_db.py`:

```python
from nara.db import connect, migrate

EXPECTED_TABLES = {
    "org", "project", "notice", "award", "status_check", "dept_check",
    "attachment", "energy_plan", "energy_unit_price", "run_log", "app_state",
}


def test_migrate_creates_every_table(tmp_path):
    conn = connect(tmp_path / "test.db")
    migrate(conn)
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert EXPECTED_TABLES <= names


def test_migrate_is_idempotent(tmp_path):
    conn = connect(tmp_path / "test.db")
    first = migrate(conn)
    second = migrate(conn)
    assert first == second


def test_migrate_seeds_unit_prices(tmp_path):
    conn = connect(tmp_path / "test.db")
    migrate(conn)
    rows = dict(conn.execute("SELECT source_type, price_per_kw FROM energy_unit_price"))
    assert rows == {
        "BIPV": 5_000_000,
        "PV": 2_500_000,
        "지열": 2_500_000,
        "PEMFC": 32_000_000,
        "SOFC": 98_250_000,
    }


def test_foreign_keys_are_enforced(tmp_path):
    conn = connect(tmp_path / "test.db")
    migrate(conn)
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `uv run pytest tests/test_db.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'nara.db'`

- [ ] **Step 3: 스키마 작성**

`nara/schema.sql`:

```sql
CREATE TABLE IF NOT EXISTS org (
  id            INTEGER PRIMARY KEY,
  name          TEXT NOT NULL UNIQUE,
  tier          TEXT NOT NULL DEFAULT 'rest',   -- 'focus' | 'rest'
  weekday_group INTEGER,                        -- 1~5, 비관심 기관만
  sheet_tab     TEXT,
  added_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS project (
  id          INTEGER PRIMARY KEY,
  org_id      INTEGER NOT NULL REFERENCES org(id),
  name        TEXT NOT NULL,
  source      TEXT NOT NULL,                    -- 'g2b' | 'manual'
  address     TEXT,
  start_date  TEXT,
  end_date    TEXT,
  floor_area  REAL,
  zeb_grade   TEXT,
  re_ratio    TEXT,
  etc_cert    TEXT,
  guide_equip TEXT,
  note        TEXT,
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_project_org ON project(org_id);

CREATE TABLE IF NOT EXISTS notice (
  bid_no       TEXT PRIMARY KEY,
  bid_ord      TEXT,
  project_id   INTEGER REFERENCES project(id),
  org_id       INTEGER REFERENCES org(id),
  org_name     TEXT NOT NULL,
  title        TEXT NOT NULL,
  kind         TEXT,
  notice_date  TEXT,
  open_date    TEXT,
  close_date   TEXT,
  url          TEXT,
  budget_krw   INTEGER,
  budget_basis TEXT,
  officer_name TEXT,
  officer_tel  TEXT,
  raw_json     TEXT,
  collected_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_notice_open ON notice(open_date);
CREATE INDEX IF NOT EXISTS idx_notice_project ON notice(project_id);
CREATE INDEX IF NOT EXISTS idx_notice_org ON notice(org_id);

CREATE TABLE IF NOT EXISTS award (
  bid_no     TEXT PRIMARY KEY REFERENCES notice(bid_no),
  winner     TEXT,
  award_date TEXT,
  raw_json   TEXT,
  checked_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS status_check (
  id            INTEGER PRIMARY KEY,
  project_id    INTEGER NOT NULL REFERENCES project(id),
  verdict       TEXT NOT NULL,
  reason        TEXT,
  decided_by    TEXT NOT NULL,                  -- 'rule' | 'llm' | 'human' | 'imported'
  evidence_json TEXT,
  checked_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_status_project ON status_check(project_id, checked_at);

CREATE TABLE IF NOT EXISTS dept_check (
  id            INTEGER PRIMARY KEY,
  bid_no        TEXT REFERENCES notice(bid_no),
  project_id    INTEGER REFERENCES project(id),
  exec_dept     TEXT,
  contract_dept TEXT,
  head_tel      TEXT,
  snippet       TEXT,
  source_file   TEXT,
  decided_by    TEXT NOT NULL,
  checked_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS attachment (
  id            INTEGER PRIMARY KEY,
  bid_no        TEXT NOT NULL REFERENCES notice(bid_no),
  filename      TEXT NOT NULL,
  path          TEXT,
  sha256        TEXT,
  text_path     TEXT,
  status        TEXT NOT NULL DEFAULT 'ok',     -- 'ok' | 'failed'
  attempts      INTEGER NOT NULL DEFAULT 0,
  downloaded_at TEXT
);

CREATE TABLE IF NOT EXISTS energy_plan (
  id          INTEGER PRIMARY KEY,
  project_id  INTEGER NOT NULL REFERENCES project(id),
  source_type TEXT NOT NULL,
  capacity_kw REAL NOT NULL,
  entered_by  TEXT NOT NULL,                    -- 'human' | 'doc' | 'imported'
  updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_energy_project ON energy_plan(project_id);

CREATE TABLE IF NOT EXISTS energy_unit_price (
  source_type    TEXT PRIMARY KEY,
  price_per_kw   INTEGER NOT NULL,
  effective_from TEXT
);

CREATE TABLE IF NOT EXISTS run_log (
  id          INTEGER PRIMARY KEY,
  command     TEXT NOT NULL,
  args        TEXT,
  started_at  TEXT NOT NULL,
  finished_at TEXT,
  processed   INTEGER NOT NULL DEFAULT 0,
  updated     INTEGER NOT NULL DEFAULT 0,
  failed      INTEGER NOT NULL DEFAULT 0,
  status      TEXT,                             -- 'ok' | 'partial' | 'error'
  message     TEXT
);

CREATE TABLE IF NOT EXISTS app_state (
  key   TEXT PRIMARY KEY,
  value TEXT
);

INSERT OR IGNORE INTO energy_unit_price (source_type, price_per_kw, effective_from) VALUES
  ('BIPV',   5000000,  '2026-09-16'),
  ('PV',     2500000,  '2026-09-16'),
  ('지열',   2500000,  '2026-09-16'),
  ('PEMFC',  32000000, '2026-09-16'),
  ('SOFC',   98250000, '2026-09-16');
```

- [ ] **Step 4: 마이그레이션 러너 작성**

`nara/db.py`:

```python
"""SQLite 연결과 스키마 적용."""

import sqlite3
from importlib import resources
from pathlib import Path

SCHEMA_VERSION = 1


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def migrate(conn: sqlite3.Connection) -> int:
    """스키마를 적용하고 버전을 돌려준다. 여러 번 불러도 결과가 같다."""
    sql = resources.files("nara").joinpath("schema.sql").read_text(encoding="utf-8")
    conn.executescript(sql)
    conn.execute(
        "INSERT INTO app_state (key, value) VALUES ('schema_version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (str(SCHEMA_VERSION),),
    )
    conn.commit()
    return SCHEMA_VERSION
```

`schema.sql`은 `importlib.resources`로 읽는다. `uv run`은 소스에서 바로 돌기 때문에 별도 패키징 설정 없이 찾아진다. 빌드 백엔드 설정은 Task 1의 `pyproject.toml`에 이미 있다.

- [ ] **Step 5: 테스트 통과 확인**

Run: `uv run pytest tests/test_db.py -v`
Expected: PASS (4 passed)

- [ ] **Step 6: 커밋**

```bash
git add nara/schema.sql nara/db.py tests/test_db.py
git commit -m "feat: SQLite 스키마와 마이그레이션"
```

---

### Task 6: 목록 API 클라이언트

**Files:**
- Create: `nara/g2b/__init__.py`
- Create: `nara/g2b/common.py`
- Create: `nara/g2b/list_api.py`
- Test: `tests/test_list_api.py`
- Test fixture: `tests/fixtures/list_page1.json`

**Interfaces:**
- Consumes: `nara.dates.to_iso_date`
- Produces:
  - `nara.g2b.common`: `G2BError`, `text(value) -> str`, `to_int(value) -> int | None`, `normalise_items(field) -> list[dict]`, `explain_xml(body) -> str`, `check_response(response) -> dict` — Task 10의 낙찰 API도 이 함수들을 그대로 쓴다
  - `nara.g2b.list_api`: `NoticeItem`, `fetch_notice_page(client, api_key, begin, end, page, rows) -> tuple[list[NoticeItem], int]`, `iter_notices(client, api_key, begin, end, rows=500, max_pages=60) -> Iterator[NoticeItem]`

인증 실패와 트래픽 초과는 HTTP 200에 XML 본문으로 오므로 반드시 잡아야 한다.

- [ ] **Step 1: 픽스처 작성**

`tests/fixtures/list_page1.json`:

```json
{
  "response": {
    "header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE."},
    "body": {
      "pageNo": 1, "numOfRows": 2, "totalCount": 3,
      "items": [
        {
          "bidNtceNo": "R26BK01418098", "bidNtceOrd": "0",
          "dminsttNm": "전북특별자치도 고창군",
          "bidNtceNm": "고창군 유아친화형 국민체육센터 건립사업 기본 및 실시설계 설계공모",
          "srvceDivNm": "기술용역", "ntceKindNm": "등록공고",
          "bidNtceDt": "202603241000", "opengDt": "202605081100", "bidClseDt": "202605071800",
          "bidNtceDtlUrl": "https://www.g2b.go.kr/link/PNPE027_01/single/?bidPbancNo=R26BK01418098&bidPbancOrd=000",
          "presmptPrce": "804280909", "asignBdgtAmt": "900000000",
          "ntceInsttOfclNm": "홍길동", "ntceInsttOfclTelNo": "063-560-2000"
        },
        {
          "bidNtceNo": "R26BK01462347", "bidNtceOrd": "0",
          "dminsttNm": "경기도 용인시",
          "bidNtceNm": "공공업무시설 신축사업(토목) 실시설계용역",
          "srvceDivNm": "기술용역", "ntceKindNm": "등록공고",
          "bidNtceDt": "20260414", "opengDt": "20260414", "bidClseDt": "",
          "bidNtceUrl": "", "presmptPrce": "", "asignBdgtAmt": "",
          "ntceInsttOfclNm": "", "ntceInsttOfclTelNo": ""
        }
      ]
    }
  }
}
```

- [ ] **Step 2: 실패하는 테스트 작성**

`tests/test_list_api.py`:

```python
import json
from datetime import datetime
from pathlib import Path

import httpx
import pytest

from nara.g2b.common import G2BError
from nara.g2b.list_api import fetch_notice_page, iter_notices

FIXTURES = Path(__file__).parent / "fixtures"
PAGE1 = json.loads((FIXTURES / "list_page1.json").read_text(encoding="utf-8"))
BEGIN = datetime(2026, 3, 1, 0, 0)
END = datetime(2026, 3, 4, 0, 0)


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_fetch_notice_page_parses_items_and_total():
    with _client(lambda req: httpx.Response(200, json=PAGE1)) as client:
        items, total = fetch_notice_page(client, "KEY", BEGIN, END, page=1, rows=2)
    assert total == 3
    assert [i.bid_no for i in items] == ["R26BK01418098", "R26BK01462347"]


def test_fetch_notice_page_normalises_dates():
    with _client(lambda req: httpx.Response(200, json=PAGE1)) as client:
        items, _ = fetch_notice_page(client, "KEY", BEGIN, END, page=1, rows=2)
    assert items[0].notice_date == "2026-03-24"
    assert items[0].open_date == "2026-05-08"
    assert items[1].close_date == ""


def test_fetch_notice_page_prefers_estimated_price():
    with _client(lambda req: httpx.Response(200, json=PAGE1)) as client:
        items, _ = fetch_notice_page(client, "KEY", BEGIN, END, page=1, rows=2)
    assert items[0].budget_krw == 804280909
    assert items[0].budget_basis == "추정가격"
    assert items[1].budget_krw is None
    assert items[1].budget_basis == ""


def test_fetch_notice_page_builds_url_when_api_omits_it():
    with _client(lambda req: httpx.Response(200, json=PAGE1)) as client:
        items, _ = fetch_notice_page(client, "KEY", BEGIN, END, page=1, rows=2)
    assert items[1].url == (
        "https://www.g2b.go.kr/link/PNPE027_01/single/"
        "?bidPbancNo=R26BK01462347&bidPbancOrd=000"
    )


def test_fetch_notice_page_keeps_raw_payload():
    with _client(lambda req: httpx.Response(200, json=PAGE1)) as client:
        items, _ = fetch_notice_page(client, "KEY", BEGIN, END, page=1, rows=2)
    assert items[0].raw["srvceDivNm"] == "기술용역"


def test_fetch_notice_page_raises_on_xml_error_body():
    xml = (
        "<OpenAPI_ServiceResponse><cmmMsgHeader>"
        "<returnAuthMsg>SERVICE_KEY_IS_NOT_REGISTERED_ERROR</returnAuthMsg>"
        "<returnReasonCode>30</returnReasonCode>"
        "</cmmMsgHeader></OpenAPI_ServiceResponse>"
    )
    with _client(lambda req: httpx.Response(200, text=xml)) as client:
        with pytest.raises(G2BError, match="SERVICE_KEY_IS_NOT_REGISTERED_ERROR"):
            fetch_notice_page(client, "KEY", BEGIN, END, page=1, rows=2)


def test_fetch_notice_page_raises_on_bad_result_code():
    bad = {"response": {"header": {"resultCode": "22", "resultMsg": "LIMITED NUMBER OF SERVICE REQUESTS"}}}
    with _client(lambda req: httpx.Response(200, json=bad)) as client:
        with pytest.raises(G2BError, match="22"):
            fetch_notice_page(client, "KEY", BEGIN, END, page=1, rows=2)


def test_iter_notices_stops_when_total_reached():
    page2 = json.loads(json.dumps(PAGE1))
    page2["response"]["body"]["pageNo"] = 2
    page2["response"]["body"]["items"] = [PAGE1["response"]["body"]["items"][0]]
    pages = {1: PAGE1, 2: page2}
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(dict(request.url.params)["pageNo"])
        seen.append(page)
        return httpx.Response(200, json=pages[page])

    with _client(handler) as client:
        items = list(iter_notices(client, "KEY", BEGIN, END, rows=2))
    assert len(items) == 3
    assert seen == [1, 2]


def test_iter_notices_honours_max_pages():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=PAGE1)

    with _client(handler) as client:
        items = list(iter_notices(client, "KEY", BEGIN, END, rows=2, max_pages=2))
    assert len(items) == 4
```

- [ ] **Step 3: 테스트가 실패하는지 확인**

Run: `uv run pytest tests/test_list_api.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'nara.g2b'`

- [ ] **Step 4: 최소 구현**

`nara/g2b/__init__.py`: 빈 파일

`nara/g2b/common.py` — 목록 API와 낙찰 API가 함께 쓰는 부분:

```python
"""나라장터 OpenAPI 공통 처리.

인증 실패와 트래픽 초과는 HTTP 200에 XML 본문으로 온다. JSON 파싱 전에 반드시 걸러야 한다.
"""

import re

import httpx


class G2BError(RuntimeError):
    """API가 오류를 돌려줬을 때."""


def text(value) -> str:
    return "" if value is None else str(value).strip()


def to_int(value) -> int | None:
    s = text(value).replace(",", "")
    if not s:
        return None
    try:
        n = int(float(s))
    except ValueError:
        return None
    return n if n > 0 else None


def normalise_items(field) -> list[dict]:
    """items가 리스트일 때도 {'item': ...}일 때도 리스트로 맞춘다."""
    items = field or []
    if isinstance(items, dict):
        items = items.get("item", [])
    if isinstance(items, dict):
        items = [items]
    return list(items)


def explain_xml(body: str) -> str:
    for pattern in (r"<returnAuthMsg>([^<]*)<", r"<errMsg>([^<]*)<", r"<resultMsg>([^<]*)<"):
        if m := re.search(pattern, body):
            return m.group(1).strip()
    return body[:200]


def check_response(response: httpx.Response) -> dict:
    """오류면 G2BError를 올리고, 정상이면 response.body 딕셔너리를 돌려준다."""
    body_text = response.text.lstrip("﻿").strip()
    if response.status_code != 200:
        raise G2BError(f"HTTP {response.status_code}: {body_text[:200]}")
    if body_text.startswith("<"):
        raise G2BError(explain_xml(body_text))

    payload = response.json()
    header = payload.get("response", {}).get("header", {})
    code = text(header.get("resultCode"))
    if code and code not in {"00", "0"}:
        raise G2BError(f"resultCode={code} {text(header.get('resultMsg'))}")
    return payload.get("response", {}).get("body") or {}
```

`nara/g2b/list_api.py`:

```python
"""나라장터 입찰공고정보서비스 — 용역 공고 목록."""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime

import httpx

from nara.dates import to_iso_date
from nara.g2b.common import check_response, normalise_items, text, to_int

BASE_URL = (
    "https://apis.data.go.kr/1230000/ad/BidPublicInfoService"
    "/getBidPblancListInfoServcPPSSrch"
)
DETAIL_URL = "https://www.g2b.go.kr/link/PNPE027_01/single/"


@dataclass(frozen=True)
class NoticeItem:
    bid_no: str
    bid_ord: str
    org_name: str
    title: str
    service_div: str
    kind: str
    notice_date: str
    open_date: str
    close_date: str
    url: str
    budget_krw: int | None
    budget_basis: str
    officer_name: str
    officer_tel: str
    raw: dict


def _budget(raw: dict) -> tuple[int | None, str]:
    if (n := to_int(raw.get("presmptPrce"))) is not None:
        return n, "추정가격"
    if (n := to_int(raw.get("asignBdgtAmt"))) is not None:
        return n, "배정예산"
    return None, ""


def _url(raw: dict) -> str:
    if url := (text(raw.get("bidNtceDtlUrl")) or text(raw.get("bidNtceUrl"))):
        return url
    bid_no = text(raw.get("bidNtceNo"))
    if not bid_no:
        return ""
    ord_ = f"{text(raw.get('bidNtceOrd')) or '0':0>3}"
    return f"{DETAIL_URL}?bidPbancNo={bid_no}&bidPbancOrd={ord_}"


def _to_item(raw: dict) -> NoticeItem:
    budget, basis = _budget(raw)
    return NoticeItem(
        bid_no=text(raw.get("bidNtceNo")),
        bid_ord=text(raw.get("bidNtceOrd")),
        org_name=text(raw.get("dminsttNm")),
        title=text(raw.get("bidNtceNm")),
        service_div=text(raw.get("srvceDivNm")),
        kind=text(raw.get("ntceKindNm")),
        notice_date=to_iso_date(text(raw.get("bidNtceDt"))),
        open_date=to_iso_date(text(raw.get("opengDt"))),
        close_date=to_iso_date(text(raw.get("bidClseDt"))),
        url=_url(raw),
        budget_krw=budget,
        budget_basis=basis,
        officer_name=text(raw.get("ntceInsttOfclNm")),
        officer_tel=text(raw.get("ntceInsttOfclTelNo")),
        raw=raw,
    )


def _stamp(dt: datetime) -> str:
    return dt.strftime("%Y%m%d%H%M")


def fetch_notice_page(
    client: httpx.Client,
    api_key: str,
    begin: datetime,
    end: datetime,
    page: int,
    rows: int,
) -> tuple[list[NoticeItem], int]:
    """한 페이지를 읽어 (항목, 전체 건수)를 돌려준다."""
    response = client.get(
        BASE_URL,
        params={
            "serviceKey": api_key,
            "type": "json",
            "inqryDiv": "1",
            "inqryBgnDt": _stamp(begin),
            "inqryEndDt": _stamp(end),
            "pageNo": str(page),
            "numOfRows": str(rows),
        },
        timeout=30.0,
    )
    body = check_response(response)
    items = [_to_item(raw) for raw in normalise_items(body.get("items"))]
    return items, int(body.get("totalCount") or 0)


def iter_notices(
    client: httpx.Client,
    api_key: str,
    begin: datetime,
    end: datetime,
    rows: int = 500,
    max_pages: int = 60,
) -> Iterator[NoticeItem]:
    """기간 안의 공고를 페이지를 넘겨 가며 전부 돌려준다."""
    page = 1
    while page <= max_pages:
        items, total = fetch_notice_page(client, api_key, begin, end, page, rows)
        if not items:
            return
        yield from items
        if total and page * rows >= total:
            return
        page += 1
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `uv run pytest tests/test_list_api.py -v`
Expected: PASS (9 passed)

- [ ] **Step 6: 커밋**

```bash
git add nara/g2b/ tests/test_list_api.py tests/fixtures/list_page1.json
git commit -m "feat: 나라장터 목록 API 클라이언트"
```

---

### Task 7: 실행 기록과 DB 쓰기 계층

**Files:**
- Create: `nara/runlog.py`
- Create: `nara/store.py`
- Test: `tests/test_store.py`

**Interfaces:**
- Consumes: `nara.db`, `nara.filters.is_focus_org`, `nara.g2b.list_api.NoticeItem`
- Produces:
  - `run_log(conn, command, args) -> ContextManager[RunCounters]` — `RunCounters`는 `processed`·`updated`·`failed` 속성을 가진 가변 객체
  - `upsert_org(conn, name, settings, now) -> int`
  - `ensure_project(conn, org_id, name, source, now) -> int`
  - `upsert_notice(conn, item, org_id, project_id, now) -> bool` — 새 공고면 True
  - `last_run(conn, command) -> sqlite3.Row | None`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_store.py`:

```python
import json
from pathlib import Path

import pytest

from nara.config import load_settings
from nara.db import connect, migrate
from nara.g2b.list_api import NoticeItem
from nara.runlog import run_log
from nara.store import ensure_project, last_run, upsert_notice, upsert_org

SETTINGS = load_settings(Path(__file__).resolve().parents[1] / "config.toml")
NOW = "2026-09-17T09:00:00"


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "test.db")
    migrate(c)
    return c


def _item(bid_no="R1", org="전북특별자치도 완주군", title="완주 체육관 실시설계용역") -> NoticeItem:
    return NoticeItem(
        bid_no=bid_no, bid_ord="0", org_name=org, title=title,
        service_div="기술용역", kind="등록공고",
        notice_date="2026-09-01", open_date="2026-09-10", close_date="2026-09-09",
        url="https://example.test/1", budget_krw=100_000_000, budget_basis="추정가격",
        officer_name="", officer_tel="", raw={"bidNtceNo": bid_no},
    )


def test_upsert_org_marks_focus_agency(conn):
    org_id = upsert_org(conn, "전북특별자치도 완주군", SETTINGS, NOW)
    row = conn.execute("SELECT tier, weekday_group FROM org WHERE id = ?", (org_id,)).fetchone()
    assert row["tier"] == "focus"
    assert row["weekday_group"] is None


def test_upsert_org_assigns_weekday_group_to_rest_agency(conn):
    org_id = upsert_org(conn, "충청북도 제천시", SETTINGS, NOW)
    row = conn.execute("SELECT tier, weekday_group FROM org WHERE id = ?", (org_id,)).fetchone()
    assert row["tier"] == "rest"
    assert row["weekday_group"] in {1, 2, 3, 4, 5}


def test_upsert_org_is_idempotent(conn):
    first = upsert_org(conn, "충청북도 제천시", SETTINGS, NOW)
    second = upsert_org(conn, "충청북도 제천시", SETTINGS, NOW)
    assert first == second
    assert conn.execute("SELECT COUNT(*) FROM org").fetchone()[0] == 1


def test_upsert_notice_creates_row_and_reports_new(conn):
    org_id = upsert_org(conn, "전북특별자치도 완주군", SETTINGS, NOW)
    project_id = ensure_project(conn, org_id, "완주 체육관 실시설계용역", "g2b", NOW)
    assert upsert_notice(conn, _item(), org_id, project_id, NOW) is True
    row = conn.execute("SELECT * FROM notice WHERE bid_no = 'R1'").fetchone()
    assert row["title"] == "완주 체육관 실시설계용역"
    assert json.loads(row["raw_json"])["bidNtceNo"] == "R1"


def test_upsert_notice_links_the_org(conn):
    """낙찰 대상 고르기가 org.tier로 걸러지므로 org_id가 반드시 박혀야 한다."""
    org_id = upsert_org(conn, "전북특별자치도 완주군", SETTINGS, NOW)
    project_id = ensure_project(conn, org_id, "완주 체육관 실시설계용역", "g2b", NOW)
    upsert_notice(conn, _item(), org_id, project_id, NOW)
    row = conn.execute("SELECT org_id FROM notice WHERE bid_no = 'R1'").fetchone()
    assert row["org_id"] == org_id


def test_upsert_notice_second_time_reports_not_new(conn):
    org_id = upsert_org(conn, "전북특별자치도 완주군", SETTINGS, NOW)
    project_id = ensure_project(conn, org_id, "완주 체육관 실시설계용역", "g2b", NOW)
    upsert_notice(conn, _item(), org_id, project_id, NOW)
    assert upsert_notice(conn, _item(), org_id, project_id, NOW) is False
    assert conn.execute("SELECT COUNT(*) FROM notice").fetchone()[0] == 1


def test_upsert_notice_does_not_reassign_existing_project(conn):
    org_id = upsert_org(conn, "전북특별자치도 완주군", SETTINGS, NOW)
    first = ensure_project(conn, org_id, "완주 체육관 실시설계용역", "g2b", NOW)
    upsert_notice(conn, _item(), org_id, first, NOW)
    other = ensure_project(conn, org_id, "다른 사업", "g2b", NOW)
    upsert_notice(conn, _item(), org_id, other, NOW)
    row = conn.execute("SELECT project_id FROM notice WHERE bid_no = 'R1'").fetchone()
    assert row["project_id"] == first


def test_run_log_records_success(conn):
    with run_log(conn, "collect", "--days 3") as counters:
        counters.processed = 10
        counters.updated = 4
    row = last_run(conn, "collect")
    assert row["status"] == "ok"
    assert row["processed"] == 10
    assert row["updated"] == 4
    assert row["finished_at"] is not None


def test_run_log_records_error_and_reraises(conn):
    with pytest.raises(ValueError):
        with run_log(conn, "collect", "") as counters:
            counters.processed = 2
            raise ValueError("boom")
    row = last_run(conn, "collect")
    assert row["status"] == "error"
    assert "boom" in row["message"]
    assert row["processed"] == 2
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `uv run pytest tests/test_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'nara.runlog'`

- [ ] **Step 3: 최소 구현**

`nara/runlog.py`:

```python
"""CLI 실행을 run_log 표에 남긴다."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime


@dataclass
class RunCounters:
    processed: int = 0
    updated: int = 0
    failed: int = 0


@contextmanager
def run_log(conn: sqlite3.Connection, command: str, args: str = "") -> Iterator[RunCounters]:
    cursor = conn.execute(
        "INSERT INTO run_log (command, args, started_at) VALUES (?, ?, ?)",
        (command, args, datetime.now().isoformat(timespec="seconds")),
    )
    run_id = cursor.lastrowid
    conn.commit()
    counters = RunCounters()
    try:
        yield counters
    except Exception as exc:
        _finish(conn, run_id, counters, "error", str(exc))
        raise
    status = "partial" if counters.failed else "ok"
    _finish(conn, run_id, counters, status, None)


def _finish(conn, run_id: int, counters: RunCounters, status: str, message: str | None) -> None:
    conn.execute(
        "UPDATE run_log SET finished_at = ?, processed = ?, updated = ?, failed = ?, "
        "status = ?, message = ? WHERE id = ?",
        (
            datetime.now().isoformat(timespec="seconds"),
            counters.processed,
            counters.updated,
            counters.failed,
            status,
            message,
            run_id,
        ),
    )
    conn.commit()
```

`nara/store.py`:

```python
"""DB 읽기·쓰기. SQL은 이 파일에만 둔다."""

import json
import sqlite3

from nara.config import Settings
from nara.filters import is_focus_org
from nara.g2b.list_api import NoticeItem

WEEKDAY_GROUPS = 5


def upsert_org(conn: sqlite3.Connection, name: str, settings: Settings, now: str) -> int:
    """수요기관을 등록하고 id를 돌려준다. 이미 있으면 그대로 둔다."""
    row = conn.execute("SELECT id FROM org WHERE name = ?", (name,)).fetchone()
    if row:
        return row["id"]
    focus = is_focus_org(name, settings)
    cursor = conn.execute(
        "INSERT INTO org (name, tier, weekday_group, added_at) VALUES (?, ?, ?, ?)",
        (name, "focus" if focus else "rest", None, now),
    )
    org_id = cursor.lastrowid
    if not focus:
        conn.execute(
            "UPDATE org SET weekday_group = ? WHERE id = ?",
            (org_id % WEEKDAY_GROUPS + 1, org_id),
        )
    conn.commit()
    return org_id


def ensure_project(conn: sqlite3.Connection, org_id: int, name: str, source: str, now: str) -> int:
    """같은 기관에 같은 이름의 사업이 있으면 그것을, 없으면 새로 만든다."""
    row = conn.execute(
        "SELECT id FROM project WHERE org_id = ? AND name = ?", (org_id, name)
    ).fetchone()
    if row:
        return row["id"]
    cursor = conn.execute(
        "INSERT INTO project (org_id, name, source, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (org_id, name, source, now, now),
    )
    conn.commit()
    return cursor.lastrowid


def upsert_notice(
    conn: sqlite3.Connection,
    item: NoticeItem,
    org_id: int,
    project_id: int,
    now: str,
) -> bool:
    """공고를 넣거나 원본만 갱신한다. 새로 넣었으면 True."""
    existing = conn.execute(
        "SELECT project_id FROM notice WHERE bid_no = ?", (item.bid_no,)
    ).fetchone()
    values = (
        org_id, item.bid_ord, item.org_name, item.title, item.kind,
        item.notice_date, item.open_date, item.close_date, item.url,
        item.budget_krw, item.budget_basis, item.officer_name, item.officer_tel,
        json.dumps(item.raw, ensure_ascii=False), now,
    )
    if existing:
        # 사업 연결은 건드리지 않는다. 사람이 바꿔 놓았을 수 있다.
        conn.execute(
            "UPDATE notice SET org_id=?, bid_ord=?, org_name=?, title=?, kind=?, "
            "notice_date=?, open_date=?, close_date=?, url=?, budget_krw=?, "
            "budget_basis=?, officer_name=?, officer_tel=?, raw_json=?, "
            "collected_at=? WHERE bid_no=?",
            (*values, item.bid_no),
        )
        conn.commit()
        return False

    conn.execute(
        "INSERT INTO notice (bid_no, project_id, org_id, bid_ord, org_name, title, kind, "
        "notice_date, open_date, close_date, url, budget_krw, budget_basis, "
        "officer_name, officer_tel, raw_json, collected_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (item.bid_no, project_id, *values),
    )
    conn.commit()
    return True


def last_run(conn: sqlite3.Connection, command: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM run_log WHERE command = ? ORDER BY id DESC LIMIT 1", (command,)
    ).fetchone()
```

`org_id % 5 + 1`로 요일 그룹을 나누는 이유는 결정적이고 고르기 때문이다. 기관이 늘어도 다시 섞이지 않는다.

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_store.py -v`
Expected: PASS (9 passed)

- [ ] **Step 5: 커밋**

```bash
git add nara/runlog.py nara/store.py tests/test_store.py
git commit -m "feat: 실행 기록과 DB 쓰기 계층"
```

---

### Task 8: 수집 명령

**Files:**
- Create: `nara/collect.py`
- Modify: `nara/cli.py`
- Test: `tests/test_collect.py`

**Interfaces:**
- Consumes: `iter_notices`, `title_passes`, `org_passes`, `upsert_org`, `ensure_project`, `upsert_notice`, `run_log`
- Produces: `collect_range(conn, client, api_key, settings, begin, end, counters) -> int` — 새로 넣은 건수

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_collect.py`:

```python
import json
from datetime import datetime
from pathlib import Path

import httpx
import pytest

from nara.collect import collect_range
from nara.config import load_settings
from nara.db import connect, migrate
from nara.runlog import RunCounters

SETTINGS = load_settings(Path(__file__).resolve().parents[1] / "config.toml")
BEGIN = datetime(2026, 9, 1)
END = datetime(2026, 9, 4)


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "test.db")
    migrate(c)
    return c


def _payload(items):
    return {
        "response": {
            "header": {"resultCode": "00"},
            "body": {"pageNo": 1, "numOfRows": 500, "totalCount": len(items), "items": items},
        }
    }


def _raw(bid_no, org, title, div="기술용역", kind="등록공고"):
    return {
        "bidNtceNo": bid_no, "bidNtceOrd": "0", "dminsttNm": org, "bidNtceNm": title,
        "srvceDivNm": div, "ntceKindNm": kind,
        "bidNtceDt": "20260901", "opengDt": "20260910", "bidClseDt": "20260909",
    }


def _client(items):
    payload = _payload(items)
    return httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload)))


def test_collect_range_stores_passing_notices(conn):
    items = [
        _raw("A1", "전북특별자치도 완주군", "완주 체육관 건립 실시설계용역"),
        _raw("A2", "충청북도 제천시", "제천 도서관 건축설계공모"),
    ]
    with _client(items) as client:
        added = collect_range(conn, client, "KEY", SETTINGS, BEGIN, END, RunCounters())
    assert added == 2
    assert conn.execute("SELECT COUNT(*) FROM notice").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM project").fetchone()[0] == 2


def test_collect_range_drops_non_technical_service(conn):
    items = [_raw("A1", "전북특별자치도 완주군", "완주 체육관 실시설계용역", div="일반용역")]
    with _client(items) as client:
        added = collect_range(conn, client, "KEY", SETTINGS, BEGIN, END, RunCounters())
    assert added == 0


def test_collect_range_drops_cancelled_notice(conn):
    items = [_raw("A1", "전북특별자치도 완주군", "완주 체육관 실시설계용역", kind="취소공고")]
    with _client(items) as client:
        added = collect_range(conn, client, "KEY", SETTINGS, BEGIN, END, RunCounters())
    assert added == 0


def test_collect_range_drops_excluded_title(conn):
    items = [_raw("A1", "전북특별자치도 완주군", "완주 상수도 관망 실시설계용역")]
    with _client(items) as client:
        added = collect_range(conn, client, "KEY", SETTINGS, BEGIN, END, RunCounters())
    assert added == 0


def test_collect_range_drops_excluded_org(conn):
    items = [_raw("A1", "전북특별자치도교육청", "OO학교 증축 실시설계용역")]
    with _client(items) as client:
        added = collect_range(conn, client, "KEY", SETTINGS, BEGIN, END, RunCounters())
    assert added == 0


def test_collect_range_registers_org_tier(conn):
    items = [
        _raw("A1", "전북특별자치도 완주군", "완주 체육관 실시설계용역"),
        _raw("A2", "충청북도 제천시", "제천 도서관 건축설계공모"),
    ]
    with _client(items) as client:
        collect_range(conn, client, "KEY", SETTINGS, BEGIN, END, RunCounters())
    tiers = dict(conn.execute("SELECT name, tier FROM org"))
    assert tiers["전북특별자치도 완주군"] == "focus"
    assert tiers["충청북도 제천시"] == "rest"


def test_collect_range_is_idempotent(conn):
    items = [_raw("A1", "전북특별자치도 완주군", "완주 체육관 실시설계용역")]
    with _client(items) as client:
        first = collect_range(conn, client, "KEY", SETTINGS, BEGIN, END, RunCounters())
        second = collect_range(conn, client, "KEY", SETTINGS, BEGIN, END, RunCounters())
    assert (first, second) == (1, 0)
    assert conn.execute("SELECT COUNT(*) FROM notice").fetchone()[0] == 1


def test_collect_range_counts_processed(conn):
    items = [
        _raw("A1", "전북특별자치도 완주군", "완주 체육관 실시설계용역"),
        _raw("A2", "전북특별자치도교육청", "OO학교 증축 실시설계용역"),
    ]
    counters = RunCounters()
    with _client(items) as client:
        collect_range(conn, client, "KEY", SETTINGS, BEGIN, END, counters)
    assert counters.processed == 2
    assert counters.updated == 1


def test_collect_range_keeps_raw_json(conn):
    items = [_raw("A1", "전북특별자치도 완주군", "완주 체육관 실시설계용역")]
    with _client(items) as client:
        collect_range(conn, client, "KEY", SETTINGS, BEGIN, END, RunCounters())
    raw = json.loads(conn.execute("SELECT raw_json FROM notice").fetchone()[0])
    assert raw["srvceDivNm"] == "기술용역"
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `uv run pytest tests/test_collect.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'nara.collect'`

- [ ] **Step 3: 최소 구현**

`nara/collect.py`:

```python
"""수집 흐름 — API에서 받아 필터를 거쳐 DB에 넣는다."""

import sqlite3
from datetime import datetime

import httpx

from nara.config import Settings
from nara.filters import org_passes, title_passes
from nara.g2b.list_api import NoticeItem, iter_notices
from nara.runlog import RunCounters
from nara.store import ensure_project, upsert_notice, upsert_org


def _accepts(item: NoticeItem, settings: Settings) -> bool:
    if item.service_div != settings.service_div_name:
        return False
    if settings.skip_cancelled and "취소" in item.kind:
        return False
    if not item.bid_no:
        return False
    return title_passes(item.title, settings) and org_passes(item.org_name, settings)


def collect_range(
    conn: sqlite3.Connection,
    client: httpx.Client,
    api_key: str,
    settings: Settings,
    begin: datetime,
    end: datetime,
    counters: RunCounters,
) -> int:
    """기간 안의 공고를 수집한다. 새로 넣은 건수를 돌려준다."""
    now = datetime.now().isoformat(timespec="seconds")
    added = 0
    for item in iter_notices(client, api_key, begin, end):
        counters.processed += 1
        if not _accepts(item, settings):
            continue
        org_id = upsert_org(conn, item.org_name, settings, now)
        project_id = ensure_project(conn, org_id, item.title, "g2b", now)
        if upsert_notice(conn, item, org_id, project_id, now):
            added += 1
            counters.updated += 1
    return added
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_collect.py -v`
Expected: PASS (9 passed)

- [ ] **Step 5: CLI에 collect 명령 연결**

`nara/cli.py`에 더한다:

```python
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx

from nara.collect import collect_range
from nara.config import load_secrets, load_settings
from nara.db import connect, migrate
from nara.runlog import run_log

DEFAULT_DB = Path("data/nara.db")
DEFAULT_CONFIG = Path("config.toml")
DEFAULT_ENV = Path(".env")


def _open_db(db: Path):
    conn = connect(db)
    migrate(conn)
    return conn


@app.command()
def collect(
    days: int = typer.Option(3, min=1, help="오늘로부터 며칠 전까지 조회할지"),
    db: Path = typer.Option(DEFAULT_DB, help="SQLite 경로"),
    config: Path = typer.Option(DEFAULT_CONFIG),
) -> None:
    """최근 N일치 설계용역 공고를 수집한다."""
    settings = load_settings(config)
    secrets = load_secrets(DEFAULT_ENV)
    if not secrets.g2b_api_key:
        typer.echo("G2B_API_KEY가 .env에 없습니다.", err=True)
        raise typer.Exit(code=1)

    end = datetime.now()
    begin = end - timedelta(days=days)
    conn = _open_db(db)
    with run_log(conn, "collect", f"--days {days}") as counters:
        with httpx.Client() as client:
            added = collect_range(
                conn, client, secrets.g2b_api_key, settings, begin, end, counters
            )
    typer.echo(f"수집 완료 — 조회 {counters.processed}건 / 신규 {added}건")
```

- [ ] **Step 6: CLI 도움말 확인**

Run: `uv run nara collect --help`
Expected: 옵션 `--days`·`--db`·`--config`가 보인다

- [ ] **Step 7: 커밋**

```bash
git add nara/collect.py nara/cli.py tests/test_collect.py
git commit -m "feat: 공고 수집 명령"
```

---

### Task 9: 소급 수집

**Files:**
- Modify: `nara/collect.py`
- Modify: `nara/cli.py`
- Test: `tests/test_backfill.py`

**Interfaces:**
- Consumes: `collect_range`, `app_state` 표
- Produces: `backfill(conn, client, api_key, settings, days_back, chunk_days, counters, now=None) -> BackfillResult` — `BackfillResult`는 `added: int`·`cursor: str`·`done: bool`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_backfill.py`:

```python
from datetime import datetime
from pathlib import Path

import httpx
import pytest

from nara.collect import backfill
from nara.config import load_settings
from nara.db import connect, migrate
from nara.runlog import RunCounters

SETTINGS = load_settings(Path(__file__).resolve().parents[1] / "config.toml")
NOW = datetime(2026, 9, 17, 12, 0)


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "test.db")
    migrate(c)
    return c


def _empty_client(calls: list):
    def handler(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        calls.append((params["inqryBgnDt"], params["inqryEndDt"]))
        return httpx.Response(
            200,
            json={"response": {"header": {"resultCode": "00"},
                               "body": {"pageNo": 1, "numOfRows": 500,
                                        "totalCount": 0, "items": []}}},
        )

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_backfill_walks_from_past_to_present_in_chunks(conn):
    calls = []
    with _empty_client(calls) as client:
        result = backfill(conn, client, "KEY", SETTINGS, days_back=9, chunk_days=3,
                          counters=RunCounters(), now=NOW)
    assert result.done is True
    assert [c[0][:8] for c in calls] == ["20260908", "20260911", "20260914"]


def test_backfill_saves_cursor_when_stopped_early(conn):
    calls = []
    with _empty_client(calls) as client:
        result = backfill(conn, client, "KEY", SETTINGS, days_back=9, chunk_days=3,
                          counters=RunCounters(), now=NOW, max_chunks=1)
    assert result.done is False
    assert result.cursor == "2026-09-11"
    saved = conn.execute("SELECT value FROM app_state WHERE key='backfill_cursor'").fetchone()
    assert saved["value"] == "2026-09-11"


def test_backfill_resumes_from_saved_cursor(conn):
    conn.execute("INSERT INTO app_state (key, value) VALUES ('backfill_cursor', '2026-09-14')")
    conn.commit()
    calls = []
    with _empty_client(calls) as client:
        backfill(conn, client, "KEY", SETTINGS, days_back=9, chunk_days=3,
                 counters=RunCounters(), now=NOW)
    assert [c[0][:8] for c in calls] == ["20260914"]


def test_backfill_clears_cursor_when_finished(conn):
    calls = []
    with _empty_client(calls) as client:
        backfill(conn, client, "KEY", SETTINGS, days_back=3, chunk_days=3,
                 counters=RunCounters(), now=NOW)
    assert conn.execute("SELECT value FROM app_state WHERE key='backfill_cursor'").fetchone() is None
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `uv run pytest tests/test_backfill.py -v`
Expected: FAIL — `ImportError: cannot import name 'backfill'`

- [ ] **Step 3: 최소 구현**

`nara/collect.py`에 더한다:

```python
# 파일 맨 위의 import에 더한다 — datetime 줄을 새로 만들지 말고 기존 줄을 넓힌다.
#   from dataclasses import dataclass
#   from datetime import date, datetime, timedelta

CURSOR_KEY = "backfill_cursor"


@dataclass(frozen=True)
class BackfillResult:
    added: int
    cursor: str
    done: bool


def _get_state(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM app_state WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def _set_state(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO app_state (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    conn.commit()


def backfill(
    conn: sqlite3.Connection,
    client: httpx.Client,
    api_key: str,
    settings: Settings,
    days_back: int,
    chunk_days: int,
    counters: RunCounters,
    now: datetime | None = None,
    max_chunks: int | None = None,
) -> BackfillResult:
    """과거 공고를 기간을 쪼개 과거에서 현재 방향으로 수집한다."""
    # CLI는 min=1로 막지만 이 함수는 직접 부를 수 있다. chunk_days가 0 이하면
    # cursor가 전진하지 않아 while 루프가 끝나지 않는다.
    if chunk_days < 1:
        raise ValueError(f"chunk_days는 1 이상이어야 한다: {chunk_days}")
    if days_back < 1:
        raise ValueError(f"days_back은 1 이상이어야 한다: {days_back}")
    now = now or datetime.now()
    floor = (now - timedelta(days=days_back)).date()
    saved = _get_state(conn, CURSOR_KEY)
    cursor = date.fromisoformat(saved) if saved else floor
    cursor = max(cursor, floor)

    added = 0
    chunks = 0
    while cursor < now.date():
        if max_chunks is not None and chunks >= max_chunks:
            _set_state(conn, CURSOR_KEY, cursor.isoformat())
            return BackfillResult(added, cursor.isoformat(), done=False)
        chunk_end = min(cursor + timedelta(days=chunk_days), now.date())
        added += collect_range(
            conn, client, api_key, settings,
            datetime.combine(cursor, datetime.min.time()),
            datetime.combine(chunk_end, datetime.min.time()),
            counters,
        )
        cursor = chunk_end
        chunks += 1
        _set_state(conn, CURSOR_KEY, cursor.isoformat())

    conn.execute("DELETE FROM app_state WHERE key = ?", (CURSOR_KEY,))
    conn.commit()
    return BackfillResult(added, cursor.isoformat(), done=True)
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_backfill.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: CLI에 backfill 명령 연결**

`nara/cli.py`에 더한다:

```python
from nara.collect import backfill as run_backfill


@app.command()
def backfill(
    days: int = typer.Option(365, min=1, help="며칠 전까지 소급할지"),
    chunk: int = typer.Option(3, min=1, help="한 번에 조회할 기간(일)"),
    db: Path = typer.Option(DEFAULT_DB),
    config: Path = typer.Option(DEFAULT_CONFIG),
) -> None:
    """과거 공고를 소급 수집한다. 중단해도 다음 실행에서 이어진다."""
    settings = load_settings(config)
    secrets = load_secrets(DEFAULT_ENV)
    if not secrets.g2b_api_key:
        typer.echo("G2B_API_KEY가 .env에 없습니다.", err=True)
        raise typer.Exit(code=1)

    conn = _open_db(db)
    with run_log(conn, "backfill", f"--days {days}") as counters:
        with httpx.Client() as client:
            result = run_backfill(
                conn, client, secrets.g2b_api_key, settings, days, chunk, counters
            )
    state = "완료" if result.done else f"진행 중 — {result.cursor}까지"
    typer.echo(f"소급 수집 {state} / 신규 {result.added}건")
```

- [ ] **Step 6: 커밋**

```bash
git add nara/collect.py nara/cli.py tests/test_backfill.py
git commit -m "feat: 과거 공고 소급 수집"
```

---

### Task 10: 낙찰업체 조회

**Files:**
- Create: `nara/g2b/award_api.py`
- Create: `nara/award.py`
- Modify: `nara/cli.py`
- Test: `tests/test_award.py`

**Interfaces:**
- Consumes: `nara.g2b.common`(`check_response`·`normalise_items`·`text`·`G2BError`), `nara.store`
- Produces:
  - `AwardItem`, `fetch_award(client, api_key, bid_no) -> AwardItem | None`
  - `pending_award_bid_nos(conn, today: str, tier: str | None, weekday_group: int | None, limit: int) -> list[str]`
  - `update_awards(conn, client, api_key, today, tier, weekday_group, limit, counters) -> int`

개찰일이 아직 안 지난 공고는 조회하지 않는다. 호출 수를 크게 줄인다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_award.py`:

```python
from pathlib import Path

import httpx
import pytest

from nara.award import pending_award_bid_nos, update_awards
from nara.config import load_settings
from nara.db import connect, migrate
from nara.g2b.award_api import fetch_award
from nara.g2b.list_api import NoticeItem
from nara.runlog import RunCounters
from nara.store import ensure_project, upsert_notice, upsert_org

SETTINGS = load_settings(Path(__file__).resolve().parents[1] / "config.toml")
NOW = "2026-09-17T09:00:00"
TODAY = "2026-09-17"


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "test.db")
    migrate(c)
    return c


def _add_notice(conn, bid_no, org, open_date):
    org_id = upsert_org(conn, org, SETTINGS, NOW)
    project_id = ensure_project(conn, org_id, f"{bid_no} 사업", "g2b", NOW)
    item = NoticeItem(
        bid_no=bid_no, bid_ord="0", org_name=org, title=f"{bid_no} 사업",
        service_div="기술용역", kind="등록공고",
        notice_date="2026-09-01", open_date=open_date, close_date="2026-09-09",
        url="", budget_krw=None, budget_basis="", officer_name="", officer_tel="",
        raw={},
    )
    upsert_notice(conn, item, org_id, project_id, NOW)


def _award_payload(winner: str | None):
    items = [] if winner is None else [{"bidwinnrNm": winner, "rgstDt": "2026-09-12 10:00:00"}]
    return {"response": {"header": {"resultCode": "00"},
                         "body": {"pageNo": 1, "numOfRows": 10,
                                  "totalCount": len(items), "items": items}}}


def _client(winner: str | None):
    payload = _award_payload(winner)
    return httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload)))


def test_fetch_award_returns_winner():
    with _client("주식회사 길종합건축사사무소") as client:
        award = fetch_award(client, "KEY", "R1")
    assert award is not None
    assert award.winner == "주식회사 길종합건축사사무소"
    assert award.award_date == "2026-09-12"


def test_fetch_award_returns_none_when_no_result():
    with _client(None) as client:
        assert fetch_award(client, "KEY", "R1") is None


def test_fetch_award_picks_most_recent_entry():
    payload = {"response": {"header": {"resultCode": "00"}, "body": {"items": [
        {"bidwinnrNm": "가건축", "rgstDt": "2026-09-10 10:00:00"},
        {"bidwinnrNm": "나건축", "rgstDt": "2026-09-14 10:00:00"},
    ]}}}
    with httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload))
    ) as client:
        award = fetch_award(client, "KEY", "R1")
    assert award.winner == "나건축"


def test_pending_skips_notices_whose_opening_is_in_the_future(conn):
    _add_notice(conn, "R1", "전북특별자치도 완주군", open_date="2026-09-10")
    _add_notice(conn, "R2", "전북특별자치도 완주군", open_date="2026-12-01")
    assert pending_award_bid_nos(conn, TODAY, None, None, 100) == ["R1"]


def test_pending_filters_by_tier(conn):
    _add_notice(conn, "R1", "전북특별자치도 완주군", open_date="2026-09-10")
    _add_notice(conn, "R2", "충청북도 제천시", open_date="2026-09-10")
    assert pending_award_bid_nos(conn, TODAY, "focus", None, 100) == ["R1"]


def test_pending_filters_by_weekday_group(conn):
    _add_notice(conn, "R1", "충청북도 제천시", open_date="2026-09-10")
    group = conn.execute("SELECT weekday_group FROM org WHERE name='충청북도 제천시'").fetchone()[0]
    assert pending_award_bid_nos(conn, TODAY, "rest", group, 100) == ["R1"]
    other = group % 5 + 1
    assert pending_award_bid_nos(conn, TODAY, "rest", other, 100) == []


def test_pending_excludes_already_recorded_award(conn):
    _add_notice(conn, "R1", "전북특별자치도 완주군", open_date="2026-09-10")
    conn.execute(
        "INSERT INTO award (bid_no, winner, award_date, checked_at) VALUES (?, ?, ?, ?)",
        ("R1", "가건축", "2026-09-12", NOW),
    )
    conn.commit()
    assert pending_award_bid_nos(conn, TODAY, None, None, 100) == []


def test_update_awards_saves_winner(conn):
    _add_notice(conn, "R1", "전북특별자치도 완주군", open_date="2026-09-10")
    counters = RunCounters()
    with _client("가건축") as client:
        updated = update_awards(conn, client, "KEY", TODAY, None, None, 100, counters)
    assert updated == 1
    row = conn.execute("SELECT winner FROM award WHERE bid_no='R1'").fetchone()
    assert row["winner"] == "가건축"


def test_update_awards_leaves_row_absent_when_not_yet_awarded(conn):
    _add_notice(conn, "R1", "전북특별자치도 완주군", open_date="2026-09-10")
    with _client(None) as client:
        updated = update_awards(conn, client, "KEY", TODAY, None, None, 100, RunCounters())
    assert updated == 0
    assert conn.execute("SELECT COUNT(*) FROM award").fetchone()[0] == 0
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `uv run pytest tests/test_award.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'nara.award'`

- [ ] **Step 3: 낙찰 API 클라이언트 작성**

`nara/g2b/award_api.py`:

```python
"""나라장터 낙찰정보서비스 — 용역 낙찰 목록."""

from dataclasses import dataclass

import httpx

from nara.dates import to_iso_date
from nara.g2b.common import check_response, normalise_items, text

BASE_URL = (
    "https://apis.data.go.kr/1230000/as/ScsbidInfoService/getScsbidListSttusServc"
)


@dataclass(frozen=True)
class AwardItem:
    winner: str
    award_date: str
    raw: dict


def _award_date_of(raw: dict) -> str:
    """등록일 우선, 없으면 최종낙찰일. 언제나 ISO 문자열이라 비교가 안전하다."""
    return to_iso_date(text(raw.get("rgstDt"))) or to_iso_date(text(raw.get("fnlSucsfDate")))


def fetch_award(client: httpx.Client, api_key: str, bid_no: str) -> AwardItem | None:
    """공고번호로 낙찰업체를 조회한다. 아직 없으면 None."""
    response = client.get(
        BASE_URL,
        params={
            "serviceKey": api_key,
            "type": "json",
            "inqryDiv": "4",
            "bidNtceNo": bid_no,
            "pageNo": "1",
            "numOfRows": "10",
        },
        timeout=30.0,
    )
    body = check_response(response)
    named = [raw for raw in normalise_items(body.get("items")) if text(raw.get("bidwinnrNm"))]
    if not named:
        return None

    # 정규화한 ISO 날짜로 비교한다. 원문끼리 비교하면 안 된다 — API가 같은 필드를
    # '20260910'과 '2026-09-20 10:00:00' 두 형태로 섞어 주는데, '-'(0x2D)가 숫자보다
    # 작아서 max()가 더 이른 날을 고른다.
    best = max(named, key=_award_date_of)
    return AwardItem(
        winner=text(best.get("bidwinnrNm")),
        award_date=_award_date_of(best),
        raw=best,
    )
```

- [ ] **Step 4: 낙찰 흐름 작성**

`nara/award.py`:

```python
"""낙찰업체 조회 흐름."""

import json
import sqlite3
from datetime import datetime

import httpx

from nara.g2b.award_api import fetch_award
from nara.g2b.common import G2BError
from nara.runlog import RunCounters


def pending_award_bid_nos(
    conn: sqlite3.Connection,
    today: str,
    tier: str | None,
    weekday_group: int | None,
    limit: int,
) -> list[str]:
    """개찰이 지났고 낙찰업체가 아직 없는 공고번호."""
    sql = [
        "SELECT n.bid_no FROM notice n",
        "JOIN org o ON o.id = n.org_id",
        "LEFT JOIN award a ON a.bid_no = n.bid_no",
        "WHERE a.bid_no IS NULL",
        "  AND n.open_date != '' AND n.open_date <= ?",
    ]
    params: list = [today]
    if tier:
        sql.append("  AND o.tier = ?")
        params.append(tier)
    if weekday_group is not None:
        sql.append("  AND o.weekday_group = ?")
        params.append(weekday_group)
    sql.append("ORDER BY n.open_date LIMIT ?")
    params.append(limit)
    return [r["bid_no"] for r in conn.execute("\n".join(sql), params)]


def update_awards(
    conn: sqlite3.Connection,
    client: httpx.Client,
    api_key: str,
    today: str,
    tier: str | None,
    weekday_group: int | None,
    limit: int,
    counters: RunCounters,
) -> int:
    """낙찰업체가 비어 있는 공고를 조회해 채운다. 기록한 건수를 돌려준다."""
    now = datetime.now().isoformat(timespec="seconds")
    updated = 0
    for bid_no in pending_award_bid_nos(conn, today, tier, weekday_group, limit):
        counters.processed += 1
        try:
            award = fetch_award(client, api_key, bid_no)
        except (G2BError, httpx.HTTPError):
            # 한 건이 실패해도 나머지는 계속 본다. 일시적 네트워크 오류 하나가
            # 그 회차의 남은 대기 건을 통째로 날리지 않게 한다.
            counters.failed += 1
            continue
        if award is None:
            continue
        conn.execute(
            "INSERT INTO award (bid_no, winner, award_date, raw_json, checked_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (bid_no, award.winner, award.award_date,
             json.dumps(award.raw, ensure_ascii=False), now),
        )
        conn.commit()
        updated += 1
        counters.updated += 1
    return updated
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `uv run pytest tests/test_award.py -v`
Expected: PASS (9 passed)

- [ ] **Step 6: CLI에 명령 연결**

`nara/cli.py`에 더한다:

```python
from nara.award import update_awards

enrich_app = typer.Typer(help="수집한 공고에 정보를 덧붙인다")
app.add_typer(enrich_app, name="enrich")


@enrich_app.command("award")
def enrich_award(
    tier: str = typer.Option("all", help="focus | rest | all"),
    group: int | None = typer.Option(None, help="비관심 기관 요일 그룹 1~5"),
    limit: int = typer.Option(300, min=1, help="한 번에 조회할 최대 건수"),
    db: Path = typer.Option(DEFAULT_DB),
) -> None:
    """낙찰업체를 조회해 채운다."""
    secrets = load_secrets(DEFAULT_ENV)
    if not secrets.g2b_api_key:
        typer.echo("G2B_API_KEY가 .env에 없습니다.", err=True)
        raise typer.Exit(code=1)

    conn = _open_db(db)
    selected = None if tier == "all" else tier
    with run_log(conn, "enrich award", f"--tier {tier}") as counters:
        with httpx.Client() as client:
            updated = update_awards(
                conn, client, secrets.g2b_api_key, date.today().isoformat(),
                selected, group, limit, counters,
            )
    typer.echo(
        f"낙찰 조회 — 조회 {counters.processed}건 / 기록 {updated}건 / 실패 {counters.failed}건"
    )
```

- [ ] **Step 7: 커밋**

```bash
git add nara/g2b/award_api.py nara/award.py nara/cli.py tests/test_award.py
git commit -m "feat: 낙찰업체 조회"
```

---

### Task 11: 구글 TSV 읽기

**Files:**
- Create: `nara/sheets_tsv.py`
- Test: `tests/test_sheets_tsv.py`

**Interfaces:**
- Consumes: 없음
- Produces: `read_tsv(text: str) -> tuple[list[str], list[list[str]]]` — (헤더, 행 목록). 행은 헤더 길이에 맞춰 채워진다

셀 안에 줄바꿈이 있으면 구글 TSV가 한 행을 두 줄로 내보낸다. 2026-09-16 작업에서 이것을 놓쳐 붙여넣기가 한 칸 밀렸다. 실제로 겪은 입력을 테스트로 박는다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_sheets_tsv.py`:

```python
from nara.sheets_tsv import read_tsv

HEADER = ["수요기관", "공고명", "설치계획내용", "업데이트일시"]


def _tsv(lines: list[str]) -> str:
    return "\n".join(["\t".join(HEADER), *lines])


def test_read_tsv_returns_header_and_rows():
    text = _tsv(["전북특별자치도 완주군\t완주 체육관\tPV: 10kW\t2026.09.16"])
    header, rows = read_tsv(text)
    assert header == HEADER
    assert rows == [["전북특별자치도 완주군", "완주 체육관", "PV: 10kW", "2026.09.16"]]


def test_read_tsv_merges_row_split_by_embedded_newline():
    """설치계획내용 칸의 줄바꿈이 행을 둘로 쪼갠 경우."""
    text = _tsv([
        "전북특별자치도 진안군\t진안고원 마이스테이\t지열 수직밀폐형: 663.988",
        " 태양광 고정식: 113.280\t2026.09.16",
    ])
    _, rows = read_tsv(text)
    assert len(rows) == 1
    assert rows[0][2] == "지열 수직밀폐형: 663.988 태양광 고정식: 113.280"
    assert rows[0][3] == "2026.09.16"


def test_read_tsv_pads_short_final_row():
    text = _tsv(["전북특별자치도 완주군\t완주 체육관"])
    _, rows = read_tsv(text)
    assert rows == [["전북특별자치도 완주군", "완주 체육관", "", ""]]


def test_read_tsv_keeps_blank_rows():
    text = _tsv(["\t\t\t", "전북특별자치도 완주군\t완주 체육관\t\t"])
    _, rows = read_tsv(text)
    assert len(rows) == 2
    assert rows[0] == ["", "", "", ""]


def test_read_tsv_survives_a_blank_line_inside_a_cell():
    """셀 안에 문단 구분용 빈 줄이 있으면 그 물리 줄은 칸이 0개다."""
    text = "\n".join([
        "\t".join(HEADER),
        "전북특별자치도 진안군\t진안고원\t첫 줄",
        "",
        "셋째 줄\t2026.09.16",
    ])
    _, rows = read_tsv(text)
    assert len(rows) == 1
    assert rows[0][2] == "첫 줄 셋째 줄"
    assert rows[0][3] == "2026.09.16"


def test_read_tsv_truncates_a_row_wider_than_the_header():
    """칸이 남으면 자른다 — 헤더에 대응하는 열이 없어 읽을 수 없는 값이다."""
    text = "\n".join([
        "\t".join(HEADER),
        "전북특별자치도 완주군\t완주 체육관\tPV: 10kW\t2026.09.16\t여분",
    ])
    _, rows = read_tsv(text)
    assert len(rows[0]) == len(HEADER)
    assert rows[0][3] == "2026.09.16"


def test_read_tsv_handles_empty_body():
    header, rows = read_tsv("\t".join(HEADER))
    assert header == HEADER
    assert rows == []
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `uv run pytest tests/test_sheets_tsv.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'nara.sheets_tsv'`

- [ ] **Step 3: 최소 구현**

`nara/sheets_tsv.py`:

```python
"""구글시트 TSV 내보내기를 읽는다.

셀 안에 줄바꿈이 있으면 한 행이 두 줄로 나온다. 필드 수가 헤더보다 적은 줄은
다음 줄과 합쳐 원래 행을 되살린다. 이 처리를 빠뜨리면 이후 모든 행이 밀린다.
"""

import csv
import io


def read_tsv(text: str) -> tuple[list[str], list[list[str]]]:
    raw = list(csv.reader(io.StringIO(text), delimiter="\t"))
    if not raw:
        return [], []

    header = raw[0]
    width = len(header)
    rows: list[list[str]] = []

    i = 1
    while i < len(raw):
        row = raw[i]
        while len(row) < width and i + 1 < len(raw):
            nxt = raw[i + 1]
            if not nxt:
                # 셀 안의 빈 줄(문단 구분). 이어붙일 내용이 없으니 삼키고 넘어간다.
                # 이걸 안 막으면 nxt[0]에서 IndexError가 나 이관 전체가 죽는다.
                i += 1
                continue
            row = row[:-1] + [f"{row[-1]} {nxt[0].strip()}".strip()] + nxt[1:]
            i += 1
        # 헤더 길이에 정확히 맞춘다. 모자라면 채우고, 넘치면 자른다 — 넘친 칸은
        # 헤더에 대응하는 열이 없어 어차피 읽히지 않는다.
        rows.append((row + [""] * (width - len(row)))[:width])
        i += 1

    return header, rows
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_sheets_tsv.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: 커밋**

```bash
git add nara/sheets_tsv.py tests/test_sheets_tsv.py
git commit -m "feat: 구글 TSV 읽기 — 줄 분할 병합"
```

---

### Task 12: 설치계획내용 파서와 예상가 계산

**Files:**
- Create: `nara/energy.py`
- Test: `tests/test_energy.py`

**Interfaces:**
- Consumes: 없음
- Produces: `EnergyItem`, `parse_energy_plan(text: str) -> list[EnergyItem]`, `estimate_cost(items, prices: dict[str, int]) -> dict[str, int]`

테스트 입력은 2026-09-16에 시트에 실제로 들어 있던 33개 문자열에서 형태별로 뽑았다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_energy.py`:

```python
import pytest

from nara.energy import EnergyItem, estimate_cost, parse_energy_plan

PRICES = {"BIPV": 5_000_000, "PV": 2_500_000, "지열": 2_500_000,
          "PEMFC": 32_000_000, "SOFC": 98_250_000}


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("PV: 21.96kW BIPV: 72.6kW",
         [EnergyItem("PV", 21.96), EnergyItem("BIPV", 72.6)]),
        ("지열 수직밀폐형 1031.044kW",
         [EnergyItem("지열", 1031.044)]),
        ("PV: 42.24kW 지열 수직밀폐형: 220.938kW",
         [EnergyItem("PV", 42.24), EnergyItem("지열", 220.938)]),
        ("태양광 BIPV: 1,756.800 연료전지 PEMFC: 120.000",
         [EnergyItem("BIPV", 1756.8), EnergyItem("PEMFC", 120.0)]),
        ("태양광 고정식: 337.920",
         [EnergyItem("PV", 337.92)]),
        ("지열: 280.000",
         [EnergyItem("지열", 280.0)]),
        ("PV: 69.12kW PEMFC: 15kW(에스퓨얼셀)",
         [EnergyItem("PV", 69.12), EnergyItem("PEMFC", 15.0)]),
        ("PV: 46.kW BIPV: 41.07kW",
         [EnergyItem("PV", 46.0), EnergyItem("BIPV", 41.07)]),
        ("지열 수직밀폐형: 663.988 태양광 고정식: 113.280",
         [EnergyItem("지열", 663.988), EnergyItem("PV", 113.28)]),
    ],
)
def test_parse_energy_plan_reads_real_sheet_values(text, expected):
    assert parse_energy_plan(text) == expected


def test_parse_energy_plan_does_not_read_bipv_as_pv():
    assert parse_energy_plan("BIPV: 78kW") == [EnergyItem("BIPV", 78.0)]


def test_parse_energy_plan_returns_empty_for_blank():
    assert parse_energy_plan("") == []


def test_parse_energy_plan_returns_empty_when_no_capacity():
    assert parse_energy_plan("설비 계획 미정") == []


def test_parse_energy_plan_skips_zero_capacity():
    assert parse_energy_plan("PV: 0kW") == []


def test_estimate_cost_multiplies_capacity_by_unit_price():
    items = [EnergyItem("PV", 21.96), EnergyItem("BIPV", 72.6)]
    assert estimate_cost(items, PRICES) == {"PV": 54_900_000, "BIPV": 363_000_000}


def test_estimate_cost_matches_unit_price_tab_worked_example():
    """단가 탭에 적힌 예시 계산과 같은 값이 나와야 한다."""
    assert estimate_cost([EnergyItem("BIPV", 21.21)], PRICES) == {"BIPV": 106_050_000}
    assert estimate_cost([EnergyItem("PV", 117.18)], PRICES) == {"PV": 292_950_000}
    assert estimate_cost([EnergyItem("지열", 247.046)], PRICES) == {"지열": 617_615_000}


def test_estimate_cost_skips_unknown_source():
    assert estimate_cost([EnergyItem("풍력", 100.0)], PRICES) == {}
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `uv run pytest tests/test_energy.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'nara.energy'`

- [ ] **Step 3: 최소 구현**

`nara/energy.py`:

```python
"""설치계획내용 문자열을 에너지원·용량으로 쪼개고 예상가를 계산한다."""

import re
from dataclasses import dataclass

# 긴 표기를 먼저 바꿔야 '태양광 BIPV'가 PV로 새지 않는다.
_ALIASES = (
    ("태양광 BIPV", "BIPV"),
    ("태양광BIPV", "BIPV"),
    ("연료전지 PEMFC", "PEMFC"),
    ("연료전지 SOFC", "SOFC"),
    ("태양광 고정식", "PV"),
    ("태양광고정식", "PV"),
    ("태양광", "PV"),
    ("지열 수직밀폐형", "지열"),
    ("지열수직밀폐형", "지열"),
)

# (?<![A-Z]) 로 BIPV 안의 PV를 걸러낸다.
_TOKEN = re.compile(r"(BIPV|(?<![A-Z])PV|지열|PEMFC|SOFC)\s*:?\s*([\d,]+(?:\.\d*)?)")


@dataclass(frozen=True)
class EnergyItem:
    source_type: str
    capacity_kw: float


def parse_energy_plan(text: str) -> list[EnergyItem]:
    """'PV: 21.96kW BIPV: 72.6kW' → [EnergyItem('PV', 21.96), EnergyItem('BIPV', 72.6)]"""
    s = text or ""
    for old, new in _ALIASES:
        s = s.replace(old, new)

    items = []
    for source, number in _TOKEN.findall(s):
        capacity = float(number.rstrip(".").replace(",", ""))
        if capacity > 0:
            items.append(EnergyItem(source, capacity))
    return items


def estimate_cost(items: list[EnergyItem], prices: dict[str, int]) -> dict[str, int]:
    """에너지원별 예상가. 단가표에 없는 에너지원은 뺀다."""
    totals: dict[str, int] = {}
    for item in items:
        if item.source_type not in prices:
            continue
        cost = round(item.capacity_kw * prices[item.source_type])
        totals[item.source_type] = totals.get(item.source_type, 0) + cost
    return totals
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_energy.py -v`
Expected: PASS (16 passed)

- [ ] **Step 5: 커밋**

```bash
git add nara/energy.py tests/test_energy.py
git commit -m "feat: 설치계획내용 파서와 예상가 계산"
```

---

### Task 13: 기존 시트 이관

**Files:**
- Create: `nara/migrate_sheets.py`
- Modify: `nara/cli.py`
- Test: `tests/test_migrate_sheets.py`

**Interfaces:**
- Consumes: `read_tsv`, `parse_energy_plan`, `upsert_org`, `ensure_project`, `to_iso_date`
- Produces: `COLUMNS`(논리 이름 → 시트 헤더 문자열), `ImportStats`(`rows`·`imported`·`notices`·`projects`·`energy`·`status`·`dept`·`skipped`·`skipped_with_data`), `import_tab(conn, tab_name, text, settings, now, counters=None) -> ImportStats`

시트 한 탭의 TSV 본문을 받아 DB에 흩뿌린다. 시트를 직접 내려받는 부분은 계획 3의 Sheets API 작업에서 붙인다. 지금은 파일로 받은 TSV를 넣는다.

`rows`는 헤더를 뺀 전체 데이터 행 수, `imported`는 사업까지 이어진 행 수다. 스펙이 요구하는 "시트 행 수와 DB 건수 대조"가 `rows == imported + skipped`로 확인된다.

`notices`·`projects`가 아니라 `imported`로 대조하는 이유가 있다. 그 둘은 **새로 만든** 건수라 같은 탭을 다시 넣으면 0이 되고, 정상적인 재실행이 대조 실패로 보인다.

- [ ] **Step 1: 실제 탭의 헤더를 확인한다**

아래 `COLUMNS`는 2026-09-16 작업 때 본 전북 탭 기준이다. 헤더가 한 글자라도 다르면 그 열은 조용히 빈칸으로 들어온다. 붙이기 전에 실제 헤더를 본다.

브라우저 탭을 이 주소로 보내면 크롬이 `~/Downloads`에 받아준다(시트 안에서 `fetch`를 쓰면 CSP에 막힌다):

```
https://docs.google.com/spreadsheets/d/1rFLfePqiaLVONf4HR7MLY6sbLovIklsv42I5T21EUw0/export?format=tsv&gid=1580636670
```

받은 파일의 첫 줄을 찍어 `COLUMNS`의 값과 대조한다:

```bash
head -1 ~/Downloads/*.tsv | tr '\t' '\n' | cat -n
```

다르면 `COLUMNS`의 오른쪽 값만 고친다. 논리 키(`org`·`title`·…)와 아래 테스트는 건드리지 않는다. 탭마다 헤더가 다르면 그 사실을 적어 두고 Step 6에서 탭별로 확인한다.

`COLUMNS`에 없는 열은 그냥 버려진다. 스펙이 `project`에 두기로 한 항목 중 실제 탭에 열이 있는 것(연면적, 신재생 공급의무비율, 기타 인증요건, 지침서 명시 설비)을 여기서 확인해 `COLUMNS`와 `import_tab`의 `UPDATE project`에 함께 넣는다. 열이 없으면 넣지 않고 그 사실을 커밋 메시지에 적는다.

- [ ] **Step 2: 실패하는 테스트 작성**

`tests/test_migrate_sheets.py`:

```python
from pathlib import Path

import pytest

from nara.config import load_settings
from nara.db import connect, migrate
from nara.migrate_sheets import import_tab

SETTINGS = load_settings(Path(__file__).resolve().parents[1] / "config.toml")
NOW = "2026-09-17T09:00:00"

HEADER = [
    "수요기관", "공고명", "주소", "착공일", "준공(예정)일", "담당부서",
    "낙찰업체 설계사무소", "예정공사비", "진행현황", "설치계획내용",
    "업데이트일시", "공고번호", "ZEB 인증등급",
]


def _tsv(rows: list[list[str]]) -> str:
    return "\n".join(["\t".join(HEADER), *["\t".join(r) for r in rows]])


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "test.db")
    migrate(c)
    return c


def test_import_tab_creates_notice_for_row_with_bid_number(conn):
    text = _tsv([[
        "전북특별자치도 완주군", "완주 체육관 실시설계용역", "", "", "", "",
        "가건축사사무소", "100,000,000원(추정가격)", "착공 전(설계 단계) - 낙찰",
        "", "2026.09.16", "R26BK01418098", "",
    ]])
    stats = import_tab(conn, "전북특별자치도", text, SETTINGS, NOW)
    assert stats.notices == 1
    assert conn.execute("SELECT COUNT(*) FROM notice").fetchone()[0] == 1
    assert conn.execute("SELECT winner FROM award").fetchone()["winner"] == "가건축사사무소"


def test_import_tab_links_the_org_on_imported_notices(conn):
    """org_id가 비면 이관된 공고가 낙찰 조회 대상에서 빠진다."""
    text = _tsv([[
        "전북특별자치도 완주군", "완주 체육관 실시설계용역", "", "", "", "",
        "", "", "", "", "", "R1", "",
    ]])
    import_tab(conn, "전북특별자치도", text, SETTINGS, NOW)
    org_id = conn.execute("SELECT id FROM org WHERE name = ?", ("전북특별자치도 완주군",)).fetchone()[0]
    assert conn.execute("SELECT org_id FROM notice WHERE bid_no = 'R1'").fetchone()[0] == org_id


def test_import_tab_creates_manual_project_for_row_without_bid_number(conn):
    text = _tsv([[
        "전북특별자치도 고창군", "고창터미널",
        "전북특별자치도 고창군 고창읍 중앙로 191", "20270311", "20270312", "건설과",
        "", "", "", "지열 수직밀폐형 1031.044kW", "", "", "",
    ]])
    stats = import_tab(conn, "전북특별자치도", text, SETTINGS, NOW)
    assert stats.projects == 1
    assert conn.execute("SELECT COUNT(*) FROM notice").fetchone()[0] == 0
    row = conn.execute("SELECT source, address, start_date, end_date FROM project").fetchone()
    assert row["source"] == "manual"
    assert row["address"] == "전북특별자치도 고창군 고창읍 중앙로 191"
    assert row["start_date"] == "2027-03-11"
    assert row["end_date"] == "2027-03-12"


def test_import_tab_splits_energy_plan_into_rows(conn):
    text = _tsv([[
        "전북특별자치도 고창군", "고창갯벌 센터", "", "", "", "",
        "", "", "", "PV: 21.96kW BIPV: 72.6kW", "", "", "",
    ]])
    stats = import_tab(conn, "전북특별자치도", text, SETTINGS, NOW)
    assert stats.energy == 2
    rows = {r["source_type"]: r["capacity_kw"] for r in
            conn.execute("SELECT source_type, capacity_kw FROM energy_plan")}
    assert rows == {"PV": 21.96, "BIPV": 72.6}


def test_import_tab_records_status_as_imported(conn):
    text = _tsv([[
        "전북특별자치도 완주군", "완주 체육관", "", "", "", "",
        "", "", "시공 중 - 2026.08.28 기공식", "", "", "R1", "",
    ]])
    import_tab(conn, "전북특별자치도", text, SETTINGS, NOW)
    row = conn.execute("SELECT verdict, reason, decided_by FROM status_check").fetchone()
    assert row["verdict"] == "시공 중"
    assert row["reason"] == "2026.08.28 기공식"
    assert row["decided_by"] == "imported"


def test_import_tab_records_department_as_imported(conn):
    text = _tsv([[
        "전북특별자치도 고창군", "고창갯벌 센터", "", "", "", "세계유산과",
        "", "", "", "", "", "", "",
    ]])
    import_tab(conn, "전북특별자치도", text, SETTINGS, NOW)
    row = conn.execute("SELECT exec_dept, decided_by FROM dept_check").fetchone()
    assert row["exec_dept"] == "세계유산과"
    assert row["decided_by"] == "imported"


def test_imported_notice_carries_the_opening_date(conn):
    """open_date가 없으면 Task 10의 낙찰 대기 쿼리에 영영 들어오지 못한다."""
    from nara.award import pending_award_bid_nos

    text = _tsv([[
        "전북특별자치도 완주군", "완주 체육관 실시설계용역", "", "", "", "",
        "", "", "", "", "2026.09.10", "R1", "",
    ]])
    import_tab(conn, "전북특별자치도", text, SETTINGS, NOW)
    got = conn.execute("SELECT open_date FROM notice WHERE bid_no='R1'").fetchone()[0]
    assert got == "2026-09-10"
    assert pending_award_bid_nos(conn, "2026-09-17", None, None, 100) == ["R1"]


def test_import_tab_counts_only_manual_projects_it_created(conn):
    """재이관에서 신규 수기사업은 0이어야 한다. 이미 있던 사업은 새것이 아니다."""
    text = _tsv([[
        "전북특별자치도 고창군", "고창터미널", "", "", "", "",
        "", "", "", "", "", "", "",
    ]])
    assert import_tab(conn, "전북특별자치도", text, SETTINGS, NOW).projects == 1
    assert import_tab(conn, "전북특별자치도", text, SETTINGS, NOW).projects == 0


def test_import_tab_reports_skipped_rows_that_still_held_data(conn):
    """공고명만 빈 행은 조용히 사라지면 안 된다. 대조는 통과해버리기 때문이다."""
    text = _tsv([
        ["", "", "전북특별자치도 고창군 고창읍 중앙로 191", "", "", "건설과",
         "", "1,777억원", "", "지열 1031.044kW", "", "", ""],
        ["", "", "", "", "", "", "", "", "", "", "", "", ""],
    ])
    stats = import_tab(conn, "전북특별자치도", text, SETTINGS, NOW)
    assert stats.skipped == 2
    assert len(stats.skipped_with_data) == 1
    assert "고창읍 중앙로 191" in stats.skipped_with_data[0]


def test_import_tab_advances_counters_row_by_row(conn):
    """중간에 터져도 run_log가 어디까지 갔는지 알 수 있어야 한다."""
    from nara.runlog import RunCounters

    counters = RunCounters()
    text = _tsv([
        ["전북특별자치도 완주군", "A", "", "", "", "", "", "", "", "", "", "", ""],
        ["", "", "", "", "", "", "", "", "", "", "", "", ""],
        ["전북특별자치도 완주군", "B", "", "", "", "", "", "", "", "", "", "", ""],
    ])
    import_tab(conn, "전북특별자치도", text, SETTINGS, NOW, counters)
    assert counters.processed == 3


def test_import_tab_skips_rows_without_org_or_title(conn):
    text = _tsv([["", "", "", "", "", "", "", "", "", "", "", "", ""]])
    stats = import_tab(conn, "전북특별자치도", text, SETTINGS, NOW)
    assert stats.skipped == 1
    assert conn.execute("SELECT COUNT(*) FROM project").fetchone()[0] == 0


def test_import_tab_counts_every_row_for_reconciliation(conn):
    """시트 행 수와 DB 건수 대조가 stats.rows로 성립해야 한다."""
    text = _tsv([
        ["전북특별자치도 완주군", "공고 있는 사업", "", "", "", "",
         "", "", "", "", "", "R1", ""],
        ["전북특별자치도 고창군", "수기 사업", "", "", "", "",
         "", "", "", "", "", "", ""],
        ["", "", "", "", "", "", "", "", "", "", "", "", ""],
    ])
    stats = import_tab(conn, "전북특별자치도", text, SETTINGS, NOW)
    assert stats.rows == 3
    assert stats.imported == 2
    assert stats.rows == stats.imported + stats.skipped


def test_import_tab_reconciles_on_a_second_run(conn):
    """같은 탭을 다시 넣어도 대조가 성립해야 한다. 재실행은 오류가 아니다."""
    text = _tsv([[
        "전북특별자치도 완주군", "완주 체육관", "", "", "", "",
        "", "", "", "", "", "R1", "",
    ]])
    import_tab(conn, "전북특별자치도", text, SETTINGS, NOW)
    again = import_tab(conn, "전북특별자치도", text, SETTINGS, NOW)
    assert again.notices == 0
    assert again.rows == again.imported + again.skipped


def test_import_tab_reads_columns_by_header_not_position(conn):
    """열 순서가 바뀐 탭에서도 헤더 이름으로 찾아야 한다."""
    shuffled = ["공고명", "공고번호", "수요기관", "담당부서"]
    text = "\n".join([
        "\t".join(shuffled),
        "\t".join(["완주 체육관", "R9", "전북특별자치도 완주군", "건설과"]),
    ])
    import_tab(conn, "전북특별자치도", text, SETTINGS, NOW)
    row = conn.execute("SELECT org_name, title FROM notice WHERE bid_no = 'R9'").fetchone()
    assert row["org_name"] == "전북특별자치도 완주군"
    assert row["title"] == "완주 체육관"
    assert conn.execute("SELECT exec_dept FROM dept_check").fetchone()["exec_dept"] == "건설과"


def test_import_tab_merges_row_split_by_embedded_newline(conn):
    text = "\n".join([
        "\t".join(HEADER),
        "전북특별자치도 진안군\t진안고원 마이스테이\t\t\t\t\t\t\t\t지열 수직밀폐형: 663.988",
        " 태양광 고정식: 113.280\t\t\t",
    ])
    stats = import_tab(conn, "전북특별자치도", text, SETTINGS, NOW)
    assert stats.projects == 1
    assert stats.energy == 2


def test_import_tab_is_idempotent(conn):
    text = _tsv([[
        "전북특별자치도 완주군", "완주 체육관 실시설계용역", "", "", "", "",
        "", "", "", "PV: 10kW", "", "R1", "",
    ]])
    import_tab(conn, "전북특별자치도", text, SETTINGS, NOW)
    import_tab(conn, "전북특별자치도", text, SETTINGS, NOW)
    assert conn.execute("SELECT COUNT(*) FROM project").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM energy_plan").fetchone()[0] == 1
```

- [ ] **Step 3: 테스트가 실패하는지 확인**

Run: `uv run pytest tests/test_migrate_sheets.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'nara.migrate_sheets'`

- [ ] **Step 4: 최소 구현**

`nara/migrate_sheets.py`:

```python
"""기존 구글시트 탭을 DB로 옮긴다."""

import sqlite3
from dataclasses import dataclass, field

from nara.config import Settings
from nara.dates import to_iso_date
from nara.energy import parse_energy_plan
from nara.runlog import RunCounters
from nara.sheets_tsv import read_tsv
from nara.store import ensure_project, upsert_org

_VERDICTS = ("준공 완료", "시공 중", "착공 전(설계 단계)", "미확인")

# 논리 이름 → 시트 헤더 문자열. 탭의 헤더가 다르면 여기만 고친다.
COLUMNS = {
    "org": "수요기관",
    "title": "공고명",
    "address": "주소",
    "start_date": "착공일",
    "end_date": "준공(예정)일",
    "dept": "담당부서",
    "winner": "낙찰업체 설계사무소",
    "budget": "예정공사비",
    "status": "진행현황",
    "energy": "설치계획내용",
    "bid_no": "공고번호",
    "open_date": "낙찰일(개찰일)",
    "zeb": "ZEB 인증등급",
}


SKIPPED_PREVIEW_MAX = 10


@dataclass
class ImportStats:
    rows: int = 0
    imported: int = 0
    notices: int = 0
    projects: int = 0
    energy: int = 0
    status: int = 0
    dept: int = 0
    skipped: int = 0
    skipped_with_data: list[str] = field(default_factory=list)


def _split_status(text: str) -> tuple[str, str]:
    """'시공 중 - 2026.08.28 기공식' → ('시공 중', '2026.08.28 기공식')"""
    s = (text or "").strip()
    if not s:
        return "", ""
    head, _, tail = s.partition(" - ")
    for verdict in _VERDICTS:
        if head.strip().startswith(verdict):
            return verdict, tail.strip()
    return "미확인", s


def import_tab(
    conn: sqlite3.Connection,
    tab_name: str,
    text: str,
    settings: Settings,
    now: str,
    counters: RunCounters | None = None,
) -> ImportStats:
    header, rows = read_tsv(text)
    index = {name.strip(): i for i, name in enumerate(header) if name.strip()}
    stats = ImportStats(rows=len(rows))

    def cell(row: list[str], key: str) -> str:
        i = index.get(COLUMNS[key])
        return row[i].strip() if i is not None and i < len(row) else ""

    for row in rows:
        # 행마다 올려 둔다. 중간에 터져도 run_log에 어디까지 갔는지 남는다.
        if counters is not None:
            counters.processed += 1

        org_name = cell(row, "org")
        title = cell(row, "title")
        if not org_name or not title:
            stats.skipped += 1
            # 내용이 있는데 필수 칸만 빈 행은 조용히 사라지면 안 된다.
            filled = [v.strip() for v in row if v.strip()]
            if filled and len(stats.skipped_with_data) < SKIPPED_PREVIEW_MAX:
                stats.skipped_with_data.append(" | ".join(filled)[:120])
            continue
        stats.imported += 1

        org_id = upsert_org(conn, org_name, settings, now)
        bid_no = cell(row, "bid_no")
        source = "g2b" if bid_no else "manual"
        existed = conn.execute(
            "SELECT 1 FROM project WHERE org_id = ? AND name = ?", (org_id, title)
        ).fetchone()
        project_id = ensure_project(conn, org_id, title, source, now)
        if source == "manual" and not existed:
            stats.projects += 1

        conn.execute(
            "UPDATE project SET address = COALESCE(NULLIF(?, ''), address), "
            "start_date = COALESCE(NULLIF(?, ''), start_date), "
            "end_date = COALESCE(NULLIF(?, ''), end_date), "
            "zeb_grade = COALESCE(NULLIF(?, ''), zeb_grade), updated_at = ? WHERE id = ?",
            (
                cell(row, "address"),
                to_iso_date(cell(row, "start_date")),
                to_iso_date(cell(row, "end_date")),
                cell(row, "zeb"),
                now,
                project_id,
            ),
        )

        if bid_no:
            existing = conn.execute(
                "SELECT 1 FROM notice WHERE bid_no = ?", (bid_no,)
            ).fetchone()
            if not existing:
                # open_date를 넣지 않으면 이 공고는 Task 10의 낙찰 대기 쿼리
                # (open_date != '' AND open_date <= today)에 영영 들어오지 못한다.
                conn.execute(
                    "INSERT INTO notice (bid_no, project_id, org_id, org_name, title, "
                    "open_date, budget_basis, collected_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (bid_no, project_id, org_id, org_name, title,
                     to_iso_date(cell(row, "open_date")), cell(row, "budget"), now),
                )
                stats.notices += 1
            if winner := cell(row, "winner"):
                conn.execute(
                    "INSERT OR IGNORE INTO award (bid_no, winner, checked_at) VALUES (?, ?, ?)",
                    (bid_no, winner, now),
                )

        verdict, reason = _split_status(cell(row, "status"))
        if verdict and not conn.execute(
            "SELECT 1 FROM status_check WHERE project_id = ? AND decided_by = 'imported'",
            (project_id,),
        ).fetchone():
            conn.execute(
                "INSERT INTO status_check (project_id, verdict, reason, decided_by, checked_at) "
                "VALUES (?, ?, ?, 'imported', ?)",
                (project_id, verdict, reason, now),
            )
            stats.status += 1

        if dept := cell(row, "dept"):
            if not conn.execute(
                "SELECT 1 FROM dept_check WHERE project_id = ? AND decided_by = 'imported'",
                (project_id,),
            ).fetchone():
                conn.execute(
                    "INSERT INTO dept_check (project_id, bid_no, exec_dept, decided_by, checked_at) "
                    "VALUES (?, ?, ?, 'imported', ?)",
                    (project_id, bid_no or None, dept, now),
                )
                stats.dept += 1

        for item in parse_energy_plan(cell(row, "energy")):
            if conn.execute(
                "SELECT 1 FROM energy_plan WHERE project_id = ? AND source_type = ?",
                (project_id, item.source_type),
            ).fetchone():
                continue
            conn.execute(
                "INSERT INTO energy_plan (project_id, source_type, capacity_kw, "
                "entered_by, updated_at) VALUES (?, ?, ?, 'imported', ?)",
                (project_id, item.source_type, item.capacity_kw, now),
            )
            stats.energy += 1

        conn.commit()

    return stats
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `uv run pytest tests/test_migrate_sheets.py -v`
Expected: PASS (16 passed)

- [ ] **Step 6: CLI에 이관 명령 연결**

`nara/cli.py`에 더한다:

```python
import shutil

from nara.migrate_sheets import import_tab

BACKUP_DIR = Path("data/sheet_backup")

migrate_app = typer.Typer(help="외부 데이터를 가져온다")
app.add_typer(migrate_app, name="migrate")


@migrate_app.command("tsv")
def migrate_tsv(
    path: Path = typer.Argument(..., help="내려받은 시트 탭 TSV 파일"),
    tab: str = typer.Option(..., help="탭 이름"),
    db: Path = typer.Option(DEFAULT_DB),
    config: Path = typer.Option(DEFAULT_CONFIG),
) -> None:
    """시트 탭 TSV 한 개를 DB로 옮긴다. 원본은 그대로 보관한다."""
    settings = load_settings(config)
    conn = _open_db(db)
    now = datetime.now().isoformat(timespec="seconds")

    # 되돌릴 수 있도록 원본을 먼저 복사해 둔다.
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = BACKUP_DIR / f"{stamp}_{tab}.tsv"
    shutil.copy2(path, backup)

    with run_log(conn, "migrate tsv", f"{tab}") as counters:
        stats = import_tab(
            conn, tab, path.read_text(encoding="utf-8"), settings, now, counters
        )
        counters.updated = stats.notices + stats.projects
        counters.failed = stats.skipped

    typer.echo(f"원본 보관: {backup}")
    typer.echo(
        f"[{tab}] 시트 행 {stats.rows} / 처리 {stats.imported} / 신규 공고 {stats.notices} / "
        f"신규 수기사업 {stats.projects} / 설비 {stats.energy} / 진행현황 {stats.status} / "
        f"부서 {stats.dept} / 건너뜀 {stats.skipped}"
    )
    if stats.skipped_with_data:
        typer.echo(
            f"내용이 있는데 수요기관·공고명이 비어 건너뛴 행 "
            f"{len(stats.skipped_with_data)}건:",
            err=True,
        )
        for preview in stats.skipped_with_data:
            typer.echo(f"  {preview}", err=True)
        typer.echo("원본 TSV를 열어 확인한다. 자동으로 채우지 않는다.", err=True)

    accounted = stats.imported + stats.skipped
    if accounted != stats.rows:
        typer.echo(
            f"대조 불일치 — 시트 {stats.rows}행인데 처리한 것은 {accounted}건이다. "
            f"TSV 줄 병합이 잘못됐을 수 있으니 확인한다.",
            err=True,
        )
        raise typer.Exit(code=1)
```

- [ ] **Step 7: 커밋**

```bash
git add nara/migrate_sheets.py nara/cli.py tests/test_migrate_sheets.py
git commit -m "feat: 기존 시트 탭 이관"
```

---

### Task 14: 데이터 점검

**Files:**
- Create: `nara/doctor.py`
- Modify: `nara/cli.py`
- Test: `tests/test_doctor.py`

**Interfaces:**
- Consumes: DB
- Produces: `Finding`(`check: str`, `detail: str`), `run_checks(conn, today: str) -> list[Finding]`

계획 1 범위에서 확인할 수 있는 항목만 넣는다. 진행현황·부서 관련 점검은 계획 2에서 더한다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_doctor.py`:

```python
from pathlib import Path

import pytest

from nara.config import load_settings
from nara.db import connect, migrate
from nara.doctor import AWARD_BATCH_LIMIT, run_checks
from nara.store import ensure_project, upsert_org

SETTINGS = load_settings(Path(__file__).resolve().parents[1] / "config.toml")
NOW = "2026-09-17T09:00:00"
TODAY = "2026-09-17"


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "test.db")
    migrate(c)
    return c


def _notice(conn, bid_no, open_date):
    org_id = upsert_org(conn, "전북특별자치도 완주군", SETTINGS, NOW)
    project_id = ensure_project(conn, org_id, f"{bid_no} 사업", "g2b", NOW)
    conn.execute(
        "INSERT INTO notice (bid_no, project_id, org_name, title, open_date, collected_at) "
        "VALUES (?, ?, '전북특별자치도 완주군', ?, ?, ?)",
        (bid_no, project_id, f"{bid_no} 사업", open_date, NOW),
    )
    conn.commit()
    return project_id


def test_run_checks_is_quiet_on_clean_database(conn):
    _notice(conn, "R1", "2026-09-10")
    assert run_checks(conn, TODAY) == []


def test_run_checks_flags_award_recorded_before_opening(conn):
    _notice(conn, "R1", "2026-12-01")
    conn.execute(
        "INSERT INTO award (bid_no, winner, checked_at) VALUES ('R1', '가건축', ?)", (NOW,)
    )
    conn.commit()
    findings = run_checks(conn, TODAY)
    assert any(f.check == "개찰 전 낙찰" and "R1" in f.detail for f in findings)


def test_run_checks_flags_orphan_project(conn):
    org_id = upsert_org(conn, "전북특별자치도 완주군", SETTINGS, NOW)
    ensure_project(conn, org_id, "공고도 수기 표시도 없는 사업", "g2b", NOW)
    findings = run_checks(conn, TODAY)
    assert any(f.check == "공고 없는 g2b 사업" for f in findings)


def test_run_checks_is_quiet_when_award_backlog_fits_one_batch(conn):
    _notice(conn, "R1", "2026-09-10")
    assert not any(f.check == "낙찰 조회 적체" for f in run_checks(conn, TODAY))


def test_run_checks_flags_award_backlog_larger_than_one_batch(conn):
    """낙찰이 영영 안 나는 건이 쌓이면 최근 공고가 매 회차 뒤로 밀린다."""
    for i in range(AWARD_BATCH_LIMIT + 1):
        _notice(conn, f"R{i}", "2026-09-10")
    hit = [f for f in run_checks(conn, TODAY) if f.check == "낙찰 조회 적체"]
    assert len(hit) == 1
    assert str(AWARD_BATCH_LIMIT + 1) in hit[0].detail


def test_award_backlog_ignores_notices_already_awarded(conn):
    """낙찰이 채워진 건은 적체가 아니다."""
    for i in range(AWARD_BATCH_LIMIT + 1):
        _notice(conn, f"R{i}", "2026-09-10")
        conn.execute(
            "INSERT INTO award (bid_no, winner, checked_at) VALUES (?, '가건축', ?)",
            (f"R{i}", NOW),
        )
    conn.commit()
    assert not any(f.check == "낙찰 조회 적체" for f in run_checks(conn, TODAY))


def test_award_backlog_is_quiet_under_normal_weekly_rotation(conn):
    """비관심 기관은 요일 그룹별로 주 1회 돈다. 전체를 합치면 상한을 넘지만
    실제로 도는 단위별로는 안 넘는다 — 이걸 적체로 잡으면 헛경보다."""
    for group in range(1, 6):
        conn.execute(
            "INSERT INTO org (name, tier, weekday_group, added_at) VALUES (?, 'rest', ?, ?)",
            (f"기관{group}", group, NOW),
        )
        org_id = conn.execute("SELECT id FROM org WHERE name = ?", (f"기관{group}",)).fetchone()[0]
        for i in range(100):
            pid = ensure_project(conn, org_id, f"P{group}-{i}", "g2b", NOW)
            conn.execute(
                "INSERT INTO notice (bid_no, project_id, org_id, org_name, title, "
                "open_date, collected_at) VALUES (?, ?, ?, ?, ?, '2026-09-10', ?)",
                (f"B{group}-{i}", pid, org_id, f"기관{group}", f"P{group}-{i}", NOW),
            )
    conn.commit()
    assert not any(f.check == "낙찰 조회 적체" for f in run_checks(conn, TODAY))


def test_run_checks_flags_a_notice_with_no_org_link(conn):
    """org_id가 비면 낙찰 대기 쿼리에 영영 안 걸린다. 적체 점검도 같은 JOIN을 쓴다."""
    org_id = upsert_org(conn, "전북특별자치도 완주군", SETTINGS, NOW)
    pid = ensure_project(conn, org_id, "연결 끊긴 사업", "g2b", NOW)
    conn.execute(
        "INSERT INTO notice (bid_no, project_id, org_id, org_name, title, "
        "open_date, collected_at) VALUES ('ORPHAN', ?, NULL, '전북특별자치도 완주군', "
        "'연결 끊긴 사업', '2026-09-10', ?)",
        (pid, NOW),
    )
    conn.commit()
    hit = [f for f in run_checks(conn, TODAY) if f.check == "기관 연결 없는 공고"]
    assert len(hit) == 1
    assert "ORPHAN" in hit[0].detail


def test_run_checks_flags_rest_org_without_weekday_group(conn):
    conn.execute(
        "INSERT INTO org (name, tier, weekday_group, added_at) "
        "VALUES ('충청북도 제천시', 'rest', NULL, ?)", (NOW,)
    )
    conn.commit()
    findings = run_checks(conn, TODAY)
    assert any(f.check == "요일 그룹 없는 비관심 기관" for f in findings)
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `uv run pytest tests/test_doctor.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'nara.doctor'`

- [ ] **Step 3: 최소 구현**

`nara/doctor.py`:

```python
"""데이터가 서로 맞는지 훑는다. 고치지는 않고 알리기만 한다."""

import sqlite3
from dataclasses import dataclass


# `nara enrich award --limit`의 기본값과 같아야 한다. 대기가 이 수를 넘으면
# 한 회차가 대기를 다 비우지 못한다.
AWARD_BATCH_LIMIT = 300


@dataclass(frozen=True)
class Finding:
    check: str
    detail: str


def _rows(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    return list(conn.execute(sql, params))


def run_checks(conn: sqlite3.Connection, today: str) -> list[Finding]:
    findings: list[Finding] = []

    for row in _rows(
        conn,
        "SELECT a.bid_no, n.open_date FROM award a JOIN notice n ON n.bid_no = a.bid_no "
        "WHERE n.open_date > ?",
        (today,),
    ):
        findings.append(
            Finding("개찰 전 낙찰", f"{row['bid_no']} — 개찰 {row['open_date']}인데 낙찰업체가 있다")
        )

    for row in _rows(
        conn,
        "SELECT p.id, p.name FROM project p LEFT JOIN notice n ON n.project_id = p.id "
        "WHERE p.source = 'g2b' AND n.bid_no IS NULL",
    ):
        findings.append(Finding("공고 없는 g2b 사업", f"{row['id']} {row['name']}"))

    for row in _rows(
        conn, "SELECT name FROM org WHERE tier = 'rest' AND weekday_group IS NULL"
    ):
        findings.append(Finding("요일 그룹 없는 비관심 기관", row["name"]))

    # 기관에 연결되지 않은 공고는 낙찰 대기 쿼리(org JOIN)에 영영 잡히지 않는다.
    # 아래 적체 점검도 같은 JOIN을 쓰므로, 먼저 여기서 걸러 내지 않으면 사각지대가 된다.
    for row in _rows(
        conn,
        "SELECT bid_no, title FROM notice WHERE org_id IS NULL",
    ):
        findings.append(
            Finding("기관 연결 없는 공고", f"{row['bid_no']} {row['title']} — 낙찰 조회에서 빠진다")
        )

    # 낙찰 대기는 성공해야만 줄어든다. 취소되거나 낙찰 공고가 안 뜬 건은 영영 대기에
    # 남아 한 회차 상한을 잡아먹고, 그런 건이 상한만큼 쌓이면 더 최근 공고는 매번
    # 뒤로 밀려 조회되지 않는다. 조용히 밀리므로 여기서 눈에 보이게 만든다.
    #
    # 실제 조회는 한 덩어리로 돌지 않는다 — 관심 기관은 하루 2회, 비관심 기관은
    # 요일 그룹별로 주 1회다(스펙의 스케줄). 그래서 전체를 합쳐 상한과 비교하면
    # 정상적인 주간 순환 대기까지 적체로 잡혀 헛경보가 된다. 실제로 도는 단위
    # (tier, weekday_group)별로 나눠 센다.
    for row in _rows(
        conn,
        "SELECT o.tier AS tier, o.weekday_group AS grp, COUNT(*) AS n, "
        "MIN(n.open_date) AS oldest "
        "FROM notice n JOIN org o ON o.id = n.org_id "
        "LEFT JOIN award a ON a.bid_no = n.bid_no "
        "WHERE a.bid_no IS NULL AND n.open_date != '' AND n.open_date <= ? "
        "GROUP BY o.tier, o.weekday_group",
        (today,),
    ):
        if row["n"] <= AWARD_BATCH_LIMIT:
            continue
        where = "관심 기관" if row["tier"] == "focus" else f"비관심 기관 요일그룹 {row['grp']}"
        findings.append(
            Finding(
                "낙찰 조회 적체",
                f"{where}: 개찰이 지났는데 낙찰 미확인인 공고가 {row['n']}건이다"
                f"(가장 오래된 개찰일 {row['oldest']}). 한 회차 상한"
                f" {AWARD_BATCH_LIMIT}건을 넘어 최근 공고가 계속 밀릴 수 있다."
                " `nara enrich award --limit`를 키워 한 번 비우거나, 낙찰이 영영"
                " 없을 건을 가려낼 방법이 필요하다.",
            )
        )

    return findings
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_doctor.py -v`
Expected: PASS (9 passed)

- [ ] **Step 5: CLI에 doctor 명령 연결**

`nara/cli.py`에 더한다:

```python
from nara.doctor import run_checks


@app.command()
def doctor(db: Path = typer.Option(DEFAULT_DB, help="SQLite 경로")) -> None:
    """데이터가 서로 맞는지 점검한다. 아무것도 고치지 않는다."""
    # _open_db를 쓰지 않는다. 그건 migrate를 돌려 없는 파일을 만들어 버리므로,
    # --db에 오타를 내면 빈 DB를 새로 만들고 "이상 없음"이라고 답한다.
    # 문제를 시끄럽게 만드는 것이 이 명령의 존재 이유인데 정반대가 된다.
    if not db.exists():
        typer.echo(f"DB 파일이 없다: {db}", err=True)
        raise typer.Exit(code=1)
    conn = connect(db)
    findings = run_checks(conn, date.today().isoformat())
    if not findings:
        typer.echo("점검 통과 — 이상 없음")
        return
    for finding in findings:
        typer.echo(f"[{finding.check}] {finding.detail}")
    typer.echo(f"\n총 {len(findings)}건")
    raise typer.Exit(code=1)
```

- [ ] **Step 6: 커밋**

```bash
git add nara/doctor.py nara/cli.py tests/test_doctor.py
git commit -m "feat: 데이터 점검 명령"
```

---

### Task 15: 실제 자격 증명으로 처음 돌려보기

여기까지는 전부 가짜 응답으로 검증했다. 실제 API로 한 번 돌려 확인한다.

**Files:**
- Create: `README.md`
- Modify: 없음 (오류가 나오면 그때 해당 파일)

- [ ] **Step 1: 커버리지 확인**

Run: `uv run pytest --cov=nara --cov-report=term-missing`
Expected: 전체 통과, `nara` 커버리지 80% 이상.

모자라면 십중팔구 `nara/cli.py`다. 다른 모듈은 Task마다 테스트를 붙였지만 CLI는 `version`만 덮여 있다. `--cov-report=term-missing`이 가리키는 줄을 보고 `tests/test_cli_commands.py`에 CliRunner 테스트를 더한다 — `tmp_path` DB와 `httpx.MockTransport`면 네트워크 없이 `collect`·`enrich award`·`doctor`를 돌릴 수 있다. **커버리지 설정에서 `cli.py`를 빼는 것으로 때우지 않는다.**

- [ ] **Step 2: ruff 통과 확인**

Run: `uv run ruff check . && uv run ruff format --check .`
Expected: 통과. 어기는 부분은 고친다

- [ ] **Step 3: 살아 있는 `설정` 탭과 키워드를 대조한다**

Task 3은 스펙 값으로 갔다. 디스크의 `Code.gs`(6월판) 기본값과는 제목 제외 6개,
수요기관 제외 4개, 관심 기관 3개가 달랐다. 진짜 정답은 스프레드시트의 `설정` 탭이다.

브라우저 탭을 아래로 보내 `설정` 탭을 받는다(`sheet=` 는 탭 이름으로 찾는다):

```
https://docs.google.com/spreadsheets/d/1rFLfePqiaLVONf4HR7MLY6sbLovIklsv42I5T21EUw0/gviz/tq?tqx=out:csv&sheet=설정
```

네 열(`제목 필수 키워드`·`제목 제외 키워드`·`수요기관 포함 키워드`·`수요기관 제외 키워드`)을
`config.toml`과 대조한다. **다르면 시트 쪽을 따르고** `config.toml`을 고친 뒤
`uv run pytest tests/test_config.py`의 개수 단언도 함께 고친다. 무엇이 달랐는지
커밋 메시지에 적는다. 시트에 `설정` 탭이 없으면 현재 값을 그대로 두고 그 사실을 적는다.

- [ ] **Step 4: 인증키 넣기**

기존 Apps Script의 스크립트 속성 `NARAJANGTER_API_KEY` 값을 가져와 `.env`에 넣는다.

```bash
cp .env.example .env
# .env 파일을 열어 G2B_API_KEY= 뒤에 값을 붙여넣는다
```

- [ ] **Step 5: 최근 3일 수집 실행**

Run: `uv run nara collect --days 3`
Expected: `수집 완료 — 조회 N건 / 신규 M건`

오류가 나면 메시지를 보고 판단한다. `SERVICE_KEY_IS_NOT_REGISTERED_ERROR`면 키가 틀렸거나 이 API 활용신청이 승인되지 않은 것이다.

- [ ] **Step 6: 수집 결과 눈으로 확인**

```bash
uv run python -c "
import sqlite3
conn = sqlite3.connect('data/nara.db')
conn.row_factory = sqlite3.Row
print('공고', conn.execute('SELECT COUNT(*) FROM notice').fetchone()[0])
print('기관', conn.execute('SELECT COUNT(*) FROM org').fetchone()[0])
for r in conn.execute('SELECT org_name, title FROM notice LIMIT 5'):
    print(' ', r['org_name'], '|', r['title'][:40])
"
```

Expected: 공고가 0건이 아니고, 제목에 모두 `설계`가 들어 있으며, 수요기관에 교육청·공사가 없다

- [ ] **Step 7: 낙찰 조회 실행**

Run: `uv run nara enrich award --tier focus --limit 20`
Expected: `낙찰 조회 — 조회 N건 / 기록 M건 / 실패 0건`

- [ ] **Step 8: 전북 탭을 실제로 이관한다**

Task 13 Step 1에서 받아 둔 TSV를 넣는다.

```bash
uv run nara migrate tsv ~/Downloads/전북특별자치도.tsv --tab 전북특별자치도
```

Expected: `원본 보관: …` 한 줄과 집계 한 줄. **대조 불일치가 뜨면 멈추고 원인을 찾는다** — 2026-09-16에 행이 밀렸던 지점이 바로 여기다.

수기로 넣은 사업(고창터미널 등)이 `source='manual'`로 들어왔는지 본다:

```bash
uv run python -c "
import sqlite3
conn = sqlite3.connect('data/nara.db')
conn.row_factory = sqlite3.Row
for r in conn.execute(\"SELECT name, address FROM project WHERE source='manual' LIMIT 10\"):
    print(' ', r['name'], '|', r['address'])
print('설비', conn.execute('SELECT COUNT(*) FROM energy_plan').fetchone()[0])
"
```

나머지 탭도 같은 방식으로 하나씩 넣는다. 탭마다 헤더가 다르면 `COLUMNS`를 그 탭에 맞춰 고치고 다시 돌린다.

- [ ] **Step 9: 점검 실행**

Run: `uv run nara doctor`
Expected: `점검 통과 — 이상 없음`. 지적이 나오면 내용을 읽고 진짜 문제인지 판단한다

- [ ] **Step 10: README 작성**

`README.md`:

````markdown
# Nara

나라장터 설계용역 공고를 모아 낙찰업체·진행현황·실행부서를 조사하는 로컬 도구.

설계 문서: `docs/superpowers/specs/2026-09-17-nara-collector-design.md`

## 설치

```bash
uv sync
cp .env.example .env   # G2B_API_KEY를 채운다
```

## 쓰는 법

```bash
uv run nara collect --days 3              # 최근 3일 수집
uv run nara backfill --days 365           # 과거 1년 소급 (중단해도 이어짐)
uv run nara enrich award --tier focus     # 낙찰업체 조회
uv run nara migrate tsv <파일> --tab 전북특별자치도   # 기존 시트 이관
uv run nara doctor                        # 데이터 점검
```

## 개발

```bash
uv run pytest --cov=nara
uv run ruff check .
```
````

- [ ] **Step 11: 커밋**

```bash
git add README.md
git commit -m "docs: README와 첫 실행 확인"
git push
```

---

## 계획 1을 마치면

- 전국 설계용역 공고가 DB에 쌓인다
- 낙찰업체가 자동으로 채워진다
- 기존 시트 데이터가 DB에 들어와 있다
- `nara doctor`가 데이터를 훑는다

**계획 2에서 붙일 것:** 진행현황 판정(규칙 + LLM), 첨부 다운로드와 텍스트 추출, 실행부서 판정, `run slot`·`run org`, 윈도우 작업 스케줄러 등록

**계획 3에서 붙일 것:** 조회 화면, PDF 리포트, Sheets API 내보내기, 시트 직접 내려받기
