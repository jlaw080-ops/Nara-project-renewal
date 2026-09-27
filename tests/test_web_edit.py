"""웹 입력 — 검증은 DB 없이, 저장은 임시 DB로 확인한다."""

from nara.energy import EnergyItem
from nara.verdict import BEFORE, BUILDING
from nara.web.edit import (
    LONG_TEXT_LIMIT,
    TEXT_LIMIT,
    check_dept,
    check_energy,
    check_info,
    check_verdict,
)

CURRENT = {
    "address": "완주군 봉동읍",
    "start_date": None,
    "end_date": None,
    "floor_area": 1000.0,
    "zeb_grade": "5등급",
    "re_ratio": None,
    "etc_cert": None,
    "guide_equip": None,
    "note": "예정공사비: 10억",
}


def _form(**overrides):
    base = {key: "" if value is None else str(value) for key, value in CURRENT.items()}
    return {**base, **overrides}


def test_check_info_accepts_the_current_values_unchanged():
    checked = check_info(_form(), CURRENT, None)
    assert checked.ok
    assert checked.values == CURRENT


def test_check_info_keeps_a_field_that_the_form_did_not_send():
    """옛 화면을 열어 둔 채 저장하거나 손으로 만든 요청이면 칸이 빠진다. 빠진 칸을 지우면 안 된다."""
    form = _form()
    del form["note"]
    assert check_info(form, CURRENT, None).values["note"] == "예정공사비: 10억"


def test_check_info_turns_a_blank_into_none():
    assert check_info(_form(address="   "), CURRENT, None).values["address"] is None


def test_check_info_rejects_a_date_that_is_not_yyyy_mm_dd():
    """date 입력을 모르는 브라우저에서는 글자 칸으로 보인다. '2026.03.01'이 들어온다."""
    for bad in ("2026.03.01", "20260301", "2026-02-30", "어제"):
        checked = check_info(_form(start_date=bad), CURRENT, None)
        assert checked.errors == {"start_date": "YYYY-MM-DD 꼴로 적으세요"}, bad


def test_check_info_rejects_an_end_before_the_start():
    checked = check_info(_form(start_date="2026-05-01", end_date="2026-04-01"), CURRENT, None)
    assert checked.errors == {"end_date": "준공일이 착공일보다 빠릅니다"}


def test_check_info_refuses_a_new_start_date_for_a_project_before_construction():
    """원 명세: 착공 전이면 확정 착공일을 기록하지 않는다. 예정 표기만 허용한다."""
    checked = check_info(_form(start_date="2026-05-01"), CURRENT, BEFORE)
    assert "비고" in checked.errors["start_date"]
    assert check_info(_form(start_date="2026-05-01"), CURRENT, BUILDING).ok


def test_check_info_keeps_an_existing_start_date_for_a_project_before_construction():
    """이미 들어 있던 착공일 때문에 다른 칸까지 못 고치면 안 된다."""
    current = {**CURRENT, "start_date": "2026-05-01"}
    form = _form(start_date="2026-05-01", address="완주군 삼례읍")
    assert check_info(form, current, BEFORE).ok


def test_check_info_reads_floor_area_with_commas():
    assert check_info(_form(floor_area="1,234.5"), CURRENT, None).values["floor_area"] == 1234.5


def test_check_info_rejects_floor_area_that_float_would_accept():
    """float()는 nan·inf·1e400을 받는다. 연면적으로는 쓸모가 없다."""
    for bad in ("0", "-3", "nan", "inf", "1e400", "천 제곱미터"):
        checked = check_info(_form(floor_area=bad), CURRENT, None)
        assert checked.errors == {"floor_area": "0보다 큰 숫자로 적으세요"}, bad


def test_check_info_limits_text_length():
    assert "address" in check_info(_form(address="가" * (TEXT_LIMIT + 1)), CURRENT, None).errors
    assert check_info(_form(note="가" * LONG_TEXT_LIMIT), CURRENT, None).ok
    assert "note" in check_info(_form(note="가" * (LONG_TEXT_LIMIT + 1)), CURRENT, None).errors


def test_check_verdict_requires_a_known_stage_and_a_reason():
    assert check_verdict({"verdict": BUILDING, "reason": "현장 확인"}).ok
    assert set(check_verdict({"verdict": "착공전", "reason": ""}).errors) == {"verdict", "reason"}


def test_check_dept_takes_a_candidate_when_nothing_is_typed():
    candidates = {7: ("체육진흥과", "부서장 홍길동 과장")}
    checked = check_dept({"pick": "7", "exec_dept": "", "snippet": ""}, candidates)
    assert checked.values == {"exec_dept": "체육진흥과", "snippet": "부서장 홍길동 과장"}


def test_check_dept_prefers_what_was_typed_over_a_candidate():
    candidates = {7: ("체육진흥과", None)}
    checked = check_dept({"pick": "7", "exec_dept": "시설과", "snippet": ""}, candidates)
    assert checked.values == {"exec_dept": "시설과", "snippet": None}


def test_check_dept_rejects_an_empty_department_and_an_unknown_candidate():
    assert "exec_dept" in check_dept({"pick": "99", "exec_dept": ""}, {}).errors
    assert "exec_dept" in check_dept({"pick": "²", "exec_dept": ""}, {7: ("과", None)}).errors


def test_check_energy_reads_lines_and_skips_blank_ones():
    checked = check_energy(["PV", "지열", ""], ["20", "1,000.5", ""])
    assert checked.values["items"] == [EnergyItem("PV", 20.0), EnergyItem("지열", 1000.5)]


def test_check_energy_allows_an_empty_plan():
    """줄을 다 비우면 계획을 지운다."""
    assert check_energy(["", ""], ["", ""]).values["items"] == []


def test_check_energy_rejects_duplicates_and_bad_capacity():
    checked = check_energy(["PV", "PV", "지열", ""], ["20", "30", "nan", "5"])
    assert checked.errors == {
        "source-1": "같은 에너지원이 두 줄입니다",
        "capacity-2": "0보다 큰 숫자로 적으세요",
        "source-3": "에너지원을 적으세요",
    }
