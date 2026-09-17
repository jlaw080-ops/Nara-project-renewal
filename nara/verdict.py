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
