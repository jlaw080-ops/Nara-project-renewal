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
            json={"response": {"header": {"resultCode": "00"},
                               "body": {"pageNo": 1, "numOfRows": 500,
                                        "totalCount": 0, "items": []}}},
        )

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_backfill_walks_from_past_to_present_in_chunks(conn):
    calls = []
    with _empty_client(calls) as client:
        result = backfill(conn, client, "KEY", SETTINGS, days_back=9, chunk_days=3,
                          counters=RunCounters(), now=NOW)
    assert result.done is True
    assert [c[0][:8] for c in calls] == ["20260908", "20260911", "20260914"]


def test_backfill_saves_cursor_when_stopped_early(conn):
    calls = []
    with _empty_client(calls) as client:
        result = backfill(conn, client, "KEY", SETTINGS, days_back=9, chunk_days=3,
                          counters=RunCounters(), now=NOW, max_chunks=1)
    assert result.done is False
    assert result.cursor == "2026-09-11"
    saved = conn.execute("SELECT value FROM app_state WHERE key='backfill_cursor'").fetchone()
    assert saved["value"] == "2026-09-11"


def test_backfill_resumes_from_saved_cursor(conn):
    conn.execute("INSERT INTO app_state (key, value) VALUES ('backfill_cursor', '2026-09-14')")
    conn.commit()
    calls = []
    with _empty_client(calls) as client:
        backfill(conn, client, "KEY", SETTINGS, days_back=9, chunk_days=3,
                 counters=RunCounters(), now=NOW)
    assert [c[0][:8] for c in calls] == ["20260914"]


def test_backfill_clears_cursor_when_finished(conn):
    calls = []
    with _empty_client(calls) as client:
        backfill(conn, client, "KEY", SETTINGS, days_back=3, chunk_days=3,
                 counters=RunCounters(), now=NOW)
    assert conn.execute("SELECT value FROM app_state WHERE key='backfill_cursor'").fetchone() is None
