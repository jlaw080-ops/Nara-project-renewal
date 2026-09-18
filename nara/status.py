"""진행현황 판정 파이프라인."""

import json
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
    read_news,
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

    found = search(secrets, f"{row['name']} 착공 준공")
    if found.searched:
        # articles가 비어도 read_news에 넘긴다 — 진짜 0건은 UNKNOWN·"검색
        # 결과 없음"으로 이미 처리된다(F1). 여기서 걸러내면 성공한 검색이
        # 실패한 검색보다 못한 취급을 받는다.
        news = read_news(found.articles, dates)
        if news.needs_llm:
            # 유보·충돌은 진짜 질문이다 — 미확인으로 내려가는 것이 정직한
            # 답이다. LLM이 답을 못 하면 이 뉴스 판정을 그대로 둔다.
            verdict, reason, evidence_url, decided_by = (
                news.verdict,
                news.reason,
                news.evidence_url,
                "news",
            )
            answer = adjudicator(secrets, row["name"], found.articles, news.llm_reason)
            if answer is not None:
                verdict, reason = answer
                decided_by = "llm"
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
            reason = f"{reason} (뉴스: {news.reason})"
    elif found.note:
        # 검색을 안 했거나 실패했다는 사실을 근거에 남긴다. 조용히 넘어가지 않는다.
        reason = f"{reason} ({found.note})"

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
        self.llm_called = False
        self.llm_unanswered = False

    def search(self, *args, **kwargs) -> SearchResult:
        result = self._search(*args, **kwargs)
        # found.searched로 판단한다 — 이 콜백은 judge_project가 매 사업마다
        # 무조건 부르므로, '불렸는가'가 아니라 '실제로 검색이 실행됐는가'를
        # 봐야 한다(키가 없어 건너뛴 경우와 구분).
        if result.searched:
            self.searched = True
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
