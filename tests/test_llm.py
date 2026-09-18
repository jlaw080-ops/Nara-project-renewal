import anthropic
import httpx2

from nara.config import Secrets
from nara.llm import adjudicate
from nara.verdict import BEFORE, BUILDING, Article

KEYED = Secrets(
    g2b_api_key="x", naver_client_id=None, naver_client_secret=None, anthropic_api_key="sk-test"
)
KEYLESS = Secrets(
    g2b_api_key="x", naver_client_id=None, naver_client_secret=None, anthropic_api_key=None
)
ARTICLES = [
    Article(
        title="완주군 다목적체육관 2026년 9월 착공 예정",
        body="",
        url="https://news.example.com/a",
        published="2026-08-01",
    )
]


class _Block:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _Response:
    def __init__(self, text):
        self.content = [_Block(text)]
        self.stop_reason = "end_turn"


class _FakeClient:
    """messages.create만 흉내 낸다. 실제 SDK를 때리지 않는다."""

    def __init__(self, response=None, raises=None):
        self._response = response
        self._raises = raises
        self.seen = {}
        self.messages = self

    def create(self, **kwargs):
        self.seen.update(kwargs)
        if self._raises:
            raise self._raises
        return self._response


def test_adjudicate_returns_none_without_key():
    assert adjudicate(KEYLESS, "완주군 다목적체육관", ARTICLES, "착공인가 예정인가") is None


def test_adjudicate_reads_verdict_and_reason():
    fake = _FakeClient(_Response(f"{BEFORE}\n기사가 '예정'이라고 적었다"))
    got = adjudicate(KEYED, "완주군 다목적체육관", ARTICLES, "착공인가 예정인가", client=fake)
    assert got == (BEFORE, "기사가 '예정'이라고 적었다")


def test_adjudicate_rejects_a_verdict_outside_the_vocabulary():
    """모델이 제 맘대로 답하면 그 답을 버린다. 조용히 쓰느니 미확인이 낫다."""
    fake = _FakeClient(_Response("아마 공사 중인 듯\n확실하지 않음"))
    assert adjudicate(KEYED, "사업", ARTICLES, "질문", client=fake) is None


def test_adjudicate_returns_none_when_the_api_fails():
    fake = _FakeClient(raises=anthropic.APIConnectionError(request=None))
    assert adjudicate(KEYED, "사업", ARTICLES, "질문", client=fake) is None


def test_adjudicate_returns_none_when_the_response_fails_schema_validation():
    """APIError의 형제가 아니라 자손 — 사슬을 좁게 잡으면 이런 것들이 빠져나간다."""
    response = httpx2.Response(status_code=200, request=httpx2.Request("POST", "https://x"))
    fake = _FakeClient(raises=anthropic.APIResponseValidationError(response=response, body=None))
    assert adjudicate(KEYED, "사업", ARTICLES, "질문", client=fake) is None


def test_adjudicate_uses_opus_5_with_adaptive_thinking_and_no_budget_tokens():
    fake = _FakeClient(_Response(f"{BUILDING}\n기공식 기사"))
    adjudicate(KEYED, "사업", ARTICLES, "질문", client=fake)
    assert fake.seen["model"] == "claude-opus-5"
    assert fake.seen["thinking"] == {"type": "adaptive"}
    # budget_tokens는 Opus 5에서 제거됐다 — 보내면 400이다.
    assert "budget_tokens" not in str(fake.seen)


def test_adjudicate_puts_the_articles_in_the_prompt():
    fake = _FakeClient(_Response(f"{BEFORE}\n근거"))
    adjudicate(KEYED, "완주군 다목적체육관", ARTICLES, "착공인가 예정인가", client=fake)
    sent = str(fake.seen["messages"])
    assert "완주군 다목적체육관 2026년 9월 착공 예정" in sent
    assert "https://news.example.com/a" in sent


def test_adjudicate_returns_none_on_refusal():
    response = _Response(f"{BUILDING}\n근거")
    response.stop_reason = "refusal"
    assert adjudicate(KEYED, "사업", ARTICLES, "질문", client=_FakeClient(response)) is None


def test_adjudicate_returns_none_when_truncated_by_max_tokens():
    """판정 줄은 멀쩡해도 근거가 잘렸을 수 있다 — end_turn만 화이트리스트로 받는다."""
    response = _Response(f"{BUILDING}\n근거가 중간에")
    response.stop_reason = "max_tokens"
    assert adjudicate(KEYED, "사업", ARTICLES, "질문", client=_FakeClient(response)) is None
