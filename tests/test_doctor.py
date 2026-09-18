from pathlib import Path

import pytest
from typer.testing import CliRunner

from nara.cli import app
from nara.config import load_settings
from nara.db import connect, migrate
from nara.doctor import AWARD_BATCH_LIMIT, run_checks
from nara.store import ensure_project, upsert_org
from nara.verdict import BEFORE, BUILDING, DONE

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
    # org_id를 채워야 낙찰 조회 적체 점검(요일그룹별 partition)이 이 공고를 잡는다.
    # 이전에는 빠져 있었는데, org_id가 NULL인 공고는 새 "기관 연결 없는 공고" 점검
    # 대상이지 여기서 만들려는 정상 공고가 아니다.
    conn.execute(
        "INSERT INTO notice (bid_no, project_id, org_id, org_name, title, open_date, collected_at) "
        "VALUES (?, ?, ?, '전북특별자치도 완주군', ?, ?, ?)",
        (bid_no, project_id, org_id, f"{bid_no} 사업", open_date, NOW),
    )
    conn.commit()
    return project_id


def _project(conn, org_name, project_name):
    org_id = upsert_org(conn, org_name, SETTINGS, NOW)
    return ensure_project(conn, org_id, project_name, "g2b", NOW)


def _status(conn, project_id, verdict, evidence_json=None, when="2026-09-18T09:00:00"):
    conn.execute(
        "INSERT INTO status_check (project_id, verdict, decided_by, evidence_json, checked_at) "
        "VALUES (?, ?, 'rule', ?, ?)",
        (project_id, verdict, evidence_json, when),
    )
    conn.commit()


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
        "VALUES ('강원특별자치도 강릉시', 'rest', NULL, ?)",
        (NOW,),
    )
    conn.commit()
    findings = run_checks(conn, TODAY)
    assert any(f.check == "요일 그룹 없는 비관심 기관" for f in findings)


def test_run_checks_is_quiet_when_backlog_is_spread_across_weekday_groups(conn):
    """관심 기관은 하루 2회, 비관심 기관은 요일그룹별 주 1회만 돈다(스펙 스케줄).
    전체 합계는 상한을 넘어도 실제로 도는 단위(요일그룹)별로 상한 밑이면 정상이다."""
    for group in range(1, 6):
        cur = conn.execute(
            "INSERT INTO org (name, tier, weekday_group, added_at) VALUES (?, 'rest', ?, ?)",
            (f"비관심기관{group}", group, NOW),
        )
        org_id = cur.lastrowid
        for i in range(100):
            bid_no = f"G{group}-{i}"
            project_id = ensure_project(conn, org_id, f"{bid_no} 사업", "g2b", NOW)
            conn.execute(
                "INSERT INTO notice (bid_no, project_id, org_id, org_name, title, open_date, "
                "collected_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    bid_no,
                    project_id,
                    org_id,
                    f"비관심기관{group}",
                    f"{bid_no} 사업",
                    "2026-09-10",
                    NOW,
                ),
            )
    conn.commit()
    assert not any(f.check == "낙찰 조회 적체" for f in run_checks(conn, TODAY))


def test_run_checks_flags_notice_without_org(conn):
    """org_id가 없는 공고는 낙찰 대기 partition 쿼리(org JOIN)에 영영 안 잡히므로
    따로 걸러야 한다."""
    conn.execute(
        "INSERT INTO notice (bid_no, org_name, title, open_date, collected_at) "
        "VALUES ('ORPHAN1', '알수없음', 'ORPHAN1 사업', '2026-09-10', ?)",
        (NOW,),
    )
    conn.commit()
    hits = [f for f in run_checks(conn, TODAY) if f.check == "기관 연결 없는 공고"]
    assert len(hits) == 1
    assert "ORPHAN1" in hits[0].detail


def test_doctor_command_refuses_to_create_missing_db(tmp_path):
    """--db에 없는 경로를 주면 빈 DB를 만들지 않고 실패해야 한다."""
    missing = tmp_path / "does-not-exist" / "nara.db"
    result = CliRunner().invoke(app, ["doctor", "--db", str(missing)])
    assert result.exit_code != 0
    assert not missing.exists()


def test_doctor_flags_before_construction_with_a_confirmed_start_date(conn):
    """'착공 전'인데 확정 착공일이 있으면 둘 중 하나가 틀렸다."""
    project_id = _project(conn, "전북특별자치도 완주군", "사업")
    conn.execute("UPDATE project SET start_date = '2025-11-03' WHERE id = ?", (project_id,))
    conn.commit()
    _status(conn, project_id, BEFORE)

    checks = [f.check for f in run_checks(conn, "2026-09-18")]

    assert "판정과 착공일 모순" in checks


def test_doctor_is_quiet_when_the_start_date_is_still_ahead(conn):
    """착공 예정일이 미래면 '착공 전'과 어긋나지 않는다 — 헛경보를 내지 않는다."""
    project_id = _project(conn, "전북특별자치도 완주군", "사업")
    conn.execute("UPDATE project SET start_date = '2027-03-01' WHERE id = ?", (project_id,))
    conn.commit()
    _status(conn, project_id, BEFORE)

    checks = [f.check for f in run_checks(conn, "2026-09-18")]

    assert "판정과 착공일 모순" not in checks


def test_doctor_flags_a_strong_verdict_without_evidence(conn):
    project_id = _project(conn, "전북특별자치도 완주군", "사업")
    _status(conn, project_id, DONE, evidence_json=None)

    checks = [f.check for f in run_checks(conn, "2026-09-18")]

    assert "근거 없는 강한 판정" in checks


def test_doctor_accepts_a_strong_verdict_with_an_evidence_url(conn):
    project_id = _project(conn, "전북특별자치도 완주군", "사업")
    _status(conn, project_id, BUILDING, evidence_json='{"url": "https://news.example.com/1"}')

    checks = [f.check for f in run_checks(conn, "2026-09-18")]

    assert "근거 없는 강한 판정" not in checks


def test_doctor_only_looks_at_the_latest_verdict(conn):
    """뒤집힌 옛 판정까지 잡으면 이력을 쌓을수록 경보가 늘어난다."""
    project_id = _project(conn, "전북특별자치도 완주군", "사업")
    _status(conn, project_id, DONE, when="2026-09-01T09:00:00")
    _status(conn, project_id, BEFORE, when="2026-09-18T09:00:00")

    checks = [f.check for f in run_checks(conn, "2026-09-18")]

    assert "근거 없는 강한 판정" not in checks
