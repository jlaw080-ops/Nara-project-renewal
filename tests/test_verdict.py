from nara.verdict import BEFORE, UNKNOWN, Facts, rule_verdict


def test_rule_verdict_uses_award_as_evidence_of_design_stage():
    """낙찰업체가 있으면 설계가 도는 중이다. 착공했다는 뜻이 아니다."""
    verdict, reason = rule_verdict(Facts(has_winner=True, open_date="2026-09-10", today="2026-09-18"))
    assert verdict == BEFORE
    assert "낙찰" in reason


def test_rule_verdict_uses_passed_opening_when_winner_unknown():
    verdict, reason = rule_verdict(Facts(has_winner=False, open_date="2026-09-10", today="2026-09-18"))
    assert verdict == BEFORE
    assert "개찰" in reason


def test_rule_verdict_is_unknown_before_opening():
    """개찰 전이면 아무것도 모른다. 공고일로 추정하지 않는다."""
    verdict, reason = rule_verdict(Facts(has_winner=False, open_date="2026-12-01", today="2026-09-18"))
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
