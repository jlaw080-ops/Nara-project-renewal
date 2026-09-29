"""공고문에서 실행부서 후보를 찾고, Claude 답을 원문과 대조한다.

notice-dept-contact-lookup 스킬의 find_dept.py를 옮겼다. 규칙은 후보만 좁힌다.
후보가 하나이고 신호어 바로 뒤에서 찾았을 때만 확정한다. 조직도나 사업
성격으로 짐작하지 않는다 — 문서에서 읽은 것만 쓴다.
"""

import re
from collections import Counter
from dataclasses import dataclass

# 계약·회계 계열 = 실행부서가 아니다
EXCL = re.compile(r"^(재무|회계|경리|세정|예산|기획예산|계약|감사|재정관리)")
# 부서처럼 보이지만 아닌 것들 (시설명·법령·기관명)
BAD = re.compile(
    r"국가법령정보센터|조달청|나라장터|지방자치단|개찰|열람장소|기술사사무소"
    r"|소방시설|정보센터|본점소|건축사사무소|엔지니어링|전시실|회의실|사무실"
    r"|민원실|교실|도서관|숙소|화장실|창고|기계실|전기실|단련실|프로그램실|자료실"
)
# 조사 '과'(=and)가 붙어 부서명처럼 보이는 것들. "이 사업과 관련된" → 가짜 부서 "사업과"
JOSA = re.compile(
    r"^(사업|다음|역할|향상|방안|제반|기관|수단|입찰|군민|방문객|성찰|업무|계획|내용"
    r"|목적|결과|기준|조건|자격|서류|절차|방법|현황)과$"
)
# 앞에 지시관형사가 오면 조사 결합이다: "이 사업과", "본 사업과", "동 용역과".
# 지시어가 따로 선 낱말일 때만이다 — "다음과 같이 건축과"의 "같이"를 "이"로 읽으면 안 된다.
DEICTIC = re.compile(r"(?:^|[^가-힣])(이|본|동|해당|당해|위)\s*$")
DEPT = re.compile(
    r"([가-힣]{2,12}(?:과|국|실|단|소|센터|본부|사업소|담당관))"
    r"(\s*([가-힣]{2,10}(?:팀|계|담당)))?"
)
# 실행부서를 가리키는 신호어 — 계약부서 신호어와 짝을 이뤄 등장하는 경우가 많다
CUE = re.compile(
    r"사업\s*담당|사업\s*부서|사업\s*관련|담당\s*부서|주관\s*부서|열람\s*문의"
    r"|설계서\s*열람|과업\s*(?:관련|문의|지시서)|설계\s*(?:관련|문의)"
    r"|용역에\s*관한|문의처|접수\s*처|장\s*소\s*:"
)
CONTRACT_CUE = re.compile(r"계약\s*(?:관련|문의|에\s*관한)|입찰\s*(?:관련|문의|에\s*관한)")
_SPACED = re.compile(r"(?<![가-힣])((?:[가-힣] ){2,}[과국실소단])(?![가-힣])")
_WS = re.compile(r"\s+")
WINDOW = 200  # 신호어 뒤로 부서를 찾는 폭
NEAR = 90  # 이 안에서 찾으면 신호어 바로 뒤로 본다
EXCERPT_AROUND = 300
EXCERPT_TAIL = 1500  # 문의처는 대개 공고문 끝에 있다
EXCERPT_LIMIT = 6000
MIN_QUOTE = 8


@dataclass(frozen=True)
class Candidate:
    name: str  # 과 단위 부서 이름
    weight: int
    snippet: str  # 근거 문장
    near: bool  # 신호어 바로 뒤(90자 안)에서 찾았는가


@dataclass(frozen=True)
class DeptAnswer:
    exec_dept: str | None
    contract_dept: str | None
    quote: str


def unspace(text: str) -> str:
    """칸을 맞추려고 띄운 부서명(`행 정 과`)을 붙인다."""
    return _SPACED.sub(lambda m: m.group(1).replace(" ", ""), text)


def squash(text: str) -> str:
    return _WS.sub("", text)


def _clean(text: str) -> str:
    return re.sub(r"[ \t]+", " ", unspace(text))


def _is_candidate(name: str, before: str) -> bool:
    if EXCL.match(name) or BAD.search(name) or len(name) < 3:
        return False
    return not (JOSA.match(name) or DEICTIC.search(before))


def find_candidates(text: str) -> list[Candidate]:
    txt = _clean(text)
    weights: Counter[str] = Counter()
    first: dict[str, tuple[str, bool]] = {}
    for cue in CUE.finditer(txt):
        start = cue.start()
        # 줄바꿈을 한 칸으로 바꿔 글자 위치를 그대로 둔다
        window = txt[start : start + WINDOW].replace("\n", " ")
        for m in DEPT.finditer(window):
            name = m.group(1)
            if not _is_candidate(name, window[: m.start()]):
                continue
            near = m.start() < NEAR
            weights[name] += 3 if near else 1
            end = start + max(150, m.end() + 20)
            snippet = _WS.sub(" ", txt[max(0, start - 40) : end]).strip()[:250]
            if name not in first or (near and not first[name][1]):
                first[name] = (snippet, near)
    return [Candidate(n, w, first[n][0], first[n][1]) for n, w in weights.most_common()]


def find_contract_dept(text: str) -> str | None:
    txt = _clean(text)
    for cue in CONTRACT_CUE.finditer(txt):
        window = txt[cue.start() : cue.start() + WINDOW].replace("\n", " ")
        for m in DEPT.finditer(window):
            if EXCL.match(m.group(1)):
                return m.group(1)
    return None


def decide_by_rule(candidates: list[Candidate]) -> Candidate | None:
    """후보가 하나뿐이고 신호어 바로 뒤에서 찾았을 때만 확정한다."""
    if len(candidates) == 1 and candidates[0].near:
        return candidates[0]
    return None


def excerpt_for_llm(text: str) -> str:
    """신호어 앞뒤 구간과 문서 끝. 끝부분은 잘리지 않게 남기고 앞쪽을 줄인다."""
    txt = _clean(text)
    tail_start = max(0, len(txt) - EXCERPT_TAIL)
    cues = [*CUE.finditer(txt), *CONTRACT_CUE.finditer(txt)]
    spans = sorted(
        (max(0, c.start() - EXCERPT_AROUND), min(tail_start, c.end() + EXCERPT_AROUND))
        for c in cues
        if c.start() < tail_start
    )
    merged: list[tuple[int, int]] = []
    for a, b in spans:
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        elif b > a:
            merged.append((a, b))
    budget = EXCERPT_LIMIT - (len(txt) - tail_start) - 3
    head = "\n…\n".join(txt[a:b] for a, b in merged)[: max(0, budget)]
    return (head + "\n…\n" if head else "") + txt[tail_start:]


def is_division(name: str) -> bool:
    """과 단위 이름인가. 팀·계·담당이 붙었거나 부서 꼴이 아니면 거짓."""
    m = DEPT.fullmatch(name)
    return m is not None and m.group(2) is None


def verify_answer(text: str, answer: DeptAnswer) -> bool:
    """근거 문장이 원문에 글자 그대로 있고, 그 안에 부서명이 있고, 계약 계열이 아니면 참.

    공백과 줄바꿈은 빼고 비교한다 — PDF 추출본은 줄을 아무 데서나 끊는다.
    """
    if not answer.exec_dept or not answer.quote:
        return False
    dept, quote = squash(answer.exec_dept), squash(answer.quote)
    if len(quote) < MIN_QUOTE or quote not in squash(text) or dept not in quote:
        return False
    return is_division(dept) and not EXCL.match(dept)
