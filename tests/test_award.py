from pathlib import Path

import httpx
import pytest

from nara.award import pending_award_bid_nos, update_awards
from nara.config import load_settings
from nara.db import connect, migrate
from nara.g2b.award_api import fetch_award
from nara.g2b.list_api import NoticeItem
from nara.runlog import RunCounters
from nara.store import ensure_project, upsert_notice, upsert_org

SETTINGS = load_settings(Path(__file__).resolve().parents[1] / "config.toml")
NOW = "2026-09-17T09:00:00"
TODAY = "2026-09-17"


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "test.db")
    migrate(c)
    return c


def _add_notice(conn, bid_no, org, open_date):
    org_id = upsert_org(conn, org, SETTINGS, NOW)
    project_id = ensure_project(conn, org_id, f"{bid_no} 사업", "g2b", NOW)
    item = NoticeItem(
        bid_no=bid_no, bid_ord="0", org_name=org, title=f"{bid_no} 사업",
        service_div="기술용역", kind="등록공고",
        notice_date="2026-09-01", open_date=open_date, close_date="2026-09-09",
        url="", budget_krw=None, budget_basis="", officer_name="", officer_tel="",
        raw={},
    )
    upsert_notice(conn, item, org_id, project_id, NOW)


def _award_payload(winner: str | None):
    items = [] if winner is None else [{"bidwinnrNm": winner, "rgstDt": "2026-09-12 10:00:00"}]
    return {"response": {"header": {"resultCode": "00"},
                         "body": {"pageNo": 1, "numOfRows": 10,
                                  "totalCount": len(items), "items": items}}}


def _client(winner: str | None):
    payload = _award_payload(winner)
    return httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload)))


def test_fetch_award_returns_winner():
    with _client("주식회사 길종합건축사사무소") as client:
        award = fetch_award(client, "KEY", "R1")
    assert award is not None
    assert award.winner == "주식회사 길종합건축사사무소"
    assert award.award_date == "2026-09-12"


def test_fetch_award_returns_none_when_no_result():
    with _client(None) as client:
        assert fetch_award(client, "KEY", "R1") is None


def test_fetch_award_picks_most_recent_entry():
    payload = {"response": {"header": {"resultCode": "00"}, "body": {"items": [
        {"bidwinnrNm": "가건축", "rgstDt": "2026-09-10 10:00:00"},
        {"bidwinnrNm": "나건축", "rgstDt": "2026-09-14 10:00:00"},
    ]}}}
    with httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload))
    ) as client:
        award = fetch_award(client, "KEY", "R1")
    assert award.winner == "나건축"


def test_pending_skips_notices_whose_opening_is_in_the_future(conn):
    _add_notice(conn, "R1", "전북특별자치도 완주군", open_date="2026-09-10")
    _add_notice(conn, "R2", "전북특별자치도 완주군", open_date="2026-12-01")
    assert pending_award_bid_nos(conn, TODAY, None, None, 100) == ["R1"]


def test_pending_filters_by_tier(conn):
    _add_notice(conn, "R1", "전북특별자치도 완주군", open_date="2026-09-10")
    _add_notice(conn, "R2", "충청북도 제천시", open_date="2026-09-10")
    assert pending_award_bid_nos(conn, TODAY, "focus", None, 100) == ["R1"]


def test_pending_filters_by_weekday_group(conn):
    _add_notice(conn, "R1", "충청북도 제천시", open_date="2026-09-10")
    group = conn.execute("SELECT weekday_group FROM org WHERE name='충청북도 제천시'").fetchone()[0]
    assert pending_award_bid_nos(conn, TODAY, "rest", group, 100) == ["R1"]
    other = group % 5 + 1
    assert pending_award_bid_nos(conn, TODAY, "rest", other, 100) == []


def test_pending_excludes_already_recorded_award(conn):
    _add_notice(conn, "R1", "전북특별자치도 완주군", open_date="2026-09-10")
    conn.execute(
        "INSERT INTO award (bid_no, winner, award_date, checked_at) VALUES (?, ?, ?, ?)",
        ("R1", "가건축", "2026-09-12", NOW),
    )
    conn.commit()
    assert pending_award_bid_nos(conn, TODAY, None, None, 100) == []


def test_update_awards_saves_winner(conn):
    _add_notice(conn, "R1", "전북특별자치도 완주군", open_date="2026-09-10")
    counters = RunCounters()
    with _client("가건축") as client:
        updated = update_awards(conn, client, "KEY", TODAY, None, None, 100, counters)
    assert updated == 1
    row = conn.execute("SELECT winner FROM award WHERE bid_no='R1'").fetchone()
    assert row["winner"] == "가건축"


def test_update_awards_leaves_row_absent_when_not_yet_awarded(conn):
    _add_notice(conn, "R1", "전북특별자치도 완주군", open_date="2026-09-10")
    with _client(None) as client:
        updated = update_awards(conn, client, "KEY", TODAY, None, None, 100, RunCounters())
    assert updated == 0
    assert conn.execute("SELECT COUNT(*) FROM award").fetchone()[0] == 0
