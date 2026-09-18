"""데이터가 서로 맞는지 훑는다. 고치지는 않고 알리기만 한다."""

import sqlite3
from dataclasses import dataclass

from nara.verdict import BEFORE, BUILDING, DONE

# `nara enrich award --limit`의 기본값과 같아야 한다. 대기가 이 수를 넘으면
# 한 회차가 대기를 다 비우지 못한다.
AWARD_BATCH_LIMIT = 300

# 사업별 최신 판정 한 줄만 본다. status_check는 이력이라 다 보면 뒤집힌 옛
# 판정까지 잡혀 회차를 돌 때마다 경보가 쌓인다.
_LATEST_STATUS = (
    "SELECT s.project_id, s.verdict, s.evidence_json, p.name, p.start_date "
    "FROM status_check s JOIN project p ON p.id = s.project_id "
    "WHERE s.id = ("
    "  SELECT id FROM status_check WHERE project_id = s.project_id "
    "  ORDER BY checked_at DESC, id DESC LIMIT 1"
    ")"
)


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
            Finding(
                "개찰 전 낙찰",
                f"{row['bid_no']} — 개찰 {row['open_date']}인데 낙찰업체가 있다",
            )
        )

    for row in _rows(
        conn,
        "SELECT p.id, p.name FROM project p LEFT JOIN notice n ON n.project_id = p.id "
        "WHERE p.source = 'g2b' AND n.bid_no IS NULL",
    ):
        findings.append(Finding("공고 없는 g2b 사업", f"{row['id']} {row['name']}"))

    for row in _rows(conn, "SELECT name FROM org WHERE tier = 'rest' AND weekday_group IS NULL"):
        findings.append(Finding("요일 그룹 없는 비관심 기관", row["name"]))

    # 기관에 연결되지 않은 공고는 낙찰 대기 쿼리(org JOIN)에 영영 잡히지 않는다.
    # 아래 적체 점검도 같은 JOIN을 쓰므로, 먼저 여기서 걸러 내지 않으면 사각지대가 된다.
    for row in _rows(
        conn,
        "SELECT bid_no, title FROM notice WHERE org_id IS NULL",
    ):
        findings.append(
            Finding("기관 연결 없는 공고", f"{row['bid_no']} {row['title']} — 낙찰 조회에서 빠진다")
        )

    # 낙찰 대기는 성공해야만 줄어든다. 취소되거나 낙찰 공고가 안 뜬 건은 영영 대기에
    # 남아 한 회차 상한을 잡아먹고, 그런 건이 상한만큼 쌓이면 더 최근 공고는 매번
    # 뒤로 밀려 조회되지 않는다. 조용히 밀리므로 여기서 눈에 보이게 만든다.
    #
    # 실제 조회는 한 덩어리로 돌지 않는다 — 관심 기관은 하루 2회, 비관심 기관은
    # 요일 그룹별로 주 1회다(스펙의 스케줄). 그래서 전체를 합쳐 상한과 비교하면
    # 정상적인 주간 순환 대기까지 적체로 잡혀 헛경보가 된다. 실제로 도는 단위
    # (tier, weekday_group)별로 나눠 센다.
    for row in _rows(
        conn,
        "SELECT o.tier AS tier, o.weekday_group AS grp, COUNT(*) AS n, "
        "MIN(n.open_date) AS oldest "
        "FROM notice n JOIN org o ON o.id = n.org_id "
        "LEFT JOIN award a ON a.bid_no = n.bid_no "
        "WHERE a.bid_no IS NULL AND n.open_date != '' AND n.open_date <= ? "
        "GROUP BY o.tier, o.weekday_group",
        (today,),
    ):
        if row["n"] <= AWARD_BATCH_LIMIT:
            continue
        where = "관심 기관" if row["tier"] == "focus" else f"비관심 기관 요일그룹 {row['grp']}"
        findings.append(
            Finding(
                "낙찰 조회 적체",
                f"{where}: 개찰이 지났는데 낙찰 미확인인 공고가 {row['n']}건이다"
                f"(가장 오래된 개찰일 {row['oldest']}). 한 회차 상한"
                f" {AWARD_BATCH_LIMIT}건을 넘어 최근 공고가 계속 밀릴 수 있다."
                " `nara enrich award --limit`를 키워 한 번 비우거나, 낙찰이 영영"
                " 없을 건을 가려낼 방법이 필요하다.",
            )
        )

    for row in _rows(conn, _LATEST_STATUS):
        verdict = row["verdict"]
        start = row["start_date"] or ""

        # 판정이 '착공 전'이면 확정 착공일이 있을 수 없다. 낙찰일·심사일을 착공일
        # 칸에 적는 실수가 잦아 이 모순이 실제로 생긴다.
        if verdict == BEFORE and start and start <= today:
            findings.append(
                Finding(
                    "판정과 착공일 모순",
                    f"{row['name']} — 착공일 {start}이 지났는데 판정은 '{verdict}'",
                )
            )

        # 근거 URL 없는 강한 판정. 판정 경로가 강등하지만 이관분·수기 입력은
        # 그 경로를 타지 않아 여기서 잡아야 한다.
        if verdict in (BUILDING, DONE) and '"url": "http' not in (row["evidence_json"] or ""):
            findings.append(
                Finding("근거 없는 강한 판정", f"{row['name']} — 근거 URL 없이 '{verdict}'")
            )

    return findings
