"""웹 조회 화면이 읽는 자료. DB는 읽기 전용으로만 연다."""

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote

from nara.energy import EnergyItem, EnergyKind, estimate_cost, load_kinds
from nara.sheet_memory import FIELD_LABELS
from nara.store import last_run
from nara.web.query import (
    LIST_LIMIT,
    Filters,
    build_count_query,
    build_excluded_query,
    build_list_query,
    hidden_clause,
)

_SQLITE_MAX_INT = 2**63 - 1


class DatabaseMissing(FileNotFoundError):
    """DB 파일이 없다. 빈 DB를 새로 만들지 않고 멈춘다."""


BUSY_TIMEOUT_SECONDS = 5.0


def _uri(db_path: Path, mode: str) -> str:
    """경로는 URL 인코딩한다. '#'이 든 경로를 URI에 그대로 넣으면 SQLite가 그
    뒤를 조각으로 잘라 엉뚱한 DB를 열고, 오류 대신 'no such table'만 낸다."""
    return f"file:{quote(db_path.resolve().as_posix(), safe='/:')}?mode={mode}"


def open_readonly(db_path: Path) -> sqlite3.Connection:
    """읽기 전용 연결을 연다.

    `nara.db.connect`를 쓰지 않는다. 그 함수는 폴더를 만들고 일반 모드로 열어
    없는 파일을 새로 만든다 — 오타 난 경로가 '자료 0건'으로 조용히 보인다.
    """
    if not db_path.exists():
        raise DatabaseMissing(f"DB 파일이 없다: {db_path}")
    conn = sqlite3.connect(_uri(db_path, "ro"), uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def open_readwrite(db_path: Path, timeout: float = BUSY_TIMEOUT_SECONDS) -> sqlite3.Connection:
    """저장할 때만 여는 연결. mode=rw라 없는 파일을 만들지 않는다.

    수집이 쓰는 중이면 timeout초까지 기다린다. 넘기면 sqlite3가
    'database is locked'를 낸다 — 화면이 이유를 보이고 입력값을 남긴다.
    """
    if not db_path.exists():
        raise DatabaseMissing(f"DB 파일이 없다: {db_path}")
    conn = sqlite3.connect(_uri(db_path, "rw"), uri=True, timeout=timeout)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@dataclass(frozen=True)
class ListResult:
    rows: list[sqlite3.Row]
    total: int
    matched: int
    excluded_no_notice: int | None
    truncated: bool


def list_projects(conn: sqlite3.Connection, f: Filters) -> ListResult:
    """조건에 걸리는 사업을 고른다. 행은 사업 하나, 공고는 가장 최근 것 하나다.

    matched는 상한과 관계없는 진짜 건수다. rows가 그보다 적으면 잘린 것이고,
    그 사실을 truncated로 돌려준다 — 화면이 "1,000건만 표시합니다"라고 적는다.
    """
    total = conn.execute(f"SELECT COUNT(*) FROM project p WHERE {hidden_clause(f)}").fetchone()[0]
    matched = conn.execute(*build_count_query(f)).fetchone()[0]
    rows = conn.execute(*build_list_query(f)).fetchall()
    excluded_query = build_excluded_query(f)
    excluded = conn.execute(*excluded_query).fetchone()[0] if excluded_query else None
    return ListResult(rows, total, matched, excluded, matched > len(rows))


DECIDED_BY_LABELS = {
    "imported": "시트 이관",
    "rule": "규칙",
    "news": "뉴스",
    "llm": "LLM",
    "human": "사람",
    "release": "잠금 해제",
    "nr": "설치계획서",
}


@dataclass(frozen=True)
class StatusEntry:
    checked_at: str
    verdict: str
    decided_by: str
    reason: str
    evidence_url: str


@dataclass(frozen=True)
class EnergyLine:
    source_type: str
    capacity_kw: float
    cost: int | None


@dataclass(frozen=True)
class ProjectDetail:
    project: sqlite3.Row
    notices: list[dict]
    history: list[StatusEntry]
    depts: list[dict]
    energy: list[EnergyLine]
    energy_total: int
    energy_unpriced: list[str]
    locked: bool = False
    edits: list[dict] = ()
    attachments: list[sqlite3.Row] = ()
    nr_plans: list[sqlite3.Row] = ()
    exec_dept: str | None = None  # 확정된 최신 실행부서
    contact: sqlite3.Row | None = None  # 그 부서의 부서장·실무 담당자 연락처
    contact_auto: frozenset[str] = frozenset()  # 공고문에서 자동으로 채운 칸
    exec_snippet: str | None = None  # 확정된 실행부서의 근거 문장


def safe_url(url: str | None) -> str:
    """http·https 주소만 링크로 쓴다.

    자동 이스케이프는 'javascript:' 주소를 막지 못한다 — href에 들어가면
    누르는 순간 실행된다. 근거 URL은 뉴스·LLM에서 오므로 믿지 않는다.
    """
    text = (url or "").strip()
    return text if text.lower().startswith(("http://", "https://")) else ""


def _evidence_url(raw: str | None) -> str:
    """evidence_json의 url. 깨진 JSON이나 url 없음은 빈 문자열 — 화면이 죽지 않는다."""
    if not raw:
        return ""
    try:
        data = json.loads(raw)
    except ValueError:
        return ""
    url = data.get("url") if isinstance(data, dict) else None
    return safe_url(url) if isinstance(url, str) else ""


def _history(conn: sqlite3.Connection, project_id: int) -> list[StatusEntry]:
    rows = conn.execute(
        "SELECT checked_at, verdict, decided_by, reason, evidence_json FROM status_check "
        "WHERE project_id = ? ORDER BY checked_at DESC, id DESC",
        (project_id,),
    )
    return [
        StatusEntry(
            checked_at=row["checked_at"],
            verdict=row["verdict"],
            decided_by=DECIDED_BY_LABELS.get(row["decided_by"], row["decided_by"]),
            reason=row["reason"] or "",
            evidence_url=_evidence_url(row["evidence_json"]),
        )
        for row in rows
    ]


def _energy(conn: sqlite3.Connection, project_id: int) -> tuple[list[EnergyLine], int, list[str]]:
    """예상가는 기존 estimate_cost로 센다.

    그 함수는 단가표에 없는 에너지원을 빼고 합한다. 빠진 에너지원을 따로 돌려줘
    화면이 합계 옆에 적게 한다 — 합계만 보이면 금액이 왜 적은지 알 수 없다.
    """
    prices = {
        row["source_type"]: row["price_per_kw"]
        for row in conn.execute("SELECT source_type, price_per_kw FROM energy_unit_price")
    }
    items = [
        EnergyItem(row["source_type"], row["capacity_kw"])
        for row in conn.execute(
            "SELECT source_type, capacity_kw FROM energy_plan WHERE project_id = ? ORDER BY id",
            (project_id,),
        )
    ]
    lines = [
        EnergyLine(i.source_type, i.capacity_kw, estimate_cost([i], prices).get(i.source_type))
        for i in items
    ]
    total = sum(estimate_cost(items, prices).values())
    unpriced = sorted({i.source_type for i in items if i.source_type not in prices})
    return lines, total, unpriced


# 출력 양식(시트)의 설치계획 표기. DB는 짧은 이름(PV)으로 둔다.
ENERGY_LABELS = {
    "PV": "태양광 고정식",
    "BIPV": "태양광 BIPV",
    "집광채광": "태양광 집광채광",
    "지열": "지열 수직밀폐형",
    "PEMFC": "연료전지 PEMFC",
    "SOFC": "연료전지 SOFC",
}


@dataclass(frozen=True)
class UnitPrice:
    kind: EnergyKind
    price: int | None
    effective_from: str | None
    updated_by: str | None


def unit_prices(conn: sqlite3.Connection) -> list[UnitPrice]:
    """단가 화면의 줄. 에너지원·형식 목록 순서대로, 단가가 없으면 None."""
    rows = {
        r["source_type"]: r
        for r in conn.execute(
            "SELECT p.source_type, p.price_per_kw, p.effective_from, u.name "
            "FROM energy_unit_price p LEFT JOIN app_user u ON u.id = p.updated_by"
        )
    }
    out = []
    for kind in load_kinds(conn):
        r = rows.get(kind.code)
        out.append(
            UnitPrice(
                kind,
                r["price_per_kw"] if r else None,
                r["effective_from"] if r else None,
                r["name"] if r else None,
            )
        )
    return out


@dataclass(frozen=True)
class PrintRow:
    """출력 양식 한 줄."""

    org_name: str
    name: str
    address: str | None
    notice_date: str | None
    open_date: str | None
    start_date: str | None
    end_date: str | None
    dept: str | None
    head_name: str | None
    head_position: str | None
    dept_tel: str | None
    winner: str | None
    plan: list[str]
    costs: list[str]
    total: int
    unpriced: list[str]
    status: str


def current_dept_row(conn: sqlite3.Connection, project_id: int) -> sqlite3.Row | None:
    """확정된 최신 실행부서 줄(exec_dept, snippet). 목록·상세가 같은 규칙으로 고른다."""
    return conn.execute(
        "SELECT exec_dept, snippet FROM dept_check WHERE project_id = ? AND confirmed = 1 "
        "AND COALESCE(exec_dept, '') != '' ORDER BY checked_at DESC, id DESC LIMIT 1",
        (project_id,),
    ).fetchone()


def current_dept(conn: sqlite3.Connection, project_id: int) -> str | None:
    row = current_dept_row(conn, project_id)
    return row["exec_dept"] if row else None


def dept_contact(conn: sqlite3.Connection, org_id: int, dept: str | None) -> sqlite3.Row | None:
    if not dept:
        return None
    return conn.execute(
        "SELECT c.*, u.name AS updated_by_name FROM dept_contact c "
        "LEFT JOIN app_user u ON u.id = c.updated_by WHERE c.org_id = ? AND c.dept = ?",
        (org_id, dept),
    ).fetchone()


def _print_row(conn: sqlite3.Connection, row: sqlite3.Row) -> PrintRow:
    pid = row["id"]
    project = conn.execute(
        "SELECT org_id, address, start_date, end_date FROM project WHERE id = ?", (pid,)
    ).fetchone()
    tel = conn.execute(
        "SELECT head_tel FROM dept_check WHERE project_id = ? AND confirmed = 1 "
        "AND COALESCE(exec_dept, '') != '' ORDER BY checked_at DESC, id DESC LIMIT 1",
        (pid,),
    ).fetchone()
    history = _history(conn, pid)
    reason = history[0].reason if history and history[0].verdict == row["verdict"] else ""
    status = f"{row['verdict']} - {reason}" if row["verdict"] and reason else row["verdict"] or ""
    lines, total, unpriced = _energy(conn, pid)
    contact = dept_contact(conn, project["org_id"], row["exec_dept"])
    return PrintRow(
        org_name=row["org_name"],
        name=row["name"],
        address=project["address"],
        notice_date=row["notice_date"],
        open_date=row["open_date"],
        start_date=project["start_date"],
        end_date=project["end_date"],
        dept=row["exec_dept"],
        head_name=contact["head_name"] if contact else None,
        head_position=contact["head_position"] if contact else None,
        # 직통번호가 먼저, 없으면 시트에서 가져온 번호
        # 부서장 직통 → 실무 담당자 직통 → 공고 기재 번호
        dept_tel=(contact and (contact["head_tel"] or contact["staff_tel"]))
        or (tel["head_tel"] if tel else None),
        winner=row["winner"],
        plan=[
            f"{ENERGY_LABELS.get(e.source_type, e.source_type)}: {e.capacity_kw:.3f} kW"
            for e in lines
        ],
        costs=[f"{e.source_type} {e.cost:,}원" for e in lines if e.cost is not None],
        total=total,
        unpriced=unpriced,
        status=status,
    )


def print_rows(conn: sqlite3.Connection, f: Filters) -> tuple[list[PrintRow], ListResult]:
    """목록과 같은 조건·순서로 출력 양식 줄을 만든다. 상한(1,000건)도 목록과 같다."""
    result = list_projects(conn, f)
    return [_print_row(conn, row) for row in result.rows], result


def project_detail(conn: sqlite3.Connection, project_id: int) -> ProjectDetail | None:
    """한 사업의 전부. 없는 id면 None."""
    if project_id > _SQLITE_MAX_INT:
        # URL의 정수는 상한이 없다. SQLite 범위를 넘기면 바인딩에서 터진다.
        return None
    project = conn.execute(
        "SELECT p.*, o.name AS org_name, u.name AS hidden_by_name "
        "FROM project p JOIN org o ON o.id = p.org_id "
        "LEFT JOIN app_user u ON u.id = p.hidden_by WHERE p.id = ?",
        (project_id,),
    ).fetchone()
    if project is None:
        return None
    notices = [
        {**dict(row), "url": safe_url(row["url"])}
        for row in conn.execute(
            "SELECT n.bid_no, n.title, n.notice_date, n.open_date, n.close_date, "
            "n.budget_krw, n.officer_name, n.officer_tel, n.url, a.winner, a.award_date "
            "FROM notice n LEFT JOIN award a ON a.bid_no = n.bid_no "
            "WHERE n.project_id = ? "
            "ORDER BY COALESCE(n.notice_date, '') DESC, n.bid_no DESC",
            (project_id,),
        )
    ]
    depts = [
        {**dict(row), "by_label": DECIDED_BY_LABELS.get(row["decided_by"], row["decided_by"])}
        for row in conn.execute(
            "SELECT id, exec_dept, contract_dept, snippet, source_file, decided_by, confirmed, "
            "note, checked_at FROM dept_check "
            "WHERE project_id = ? ORDER BY checked_at DESC, id DESC",
            (project_id,),
        )
    ]
    attachments = conn.execute(
        "SELECT a.id, a.bid_no, a.filename, a.downloaded_at FROM attachment a "
        "JOIN notice n ON n.bid_no = a.bid_no "
        "WHERE n.project_id = ? AND a.status = 'ok' ORDER BY a.bid_no DESC, a.seq",
        (project_id,),
    ).fetchall()
    energy, energy_total, energy_unpriced = _energy(conn, project_id)
    latest = conn.execute(
        "SELECT decided_by FROM status_check WHERE project_id = ? "
        "ORDER BY checked_at DESC, id DESC LIMIT 1",
        (project_id,),
    ).fetchone()
    edits = [
        {**dict(row), "label": FIELD_LABELS.get(row["field"], row["field"])}
        for row in conn.execute(
            "SELECT e.edited_at, e.field, e.old_value, e.new_value, u.name AS user_name "
            "FROM edit_log e LEFT JOIN app_user u ON u.id = e.user_id "
            "WHERE e.project_id = ? ORDER BY e.edited_at DESC, e.id DESC",
            (project_id,),
        )
    ]
    dept_row = current_dept_row(conn, project_id)
    exec_dept = dept_row["exec_dept"] if dept_row else None
    contact = dept_contact(conn, project["org_id"], exec_dept)
    return ProjectDetail(
        project=project,
        notices=notices,
        history=_history(conn, project_id),
        depts=depts,
        energy=energy,
        energy_total=energy_total,
        energy_unpriced=energy_unpriced,
        locked=latest is not None and latest["decided_by"] == "human",
        edits=edits,
        attachments=attachments,
        exec_dept=exec_dept,
        exec_snippet=dept_row["snippet"] if dept_row else None,
        contact=contact,
        contact_auto=frozenset(
            a for a in ((contact["auto_fields"] if contact else "") or "").split(",") if a
        ),
        nr_plans=conn.execute(
            "SELECT * FROM nr_plan WHERE project_id = ? ORDER BY updated_at DESC, id DESC",
            (project_id,),
        ).fetchall(),
    )


# 스케줄러가 도는 단계만 본다. 소급 수집은 사람이 한 번 돌리는 일이라 넣으면
# 늘 빨갛게 떠서 경고를 무시하게 만든다.
PIPELINE_STAGES = (
    ("collect", "수집"),
    ("enrich award", "낙찰 조회"),
    ("enrich status", "진행현황"),
    ("enrich dept", "실행부서"),
    ("backup", "백업"),
)
# 이보다 오래 새 실행이 없으면 멈춘 것으로 본다. 스케줄러가 멈추면 run_log에 새 줄이
# 생기지 않아 마지막 '정상'이 계속 정상으로 보인다. 금요일 15시 뒤 월요일 9시(66시간)는
# 멈춤이 아니다.
STALE_AFTER = timedelta(hours=72)
_STATUS_LABELS = {"ok": "정상", "partial": "일부 실패", "error": "실패"}


@dataclass(frozen=True)
class StageRun:
    label: str
    started_at: str | None
    status_label: str
    healthy: bool


def _status_label(status: str | None) -> str:
    # run_log는 시작할 때 status 없이 넣고 끝날 때 채운다. 비어 있으면 끝나지 않은 실행이다.
    if status is None:
        return "끝나지 않음"
    return _STATUS_LABELS.get(status, status)


def _is_stale(started_at: str, now: datetime) -> bool:
    try:
        return now - datetime.fromisoformat(started_at) > STALE_AFTER
    except ValueError:
        return False


def last_runs(conn: sqlite3.Connection, now: datetime | None = None) -> list[StageRun]:
    """파이프라인 단계마다 가장 최근 실행.

    원 명세가 핵심 위험으로 꼽은 '자동 실행이 조용히 멈추는 것'을 목록 맨 위에
    보이는 장치다. 한 번도 돌지 않은 단계도 빠뜨리지 않는다. 상태가 정상이어도
    STALE_AFTER보다 오래 새 실행이 없으면 멈춘 것으로 표시한다.
    """
    now = now or datetime.now()
    runs = []
    for command, label in PIPELINE_STAGES:
        row = last_run(conn, command)
        if row is None:
            runs.append(StageRun(label, None, "실행 기록 없음", False))
        else:
            status = row["status"]
            label_text = _status_label(status)
            stale = _is_stale(row["started_at"], now)
            if stale:
                label_text += " · 3일 넘게 실행 없음"
            healthy = status == "ok" and not stale
            runs.append(StageRun(label, row["started_at"], label_text, healthy))
    return runs


def org_options(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """수요기관 선택 목록. 관심기관을 먼저, 그 안에서는 이름순."""
    return conn.execute(
        "SELECT id, name, tier FROM org ORDER BY tier = 'focus' DESC, name"
    ).fetchall()


NR_STATE_LABELS = {
    "pending": "확인 필요",
    "auto": "자동 연결",
    "new": "새 사업",
    "human": "사람 연결",
    "ignored": "무시",
}
_NR_SELECT = (
    "SELECT n.*, p.name AS project_name FROM nr_plan n LEFT JOIN project p ON p.id = n.project_id "
)


def nr_counts(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute("SELECT match_state, COUNT(*) FROM nr_plan GROUP BY match_state")
    return {r[0]: r[1] for r in rows}


def nr_rows(conn: sqlite3.Connection, state: str) -> list[sqlite3.Row]:
    return conn.execute(
        _NR_SELECT + "WHERE n.match_state = ? ORDER BY n.updated_at DESC, n.id DESC LIMIT ?",
        (state, LIST_LIMIT),
    ).fetchall()


def nr_plan_detail(conn: sqlite3.Connection, plan_id: int) -> sqlite3.Row | None:
    if plan_id > _SQLITE_MAX_INT:
        return None
    return conn.execute(_NR_SELECT + "WHERE n.id = ?", (plan_id,)).fetchone()
