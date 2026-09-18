"""진행현황 판정 파이프라인."""

import sqlite3
from collections.abc import Callable

from nara.config import Secrets
from nara.naver import SearchResult
from nara.verdict import UNKNOWN, Facts, Judgment, date_conflict, read_news, rule_verdict


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
