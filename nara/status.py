"""진행현황 판정 파이프라인."""

import sqlite3


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
