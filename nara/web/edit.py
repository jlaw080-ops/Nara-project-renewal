"""웹 입력의 검증과 저장. 검증은 DB를 모르고, 저장은 쓰기 연결로만 한다."""

import hashlib
import math
import re
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from itertools import zip_longest

from nara.energy import EnergyItem, EnergyKind
from nara.settings_store import KINDS, Change
from nara.sheet_memory import FIELD_LABELS, PROJECT_FIELDS, canonical, energy_value
from nara.verdict import BEFORE, BUILDING, DONE, UNKNOWN

TEXT_LIMIT = 200
LONG_TEXT_LIMIT = 2000
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


def check_energy(
    sources: list[str], kinds: list[str], capacities: list[str], known: Mapping[str, EnergyKind]
) -> Checked:
    """줄마다 에너지원·형식·용량. 셋 다 빈 줄은 건너뛴다 — 빈 줄로 줄을 지운다.

    형식(kinds)의 값은 저장할 이름(PV 등)이다. known(energy_kind 표)에 있고
    고른 에너지원의 형식이어야 한다.
    """
    items: list[EnergyItem] = []
    errors: dict[str, str] = {}
    seen: set[str] = set()
    rows = zip_longest(sources, kinds, capacities, fillvalue="")
    for i, (raw_source, raw_kind, raw_capacity) in enumerate(rows):
        source, code, capacity_text = raw_source.strip(), raw_kind.strip(), raw_capacity.strip()
        if not source and not code and not capacity_text:
            continue
        if not source:
            errors[f"source-{i}"] = "에너지원을 고르세요"
            continue
        kind = known.get(code)
        if kind is None or kind.source != source:
            errors[f"kind-{i}"] = "형식을 고르세요"
            continue
        if code in seen:
            errors[f"kind-{i}"] = "같은 형식이 두 줄입니다"
            continue
        capacity = _positive(capacity_text, errors, f"capacity-{i}")
        if capacity is None:
            errors.setdefault(f"capacity-{i}", "0보다 큰 숫자로 적으세요")
            continue
        seen.add(code)
        items.append(EnergyItem(code, capacity))
    return Checked({"items": items}, errors)


def check_prices(codes: list[str], prices: list[str], current: Mapping[str, int | None]) -> Checked:
    """단가(원/kW). 1 이상의 정수. 아직 단가가 없는 종류는 비워 둘 수 있다."""
    values: dict[str, int] = {}
    errors: dict[str, str] = {}
    for code, raw in zip_longest(codes, prices, fillvalue=""):
        if code not in current:
            errors["_form"] = "모르는 에너지원이 있습니다"
            continue
        text = raw.strip().replace(",", "")
        if not text and current[code] is None:
            continue
        if not text.isdigit() or int(text) < 1:
            errors[f"price-{code}"] = "1 이상의 정수로 적으세요"
            continue
        values[code] = int(text)
    return Checked({"prices": values}, errors)


CONTACT_LIMIT = 50
_TEL = re.compile(r"[0-9-]+")
CONTACT_FIELDS = ("head_name", "head_position", "head_tel")


def check_contact(form: Mapping[str, str]) -> Checked:
    """부서장 이름·직위·직통번호. 셋 다 비우면 지운다."""
    values: dict[str, str | None] = {}
    errors: dict[str, str] = {}
    for key in ("head_name", "head_position"):
        text = _text(form, key)
        if len(text) > CONTACT_LIMIT:
            errors[key] = f"{CONTACT_LIMIT}자까지 적을 수 있습니다"
        values[key] = text or None
    tel = _text(form, "head_tel")
    digits = re.sub(r"[^0-9]", "", tel)
    if tel and (not _TEL.fullmatch(tel) or not 9 <= len(digits) <= 11):
        errors["head_tel"] = "숫자와 -로 9~11자리를 적으세요 (예: 051-000-0000)"
    values["head_tel"] = tel or None
    return Checked(values, errors)


def save_contact(
    conn: sqlite3.Connection,
    org_id: int,
    dept: str,
    values: Mapping[str, str | None],
    now: str,
    user_id: int | None = None,
) -> bool:
    """기관+부서의 연락처를 바꾼다. 바뀐 게 있으면 True."""
    old = conn.execute(
        "SELECT head_name, head_position, head_tel FROM dept_contact WHERE org_id = ? AND dept = ?",
        (org_id, dept),
    ).fetchone()
    new = tuple(values[k] for k in CONTACT_FIELDS)
    if (tuple(old) if old else (None, None, None)) == new:
        return False
    with conn:
        if not any(new):
            conn.execute("DELETE FROM dept_contact WHERE org_id = ? AND dept = ?", (org_id, dept))
        else:
            conn.execute(
                "INSERT INTO dept_contact (org_id, dept, head_name, head_position, head_tel, "
                "updated_at, updated_by) VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(org_id, dept) DO UPDATE SET head_name = excluded.head_name, "
                "head_position = excluded.head_position, head_tel = excluded.head_tel, "
                "updated_at = excluded.updated_at, updated_by = excluded.updated_by",
                (org_id, dept, *new, now, user_id),
            )
    return True


def _log(
    conn: sqlite3.Connection,
    project_id: int,
    field: str,
    old: object,
    new: object,
    now: str,
    user_id: int | None = None,
) -> None:
    conn.execute(
        "INSERT INTO edit_log (project_id, field, old_value, new_value, edited_at, user_id) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (project_id, field, canonical(old) or None, canonical(new) or None, now, user_id),
    )


def save_info(
    conn: sqlite3.Connection,
    project_id: int,
    values: dict,
    now: str,
    user_id: int | None = None,
) -> list[str]:
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
            _log(conn, project_id, field, current[field], new, now, user_id)
            changed.append(FIELD_LABELS[field])
    return changed


def _latest_verdict(conn: sqlite3.Connection, project_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT verdict, reason, decided_by FROM status_check WHERE project_id = ? "
        "ORDER BY checked_at DESC, id DESC LIMIT 1",
        (project_id,),
    ).fetchone()


def save_verdict(
    conn: sqlite3.Connection,
    project_id: int,
    verdict: str,
    reason: str,
    now: str,
    user_id: int | None = None,
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
        _log(
            conn,
            project_id,
            "verdict",
            latest["verdict"] if latest else None,
            verdict,
            now,
            user_id,
        )
    return [FIELD_LABELS["verdict"]]


def release_verdict(
    conn: sqlite3.Connection, project_id: int, now: str, user_id: int | None = None
) -> bool:
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
        # 칸 이름을 verdict와 나눈다. verdict로 남기면 다음 시트 판정 변경이 웹 충돌로 보고된다.
        _log(
            conn, project_id, "verdict_release", latest["verdict"], latest["verdict"], now, user_id
        )
    return True


def save_dept(
    conn: sqlite3.Connection,
    project_id: int,
    exec_dept: str,
    snippet: str | None,
    now: str,
    user_id: int | None = None,
) -> list[str]:
    latest = conn.execute(
        "SELECT exec_dept, snippet, decided_by FROM dept_check WHERE project_id = ? "
        "AND confirmed = 1 AND COALESCE(exec_dept, '') != '' "
        "ORDER BY checked_at DESC, id DESC LIMIT 1",
        (project_id,),
    ).fetchone()
    # 후보를 사람이 확정한 것도 기록한다. 이미 사람이 같은 값으로 확정했을 때만 건너뛴다.
    if (
        latest is not None
        and latest["decided_by"] == "human"
        and latest["exec_dept"] == exec_dept
        and latest["snippet"] == snippet
    ):
        return []
    with conn:
        conn.execute(
            "INSERT INTO dept_check (project_id, exec_dept, snippet, decided_by, checked_at) "
            "VALUES (?, ?, ?, 'human', ?)",
            (project_id, exec_dept, snippet, now),
        )
        old = latest["exec_dept"] if latest else None
        # 후보를 확정만 한 것은 값 변경이 아니다. 기록하면 다음 시트 변경이 웹 충돌로 보고된다.
        if old != exec_dept:
            _log(conn, project_id, "exec_dept", old, exec_dept, now, user_id)
    return [FIELD_LABELS["exec_dept"]]


def save_energy(
    conn: sqlite3.Connection,
    project_id: int,
    items: list[EnergyItem],
    now: str,
    user_id: int | None = None,
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
        _log(conn, project_id, "energy", old, new, now, user_id)
    return [FIELD_LABELS["energy"]]


SECTION_FIELDS = {
    "info": PROJECT_FIELDS,
    "verdict": ("verdict", "verdict_release"),
    "dept": ("exec_dept",),
    "energy": ("energy",),
}


def version_of(conn: sqlite3.Connection, project_id: int, section: str) -> str:
    """그 묶음의 지금 값으로 만든 짧은 표시. 폼을 연 뒤 값이 바뀌면 달라진다."""
    if section == "info":
        row = conn.execute(
            f"SELECT {', '.join(PROJECT_FIELDS)} FROM project WHERE id = ?", (project_id,)
        ).fetchone()
        parts = [canonical(row[f]) for f in PROJECT_FIELDS] if row else []
    elif section == "verdict":
        latest = _latest_row_id(conn, "status_check", project_id, "")
        parts = [latest]
    elif section == "dept":
        parts = [
            _latest_row_id(
                conn,
                "dept_check",
                project_id,
                "AND confirmed = 1 AND COALESCE(exec_dept, '') != ''",
            )
        ]
    else:
        rows = conn.execute(
            "SELECT source_type, capacity_kw FROM energy_plan WHERE project_id = ?", (project_id,)
        ).fetchall()
        parts = [energy_value(EnergyItem(r["source_type"], r["capacity_kw"]) for r in rows)]
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:16]


def _latest_row_id(conn: sqlite3.Connection, table: str, project_id: int, extra: str) -> str:
    # table·extra는 위의 고정 값만 받는다.
    row = conn.execute(
        f"SELECT id FROM {table} WHERE project_id = ? {extra} "
        "ORDER BY checked_at DESC, id DESC LIMIT 1",
        (project_id,),
    ).fetchone()
    return str(row[0]) if row else ""


def last_editor(conn: sqlite3.Connection, project_id: int, section: str) -> str | None:
    """그 묶음을 가장 최근에 웹에서 고친 사람의 이름. 기록이 없으면 None."""
    fields = SECTION_FIELDS[section]
    row = conn.execute(
        f"SELECT u.name FROM edit_log e JOIN app_user u ON u.id = e.user_id "
        f"WHERE e.project_id = ? AND e.field IN ({', '.join('?' * len(fields))}) "
        "ORDER BY e.edited_at DESC, e.id DESC LIMIT 1",
        (project_id, *fields),
    ).fetchone()
    return row[0] if row else None


def _hidden_label(reason: str | None) -> str:
    return f"숨김: {reason}" if reason else "숨김"


def mark_hidden(
    conn: sqlite3.Connection,
    project_ids: list[int],
    reason: str,
    now: str,
    user_id: int | None = None,
) -> int:
    """트랜잭션을 열지 않는다 — 설정 저장처럼 부른 쪽이 한 번에 커밋할 때 쓴다."""
    reason = reason.strip()[:TEXT_LIMIT] or None
    hidden = 0
    for pid in project_ids:
        cur = conn.execute(
            "UPDATE project SET hidden_at = ?, hidden_by = ?, hidden_reason = ? "
            "WHERE id = ? AND hidden_at IS NULL",
            (now, user_id, reason, pid),
        )
        if cur.rowcount:
            _log(conn, pid, "hidden", None, _hidden_label(reason), now, user_id)
            hidden += 1
    return hidden


def hide_projects(
    conn: sqlite3.Connection,
    project_ids: list[int],
    reason: str,
    now: str,
    user_id: int | None = None,
) -> int:
    """목록에서 숨긴다. 이미 숨긴 사업·없는 id는 건드리지 않는다. 숨긴 건수를 돌려준다."""
    with conn:
        return mark_hidden(conn, project_ids, reason, now, user_id)


def unhide_projects(
    conn: sqlite3.Connection, project_ids: list[int], now: str, user_id: int | None = None
) -> int:
    """숨김을 푼다. 다시 목록에 나오고 자동 판정·부서 찾기 대상이 된다."""
    shown = 0
    with conn:
        for pid in project_ids:
            row = conn.execute(
                "SELECT hidden_reason FROM project WHERE id = ? AND hidden_at IS NOT NULL", (pid,)
            ).fetchone()
            if row is None:
                continue
            conn.execute(
                "UPDATE project SET hidden_at = NULL, hidden_by = NULL, hidden_reason = NULL "
                "WHERE id = ?",
                (pid,),
            )
            _log(conn, pid, "hidden", _hidden_label(row["hidden_reason"]), None, now, user_id)
            shown += 1
    return shown


def save_prices(
    conn: sqlite3.Connection, prices: Mapping[str, int], today: str, user_id: int | None = None
) -> list[str]:
    """바뀐 단가만 고치고 적용일·고친 사람을 남긴다. 바뀐 이름을 돌려준다."""
    current = dict(conn.execute("SELECT source_type, price_per_kw FROM energy_unit_price"))
    changed = [code for code, price in prices.items() if current.get(code) != price]
    if not changed:
        return []
    with conn:
        for code in changed:
            conn.execute(
                "INSERT INTO energy_unit_price (source_type, price_per_kw, effective_from, "
                "updated_by) VALUES (?, ?, ?, ?) ON CONFLICT(source_type) DO UPDATE SET "
                "price_per_kw = excluded.price_per_kw, effective_from = excluded.effective_from, "
                "updated_by = excluded.updated_by",
                (code, prices[code], today, user_id),
            )
    return changed


SETTING_MIN = 2
SETTING_LIMIT = 50
ALIAS_FORMAT = "`설치계획서 기관명 = 나라 앱 기관명` 꼴로 적으세요"
NO_REQUIRED = "제목 필수 키워드가 없으면 모든 용역을 수집합니다"


def _setting_error(value: str) -> str | None:
    if len(value) < SETTING_MIN:
        return f"키워드는 2자 이상이어야 합니다: {value}"
    if len(value) > SETTING_LIMIT:
        return f"{SETTING_LIMIT}자까지 적을 수 있습니다"
    return None


def _setting_lines(kind: str, raw: str) -> tuple[list[tuple[str, str | None]], str | None]:
    """한 줄에 하나. 앞뒤 공백만 지운다 — '제설 전진기지'의 안쪽 공백은 키워드의 일부다."""
    out: list[tuple[str, str | None]] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        target = None
        if kind == "nr_alias":
            value, sep, target = (part.strip() for part in line.partition("="))
            if not sep or not value or not target:
                return [], ALIAS_FORMAT
            line = value
        error = _setting_error(line) or (target and _setting_error(target))
        if error:
            return [], error
        if all(v != line for v, _ in out):
            out.append((line, target))
    return out, None


def check_settings(form, current: Mapping[str, set[str]]) -> Checked:
    """설정 화면 입력. 이미 있는 값을 더하거나 없는 값을 빼는 것은 오류가 아니라 무시한다."""
    adds: list[tuple[str, str, str | None]] = []
    removes: list[tuple[str, str]] = []
    errors: dict[str, str] = {}
    for kind in KINDS:
        lines, error = _setting_lines(kind, form.get(f"add_{kind}", ""))
        if error:
            errors[kind] = error
            continue
        adds += [(kind, v, t) for v, t in lines if v not in current[kind]]
        removes += [(kind, v) for v in form.getlist(f"remove_{kind}") if v in current[kind]]
    warnings = []
    left = (current["title_required"] - {v for k, v in removes if k == "title_required"}) | {
        v for k, v, _ in adds if k == "title_required"
    }
    if current["title_required"] and not left:
        warnings.append(NO_REQUIRED)
    change = Change(tuple(adds), tuple(removes))
    return Checked({"change": change, "warnings": warnings}, errors)
