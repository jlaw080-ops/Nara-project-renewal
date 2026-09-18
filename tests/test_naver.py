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


# --- Fix round 1: F1 — HTTP 200이어도 본문이 JSON이 아니면 예외가 새면 안 된다 ---


def test_search_news_surfaces_non_json_body_without_raising():
    """200인데 본문이 HTML(장애 안내 등)이면 예외를 던지지 않고 note로 알린다."""
    with _client(lambda r: httpx.Response(200, text="<html>Service Unavailable</html>")) as client:
        got = search_news(client, KEYED, "q")
    assert got.searched is False
    assert got.articles == []
    assert "Service Unavailable" in got.note


# --- Fix round 1: F2 — 200 + 오류/이상 페이로드가 진짜 0건과 구분돼야 한다 ---


def test_search_news_reports_naver_error_payload_without_pretending_to_have_searched():
    """키가 틀렸을 때 네이버가 돌려주는 200 + errorCode 페이로드는 검색 실패다."""
    payload = {"errorCode": "024", "errorMessage": "Not Exist Client ID"}
    with _client(lambda r: httpx.Response(200, json=payload)) as client:
        got = search_news(client, KEYED, "q")
    assert got.searched is False
    assert got.articles == []
    assert "024" in got.note
    assert "Not Exist Client ID" in got.note


def test_search_news_truncates_oversized_error_message_to_the_same_bound_as_siblings():
    """errorMessage가 5000자여도 note는 다른 두 경로와 같은 200자 발췌 한도를 지킨다."""
    message = "A" * 5000
    payload = {"errorCode": "024", "errorMessage": message}
    with _client(lambda r: httpx.Response(200, json=payload)) as client:
        got = search_news(client, KEYED, "q")
    assert got.searched is False
    assert message not in got.note
    # "024 " + "A"*196 == 200자 발췌("024 " + message를 [:200]으로 자른 결과).
    prefix_len = len("뉴스 검색 실패: ")
    assert len(got.note) == prefix_len + 200
    assert got.note.endswith("A" * 196)
    assert "A" * 197 not in got.note


def test_search_news_reports_null_items_without_pretending_to_have_searched():
    """items가 null이면 '0건'이 아니라 '검색 안 됨'이다."""
    with _client(lambda r: httpx.Response(200, json={"items": None})) as client:
        got = search_news(client, KEYED, "q")
    assert got.searched is False
    assert got.articles == []
    assert got.note


def test_search_news_reports_missing_items_key_without_pretending_to_have_searched():
    """items 키 자체가 없으면 '0건'이 아니라 '검색 안 됨'이다."""
    payload = {"lastBuildDate": "Thu, 28 Aug 2026"}
    with _client(lambda r: httpx.Response(200, json=payload)) as client:
        got = search_news(client, KEYED, "q")
    assert got.searched is False
    assert got.articles == []
    assert got.note


def test_search_news_treats_genuinely_empty_items_as_a_real_zero_result():
    """items가 빈 리스트인 진짜 0건은 위 세 경우와 달리 searched=True다."""
    with _client(lambda r: httpx.Response(200, json={"items": []})) as client:
        got = search_news(client, KEYED, "q")
    assert got.searched is True
    assert got.articles == []


# --- Fix round 1: F3 — <b> 태그만 벗긴다. 다른 꺾쇠는 기사 내용이다 ---


def test_search_news_still_strips_b_tags():
    payload = {"items": [dict(PAYLOAD["items"][0], title="<b>기공식</b> 개최", description="")]}
    with _client(lambda r: httpx.Response(200, json=payload)) as client:
        got = search_news(client, KEYED, "q")
    assert got.articles[0].title == "기공식 개최"


def test_search_news_keeps_non_b_angle_brackets_as_article_content():
    payload = {
        "items": [
            dict(
                PAYLOAD["items"][0],
                title="완주군 복지관 면적 <300㎡로 확장> 준공식",
                description="예산 3억<원> 증액",
            )
        ]
    }
    with _client(lambda r: httpx.Response(200, json=payload)) as client:
        got = search_news(client, KEYED, "q")
    assert got.articles[0].title == "완주군 복지관 면적 <300㎡로 확장> 준공식"
    assert got.articles[0].body == "예산 3억<원> 증액"


# --- Fix round 2: I1 — 검색 실패와 '키가 없어 건너뜀'은 서로 다른 일이다 ---


def test_search_news_marks_an_http_failure_as_failed():
    """실패는 failed로 표시한다 — 호출부가 note 문자열을 뒤지지 않게 한다."""
    with _client(lambda r: httpx.Response(401, text="Unauthorized")) as client:
        got = search_news(client, KEYED, "q")
    assert got.searched is False
    assert got.failed is True


def test_search_news_does_not_mark_a_missing_key_as_a_failure():
    """키가 없어 건너뛴 것은 실패가 아니다 — CLI가 이미 따로 안내한다.

    이걸 실패로 세면 키 없는 회차마다 경고가 두 번 나와, 진짜 실패한 회차와
    구분이 안 된다.
    """
    with _client(lambda r: httpx.Response(200, json=PAYLOAD)) as client:
        got = search_news(client, KEYLESS, "q")
    assert got.searched is False
    assert got.failed is False


def test_search_news_does_not_mark_a_successful_search_as_failed():
    with _client(lambda r: httpx.Response(200, json=PAYLOAD)) as client:
        got = search_news(client, KEYED, "q")
    assert got.searched is True
    assert got.failed is False


def test_search_news_marks_an_error_payload_as_failed():
    """200 + errorCode도 실패다 — HTTP 코드만 보면 놓친다."""
    payload = {"errorCode": "024", "errorMessage": "Not Exist Client ID"}
    with _client(lambda r: httpx.Response(200, json=payload)) as client:
        got = search_news(client, KEYED, "q")
    assert got.failed is True
