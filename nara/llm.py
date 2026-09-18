"""규칙과 기사로 못 가른 건만 Claude에게 묻는다.

키가 없거나 호출이 실패하거나 모델이 어휘 밖의 답을 하면 None을 돌려준다.
호출부는 그걸 '미확인'으로 남긴다 — 추측한 판정을 쓰는 것보다 낫다.
"""

import anthropic

from nara.config import Secrets
from nara.verdict import BEFORE, BUILDING, DONE, UNKNOWN, Article

MODEL = "claude-opus-5"
VOCABULARY = (BEFORE, BUILDING, DONE, UNKNOWN)

SYSTEM = (
    "너는 한국 공공 건축사업의 진행현황을 기사만 보고 판정한다.\n"
    "첫 줄에 판정 하나만 적는다. 다음 넷 중 하나를 글자 그대로 쓴다:\n"
    f"{BEFORE} / {BUILDING} / {DONE} / {UNKNOWN}\n"
    "둘째 줄에 근거를 한 문장으로 적는다.\n"
    "규칙:\n"
    "- 철거·멸실은 착공이 아니다. 철거 단계면 착공 전이다.\n"
    "- '착공 예정'·'준공 목표'는 그 일이 일어났다는 뜻이 아니다.\n"
    "- 기사가 같은 이름의 다른 사업으로 보이면 미확인이다.\n"
    "- 확신이 없으면 미확인이라고 적는다. 추측하지 않는다."
)


def _prompt(project_name: str, articles: list[Article], question: str) -> str:
    lines = [f"사업명: {project_name}", f"가려야 할 점: {question}", "", "기사:"]
    for article in articles:
        lines.append(f"- [{article.published}] {article.title} ({article.url})")
        if article.body:
            lines.append(f"  {article.body}")
    return "\n".join(lines)


def adjudicate(
    secrets: Secrets,
    project_name: str,
    articles: list[Article],
    question: str,
    client=None,
) -> tuple[str, str] | None:
    if not secrets.anthropic_api_key:
        return None

    api = client or anthropic.Anthropic(api_key=secrets.anthropic_api_key, timeout=30.0)
    try:
        response = api.messages.create(
            model=MODEL,
            max_tokens=1000,
            system=SYSTEM,
            thinking={"type": "adaptive"},
            output_config={"effort": "low"},
            messages=[{"role": "user", "content": _prompt(project_name, articles, question)}],
        )
    except anthropic.APIError:
        return None

    # 화이트리스트: 자연 종료(end_turn)만 받아들인다. tool·정지 시퀀스를
    # 쓰지 않으니 end_turn이 유일한 정상 종료다. refusal은 물론
    # max_tokens(중간에 잘린 근거를 그대로 판정으로 쓰게 됨) 같은 낯선
    # stop_reason도 전부 닫힌 쪽으로 실패한다.
    if getattr(response, "stop_reason", "") != "end_turn":
        return None

    text = "".join(b.text for b in response.content if getattr(b, "type", "") == "text")
    head, _, tail = text.strip().partition("\n")
    verdict = head.strip()
    # 어휘 밖의 답은 판정으로 받아들이지 않는다.
    if verdict not in VOCABULARY:
        return None
    return verdict, tail.strip()
