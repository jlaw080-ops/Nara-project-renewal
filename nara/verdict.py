"""진행현황 판정 규칙. I/O가 없어야 테스트가 네트워크를 타지 않는다."""

from dataclasses import dataclass

BEFORE = "착공 전(설계 단계)"
BUILDING = "시공 중"
DONE = "준공 완료"
UNKNOWN = "미확인"

# 공사 단계의 순서. 미확인은 여기 없다 — 단계가 아니라 '모른다'는 말이라
# 앞뒤를 잴 수 없다. 그 경우는 아래 미확인 가드가 따로 맡는다.
_STAGES = (BEFORE, BUILDING, DONE)


def _stage(verdict: str) -> int | None:
    """단계 번호. 미확인이거나 모르는 문자열(오타 등)이면 None."""
    return _STAGES.index(verdict) if verdict in _STAGES else None


@dataclass(frozen=True)
class Judgment:
    verdict: str
    reason: str
    decided_by: str  # 'rule' | 'news' | 'llm' | 'human' | 'imported'
    evidence_url: str


def should_record(latest: dict | None, candidate: Judgment) -> tuple[bool, str]:
    """이 판정을 status_check에 쌓을지 정한다. (기록할지, 안 하는 이유).

    status_check는 이력이고 화면은 최신 행만 본다. 그래서 '기록하지 않는다'는
    선택이 곧 '앞선 판정을 그대로 둔다'는 뜻이다.
    """
    if latest is None:
        return True, ""

    if latest.get("verdict") == candidate.verdict and latest.get("reason") == candidate.reason:
        return False, "판정과 사유가 그대로다 — 회차마다 같은 줄을 쌓지 않는다"

    # 앞선 판정이 규칙이 아니면 — 사람이든 이관이든 뉴스든 LLM이든, 또는
    # 모르는 값(오타·대소문자 등)이든 — 규칙 판정은 그것을 밀어내지 못한다.
    # 규칙 판정은 DB 사실로 내리는 것이라 뉴스 근거를 가질 일이 없다.
    # evidence_url 유무로 여는 조건은 두지 않는다 — 그 조건이 우회로였다(F2).
    if candidate.decided_by == "rule" and latest.get("decided_by") != "rule":
        return False, (
            f"근거를 보고 내린 '{latest.get('verdict')}' 판정을 규칙 판정으로 밀어내지 않는다"
        )

    # 미확인은 이미 있는 판정을 덮지 않는다 — 위 규칙 판정 가드와 달리
    # decided_by를 가리지 않는다. '모른다'는 '안다'보다 정보가 적어서,
    # 누가 내렸든 미확인이 알려진 판정 위에 쌓이면 순손실이다. 대표 사례:
    # judge_project가 needs_llm=True인데 LLM이 응답하지 않아
    # decided_by="news"·verdict=미확인을 돌려주는 경우 — 뉴스 한 건이
    # 애매하다는 이유로 이관된 '시공 중'이 화면에서 사라져선 안 된다.
    if candidate.verdict == UNKNOWN and latest.get("verdict") != UNKNOWN:
        return False, (f"'{latest.get('verdict')}' 판정이 있는데 '미확인'은 그것을 밀어내지 않는다")

    # 공사는 거꾸로 가지 않는다. 착공 전 → 시공 중 → 준공 완료는 한
    # 방향이라, 뒤로 가는 판정은 세상이 변한 게 아니라 기계가 틀린 것이다.
    # decided_by를 가리지 않는다 — 누가 내렸든 후퇴는 후퇴다. 앞의 두
    # 가드보다 뒤에 두는 이유: 셋 다 False만 돌려주므로 순서는 판단이
    # 아니라 사유 문구만 바꾼다. 더 좁고 구체적인 앞의 두 가드가 먼저
    # 제 문구로 답하게 두고, 이 가드는 그 둘이 안 잡은 후퇴만 받는다.
    # 틀렸을 때의 대가: 사람이 잘못 넣은 앞 단계 판정이 뉴스로 교정되지
    # 않는다 — doctor가 계속 잡고, 사람이 고칠 수 있다.
    was, now = _stage(latest.get("verdict", "")), _stage(candidate.verdict)
    if was is not None and now is not None and now < was:
        return False, (
            f"'{latest.get('verdict')}'에서 '{candidate.verdict}'로는 되돌아가지 않는다 "
            f"— 공사는 거꾸로 가지 않는다"
        )

    return True, ""


def date_conflict(verdict: str, project_dates: tuple[str, str], today: str) -> str | None:
    """판정과 사람이 넣은 날짜가 어긋나면 그 사실만 문장으로 돌려준다.

    **날짜를 고치지 않는다.** 시트 값은 사용자가 넣은 자료이고, 어느 쪽이
    맞는지는 담당부서에 물어야 안다.
    """
    start, end = project_dates
    if verdict == BEFORE and start and start <= today:
        return f"시트 착공일 {start}이 지났는데 판정은 착공 전 — 확인 필요"
    if verdict == DONE and end and end > today:
        return f"시트 준공일 {end}이 아직인데 판정은 준공 완료 — 확인 필요"
    return None


def demote_premature_completion(
    verdict: str, project_dates: tuple[str, str], today: str
) -> tuple[str, str | None]:
    """준공예정일이 아직인데 '준공 완료'라고 하면 판정하지 않는다.

    스펙의 도메인 사실은 '준공예정일 경과 ≠ 준공'이다. 그 반대는 더
    이상하다 — 예정일이 2년 남은 사업을 기사 한 건으로 준공이라 할 수는
    없다. 대개 같은 이름의 다른 시설이거나 다른 공정의 준공이다.

    이걸 막아야 하는 이유가 하나 더 있다. '준공 완료'는 마지막 단계라
    후퇴 금지 가드 때문에 한번 찍히면 어떤 뉴스로도 되돌아오지 않는다.
    틀린 채로 영구히 남는다.

    미확인으로 내린다 — 미확인은 이미 있는 판정을 덮지 않으므로 사람이
    확인해 둔 판정이 그대로 지켜진다.
    """
    _, end = project_dates
    if verdict == DONE and end and end > today:
        return UNKNOWN, f"시트 준공일 {end}이 아직이라 준공 보도를 그대로 받지 않음"
    return verdict, None


@dataclass(frozen=True)
class Facts:
    """공고에서 바로 읽히는 사실만 담는다. 추정한 값은 넣지 않는다."""

    has_winner: bool
    open_date: str  # ISO 또는 ""
    today: str  # ISO


def rule_verdict(facts: Facts) -> tuple[str, str]:
    """(판정, 근거). 규칙은 '착공 전'과 '미확인'까지만 말한다.

    '시공 중'·'준공 완료'는 보도 근거가 있어야 내릴 수 있는 판정이라
    여기서는 절대 나오지 않는다.
    """
    if facts.has_winner:
        return BEFORE, "낙찰업체가 기록됨 — 설계 단계"
    if facts.open_date and facts.open_date <= facts.today:
        return BEFORE, "개찰일이 지났고 낙찰업체 미확인 — 설계 단계"
    if facts.open_date:
        return UNKNOWN, f"개찰 전(개찰 예정 {facts.open_date})"
    return UNKNOWN, "개찰일 없음"


SIGNAL_START = "착공"
SIGNAL_DONE = "준공"
SIGNAL_DESIGN = "설계"
SIGNAL_DEMOLITION = "철거"
SIGNAL_PLANNED = "예정"
SIGNAL_HEDGE = "유보"

# "해체"는 위원회 해체처럼 철거가 아닌 문맥도 잡아서 뺐다. 철거·멸실만 남긴다.
_DEMOLITION_WORDS = ("철거", "멸실")
_START_WORDS = ("착공", "기공식", "첫 삽", "공사 착수")
_DONE_WORDS = ("준공", "개관", "준공식", "운영 개시", "개원")
# "낙찰"은 설계 낙찰과 시공사 낙찰을 구분 못 해 뺐다.
# 설계 낙찰 여부는 award 테이블로 이미 안다(rule_verdict).
# "실시설계"·"기본설계"는 "설계"의 부분 문자열이라 이미 잡힌다.
_DESIGN_WORDS = ("설계", "공모", "당선작")
_PLANNED_WORDS = ("예정", "목표", "계획", "추진")
# 취소·지연·임박·재촉 표현. "예정"과는 뜻이 다르다 — 예정은 미래 일정 표기이고,
# 이건 확정된 줄 알았던 착공·준공이 실제로는 엎어졌거나 미뤄졌을 가능성이다(R9/F1).
# "요구"·"건의"는 뺐다(R13/F4) — 너무 흔해 "주민 요구 수용해 설계 변경 뒤 기공식"
# 같은 멀쩡한 기사까지 위임시킨다. "촉구"가 주장·요구 계열 신호를 이미 잡는다.
# "중단"은 남긴다 — "공사 중단 없이 준공"처럼 부정형으로 쓰이는 경우가 위임되는
# 것은 감수한다. 안전한 방향으로 실패하는 쪽이 낫다. 부정어 처리는 넣지 않는다.
_HEDGE_WORDS = (
    "취소",
    "무산",
    "백지화",
    "철회",
    "보류",
    "연기",
    "지연",
    "중단",
    "중지",
    "반려",
    "불발",
    "앞두고",
    "임박",
    "촉구",
)


@dataclass(frozen=True)
class Article:
    title: str
    body: str
    url: str
    published: str  # ISO 또는 ""


def read_signals(article: Article) -> frozenset[str]:
    """기사에서 판정 재료만 뽑는다. 여기서 판정하지 않는다.

    철거와 착공 낱말이 함께 있으면(철거 마치고 본공사 착공 등) 착공 신호를
    억누르지 않고 둘 다 세운다. 어느 한쪽으로 단정해 조용히 틀리는 것보다,
    다음 단계가 애매하다고 보고 미확인으로 보류하는 편이 낫다.
    """
    text = f"{article.title} {article.body}"
    found: set[str] = set()
    if any(w in text for w in _DEMOLITION_WORDS):
        found.add(SIGNAL_DEMOLITION)
    if any(w in text for w in _START_WORDS):
        found.add(SIGNAL_START)
    if any(w in text for w in _DONE_WORDS):
        found.add(SIGNAL_DONE)
    if any(w in text for w in _DESIGN_WORDS):
        found.add(SIGNAL_DESIGN)
    if any(w in text for w in _PLANNED_WORDS):
        found.add(SIGNAL_PLANNED)
    if any(w in text for w in _HEDGE_WORDS):
        found.add(SIGNAL_HEDGE)
    return frozenset(found)


_STRONG = (BUILDING, DONE)


def demote_without_evidence(verdict: str, evidence_url: str | None) -> tuple[str, str | None]:
    """근거 URL 없는 '시공 중'·'준공 완료'는 '착공 전'으로 내린다.

    (판정, 강등 메모). 강등하지 않았으면 메모는 None이다.
    """
    if verdict in _STRONG and not (evidence_url or "").strip():
        return BEFORE, f"근거 URL이 없어 '{verdict}' 주장을 착공 전으로 내림"
    return verdict, None


_YEAR_GAP = 3  # 기사 연도가 사업 일정에서 이만큼 벗어나면 같은 사업인지 의심한다


@dataclass(frozen=True)
class NewsRead:
    verdict: str
    reason: str
    evidence_url: str
    needs_llm: bool
    llm_reason: str


def _year(iso: str) -> int | None:
    head = (iso or "")[:4]
    return int(head) if head.isdigit() else None


def _far_from(published: str, dates: tuple[str, str], open_date: str) -> bool:
    """개찰일은 사업 날짜가 하나도 없을 때만 쓰는 **대체** 기준점이다.

    사업 날짜가 하나라도 있으면 그쪽이 공사 일정에 직접 붙은 값이라 더
    가깝다. 개찰일을 언제나 함께 세면 min() 때문에 허용 폭이 넓어져,
    지금 걸러내고 있는 기사까지 통과시킨다 — 기존 동작이 조용히 느슨해진다.
    """
    published_year = _year(published)
    if published_year is None:
        return False
    years = [y for y in (_year(dates[0]), _year(dates[1])) if y]
    if not years:
        years = [y for y in (_year(open_date),) if y]
    if not years:
        return False
    return min(abs(published_year - y) for y in years) > _YEAR_GAP


def _pick_with_evidence(group: list[Article]) -> Article:
    """근거 URL이 있는 기사를 먼저 고른다. 하나도 없으면 첫 기사를 돌려준다(F2/R10).

    'group[0]'만 보면, 그 뒤에 근거 URL이 멀쩡한 같은 판정 기사가 있어도
    URL 없는 첫 기사 때문에 착공 전으로 잘못 강등된다.
    """
    for article in group:
        if (article.url or "").strip():
            return article
    return group[0]


# 사업명에 흔히 붙는 일반 낱말. 이것만 겹치는 건 같은 사업이라는 근거가
# 못 된다 — '성남시 도서관'이 '성남시 체육관 건립사업 착공'에 걸린다.
_GENERIC_WORDS = (
    "건립사업",
    "건립공사",
    "건립",
    "조성사업",
    "조성",
    "구축사업",
    "구축",
    "신축공사",
    "신축",
    "증축",
    "리모델링공사",
    "리모델링",
    "보수",
    "정비",
    "확충",
    "사업",
    "공사",
)


def _key_words(name: str) -> list[str]:
    """사업명에서 그 사업을 가리키는 낱말만 남긴다.

    전부 일반 낱말이면 골라낼 것이 없으니 원래 낱말을 그대로 쓴다 —
    빈 목록을 돌려주면 모든 기사가 걸러진다.
    """
    words = [w for w in (name or "").split() if w]
    keys = [w for w in words if w not in _GENERIC_WORDS]
    return keys or words


def relevant_articles(articles: list[Article], project_name: str) -> list[Article]:
    """그 사업을 실제로 가리키는 기사만 남긴다.

    검색 엔진은 늘 뭔가를 돌려준다. 돌려받은 것을 그대로 믿으면 같은
    동네의 다른 건물이나 다른 지역의 옛 시설이 판정을 만든다 — 실측에서
    확신 판정 4건 중 2건이 그랬다.

    핵심 낱말 둘이 겹쳐야 한다. 핵심 낱말이 하나뿐인 사업명은 그 하나가
    겹쳐야 한다. 지자체명 하나만 겹치는 것으로는 모자란다.

    거르다 남는 게 없으면 뉴스가 아무 말도 못 한 것이 된다 — 호출부가
    규칙 판정을 그대로 두므로 근거 없는 판정이 나가지 않는다.
    """
    keys = _key_words(project_name)
    if not keys:
        return list(articles)
    need = 1 if len(keys) == 1 else 2

    kept = []
    for article in articles:
        text = f"{article.title} {article.body}"
        if sum(1 for k in keys if k in text) >= need:
            kept.append(article)
    return kept


def read_news(
    articles: list[Article], project_dates: tuple[str, str], open_date: str = ""
) -> NewsRead:
    """기사 묶음에서 판정을 읽는다. 애매하면 판정하지 않고 넘긴다.

    `open_date`는 공고 개찰일이다 — 사업의 착공일·준공일이 둘 다 비었을 때
    기사 연도를 견줄 대체 기준점으로 쓴다(C1). 기본값이 ""라 이 인자를 안
    넘기는 호출부의 동작은 그대로다.

    판정 순서(R5) — 철거+착공 충돌을 착공/준공 충돌보다 먼저 걸러낸다.
    read_signals가 철거와 착공 낱말이 함께 있는 기사에서 두 신호를 모두
    세우므로, 그런 기사를 착공 분기로 흘려보내면 확신에 찬 오판정이 된다.
    """
    if not articles:
        return NewsRead(UNKNOWN, "검색 결과 없음", "", False, "")

    for article in articles:
        if _far_from(article.published, project_dates, open_date):
            gap = f"기사 연도({article.published[:4]})가 사업 일정과 {_YEAR_GAP}년 넘게 어긋남"
            return NewsRead(UNKNOWN, "기사 연도가 사업 일정과 어긋남", article.url, True, gap)

    signals = [(a, read_signals(a)) for a in articles]

    for article, sig in signals:
        if SIGNAL_DEMOLITION in sig and SIGNAL_START in sig:
            return NewsRead(
                UNKNOWN,
                "철거 기사와 착공 기사를 구분할 수 없음",
                article.url,
                True,
                "철거와 착공이 한 기사에 함께 쓰여 실제 착공인지 불분명",
            )

    starts = [(a, s) for a, s in signals if SIGNAL_START in s]
    dones = [(a, s) for a, s in signals if SIGNAL_DONE in s]

    if starts and dones:
        return NewsRead(
            UNKNOWN,
            "착공 기사와 준공 기사가 함께 잡힘",
            dones[0][0].url,
            True,
            "착공 기사와 준공 기사가 동시에 잡힘",
        )

    for group, strong, label in ((dones, DONE, "준공"), (starts, BUILDING, "착공·기공식")):
        if not group:
            continue
        # 유보·예정 검사는 묶음 전체에 건다(F3/R12). 고른 기사 하나의 URL만
        # 보면, 같은 묶음 안에 "착공 무산" 기사가 섞여 있어도 URL 있는 다른
        # 기사 때문에 그 유보 신호가 통째로 사라져 확신에 찬 오판정이 된다.
        cues = []
        if any(SIGNAL_PLANNED in s for _, s in group):
            cues.append("예정 표기")
        if any(SIGNAL_HEDGE in s for _, s in group):
            cues.append("유보·취소성 표현")
        article = _pick_with_evidence([a for a, _ in group])
        if cues:
            cue = " · ".join(cues)
            return NewsRead(
                UNKNOWN,
                f"{label} {cue}",
                article.url,
                True,
                f"{label} 기사 묶음에 {cue}이 함께 쓰여 실제인지 불분명",
            )
        verdict, note = demote_without_evidence(strong, article.url)
        return NewsRead(verdict, note or f"{label} 보도", article.url, False, "")

    for article, sig in signals:
        if SIGNAL_DEMOLITION in sig:
            return NewsRead(BEFORE, "철거 단계 — 본공사 착공 전", article.url, False, "")
    for article, sig in signals:
        if SIGNAL_DESIGN in sig:
            return NewsRead(BEFORE, "설계·공모 단계 보도", article.url, False, "")

    return NewsRead(UNKNOWN, "관련 신호 없음", "", False, "")
