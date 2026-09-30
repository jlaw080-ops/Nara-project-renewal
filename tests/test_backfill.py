from datetime import datetime
from pathlib import Path

import httpx
import pytest

from nara.collect import backfill
from nara.config import load_settings
from nara.db import connect, migrate
from nara.runlog import RunCounters

SETTINGS = load_settings(Path(__file__).resolve().parents[1] / "config.toml")
NOW = datetime(2026, 9, 17, 12, 0)


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "test.db")
    migrate(c)
    return c


def _empty_client(calls: list):
    def handler(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        calls.append((params["inqryBgnDt"], params["inqryEndDt"]))
        return httpx.Response(
            200,
            json={
                "response": {
                    "header": {"resultCode": "00"},
                    "body": {"pageNo": 1, "numOfRows": 500, "totalCount": 0, "items": []},
                }
            },
        )

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_backfill_walks_from_past_to_present_in_chunks(conn):
    calls = []
    with _empty_client(calls) as client:
        result = backfill(
            conn,
            client,
            "KEY",
            SETTINGS,
            days_back=9,
            chunk_days=3,
            counters=RunCounters(),
            now=NOW,
        )
    assert result.done is True
    assert [c[0][:8] for c in calls] == ["20260908", "20260911", "20260914"]


def test_backfill_saves_cursor_when_stopped_early(conn):
    calls = []
    with _empty_client(calls) as client:
        result = backfill(
            conn,
            client,
            "KEY",
            SETTINGS,
            days_back=9,
            chunk_days=3,
            counters=RunCounters(),
            now=NOW,
            max_chunks=1,
        )
    assert result.done is False
    assert result.cursor == "2026-09-11"
    saved = conn.execute("SELECT value FROM app_state WHERE key='backfill_cursor'").fetchone()
    assert saved["value"] == "2026-09-11"


def test_backfill_resumes_from_saved_cursor(conn):
    conn.execute("INSERT INTO app_state (key, value) VALUES ('backfill_cursor', '2026-09-14')")
    conn.commit()
    calls = []
    with _empty_client(calls) as client:
        backfill(
            conn,
            client,
            "KEY",
            SETTINGS,
            days_back=9,
            chunk_days=3,
            counters=RunCounters(),
            now=NOW,
        )
    assert [c[0][:8] for c in calls] == ["20260914"]


def test_backfill_clears_cursor_when_finished(conn):
    calls = []
    with _empty_client(calls) as client:
        backfill(
            conn,
            client,
            "KEY",
            SETTINGS,
            days_back=3,
            chunk_days=3,
            counters=RunCounters(),
            now=NOW,
        )
    row = conn.execute("SELECT value FROM app_state WHERE key='backfill_cursor'").fetchone()
    assert row is None


def test_backfill_rejects_non_positive_chunk_days(conn):
    calls = []
    with _empty_client(calls) as client:
        with pytest.raises(ValueError):
            backfill(
                conn,
                client,
                "KEY",
                SETTINGS,
                days_back=9,
                chunk_days=0,
                counters=RunCounters(),
                now=NOW,
            )
    assert calls == []


def test_backfill_rejects_non_positive_days_back(conn):
    calls = []
    with _empty_client(calls) as client:
        with pytest.raises(ValueError):
            backfill(
                conn,
                client,
                "KEY",
                SETTINGS,
                days_back=0,
                chunk_days=3,
                counters=RunCounters(),
                now=NOW,
            )
    assert calls == []


def _seoul_client(calls: list):
    """수요기관명으로 거른 응답. 본청·구청·본부가 섞여 온다."""

    def raw(bid_no, org, title):
        return {
            "bidNtceNo": bid_no,
            "bidNtceOrd": "000",
            "dminsttNm": org,
            "bidNtceNm": title,
            "srvceDivNm": "기술용역",
            "ntceKindNm": "등록공고",
            "bidNtceDt": "20260901",
            "opengDt": "20260910",
            "bidClseDt": "20260909",
        }

    items = [
        raw("S1", "서울특별시", "서울 시민센터 건립 설계공모"),
        raw("S2", "서울특별시 강남구", "강남구 복합청사 건립 실시설계용역"),
        raw("S3", "서울특별시 미래한강본부", "한강 전망대 건립 설계공모"),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.params.get("dminsttNm"))
        body = {"pageNo": 1, "numOfRows": 500, "totalCount": len(items), "items": items}
        return httpx.Response(
            200, json={"response": {"header": {"resultCode": "00"}, "body": body}}
        )

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_an_org_backfill_asks_for_that_agency_and_keeps_only_focus_orgs(conn):
    """서울 소급은 서울로 걸러 묻고, 본청·구청(관심기관)만 넣는다 — 본부는 넣지 않는다."""
    calls = []
    with _seoul_client(calls) as client:
        backfill(
            conn,
            client,
            "KEY",
            SETTINGS,
            days_back=30,
            chunk_days=30,
            counters=RunCounters(),
            now=NOW,
            org="서울특별시",
        )
    assert calls and set(calls) == {"서울특별시"}
    stored = {row[0] for row in conn.execute("SELECT org_name FROM notice")}
    assert stored == {"서울특별시", "서울특별시 강남구"}


def test_an_org_backfill_keeps_its_own_cursor(conn):
    """기관별 소급이 중간에 멈춰도 전체 소급의 이어하기 위치를 건드리지 않는다."""
    conn.execute("INSERT INTO app_state (key, value) VALUES ('backfill_cursor', '2026-01-01')")
    conn.commit()
    with _seoul_client([]) as client:
        result = backfill(
            conn,
            client,
            "KEY",
            SETTINGS,
            days_back=90,
            chunk_days=30,
            counters=RunCounters(),
            now=NOW,
            max_chunks=1,
            org="서울특별시",
        )
    assert result.done is False
    state = dict(conn.execute("SELECT key, value FROM app_state").fetchall())
    assert state["backfill_cursor"] == "2026-01-01"
    assert state["backfill_cursor:서울특별시"] == result.cursor


def test_backfill_command_passes_the_agency_and_logs_it(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from nara import cli
    from nara.collect import BackfillResult
    from nara.config import Secrets

    seen = {}

    def fake(conn, client, api_key, settings, days, chunk, counters, org=None):
        seen.update(days=days, chunk=chunk, org=org)
        return BackfillResult(0, "2026-10-01", done=True)

    monkeypatch.setattr(cli, "run_backfill", fake)
    monkeypatch.setattr(
        cli,
        "load_secrets",
        lambda path: Secrets(
            g2b_api_key="K", naver_client_id=None, naver_client_secret=None, anthropic_api_key=None
        ),
    )
    db = tmp_path / "n.db"
    args = ["backfill", "--days", "730", "--chunk", "30", "--org", "서울특별시", "--db", str(db)]
    result = CliRunner().invoke(cli.app, args)
    assert result.exit_code == 0, result.output
    assert seen == {"days": 730, "chunk": 30, "org": "서울특별시"}
    logged = connect(db).execute("SELECT args FROM run_log WHERE command = 'backfill'").fetchone()
    assert "--org 서울특별시" in logged[0]
