"""신재생에너지센터 설치계획서 — 받은 행 검사와 저장. 짝 찾기·반영은 nr_apply가 한다."""

import json
import math
import sqlite3
from dataclasses import dataclass
from datetime import date

TEXT_LIMIT = 200


@dataclass(frozen=True)
class NrEnergy:
    source: str
    form: str
    capacity_kw: float


@dataclass(frozen=True)
class NrRow:
    key: str
    org: str
    name: str
    addr: str
    start: str | None
    end: str | None
    dept: str
    energy: tuple[NrEnergy, ...]


def _text(raw: object) -> str:
    return raw.strip()[:TEXT_LIMIT] if isinstance(raw, str) else ""


def _iso(raw: object, label: str) -> str | None:
    """'YYYY-MM-DD'이고 실제로 있는 날짜만. date.fromisoformat은 '20270301'도 받는다."""
    text = _text(raw)
    if not text:
        return None
    try:
        if len(text) != 10:
            raise ValueError
        return date.fromisoformat(text).isoformat()
    except ValueError:
        raise ValueError(f"{label} 날짜는 YYYY-MM-DD로 보내세요: {text}") from None


def _energy(raw: object) -> tuple[NrEnergy, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ValueError("energy는 배열이어야 합니다")
    out = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("energy 항목은 객체여야 합니다")
        source, form = _text(item.get("source")), _text(item.get("form"))
        if not source:
            raise ValueError("energy에 에너지원이 없습니다")
        cap = item.get("capacity_kw")
        # bool은 int의 하위형이라 True가 1로 들어온다. 문자열 '336'도 받지 않는다.
        if isinstance(cap, bool) or not isinstance(cap, int | float):
            cap = math.nan
        if not math.isfinite(cap) or cap <= 0:
            raise ValueError(f"용량은 0보다 큰 수여야 합니다: {source} {form}".rstrip())
        out.append(NrEnergy(source, form, float(cap)))
    return tuple(out)


def parse_nr_row(raw: object) -> NrRow | str:
    """받은 행 하나. 못 쓰면 이유 문자열을 돌려준다 — 그 행만 버리고 나머지는 받는다."""
    if not isinstance(raw, dict):
        return "행은 객체여야 합니다"
    key, org, name = _text(raw.get("key")), _text(raw.get("org")), _text(raw.get("name"))
    if not key or not org or not name:
        return "key·org·name은 꼭 있어야 합니다"
    try:
        return NrRow(
            key,
            org,
            name,
            _text(raw.get("addr")),
            _iso(raw.get("start"), "착공"),
            _iso(raw.get("end"), "준공"),
            _text(raw.get("dept")),
            _energy(raw.get("energy")),
        )
    except ValueError as exc:
        return str(exc)


def energy_json(energy: tuple[NrEnergy, ...]) -> str:
    items = [{"source": e.source, "form": e.form, "capacity_kw": e.capacity_kw} for e in energy]
    return json.dumps(items, ensure_ascii=False)


def load_energy(text: str | None) -> tuple[NrEnergy, ...]:
    return tuple(
        NrEnergy(d["source"], d["form"], float(d["capacity_kw"])) for d in json.loads(text or "[]")
    )


_FIELDS = (
    "org_name", "building_name", "address", "start_date", "end_date", "dept", "energy_json",
)  # fmt: skip


def _values(row: NrRow) -> tuple:
    return (row.org, row.name, row.addr, row.start, row.end, row.dept, energy_json(row.energy))


def save_nr_plan(conn: sqlite3.Connection, row: NrRow, now: str) -> tuple[int, str]:
    """key마다 한 줄. 같은 값이 다시 오면 손대지 않는다. 커밋은 부른 쪽이 한다."""
    cols = ", ".join(_FIELDS)
    old = conn.execute(f"SELECT id, {cols} FROM nr_plan WHERE key = ?", (row.key,)).fetchone()
    values = _values(row)
    if old is not None and not row.energy and old["energy_json"] not in (None, "[]"):
        # 에너지원 표를 못 읽은 재전송이다. 비었다고 설비가 없는 것이 아니다 — 전 값을 둔다.
        values = (*values[:-1], old["energy_json"])
    if old is None:
        cursor = conn.execute(
            f"INSERT INTO nr_plan (key, {cols}, received_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (row.key, *values, now, now),
        )
        return cursor.lastrowid, "created"
    if tuple(old[f] for f in _FIELDS) == values:
        return old["id"], "unchanged"
    sets = ", ".join(f"{f} = ?" for f in _FIELDS)
    conn.execute(
        f"UPDATE nr_plan SET {sets}, updated_at = ? WHERE id = ?", (*values, now, old["id"])
    )
    return old["id"], "updated"
