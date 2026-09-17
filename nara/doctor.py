"""데이터가 서로 맞는지 훑는다. 고치지는 않고 알리기만 한다."""

import sqlite3
from dataclasses import dataclass


# `nara enrich award --limit`의 기본값과 같아야 한다. 대기가 이 수를 넘으면
# 한 회차가 대기를 다 비우지 못한다.
AWARD_BATCH_LIMIT = 300


@dataclass(frozen=True)
class Finding:
    check: str
    detail: str


def _rows(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    return list(conn.execute(sql, params))


def run_checks(conn: sqlite3.Connection, today: str) -> list[Finding]:
    findings: list[Finding] = []

    for row in _rows(
        conn,
        "SELECT a.bid_no, n.open_date FROM award a JOIN notice n ON n.bid_no = a.bid_no "
        "WHERE n.open_date > ?",
        (today,),
    ):
        findings.append(
            Finding("개찰 전 낙찰", f"{row['bid_no']} — 개찰 {row['open_date']}인데 낙찰업체가 있다")
        )

    for row in _rows(
        conn,
        "SELECT p.id, p.name FROM project p LEFT JOIN notice n ON n.project_id = p.id "
        "WHERE p.source = 'g2b' AND n.bid_no IS NULL",
    ):
        findings.append(Finding("공고 없는 g2b 사업", f"{row['id']} {row['name']}"))

    for row in _rows(
        conn, "SELECT name FROM org WHERE tier = 'rest' AND weekday_group IS NULL"
    ):
        findings.append(Finding("요일 그룹 없는 비관심 기관", row["name"]))

    # 낙찰 대기는 성공해야만 줄어든다. 취소되거나 낙찰 공고가 안 뜬 건은 영영 대기에
    # 남아 한 회차 상한을 잡아먹고, 그런 건이 상한만큼 쌓이면 더 최근 공고는 매번
    # 뒤로 밀려 조회되지 않는다. 조용히 밀리므로 여기서 눈에 보이게 만든다.
    backlog = conn.execute(
        "SELECT COUNT(*) AS n, MIN(n.open_date) AS oldest FROM notice n "
        "LEFT JOIN award a ON a.bid_no = n.bid_no "
        "WHERE a.bid_no IS NULL AND n.open_date != '' AND n.open_date <= ?",
        (today,),
    ).fetchone()
    if backlog["n"] > AWARD_BATCH_LIMIT:
        findings.append(
            Finding(
                "낙찰 조회 적체",
                f"개찰이 지났는데 낙찰 미확인인 공고가 {backlog['n']}건이다"
                f"(가장 오래된 개찰일 {backlog['oldest']}). 한 회차 상한"
                f" {AWARD_BATCH_LIMIT}건을 넘어 최근 공고가 계속 밀릴 수 있다."
                " `nara enrich award --limit`를 키워 한 번 비우거나, 낙찰이 영영"
                " 없을 건을 가려낼 방법이 필요하다.",
            )
        )

    return findings
