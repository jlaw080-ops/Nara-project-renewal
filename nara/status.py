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
    open_date = (
        conn.execute(
            "SELECT MAX(open_date) FROM notice WHERE project_id = ?", (row["id"],)
        ).fetchone()[0]
        or ""
    )
    dates = (row["start_date"] or "", row["end_date"] or "")

    verdict, reason = rule_verdict(Facts(has_winner=has_winner, open_date=open_date, today=today))
    decided_by, evidence_url = "rule", ""

    found = search(secrets, f"{row['name']} 착공 준공")
    if found.searched and found.articles:
        news = read_news(found.articles, dates)
        verdict = news.verdict
        reason = news.reason
        evidence_url = news.evidence_url
        decided_by = "news"
        if news.needs_llm:
            answer = adjudicator(secrets, row["name"], found.articles, news.llm_reason)
            if answer is not None:
                verdict, reason = answer
                decided_by = "llm"
    elif not found.searched and found.note:
        # 검색을 안 했다는 사실을 근거에 남긴다. 조용히 넘어가지 않는다.
        reason = f"{reason} ({found.note})"

    conflict = date_conflict(verdict, dates, today)
    if not conflict and verdict == UNKNOWN:
        # date_conflict는 '착공 전'·'준공 완료' 주장과 시트 날짜가 어긋나는
        # 경우만 본다. 미확인은 주장 자체가 없어 그 함수로는 못 잡지만,
        # 시트 착공일·준공일이 이미 지났는데 근거가 하나도 없는 것 자체가
        # 확인이 필요한 신호다. 조용히 넘어가지 않는다.
        start, end = dates
        if start and start <= today:
            conflict = f"시트 착공일 {start}이 지났는데 근거가 없어 미확인 — 확인 필요"
        elif end and end <= today:
            conflict = f"시트 준공일 {end}이 지났는데 근거가 없어 미확인 — 확인 필요"
    if conflict:
        reason = f"{reason} / {conflict}"

    return Judgment(
        verdict=verdict, reason=reason, decided_by=decided_by, evidence_url=evidence_url
    )
