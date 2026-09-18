"""네이버 뉴스 검색. 키가 없으면 검색하지 않았다고 말한다."""

import html
import re
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime

import httpx

from nara.config import Secrets
from nara.verdict import Article

ENDPOINT = "https://openapi.naver.com/v1/search/news.json"
# 네이버가 실제로 섞어 보내는 건 검색어 강조용 <b> 태그뿐이다. 그 외 꺾쇠는
# 기사 본문 내용일 수 있어(R20) 일반 태그 제거로 지우지 않는다.
_B_TAG = re.compile(r"</?b>", re.IGNORECASE)


@dataclass(frozen=True)
class SearchResult:
    """`searched`와 `failed`는 서로 다른 일을 뜻한다 — 둘 다 False일 수 있다.

    키가 없어 아예 안 부른 것은 실패가 아니다. 그 건은 CLI가 회차 첫머리에
    따로 안내하므로, 실패로 세면 같은 사실을 두 번 말하면서 진짜 실패한
    회차와 구분이 안 된다. 호출부가 note 문자열을 뒤져 둘을 가르지 않도록
    여기서 표시해 둔다.
    """

    articles: list[Article] = field(default_factory=list)
    searched: bool = False
    failed: bool = False
    note: str = ""


def _plain(raw: str) -> str:
    """네이버는 <b> 태그와 HTML 엔티티를 섞어 보낸다. 둘 다 벗긴다.

    <b> 태그만 벗긴다 — 다른 꺾쇠(<원>, <300㎡로 확장> 등)는 기사 본문의
    일부라 지우면 내용이 사라진다. 보이는 쪽이 사라지는 쪽보다 낫다.
    """
    return html.unescape(_B_TAG.sub("", raw or "")).strip()


def _iso(pub_date: str) -> str:
    """RFC 822('Mon, 26 Sep 2026 14:12:00 +0900') → ISO 날짜. 못 읽으면 빈 문자열."""
    try:
        return parsedate_to_datetime(pub_date).date().isoformat()
    except TypeError, ValueError:
        return ""


def search_news(
    client: httpx.Client, secrets: Secrets, query: str, display: int = 10
) -> SearchResult:
    if not (secrets.naver_client_id and secrets.naver_client_secret):
        return SearchResult(note="네이버 검색 키가 없어 뉴스 검색을 건너뛰었다")

    try:
        response = client.get(
            ENDPOINT,
            params={"query": query, "display": display, "sort": "sim"},
            headers={
                "X-Naver-Client-Id": secrets.naver_client_id,
                "X-Naver-Client-Secret": secrets.naver_client_secret,
            },
            timeout=10.0,
        )
    except httpx.HTTPError as exc:
        return SearchResult(failed=True, note=f"뉴스 검색 실패: {exc}")

    if response.status_code != 200:
        return SearchResult(failed=True, note=f"뉴스 검색 실패: HTTP {response.status_code}")

    try:
        payload = response.json()
    except ValueError:
        # HTTP 200이어도 본문이 JSON이 아닐 수 있다(예: 장애 안내 HTML).
        # g2b/common.py의 check_response와 같은 방식으로 본문 앞부분을 남긴다.
        return SearchResult(
            failed=True, note=f"뉴스 검색 실패: 응답이 JSON이 아님: {response.text[:200]}"
        )

    if payload.get("errorCode") or payload.get("errorMessage"):
        code = payload.get("errorCode", "")
        message = payload.get("errorMessage", "")
        # 다른 두 경로(JSON 아님·items 없음)와 같은 방식으로 본문 앞부분만 남긴다.
        # 벤더가 실어 보내는 문자열을 그대로 DB 컬럼에 무제한으로 태우지 않는다.
        detail = f"{code} {message}".strip()[:200]
        return SearchResult(failed=True, note=f"뉴스 검색 실패: {detail}")

    items = payload.get("items")
    if not isinstance(items, list):
        # items가 아예 없거나(필드 누락·None) 리스트가 아니면 '진짜 0건'과
        # 구분할 수 없다(R21). 이때는 검색이 안 된 것으로 취급한다.
        return SearchResult(
            failed=True, note=f"뉴스 검색 실패: 응답에 items가 없음: {response.text[:200]}"
        )

    articles = [
        Article(
            title=_plain(item.get("title", "")),
            body=_plain(item.get("description", "")),
            # 원 기사를 근거로 남긴다. 포털 링크는 원문이 내려가면 같이 사라진다.
            url=(item.get("originallink") or item.get("link") or "").strip(),
            published=_iso(item.get("pubDate", "")),
        )
        for item in items
    ]
    return SearchResult(articles=articles, searched=True)
