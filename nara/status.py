"""진행현황 판정 파이프라인."""

import json
import re
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from nara.config import Secrets
from nara.naver import SearchResult
from nara.runlog import RunCounters
from nara.verdict import (
    UNKNOWN,
    Facts,
    Judgment,
    date_conflict,
    demote_premature_completion,
    demote_without_evidence,
    read_news,
    relevant_articles,
    rule_verdict,
    should_record,
)

BUDGET_SECONDS = 1200  # 스펙의 기본 시간 예산 20분


def pending_status_projects(
    conn: sqlite3.Connection, tier: str | None, limit: int
) -> list[sqlite3.Row]:
    """오래 안 본 사업부터 돌려준다.

    한 번도 안 본 사업이 맨 앞이다. 낙찰 조회처럼 개찰일로 줄 세우면
    결과가 영영 없는 건이 앞을 막아 최근 사업이 뒤로 밀린다.
    """
    if limit < 1:
        raise ValueError(f"limit은 1 이상이어야 한다: {limit}")

    sql = [
        "SELECT p.id, p.name, p.start_date, p.end_date, o.name AS org_name,",
        "       MAX(s.checked_at) AS last_checked",
        "FROM project p",
        "JOIN org o ON o.id = p.org_id",
        "LEFT JOIN status_check s ON s.project_id = p.id",
    ]
    params: list[object] = []
    if tier:
        sql.append("WHERE o.tier = ?")
        params.append(tier)
    sql.append("GROUP BY p.id")
    # 한 번도 안 본 사업(NULL)이 맨 앞에 오게 한다.
    sql.append("ORDER BY last_checked IS NOT NULL, last_checked, p.id")
    sql.append("LIMIT ?")
    params.append(limit)
    return list(conn.execute("\n".join(sql), params))


# 사업명은 입찰 공고 제목 그대로라 조달 용어가 붙어 있다. 기사에는 그런
# 낱말이 없고, 검색은 낱말을 AND로 묶는다 — '설계의도구현'이 들어간 질의는
# 0건이 된다. 실측: 이관된 152건 중 109건이 이 꼬리를 달고 있었고, 떼자
# 0건이던 질의들이 그 사업의 착공 기사를 바로 물어 왔다.
_QUERY_MARKERS = (
    "설계",
    "용역",
    "공모",
    "공고",
    "입찰",
    "수의시담",
    "사업수행능력",
    "턴키",
    "기술제안",
    "적격심사",
)
# 마커에서 자르면 '기본 및 실시설계'가 '기본 및 실시'로 남는다. 꼬리에
# 남는 수식어를 마저 뗀다.
_QUERY_TAIL = ("기본", "및", "실시", "보완", "건축", "일괄", "기타", "변경", "추가")
# 머리에 붙은 '[수의시담]'에서 자르면 이름이 통째로 사라진다. 먼저 걷어낸다.
_QUERY_BRACKET = re.compile(r"^\s*[\[(（【][^\])）】]*[\])）】]\s*")


def news_query(name: str, org_name: str = "") -> str:
    """사업명에서 뉴스에 나올 리 없는 조달 용어를 떼고, 없으면 지자체를 붙인다.

    '장애인회관 건립사업' 같은 이름은 전국 어디에나 있다. 지자체가 빠지면
    산청군·김천시·충북도 기사가 전부 같은 사업으로 읽힌다(실측). 기관명의
    마지막 낱말(시·군·구)이 기사에 실제로 쓰이는 이름이다 — '경상남도
    산청군'이 아니라 '산청군'.

    잘라서 남는 게 너무 짧으면 원래 이름을 그대로 쓴다 — 아무 사업이나
    걸리는 질의를 만드는 것보다 0건이 낫다.
    """
    text = _QUERY_BRACKET.sub("", name or "").strip()
    cut = min((text.find(m) for m in _QUERY_MARKERS if m in text), default=-1)
    if cut > 0:
        text = text[:cut]
    parts = text.split()
    while parts and parts[-1] in _QUERY_TAIL:
        parts.pop()
    trimmed = " ".join(parts).strip(" ,-·") or (name or "").strip()
    if len(trimmed) < 4:
        trimmed = (name or "").strip()

    town = (org_name or "").split()[-1] if (org_name or "").split() else ""
    if town and town not in trimmed:
        trimmed = f"{town} {trimmed}".strip()
    return trimmed


def _project_open_date(conn: sqlite3.Connection, project_id: int, today: str) -> str:
    """개찰일 하나를 고른다 — 이미 지난 개찰 중 가장 최근 것을 우선한다.

    유찰 후 재공고가 흔한 도메인이라 MAX(open_date)로 고르면, 아직 열리지
    않은 재공고의 미래 개찰일에 가려 이미 지난 개찰(과 그 유찰 사실)이
    사라진다(R29). 지난 개찰이 하나도 없을 때만 가장 이른 미래 개찰로
    대체한다. 빈 open_date는 둘 다에서 무시한다.
    """
    past = conn.execute(
        "SELECT open_date FROM notice "
        "WHERE project_id = ? AND open_date != '' AND open_date <= ? "
        "ORDER BY open_date DESC LIMIT 1",
        (project_id, today),
    ).fetchone()
    if past:
        return past[0]
    future = conn.execute(
        "SELECT open_date FROM notice "
        "WHERE project_id = ? AND open_date != '' AND open_date > ? "
        "ORDER BY open_date ASC LIMIT 1",
        (project_id, today),
    ).fetchone()
    return future[0] if future else ""


def judge_project(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    secrets: Secrets,
    today: str,
    search: Callable[..., SearchResult],
    adjudicator: Callable[..., tuple[str, str] | None],
) -> Judgment:
    """한 사업의 진행현황을 판정한다. 규칙 → 뉴스 → LLM 순으로 내려간다.

    어느 단계도 못 가르면 미확인이다. 이 함수는 project 표를 읽기만 하고
    쓰지 않는다 — 사람이 넣은 착공일·준공일을 고치는 경로가 없어야 한다.
    """
    has_winner = bool(
        conn.execute(
            "SELECT 1 FROM notice n JOIN award a ON a.bid_no = n.bid_no "
            "WHERE n.project_id = ? AND COALESCE(a.winner, '') != '' LIMIT 1",
            (row["id"],),
        ).fetchone()
    )
    open_date = _project_open_date(conn, row["id"], today)
    dates = (row["start_date"] or "", row["end_date"] or "")

    verdict, reason = rule_verdict(Facts(has_winner=has_winner, open_date=open_date, today=today))
    decided_by, evidence_url = "rule", ""

    query = news_query(row["name"], row["org_name"])
    found = search(secrets, f"{query} 착공 준공")
    # 검색 엔진은 늘 뭔가를 돌려준다. 그 사업을 가리키지 않는 기사를 먼저
    # 걷어낸다 — LLM에게도 거른 뒤의 기사만 보인다. 안 그러면 같은 오판이
    # 한 단계 아래로 옮겨갈 뿐이다.
    articles = relevant_articles(found.articles, query)
    if found.searched:
        # articles가 비어도 read_news에 넘긴다 — 진짜 0건은 UNKNOWN·"검색
        # 결과 없음"으로 이미 처리된다(F1). 여기서 걸러내면 성공한 검색이
        # 실패한 검색보다 못한 취급을 받는다.
        # 개찰일도 함께 넘긴다 — 사업 날짜가 둘 다 빈 실데이터 196/249건에서
        # 기사 연도 가드가 기댈 유일한 기준점이다(C1). 규칙 판정에 쓰려고 이미
        # 손에 쥔 값이라 새로 읽는 질의가 늘지 않는다.
        news = read_news(articles, dates, open_date)
        if news.needs_llm:
            # 유보·충돌은 진짜 질문이다 — 미확인으로 내려가는 것이 정직한
            # 답이다. LLM이 답을 못 하면 이 뉴스 판정을 그대로 둔다.
            verdict, reason, evidence_url, decided_by = (
                news.verdict,
                news.reason,
                news.evidence_url,
                "news",
            )
            answer = adjudicator(secrets, row["name"], articles, news.llm_reason)
            if answer is not None:
                verdict, reason = answer
                decided_by = "llm"
                # LLM이 무엇을 의심한 건에 답한 것인지 기록에 남긴다. 연도
                # 가드가 걷어낸 기사의 URL은 evidence_url에 그대로 남아
                # 강등도 걸리지 않는데, reason까지 통째로 갈리면 왜 이
                # 판정이 나왔는지 알 길이 없다 — 같은 오판이 'llm' 이름표를
                # 달고 되돌아온다.
                reason = f"{reason} / {news.reason}"
                # 뉴스 경로와 같은 강등을 LLM 답에도 건다(C2). LLM은
                # evidence_url을 만들어 내지 못하고, 여기서 남는 것은 뉴스가
                # 고른 URL이다 — 그게 비어 있으면 '준공 완료'·'시공 중'은
                # 근거 없는 주장이다. 뉴스에는 걸고 LLM에는 안 거는 비대칭이
                # 곧 근거 없는 확신이 화면에 닿는 구멍이었다.
                verdict, note = demote_without_evidence(verdict, evidence_url)
                if note:
                    reason = f"{reason} / {note}"
        elif news.verdict != UNKNOWN:
            verdict, reason, evidence_url, decided_by = (
                news.verdict,
                news.reason,
                news.evidence_url,
                "news",
            )
        else:
            # 뉴스가 아무 말도 못 했다(관련 기사 없음 또는 진짜 0건) — DB가
            # 이미 아는 사실(규칙 판정)을 지우지 않는다(F2). 뉴스를
            # 확인했다는 사실만 사유에 남긴다.
            #
            # 기사를 받았는데 전부 걸러냈으면 '검색 결과 없음'이 아니다.
            # 그렇게 적으면 검색이 헛돌았는지 그 사업 기사가 없었는지
            # 구분이 안 된다 — 걸러냈다는 사실을 적는다.
            #
            # 걸러낸 건수는 적지 않는다. 구글이 회차마다 다른 건수를
            # 돌려줘 사유가 흔들리고, should_record가 그걸 '달라진 판정'으로
            # 보아 같은 말을 하는 줄이 계속 쌓인다(실측: 2회차에 1건).
            dropped = len(found.articles) > len(articles) == 0
            note = "그 사업을 가리키는 기사 없음" if dropped else news.reason
            reason = f"{reason} (뉴스: {note})"
    elif found.note:
        # 검색을 안 했거나 실패했다는 사실을 근거에 남긴다. 조용히 넘어가지 않는다.
        reason = f"{reason} ({found.note})"

    # 준공예정일이 아직인데 준공 보도가 왔으면 기계가 가릴 일이 아니다.
    # '준공 완료'는 마지막 단계라 후퇴 금지 가드 때문에 한번 찍히면
    # 되돌아오지 않는다 — 틀린 채로 영구히 남는다.
    verdict, premature = demote_premature_completion(verdict, dates, today)
    if premature:
        reason = f"{reason} / {premature}"

    conflict = date_conflict(verdict, dates, today)
    if conflict:
        reason = f"{reason} / {conflict}"

    return Judgment(
        verdict=verdict, reason=reason, decided_by=decided_by, evidence_url=evidence_url
    )


@dataclass
class StatusRun:
    checked: int = 0
    recorded: int = 0
    skipped: int = 0
    searched: int = 0
    search_failed: int = 0
    asked_llm: int = 0
    llm_unanswered: int = 0
    stopped_early: bool = False


class _CallTracker:
    """search·adjudicator가 실제로 불렸는지 셈한다(R31).

    judge_project는 규칙 → 뉴스 → LLM 순으로 내려가며 필요할 때만 이
    콜백을 부른다. run_log는 이 무인 시스템이 실제로 한 일에 대한 유일한
    사후 기록이라, '판정이 바뀌었을 때'가 아니라 '실제로 호출됐을 때'를
    세야 한다 — 그래야 검색·LLM 호출 건수가 실제 호출 횟수와 어긋나지
    않는다.
    """

    def __init__(
        self,
        search: Callable[..., SearchResult],
        adjudicator: Callable[..., tuple[str, str] | None],
    ) -> None:
        self._search = search
        self._adjudicator = adjudicator
        self.searched = False
        self.search_failed = False
        self.llm_called = False
        self.llm_unanswered = False

    def search(self, *args, **kwargs) -> SearchResult:
        result = self._search(*args, **kwargs)
        # found.searched로 판단한다 — 이 콜백은 judge_project가 매 사업마다
        # 무조건 부르므로, '불렸는가'가 아니라 '실제로 검색이 실행됐는가'를
        # 봐야 한다(키가 없어 건너뛴 경우와 구분).
        if result.searched:
            self.searched = True
        # 실패는 따로 센다 — 이 값이 없으면 실패 흔적이 reason 문자열
        # 조각으로만 남아 무인 실행에서 아무도 못 본다(I1).
        if result.failed:
            self.search_failed = True
        return result

    def adjudicator(self, *args, **kwargs) -> tuple[str, str] | None:
        self.llm_called = True
        answer = self._adjudicator(*args, **kwargs)
        if answer is None:
            self.llm_unanswered = True
        return answer


def _latest(conn: sqlite3.Connection, project_id: int) -> dict | None:
    """should_record가 비교할 수 있게 dict로 돌려준다.

    sqlite3.Row에는 .get()이 없다 — should_record는 .get()으로 판정과
    사유를 함께 비교하므로, Row를 그대로 넘기면 첫 실행에서
    AttributeError로 죽는다(R18).
    """
    row = conn.execute(
        "SELECT verdict, reason, decided_by, evidence_json FROM status_check "
        "WHERE project_id = ? ORDER BY checked_at DESC, id DESC LIMIT 1",
        (project_id,),
    ).fetchone()
    return dict(row) if row is not None else None


def update_statuses(
    conn: sqlite3.Connection,
    secrets: Secrets,
    today: str,
    tier: str | None,
    limit: int,
    counters: RunCounters,
    search: Callable[..., SearchResult],
    adjudicator: Callable[..., tuple[str, str] | None],
    budget_seconds: int = BUDGET_SECONDS,
    now_fn: Callable[[], float] = time.monotonic,
) -> StatusRun:
    """대상을 돌며 판정하고 달라진 것만 쌓는다.

    시간 예산을 넘기면 처리한 만큼 저장하고 멈춘다 — 다음 회차가 남은
    대상을 이어받는다. 행마다 커밋해 중간에 터져도 거기까지는 남는다.
    사업 한 건이 죽어도(R30) 나머지는 계속 본다 — 그 건은 checked_at이
    안 남으므로 '오래 안 본 사업부터' 정렬 덕에 다음 회차 맨 앞에서
    다시 시도된다.
    """
    rows = pending_status_projects(conn, tier, limit)
    run = StatusRun()
    started = now_fn()

    for row in rows:
        if now_fn() - started > budget_seconds:
            run.stopped_early = True
            break

        counters.processed += 1
        run.checked += 1
        tracker = _CallTracker(search, adjudicator)
        try:
            judgment = judge_project(conn, row, secrets, today, tracker.search, tracker.adjudicator)
        except sqlite3.Error:
            # award.py의 실패 하나하나는 독립된 네트워크 호출이지만, 여기는
            # 모든 사업이 같은 conn을 공유한다. sqlite3.Error는 DB 파일
            # 잠김·손상처럼 저장 계층 전체가 망가졌다는 신호라 개별 사업
            # 실패로 세지 않고 그대로 터뜨린다(R33) — 그래야 run_log가
            # 'partial'이 아니라 'error'로 정직하게 남는다.
            raise
        except Exception:
            # nara/award.py의 update_awards와 같은 모양이다 — 한 건이
            # 터져도 나머지 대기 건을 계속 본다. KeyboardInterrupt·
            # SystemExit은 Exception이 아니라 여기서 삼켜지지 않는다.
            counters.failed += 1
            continue

        if tracker.searched:
            run.searched += 1
        if tracker.search_failed:
            run.search_failed += 1
        if tracker.llm_called:
            run.asked_llm += 1
            if tracker.llm_unanswered:
                run.llm_unanswered += 1

        ok, _ = should_record(_latest(conn, row["id"]), judgment)
        if not ok:
            run.skipped += 1
            continue

        conn.execute(
            "INSERT INTO status_check (project_id, verdict, reason, decided_by, "
            "evidence_json, checked_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                row["id"],
                judgment.verdict,
                judgment.reason,
                judgment.decided_by,
                json.dumps({"url": judgment.evidence_url}, ensure_ascii=False),
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        # 행마다 커밋한다 — 중간에 터져도 거기까지는 남는다.
        conn.commit()
        run.recorded += 1
        counters.updated += 1

    return run
