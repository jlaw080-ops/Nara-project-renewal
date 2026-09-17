"""기존 구글시트 탭을 DB로 옮긴다."""

import sqlite3
from dataclasses import dataclass, field

from nara.config import Settings
from nara.dates import to_iso_date
from nara.energy import parse_energy_plan
from nara.runlog import RunCounters
from nara.sheets_tsv import read_tsv
from nara.store import ensure_project, upsert_org

_VERDICTS = ("준공 완료", "시공 중", "착공 전(설계 단계)", "미확인")

SKIPPED_PREVIEW_MAX = 10

# 논리 이름 → 시트 헤더 문자열. 탭의 헤더가 다르면 여기만 고친다.
COLUMNS = {
    "org": "수요기관",
    "title": "공고명",
    "address": "주소",
    "start_date": "착공일",
    "end_date": "준공(예정)일",
    "dept": "담당부서",
    "winner": "낙찰업체 설계사무소",
    "budget": "예정공사비",
    "status": "진행현황",
    "energy": "설치계획내용",
    "bid_no": "공고번호",
    "open_date": "낙찰일(개찰일)",
    "zeb": "ZEB 인증등급",
}


@dataclass
class ImportStats:
    rows: int = 0
    imported: int = 0
    notices: int = 0
    projects: int = 0
    energy: int = 0
    status: int = 0
    dept: int = 0
    skipped: int = 0
    skipped_with_data: list[str] = field(default_factory=list)


def _split_status(text: str) -> tuple[str, str]:
    """'시공 중 - 2026.08.28 기공식' → ('시공 중', '2026.08.28 기공식')"""
    s = (text or "").strip()
    if not s:
        return "", ""
    head, _, tail = s.partition(" - ")
    for verdict in _VERDICTS:
        if head.strip().startswith(verdict):
            return verdict, tail.strip()
    return "미확인", s


def import_tab(
    conn: sqlite3.Connection,
    tab_name: str,
    text: str,
    settings: Settings,
    now: str,
    counters: RunCounters | None = None,
) -> ImportStats:
    header, rows = read_tsv(text)
    index = {name.strip(): i for i, name in enumerate(header) if name.strip()}
    stats = ImportStats(rows=len(rows))

    def cell(row: list[str], key: str) -> str:
        i = index.get(COLUMNS[key])
        return row[i].strip() if i is not None and i < len(row) else ""

    for row in rows:
        # 행마다 올려 둔다. 중간에 터져도 run_log에 어디까지 갔는지 남는다.
        if counters is not None:
            counters.processed += 1

        org_name = cell(row, "org")
        title = cell(row, "title")
        if not org_name or not title:
            stats.skipped += 1
            # 내용이 있는데 필수 칸만 빈 행은 조용히 사라지면 안 된다.
            filled = [v.strip() for v in row if v.strip()]
            if filled and len(stats.skipped_with_data) < SKIPPED_PREVIEW_MAX:
                stats.skipped_with_data.append(" | ".join(filled)[:120])
            continue
        stats.imported += 1

        org_id = upsert_org(conn, org_name, settings, now)
        bid_no = cell(row, "bid_no")
        source = "g2b" if bid_no else "manual"
        existed = conn.execute(
            "SELECT 1 FROM project WHERE org_id = ? AND name = ?", (org_id, title)
        ).fetchone()
        project_id = ensure_project(conn, org_id, title, source, now)
        if source == "manual" and not existed:
            stats.projects += 1

        conn.execute(
            "UPDATE project SET address = COALESCE(NULLIF(?, ''), address), "
            "start_date = COALESCE(NULLIF(?, ''), start_date), "
            "end_date = COALESCE(NULLIF(?, ''), end_date), "
            "zeb_grade = COALESCE(NULLIF(?, ''), zeb_grade), updated_at = ? WHERE id = ?",
            (
                cell(row, "address"),
                to_iso_date(cell(row, "start_date")),
                to_iso_date(cell(row, "end_date")),
                cell(row, "zeb"),
                now,
                project_id,
            ),
        )

        if bid_no:
            existing = conn.execute(
                "SELECT 1 FROM notice WHERE bid_no = ?", (bid_no,)
            ).fetchone()
            if not existing:
                # open_date를 넣지 않으면 이 공고는 Task 10의 낙찰 대기 쿼리
                # (open_date != '' AND open_date <= today)에 영영 들어오지 못한다.
                conn.execute(
                    "INSERT INTO notice (bid_no, project_id, org_id, org_name, title, "
                    "open_date, budget_basis, collected_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (bid_no, project_id, org_id, org_name, title,
                     to_iso_date(cell(row, "open_date")), cell(row, "budget"), now),
                )
                stats.notices += 1
            if winner := cell(row, "winner"):
                conn.execute(
                    "INSERT OR IGNORE INTO award (bid_no, winner, checked_at) VALUES (?, ?, ?)",
                    (bid_no, winner, now),
                )

        verdict, reason = _split_status(cell(row, "status"))
        if verdict and not conn.execute(
            "SELECT 1 FROM status_check WHERE project_id = ? AND decided_by = 'imported'",
            (project_id,),
        ).fetchone():
            conn.execute(
                "INSERT INTO status_check (project_id, verdict, reason, decided_by, checked_at) "
                "VALUES (?, ?, ?, 'imported', ?)",
                (project_id, verdict, reason, now),
            )
            stats.status += 1

        if dept := cell(row, "dept"):
            if not conn.execute(
                "SELECT 1 FROM dept_check WHERE project_id = ? AND decided_by = 'imported'",
                (project_id,),
            ).fetchone():
                conn.execute(
                    "INSERT INTO dept_check (project_id, bid_no, exec_dept, decided_by, checked_at) "
                    "VALUES (?, ?, ?, 'imported', ?)",
                    (project_id, bid_no or None, dept, now),
                )
                stats.dept += 1

        for item in parse_energy_plan(cell(row, "energy")):
            if conn.execute(
                "SELECT 1 FROM energy_plan WHERE project_id = ? AND source_type = ?",
                (project_id, item.source_type),
            ).fetchone():
                continue
            conn.execute(
                "INSERT INTO energy_plan (project_id, source_type, capacity_kw, "
                "entered_by, updated_at) VALUES (?, ?, ?, 'imported', ?)",
                (project_id, item.source_type, item.capacity_kw, now),
            )
            stats.energy += 1

        conn.commit()

    return stats
