from nara.verdict import (
    BEFORE,
    BUILDING,
    DONE,
    SIGNAL_DEMOLITION,
    SIGNAL_DESIGN,
    SIGNAL_DONE,
    SIGNAL_PLANNED,
    SIGNAL_START,
    UNKNOWN,
    Article,
    Facts,
    demote_without_evidence,
    read_news,
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


def test_read_signals_finds_pure_demolition_without_start():
    """철거 낱말만 있고 착공 낱말이 없으면 착공 신호는 세우지 않는다."""
    signals = read_signals(_a(title="옛 청사 철거 현장 가림막 설치"))
    assert SIGNAL_DEMOLITION in signals
    assert SIGNAL_START not in signals


def test_read_signals_raises_both_on_demolition_and_start_collision():
    """'철거 마치고 본공사 착공'은 착공을 보도하는 기사다.

    철거 낱말이 있다고 착공 신호를 죽이면 실제 착공 기사를 놓친다(F1).
    둘 다 세워서 다음 단계(read_news)가 애매함으로 보류하게 한다 —
    잘못된 확정 판정보다 미확인 쪽이 안전하다.
    """
    signals = read_signals(_a(title="완주군 종합복지관, 철거 마치고 본공사 착공"))
    assert SIGNAL_DEMOLITION in signals
    assert SIGNAL_START in signals


def test_read_signals_does_not_treat_committee_dissolution_as_demolition():
    """'추진위원회 해체'는 물리적 철거가 아니다. '해체'는 철거 낱말 목록에서 뺐다(F2)."""
    signals = read_signals(_a(title="추진위원회 해체"))
    assert SIGNAL_DEMOLITION not in signals


def test_read_signals_marks_planned_language():
    """'2026년 9월 착공 예정'은 착공이 아니다."""
    signals = read_signals(_a(title="완주군 다목적체육관 2026년 9월 착공 예정"))
    assert SIGNAL_PLANNED in signals
    assert SIGNAL_START in signals  # '착공'이라는 말은 있다 — 판단은 다음 단계가 한다


def test_read_signals_finds_design_stage():
    assert SIGNAL_DESIGN in read_signals(_a(title="설계공모 당선작 발표"))


def test_read_signals_does_not_read_builder_award_as_design_stage():
    """시공사 낙찰은 설계 단계가 아니다. '낙찰'은 설계 낱말 목록에서 뺐다(F3).

    설계 낙찰 여부는 award 테이블로 이미 안다(rule_verdict) — 뉴스에서
    '낙찰'을 다시 읽으면 시공사 낙찰과 구분되지 않아 오히려 오도한다.
    """
    signals = read_signals(_a(title="OO체육관 신축공사 시공사 A건설 낙찰"))
    assert SIGNAL_DESIGN not in signals


def test_read_signals_returns_empty_for_unrelated_text():
    assert read_signals(_a(title="군수 신년사")) == frozenset()


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


def test_read_news_reports_unknown_without_articles():
    got = read_news([], ("", ""))
    assert got.verdict == UNKNOWN
    assert got.needs_llm is False


def test_read_news_calls_construction_when_groundbreaking_is_reported():
    got = read_news([_a("완주군 종합사회복지관 기공식 개최")], ("", ""))
    assert got.verdict == BUILDING
    assert got.evidence_url == "https://example.com/1"


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
    """착공 낱말이 없는 순수 철거 기사만 확신을 갖고 착공 전으로 본다."""
    got = read_news([_a("옛 청사 철거 현장 가림막 설치")], ("", ""))
    assert got.verdict == BEFORE
    assert got.needs_llm is False


def test_read_news_defers_when_demolition_and_construction_start_collide():
    """'철거 마치고 본공사 착공' — 철거 기사인지 착공 기사인지 기계가 못 가른다."""
    got = read_news(
        [_a("완주군 종합복지관, 철거 마치고 본공사 착공")],
        ("", ""),
    )
    assert got.needs_llm is True
    assert "철거" in got.llm_reason


def test_read_news_never_returns_strong_verdict_without_evidence_url():
    got = read_news([_a("체육관 준공", url="")], ("", ""))
    assert got.verdict not in (BUILDING, DONE)
