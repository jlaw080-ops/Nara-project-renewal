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
        "남천동 주차타워 건립공사 감리용역",  # 감리
        "학교 기숙사 신축 실시설계용역",  # 기숙사
        "OO지구 지방하천 정비 실시설계",  # 지방하천
        "상수도 관망 정비 실시설계용역",  # 상수도
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
        ("경상북도 상주시", False),
        ("강원특별자치도 강릉시", False),
    ],
)
def test_is_focus_org_matches_by_substring(org, expected):
    assert is_focus_org(org, SETTINGS) is expected
