from pathlib import Path

import pytest

from nara.config import load_settings
from nara.db import connect, migrate
from nara.doctor import AWARD_BATCH_LIMIT, run_checks
from nara.store import ensure_project, upsert_org

SETTINGS = load_settings(Path(__file__).resolve().parents[1] / "config.toml")
NOW = "2026-09-17T09:00:00"
TODAY = "2026-09-17"


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "test.db")
    migrate(c)
    return c


def _notice(conn, bid_no, open_date):
    org_id = upsert_org(conn, "전북특별자치도 완주군", SETTINGS, NOW)
    project_id = ensure_project(conn, org_id, f"{bid_no} 사업", "g2b", NOW)
    conn.execute(
        "INSERT INTO notice (bid_no, project_id, org_name, title, open_date, collected_at) "
        "VALUES (?, ?, '전북특별자치도 완주군', ?, ?, ?)",
        (bid_no, project_id, f"{bid_no} 사업", open_date, NOW),
    )
    conn.commit()
    return project_id


def test_run_checks_is_quiet_on_clean_database(conn):
    _notice(conn, "R1", "2026-09-10")
    assert run_checks(conn, TODAY) == []


def test_run_checks_flags_award_recorded_before_opening(conn):
    _notice(conn, "R1", "2026-12-01")
    conn.execute(
        "INSERT INTO award (bid_no, winner, checked_at) VALUES ('R1', '가건축', ?)", (NOW,)
    )
    conn.commit()
    findings = run_checks(conn, TODAY)
    assert any(f.check == "개찰 전 낙찰" and "R1" in f.detail for f in findings)


def test_run_checks_flags_orphan_project(conn):
    org_id = upsert_org(conn, "전북특별자치도 완주군", SETTINGS, NOW)
    ensure_project(conn, org_id, "공고도 수기 표시도 없는 사업", "g2b", NOW)
    findings = run_checks(conn, TODAY)
    assert any(f.check == "공고 없는 g2b 사업" for f in findings)


def test_run_checks_is_quiet_when_award_backlog_fits_one_batch(conn):
    _notice(conn, "R1", "2026-09-10")
    assert not any(f.check == "낙찰 조회 적체" for f in run_checks(conn, TODAY))


def test_run_checks_flags_award_backlog_larger_than_one_batch(conn):
    """낙찰이 영영 안 나는 건이 쌓이면 최근 공고가 매 회차 뒤로 밀린다."""
    for i in range(AWARD_BATCH_LIMIT + 1):
        _notice(conn, f"R{i}", "2026-09-10")
    hit = [f for f in run_checks(conn, TODAY) if f.check == "낙찰 조회 적체"]
    assert len(hit) == 1
    assert str(AWARD_BATCH_LIMIT + 1) in hit[0].detail


def test_award_backlog_ignores_notices_already_awarded(conn):
    """낙찰이 채워진 건은 적체가 아니다."""
    for i in range(AWARD_BATCH_LIMIT + 1):
        _notice(conn, f"R{i}", "2026-09-10")
        conn.execute(
            "INSERT INTO award (bid_no, winner, checked_at) VALUES (?, '가건축', ?)",
            (f"R{i}", NOW),
        )
    conn.commit()
    assert not any(f.check == "낙찰 조회 적체" for f in run_checks(conn, TODAY))


def test_run_checks_flags_rest_org_without_weekday_group(conn):
    conn.execute(
        "INSERT INTO org (name, tier, weekday_group, added_at) "
        "VALUES ('충청북도 제천시', 'rest', NULL, ?)", (NOW,)
    )
    conn.commit()
    findings = run_checks(conn, TODAY)
    assert any(f.check == "요일 그룹 없는 비관심 기관" for f in findings)
