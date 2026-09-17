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


def _award_date_of(raw: dict) -> str:
    """등록일 우선, 없으면 최종낙찰일. 언제나 ISO 문자열이라 비교가 안전하다."""
    return to_iso_date(text(raw.get("rgstDt"))) or to_iso_date(text(raw.get("fnlSucsfDate")))


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

    # 정규화한 ISO 날짜로 비교한다. 원문끼리 비교하면 안 된다 — API가 같은 필드를
    # '20260910'과 '2026-09-20 10:00:00' 두 형태로 섞어 주는데, '-'(0x2D)가 숫자보다
    # 작아서 max()가 더 이른 날을 고른다.
    best = max(named, key=_award_date_of)
    return AwardItem(
        winner=text(best.get("bidwinnrNm")),
        award_date=_award_date_of(best),
        raw=best,
    )
