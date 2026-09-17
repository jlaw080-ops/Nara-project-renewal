from nara.verdict import (
    BEFORE,
    SIGNAL_DEMOLITION,
    SIGNAL_DESIGN,
    SIGNAL_DONE,
    SIGNAL_PLANNED,
    SIGNAL_START,
    UNKNOWN,
    Article,
    Facts,
    read_signals,
    rule_verdict,
)


def test_rule_verdict_uses_award_as_evidence_of_design_stage():
    """낙찰업체가 있으면 설계가 도는 중이다. 착공했다는 뜻이 아니다."""
    facts = Facts(has_winner=True, open_date="2026-09-10", today="2026-09-18")
    verdict, reason = rule_verdict(facts)
    assert verdict == BEFORE
    assert "낙찰" in reason


def test_rule_verdict_uses_passed_opening_when_winner_unknown():
    facts = Facts(has_winner=False, open_date="2026-09-10", today="2026-09-18")
    verdict, reason = rule_verdict(facts)
    assert verdict == BEFORE
    assert "개찰" in reason


def test_rule_verdict_is_unknown_before_opening():
    """개찰 전이면 아무것도 모른다. 공고일로 추정하지 않는다."""
    facts = Facts(has_winner=False, open_date="2026-12-01", today="2026-09-18")
    verdict, reason = rule_verdict(facts)
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
