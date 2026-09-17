import json
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from nara.cli import app
from nara.collect import collect_range
from nara.config import Secrets, load_settings
from nara.db import connect, migrate
from nara.runlog import RunCounters

SETTINGS = load_settings(Path(__file__).resolve().parents[1] / "config.toml")
BEGIN = datetime(2026, 9, 1)
END = datetime(2026, 9, 4)


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "test.db")
    migrate(c)
    return c


def _payload(items):
    return {
        "response": {
            "header": {"resultCode": "00"},
            "body": {"pageNo": 1, "numOfRows": 500, "totalCount": len(items), "items": items},
        }
    }


def _raw(bid_no, org, title, div="기술용역", kind="등록공고"):
    return {
        "bidNtceNo": bid_no,
        "bidNtceOrd": "0",
        "dminsttNm": org,
        "bidNtceNm": title,
        "srvceDivNm": div,
        "ntceKindNm": kind,
        "bidNtceDt": "20260901",
        "opengDt": "20260910",
        "bidClseDt": "20260909",
    }


def _client(items):
    payload = _payload(items)
    return httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload)))


def test_collect_range_stores_passing_notices(conn):
    items = [
        _raw("A1", "전북특별자치도 완주군", "완주 체육관 건립 실시설계용역"),
        _raw("A2", "충청북도 제천시", "제천 도서관 건축설계공모"),
    ]
    with _client(items) as client:
        added = collect_range(conn, client, "KEY", SETTINGS, BEGIN, END, RunCounters())
    assert added == 2
    assert conn.execute("SELECT COUNT(*) FROM notice").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM project").fetchone()[0] == 2


def test_collect_range_drops_non_technical_service(conn):
    items = [_raw("A1", "전북특별자치도 완주군", "완주 체육관 실시설계용역", div="일반용역")]
    with _client(items) as client:
        added = collect_range(conn, client, "KEY", SETTINGS, BEGIN, END, RunCounters())
    assert added == 0


def test_collect_range_drops_cancelled_notice(conn):
    items = [_raw("A1", "전북특별자치도 완주군", "완주 체육관 실시설계용역", kind="취소공고")]
    with _client(items) as client:
        added = collect_range(conn, client, "KEY", SETTINGS, BEGIN, END, RunCounters())
    assert added == 0


def test_collect_range_drops_excluded_title(conn):
    items = [_raw("A1", "전북특별자치도 완주군", "완주 상수도 관망 실시설계용역")]
    with _client(items) as client:
        added = collect_range(conn, client, "KEY", SETTINGS, BEGIN, END, RunCounters())
    assert added == 0


def test_collect_range_drops_excluded_org(conn):
    items = [_raw("A1", "전북특별자치도교육청", "OO학교 증축 실시설계용역")]
    with _client(items) as client:
        added = collect_range(conn, client, "KEY", SETTINGS, BEGIN, END, RunCounters())
    assert added == 0


def test_collect_range_registers_org_tier(conn):
    items = [
        _raw("A1", "전북특별자치도 완주군", "완주 체육관 실시설계용역"),
        _raw("A2", "강원특별자치도 강릉시", "강릉 도서관 건축설계공모"),
    ]
    with _client(items) as client:
        collect_range(conn, client, "KEY", SETTINGS, BEGIN, END, RunCounters())
    tiers = dict(conn.execute("SELECT name, tier FROM org"))
    assert tiers["전북특별자치도 완주군"] == "focus"
    assert tiers["강원특별자치도 강릉시"] == "rest"


def test_collect_range_is_idempotent(conn):
    items = [_raw("A1", "전북특별자치도 완주군", "완주 체육관 실시설계용역")]
    with _client(items) as client:
        first = collect_range(conn, client, "KEY", SETTINGS, BEGIN, END, RunCounters())
        second = collect_range(conn, client, "KEY", SETTINGS, BEGIN, END, RunCounters())
    assert (first, second) == (1, 0)
    assert conn.execute("SELECT COUNT(*) FROM notice").fetchone()[0] == 1


def test_collect_range_counts_processed(conn):
    items = [
        _raw("A1", "전북특별자치도 완주군", "완주 체육관 실시설계용역"),
        _raw("A2", "전북특별자치도교육청", "OO학교 증축 실시설계용역"),
    ]
    counters = RunCounters()
    with _client(items) as client:
        collect_range(conn, client, "KEY", SETTINGS, BEGIN, END, counters)
    assert counters.processed == 2
    assert counters.updated == 1


def test_collect_range_keeps_raw_json(conn):
    items = [_raw("A1", "전북특별자치도 완주군", "완주 체육관 실시설계용역")]
    with _client(items) as client:
        collect_range(conn, client, "KEY", SETTINGS, BEGIN, END, RunCounters())
    raw = json.loads(conn.execute("SELECT raw_json FROM notice").fetchone()[0])
    assert raw["srvceDivNm"] == "기술용역"


def test_collect_command_rejects_non_positive_days(monkeypatch):
    # 이 환경엔 .env가 없어 API 키 부재로도 0이 아닌 종료 코드가 나올 수 있다.
    # --days 검증만 따로 확인하기 위해 키가 있는 것처럼 만들고, 실제로 수집이
    # 시작되면(=검증이 없으면) 어디서 멈추는지 calls로 잡아낸다.
    import nara.cli as cli

    calls: list[str] = []
    monkeypatch.setattr(cli, "load_secrets", lambda path: Secrets("KEY", None, None, None))
    monkeypatch.setattr(cli, "_open_db", lambda db: calls.append("open_db") or object())

    @contextmanager
    def fake_run_log(conn, command, args=""):
        calls.append("run_log")
        yield RunCounters()

    monkeypatch.setattr(cli, "run_log", fake_run_log)
    monkeypatch.setattr(cli, "collect_range", lambda *a, **k: calls.append("collect_range") or 0)

    result = CliRunner().invoke(app, ["collect", "--days", "0"])

    assert result.exit_code != 0
    assert calls == []
