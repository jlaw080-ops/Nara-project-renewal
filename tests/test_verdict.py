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
    Judgment,
    date_conflict,
    demote_without_evidence,
    read_news,
    read_signals,
    rule_verdict,
    should_record,
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


def test_read_news_defers_when_start_is_hedged_by_cancellation():
    """무산은 예정이 아니다 — 착공이 엎어졌다는 뜻이라 확정하면 대상에서 영영 빠진다(F1)."""
    got = read_news([_a("주민 반발에 완주군 다목적체육관 착공 무산")], ("", ""))
    assert got.needs_llm is True
    assert got.verdict != BUILDING


def test_read_news_defers_when_completion_is_hedged_by_suspension():
    got = read_news([_a("완주군 종합사회복지관 준공 지연, 공사 중단")], ("", ""))
    assert got.needs_llm is True
    assert got.verdict != DONE


def test_read_news_defers_when_completion_is_hedged_by_imminent_wording():
    got = read_news([_a("순창군 동계면 종합체육관, 10월 준공 앞두고 마무리 공사 한창")], ("", ""))
    assert got.needs_llm is True


def test_read_news_defers_when_start_is_hedged_by_postponement():
    got = read_news([_a("완주군 다목적체육관 착공 연기")], ("", ""))
    assert got.needs_llm is True


def test_read_news_defers_when_start_is_hedged_by_public_demand():
    """주민 촉구는 아직 착공하지 않았다는 신호다 — 확정하면 안 된다."""
    got = read_news([_a("주민들 조속한 착공 촉구")], ("", ""))
    assert got.needs_llm is True


def test_read_news_still_confirms_clean_groundbreaking_report():
    """유보 낱말이 없는 깨끗한 기공식 기사는 과교정 없이 그대로 확정해야 한다."""
    got = read_news([_a("완주군 종합사회복지관 기공식 개최")], ("", ""))
    assert got.verdict == BUILDING
    assert got.needs_llm is False


def test_read_news_picks_article_with_evidence_url_over_urlless_first_match():
    """같은 판정 그룹 안에서 URL 없는 첫 기사 때문에 뒤의 근거 있는 기사를 놓치면 안 된다(F2)."""
    first = Article("체육관 준공식", "", "", "2026-08-01")
    second = Article("체육관 준공 확인", "", "https://news.example.com/good", "2026-08-01")
    got = read_news([first, second], ("", ""))
    assert got.verdict == DONE
    assert got.evidence_url == "https://news.example.com/good"


def test_read_news_defers_when_hedge_is_only_on_one_article_in_start_group():
    """R12/F3 — 유보 신호가 '고른 기사' 하나가 아니라 묶음 전체에 걸려야 한다.

    URL 있는 '착공식 개최' 기사 뒤에 URL 없는 '착공 무산' 기사가 섞여 있어도,
    _pick_with_evidence가 URL 있는 쪽을 고른다는 이유로 무산 신호를 지워선 안 된다.
    """
    got = read_news(
        [
            Article("주민 반발에 완주군 다목적체육관 착공 무산", "", "", "2026-08-01"),
            Article(
                "완주군 다목적체육관 착공식 개최",
                "",
                "https://news.example.com/ok",
                "2026-08-02",
            ),
        ],
        ("", ""),
    )
    assert got.needs_llm is True
    assert got.verdict != BUILDING


def test_read_news_defers_when_hedge_collides_regardless_of_missing_urls():
    """URL이 둘 다 비어 있어도 묶음 안의 유보 신호는 그대로 걸려야 한다."""
    got = read_news(
        [
            Article("주민 반발에 완주군 다목적체육관 착공 무산", "", "", "2026-08-01"),
            Article("완주군 다목적체육관 착공식 개최", "", "", "2026-08-02"),
        ],
        ("", ""),
    )
    assert got.needs_llm is True
    assert got.verdict != BUILDING


def test_read_news_confirms_construction_despite_resident_demand_wording():
    """'요구'는 유보 낱말에서 뺐다(F4) — 흔한 표현이라 멀쩡한 기사까지 위임시킨다."""
    got = read_news([_a("주민 요구 수용해 설계 변경 뒤 기공식")], ("", ""))
    assert got.needs_llm is False
    assert got.verdict == BUILDING


def test_read_news_confirms_completion_despite_resident_suggestion_wording():
    """'건의'도 유보 낱말에서 뺐다(F4) — 같은 이유."""
    got = read_news([_a("주민 건의 반영한 복지관 준공식")], ("", ""))
    assert got.needs_llm is False
    assert got.verdict == DONE


def _latest(verdict, decided_by, evidence_url="", reason=""):
    return {
        "verdict": verdict,
        "decided_by": decided_by,
        "evidence_json": evidence_url,
        "reason": reason,
    }


def test_should_record_first_judgment():
    ok, _ = should_record(None, Judgment(BEFORE, "개찰 근거", "rule", ""))
    assert ok is True


def test_should_record_skips_identical_repeat():
    """같은 판정 + 같은 사유를 회차마다 다시 쌓지 않는다 — 이력이 못 읽을 것이 된다."""
    latest = _latest(BEFORE, "rule", reason="개찰 근거")
    ok, why = should_record(latest, Judgment(BEFORE, "개찰 근거", "rule", ""))
    assert ok is False
    assert why


def test_should_record_when_verdict_changes():
    latest = _latest(BEFORE, "rule")
    ok, _ = should_record(latest, Judgment(BUILDING, "기공식 보도", "news", "https://n/1"))
    assert ok is True


def test_should_record_when_reason_changes_even_if_verdict_does_not():
    """F3 — 판정은 같아도 사유가 바뀌면(새 사실 확인) 기록한다.

    '개찰일이 지났고 낙찰업체 미확인' → '낙찰업체가 기록됨'은 둘 다 착공 전이지만
    낙찰업체가 새로 확인됐다는 사실이 다르다. verdict만 비교하면 이 변화가
    이력에서 영영 사라진다.
    """
    latest = _latest(BEFORE, "rule", reason="개찰일이 지났고 낙찰업체 미확인")
    ok, _ = should_record(latest, Judgment(BEFORE, "낙찰업체가 기록됨", "rule", ""))
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


def test_should_record_guard_closes_on_unrecognized_decided_by_value():
    """F1 — 대문자 오타 등 모르는 decided_by 값이 와도 가드가 열리면 안 된다.

    'rule'이 아니면 전부 막는다 — 사람이든 이관이든, 우리가 모르는 값이든.
    """
    ok, _ = should_record(
        {"verdict": BUILDING, "decided_by": "Imported", "reason": "x"},
        Judgment(BEFORE, "개찰 근거", "rule", ""),
    )
    assert ok is False


def test_should_record_guard_ignores_evidence_url_on_rule_candidate():
    """F2 — 규칙 판정에 evidence_url이 붙어도 가드를 우회하지 못한다.

    규칙 판정은 DB 사실로 내리는 것이라 뉴스 근거를 가질 일이 없다.
    evidence_url 유무로 가드를 여는 조건 자체를 없앤다.
    """
    ok, _ = should_record(
        {"verdict": BUILDING, "decided_by": "imported", "reason": "25.06.30 기공식"},
        Judgment(BEFORE, "개찰 근거", "rule", "https://n/1"),
    )
    assert ok is False


def test_conflict_when_before_construction_but_start_date_has_passed():
    """'착공 전'인데 시트의 착공일이 이미 지났다 — 둘 중 하나가 틀렸다."""
    note = date_conflict(BEFORE, ("2025-11-03", ""), "2026-09-18")
    assert note and "착공" in note


def test_no_conflict_when_before_construction_and_start_date_is_future():
    assert date_conflict(BEFORE, ("2027-03-01", ""), "2026-09-18") is None


def test_conflict_when_completed_but_end_date_is_future():
    note = date_conflict(DONE, ("", "2029-01-30"), "2026-09-18")
    assert note and "준공" in note


def test_no_conflict_when_before_construction_and_start_date_is_blank():
    """F4 — 착공일이 비어 있으면 '착공 전' 판정과 비교할 것이 없다.

    빈 문자열은 사전식 비교에서 어떤 날짜보다도 작아 '지났다'로 오판되기
    쉽다. 이 가드(`and start`)를 지우면 이 테스트가 실패해야 한다.
    """
    assert date_conflict(BEFORE, ("", ""), "2026-09-18") is None


def test_no_conflict_when_completed_and_end_date_is_blank():
    """F4 — 준공일이 비어 있으면 '준공 완료' 판정과 비교할 것이 없다."""
    assert date_conflict(DONE, ("", ""), "2026-09-18") is None


def test_conflict_never_changes_the_dates():
    """이 함수는 문자열만 돌려준다. 값을 고치는 경로가 아예 없다."""
    dates = ("2025-11-03", "2026-01-01")
    date_conflict(BEFORE, dates, "2026-09-18")
    assert dates == ("2025-11-03", "2026-01-01")
