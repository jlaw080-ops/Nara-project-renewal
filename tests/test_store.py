import json
from pathlib import Path

import pytest

from nara.config import load_settings
from nara.db import connect, migrate
from nara.g2b.list_api import NoticeItem
from nara.runlog import run_log
from nara.store import ensure_project, last_run, upsert_notice, upsert_org

SETTINGS = load_settings(Path(__file__).resolve().parents[1] / "config.toml")
NOW = "2026-09-17T09:00:00"


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "test.db")
    migrate(c)
    return c


def _item(bid_no="R1", org="전북특별자치도 완주군", title="완주 체육관 실시설계용역") -> NoticeItem:
    return NoticeItem(
        bid_no=bid_no,
        bid_ord="0",
        org_name=org,
        title=title,
        service_div="기술용역",
        kind="등록공고",
        notice_date="2026-09-01",
        open_date="2026-09-10",
        close_date="2026-09-09",
        url="https://example.test/1",
        budget_krw=100_000_000,
        budget_basis="추정가격",
        officer_name="",
        officer_tel="",
        raw={"bidNtceNo": bid_no},
    )


def test_upsert_org_marks_focus_agency(conn):
    org_id = upsert_org(conn, "전북특별자치도 완주군", SETTINGS, NOW)
    row = conn.execute("SELECT tier, weekday_group FROM org WHERE id = ?", (org_id,)).fetchone()
    assert row["tier"] == "focus"
    assert row["weekday_group"] is None


def test_upsert_org_assigns_weekday_group_to_rest_agency(conn):
    org_id = upsert_org(conn, "강원특별자치도 강릉시", SETTINGS, NOW)
    row = conn.execute("SELECT tier, weekday_group FROM org WHERE id = ?", (org_id,)).fetchone()
    assert row["tier"] == "rest"
    assert row["weekday_group"] in {1, 2, 3, 4, 5}


def test_upsert_org_is_idempotent(conn):
    first = upsert_org(conn, "충청북도 제천시", SETTINGS, NOW)
    second = upsert_org(conn, "충청북도 제천시", SETTINGS, NOW)
    assert first == second
    assert conn.execute("SELECT COUNT(*) FROM org").fetchone()[0] == 1


def test_upsert_notice_creates_row_and_reports_new(conn):
    org_id = upsert_org(conn, "전북특별자치도 완주군", SETTINGS, NOW)
    project_id = ensure_project(conn, org_id, "완주 체육관 실시설계용역", "g2b", NOW)
    assert upsert_notice(conn, _item(), org_id, project_id, NOW) is True
    row = conn.execute("SELECT * FROM notice WHERE bid_no = 'R1'").fetchone()
    assert row["title"] == "완주 체육관 실시설계용역"
    assert json.loads(row["raw_json"])["bidNtceNo"] == "R1"


def test_upsert_notice_links_the_org(conn):
    """낙찰 대상 고르기가 org.tier로 걸러지므로 org_id가 반드시 박혀야 한다."""
    org_id = upsert_org(conn, "전북특별자치도 완주군", SETTINGS, NOW)
    project_id = ensure_project(conn, org_id, "완주 체육관 실시설계용역", "g2b", NOW)
    upsert_notice(conn, _item(), org_id, project_id, NOW)
    row = conn.execute("SELECT org_id FROM notice WHERE bid_no = 'R1'").fetchone()
    assert row["org_id"] == org_id


def test_upsert_notice_second_time_reports_not_new(conn):
    org_id = upsert_org(conn, "전북특별자치도 완주군", SETTINGS, NOW)
    project_id = ensure_project(conn, org_id, "완주 체육관 실시설계용역", "g2b", NOW)
    upsert_notice(conn, _item(), org_id, project_id, NOW)
    assert upsert_notice(conn, _item(), org_id, project_id, NOW) is False
    assert conn.execute("SELECT COUNT(*) FROM notice").fetchone()[0] == 1


def test_upsert_notice_does_not_reassign_existing_project(conn):
    org_id = upsert_org(conn, "전북특별자치도 완주군", SETTINGS, NOW)
    first = ensure_project(conn, org_id, "완주 체육관 실시설계용역", "g2b", NOW)
    upsert_notice(conn, _item(), org_id, first, NOW)
    other = ensure_project(conn, org_id, "다른 사업", "g2b", NOW)
    upsert_notice(conn, _item(), org_id, other, NOW)
    row = conn.execute("SELECT project_id FROM notice WHERE bid_no = 'R1'").fetchone()
    assert row["project_id"] == first


def test_run_log_records_success(conn):
    with run_log(conn, "collect", "--days 3") as counters:
        counters.processed = 10
        counters.updated = 4
    row = last_run(conn, "collect")
    assert row["status"] == "ok"
    assert row["processed"] == 10
    assert row["updated"] == 4
    assert row["finished_at"] is not None


def test_run_log_records_error_and_reraises(conn):
    with pytest.raises(ValueError):
        with run_log(conn, "collect", "") as counters:
            counters.processed = 2
            raise ValueError("boom")
    row = last_run(conn, "collect")
    assert row["status"] == "error"
    assert "boom" in row["message"]
    assert row["processed"] == 2
