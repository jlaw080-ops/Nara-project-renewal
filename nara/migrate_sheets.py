"""기존 구글시트 탭을 DB로 옮긴다."""

import sqlite3
from dataclasses import dataclass

from nara.config import Settings
from nara.dates import to_iso_date
from nara.energy import parse_energy_plan
from nara.sheets_tsv import read_tsv
from nara.store import ensure_project, upsert_org

_VERDICTS = ("준공 완료", "시공 중", "착공 전(설계 단계)", "미확인")

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
) -> ImportStats:
    header, rows = read_tsv(text)
    index = {name.strip(): i for i, name in enumerate(header) if name.strip()}
    stats = ImportStats(rows=len(rows))

    def cell(row: list[str], key: str) -> str:
        i = index.get(COLUMNS[key])
        return row[i].strip() if i is not None and i < len(row) else ""

    for row in rows:
        org_name = cell(row, "org")
        title = cell(row, "title")
        if not org_name or not title:
            stats.skipped += 1
            continue
        stats.imported += 1

        org_id = upsert_org(conn, org_name, settings, now)
        bid_no = cell(row, "bid_no")
        source = "g2b" if bid_no else "manual"
        project_id = ensure_project(conn, org_id, title, source, now)
        if source == "manual":
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
                conn.execute(
                    "INSERT INTO notice (bid_no, project_id, org_id, org_name, title, "
                    "budget_basis, collected_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (bid_no, project_id, org_id, org_name, title, cell(row, "budget"), now),
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
