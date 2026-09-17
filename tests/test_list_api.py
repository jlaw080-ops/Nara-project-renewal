import json
from datetime import datetime
from pathlib import Path

import httpx
import pytest

from nara.g2b.common import G2BError
from nara.g2b.list_api import fetch_notice_page, iter_notices

FIXTURES = Path(__file__).parent / "fixtures"
PAGE1 = json.loads((FIXTURES / "list_page1.json").read_text(encoding="utf-8"))
BEGIN = datetime(2026, 3, 1, 0, 0)
END = datetime(2026, 3, 4, 0, 0)


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_fetch_notice_page_parses_items_and_total():
    with _client(lambda req: httpx.Response(200, json=PAGE1)) as client:
        items, total = fetch_notice_page(client, "KEY", BEGIN, END, page=1, rows=2)
    assert total == 3
    assert [i.bid_no for i in items] == ["R26BK01418098", "R26BK01462347"]


def test_fetch_notice_page_normalises_dates():
    with _client(lambda req: httpx.Response(200, json=PAGE1)) as client:
        items, _ = fetch_notice_page(client, "KEY", BEGIN, END, page=1, rows=2)
    assert items[0].notice_date == "2026-03-24"
    assert items[0].open_date == "2026-05-08"
    assert items[1].close_date == ""


def test_fetch_notice_page_prefers_estimated_price():
    with _client(lambda req: httpx.Response(200, json=PAGE1)) as client:
        items, _ = fetch_notice_page(client, "KEY", BEGIN, END, page=1, rows=2)
    assert items[0].budget_krw == 804280909
    assert items[0].budget_basis == "추정가격"
    assert items[1].budget_krw is None
    assert items[1].budget_basis == ""


def test_fetch_notice_page_builds_url_when_api_omits_it():
    with _client(lambda req: httpx.Response(200, json=PAGE1)) as client:
        items, _ = fetch_notice_page(client, "KEY", BEGIN, END, page=1, rows=2)
    assert items[1].url == (
        "https://www.g2b.go.kr/link/PNPE027_01/single/?bidPbancNo=R26BK01462347&bidPbancOrd=000"
    )


def test_fetch_notice_page_keeps_raw_payload():
    with _client(lambda req: httpx.Response(200, json=PAGE1)) as client:
        items, _ = fetch_notice_page(client, "KEY", BEGIN, END, page=1, rows=2)
    assert items[0].raw["srvceDivNm"] == "기술용역"


def test_fetch_notice_page_raises_on_xml_error_body():
    xml = (
        "<OpenAPI_ServiceResponse><cmmMsgHeader>"
        "<returnAuthMsg>SERVICE_KEY_IS_NOT_REGISTERED_ERROR</returnAuthMsg>"
        "<returnReasonCode>30</returnReasonCode>"
        "</cmmMsgHeader></OpenAPI_ServiceResponse>"
    )
    with _client(lambda req: httpx.Response(200, text=xml)) as client:
        with pytest.raises(G2BError, match="SERVICE_KEY_IS_NOT_REGISTERED_ERROR"):
            fetch_notice_page(client, "KEY", BEGIN, END, page=1, rows=2)


def test_fetch_notice_page_raises_on_bad_result_code():
    bad = {
        "response": {
            "header": {"resultCode": "22", "resultMsg": "LIMITED NUMBER OF SERVICE REQUESTS"}
        }
    }
    with _client(lambda req: httpx.Response(200, json=bad)) as client:
        with pytest.raises(G2BError, match="22"):
            fetch_notice_page(client, "KEY", BEGIN, END, page=1, rows=2)


def test_fetch_notice_page_raises_on_missing_response_envelope():
    with _client(lambda req: httpx.Response(200, json={})) as client:
        with pytest.raises(G2BError):
            fetch_notice_page(client, "KEY", BEGIN, END, page=1, rows=2)


def test_fetch_notice_page_raises_on_missing_header():
    bad = {"response": {"body": {"items": []}}}
    with _client(lambda req: httpx.Response(200, json=bad)) as client:
        with pytest.raises(G2BError):
            fetch_notice_page(client, "KEY", BEGIN, END, page=1, rows=2)


def test_iter_notices_stops_when_total_reached():
    page2 = json.loads(json.dumps(PAGE1))
    page2["response"]["body"]["pageNo"] = 2
    page2["response"]["body"]["items"] = [PAGE1["response"]["body"]["items"][0]]
    pages = {1: PAGE1, 2: page2}
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(dict(request.url.params)["pageNo"])
        seen.append(page)
        return httpx.Response(200, json=pages[page])

    with _client(handler) as client:
        items = list(iter_notices(client, "KEY", BEGIN, END, rows=2))
    assert len(items) == 3
    assert seen == [1, 2]


def test_iter_notices_honours_max_pages():
    """total이 max_pages*rows보다 커서 매 페이지가 total-도달 분기를 타지 않을 때,
    max_pages 소진 자체가 G2BError를 올려야 한다 (조용히 끝나면 안 됨)."""
    page = json.loads(json.dumps(PAGE1))
    page["response"]["body"]["totalCount"] = 10

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=page)

    with _client(handler) as client:
        with pytest.raises(G2BError, match="max_pages"):
            list(iter_notices(client, "KEY", BEGIN, END, rows=2, max_pages=2))


def test_iter_notices_raises_on_short_read_mid_run():
    """페이지가 비었는데 total이 아직 남아 있으면 조용히 끝나지 않고 raise한다."""
    page1 = json.loads(json.dumps(PAGE1))
    page1["response"]["body"]["totalCount"] = 1832
    page2 = json.loads(json.dumps(PAGE1))
    page2["response"]["body"]["totalCount"] = 1832
    page2["response"]["body"]["items"] = []
    pages = {1: page1, 2: page2}

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(dict(request.url.params)["pageNo"])
        return httpx.Response(200, json=pages[page])

    with _client(handler) as client:
        with pytest.raises(G2BError, match="1832"):
            list(iter_notices(client, "KEY", BEGIN, END, rows=2, max_pages=60))


def test_iter_notices_genuinely_empty_result_returns_without_raising():
    """totalCount=0이고 items도 비어 있으면 정상적으로 빈 결과를 돌려준다."""
    empty = json.loads(json.dumps(PAGE1))
    empty["response"]["body"]["totalCount"] = 0
    empty["response"]["body"]["items"] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=empty)

    with _client(handler) as client:
        items = list(iter_notices(client, "KEY", BEGIN, END, rows=2, max_pages=60))
    assert items == []
