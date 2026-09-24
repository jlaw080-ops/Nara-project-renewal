import httpx

from nara.config import Secrets
from nara.google import search_news

SECRETS = Secrets(
    g2b_api_key="x", naver_client_id=None, naver_client_secret=None, anthropic_api_key=None
)


def _feed(items: str) -> str:
    return (
        f'<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>{items}</channel></rss>'
    )


ITEM = """<item>
  <title>완주군 종합사회복지관 기공식 개최 - 전북일보 인터넷신문</title>
  <link>https://news.google.com/rss/articles/CBMiABC</link>
  <guid isPermaLink="false">CBMiABC</guid>
  <pubDate>Thu, 28 Aug 2026 10:00:00 GMT</pubDate>
  <description>&lt;a href="https://news.google.com/rss/articles/CBMiABC"&gt;완주군&lt;/a&gt;</description>
  <source url="https://www.jjan.kr">전북일보 인터넷신문</source>
</item>"""


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_search_news_needs_no_key():
    """구글 뉴스 RSS는 키를 요구하지 않는다 — 키 없는 회차도 진짜 검색이다."""
    with _client(lambda r: httpx.Response(200, text=_feed(ITEM))) as client:
        got = search_news(client, SECRETS, "완주군 종합사회복지관")
    assert got.searched is True
    assert got.failed is False
    assert len(got.articles) == 1


def test_search_news_strips_the_publisher_suffix_from_the_title():
    """구글은 제목 끝에 ' - 매체명'을 붙인다. <source>와 정확히 맞을 때만 뗀다."""
    with _client(lambda r: httpx.Response(200, text=_feed(ITEM))) as client:
        got = search_news(client, SECRETS, "완주군 종합사회복지관")
    assert got.articles[0].title == "완주군 종합사회복지관 기공식 개최"


def test_search_news_keeps_a_title_whose_tail_is_not_the_publisher():
    """매체명과 다른 꼬리는 기사 제목의 일부다 — 추측으로 자르지 않는다."""
    item = ITEM.replace(
        "<title>완주군 종합사회복지관 기공식 개최 - 전북일보 인터넷신문</title>",
        "<title>완주군 복지관 - 설계공모 당선작 발표</title>",
    )
    with _client(lambda r: httpx.Response(200, text=_feed(item))) as client:
        got = search_news(client, SECRETS, "완주군")
    assert got.articles[0].title == "완주군 복지관 - 설계공모 당선작 발표"


def test_search_news_leaves_the_body_empty():
    """RSS description은 링크 태그뿐이라 본문이 없다.

    매체명을 대신 채우면 '전북일보'가 신호 낱말 판정에 섞인다. 없는 것을
    없다고 두는 편이 낫다.
    """
    with _client(lambda r: httpx.Response(200, text=_feed(ITEM))) as client:
        got = search_news(client, SECRETS, "완주군 종합사회복지관")
    assert got.articles[0].body == ""


def test_search_news_reads_the_published_date():
    with _client(lambda r: httpx.Response(200, text=_feed(ITEM))) as client:
        got = search_news(client, SECRETS, "완주군 종합사회복지관")
    assert got.articles[0].published == "2026-08-28"


def test_search_news_keeps_an_article_whose_date_is_unreadable():
    """날짜를 못 읽어도 기사는 버리지 않는다 — 연도 가드가 빈 값을 이미 다룬다."""
    item = ITEM.replace(
        "<pubDate>Thu, 28 Aug 2026 10:00:00 GMT</pubDate>", "<pubDate>어제</pubDate>"
    )
    with _client(lambda r: httpx.Response(200, text=_feed(item))) as client:
        got = search_news(client, SECRETS, "완주군")
    assert len(got.articles) == 1
    assert got.articles[0].published == ""


def test_search_news_reports_a_real_zero_result():
    """진짜 0건은 검색에 성공한 것이다. 실패와 섞으면 안 된다."""
    with _client(lambda r: httpx.Response(200, text=_feed(""))) as client:
        got = search_news(client, SECRETS, "없는 사업")
    assert got.searched is True
    assert got.failed is False
    assert got.articles == []


def test_search_news_reports_an_http_error_as_a_failure():
    with _client(lambda r: httpx.Response(503)) as client:
        got = search_news(client, SECRETS, "완주군")
    assert got.searched is False
    assert got.failed is True
    assert "503" in got.note


def test_search_news_reports_a_transport_error_as_a_failure():
    def boom(request):
        raise httpx.ConnectError("끊김")

    with _client(boom) as client:
        got = search_news(client, SECRETS, "완주군")
    assert got.failed is True
    assert got.note


def test_search_news_reports_unparseable_xml_as_a_failure():
    """HTTP 200이어도 본문이 XML이 아닐 수 있다(장애 안내 HTML 등)."""
    with _client(lambda r: httpx.Response(200, text="<html>점검 중</html>")) as client:
        got = search_news(client, SECRETS, "완주군")
    assert got.failed is True
    assert got.searched is False
    assert got.note


def test_search_news_caps_the_failure_note():
    """벤더 문자열을 DB 컬럼에 무제한으로 태우지 않는다 — 다른 경로와 같은 한도."""
    with _client(lambda r: httpx.Response(200, text="<" + "긴오류" * 400)) as client:
        got = search_news(client, SECRETS, "완주군")
    assert got.failed is True
    assert len(got.note) <= 240


def test_search_news_asks_google_in_korean():
    """한국어 결과를 받으려면 hl·gl·ceid가 붙어야 한다."""
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        return httpx.Response(200, text=_feed(ITEM))

    with _client(handler) as client:
        search_news(client, SECRETS, "완주군 종합사회복지관")
    assert "hl=ko" in seen["url"]
    assert "gl=KR" in seen["url"]
    assert "ceid=KR%3Ako" in seen["url"] or "ceid=KR:ko" in seen["url"]
    assert "%EC%99%84%EC%A3%BC%EA%B5%B0" in seen["url"]
