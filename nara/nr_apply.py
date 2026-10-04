"""설치계획서 받기 흐름 — 저장, 짝 찾기, 새 사업, 반영.

반영 원칙: 사람이 웹에서 고친 칸은 덮지 않고 skipped에 남긴다(edited_on_web).
"""

import sqlite3
from dataclasses import dataclass
from datetime import datetime

from nara.config import Settings
from nara.energy import kind_for
from nara.nr_match import candidates, canonical_org, decide, org_key
from nara.nr_plan import load_energy, parse_nr_row, save_nr_plan
from nara.runlog import RunCounters
from nara.sheet_memory import edited_on_web
from nara.store import ensure_project, upsert_org

NR_SNIPPET = "설치계획서 의무기관 담당자 부서"
LINKED = ("auto", "new", "human")
MATCH_RESULTS = {
    "auto": "linked",
    "human": "linked",
    "new": "new_project",
    "pending": "pending",
    "ignored": "ignored",
}
_PROJECT_FIELDS = ("address", "start_date", "end_date")


@dataclass(frozen=True)
class RowResult:
    key: str
    saved: str  # created | updated | unchanged | invalid
    match: str | None = None  # linked | new_project | pending | ignored
    project_id: int | None = None
    error: str | None = None


def _plans(conn: sqlite3.Connection, project_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM nr_plan WHERE project_id = ? AND match_state IN ('auto', 'new', 'human') "
        "ORDER BY updated_at DESC, id DESC",
        (project_id,),
    ).fetchall()


def _apply_energy(
    conn: sqlite3.Connection, pid: int, plans: list[sqlite3.Row], now: str, skipped: list[str]
) -> None:
    """연결된 설치계획서들의 용량을 종류별로 합친다. 한 사업에 건물이 여럿일 수 있다."""
    totals: dict[str, float] = {}
    for plan in plans:
        for e in load_energy(plan["energy_json"]):
            code = kind_for(conn, e.source, e.form).code
            totals[code] = round(totals.get(code, 0.0) + e.capacity_kw, 3)
    if not totals:
        return  # 에너지원 표를 못 읽은 설치계획서가 있던 계획을 지우지 않는다
    rows = conn.execute(
        "SELECT source_type, capacity_kw FROM energy_plan WHERE project_id = ?", (pid,)
    )
    if {r["source_type"]: r["capacity_kw"] for r in rows} == totals:
        return
    if edited_on_web(conn, pid, "energy"):
        skipped.append("energy")
        return
    conn.execute("DELETE FROM energy_plan WHERE project_id = ?", (pid,))
    for code, capacity in totals.items():
        conn.execute(
            "INSERT INTO energy_plan (project_id, source_type, capacity_kw, entered_by, "
            "updated_at) VALUES (?, ?, ?, 'nr', ?)",
            (pid, code, capacity, now),
        )


def _apply_dept(
    conn: sqlite3.Connection, pid: int, dept: str | None, now: str, skipped: list[str]
) -> None:
    if not dept:
        return
    latest = conn.execute(
        "SELECT exec_dept, decided_by FROM dept_check WHERE project_id = ? AND confirmed = 1 "
        "AND COALESCE(exec_dept, '') != '' ORDER BY id DESC LIMIT 1",
        (pid,),
    ).fetchone()
    if latest and latest["decided_by"] == "human":
        if latest["exec_dept"] != dept:
            skipped.append("exec_dept")
        return
    if latest and latest["decided_by"] == "nr" and latest["exec_dept"] == dept:
        return
    conn.execute(
        "INSERT INTO dept_check (project_id, exec_dept, snippet, confirmed, decided_by, "
        "checked_at) VALUES (?, ?, ?, 1, 'nr', ?)",
        (pid, dept, NR_SNIPPET, now),
    )


def apply_plans(conn: sqlite3.Connection, project_id: int, now: str) -> list[str]:
    """그 사업에 연결된 설치계획서를 반영한다. 건너뛴 칸 이름을 돌려준다. 커밋은 부른 쪽이."""
    plans = _plans(conn, project_id)
    if not plans:
        return []
    skipped: list[str] = []
    _apply_energy(conn, project_id, plans, now, skipped)
    latest = plans[0]
    project = conn.execute(
        "SELECT address, start_date, end_date FROM project WHERE id = ?", (project_id,)
    ).fetchone()
    for field in _PROJECT_FIELDS:
        value = latest[field]
        if not value or value == project[field]:
            continue
        if edited_on_web(conn, project_id, field):
            skipped.append(field)
            continue
        # field는 위의 고정 목록에서만 온다.
        conn.execute(
            f"UPDATE project SET {field} = ?, updated_at = ? WHERE id = ?",
            (value, now, project_id),
        )
    _apply_dept(conn, project_id, latest["dept"], now, skipped)
    conn.execute(
        "UPDATE nr_plan SET skipped = ? WHERE project_id = ?",
        (",".join(skipped) or None, project_id),
    )
    return skipped


def _new_project(conn: sqlite3.Connection, plan: sqlite3.Row, settings: Settings, now: str) -> int:
    aliases = dict(settings.nr_org_aliases)
    key = org_key(plan["org_name"], aliases)
    org_id = next(
        (
            r["id"]
            for r in conn.execute("SELECT id, name FROM org ORDER BY id")
            if org_key(r["name"], aliases) == key
        ),
        None,
    )
    if org_id is None:
        name = canonical_org(plan["org_name"], aliases)
        org_id = upsert_org(conn, name, settings, now, commit=False)
    return ensure_project(conn, org_id, plan["building_name"], "nr", now, commit=False)


def ingest(
    conn: sqlite3.Connection,
    raw_rows: list,
    settings: Settings,
    now: str,
    counters: RunCounters | None = None,
) -> list[RowResult]:
    """받은 행마다 저장 → (확인 필요면) 짝 찾기 → 반영. 행마다 커밋한다."""
    counters = counters or RunCounters()
    aliases = dict(settings.nr_org_aliases)
    results = []
    for raw in raw_rows:
        row = parse_nr_row(raw)
        if isinstance(row, str):
            key = raw.get("key") if isinstance(raw, dict) else None
            results.append(RowResult(key if isinstance(key, str) else "", "invalid", error=row))
            counters.failed += 1
            continue
        plan_id, saved = save_nr_plan(conn, row, now)
        plan = conn.execute("SELECT * FROM nr_plan WHERE id = ?", (plan_id,)).fetchone()
        state, pid = plan["match_state"], plan["project_id"]
        if state == "pending":
            decision = decide(candidates(conn, row.org, row.name, row.addr, aliases))
            state = decision.state
            pid = decision.project_id
            if state == "new":
                pid = _new_project(conn, plan, settings, now)
            conn.execute(
                "UPDATE nr_plan SET match_state = ?, match_score = ?, project_id = ? WHERE id = ?",
                (state, decision.score, pid, plan_id),
            )
        if pid is not None and state in LINKED:
            apply_plans(conn, pid, now)
        conn.commit()
        counters.processed += 1
        counters.updated += saved != "unchanged"
        results.append(RowResult(row.key, saved, MATCH_RESULTS[state], pid))
    return results


def _refresh(conn: sqlite3.Connection, project_id: int, now: str) -> None:
    """설치계획서가 떨어져 나간 사업을 남은 것으로 다시 맞춘다. 없으면 그 몫의 설비를 지운다.

    주소·일정·부서는 되돌리지 않는다 — 다른 출처와 섞여 있어 사람이 판단한다.
    """
    if _plans(conn, project_id):
        apply_plans(conn, project_id, now)
        return
    conn.execute(
        "DELETE FROM energy_plan WHERE project_id = ? AND entered_by = 'nr'", (project_id,)
    )


def link_plan(
    conn: sqlite3.Connection,
    plan_id: int,
    project_id: int | None,
    settings: Settings,
    now: str,
) -> int:
    """사람이 연결한다. project_id가 None이면 새 사업을 만든다. 연결한 사업 id를 돌려준다."""
    plan = conn.execute("SELECT * FROM nr_plan WHERE id = ?", (plan_id,)).fetchone()
    if plan is None:
        raise LookupError(f"설치계획서 {plan_id}")
    if project_id is None:
        project_id = _new_project(conn, plan, settings, now)
    elif conn.execute("SELECT 1 FROM project WHERE id = ?", (project_id,)).fetchone() is None:
        raise LookupError(f"사업 {project_id}")
    conn.execute(
        "UPDATE nr_plan SET match_state = 'human', project_id = ? WHERE id = ?",
        (project_id, plan_id),
    )
    if plan["project_id"] is not None and plan["project_id"] != project_id:
        _refresh(conn, plan["project_id"], now)
    apply_plans(conn, project_id, now)
    conn.commit()
    return project_id


def ignore_plan(conn: sqlite3.Connection, plan_id: int, now: str | None = None) -> None:
    """무시한다. 연결돼 있던 사업의 설비는 남은 설치계획서로 다시 맞춘다."""
    plan = conn.execute("SELECT project_id FROM nr_plan WHERE id = ?", (plan_id,)).fetchone()
    if plan is None:
        raise LookupError(f"설치계획서 {plan_id}")
    conn.execute(
        "UPDATE nr_plan SET match_state = 'ignored', project_id = NULL WHERE id = ?", (plan_id,)
    )
    if plan["project_id"] is not None:
        _refresh(conn, plan["project_id"], now or datetime.now().isoformat(timespec="seconds"))
    conn.commit()
