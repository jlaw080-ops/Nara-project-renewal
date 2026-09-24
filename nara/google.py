"""구글 뉴스 RSS 검색. 키가 필요 없고, 본문은 오지 않는다.

`naver.py`와 같은 `SearchResult` 계약을 지킨다 — 호출부가 어느 소스인지
몰라도 되게 하려는 것이다.

구글의 공식 검색 API(Custom Search JSON API)는 2026년 1월에 신규 가입이
닫혔고 2027년 1월 1일에 종료된다. 후속으로 안내하는 Vertex AI Search는
내 문서를 검색하는 제품이라 공개 웹 뉴스를 돌려주지 않는다. 그래서
키 없이 부르는 RSS가 현실적인 유일한 구글 경로다.

RSS가 주지 않는 것이 둘 있고, 둘 다 판정을 약하게 만든다:

- **본문.** description은 링크 태그뿐이다. 제목만으로 신호를 읽게 된다.
- **원문 URL.** link는 구글 경유 주소다. 피드 어디에도 기사 원문 주소가
  없고 `<source url>`의 매체 도메인까지가 전부다. 구글이 이 주소 형식을
  바꾸면 그때까지 쌓인 근거 링크가 같이 깨진다.
"""

from email.utils import parsedate_to_datetime
from xml.etree import ElementTree

import httpx

from nara.config import Secrets
from nara.naver import SearchResult
from nara.verdict import Article

ENDPOINT = "https://news.google.com/rss/search"
# 벤더 문자열을 DB 컬럼에 무제한으로 태우지 않는다. naver.py와 같은 한도.
_NOTE_LIMIT = 200


def _iso(pub_date: str) -> str:
    """RFC 822('Sun, 30 Nov 2025 08:00:00 GMT') → ISO 날짜. 못 읽으면 빈 문자열.

    형식이 네이버와 같아 변환도 같다. 못 읽어도 기사를 버리지 않는다 —
    연도 가드가 빈 날짜를 '기준점 없음'으로 이미 다룬다.
    """
    try:
        return parsedate_to_datetime(pub_date).date().isoformat()
    except TypeError, ValueError:
        return ""


def _title(raw: str, publisher: str) -> str:
    """구글이 제목 끝에 붙이는 ' - 매체명'을 뗀다.

    `<source>`가 준 매체명과 **정확히** 맞을 때만 뗀다. 마지막 ' - '를
    추측으로 자르면 '완주군 복지관 - 설계공모 당선작 발표' 같은 진짜
    제목이 잘린다.
    """
    title = (raw or "").strip()
    suffix = f" - {publisher.strip()}"
    if publisher.strip() and title.endswith(suffix):
        return title[: -len(suffix)].strip()
    return title


def search_news(
    client: httpx.Client, secrets: Secrets, query: str, display: int = 10
) -> SearchResult:
    """구글 뉴스에서 기사를 찾는다. `display`는 RSS가 받지 않아 무시한다."""
    try:
        response = client.get(
            ENDPOINT,
            # hl·gl·ceid가 없으면 영어권 결과가 온다. 셋이 함께 붙어야 한다.
            params={"q": query, "hl": "ko", "gl": "KR", "ceid": "KR:ko"},
            timeout=10.0,
        )
    except httpx.HTTPError as exc:
        return SearchResult(failed=True, note=f"뉴스 검색 실패: {exc}"[:_NOTE_LIMIT])

    if response.status_code != 200:
        return SearchResult(failed=True, note=f"뉴스 검색 실패: HTTP {response.status_code}")

    try:
        root = ElementTree.fromstring(response.text)
    except ElementTree.ParseError:
        # HTTP 200이어도 본문이 RSS가 아닐 수 있다(장애 안내 HTML 등).
        # 다른 경로와 같은 방식으로 본문 앞부분만 남긴다.
        return SearchResult(
            failed=True, note=f"뉴스 검색 실패: 응답이 RSS가 아님: {response.text[:_NOTE_LIMIT]}"
        )

    # 잘 만들어진 HTML은 XML로도 읽힌다 — '<html>점검 중</html>'이 그대로
    # 파싱돼 '기사 0건'이 된다. 그러면 장애가 진짜 0건으로 둔갑한다.
    # RSS인지 확인하고 아니면 실패로 말한다.
    if root.tag != "rss" or root.find("channel") is None:
        return SearchResult(
            failed=True, note=f"뉴스 검색 실패: 응답이 RSS가 아님: {response.text[:_NOTE_LIMIT]}"
        )

    articles = []
    for item in root.findall(".//item"):
        source = item.find("source")
        publisher = (source.text or "") if source is not None else ""
        articles.append(
            Article(
                title=_title(item.findtext("title", ""), publisher),
                # RSS description은 링크 태그뿐이라 본문이 없다. 매체명을
                # 대신 채우면 '전북일보'가 신호 낱말 판정에 섞인다.
                body="",
                url=(item.findtext("link", "") or "").strip(),
                published=_iso(item.findtext("pubDate", "")),
            )
        )
    # 항목이 없어도 검색은 성공한 것이다. 진짜 0건과 실패를 섞지 않는다.
    return SearchResult(articles=articles, searched=True)
