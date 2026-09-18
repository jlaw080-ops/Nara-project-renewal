import httpx

from nara.config import Secrets
from nara.naver import search_news

KEYED = Secrets(
    g2b_api_key="x", naver_client_id="id", naver_client_secret="sec", anthropic_api_key=None
)
KEYLESS = Secrets(
    g2b_api_key="x", naver_client_id=None, naver_client_secret=None, anthropic_api_key=None
)

PAYLOAD = {
    "items": [
        {
            "title": "완주군 <b>종합사회복지관</b> 기공식",
            "description": "28일 &quot;기공식&quot;이 열렸다",
            "originallink": "https://news.example.com/a",
            "link": "https://n.news.naver.com/a",
            "pubDate": "Thu, 28 Aug 2026 10:00:00 +0900",
        }
    ]
}


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_search_news_reports_that_it_did_not_search_without_keys():
    """키가 없는 것과 결과가 없는 것은 다른 일이다."""
    with _client(lambda r: httpx.Response(500)) as client:
        got = search_news(client, KEYLESS, "완주군 종합사회복지관")
    assert got.searched is False
    assert got.articles == []
    assert got.note


def test_search_news_strips_markup_and_entities_from_title():
    with _client(lambda r: httpx.Response(200, json=PAYLOAD)) as client:
        got = search_news(client, KEYED, "완주군 종합사회복지관")
    assert got.searched is True
    assert got.articles[0].title == "완주군 종합사회복지관 기공식"
    assert '"기공식"' in got.articles[0].body


def test_search_news_converts_rfc822_date_to_iso():
    with _client(lambda r: httpx.Response(200, json=PAYLOAD)) as client:
        got = search_news(client, KEYED, "q")
    assert got.articles[0].published == "2026-08-28"


def test_search_news_uses_the_original_article_url_not_the_portal_link():
    with _client(lambda r: httpx.Response(200, json=PAYLOAD)) as client:
        got = search_news(client, KEYED, "q")
    assert got.articles[0].url == "https://news.example.com/a"


def test_search_news_sends_credentials_in_headers():
    seen = {}

    def handler(request):
        seen.update(request.headers)
        return httpx.Response(200, json=PAYLOAD)

    with _client(handler) as client:
        search_news(client, KEYED, "q")
    assert seen["x-naver-client-id"] == "id"
    assert seen["x-naver-client-secret"] == "sec"


def test_search_news_surfaces_http_failure_without_pretending_to_have_searched():
    with _client(lambda r: httpx.Response(429, text="quota")) as client:
        got = search_news(client, KEYED, "q")
    assert got.searched is False
    assert "429" in got.note


def test_search_news_falls_back_to_portal_link_when_original_is_missing():
    payload = {"items": [dict(PAYLOAD["items"][0], originallink="")]}
    with _client(lambda r: httpx.Response(200, json=payload)) as client:
        got = search_news(client, KEYED, "q")
    assert got.articles[0].url == "https://n.news.naver.com/a"
