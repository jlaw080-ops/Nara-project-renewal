"""나라장터 입찰공고정보서비스 — 용역 공고 목록."""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime

import httpx

from nara.dates import to_iso_date
from nara.g2b.common import G2BError, check_response, normalise_items, text, to_int

BASE_URL = (
    "https://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoServcPPSSrch"
)
DETAIL_URL = "https://www.g2b.go.kr/link/PNPE027_01/single/"


@dataclass(frozen=True)
class NoticeItem:
    bid_no: str
    bid_ord: str
    org_name: str
    title: str
    service_div: str
    kind: str
    notice_date: str
    open_date: str
    close_date: str
    url: str
    budget_krw: int | None
    budget_basis: str
    officer_name: str
    officer_tel: str
    raw: dict


def _budget(raw: dict) -> tuple[int | None, str]:
    if (n := to_int(raw.get("presmptPrce"))) is not None:
        return n, "추정가격"
    if (n := to_int(raw.get("asignBdgtAmt"))) is not None:
        return n, "배정예산"
    return None, ""


def _url(raw: dict) -> str:
    if url := (text(raw.get("bidNtceDtlUrl")) or text(raw.get("bidNtceUrl"))):
        return url
    bid_no = text(raw.get("bidNtceNo"))
    if not bid_no:
        return ""
    ord_ = f"{text(raw.get('bidNtceOrd')) or '0':0>3}"
    return f"{DETAIL_URL}?bidPbancNo={bid_no}&bidPbancOrd={ord_}"


def _to_item(raw: dict) -> NoticeItem:
    budget, basis = _budget(raw)
    return NoticeItem(
        bid_no=text(raw.get("bidNtceNo")),
        bid_ord=text(raw.get("bidNtceOrd")),
        org_name=text(raw.get("dminsttNm")),
        title=text(raw.get("bidNtceNm")),
        service_div=text(raw.get("srvceDivNm")),
        kind=text(raw.get("ntceKindNm")),
        notice_date=to_iso_date(text(raw.get("bidNtceDt"))),
        open_date=to_iso_date(text(raw.get("opengDt"))),
        close_date=to_iso_date(text(raw.get("bidClseDt"))),
        url=_url(raw),
        budget_krw=budget,
        budget_basis=basis,
        officer_name=text(raw.get("ntceInsttOfclNm")),
        officer_tel=text(raw.get("ntceInsttOfclTelNo")),
        raw=raw,
    )


def _stamp(dt: datetime) -> str:
    return dt.strftime("%Y%m%d%H%M")


def fetch_notice_page(
    client: httpx.Client,
    api_key: str,
    begin: datetime,
    end: datetime,
    page: int,
    rows: int,
) -> tuple[list[NoticeItem], int]:
    """한 페이지를 읽어 (항목, 전체 건수)를 돌려준다."""
    response = client.get(
        BASE_URL,
        params={
            "serviceKey": api_key,
            "type": "json",
            "inqryDiv": "1",
            "inqryBgnDt": _stamp(begin),
            "inqryEndDt": _stamp(end),
            "pageNo": str(page),
            "numOfRows": str(rows),
        },
        timeout=30.0,
    )
    body = check_response(response)
    items = [_to_item(raw) for raw in normalise_items(body.get("items"))]
    return items, int(body.get("totalCount") or 0)


def iter_notices(
    client: httpx.Client,
    api_key: str,
    begin: datetime,
    end: datetime,
    rows: int = 500,
    max_pages: int = 60,
) -> Iterator[NoticeItem]:
    """기간 안의 공고를 페이지를 넘겨 가며 전부 돌려준다.

    빈 페이지나 max_pages 소진은 total이 이미 다 채워졌을 때만 정상 종료다.
    그렇지 않으면 짧은 응답을 조용히 삼키지 않고 G2BError를 올린다.
    """
    page = 1
    fetched = 0
    total = 0
    while page <= max_pages:
        items, total = fetch_notice_page(client, api_key, begin, end, page, rows)
        if not items:
            if (page - 1) * rows < total:
                raise G2BError(
                    f"{page}페이지가 비어 있는데 totalCount={total}, 지금까지 {fetched}건만 받음"
                )
            return
        fetched += len(items)
        yield from items
        if total and page * rows >= total:
            return
        page += 1
    if total and fetched < total:
        raise G2BError(f"max_pages={max_pages} 소진, totalCount={total}, {fetched}건만 받음")
