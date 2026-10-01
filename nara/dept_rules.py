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
# 부서처럼 보이지만 아닌 것들 (시설명·법령·기관명). '조달'은 조달청·전자 조달센터·
# 정부조달콜센터 — 서울 공고문 공통 문의처 문구다(2026-10-01).
BAD = re.compile(
    r"국가법령정보센터|조달|나라장터|지방자치단|개찰|열람장소|기술사사무소"
    r"|소방시설|정보센터|본점소|건축사사무소|엔지니어링|전시실|회의실|사무실"
    r"|민원실|교실|도서관|숙소|화장실|창고|기계실|전기실|단련실|프로그램실|자료실|장소"
    r"|접견실|신고센터|영업소|매표소|상황실|조리실|치료실"
)
# 조사 '과'(=and)가 붙어 부서명처럼 보이는 것들. "이 사업과 관련된" → 가짜 부서 "사업과"
JOSA = re.compile(
    r"^(사업|다음|역할|향상|방안|제반|기관|수단|입찰|군민|방문객|성찰|업무|계획|내용"
    r"|목적|결과|기준|조건|자격|서류|절차|방법|현황|발주기관|수급인|계약상대자|관계기관)과$"
)
# 부서처럼 끝나는 보통 낱말. "심사 평가결과에"를 부서 "평가결과"로 읽으면 안 된다.
# '~사항과'·'~입찰금액과' 같은 '명사+과'는 조사 결합이다: "위반사항과 추가", "입찰금액과
# 산출내역서", "학식과 경험"(2026-10-01 서울 검토 후보 사례).
WORD_END = re.compile(
    r"(결과|효과|성과|통과|초과|경과|부과|취소|사실|요소|명단|한국"
    r"|사항과|수행과|금액과|능력과|수량과|법령과|법과|규정과|기준과|내역과|여건과|방법과"
    r"|내용과|위원과|주민과|감독관과|감독원과|감독과|발주청과|프로그램과|학식과|존엄과"
    r"|성실과|절약과|갖춤과|재질과|제출과|집행과|품질과|공정과|심사평과|연구진과|영문과|군과)$"
)
# 앞에 지시관형사가 오면 조사 결합이다: "이 사업과", "본 사업과", "동 용역과".
# 지시어가 따로 선 낱말일 때만이다 — "다음과 같이 건축과"의 "같이"를 "이"로 읽으면 안 된다.
DEICTIC = re.compile(r"(?:^|[^가-힣])(이|본|동|해당|당해|위)\s*$")
# '설계과정'·'설계과업'·'설계과오'의 '설계과', '특정단체'·'재배단지'의 '특정단'·'재배단',
# '수행실적'·'유산실측'·'개발실태'의 '~실', '노임단가'·'국제단위'의 '~단', '중소기업'의
# '중소'처럼 긴 낱말의 앞부분을 떼어 내지 않는다. '건축과에서'·'도시계획과장'은 그대로 부서다.
# 앞에 붙은 숫자는 이름에 넣는다 — '100세행복과'를 '세행복과'로 자르면 안 된다.
DEPT = re.compile(
    r"(\d*[가-힣]{2,12}"
    r"(?:과(?!정|업|오)|국|실(?!적|측|태)|단(?!체|지|가|위)|소(?!기업)|센터|본부|사업소|담당관))"
    r"(\s*([가-힣]{2,10}(?:팀|계|담당)))?"
)
# 실행부서를 가리키는 신호어. 문의처·담당 신호어 근처에서 찾은 부서만 자동 확정한다.
# 본문 속 일반 신호어("본 사업 관련 홍보", "본 과업지시서는", "장소:")로 찾은 것은
# 후보일 뿐이다 — 2026-09-30 실데이터에서 시설명·장소명이 부서로 확정됐다.
CONTACT_CUE = re.compile(
    r"사업\s*담당|사업\s*부서|담당\s*부서|주관\s*부서|사업\s*관련\s*문의"
    r"|(?:과업|설계|용역)\s*(?:관련\s*)?문의|열람\s*문의|설계서\s*열람|용역에\s*관한"
    r"|문의\s*처|접수\s*처"
)
CONTEXT_CUE = re.compile(r"사업\s*관련|과업\s*(?:관련|지시서)|설계\s*관련|장\s*소\s*:")
CONTRACT_CUE = re.compile(r"계약\s*(?:관련|문의|에\s*관한)|입찰\s*(?:관련|문의|에\s*관한)")
_SPACED = re.compile(r"(?<![가-힣])((?:[가-힣] ){2,}[과국실소단])(?![가-힣])")
_WS = re.compile(r"\s+")
_SENTENCE_END = re.compile(r"다\.(?:\s|$)")  # "~한다. ", "~습니다. "
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
    near: bool  # 문의처·담당 신호어 바로 뒤(90자 안)에서 찾았는가


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
    if EXCL.match(name) or BAD.search(name) or WORD_END.search(name) or len(name) < 3:
        return False
    return not (JOSA.match(name) or DEICTIC.search(before))


def _cues(txt: str) -> list[tuple[int, int, bool]]:
    """(신호어 시작, 끝, 문의처·담당 신호어인가). 문의처 신호어와 겹치는 일반 신호어는 뺀다."""
    contact = [(m.start(), m.end()) for m in CONTACT_CUE.finditer(txt)]
    found = [(a, b, True) for a, b in contact]
    for m in CONTEXT_CUE.finditer(txt):
        if not any(a <= m.start() < b for a, b in contact):
            found.append((m.start(), m.end(), False))
    return sorted(found)


def find_candidates(text: str) -> list[Candidate]:
    txt = _clean(text)
    weights: Counter[str] = Counter()
    first: dict[str, tuple[str, bool]] = {}
    for start, cue_end, contact in _cues(txt):
        # 신호어 끝부터 본다. 탭이 사라져 '사업담당도시재생과'처럼 붙어도 신호어가
        # 이름에 들어가지 않는다. 줄바꿈은 한 칸으로 바꿔 글자 위치를 그대로 둔다.
        window = txt[cue_end : cue_end + WINDOW].replace("\n", " ")
        for m in DEPT.finditer(window):
            name = m.group(1)
            if not _is_candidate(name, window[: m.start()]):
                continue
            # 신호어와 같은 문장 안이어야 바로 뒤다 — "담당부서)와 협의하여 … 작성한다. 마. …
            # 서울시(지리정보담당관)"의 부서는 다음 문장의 말이다.
            gap = window[: m.start()]
            near = contact and m.start() < NEAR and not _SENTENCE_END.search(gap)
            weights[name] += 3 if near else 1
            end = max(start + 150, cue_end + m.end() + 20)
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
    """후보가 하나뿐이고 신호어 바로 뒤에서 찾았을 때만 확정한다.

    숫자로 시작하는 이름('100세행복과')은 전화번호가 붙은 것('2842건축과')과 가릴 수
    없어 확정하지 않는다 — 사람이 본다.
    """
    if len(candidates) == 1 and candidates[0].near and not candidates[0].name[0].isdigit():
        return candidates[0]
    return None


def excerpt_for_llm(text: str) -> str:
    """신호어 앞뒤 구간과 문서 끝. 끝부분은 잘리지 않게 남기고 앞쪽을 줄인다."""
    txt = _clean(text)
    tail_start = max(0, len(txt) - EXCERPT_TAIL)
    cues = [*CONTACT_CUE.finditer(txt), *CONTEXT_CUE.finditer(txt), *CONTRACT_CUE.finditer(txt)]
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


def _names_whole(quote: str, dept: str) -> bool:
    """근거 문장에 부서명이 온전한 낱말로 있는가. '도시건축과' 안의 '건축과'는 아니다."""
    pattern = r"(?<![가-힣])" + r"\s*".join(map(re.escape, dept))
    return re.search(pattern, quote) is not None


def verify_answer(text: str, answer: DeptAnswer) -> bool:
    """근거 문장이 원문에 글자 그대로 있고, 그 안에 부서명이 있고, 계약 계열이 아니면 참.

    공백과 줄바꿈은 빼고 비교한다 — PDF 추출본은 줄을 아무 데서나 끊는다.
    """
    if not answer.exec_dept or not answer.quote:
        return False
    dept, quote = squash(answer.exec_dept), squash(answer.quote)
    if len(quote) < MIN_QUOTE or quote not in squash(text):
        return False
    if not _names_whole(answer.quote, dept):
        return False
    return is_division(dept) and not EXCL.match(dept)
