"""웹 입력의 검증과 저장. 검증은 DB를 모르고, 저장은 쓰기 연결로만 한다."""

import math
import re
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from itertools import zip_longest

from nara.energy import EnergyItem
from nara.sheet_memory import FIELD_LABELS, PROJECT_FIELDS, canonical, energy_value
from nara.verdict import BEFORE, BUILDING, DONE, UNKNOWN

TEXT_LIMIT = 200
LONG_TEXT_LIMIT = 2000
SOURCE_LIMIT = 50
EDIT_VERDICTS = (BEFORE, BUILDING, DONE, UNKNOWN)
INFO_FORM = (
    ("address", "주소", "text"),
    ("start_date", "착공일", "date"),
    ("end_date", "준공일", "date"),
    ("floor_area", "연면적(㎡)", "text"),
    ("zeb_grade", "ZEB 등급", "text"),
    ("re_ratio", "신재생 비율", "text"),
    ("etc_cert", "기타 인증", "text"),
    ("guide_equip", "관급 장비", "text"),
    ("note", "비고", "long"),
)
_LONG_FIELDS = ("note",)
_TEXT_FIELDS = ("address", "zeb_grade", "re_ratio", "etc_cert", "guide_equip", "note")
_ISO_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_ID = re.compile(r"[0-9]{1,18}")


@dataclass(frozen=True)
class Checked:
    values: dict
    errors: dict[str, str]

    @property
    def ok(self) -> bool:
        return not self.errors


def _text(form: Mapping[str, str], key: str) -> str:
    return (form.get(key) or "").strip()


def _date(raw: str, errors: dict[str, str], key: str) -> str | None:
    """'YYYY-MM-DD'이고 실제로 있는 날짜만. DB는 이 꼴의 글자로 비교한다."""
    if not raw:
        return None
    if _ISO_DATE.fullmatch(raw):
        try:
            date.fromisoformat(raw)
            return raw
        except ValueError:
            pass
    errors[key] = "YYYY-MM-DD 꼴로 적으세요"
    return None


def _positive(raw: str, errors: dict[str, str], key: str) -> float | None:
    """0보다 큰 유한한 수. float()가 받는 nan·inf·1e400은 거부한다."""
    if not raw:
        return None
    try:
        number = float(raw.replace(",", ""))
    except ValueError:
        number = math.nan
    if not math.isfinite(number) or number <= 0:
        errors[key] = "0보다 큰 숫자로 적으세요"
        return None
    return number


def _limit(key: str, raw: str, errors: dict[str, str]) -> None:
    limit = LONG_TEXT_LIMIT if key in _LONG_FIELDS else TEXT_LIMIT
    if len(raw) > limit:
        errors[key] = f"{limit:,}자까지 적을 수 있습니다"


def check_info(form: Mapping[str, str], current: Mapping, latest_verdict: str | None) -> Checked:
    """사업 정보 9칸. 폼에 없는 칸은 지금 값을 그대로 둔다 — 빠진 칸을 지우지 않는다."""
    errors: dict[str, str] = {}
    values: dict = {}
    for key in PROJECT_FIELDS:
        if key not in form:
            values[key] = current[key]
            continue
        raw = _text(form, key)
        if key in ("start_date", "end_date"):
            values[key] = _date(raw, errors, key)
        elif key == "floor_area":
            values[key] = _positive(raw, errors, key)
        else:
            _limit(key, raw, errors)
            values[key] = raw or None
    start, end = values["start_date"], values["end_date"]
    if start and end and end < start and "end_date" not in errors:
        errors["end_date"] = "준공일이 착공일보다 빠릅니다"
    if start and start != current["start_date"] and latest_verdict == BEFORE:
        errors["start_date"] = (
            "착공 전인 사업에는 확정 착공일을 적지 않습니다. 예정은 비고에 적으세요"
        )
    return Checked(values, errors)


def check_verdict(form: Mapping[str, str]) -> Checked:
    verdict, reason = _text(form, "verdict"), _text(form, "reason")
    errors: dict[str, str] = {}
    if verdict not in EDIT_VERDICTS:
        errors["verdict"] = "네 단계 가운데 하나를 고르세요"
    if not reason:
        errors["reason"] = "사유를 적으세요"
    elif len(reason) > LONG_TEXT_LIMIT:
        errors["reason"] = f"{LONG_TEXT_LIMIT:,}자까지 적을 수 있습니다"
    return Checked({"verdict": verdict, "reason": reason}, errors)


def check_dept(
    form: Mapping[str, str], candidates: Mapping[int, tuple[str, str | None]]
) -> Checked:
    """직접 적은 부서가 먼저다. 비어 있으면 고른 후보의 부서와 근거 문장을 쓴다."""
    exec_dept, snippet = _text(form, "exec_dept"), _text(form, "snippet")
    pick = _text(form, "pick")
    if not exec_dept and _ID.fullmatch(pick) and int(pick) in candidates:
        exec_dept, picked_snippet = candidates[int(pick)]
        snippet = snippet or (picked_snippet or "")
    errors: dict[str, str] = {}
    if not exec_dept:
        errors["exec_dept"] = "실행부서를 적거나 후보를 고르세요"
    elif len(exec_dept) > TEXT_LIMIT:
        errors["exec_dept"] = f"{TEXT_LIMIT:,}자까지 적을 수 있습니다"
    if len(snippet) > LONG_TEXT_LIMIT:
        errors["snippet"] = f"{LONG_TEXT_LIMIT:,}자까지 적을 수 있습니다"
    return Checked({"exec_dept": exec_dept, "snippet": snippet or None}, errors)


def check_energy(sources: list[str], capacities: list[str]) -> Checked:
    """줄마다 에너지원과 용량. 둘 다 빈 줄은 건너뛴다 — 빈 줄로 줄을 지운다."""
    items: list[EnergyItem] = []
    errors: dict[str, str] = {}
    seen: set[str] = set()
    for i, (raw_source, raw_capacity) in enumerate(zip_longest(sources, capacities, fillvalue="")):
        source, capacity_text = raw_source.strip(), raw_capacity.strip()
        if not source and not capacity_text:
            continue
        if not source:
            errors[f"source-{i}"] = "에너지원을 적으세요"
            continue
        if len(source) > SOURCE_LIMIT:
            errors[f"source-{i}"] = f"{SOURCE_LIMIT}자까지 적을 수 있습니다"
            continue
        if source in seen:
            errors[f"source-{i}"] = "같은 에너지원이 두 줄입니다"
            continue
        capacity = _positive(capacity_text, errors, f"capacity-{i}")
        if capacity is None:
            errors.setdefault(f"capacity-{i}", "0보다 큰 숫자로 적으세요")
            continue
        seen.add(source)
        items.append(EnergyItem(source, capacity))
    return Checked({"items": items}, errors)


def _log(
    conn: sqlite3.Connection, project_id: int, field: str, old: object, new: object, now: str
) -> None:
    conn.execute(
        "INSERT INTO edit_log (project_id, field, old_value, new_value, edited_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (project_id, field, canonical(old) or None, canonical(new) or None, now),
    )


def save_info(conn: sqlite3.Connection, project_id: int, values: dict, now: str) -> list[str]:
    """바뀐 칸만 쓰고 기록한다. 값과 기록은 한 트랜잭션이다."""
    current = conn.execute("SELECT * FROM project WHERE id = ?", (project_id,)).fetchone()
    changed: list[str] = []
    with conn:
        for field in PROJECT_FIELDS:
            new = values[field]
            if canonical(new) == canonical(current[field]):
                continue
            # field는 PROJECT_FIELDS에서만 온다 — 폼 값이 칸 이름이 되지 않는다.
            conn.execute(
                f"UPDATE project SET {field} = ?, updated_at = ? WHERE id = ?",
                (new, now, project_id),
            )
            _log(conn, project_id, field, current[field], new, now)
            changed.append(FIELD_LABELS[field])
    return changed


def _latest_verdict(conn: sqlite3.Connection, project_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT verdict, reason, decided_by FROM status_check WHERE project_id = ? "
        "ORDER BY checked_at DESC, id DESC LIMIT 1",
        (project_id,),
    ).fetchone()


def save_verdict(
    conn: sqlite3.Connection, project_id: int, verdict: str, reason: str, now: str
) -> list[str]:
    """사람 판정 한 줄. 최신 판정이 사람 판정이 되어 자동 판정이 이 사업을 건너뛴다."""
    latest = _latest_verdict(conn, project_id)
    if (
        latest is not None
        and latest["decided_by"] == "human"
        and latest["verdict"] == verdict
        and (latest["reason"] or "") == reason
    ):
        return []
    with conn:
        conn.execute(
            "INSERT INTO status_check (project_id, verdict, reason, decided_by, checked_at) "
            "VALUES (?, ?, ?, 'human', ?)",
            (project_id, verdict, reason, now),
        )
        _log(conn, project_id, "verdict", latest["verdict"] if latest else None, verdict, now)
    return [FIELD_LABELS["verdict"]]


def release_verdict(conn: sqlite3.Connection, project_id: int, now: str) -> bool:
    """잠금을 푼다. verdict가 NOT NULL이라 판정을 비우지 않고 지금 판정을 복사해 쌓는다."""
    latest = _latest_verdict(conn, project_id)
    if latest is None or latest["decided_by"] != "human":
        return False
    with conn:
        conn.execute(
            "INSERT INTO status_check (project_id, verdict, reason, decided_by, checked_at) "
            "VALUES (?, ?, '자동 판정에 다시 맡김', 'release', ?)",
            (project_id, latest["verdict"], now),
        )
    return True


def save_dept(
    conn: sqlite3.Connection, project_id: int, exec_dept: str, snippet: str | None, now: str
) -> list[str]:
    latest = conn.execute(
        "SELECT exec_dept, snippet FROM dept_check WHERE project_id = ? "
        "AND COALESCE(exec_dept, '') != '' ORDER BY checked_at DESC, id DESC LIMIT 1",
        (project_id,),
    ).fetchone()
    if latest is not None and latest["exec_dept"] == exec_dept and latest["snippet"] == snippet:
        return []
    with conn:
        conn.execute(
            "INSERT INTO dept_check (project_id, exec_dept, snippet, decided_by, checked_at) "
            "VALUES (?, ?, ?, 'human', ?)",
            (project_id, exec_dept, snippet, now),
        )
        old = latest["exec_dept"] if latest else None
        _log(conn, project_id, "exec_dept", old, exec_dept, now)
    return [FIELD_LABELS["exec_dept"]]


def save_energy(
    conn: sqlite3.Connection, project_id: int, items: list[EnergyItem], now: str
) -> list[str]:
    """그 사업의 신재생 줄을 새 목록으로 바꾼다."""
    rows = conn.execute(
        "SELECT source_type, capacity_kw FROM energy_plan WHERE project_id = ?", (project_id,)
    ).fetchall()
    old = energy_value(EnergyItem(r["source_type"], r["capacity_kw"]) for r in rows)
    new = energy_value(items)
    if old == new:
        return []
    with conn:
        conn.execute("DELETE FROM energy_plan WHERE project_id = ?", (project_id,))
        for item in items:
            conn.execute(
                "INSERT INTO energy_plan (project_id, source_type, capacity_kw, entered_by, "
                "updated_at) VALUES (?, ?, ?, 'human', ?)",
                (project_id, item.source_type, item.capacity_kw, now),
            )
        _log(conn, project_id, "energy", old, new, now)
    return [FIELD_LABELS["energy"]]
