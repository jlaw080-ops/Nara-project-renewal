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


_STRONG = (BUILDING, DONE)


def demote_without_evidence(verdict: str, evidence_url: str | None) -> tuple[str, str | None]:
    """근거 URL 없는 '시공 중'·'준공 완료'는 '착공 전'으로 내린다.

    (판정, 강등 메모). 강등하지 않았으면 메모는 None이다.
    """
    if verdict in _STRONG and not (evidence_url or "").strip():
        return BEFORE, f"근거 URL이 없어 '{verdict}' 주장을 착공 전으로 내림"
    return verdict, None
