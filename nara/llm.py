"""규칙과 기사로 못 가른 건만 Claude에게 묻는다.

키가 없거나 호출이 실패하거나 모델이 어휘 밖의 답을 하면 None을 돌려준다.
호출부는 그걸 '미확인'으로 남긴다 — 추측한 판정을 쓰는 것보다 낫다.
"""

import re

import anthropic

from nara.config import Secrets
from nara.dept_rules import POSITION, DeptAnswer, StaffContact, normalize_tel
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
SYSTEM_DEPT = (
    "너는 한국 지자체 입찰 공고문에서 사업을 맡은 실행부서를 찾는다.\n"
    "다음 다섯 줄로만 답한다:\n"
    "실행부서: <부서 이름 또는 없음>\n"
    "계약부서: <부서 이름 또는 없음>\n"
    "근거: <공고문에서 글자를 바꾸지 않고 그대로 옮긴 문장>\n"
    "담당자: <실행부서 담당자 이름 직위 또는 없음>\n"
    "전화: <실행부서 전화번호 또는 없음>\n"
    "규칙:\n"
    "- 공고문에 적힌 것만 답한다. 조직도나 사업 성격으로 짐작하지 않는다.\n"
    "- 계약·입찰·개찰·회계 문의 부서(재무과·회계과 등)는 실행부서가 아니다.\n"
    "- 실행부서는 과 단위로 적는다. 팀 이름은 적지 않는다.\n"
    "- 담당자·전화도 공고문에 적힌 것만 적는다. 계약부서 전화는 적지 않는다.\n"
    "- 확신이 없으면 '실행부서: 없음'이라고 적는다."
)
_NONE = {"", "없음", "없음.", "-"}


def _prompt(project_name: str, articles: list[Article], question: str) -> str:
    lines = [f"사업명: {project_name}", f"가려야 할 점: {question}", "", "기사:"]
    for article in articles:
        lines.append(f"- [{article.published}] {article.title} ({article.url})")
        if article.body:
            lines.append(f"  {article.body}")
    return "\n".join(lines)


# 키별로 클라이언트 하나씩 돌려 쓴다. 예전에는 호출마다 새로 만들고 닫지
# 않아 300건 회차면 연결 풀을 든 클라이언트가 300개 생겼다. SDK 클라이언트는
# 상태가 없고 스레드 안전하며 연결 풀을 재사용하도록 만들어진 물건이라,
# 건마다 새로 만들 이유가 없다. 키를 섞지 않도록 키를 열쇠로 쓴다.
_CLIENTS: dict[str, anthropic.Anthropic] = {}


def _shared_client(api_key: str) -> anthropic.Anthropic:
    api = _CLIENTS.get(api_key)
    if api is None:
        api = anthropic.Anthropic(api_key=api_key, timeout=30.0)
        _CLIENTS[api_key] = api
    return api


def _reset_clients() -> None:
    """테스트가 가짜 클라이언트를 끼울 수 있게 캐시를 비운다."""
    _CLIENTS.clear()


def _complete(secrets: Secrets, system: str, content: str, client=None) -> str | None:
    """정상 종료한 답의 글자. 키가 없거나 실패하면 None."""
    if not secrets.anthropic_api_key:
        return None
    api = client or _shared_client(secrets.anthropic_api_key)
    try:
        response = api.messages.create(
            model=MODEL,
            max_tokens=1000,
            system=system,
            thinking={"type": "adaptive"},
            output_config={"effort": "low"},
            messages=[{"role": "user", "content": content}],
        )
    except anthropic.APIError:
        return None
    # 화이트리스트: 자연 종료(end_turn)만 받아들인다. tool·정지 시퀀스를
    # 쓰지 않으니 end_turn이 유일한 정상 종료다. refusal은 물론
    # max_tokens(중간에 잘린 근거를 그대로 판정으로 쓰게 됨) 같은 낯선
    # stop_reason도 전부 닫힌 쪽으로 실패한다.
    if getattr(response, "stop_reason", "") != "end_turn":
        return None
    return "".join(b.text for b in response.content if getattr(b, "type", "") == "text")


def adjudicate(
    secrets: Secrets,
    project_name: str,
    articles: list[Article],
    question: str,
    client=None,
) -> tuple[str, str] | None:
    text = _complete(secrets, SYSTEM, _prompt(project_name, articles, question), client)
    if text is None:
        return None
    head, _, tail = text.strip().partition("\n")
    verdict = head.strip()
    # 어휘 밖의 답은 판정으로 받아들이지 않는다.
    if verdict not in VOCABULARY:
        return None
    return verdict, tail.strip()


def _field(text: str, label: str) -> str:
    for line in text.splitlines():
        head, sep, value = line.partition(":")
        if sep and head.strip() == label:
            return value.strip()
    return ""


def ask_dept(secrets: Secrets, excerpt: str, client=None) -> DeptAnswer | None:
    """공고문 발췌를 보여 주고 실행부서·계약부서·근거 문장을 받는다.

    답을 믿지 않는다 — 호출부가 근거 문장을 원문과 대조한 뒤에만 확정한다.
    """
    text = _complete(secrets, SYSTEM_DEPT, f"공고문 발췌:\n{excerpt}", client)
    if text is None:
        return None
    exec_dept, contract = _field(text, "실행부서"), _field(text, "계약부서")
    return DeptAnswer(
        exec_dept=None if exec_dept in _NONE else exec_dept,
        contract_dept=None if contract in _NONE else contract,
        quote=_field(text, "근거"),
        staff=_staff(_field(text, "담당자"), _field(text, "전화")),
    )


def _staff(who: str, tel: str) -> StaffContact | None:
    """'김철수 주무관' → 이름·직위. 직위 낱말이 없으면 전부 이름."""
    name = position = None
    if who not in _NONE:
        m = re.fullmatch(rf"\s*([가-힣]{{2,4}})\s*({POSITION})?\s*", who)
        if m:
            name, position = m.group(1), m.group(2)
    staff = StaffContact(name, position, None if tel in _NONE else normalize_tel(tel))
    return None if staff.empty else staff
