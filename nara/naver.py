"""네이버 뉴스 검색. 키가 없으면 검색하지 않았다고 말한다."""

import html
import re
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime

import httpx

from nara.config import Secrets
from nara.verdict import Article

ENDPOINT = "https://openapi.naver.com/v1/search/news.json"
_TAG = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class SearchResult:
    articles: list[Article] = field(default_factory=list)
    searched: bool = False
    note: str = ""


def _plain(raw: str) -> str:
    """네이버는 <b> 태그와 HTML 엔티티를 섞어 보낸다. 둘 다 벗긴다."""
    return html.unescape(_TAG.sub("", raw or "")).strip()


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
        return SearchResult(note=f"뉴스 검색 실패: {exc}")

    if response.status_code != 200:
        return SearchResult(note=f"뉴스 검색 실패: HTTP {response.status_code}")

    items = response.json().get("items") or []
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
