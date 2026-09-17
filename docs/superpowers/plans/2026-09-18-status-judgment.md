# 진행현황 판정 구현 계획 (계획 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 수집한 공고의 진행현황을 스스로 판정하고, 근거가 없으면 없다고 말하게 한다.

**Architecture:** 판정 규칙은 I/O가 없는 순수 함수(`verdict.py`)에 모으고, 뉴스 검색(`naver.py`)과 LLM 판정(`llm.py`)은 각각 얇은 클라이언트로 분리한다. 파이프라인(`status.py`)이 셋을 엮고 `award.py`와 같은 모양으로 `run_log`에 흔적을 남긴다. 키가 없으면 그 경로를 건너뛰고 규칙 판정만 남기되, **건너뛰었다는 사실을 출력에 적는다.**

**Tech Stack:** Python 3.14, httpx, Typer, sqlite3(표준 라이브러리), pytest, ruff.
**의존성 1개가 늘어난다: `anthropic`.** Claude 호출은 공식 SDK를 쓴다 — raw HTTP는 SDK가 없는 언어이거나 사용자가 명시적으로 요청할 때만이다. 네이버 검색은 이미 있는 httpx를 쓴다.

**Spec:** `docs/superpowers/specs/2026-09-17-nara-collector-design.md` (3단계 · 진행현황)

## Global Constraints

스펙과 실전 기록에서 그대로 옮긴다. 모든 작업의 요구사항에 이 절이 포함된다.

- **근거 없으면 `미확인`이다. 추정하지 않는다.** 공고일로부터 진행현황을 추론하는 것은 금지다.
- **근거 URL 없는 `준공 완료`·`시공 중` 주장은 `착공 전(설계 단계)`으로 내린다.**
- **철거(멸실)는 착공이 아니다.** `이주 → 철거 → 착공(본공사)` 순서다. 철거 중이면 착공 전이고 오히려 접촉 최적기다. 조사 에이전트가 이걸 착공으로 오판한 사고가 반복됐다.
- **준공예정일이 지났다는 사실만으로 `준공 완료`로 판정하지 않는다.** 지연이 흔하다(Farm&Forest 26.06 → 26.12).
- **개찰일·낙찰일을 착공일로 쓰지 않는다.**
- **판정이 `착공 전`이면 확정 착공일을 기록하지 않는다.** `2027년 착공 예정` 같은 예정 표기만 허용한다.
- **사람이 넣은 착공일·준공일은 고치지 않는다.** 보도와 어긋나면 값을 그대로 두고 불일치 사실만 기록한다.
- `status_check`는 덮어쓰지 않고 한 줄씩 쌓는다. 화면은 최신 것만 본다.
- 판정 어휘는 네 가지로 고정한다: `착공 전(설계 단계)` / `시공 중` / `준공 완료` / `미확인`. 이관된 152건이 이미 이 어휘를 쓴다.
- 네이버 키가 없으면 뉴스 단계를 건너뛰고, Claude 키가 없으면 LLM 단계를 건너뛴다. **둘 다 건너뛴 사실을 CLI 출력에 적는다.** 조용히 넘어가지 않는다.
- 커밋 메시지는 `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`로 끝낸다.
- `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .` 셋 다 통과해야 작업이 끝난 것이다.

## 이 계획이 건드리지 않는 것

- 4단계 부서·첨부 조회(Playwright) — 계획 3
- `nara run slot`과 작업 스케줄러 등록 — 계획 4
- 조회 화면·PDF·시트 내보내기 — 계획 5

---

## File Structure

| 파일 | 책임 |
|---|---|
| `nara/verdict.py` (신규) | 판정 어휘, 규칙 판정, 기사 신호 읽기, 강등, 애매 판정 감지, 기록 여부 결정. **I/O 없음** |
| `nara/naver.py` (신규) | 네이버 뉴스 검색 API 클라이언트. 키 없으면 빈 결과 |
| `nara/llm.py` (신규) | Claude 판정 클라이언트. 키 없으면 `None` |
| `nara/status.py` (신규) | 파이프라인. 대상 선택 → 판정 → 기록. 시간 예산 |
| `nara/cli.py` (수정) | `nara enrich status` 명령 추가 |
| `nara/doctor.py` (수정) | 판정·날짜 모순 점검 3종 추가 |
| `nara/config.py` (수정 여부 확인) | `Secrets`에 네이버·Claude 키가 이미 있는지 보고 없으면 추가 |
| `tests/test_verdict.py` (신규) | 순수 규칙 전부 |
| `tests/test_naver.py` (신규) | MockTransport로 검색 클라이언트 |
| `tests/test_llm.py` (신규) | MockTransport로 LLM 클라이언트 |
| `tests/test_status.py` (신규) | 파이프라인 통합 |
| `tests/test_status_regression.py` (신규) | 2026-09-16에 실제로 틀렸던 4건 |

`nara/config.py`의 `Secrets`에는 `naver_client_id` · `naver_client_secret` · `anthropic_api_key`가 **이미 있다**(확인함). 새 필드를 만들지 않는다.

---

### Task 1: 판정 어휘와 규칙 판정

뉴스 없이 공고 사실만으로 내리는 판정이다. 이관된 152건이 쓰는 어휘를 그대로 쓴다.

**Files:**
- Create: `nara/verdict.py`
- Test: `tests/test_verdict.py`

**Interfaces:**
- Produces: `BEFORE`, `BUILDING`, `DONE`, `UNKNOWN` 상수, `Facts` 데이터클래스, `rule_verdict(facts) -> tuple[str, str]`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
from nara.verdict import BEFORE, UNKNOWN, Facts, rule_verdict


def test_rule_verdict_uses_award_as_evidence_of_design_stage():
    """낙찰업체가 있으면 설계가 도는 중이다. 착공했다는 뜻이 아니다."""
    verdict, reason = rule_verdict(
        Facts(has_winner=True, open_date="2026-09-10", today="2026-09-18")
    )
    assert verdict == BEFORE
    assert "낙찰" in reason


def test_rule_verdict_uses_passed_opening_when_winner_unknown():
    verdict, reason = rule_verdict(
        Facts(has_winner=False, open_date="2026-09-10", today="2026-09-18")
    )
    assert verdict == BEFORE
    assert "개찰" in reason


def test_rule_verdict_is_unknown_before_opening():
    """개찰 전이면 아무것도 모른다. 공고일로 추정하지 않는다."""
    verdict, reason = rule_verdict(
        Facts(has_winner=False, open_date="2026-12-01", today="2026-09-18")
    )
    assert verdict == UNKNOWN
    assert reason


def test_rule_verdict_is_unknown_without_opening_date():
    """수기로 넣은 사업은 개찰일이 없다. 그래도 추정하지 않는다."""
    verdict, _ = rule_verdict(Facts(has_winner=False, open_date="", today="2026-09-18"))
    assert verdict == UNKNOWN


def test_rule_verdict_never_claims_construction_or_completion():
    """규칙만으로는 '시공 중'·'준공 완료'를 말할 수 없다 — 그건 보도 근거가 필요하다."""
    seen = {
        rule_verdict(Facts(has_winner=w, open_date=d, today="2026-09-18"))[0]
        for w in (True, False)
        for d in ("", "2026-09-10", "2026-12-01")
    }
    assert seen <= {BEFORE, UNKNOWN}
```

- [ ] **Step 2: 실패를 확인한다**

Run: `uv run pytest tests/test_verdict.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'nara.verdict'`

- [ ] **Step 3: 최소 구현**

```python
"""진행현황 판정 규칙. I/O가 없어야 테스트가 네트워크를 타지 않는다."""

from dataclasses import dataclass

BEFORE = "착공 전(설계 단계)"
BUILDING = "시공 중"
DONE = "준공 완료"
UNKNOWN = "미확인"


@dataclass(frozen=True)
class Facts:
    """공고에서 바로 읽히는 사실만 담는다. 추정한 값은 넣지 않는다."""

    has_winner: bool
    open_date: str  # ISO 또는 ""
    today: str  # ISO


def rule_verdict(facts: Facts) -> tuple[str, str]:
    """(판정, 근거). 규칙은 '착공 전'과 '미확인'까지만 말한다.

    '시공 중'·'준공 완료'는 보도 근거가 있어야 내릴 수 있는 판정이라
    여기서는 절대 나오지 않는다.
    """
    if facts.has_winner:
        return BEFORE, "낙찰업체가 기록됨 — 설계 단계"
    if facts.open_date and facts.open_date <= facts.today:
        return BEFORE, "개찰일이 지났고 낙찰업체 미확인 — 설계 단계"
    if facts.open_date:
        return UNKNOWN, f"개찰 전(개찰 예정 {facts.open_date})"
    return UNKNOWN, "개찰일 없음"
```

- [ ] **Step 4: 통과를 확인한다**

Run: `uv run pytest tests/test_verdict.py -v`
Expected: PASS (5개)

- [ ] **Step 5: 커밋**

```bash
git add nara/verdict.py tests/test_verdict.py
git commit -m "feat: 공고 사실만으로 내리는 진행현황 규칙 판정

규칙은 '착공 전'과 '미확인'까지만 말한다. '시공 중'·'준공 완료'는
보도 근거가 있어야 하는 판정이라 규칙 경로에서는 나올 수 없다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: 기사에서 신호 읽기

기사 제목·본문에서 판정에 쓰는 신호만 뽑는다. 여기서 판정하지 않는다.

**Files:**
- Modify: `nara/verdict.py`
- Test: `tests/test_verdict.py`

**Interfaces:**
- Consumes: Task 1의 상수
- Produces: `Article` 데이터클래스, `SIGNAL_*` 상수, `read_signals(article) -> frozenset[str]`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
from nara.verdict import (
    SIGNAL_DEMOLITION,
    SIGNAL_DESIGN,
    SIGNAL_DONE,
    SIGNAL_PLANNED,
    SIGNAL_START,
    Article,
    read_signals,
)


def _a(title="", body="", url="https://example.com/1", published="2026-09-01"):
    return Article(title=title, body=body, url=url, published=published)


def test_read_signals_finds_groundbreaking():
    assert SIGNAL_START in read_signals(_a(title="완주군 종합사회복지관 기공식"))


def test_read_signals_finds_completion():
    assert SIGNAL_DONE in read_signals(_a(title="순창군 동계면 종합체육관 준공"))


def test_read_signals_treats_demolition_as_not_started():
    """철거는 착공이 아니다. 이주 → 철거 → 착공 순서이고 철거 중이면 접촉 최적기다."""
    signals = read_signals(_a(title="옛 청사 철거 공사 착수", body="멸실 신고 완료"))
    assert SIGNAL_DEMOLITION in signals
    assert SIGNAL_START not in signals


def test_read_signals_marks_planned_language():
    """'2026년 9월 착공 예정'은 착공이 아니다."""
    signals = read_signals(_a(title="완주군 다목적체육관 2026년 9월 착공 예정"))
    assert SIGNAL_PLANNED in signals
    assert SIGNAL_START in signals  # '착공'이라는 말은 있다 — 판단은 다음 단계가 한다


def test_read_signals_finds_design_stage():
    assert SIGNAL_DESIGN in read_signals(_a(title="설계공모 당선작 발표"))


def test_read_signals_returns_empty_for_unrelated_text():
    assert read_signals(_a(title="군수 신년사")) == frozenset()
```

- [ ] **Step 2: 실패를 확인한다**

Run: `uv run pytest tests/test_verdict.py -v`
Expected: FAIL — `ImportError: cannot import name 'Article'`

- [ ] **Step 3: 최소 구현**

`nara/verdict.py`에 추가한다.

```python
SIGNAL_START = "착공"
SIGNAL_DONE = "준공"
SIGNAL_DESIGN = "설계"
SIGNAL_DEMOLITION = "철거"
SIGNAL_PLANNED = "예정"

# 철거를 착공으로 오판한 사고가 반복됐다. 철거 낱말이 보이면 착공 신호를 세우지 않는다.
_DEMOLITION_WORDS = ("철거", "멸실", "해체")
_START_WORDS = ("착공", "기공식", "첫 삽", "공사 착수")
_DONE_WORDS = ("준공", "개관", "준공식", "운영 개시", "개원")
_DESIGN_WORDS = ("설계", "공모", "당선작", "낙찰", "실시설계", "기본설계")
_PLANNED_WORDS = ("예정", "목표", "계획", "추진")


@dataclass(frozen=True)
class Article:
    title: str
    body: str
    url: str
    published: str  # ISO 또는 ""


def read_signals(article: Article) -> frozenset[str]:
    """기사에서 판정 재료만 뽑는다. 여기서 판정하지 않는다."""
    text = f"{article.title} {article.body}"
    found: set[str] = set()
    demolition = any(w in text for w in _DEMOLITION_WORDS)
    if demolition:
        found.add(SIGNAL_DEMOLITION)
    if any(w in text for w in _START_WORDS) and not demolition:
        found.add(SIGNAL_START)
    if any(w in text for w in _DONE_WORDS):
        found.add(SIGNAL_DONE)
    if any(w in text for w in _DESIGN_WORDS):
        found.add(SIGNAL_DESIGN)
    if any(w in text for w in _PLANNED_WORDS):
        found.add(SIGNAL_PLANNED)
    return frozenset(found)
```

- [ ] **Step 4: 통과를 확인한다**

Run: `uv run pytest tests/test_verdict.py -v`
Expected: PASS (11개)

- [ ] **Step 5: 커밋**

```bash
git add nara/verdict.py tests/test_verdict.py
git commit -m "feat: 기사에서 진행현황 신호를 읽는다

철거는 착공이 아니다 — 이주 다음 철거, 그 다음이 본공사 착공이다.
철거 낱말이 보이면 착공 신호를 세우지 않는다. 조사에서 이걸
착공으로 오판해 영업 대상에서 빼는 사고가 반복됐다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: 근거 없는 강한 판정을 내린다

스펙의 강등 규칙이다. 근거 URL이 없으면 `준공 완료`·`시공 중`을 주장할 수 없다.

**Files:**
- Modify: `nara/verdict.py`
- Test: `tests/test_verdict.py`

**Interfaces:**
- Produces: `demote_without_evidence(verdict, evidence_url) -> tuple[str, str | None]`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
from nara.verdict import BEFORE, BUILDING, DONE, UNKNOWN, demote_without_evidence


def test_demote_drops_completion_claim_without_url():
    verdict, note = demote_without_evidence(DONE, "")
    assert verdict == BEFORE
    assert note and "근거" in note


def test_demote_drops_construction_claim_without_url():
    verdict, note = demote_without_evidence(BUILDING, None)
    assert verdict == BEFORE
    assert note


def test_demote_keeps_strong_claim_when_url_present():
    verdict, note = demote_without_evidence(DONE, "https://news.example.com/1")
    assert verdict == DONE
    assert note is None


def test_demote_leaves_weak_verdicts_alone():
    """'착공 전'·'미확인'은 강등할 것이 없다. 헛되이 건드리지 않는다."""
    for weak in (BEFORE, UNKNOWN):
        assert demote_without_evidence(weak, "") == (weak, None)
```

- [ ] **Step 2: 실패를 확인한다**

Run: `uv run pytest tests/test_verdict.py -v`
Expected: FAIL — `ImportError: cannot import name 'demote_without_evidence'`

- [ ] **Step 3: 최소 구현**

```python
_STRONG = (BUILDING, DONE)


def demote_without_evidence(verdict: str, evidence_url: str | None) -> tuple[str, str | None]:
    """근거 URL 없는 '시공 중'·'준공 완료'는 '착공 전'으로 내린다.

    (판정, 강등 메모). 강등하지 않았으면 메모는 None이다.
    """
    if verdict in _STRONG and not (evidence_url or "").strip():
        return BEFORE, f"근거 URL이 없어 '{verdict}' 주장을 착공 전으로 내림"
    return verdict, None
```

- [ ] **Step 4: 통과를 확인한다**

Run: `uv run pytest tests/test_verdict.py -v`
Expected: PASS (15개)

- [ ] **Step 5: 커밋**

```bash
git add nara/verdict.py tests/test_verdict.py
git commit -m "feat: 근거 URL 없는 준공·시공 주장을 착공 전으로 내린다

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: 기사로 판정하고, 애매하면 넘긴다

기사 신호를 모아 판정하되 **스펙이 열거한 애매 상황은 판정하지 않고 LLM으로 넘긴다.** 전부 2026-09-16에 실제로 틀렸던 유형이다.

**Files:**
- Modify: `nara/verdict.py`
- Test: `tests/test_verdict.py`

**Interfaces:**
- Produces: `NewsRead` 데이터클래스(`verdict`, `reason`, `evidence_url`, `needs_llm`, `llm_reason`), `read_news(articles, project_dates) -> NewsRead`
- `project_dates`는 `(start_date, end_date)` 튜플. 사람이 시트에 넣은 값이며 **고치지 않는다.**

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
from nara.verdict import BEFORE, BUILDING, DONE, UNKNOWN, Article, read_news


def _a(title, body="", url="https://news.example.com/1", published="2026-09-01"):
    return Article(title=title, body=body, url=url, published=published)


def test_read_news_reports_unknown_without_articles():
    got = read_news([], ("", ""))
    assert got.verdict == UNKNOWN
    assert got.needs_llm is False


def test_read_news_calls_construction_when_groundbreaking_is_reported():
    got = read_news([_a("완주군 종합사회복지관 기공식 개최")], ("", ""))
    assert got.verdict == BUILDING
    assert got.evidence_url == "https://news.example.com/1"


def test_read_news_calls_completion_when_opening_is_reported():
    got = read_news([_a("순창군 동계면 종합체육관 준공식")], ("", ""))
    assert got.verdict == DONE


def test_read_news_defers_when_start_and_planned_collide():
    """'2026년 9월 착공 예정' — 예정인지 실제인지 기계가 못 가른다."""
    got = read_news([_a("완주군 다목적체육관 2026년 9월 착공 예정")], ("", ""))
    assert got.needs_llm is True
    assert got.llm_reason


def test_read_news_defers_when_completion_and_start_collide():
    """준공 기사와 착공 기사가 동시에 잡히는 경우 — 순창군 사례."""
    first = _a("동계면 종합체육관 착공")
    second = _a("동계면 종합체육관 준공", url="https://news.example.com/2")
    assert read_news([first, second], ("", "")).needs_llm is True


def test_read_news_defers_when_article_year_is_far_from_project_dates():
    """진안복합노인 복지센터 — 2006년 개원 시설이 검색돼 들어왔다."""
    got = read_news(
        [_a("진안복합노인 복지센터 개원", published="2006-05-26")], ("2026-01-01", "2027-12-31")
    )
    assert got.needs_llm is True
    assert "연도" in got.llm_reason


def test_read_news_treats_demolition_as_before_construction():
    got = read_news([_a("옛 청사 철거 착수")], ("", ""))
    assert got.verdict == BEFORE
    assert got.needs_llm is False


def test_read_news_never_returns_strong_verdict_without_evidence_url():
    got = read_news([_a("체육관 준공", url="")], ("", ""))
    assert got.verdict not in (BUILDING, DONE)
```

- [ ] **Step 2: 실패를 확인한다**

Run: `uv run pytest tests/test_verdict.py -v`
Expected: FAIL — `ImportError: cannot import name 'read_news'`

- [ ] **Step 3: 최소 구현**

```python
_YEAR_GAP = 3  # 기사 연도가 사업 일정에서 이만큼 벗어나면 같은 사업인지 의심한다


@dataclass(frozen=True)
class NewsRead:
    verdict: str
    reason: str
    evidence_url: str
    needs_llm: bool
    llm_reason: str


def _year(iso: str) -> int | None:
    head = (iso or "")[:4]
    return int(head) if head.isdigit() else None


def _far_from(published: str, dates: tuple[str, str]) -> bool:
    published_year = _year(published)
    years = [y for y in (_year(dates[0]), _year(dates[1])) if y]
    if published_year is None or not years:
        return False
    return min(abs(published_year - y) for y in years) > _YEAR_GAP


def read_news(articles: list[Article], project_dates: tuple[str, str]) -> NewsRead:
    """기사 묶음에서 판정을 읽는다. 애매하면 판정하지 않고 넘긴다."""
    if not articles:
        return NewsRead(UNKNOWN, "검색 결과 없음", "", False, "")

    for article in articles:
        if _far_from(article.published, project_dates):
            gap = f"기사 연도({article.published[:4]})가 사업 일정과 {_YEAR_GAP}년 넘게 어긋남"
            return NewsRead(UNKNOWN, "기사 연도가 사업 일정과 어긋남", article.url, True, gap)

    signals = [(a, read_signals(a)) for a in articles]
    starts = [a for a, s in signals if SIGNAL_START in s]
    dones = [a for a, s in signals if SIGNAL_DONE in s]
    planned = {a.url for a, s in signals if SIGNAL_PLANNED in s}

    if starts and dones:
        return NewsRead(
            UNKNOWN,
            "착공 기사와 준공 기사가 함께 잡힘",
            dones[0].url,
            True,
            "착공 기사와 준공 기사가 동시에 잡힘",
        )

    for group, strong, label in ((dones, DONE, "준공"), (starts, BUILDING, "착공·기공식")):
        if not group:
            continue
        article = group[0]
        if article.url in planned:
            return NewsRead(
                UNKNOWN,
                f"{label} 예정 표기",
                article.url,
                True,
                f"{label}과 예정이 함께 쓰여 실제인지 불분명",
            )
        verdict, note = demote_without_evidence(strong, article.url)
        return NewsRead(verdict, note or f"{label} 보도", article.url, False, "")

    for article, sig in signals:
        if SIGNAL_DEMOLITION in sig:
            return NewsRead(BEFORE, "철거 단계 — 본공사 착공 전", article.url, False, "")
    for article, sig in signals:
        if SIGNAL_DESIGN in sig:
            return NewsRead(BEFORE, "설계·공모 단계 보도", article.url, False, "")

    return NewsRead(UNKNOWN, "관련 신호 없음", "", False, "")
```

- [ ] **Step 4: 통과를 확인한다**

Run: `uv run pytest tests/test_verdict.py -v`
Expected: PASS (23개)

- [ ] **Step 5: 커밋**

```bash
git add nara/verdict.py tests/test_verdict.py
git commit -m "feat: 기사로 진행현황을 읽고 애매하면 판정하지 않는다

스펙이 열거한 애매 상황(착공/예정 충돌, 준공/착공 동시, 기사 연도
어긋남)은 기계가 가르지 않고 LLM으로 넘긴다. 전부 2026-09-16에
실제로 틀렸던 유형이다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: 언제 기록할지 정한다

`status_check`는 덮어쓰지 않고 쌓는다. 그래서 두 가지를 막아야 한다.

1. **같은 판정을 회차마다 다시 쌓는 것.** 하루 두 번 × 158건이면 이력이 순식간에 못 읽을 것이 된다.
2. **근거 있는 판정을 근거 없는 규칙 판정이 밀어내는 것.** 이관된 152건에는 사람이 보도를 읽고 넣은 `시공 중 - 25.06.30 기공식` 같은 판정이 있다. 규칙은 그 사업을 `착공 전(개찰 근거)`으로밖에 못 본다. 화면이 최신 행을 보여주므로 그대로 두면 **사람이 조사한 결과가 규칙 판정에 덮인다.**

**Files:**
- Modify: `nara/verdict.py`
- Test: `tests/test_verdict.py`

**Interfaces:**
- Produces: `Judgment` 데이터클래스(`verdict`, `reason`, `decided_by`, `evidence_url`), `should_record(latest, candidate) -> tuple[bool, str]`
- `latest`는 그 사업의 가장 최근 `status_check` 행(`dict` 또는 `None`)

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
from nara.verdict import BEFORE, BUILDING, UNKNOWN, Judgment, should_record


def _latest(verdict, decided_by, evidence_url=""):
    return {"verdict": verdict, "decided_by": decided_by, "evidence_json": evidence_url}


def test_should_record_first_judgment():
    ok, _ = should_record(None, Judgment(BEFORE, "개찰 근거", "rule", ""))
    assert ok is True


def test_should_record_skips_identical_repeat():
    """같은 판정을 회차마다 다시 쌓지 않는다 — 이력이 못 읽을 것이 된다."""
    latest = _latest(BEFORE, "rule")
    ok, why = should_record(latest, Judgment(BEFORE, "개찰 근거", "rule", ""))
    assert ok is False
    assert why


def test_should_record_when_verdict_changes():
    latest = _latest(BEFORE, "rule")
    ok, _ = should_record(latest, Judgment(BUILDING, "기공식 보도", "news", "https://n/1"))
    assert ok is True


def test_rule_judgment_does_not_bury_human_research():
    """사람이 보도를 읽고 넣은 '시공 중'을 규칙 판정이 밀어내면 안 된다."""
    latest = _latest(BUILDING, "imported")
    ok, why = should_record(latest, Judgment(BEFORE, "개찰일이 지났고 낙찰업체 미확인", "rule", ""))
    assert ok is False
    assert "근거" in why or "규칙" in why


def test_rule_judgment_may_follow_another_rule_judgment_that_changed():
    latest = _latest(UNKNOWN, "rule")
    ok, _ = should_record(latest, Judgment(BEFORE, "낙찰업체가 기록됨", "rule", ""))
    assert ok is True


def test_evidenced_judgment_may_overturn_human_research():
    """근거 URL을 들고 오면 사람 판정도 뒤집을 수 있다. 이력에 둘 다 남는다."""
    latest = _latest(BUILDING, "imported")
    ok, _ = should_record(latest, Judgment("준공 완료", "준공 보도", "news", "https://n/9"))
    assert ok is True
```

- [ ] **Step 2: 실패를 확인한다**

Run: `uv run pytest tests/test_verdict.py -v`
Expected: FAIL — `ImportError: cannot import name 'Judgment'`

- [ ] **Step 3: 최소 구현**

```python
@dataclass(frozen=True)
class Judgment:
    verdict: str
    reason: str
    decided_by: str  # 'rule' | 'news' | 'llm' | 'human' | 'imported'
    evidence_url: str


def should_record(latest: dict | None, candidate: Judgment) -> tuple[bool, str]:
    """이 판정을 status_check에 쌓을지 정한다. (기록할지, 안 하는 이유).

    status_check는 이력이고 화면은 최신 행만 본다. 그래서 '기록하지 않는다'는
    선택이 곧 '앞선 판정을 그대로 둔다'는 뜻이다.
    """
    if latest is None:
        return True, ""

    if latest.get("verdict") == candidate.verdict:
        return False, "판정이 그대로다 — 회차마다 같은 줄을 쌓지 않는다"

    bare_rule = candidate.decided_by == "rule" and not candidate.evidence_url.strip()
    if bare_rule and latest.get("decided_by") in ("imported", "human", "news", "llm"):
        return False, (
            f"근거를 보고 내린 '{latest.get('verdict')}' 판정을 "
            "근거 없는 규칙 판정으로 밀어내지 않는다"
        )

    return True, ""
```

- [ ] **Step 4: 통과를 확인한다**

Run: `uv run pytest tests/test_verdict.py -v`
Expected: PASS (29개)

- [ ] **Step 5: 커밋**

```bash
git add nara/verdict.py tests/test_verdict.py
git commit -m "feat: 규칙 판정이 사람이 조사한 판정을 밀어내지 않는다

status_check는 이력이고 화면은 최신 행을 본다. 그래서 '기록하지
않는다'가 곧 '앞선 판정을 그대로 둔다'는 뜻이다. 같은 판정을
회차마다 쌓지도 않는다 — 하루 두 번 158건이면 이력을 못 읽는다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: 사람이 넣은 날짜와 보도가 어긋나면 기록만 한다

스펙: "사람이 넣은 착공일·준공일과 보도가 어긋나면 사용자 값을 고치지 않고 불일치로 기록한다." 2026-09-16 조사에서 12건이 어긋났다.

**Files:**
- Modify: `nara/verdict.py`
- Test: `tests/test_verdict.py`

**Interfaces:**
- Produces: `date_conflict(verdict, project_dates, today) -> str | None`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
from nara.verdict import BEFORE, BUILDING, DONE, date_conflict


def test_conflict_when_before_construction_but_start_date_has_passed():
    """'착공 전'인데 시트의 착공일이 이미 지났다 — 둘 중 하나가 틀렸다."""
    note = date_conflict(BEFORE, ("2025-11-03", ""), "2026-09-18")
    assert note and "착공" in note


def test_no_conflict_when_before_construction_and_start_date_is_future():
    assert date_conflict(BEFORE, ("2027-03-01", ""), "2026-09-18") is None


def test_conflict_when_completed_but_end_date_is_future():
    note = date_conflict(DONE, ("", "2029-01-30"), "2026-09-18")
    assert note and "준공" in note


def test_no_conflict_when_dates_are_blank():
    assert date_conflict(BUILDING, ("", ""), "2026-09-18") is None


def test_conflict_never_changes_the_dates():
    """이 함수는 문자열만 돌려준다. 값을 고치는 경로가 아예 없다."""
    dates = ("2025-11-03", "2026-01-01")
    date_conflict(BEFORE, dates, "2026-09-18")
    assert dates == ("2025-11-03", "2026-01-01")
```

- [ ] **Step 2: 실패를 확인한다**

Run: `uv run pytest tests/test_verdict.py -v`
Expected: FAIL — `ImportError: cannot import name 'date_conflict'`

- [ ] **Step 3: 최소 구현**

```python
def date_conflict(verdict: str, project_dates: tuple[str, str], today: str) -> str | None:
    """판정과 사람이 넣은 날짜가 어긋나면 그 사실만 문장으로 돌려준다.

    **날짜를 고치지 않는다.** 시트 값은 사용자가 넣은 자료이고, 어느 쪽이
    맞는지는 담당부서에 물어야 안다.
    """
    start, end = project_dates
    if verdict == BEFORE and start and start <= today:
        return f"시트 착공일 {start}이 지났는데 판정은 착공 전 — 확인 필요"
    if verdict == DONE and end and end > today:
        return f"시트 준공일 {end}이 아직인데 판정은 준공 완료 — 확인 필요"
    return None
```

- [ ] **Step 4: 통과를 확인한다**

Run: `uv run pytest tests/test_verdict.py -v`
Expected: PASS (34개)

- [ ] **Step 5: 커밋**

```bash
git add nara/verdict.py tests/test_verdict.py
git commit -m "feat: 시트 날짜와 판정이 어긋나면 고치지 않고 기록만 한다

어느 쪽이 맞는지는 담당부서에 물어야 안다. 2026-09-16 조사에서
12건이 어긋났고 그때도 시트 값은 손대지 않았다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 7: 네이버 뉴스 검색 클라이언트

키가 없으면 빈 결과를 돌려준다. **예외를 던지지 않고, 조용히 성공한 척도 하지 않는다** — 호출부가 "검색을 안 했다"를 알 수 있어야 한다.

**Files:**
- Create: `nara/naver.py`
- Test: `tests/test_naver.py`

**Interfaces:**
- Consumes: `nara.verdict.Article`, `nara.config.Secrets`
- Produces: `SearchResult` 데이터클래스(`articles`, `searched`, `note`), `search_news(client, secrets, query, display=10) -> SearchResult`
- `searched=False`면 검색을 하지 않은 것이다. 빈 `articles`와 구분된다.

네이버 뉴스 검색 API 사실(구현자가 추측하지 말 것):
- `GET https://openapi.naver.com/v1/search/news.json`
- 헤더 `X-Naver-Client-Id`, `X-Naver-Client-Secret`
- 질의 `query`(필수), `display`(1~100), `sort`(`sim`|`date`)
- 응답 `items[]`의 `title`·`description`은 **`<b>` 태그와 HTML 엔티티가 섞여 온다.** 벗겨야 한다.
- `pubDate`는 RFC 822 형식(`Mon, 26 Sep 2026 14:12:00 +0900`)이다. ISO가 아니다.
- `originallink`는 원 기사, `link`는 네이버 링크다. **원 기사를 근거 URL로 쓴다.**

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
import httpx

from nara.config import Secrets
from nara.naver import search_news

KEYED = Secrets(
    g2b_api_key="x", naver_client_id="id", naver_client_secret="sec", anthropic_api_key=None
)
KEYLESS = Secrets(
    g2b_api_key="x", naver_client_id=None, naver_client_secret=None, anthropic_api_key=None
)

PAYLOAD = {
    "items": [
        {
            "title": "완주군 <b>종합사회복지관</b> 기공식",
            "description": "28일 &quot;기공식&quot;이 열렸다",
            "originallink": "https://news.example.com/a",
            "link": "https://n.news.naver.com/a",
            "pubDate": "Thu, 28 Aug 2026 10:00:00 +0900",
        }
    ]
}


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_search_news_reports_that_it_did_not_search_without_keys():
    """키가 없는 것과 결과가 없는 것은 다른 일이다."""
    with _client(lambda r: httpx.Response(500)) as client:
        got = search_news(client, KEYLESS, "완주군 종합사회복지관")
    assert got.searched is False
    assert got.articles == []
    assert got.note


def test_search_news_strips_markup_and_entities_from_title():
    with _client(lambda r: httpx.Response(200, json=PAYLOAD)) as client:
        got = search_news(client, KEYED, "완주군 종합사회복지관")
    assert got.searched is True
    assert got.articles[0].title == "완주군 종합사회복지관 기공식"
    assert '"기공식"' in got.articles[0].body


def test_search_news_converts_rfc822_date_to_iso():
    with _client(lambda r: httpx.Response(200, json=PAYLOAD)) as client:
        got = search_news(client, KEYED, "q")
    assert got.articles[0].published == "2026-08-28"


def test_search_news_uses_the_original_article_url_not_the_portal_link():
    with _client(lambda r: httpx.Response(200, json=PAYLOAD)) as client:
        got = search_news(client, KEYED, "q")
    assert got.articles[0].url == "https://news.example.com/a"


def test_search_news_sends_credentials_in_headers():
    seen = {}

    def handler(request):
        seen.update(request.headers)
        return httpx.Response(200, json=PAYLOAD)

    with _client(handler) as client:
        search_news(client, KEYED, "q")
    assert seen["x-naver-client-id"] == "id"
    assert seen["x-naver-client-secret"] == "sec"


def test_search_news_surfaces_http_failure_without_pretending_to_have_searched():
    with _client(lambda r: httpx.Response(429, text="quota")) as client:
        got = search_news(client, KEYED, "q")
    assert got.searched is False
    assert "429" in got.note


def test_search_news_falls_back_to_portal_link_when_original_is_missing():
    payload = {"items": [dict(PAYLOAD["items"][0], originallink="")]}
    with _client(lambda r: httpx.Response(200, json=payload)) as client:
        got = search_news(client, KEYED, "q")
    assert got.articles[0].url == "https://n.news.naver.com/a"
```

- [ ] **Step 2: 실패를 확인한다**

Run: `uv run pytest tests/test_naver.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'nara.naver'`

- [ ] **Step 3: 최소 구현**

```python
"""네이버 뉴스 검색. 키가 없으면 검색하지 않았다고 말한다."""

import html
import re
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime

import httpx

from nara.config import Secrets
from nara.verdict import Article

ENDPOINT = "https://openapi.naver.com/v1/search/news.json"
_TAG = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class SearchResult:
    articles: list[Article] = field(default_factory=list)
    searched: bool = False
    note: str = ""


def _plain(raw: str) -> str:
    """네이버는 <b> 태그와 HTML 엔티티를 섞어 보낸다. 둘 다 벗긴다."""
    return html.unescape(_TAG.sub("", raw or "")).strip()


def _iso(pub_date: str) -> str:
    """RFC 822('Mon, 26 Sep 2026 14:12:00 +0900') → ISO 날짜. 못 읽으면 빈 문자열."""
    try:
        return parsedate_to_datetime(pub_date).date().isoformat()
    except TypeError, ValueError:
        return ""


def search_news(
    client: httpx.Client, secrets: Secrets, query: str, display: int = 10
) -> SearchResult:
    if not (secrets.naver_client_id and secrets.naver_client_secret):
        return SearchResult(note="네이버 검색 키가 없어 뉴스 검색을 건너뛰었다")

    try:
        response = client.get(
            ENDPOINT,
            params={"query": query, "display": display, "sort": "sim"},
            headers={
                "X-Naver-Client-Id": secrets.naver_client_id,
                "X-Naver-Client-Secret": secrets.naver_client_secret,
            },
            timeout=10.0,
        )
    except httpx.HTTPError as exc:
        return SearchResult(note=f"뉴스 검색 실패: {exc}")

    if response.status_code != 200:
        return SearchResult(note=f"뉴스 검색 실패: HTTP {response.status_code}")

    items = response.json().get("items") or []
    articles = [
        Article(
            title=_plain(item.get("title", "")),
            body=_plain(item.get("description", "")),
            # 원 기사를 근거로 남긴다. 포털 링크는 원문이 내려가면 같이 사라진다.
            url=(item.get("originallink") or item.get("link") or "").strip(),
            published=_iso(item.get("pubDate", "")),
        )
        for item in items
    ]
    return SearchResult(articles=articles, searched=True)
```

- [ ] **Step 4: 통과를 확인한다**

Run: `uv run pytest tests/test_naver.py -v`
Expected: PASS (7개)

- [ ] **Step 5: 커밋**

```bash
git add nara/naver.py tests/test_naver.py
git commit -m "feat: 네이버 뉴스 검색 — 키가 없으면 검색 안 했다고 말한다

'키가 없다'와 '결과가 0건이다'는 다른 일이다. searched 플래그로
구분해 호출부가 둘을 섞지 않게 한다. 네이버가 섞어 보내는 <b> 태그와
HTML 엔티티를 벗기고, RFC 822 날짜를 ISO로 바꾼다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 8: Claude 판정 클라이언트

규칙과 기사로 못 가른 건만 넘어온다. **키가 없거나 호출이 실패하면 `None`을 돌려주고, 호출부는 `미확인`으로 남긴다.** 추측하지 않는다.

공식 `anthropic` SDK를 쓴다. `claude-api` 참조에서 확인한 사실이며 추측이 아니다:

- 모델은 **`claude-opus-5`**. 날짜 접미사를 붙이지 않는다.
- `thinking={"type": "adaptive"}` + `output_config={"effort": "low"}`. **`budget_tokens`는 제거돼 400을 받는다.**
- 어시스턴트 prefill은 **400**이다. 응답 형식은 시스템 프롬프트로 지시한다.
- 오류는 넓은 한 덩어리로 잡지 말고 구체적인 것부터 사슬로 잡는다.

**모델이 이상한 답을 하면 그 답을 버린다.** 네 가지 어휘 밖의 문자열이 오면 판정으로 받아들이지 않고 `None`을 돌려준다. 조용히 틀린 판정을 쓰느니 `미확인`이 낫다.

**Files:**
- Create: `nara/llm.py`
- Modify: `pyproject.toml` (의존성 `anthropic` 추가)
- Test: `tests/test_llm.py`

**Interfaces:**
- Consumes: `nara.verdict`의 어휘 상수와 `Article`, `nara.config.Secrets`
- Produces: `adjudicate(secrets, project_name, articles, question, client=None) -> tuple[str, str] | None`
- 돌려주는 값은 `(판정, 근거 한 줄)`. 판정은 반드시 네 어휘 중 하나다.
- `client`는 테스트가 가짜를 밀어 넣는 자리다. 실제 실행에서는 `None`으로 두고 함수가 만든다.

- [ ] **Step 1: 의존성을 추가한다**

```bash
uv add anthropic
uv run python -c "import anthropic; print(anthropic.__version__)"
```

- [ ] **Step 2: 실패하는 테스트를 쓴다**

```python
import anthropic
import pytest

from nara.config import Secrets
from nara.llm import adjudicate
from nara.verdict import BEFORE, BUILDING, Article

KEYED = Secrets(
    g2b_api_key="x", naver_client_id=None, naver_client_secret=None, anthropic_api_key="sk-test"
)
KEYLESS = Secrets(
    g2b_api_key="x", naver_client_id=None, naver_client_secret=None, anthropic_api_key=None
)
ARTICLES = [
    Article(
        title="완주군 다목적체육관 2026년 9월 착공 예정",
        body="",
        url="https://news.example.com/a",
        published="2026-08-01",
    )
]


class _Block:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _Response:
    def __init__(self, text):
        self.content = [_Block(text)]
        self.stop_reason = "end_turn"


class _FakeClient:
    """messages.create만 흉내 낸다. 실제 SDK를 때리지 않는다."""

    def __init__(self, response=None, raises=None):
        self._response = response
        self._raises = raises
        self.seen = {}
        self.messages = self

    def create(self, **kwargs):
        self.seen.update(kwargs)
        if self._raises:
            raise self._raises
        return self._response


def test_adjudicate_returns_none_without_key():
    assert adjudicate(KEYLESS, "완주군 다목적체육관", ARTICLES, "착공인가 예정인가") is None


def test_adjudicate_reads_verdict_and_reason():
    fake = _FakeClient(_Response(f"{BEFORE}\n기사가 '예정'이라고 적었다"))
    got = adjudicate(KEYED, "완주군 다목적체육관", ARTICLES, "착공인가 예정인가", client=fake)
    assert got == (BEFORE, "기사가 '예정'이라고 적었다")


def test_adjudicate_rejects_a_verdict_outside_the_vocabulary():
    """모델이 제 맘대로 답하면 그 답을 버린다. 조용히 쓰느니 미확인이 낫다."""
    fake = _FakeClient(_Response("아마 공사 중인 듯\n확실하지 않음"))
    assert adjudicate(KEYED, "사업", ARTICLES, "질문", client=fake) is None


def test_adjudicate_returns_none_when_the_api_fails():
    fake = _FakeClient(raises=anthropic.APIConnectionError(request=None))
    assert adjudicate(KEYED, "사업", ARTICLES, "질문", client=fake) is None


def test_adjudicate_uses_opus_5_with_adaptive_thinking_and_no_budget_tokens():
    fake = _FakeClient(_Response(f"{BUILDING}\n기공식 기사"))
    adjudicate(KEYED, "사업", ARTICLES, "질문", client=fake)
    assert fake.seen["model"] == "claude-opus-5"
    assert fake.seen["thinking"] == {"type": "adaptive"}
    # budget_tokens는 Opus 5에서 제거됐다 — 보내면 400이다.
    assert "budget_tokens" not in str(fake.seen)


def test_adjudicate_puts_the_articles_in_the_prompt():
    fake = _FakeClient(_Response(f"{BEFORE}\n근거"))
    adjudicate(KEYED, "완주군 다목적체육관", ARTICLES, "착공인가 예정인가", client=fake)
    sent = str(fake.seen["messages"])
    assert "완주군 다목적체육관 2026년 9월 착공 예정" in sent
    assert "https://news.example.com/a" in sent


def test_adjudicate_returns_none_on_refusal():
    response = _Response(f"{BUILDING}\n근거")
    response.stop_reason = "refusal"
    assert adjudicate(KEYED, "사업", ARTICLES, "질문", client=_FakeClient(response)) is None
```

- [ ] **Step 3: 실패를 확인한다**

Run: `uv run pytest tests/test_llm.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'nara.llm'`

- [ ] **Step 4: 최소 구현**

```python
"""규칙과 기사로 못 가른 건만 Claude에게 묻는다.

키가 없거나 호출이 실패하거나 모델이 어휘 밖의 답을 하면 None을 돌려준다.
호출부는 그걸 '미확인'으로 남긴다 — 추측한 판정을 쓰는 것보다 낫다.
"""

import anthropic

from nara.config import Secrets
from nara.verdict import BEFORE, BUILDING, DONE, UNKNOWN, Article

MODEL = "claude-opus-5"
VOCABULARY = (BEFORE, BUILDING, DONE, UNKNOWN)

SYSTEM = (
    "너는 한국 공공 건축사업의 진행현황을 기사만 보고 판정한다.\n"
    "첫 줄에 판정 하나만 적는다. 다음 넷 중 하나를 글자 그대로 쓴다:\n"
    f"{BEFORE} / {BUILDING} / {DONE} / {UNKNOWN}\n"
    "둘째 줄에 근거를 한 문장으로 적는다.\n"
    "규칙:\n"
    "- 철거·멸실은 착공이 아니다. 철거 단계면 착공 전이다.\n"
    "- '착공 예정'·'준공 목표'는 그 일이 일어났다는 뜻이 아니다.\n"
    "- 기사가 같은 이름의 다른 사업으로 보이면 미확인이다.\n"
    "- 확신이 없으면 미확인이라고 적는다. 추측하지 않는다."
)


def _prompt(project_name: str, articles: list[Article], question: str) -> str:
    lines = [f"사업명: {project_name}", f"가려야 할 점: {question}", "", "기사:"]
    for article in articles:
        lines.append(f"- [{article.published}] {article.title} ({article.url})")
        if article.body:
            lines.append(f"  {article.body}")
    return "\n".join(lines)


def adjudicate(
    secrets: Secrets,
    project_name: str,
    articles: list[Article],
    question: str,
    client=None,
) -> tuple[str, str] | None:
    if not secrets.anthropic_api_key:
        return None

    api = client or anthropic.Anthropic(api_key=secrets.anthropic_api_key, timeout=30.0)
    try:
        response = api.messages.create(
            model=MODEL,
            max_tokens=1000,
            system=SYSTEM,
            thinking={"type": "adaptive"},
            output_config={"effort": "low"},
            messages=[{"role": "user", "content": _prompt(project_name, articles, question)}],
        )
    except anthropic.APIStatusError:
        return None
    except anthropic.APIConnectionError:
        return None

    if getattr(response, "stop_reason", "") == "refusal":
        return None

    text = "".join(b.text for b in response.content if getattr(b, "type", "") == "text")
    head, _, tail = text.strip().partition("\n")
    verdict = head.strip()
    # 어휘 밖의 답은 판정으로 받아들이지 않는다.
    if verdict not in VOCABULARY:
        return None
    return verdict, tail.strip()
```

- [ ] **Step 5: 통과를 확인한다**

Run: `uv run pytest tests/test_llm.py -v`
Expected: PASS (7개)

- [ ] **Step 6: 커밋**

```bash
git add nara/llm.py tests/test_llm.py pyproject.toml uv.lock
git commit -m "feat: 애매한 건만 Claude에게 묻고, 이상한 답은 버린다

어휘 밖의 답이 오면 판정으로 받아들이지 않고 None을 돌려준다.
키가 없을 때, 호출이 실패할 때, 모델이 거절할 때도 마찬가지다.
호출부는 전부 '미확인'으로 남긴다 — 추측한 판정보다 낫다.

Opus 5는 budget_tokens를 받지 않는다(400). adaptive thinking에
effort low를 쓴다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 9: 대상 고르기 — 오래 안 본 것부터

낙찰 조회는 `ORDER BY open_date`라 적체가 생길 수 있었다(계획 1의 R15 — 스펙이 그렇게 정해서 그대로 두고 `doctor`로 드러냈다). **진행현황에는 그 제약이 없으므로 처음부터 굶지 않게 만든다: 가장 오래 안 본 사업부터 본다.**

**Files:**
- Create: `nara/status.py`
- Test: `tests/test_status.py`

**Interfaces:**
- Produces: `pending_status_projects(conn, tier, limit) -> list[sqlite3.Row]`
- 돌려주는 행에는 최소한 `id`, `name`, `start_date`, `end_date`, `org_name`이 있다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
from pathlib import Path

import pytest

from nara.config import load_settings
from nara.db import connect, migrate
from nara.status import pending_status_projects
from nara.store import ensure_project, upsert_org

SETTINGS = load_settings(Path(__file__).resolve().parents[1] / "config.toml")
NOW = "2026-09-18T09:00:00"


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "test.db")
    migrate(c)
    return c


def _project(conn, org_name, name):
    org_id = upsert_org(conn, org_name, SETTINGS, NOW)
    return ensure_project(conn, org_id, name, "manual", NOW)


def _checked(conn, project_id, when, verdict="미확인"):
    conn.execute(
        "INSERT INTO status_check (project_id, verdict, decided_by, checked_at) "
        "VALUES (?, ?, 'rule', ?)",
        (project_id, verdict, when),
    )
    conn.commit()


def test_pending_prefers_projects_never_checked(conn):
    old = _project(conn, "전북특별자치도 완주군", "본 적 있는 사업")
    fresh = _project(conn, "전북특별자치도 완주군", "한 번도 안 본 사업")
    _checked(conn, old, "2026-09-01T09:00:00")

    rows = pending_status_projects(conn, tier=None, limit=10)

    assert rows[0]["id"] == fresh


def test_pending_orders_older_checks_first(conn):
    recent = _project(conn, "전북특별자치도 완주군", "최근에 본 사업")
    stale = _project(conn, "전북특별자치도 완주군", "오래전에 본 사업")
    _checked(conn, recent, "2026-09-17T09:00:00")
    _checked(conn, stale, "2026-08-01T09:00:00")

    rows = pending_status_projects(conn, tier=None, limit=10)

    assert [r["id"] for r in rows] == [stale, recent]


def test_pending_filters_by_tier(conn):
    focus = _project(conn, "전북특별자치도 완주군", "관심 기관 사업")
    _project(conn, "강원특별자치도 양양군", "비관심 기관 사업")

    rows = pending_status_projects(conn, tier="focus", limit=10)

    assert [r["id"] for r in rows] == [focus]


def test_pending_honours_limit(conn):
    for i in range(5):
        _project(conn, "전북특별자치도 완주군", f"사업 {i}")
    assert len(pending_status_projects(conn, tier=None, limit=2)) == 2


def test_pending_rejects_nonpositive_limit(conn):
    """limit 0이면 조용히 '대상 0건'으로 끝나 조용한 날과 구분되지 않는다."""
    with pytest.raises(ValueError):
        pending_status_projects(conn, tier=None, limit=0)


def test_pending_carries_the_dates_the_judgment_needs(conn):
    project_id = _project(conn, "전북특별자치도 완주군", "사업")
    conn.execute(
        "UPDATE project SET start_date = ?, end_date = ? WHERE id = ?",
        ("2027-03-01", "2029-01-30", project_id),
    )
    conn.commit()

    row = pending_status_projects(conn, tier=None, limit=10)[0]

    assert row["start_date"] == "2027-03-01"
    assert row["end_date"] == "2029-01-30"
    assert row["name"] == "사업"
```

- [ ] **Step 2: 실패를 확인한다**

Run: `uv run pytest tests/test_status.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'nara.status'`

- [ ] **Step 3: 최소 구현**

```python
"""진행현황 판정 파이프라인."""

import sqlite3


def pending_status_projects(
    conn: sqlite3.Connection, tier: str | None, limit: int
) -> list[sqlite3.Row]:
    """오래 안 본 사업부터 돌려준다.

    한 번도 안 본 사업이 맨 앞이다. 낙찰 조회처럼 개찰일로 줄 세우면
    결과가 영영 없는 건이 앞을 막아 최근 사업이 뒤로 밀린다.
    """
    if limit < 1:
        raise ValueError(f"limit은 1 이상이어야 한다: {limit}")

    sql = [
        "SELECT p.id, p.name, p.start_date, p.end_date, o.name AS org_name,",
        "       MAX(s.checked_at) AS last_checked",
        "FROM project p",
        "JOIN org o ON o.id = p.org_id",
        "LEFT JOIN status_check s ON s.project_id = p.id",
    ]
    params: list[object] = []
    if tier:
        sql.append("WHERE o.tier = ?")
        params.append(tier)
    sql.append("GROUP BY p.id")
    # 한 번도 안 본 사업(NULL)이 맨 앞에 오게 한다.
    sql.append("ORDER BY last_checked IS NOT NULL, last_checked, p.id")
    sql.append("LIMIT ?")
    params.append(limit)
    return list(conn.execute("\n".join(sql), params))
```

- [ ] **Step 4: 통과를 확인한다**

Run: `uv run pytest tests/test_status.py -v`
Expected: PASS (6개)

- [ ] **Step 5: 커밋**

```bash
git add nara/status.py tests/test_status.py
git commit -m "feat: 진행현황 대상은 오래 안 본 사업부터 고른다

낙찰 조회는 개찰일 순이라 결과가 영영 없는 건이 앞을 막는 적체가
생긴다(계획 1 R15). 진행현황에는 그 제약이 없으니 처음부터 굶지
않게 만든다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```
---

### Task 10: 한 사업을 판정한다

규칙 → 뉴스 → LLM 순으로 내려가며, 각 단계가 못 가르면 다음으로 넘긴다. **어느 단계도 못 가르면 `미확인`이다.**

**Files:**
- Modify: `nara/status.py`
- Test: `tests/test_status.py`

**Interfaces:**
- Consumes: `nara.verdict`의 전부, `nara.naver.SearchResult`
- Produces: `judge_project(conn, row, secrets, today, search, adjudicator) -> Judgment`
- `search`와 `adjudicator`는 **주입한다. 기본값을 두지 않는다** — 테스트가 네트워크를 타면 안 된다.
- `search(secrets, query) -> SearchResult`, `adjudicator(secrets, name, articles, question) -> tuple[str, str] | None`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_status.py`에 추가한다. Task 9의 `conn` 픽스처와 `_project` 도우미를 그대로 쓴다.

```python
from nara.config import Secrets
from nara.naver import SearchResult
from nara.status import judge_project
from nara.verdict import BEFORE, BUILDING, UNKNOWN, Article

SECRETS = Secrets(
    g2b_api_key="x", naver_client_id=None, naver_client_secret=None, anthropic_api_key=None
)


def _no_search(*args, **kwargs):
    return SearchResult(note="네이버 검색 키가 없어 뉴스 검색을 건너뛰었다")


def _no_llm(*args, **kwargs):
    return None


def _row(conn, project_id):
    return conn.execute(
        "SELECT p.id, p.name, p.start_date, p.end_date, o.name AS org_name "
        "FROM project p JOIN org o ON o.id = p.org_id WHERE p.id = ?",
        (project_id,),
    ).fetchone()


def test_judge_falls_back_to_rules_when_search_is_unavailable(conn):
    project_id = _project(conn, "전북특별자치도 완주군", "사업")
    got = judge_project(
        conn, _row(conn, project_id), SECRETS, "2026-09-18", search=_no_search, adjudicator=_no_llm
    )
    assert got.decided_by == "rule"
    assert got.verdict in (BEFORE, UNKNOWN)


def test_judge_says_it_skipped_the_news_search(conn):
    """검색을 안 했다는 사실이 근거에 남아야 한다. 조용히 넘어가지 않는다."""
    project_id = _project(conn, "전북특별자치도 완주군", "사업")
    got = judge_project(
        conn, _row(conn, project_id), SECRETS, "2026-09-18", search=_no_search, adjudicator=_no_llm
    )
    assert "건너뛰" in got.reason


def test_judge_uses_news_when_it_finds_evidence(conn):
    project_id = _project(conn, "전북특별자치도 완주군", "완주군 종합사회복지관")
    found = SearchResult(
        articles=[Article("완주군 종합사회복지관 기공식", "", "https://n/1", "2026-08-28")],
        searched=True,
    )
    got = judge_project(
        conn,
        _row(conn, project_id),
        SECRETS,
        "2026-09-18",
        search=lambda *a, **k: found,
        adjudicator=_no_llm,
    )
    assert got.verdict == BUILDING
    assert got.decided_by == "news"
    assert got.evidence_url == "https://n/1"


def test_judge_asks_the_llm_only_when_the_news_read_is_ambiguous(conn):
    project_id = _project(conn, "전북특별자치도 완주군", "완주군 다목적체육관")
    found = SearchResult(
        articles=[
            Article("완주군 다목적체육관 2026년 9월 착공 예정", "", "https://n/2", "2026-08-01")
        ],
        searched=True,
    )
    asked = []

    def adjudicator(*args, **kwargs):
        asked.append(True)
        return BEFORE, "기사가 예정이라고 적었다"

    got = judge_project(
        conn,
        _row(conn, project_id),
        SECRETS,
        "2026-09-18",
        search=lambda *a, **k: found,
        adjudicator=adjudicator,
    )
    assert asked
    assert got.decided_by == "llm"
    assert got.verdict == BEFORE


def test_judge_does_not_ask_the_llm_when_the_news_read_is_clear(conn):
    project_id = _project(conn, "전북특별자치도 완주군", "완주군 종합사회복지관")
    found = SearchResult(
        articles=[Article("완주군 종합사회복지관 기공식", "", "https://n/1", "2026-08-28")],
        searched=True,
    )
    asked = []

    def adjudicator(*args, **kwargs):
        asked.append(True)
        return BEFORE, "불려서는 안 된다"

    judge_project(
        conn,
        _row(conn, project_id),
        SECRETS,
        "2026-09-18",
        search=lambda *a, **k: found,
        adjudicator=adjudicator,
    )
    assert not asked


def test_judge_stays_unknown_when_the_llm_cannot_answer(conn):
    project_id = _project(conn, "전북특별자치도 완주군", "완주군 다목적체육관")
    found = SearchResult(
        articles=[
            Article("완주군 다목적체육관 2026년 9월 착공 예정", "", "https://n/2", "2026-08-01")
        ],
        searched=True,
    )
    got = judge_project(
        conn,
        _row(conn, project_id),
        SECRETS,
        "2026-09-18",
        search=lambda *a, **k: found,
        adjudicator=_no_llm,
    )
    assert got.verdict == UNKNOWN
    assert got.decided_by == "news"


def test_judge_records_the_date_conflict_in_the_reason(conn):
    project_id = _project(conn, "전북특별자치도 완주군", "사업")
    conn.execute("UPDATE project SET start_date = '2025-11-03' WHERE id = ?", (project_id,))
    conn.commit()
    got = judge_project(
        conn, _row(conn, project_id), SECRETS, "2026-09-18", search=_no_search, adjudicator=_no_llm
    )
    assert "2025-11-03" in got.reason


def test_judge_never_changes_the_project_dates(conn):
    """불일치를 기록할 뿐 시트 값을 고치지 않는다."""
    project_id = _project(conn, "전북특별자치도 완주군", "사업")
    conn.execute("UPDATE project SET start_date = '2025-11-03' WHERE id = ?", (project_id,))
    conn.commit()
    judge_project(
        conn, _row(conn, project_id), SECRETS, "2026-09-18", search=_no_search, adjudicator=_no_llm
    )
    after = conn.execute("SELECT start_date FROM project WHERE id = ?", (project_id,)).fetchone()
    assert after["start_date"] == "2025-11-03"
```

- [ ] **Step 2: 실패를 확인한다**

Run: `uv run pytest tests/test_status.py -v`
Expected: FAIL — `ImportError: cannot import name 'judge_project'`

- [ ] **Step 3: 최소 구현**

`nara/status.py`에 추가한다.

```python
from collections.abc import Callable

from nara.config import Secrets
from nara.naver import SearchResult
from nara.verdict import Facts, Judgment, date_conflict, read_news, rule_verdict


def judge_project(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    secrets: Secrets,
    today: str,
    search: Callable[..., SearchResult],
    adjudicator: Callable[..., tuple[str, str] | None],
) -> Judgment:
    """한 사업의 진행현황을 판정한다. 규칙 → 뉴스 → LLM 순으로 내려간다.

    어느 단계도 못 가르면 미확인이다. 이 함수는 project 표를 읽기만 하고
    쓰지 않는다 — 사람이 넣은 착공일·준공일을 고치는 경로가 없어야 한다.
    """
    has_winner = bool(
        conn.execute(
            "SELECT 1 FROM notice n JOIN award a ON a.bid_no = n.bid_no "
            "WHERE n.project_id = ? AND COALESCE(a.winner, '') != '' LIMIT 1",
            (row["id"],),
        ).fetchone()
    )
    open_date = (
        conn.execute(
            "SELECT MAX(open_date) FROM notice WHERE project_id = ?", (row["id"],)
        ).fetchone()[0]
        or ""
    )
    dates = (row["start_date"] or "", row["end_date"] or "")

    verdict, reason = rule_verdict(Facts(has_winner=has_winner, open_date=open_date, today=today))
    decided_by, evidence_url = "rule", ""

    found = search(secrets, f"{row['name']} 착공 준공")
    if found.searched and found.articles:
        news = read_news(found.articles, dates)
        verdict = news.verdict
        reason = news.reason
        evidence_url = news.evidence_url
        decided_by = "news"
        if news.needs_llm:
            answer = adjudicator(secrets, row["name"], found.articles, news.llm_reason)
            if answer is not None:
                verdict, reason = answer
                decided_by = "llm"
    elif not found.searched and found.note:
        # 검색을 안 했다는 사실을 근거에 남긴다. 조용히 넘어가지 않는다.
        reason = f"{reason} ({found.note})"

    conflict = date_conflict(verdict, dates, today)
    if conflict:
        reason = f"{reason} / {conflict}"

    return Judgment(
        verdict=verdict, reason=reason, decided_by=decided_by, evidence_url=evidence_url
    )
```

- [ ] **Step 4: 통과를 확인한다**

Run: `uv run pytest tests/test_status.py -v`
Expected: PASS (14개)

- [ ] **Step 5: 커밋**

```bash
git add nara/status.py tests/test_status.py
git commit -m "feat: 규칙 -> 뉴스 -> LLM 순으로 내려가며 진행현황을 판정한다

어느 단계도 못 가르면 미확인이다. 검색을 건너뛰었으면 그 사실을
근거에 적는다. 검색·판정 함수를 주입받아 테스트가 네트워크를
타지 않는다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```
---

### Task 11: 회차를 돌리고 흔적을 남긴다

대상을 돌며 판정하고, `should_record`가 허락한 것만 쌓는다. **시간 예산을 넘기면 처리한 만큼 저장하고 멈춘다**(스펙: 중단과 이어하기). 다음 회차가 이어받는다.

**Files:**
- Modify: `nara/status.py`
- Test: `tests/test_status.py`

**Interfaces:**
- Consumes: Task 9·10의 전부, `nara.runlog.RunCounters`
- Produces: `StatusRun` 데이터클래스(`checked`, `recorded`, `skipped`, `searched`, `asked_llm`, `stopped_early`), `update_statuses(conn, secrets, today, tier, limit, counters, search, adjudicator, budget_seconds=1200, now_fn=...) -> StatusRun`
- `now_fn`은 시간 예산 테스트가 시계를 밀어 넣는 자리다. 기본값은 `time.monotonic`.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
from nara.runlog import RunCounters
from nara.status import update_statuses
from nara.verdict import BEFORE, BUILDING


def _run(conn, **kwargs):
    kwargs.setdefault("search", _no_search)
    kwargs.setdefault("adjudicator", _no_llm)
    kwargs.setdefault("tier", None)
    kwargs.setdefault("limit", 100)
    return update_statuses(conn, SECRETS, "2026-09-18", counters=RunCounters(), **kwargs)


def test_update_statuses_records_a_first_judgment(conn):
    _project(conn, "전북특별자치도 완주군", "사업")
    got = _run(conn)
    assert got.checked == 1
    assert got.recorded == 1
    rows = conn.execute("SELECT verdict, decided_by FROM status_check").fetchall()
    assert len(rows) == 1
    assert rows[0]["decided_by"] == "rule"


def test_update_statuses_does_not_stack_the_same_verdict_twice(conn):
    """두 번 돌려도 같은 판정이면 한 줄만 남는다."""
    _project(conn, "전북특별자치도 완주군", "사업")
    _run(conn)
    second = _run(conn)
    assert second.checked == 1
    assert second.recorded == 0
    assert second.skipped == 1
    assert conn.execute("SELECT COUNT(*) FROM status_check").fetchone()[0] == 1


def test_update_statuses_keeps_human_research_intact(conn):
    """이관된 '시공 중'을 규칙 판정이 밀어내지 않는다."""
    project_id = _project(conn, "전북특별자치도 완주군", "사업")
    conn.execute(
        "INSERT INTO status_check (project_id, verdict, reason, decided_by, checked_at) "
        "VALUES (?, ?, '25.06.30 기공식', 'imported', '2026-09-16T00:00:00')",
        (project_id, BUILDING),
    )
    conn.commit()

    got = _run(conn)

    assert got.recorded == 0
    latest = conn.execute(
        "SELECT verdict FROM status_check ORDER BY checked_at DESC LIMIT 1"
    ).fetchone()
    assert latest["verdict"] == BUILDING


def test_update_statuses_stores_the_evidence_url(conn):
    _project(conn, "전북특별자치도 완주군", "완주군 종합사회복지관")
    found = SearchResult(
        articles=[Article("완주군 종합사회복지관 기공식", "", "https://n/1", "2026-08-28")],
        searched=True,
    )
    _run(conn, search=lambda *a, **k: found)
    row = conn.execute("SELECT verdict, evidence_json FROM status_check").fetchone()
    assert row["verdict"] == BUILDING
    assert "https://n/1" in row["evidence_json"]


def test_update_statuses_counts_what_it_actually_did(conn):
    for i in range(3):
        _project(conn, "전북특별자치도 완주군", f"사업 {i}")
    counters = RunCounters()
    update_statuses(
        conn,
        SECRETS,
        "2026-09-18",
        tier=None,
        limit=100,
        counters=counters,
        search=_no_search,
        adjudicator=_no_llm,
    )
    assert counters.processed == 3
    assert counters.updated == 3


def test_update_statuses_stops_when_the_budget_runs_out(conn):
    """예산을 넘기면 처리한 만큼 저장하고 멈춘다. 다음 회차가 이어받는다."""
    for i in range(5):
        _project(conn, "전북특별자치도 완주군", f"사업 {i}")
    ticks = iter([0.0, 0.0, 30.0, 61.0, 61.0, 61.0, 61.0])

    got = update_statuses(
        conn,
        SECRETS,
        "2026-09-18",
        tier=None,
        limit=100,
        counters=RunCounters(),
        search=_no_search,
        adjudicator=_no_llm,
        budget_seconds=60,
        now_fn=lambda: next(ticks),
    )

    assert got.stopped_early is True
    assert got.checked < 5
    assert conn.execute("SELECT COUNT(*) FROM status_check").fetchone()[0] == got.recorded


def test_update_statuses_reports_that_it_never_searched(conn):
    """키가 없어 뉴스를 한 번도 못 본 회차임을 호출부가 알 수 있어야 한다."""
    _project(conn, "전북특별자치도 완주군", "사업")
    assert _run(conn).searched == 0


def test_update_statuses_rejects_nonpositive_limit(conn):
    with pytest.raises(ValueError):
        _run(conn, limit=0)
```

- [ ] **Step 2: 실패를 확인한다**

Run: `uv run pytest tests/test_status.py -v`
Expected: FAIL — `ImportError: cannot import name 'update_statuses'`

- [ ] **Step 3: 최소 구현**

```python
import json
import time
from dataclasses import dataclass
from datetime import datetime

from nara.runlog import RunCounters
from nara.verdict import should_record

BUDGET_SECONDS = 1200  # 스펙의 기본 시간 예산 20분


@dataclass
class StatusRun:
    checked: int = 0
    recorded: int = 0
    skipped: int = 0
    searched: int = 0
    asked_llm: int = 0
    stopped_early: bool = False


def _latest(conn: sqlite3.Connection, project_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT verdict, decided_by, evidence_json FROM status_check "
        "WHERE project_id = ? ORDER BY checked_at DESC, id DESC LIMIT 1",
        (project_id,),
    ).fetchone()


def update_statuses(
    conn: sqlite3.Connection,
    secrets: Secrets,
    today: str,
    tier: str | None,
    limit: int,
    counters: RunCounters,
    search: Callable[..., SearchResult],
    adjudicator: Callable[..., tuple[str, str] | None],
    budget_seconds: int = BUDGET_SECONDS,
    now_fn: Callable[[], float] = time.monotonic,
) -> StatusRun:
    """대상을 돌며 판정하고 달라진 것만 쌓는다. 예산을 넘기면 멈춘다."""
    rows = pending_status_projects(conn, tier, limit)
    run = StatusRun()
    started = now_fn()

    for row in rows:
        if now_fn() - started > budget_seconds:
            run.stopped_early = True
            break

        counters.processed += 1
        run.checked += 1
        judgment = judge_project(conn, row, secrets, today, search, adjudicator)
        if judgment.decided_by in ("news", "llm"):
            run.searched += 1
        if judgment.decided_by == "llm":
            run.asked_llm += 1

        ok, _ = should_record(_latest(conn, row["id"]), judgment)
        if not ok:
            run.skipped += 1
            continue

        conn.execute(
            "INSERT INTO status_check (project_id, verdict, reason, decided_by, "
            "evidence_json, checked_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                row["id"],
                judgment.verdict,
                judgment.reason,
                judgment.decided_by,
                json.dumps({"url": judgment.evidence_url}, ensure_ascii=False),
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        # 행마다 커밋한다. 중간에 터져도 여기까지는 남는다.
        conn.commit()
        run.recorded += 1
        counters.updated += 1

    return run
```

- [ ] **Step 4: 통과를 확인한다**

Run: `uv run pytest tests/test_status.py -v`
Expected: PASS (22개)

- [ ] **Step 5: 커밋**

```bash
git add nara/status.py tests/test_status.py
git commit -m "feat: 진행현황 회차 — 달라진 판정만 쌓고 예산을 넘기면 멈춘다

행마다 커밋해 중간에 터져도 거기까지는 남는다. 예산 초과는
stopped_early로 드러내고 다음 회차가 이어받는다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```
---

### Task 12: CLI 명령

`nara enrich status`. `enrich award`와 같은 모양으로 만들되, **키가 없어 건너뛴 단계를 반드시 출력한다.**

**Files:**
- Modify: `nara/cli.py`
- Test: `tests/test_status_cli.py`

**Interfaces:**
- Consumes: `nara.status.update_statuses`, `nara.naver.search_news`, `nara.llm.adjudicate`
- `enrich_award`의 `--tier` 검증(계획 1의 Fix6)을 그대로 따른다. 오타는 종료코드 1이다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
from pathlib import Path

from typer.testing import CliRunner

import nara.cli as cli
from nara.cli import app
from nara.config import Secrets, load_settings
from nara.db import connect, migrate
from nara.store import ensure_project, upsert_org

SETTINGS = load_settings(Path(__file__).resolve().parents[1] / "config.toml")
NOW = "2026-09-18T09:00:00"
runner = CliRunner()


def _db(tmp_path, projects=1):
    db = tmp_path / "test.db"
    conn = connect(db)
    migrate(conn)
    org_id = upsert_org(conn, "전북특별자치도 완주군", SETTINGS, NOW)
    for i in range(projects):
        ensure_project(conn, org_id, f"사업 {i}", "manual", NOW)
    conn.close()
    return db


def test_enrich_status_rejects_a_bad_tier(tmp_path):
    result = runner.invoke(app, ["enrich", "status", "--tier", "oops", "--db", str(_db(tmp_path))])
    assert result.exit_code == 1
    assert "focus" in result.output


def test_enrich_status_rejects_nonpositive_limit(tmp_path):
    result = runner.invoke(app, ["enrich", "status", "--limit", "0", "--db", str(_db(tmp_path))])
    assert result.exit_code != 0


def test_enrich_status_says_which_steps_it_skipped(tmp_path, monkeypatch):
    """키가 없으면 그 사실이 화면에 나와야 한다 — 스펙이 요구한다."""
    monkeypatch.setattr(
        cli,
        "load_secrets",
        lambda path: Secrets(
            g2b_api_key="x", naver_client_id=None, naver_client_secret=None, anthropic_api_key=None
        ),
    )
    result = runner.invoke(app, ["enrich", "status", "--db", str(_db(tmp_path))])
    assert result.exit_code == 0
    assert "네이버" in result.output
    assert "Claude" in result.output


def test_enrich_status_reports_counts(tmp_path, monkeypatch):
    monkeypatch.setattr(
        cli,
        "load_secrets",
        lambda path: Secrets(
            g2b_api_key="x", naver_client_id=None, naver_client_secret=None, anthropic_api_key=None
        ),
    )
    result = runner.invoke(app, ["enrich", "status", "--db", str(_db(tmp_path, projects=3))])
    assert "3" in result.output


def test_enrich_status_writes_a_run_log_row(tmp_path, monkeypatch):
    monkeypatch.setattr(
        cli,
        "load_secrets",
        lambda path: Secrets(
            g2b_api_key="x", naver_client_id=None, naver_client_secret=None, anthropic_api_key=None
        ),
    )
    db = _db(tmp_path)
    runner.invoke(app, ["enrich", "status", "--db", str(db)])
    conn = connect(db)
    row = conn.execute(
        "SELECT command, processed, status FROM run_log ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert row["command"] == "enrich status"
    assert row["processed"] == 1
    assert row["status"] == "ok"
```

- [ ] **Step 2: 실패를 확인한다**

Run: `uv run pytest tests/test_status_cli.py -v`
Expected: FAIL — `enrich status` 명령이 없어 exit_code 2

- [ ] **Step 3: 최소 구현**

`nara/cli.py`에 추가한다. 기존 import 줄을 넓혀 쓴다 — 새 import 줄을 따로 만들지 않는다.

```python
@enrich_app.command("status")
def enrich_status(
    tier: str = typer.Option("all", help="focus | rest | all"),
    limit: int = typer.Option(300, min=1, help="한 번에 볼 최대 사업 수"),
    budget: int = typer.Option(1200, min=1, help="시간 예산(초). 넘기면 저장하고 멈춘다"),
    db: Path = typer.Option(DEFAULT_DB),
) -> None:
    """진행현황을 판정해 쌓는다."""
    if tier not in {"focus", "rest", "all"}:
        typer.echo(f"--tier는 focus | rest | all 중 하나여야 한다: {tier!r}", err=True)
        raise typer.Exit(code=1)

    secrets = load_secrets(DEFAULT_ENV)
    skipped = []
    if not (secrets.naver_client_id and secrets.naver_client_secret):
        skipped.append("네이버 검색 키가 없어 뉴스 검색을 건너뛴다 — 규칙 판정만 남는다")
    if not secrets.anthropic_api_key:
        skipped.append("Claude API 키가 없어 애매한 건을 미확인으로 남긴다")

    conn = _open_db(db)
    selected = None if tier == "all" else tier
    with httpx.Client() as client:

        def search(secrets_, query):
            return search_news(client, secrets_, query)

        with run_log(conn, "enrich status", f"--tier {tier}") as counters:
            run = update_statuses(
                conn,
                secrets,
                date.today().isoformat(),
                selected,
                limit,
                counters,
                search=search,
                adjudicator=adjudicate,
                budget_seconds=budget,
            )

    typer.echo(
        f"진행현황 — 확인 {run.checked}건 / 기록 {run.recorded}건 / "
        f"변화 없음 {run.skipped}건 / 뉴스 근거 {run.searched}건 / LLM 판정 {run.asked_llm}건"
    )
    # 건너뛴 단계는 반드시 말한다. 조용히 넘어가면 규칙 판정만 돈 회차를
    # 완전한 판정으로 착각하게 된다.
    for note in skipped:
        typer.echo(note, err=True)
    if run.stopped_early:
        typer.echo(
            f"시간 예산 {budget}초를 넘겨 멈췄다. 다음 회차가 남은 대상을 이어받는다.",
            err=True,
        )
```

- [ ] **Step 4: 통과를 확인한다**

Run: `uv run pytest tests/test_status_cli.py -v`
Expected: PASS (5개)

- [ ] **Step 5: 전체 검사**

```bash
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
```

- [ ] **Step 6: 커밋**

```bash
git add nara/cli.py tests/test_status_cli.py
git commit -m "feat: nara enrich status — 건너뛴 단계를 반드시 말한다

키가 없어 뉴스 검색이나 LLM 판정을 건너뛰었으면 그 사실을 stderr에
적는다. 조용히 넘어가면 규칙 판정만 돈 회차를 완전한 판정으로
착각하게 된다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```
---

### Task 13: doctor가 판정의 모순을 잡는다

스펙의 자가 점검 표에서 진행현황에 해당하는 둘을 더한다. 셋째(`개찰일이 미래인데 낙찰업체가 기록된 행`)는 `nara/doctor.py`에 **이미 있다**(`개찰 전 낙찰` — 확인함). 다시 만들지 않는다.

이 점검은 **이관된 152건에도 걸린다.** 2026-09-16 조사에서 12건이 시트 일정과 보도가 어긋났고, 그 사실은 지금 `status_check.reason`에만 있다. `doctor`가 숫자로 보여줘야 한다.

**Files:**
- Modify: `nara/doctor.py`
- Test: `tests/test_doctor.py`

**Interfaces:**
- Consumes: `nara.verdict`의 어휘 상수
- 기존 `run_checks(conn, today)`에 점검 두 개를 더한다. 새 함수를 만들지 않는다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_doctor.py`에 추가한다. 그 파일의 기존 픽스처를 쓴다.

```python
from nara.verdict import BEFORE, BUILDING, DONE


def _status(conn, project_id, verdict, evidence_json=None, when="2026-09-18T09:00:00"):
    conn.execute(
        "INSERT INTO status_check (project_id, verdict, decided_by, evidence_json, checked_at) "
        "VALUES (?, ?, 'rule', ?, ?)",
        (project_id, verdict, evidence_json, when),
    )
    conn.commit()


def test_doctor_flags_before_construction_with_a_confirmed_start_date(conn):
    """'착공 전'인데 확정 착공일이 있으면 둘 중 하나가 틀렸다."""
    project_id = _project(conn, "전북특별자치도 완주군", "사업")
    conn.execute("UPDATE project SET start_date = '2025-11-03' WHERE id = ?", (project_id,))
    conn.commit()
    _status(conn, project_id, BEFORE)

    checks = [f.check for f in run_checks(conn, "2026-09-18")]

    assert "판정과 착공일 모순" in checks


def test_doctor_is_quiet_when_the_start_date_is_still_ahead(conn):
    """착공 예정일이 미래면 '착공 전'과 어긋나지 않는다 — 헛경보를 내지 않는다."""
    project_id = _project(conn, "전북특별자치도 완주군", "사업")
    conn.execute("UPDATE project SET start_date = '2027-03-01' WHERE id = ?", (project_id,))
    conn.commit()
    _status(conn, project_id, BEFORE)

    checks = [f.check for f in run_checks(conn, "2026-09-18")]

    assert "판정과 착공일 모순" not in checks


def test_doctor_flags_a_strong_verdict_without_evidence(conn):
    project_id = _project(conn, "전북특별자치도 완주군", "사업")
    _status(conn, project_id, DONE, evidence_json=None)

    checks = [f.check for f in run_checks(conn, "2026-09-18")]

    assert "근거 없는 강한 판정" in checks


def test_doctor_accepts_a_strong_verdict_with_an_evidence_url(conn):
    project_id = _project(conn, "전북특별자치도 완주군", "사업")
    _status(conn, project_id, BUILDING, evidence_json='{"url": "https://news.example.com/1"}')

    checks = [f.check for f in run_checks(conn, "2026-09-18")]

    assert "근거 없는 강한 판정" not in checks


def test_doctor_only_looks_at_the_latest_verdict(conn):
    """뒤집힌 옛 판정까지 잡으면 이력을 쌓을수록 경보가 늘어난다."""
    project_id = _project(conn, "전북특별자치도 완주군", "사업")
    _status(conn, project_id, DONE, when="2026-09-01T09:00:00")
    _status(conn, project_id, BEFORE, when="2026-09-18T09:00:00")

    checks = [f.check for f in run_checks(conn, "2026-09-18")]

    assert "근거 없는 강한 판정" not in checks
```

- [ ] **Step 2: 실패를 확인한다**

Run: `uv run pytest tests/test_doctor.py -v`
Expected: FAIL — 세 테스트가 `assert ... in checks`에서 깨진다

- [ ] **Step 3: 최소 구현**

`run_checks` 안에 더한다. 두 점검 모두 **사업별 최신 판정 한 줄만** 본다.

```python
_LATEST_STATUS = (
    "SELECT s.project_id, s.verdict, s.evidence_json, p.name, p.start_date "
    "FROM status_check s JOIN project p ON p.id = s.project_id "
    "WHERE s.id = ("
    "  SELECT id FROM status_check WHERE project_id = s.project_id "
    "  ORDER BY checked_at DESC, id DESC LIMIT 1"
    ")"
)

for row in _rows(conn, _LATEST_STATUS):
    verdict = row["verdict"]
    start = row["start_date"] or ""

    # 판정이 '착공 전'이면 확정 착공일이 있을 수 없다. 낙찰일·심사일을 착공일
    # 칸에 적는 실수가 잦아 이 모순이 실제로 생긴다.
    if verdict == BEFORE and start and start <= today:
        findings.append(
            Finding(
                "판정과 착공일 모순",
                f"{row['name']} — 착공일 {start}이 지났는데 판정은 '{verdict}'",
            )
        )

    # 근거 URL 없는 강한 판정. 판정 경로가 강등하지만 이관분·수기 입력은
    # 그 경로를 타지 않아 여기서 잡아야 한다.
    if verdict in (BUILDING, DONE) and '"url": "http' not in (row["evidence_json"] or ""):
        findings.append(
            Finding("근거 없는 강한 판정", f"{row['name']} — 근거 URL 없이 '{verdict}'")
        )
```

- [ ] **Step 4: 통과를 확인한다**

Run: `uv run pytest tests/test_doctor.py -v`
Expected: PASS

- [ ] **Step 5: 실제 DB에 돌려본다**

```bash
uv run nara doctor --db data/nara.db
```

이관된 152건에 대해 무엇이 걸리는지 숫자로 확인한다. **걸리는 게 있는 것이 정상이다** — 2026-09-16 조사에서 12건이 시트 일정과 어긋났고 ZEB·신재생 열은 전건 미확인이었다. 결과를 커밋 메시지에 적는다.

- [ ] **Step 6: 커밋**

```bash
git add nara/doctor.py tests/test_doctor.py
git commit -m "feat: doctor가 판정과 날짜의 모순, 근거 없는 강한 판정을 잡는다

사업별 최신 판정 한 줄만 본다 — 뒤집힌 옛 판정까지 세면 이력을
쌓을수록 경보가 늘어 점검이 무력해진다.

실제 DB 결과: <숫자를 여기 적는다>

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```
---

### Task 14: 실제로 틀렸던 네 건을 테스트로 박는다

스펙: "TSV 줄병합과 진행현황 강등 규칙은 **실제로 틀렸던 입력을 그대로 테스트 케이스로 박아 둔다.**"

아래 넷은 2026-09-16 전북 조사에서 조사자가 실제로 헷갈렸거나 틀린 건이다. 기사 문구는 그때 남은 조사결과 노트에서 가져왔다. **지어내지 말 것** — 아래 표의 문자열을 그대로 쓴다.

| 사업 | 그때 무슨 일이 있었나 | 이 테스트가 지키는 것 |
|---|---|---|
| 완주군 다목적체육관 | "2026년 9월 착공"이 예정인지 실제인지 갈리지 않았다 | 착공+예정이 겹치면 판정하지 않고 넘긴다 |
| 진안복합노인 복지센터 | 2006년 개원 시설이 검색돼 들어왔다(시트는 2007 착공·2008 준공) | 기사 연도가 어긋나면 넘긴다 |
| 순창군 동계면 종합체육관 | 착공 기사와 준공 기사가 동시에 잡혔다 | 둘이 겹치면 넘긴다 |
| 옛 청사 철거 | 철거를 착공으로 오판해 영업 대상에서 빼는 사고가 반복됐다 | 철거는 착공이 아니다 |

**Files:**
- Create: `tests/test_status_regression.py`

**Interfaces:**
- Consumes: `nara.verdict`의 `read_news`, `Article`, 어휘 상수

- [ ] **Step 1: 테스트를 쓴다**

이 작업은 회귀 테스트만 더한다. 구현은 Task 1~6에서 이미 끝났으므로 **처음부터 통과해야 한다.** 하나라도 실패하면 그 규칙이 실제로는 안 지켜지고 있다는 뜻이니, 테스트를 고치지 말고 규칙을 고친다.

```python
"""2026-09-16 전북 조사에서 실제로 틀렸거나 헷갈렸던 건을 그대로 박아 둔다.

여기가 깨지면 그때의 사고가 되돌아온 것이다. 테스트를 고치지 말고 규칙을 고친다.
"""

from nara.verdict import BEFORE, BUILDING, DONE, UNKNOWN, Article, read_news


def test_wanju_multipurpose_gym_start_or_plan_is_not_decided_by_rules():
    """완주군 다목적체육관 — 시트 착공 2026.04.30, 보도 '2026.09 착공'.

    예정인지 실제인지 기사만으로 갈리지 않는다. 기계가 정하면 안 된다.
    """
    got = read_news(
        [
            Article(
                "완주군 다목적체육관 조성사업 2026년 9월 착공 목표",
                "",
                "https://news.example.com/wanju",
                "2026-08-10",
            )
        ],
        ("2026-04-30", "2028-12-31"),
    )
    assert got.needs_llm is True
    assert got.verdict == UNKNOWN


def test_jinan_senior_center_2006_article_does_not_decide_a_2026_project():
    """진안복합노인 복지센터 — 2006.05 개원 기사가 검색돼 들어왔다.

    시트는 착공 2007·준공 2008이다. 같은 이름의 다른(또는 옛) 시설이다.
    """
    got = read_news(
        [Article("진안복합노인 복지센터 개원", "", "https://news.example.com/jinan", "2006-05-26")],
        ("2026-01-01", "2027-12-31"),
    )
    assert got.needs_llm is True
    assert got.verdict != DONE


def test_sunchang_gym_completion_and_start_articles_collide():
    """순창군 동계면 종합체육관 — 시트 착공 2025.07.17, 보도는 2020 착공·2025.06.25 준공."""
    got = read_news(
        [
            Article(
                "순창군 동계면 종합체육관 착공", "", "https://news.example.com/s1", "2020-01-15"
            ),
            Article(
                "순창군 동계면 종합체육관 준공식", "", "https://news.example.com/s2", "2025-06-25"
            ),
        ],
        ("2025-07-17", "2026-12-31"),
    )
    assert got.needs_llm is True


def test_demolition_is_not_construction_start():
    """철거를 착공으로 읽어 영업 대상에서 빼는 사고가 반복됐다.

    이주 → 철거 → 본공사 착공 순서다. 철거 중이면 오히려 접촉 최적기다.
    """
    got = read_news(
        [
            Article(
                "옛 청사 철거공사 착수",
                "멸실 신고를 마쳤다",
                "https://news.example.com/demo",
                "2026-07-01",
            )
        ],
        ("", ""),
    )
    assert got.verdict == BEFORE
    assert got.needs_llm is False


def test_a_clear_groundbreaking_still_reads_as_construction():
    """강등 규칙이 과해져서 진짜 착공까지 놓치면 안 된다 — 반대 방향 확인."""
    got = read_news(
        [
            Article(
                "완주군 종합사회복지관 기공식 개최", "", "https://news.example.com/w2", "2026-08-28"
            )
        ],
        ("2027-10-07", ""),
    )
    assert got.verdict == BUILDING
    assert got.needs_llm is False
```

- [ ] **Step 2: 통과를 확인한다**

Run: `uv run pytest tests/test_status_regression.py -v`
Expected: PASS (5개). **실패하면 규칙을 고친다. 테스트를 고치지 않는다.**

- [ ] **Step 3: 전체 검사**

```bash
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
```

- [ ] **Step 4: 커밋**

```bash
git add tests/test_status_regression.py
git commit -m "test: 2026-09-16에 실제로 틀렸던 네 건을 회귀 테스트로 박는다

완주군 다목적체육관(착공/예정), 진안복합노인 복지센터(기사 연도),
순창군 동계면 종합체육관(착공/준공 동시), 철거 오판. 여기가 깨지면
그때의 사고가 되돌아온 것이다.

반대 방향도 하나 박았다 — 진짜 기공식은 여전히 '시공 중'으로 읽혀야
강등 규칙이 과해지지 않는다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## 마무리

- [ ] `uv run pytest -q` — 전부 통과
- [ ] `uv run ruff check .` · `uv run ruff format --check .` — 깨끗
- [ ] `uv run nara enrich status --db data/nara.db --limit 20` — 실제 DB에서 한 회차 돌려보고 출력을 기록한다. 키가 없으므로 **"네이버 검색 키가 없어…"와 "Claude API 키가 없어…"가 stderr에 나와야 한다.** 안 나오면 결함이다.
- [ ] `uv run nara doctor --db data/nara.db` — 새 점검 두 개의 결과를 숫자로 기록한다
- [ ] `docs/known-issues.md`에 이번에 이월한 항목을 더한다

## 자체 점검 (계획 작성자가 직접 돌린 것)

**스펙 대응:** 3단계 절의 요구 하나하나에 작업을 붙였다.

| 스펙 요구 | 작업 |
|---|---|
| 규칙이 바로 판정하는 세 경우 | Task 1 |
| LLM으로 넘기는 네 상황 | Task 4(세 개는 규칙으로 감지) + Task 8(판정) + Task 14(회귀) |
| 개찰일·낙찰일을 착공일로 쓰지 않는다 | Task 10이 `project`를 읽기만 한다(쓰기 경로 없음) + Task 13 점검 |
| 착공 전이면 확정 착공일을 기록하지 않는다 | Task 13 점검 |
| 근거 URL 없는 강한 판정을 내린다 | Task 3 + Task 13 점검 |
| 사람이 넣은 날짜와 어긋나면 기록만 한다 | Task 6 + Task 10 |
| 네이버 키가 없으면 건너뛰고 표시한다 | Task 7 + Task 12 |
| 판정을 이력으로 쌓는다 | Task 5 + Task 11 |
| 시간 예산 20분, 넘기면 저장하고 멈춘다 | Task 11 |
| 실제로 틀렸던 입력을 테스트로 박는다 | Task 14 |

**빈칸 없음:** "적절히 처리한다" 류의 문장 없이 모든 코드 단계에 실제 코드가 있다.

**타입 일관성:** `Judgment`(Task 5)를 Task 10·11이 그대로 쓴다. `Article`(Task 2)을 Task 4·7·8·14가 쓴다. `SearchResult`(Task 7)를 Task 10·11이 쓴다. `Facts`(Task 1)는 Task 10만 만든다. 이름이 갈라지는 곳은 없다.

**알려진 한계 — 사용자에게 미리 말할 것:**

- 네이버·Claude 키가 없으므로 **이 계획이 끝나도 실제 뉴스 판정은 검증되지 않는다.** 규칙 경로와 "건너뛰었다" 경로만 실데이터로 확인된다. 계획 1에서 인증키가 들어온 뒤 파이프라인 전체가 검증됐던 것과 같은 단계를 여기서는 못 밟는다.
- `read_signals`는 낱말 대조다. "착공"이라는 낱말이 없는 착공 기사는 못 읽는다. 뉴스 경로를 실제로 돌려보기 전에는 이 규칙이 실전에서 얼마나 맞는지 알 수 없다.
