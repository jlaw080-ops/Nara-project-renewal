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
        # 제외어가 낱말 안에 숨어 있는 건축 공고(2026-10-01 실데이터). '제설'은 '국제설계',
        # '보도'는 '정보도서관', '거리'는 '사거리'에 들어 있어 제외어로 넣으면 이것들이 빠진다.
        "영등포구 통합 신청사 국제설계공모",
        "증산정보도서관 그린리모델링 설계 용역",
        "터미널사거리 주차타워 조성사업 실시설계 용역 (P.Q후 가격입찰)",
    ],
)
def test_title_passes_for_building_design_notices(title):
    assert title_passes(title, SETTINGS) is True


def test_title_passes_when_a_near_miss_keyword_appears():
    """제외어는 부분 문자열로만 걸린다. '숲가꾸기'는 제외어지만 '숲 체험관'은 아니다."""
    assert title_passes("OO 숲 체험관 건립 실시설계 용역", SETTINGS) is True


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
        "2026년 교통사고 잦은 곳 실시설계용역(1구역)",  # 교통사고
        "흑석 빗물펌프장 시설용량 증대 기본 및 실시설계 용역",  # 빗물펌프장
        "매봉산 오르락(樂) 엘리베이터 설치 기본 및 실시설계 용역",  # 오르락·엘리베이터
        "암사역사공원 기후대응 도시숲 조성사업 실시설계용역",  # 도시숲
        "올림픽대교 B램프 보수공사 실시설계 용역",  # 대교·램프·보수공사
        "제설 전진기지 신규 구축 실시설계 용역",  # 제설 전진기지
        "2026년 횡단보도 기본 및 실시설계 용역",  # 횡단보도
        "압구정역 4번출구 보도확장 기본 및 실시설계 용역",  # 보도확장
        "걷고 싶은 거리 조성사업(도산대로) 실시설계 용역",  # 거리 조성
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
        # 서울은 본청과 25개 구청만 — 이름이 정확히 같을 때만 관심이다.
        ("서울특별시", True),
        ("서울특별시 강남구", True),
        ("서울특별시 중구", True),
        ("서울특별시 미래한강본부", False),
        ("서울특별시 도시기반시설본부", False),
        ("대구광역시 중구", False),
        ("인천광역시 남동구", False),
    ],
)
def test_is_focus_org_matches_by_substring(org, expected):
    assert is_focus_org(org, SETTINGS) is expected
