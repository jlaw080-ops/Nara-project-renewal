"""설치계획서 ↔ 사업 짝 찾기."""

from pathlib import Path

import pytest

from nara.config import load_settings
from nara.db import connect, migrate
from nara.nr_match import (
    Candidate,
    Decision,
    candidates,
    canonical_org,
    decide,
    name_key,
    name_score,
    org_key,
    overlaps,
)
from nara.store import ensure_project, upsert_org

SETTINGS = load_settings(Path(__file__).resolve().parents[1] / "config.toml")
NOW = "2026-10-04T09:00:00"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("전라북도 완주군", "전북특별자치도 완주군"),
        ("강원도 강릉시", "강원특별자치도 강릉시"),
        ("제주도 서귀포시", "제주특별자치도 서귀포시"),
        ("서울특별시 서초구청", "서울특별시 서초구"),
        ("부산광역시청", "부산광역시"),
        ("  경기도   수원시 ", "경기도 수원시"),
        ("강원도교육청", "강원특별자치도교육청"),
        ("전북특별자치도 완주군", "전북특별자치도 완주군"),
    ],
)
def test_canonical_org_follows_renamed_regions_and_drops_the_office_suffix(raw, expected):
    assert canonical_org(raw) == expected


def test_canonical_org_prefers_a_configured_alias():
    aliases = {"전라북도교육청": "전북특별자치도교육청"}
    assert canonical_org("전라북도교육청", aliases) == "전북특별자치도교육청"


def test_org_key_ignores_spaces():
    assert org_key("서울특별시 서초구청") == org_key("서울특별시서초구")


@pytest.mark.parametrize(
    ("name", "org", "expected"),
    [
        ("완주군 다목적체육관 건립 설계용역", "전북특별자치도 완주군", "다목적체육관"),
        ("완주 다목적체육관", "전라북도 완주군", "다목적체육관"),
        ("[수의시담] 서초 청소년센터 신축공사 설계공모", "서울특별시 서초구", "청소년센터"),
        ("공공도서관", "", "공공도서관"),
    ],
)
def test_name_key_drops_procurement_words_and_the_town_name(name, org, expected):
    assert name_key(name, org) == expected


def test_name_score_ranks_equal_contained_and_unrelated_names():
    assert name_score("다목적체육관", "다목적체육관") == 1.0
    assert name_score("봉동다목적체육관", "다목적체육관") == 0.9
    assert name_score("다목적체육관", "공공도서관") < 0.4
    assert name_score("", "다목적체육관") == 0.0


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "m.db")
    migrate(c)
    return c


def _project(conn, org, name, address=None):
    org_id = upsert_org(conn, org, SETTINGS, NOW)
    pid = ensure_project(conn, org_id, name, "g2b", NOW)
    conn.execute("UPDATE project SET address = ? WHERE id = ?", (address, pid))
    conn.commit()
    return pid


def test_candidates_find_the_project_under_the_renamed_org(conn):
    gym = _project(conn, "전북특별자치도 완주군", "완주군 다목적체육관 건립 설계용역")
    _project(conn, "전북특별자치도 완주군", "완주군 공공도서관 건립 설계용역")
    _project(conn, "경기도 수원시", "수원 다목적체육관 설계용역")
    found = candidates(conn, "전라북도 완주군", "완주 다목적체육관", "")
    assert found[0] == Candidate(
        gym, "완주군 다목적체육관 건립 설계용역", "전북특별자치도 완주군", 1.0
    )
    assert all(c.org_name == "전북특별자치도 완주군" for c in found)


def test_a_matching_road_name_adds_to_the_score(conn):
    _project(
        conn, "서울특별시 서초구", "서초 복합문화센터 설계용역", "서울특별시 서초구 반포대로 10"
    )
    plain = candidates(conn, "서울특별시 서초구청", "서초 문화센터", "")[0].score
    road = candidates(conn, "서울특별시 서초구청", "서초 문화센터", "서초구 반포대로 12")[0].score
    assert road == pytest.approx(min(1.0, plain + 0.1))


def test_decide_links_only_a_clear_winner():
    assert decide([Candidate(1, "a", "o", 0.9), Candidate(2, "b", "o", 0.5)]) == Decision(
        "auto", 1, 0.9
    )
    assert decide([Candidate(1, "a", "o", 0.9), Candidate(2, "b", "o", 0.8)]).state == "pending"
    assert decide([Candidate(1, "a", "o", 0.6)]).state == "pending"
    assert decide([Candidate(1, "a", "o", 0.3)]) == Decision("new", None, 0.3)
    assert decide([]) == Decision("new", None, None)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("완주 하수처리사업소 청사", "하수처리사업소청사"),
        ("완주 농업기술센터 사업소 체육관", "농업기술센터사업소체육관"),
        ("완주군 도시재생 조성사업 설계용역", "도시재생조성"),
        ("완주군 청사 건립공사 설계", "청사"),
    ],
)
def test_name_key_cuts_at_business_or_construction_only_where_a_word_ends(name, expected):
    """'사업소'·'공사관'의 '사업'·'공사'에서 자르면 다른 건물이 같은 짧은 이름이 된다."""
    assert name_key(name, "전북특별자치도 완주군") == expected


@pytest.mark.parametrize(
    ("raw", "address", "expected"),
    [
        ("부산광역시기장군청", "", "부산광역시 기장군"),
        ("부산광역시남구청", "", "부산광역시 남구"),
        ("경상남도김해시", "", "경상남도 김해시"),
        ("강원도교육청", "", "강원특별자치도교육청"),
        ("강서구청", "부산광역시 강서구 에코대로 243", "부산광역시 강서구"),
        ("수원시청", "경기도 수원시 권선구 호매실로 237", "경기도 수원시"),
        ("강서구청", "서울특별시 마포구 월드컵로 1", "강서구"),
        ("중구청", "", "중구"),
        ("부산광역시", "부산광역시 해운대구 APEC로 55", "부산광역시"),
    ],
)
def test_canonical_org_fills_in_the_region_from_spacing_or_the_address(raw, address, expected):
    """설치계획서는 '강서구청'처럼 시·도를 빼고 적는다. 주소의 시·도를 붙여야 서울·부산이 갈린다."""
    assert canonical_org(raw, address=address) == expected


def test_candidates_use_the_address_to_tell_busan_from_seoul(conn):
    busan = _project(conn, "부산광역시 강서구", "강서구 통합복지관 건립 설계용역")
    _project(conn, "서울특별시 강서구", "강서구 통합복지관 건립 설계용역")
    found = candidates(conn, "강서구청", "강서구통합복지관", "부산광역시 강서구 강동송백2길 2")
    assert [c.project_id for c in found] == [busan]


def _nr(conn, org, name, address=None):
    pid = _project(conn, org, name, address)
    conn.execute("UPDATE project SET source = 'nr' WHERE id = ?", (pid,))
    conn.commit()
    return pid


def test_overlaps_pair_a_plan_only_project_with_the_same_orgs_procurement(conn):
    """설치계획서로 만든 사업이 나중에 공고로 들어온 사업과 같은 것인지 찾는다."""
    g2b = _project(conn, "부산광역시 동구", "좌천 주민활력 어울림파크 조성사업 설계용역")
    _project(conn, "부산광역시 동구", "동구 공공도서관 건립 설계용역")
    _project(conn, "부산광역시 서구", "좌천 주민활력 어울림파크 설계용역")  # 다른 기관
    nr = _nr(conn, "부산광역시 동구", "좌천 주민활력 어울림파크")
    _nr(conn, "부산광역시 동구", "좌천 주민활력 어울림파크 별관")  # 설치계획서끼리는 비교하지 않음
    found = overlaps(conn)
    assert [(o.nr_id, o.project_id) for o in found if o.nr_id == nr] == [(nr, g2b)]
    assert all(o.org_name == "부산광역시 동구" for o in found)


def test_overlaps_skip_hidden_projects_and_filter_by_region(conn):
    hidden = _project(conn, "부산광역시 동구", "좌천 어울림파크 설계용역")
    conn.execute("UPDATE project SET hidden_at = ? WHERE id = ?", (NOW, hidden))
    _project(conn, "서울특별시 서초구", "서초 복합문화센터 설계용역")
    _nr(conn, "부산광역시 동구", "좌천 어울림파크")
    seoul = _nr(conn, "서울특별시 서초구", "서초 복합문화센터")
    assert overlaps(conn, region="부산광역시") == []
    assert [o.nr_id for o in overlaps(conn)] == [seoul]
    assert overlaps(conn, min_score=1.01) == []
