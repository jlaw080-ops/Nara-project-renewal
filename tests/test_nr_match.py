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
