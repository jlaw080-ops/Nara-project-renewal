"""나라장터 낙찰정보서비스 — 용역 낙찰 목록."""

from dataclasses import dataclass

import httpx

from nara.dates import to_iso_date
from nara.g2b.common import check_response, normalise_items, text

BASE_URL = (
    "https://apis.data.go.kr/1230000/as/ScsbidInfoService/getScsbidListSttusServc"
)


@dataclass(frozen=True)
class AwardItem:
    winner: str
    award_date: str
    raw: dict


def fetch_award(client: httpx.Client, api_key: str, bid_no: str) -> AwardItem | None:
    """공고번호로 낙찰업체를 조회한다. 아직 없으면 None."""
    response = client.get(
        BASE_URL,
        params={
            "serviceKey": api_key,
            "type": "json",
            "inqryDiv": "4",
            "bidNtceNo": bid_no,
            "pageNo": "1",
            "numOfRows": "10",
        },
        timeout=30.0,
    )
    body = check_response(response)
    named = [raw for raw in normalise_items(body.get("items")) if text(raw.get("bidwinnrNm"))]
    if not named:
        return None

    best = max(named, key=lambda raw: text(raw.get("rgstDt")) or text(raw.get("fnlSucsfDate")))
    return AwardItem(
        winner=text(best.get("bidwinnrNm")),
        award_date=to_iso_date(text(best.get("rgstDt")) or text(best.get("fnlSucsfDate"))),
        raw=best,
    )
