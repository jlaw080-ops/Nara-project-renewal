"""실행부서 판정 규칙 — 스킬에 적힌 실제 실패 사례를 옮겼다."""

from nara.dept_rules import (
    DeptAnswer,
    decide_by_rule,
    excerpt_for_llm,
    find_candidates,
    find_contract_dept,
    unspace,
    verify_answer,
)

PAIR = (
    "13. 기타사항\n"
    "가. 계약관련 문의: 재무과 계약팀 (063-000-0000)\n"
    "나. 사업관련 문의: 문화관광과 관광팀 (063-000-0001)\n"
)


def _names(text):
    return [c.name for c in find_candidates(text)]


def test_the_pair_structure_gives_the_executing_department():
    """공고문은 계약부서와 실행부서를 짝으로 적는다. 실행부서 쪽을 고른다."""
    candidates = find_candidates(PAIR)
    assert [c.name for c in candidates] == ["문화관광과"]
    assert candidates[0].near
    assert "사업관련 문의" in candidates[0].snippet
    assert decide_by_rule(candidates).name == "문화관광과"
    assert find_contract_dept(PAIR) == "재무과"


def test_contract_departments_are_never_candidates():
    assert _names("문의처: 재무과 경리팀 063-000-0000") == []
    assert _names("사업 담당 부서: 회계과") == []


def test_a_conjunction_is_not_a_department():
    """조사 '과'(=and)가 붙은 말은 부서가 아니다. '동 용역과'처럼 지시어 뒤도 그렇다."""
    assert _names("과업 관련 문의: 동 용역과 관련하여 도시계획과로 문의") == ["도시계획과"]
    assert _names("사업관련 문의는 다음과 같이 건축과 건축팀으로 한다") == ["건축과"]


def test_spaced_out_names_are_joined():
    """칸을 맞추려고 부서명 글자 사이를 띄운 공고문이 있다."""
    assert unspace("사업 담당 부서 : 행 정 과") == "사업 담당 부서 : 행정과"
    assert _names("사업 담당 부서 : 행 정 과 (063-000-0000)") == ["행정과"]


def test_a_team_name_is_reduced_to_its_division():
    assert _names("사업담당: 문화관광과 문화유산팀") == ["문화관광과"]


def test_two_candidates_are_not_decided_by_rule():
    text = "사업관련 문의: 건축과\n설계서 열람 문의: 도시재생과"
    assert sorted(_names(text)) == ["건축과", "도시재생과"]
    assert decide_by_rule(find_candidates(text)) is None


def test_a_department_far_from_the_cue_is_not_decided_by_rule():
    text = "사업관련 문의: " + "가" * 120 + " 건축과"
    candidates = find_candidates(text)
    assert [c.name for c in candidates] == ["건축과"]
    assert not candidates[0].near
    assert decide_by_rule(candidates) is None


def test_the_excerpt_keeps_the_contact_sections_and_the_end():
    body = "가" * 5000 + "\n사업관련 문의: 건축과\n" + "나" * 5000 + "\n문의처: 행정과 끝"
    excerpt = excerpt_for_llm(body)
    assert "사업관련 문의: 건축과" in excerpt
    assert excerpt.endswith("문의처: 행정과 끝")
    assert len(excerpt) <= 6000


def _answer(dept, quote, contract=None):
    return DeptAnswer(exec_dept=dept, contract_dept=contract, quote=quote)


def test_a_quote_found_in_the_text_confirms_the_answer():
    assert verify_answer(PAIR, _answer("문화관광과", "사업관련 문의: 문화관광과 관광팀"))


def test_spacing_and_line_breaks_do_not_break_the_match():
    """PDF는 줄을 아무 데서나 끊는다. 공백을 빼고 비교한다."""
    text = "나. 사업관련\n문의: 문화 관광과 관광팀"
    assert verify_answer(text, _answer("문화관광과", "사업관련 문의: 문화관광과 관광팀"))


def test_a_reworded_quote_is_rejected():
    assert not verify_answer(PAIR, _answer("문화관광과", "사업 문의는 문화관광과에서 받습니다"))


def test_a_department_missing_from_its_own_quote_is_rejected():
    assert not verify_answer(PAIR, _answer("건축과", "사업관련 문의: 문화관광과 관광팀"))


def test_a_contract_department_answer_is_rejected():
    assert not verify_answer(PAIR, _answer("재무과", "계약관련 문의: 재무과 계약팀"))


def test_a_team_only_or_empty_answer_is_rejected():
    text = "사업관련 문의: 관광팀 (063-000-0001)"
    assert not verify_answer(text, _answer("관광팀", "사업관련 문의: 관광팀"))
    assert not verify_answer(PAIR, _answer(None, "사업관련 문의: 문화관광과 관광팀"))
    assert not verify_answer(PAIR, _answer("문화관광과", "관광과"))


# 실데이터 검증(2026-09-30)에서 시트 값과 어긋난 자동 확정 네 건. 본문 속 일반 신호어로
# 찾은 부서는 후보일 뿐이다. 문의처를 가리키는 신호어 근처에서 찾아야 확정한다.
def test_a_venue_after_place_is_not_confirmed():
    text = (
        "◦ 장소: 미정(설계공모 홈페이지을 통해 추후 공지) ◦ 기타사항은 설계공모지침서 참조 "
        "※ 심사일 및 심사장소는 발주기관의 사정에 따라 변경될 수 있음"
    )
    assert "심사장소" not in _names(text)
    assert decide_by_rule(find_candidates(text)) is None


def test_a_facility_in_the_task_prose_is_not_confirmed():
    text = "- 본 사업 관련 홍보 및 교육방안 등 - 커뮤니티센터 설치 및 인테리어 계획"
    assert decide_by_rule(find_candidates(text)) is None
    text = "가. 본 과업지시서는 “비봉면 행정복지센터 건립사업 설계용역”에 적용한다."
    assert decide_by_rule(find_candidates(text)) is None


def test_the_ordering_agency_and_is_not_a_department():
    text = (
        "○ 과업을 수행함에 있어 과업지시서에 명기되지 아니한 사항은 발주기관과 수급인이 상호 조정"
    )
    assert "발주기관과" not in _names(text)


def test_a_contact_cue_still_confirms():
    text = "나. 과업 관련 문의: 환경사업소 자원순환팀 (063-580-0000)"
    assert decide_by_rule(find_candidates(text)).name == "환경사업소"


def test_a_word_ending_in_result_is_not_a_department():
    """'결과'·'효과'처럼 '과'로 끝나는 보통 낱말은 부서가 아니다(실데이터 사례)."""
    text = "지역업체 참여도는 사업부서의 심사 평가결과에 따릅니다."
    assert "평가결과" not in _names(text)
    assert _names("사업부서: 성과관리과 (063-000-0000)") == ["성과관리과"]


def test_a_cue_glued_to_the_name_does_not_join_it():
    """HWPX 탭·PDF 추출로 신호어와 부서명이 붙어도 신호어가 이름에 들어가지 않는다."""
    assert decide_by_rule(find_candidates("○ 사업담당도시재생과 홍길동")).name == "도시재생과"
    assert _names("담당부서건축과 (063-000-0000)") == ["건축과"]


def test_part_of_a_longer_name_does_not_verify():
    """'도시건축과' 안에 '건축과'가 들어 있어도 건축과라고 적힌 것이 아니다."""
    quote = "사업 담당부서: 도시건축과 건축팀"
    text = f"13. 기타\n{quote}\n"
    assert not verify_answer(text, _answer("건축과", quote))
    assert verify_answer(text, _answer("도시건축과", quote))


def _after_cue(phrase: str) -> list[str]:
    """신호어 바로 뒤에 phrase를 두고, 끝에 진짜 부서를 하나 둔다."""
    return _names(f"사업부서 문의: {phrase} 담당은 건축과")


def test_a_noun_joined_by_and_is_not_a_department():
    """'~사항과', '~수행과'는 조사 '과'가 붙은 말이다(2026-09-30 슬롯 사례)."""
    assert _after_cue("명시하지 않은 세부적인 위반사항과 추가 보완") == ["건축과"]
    assert _after_cue("과업수행과 관련하여 제3자에게") == ["건축과"]
    assert _after_cue("업무수행과 관련한 일체사항") == ["건축과"]


def test_ordinary_words_that_look_like_departments_are_not_candidates():
    """벌점부과·등록취소·입찰취소·접견실·신고센터는 부서가 아니다(2026-09-30 슬롯 사례)."""
    assert _after_cue("건설기술용역업자 벌점부과, 등록취소, 영업정지") == ["건축과"]
    assert _after_cue("입찰취소를 신청할 수 있습니다") == ["건축과"]
    assert _names("장소 : 대전광역시청 2층 민원인 접견실") == []
    assert _after_cue("공직자부조리 신고센터(031-000-0000)") == ["건축과"]


def test_the_front_of_a_longer_word_is_not_a_department():
    """'설계과정'의 '설계과', '특정단체'의 '특정단'처럼 낱말 앞부분을 떼어 내지 않는다."""
    assert _after_cue("모든 설계과정에서 발주자와 협의") == ["건축과"]
    assert _after_cue("주요 설계과업내용 변경 시 설계과오가 있으면") == ["건축과"]
    assert _after_cue("개인 또는 특정단체 등의 이익") == ["건축과"]
    assert _after_cue("눈개승마 재배단지 꽃밭 조성") == ["건축과"]
    assert _names("사업부서: 건축과에서 담당, 도시계획과장 확인") == ["건축과", "도시계획과"]


def test_a_name_that_starts_with_a_number_is_kept_whole_and_left_for_review():
    """'100세행복과'를 '세행복과'로 자르면 틀린 이름이 확정된다(논산시 사례).

    숫자로 시작하는 이름은 전화번호가 붙은 것('2842건축과')과 가릴 수 없어 규칙으로
    확정하지 않고 사람이 본다.
    """
    text = "8. 문의처 : 논산시 100세행복과 어르신시설팀(☏ 041-746-5803)으로 문의"
    assert _names(text) == ["100세행복과"]
    assert decide_by_rule(find_candidates(text)) is None


def test_general_affairs_stays_a_candidate():
    """구청 총무과는 입찰 창구일 때가 많지만 사업을 맡기도 한다 — 빼지 않고 사람이 고른다."""
    assert "총무과" in _names("사업관련 문의: 총무과 (031-000-0000)")
