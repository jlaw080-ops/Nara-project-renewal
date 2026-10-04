"""설치계획내용 문자열을 에너지원·용량으로 쪼개고 예상가를 계산한다."""

import re
import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class EnergyKind:
    source: str  # 에너지원
    form: str  # 형식
    code: str  # energy_plan·energy_unit_price에 적는 이름


# 단가표(원/kW) 시트의 에너지원·형식 — 처음 목록(시드). 실제 목록은 energy_kind 표다.
ENERGY_KINDS = (
    EnergyKind("태양광", "BIPV", "BIPV"),
    EnergyKind("태양광", "PV", "PV"),
    EnergyKind("태양광", "집광채광", "집광채광"),
    EnergyKind("지열", "수직밀폐형", "지열"),
    EnergyKind("연료전지", "PEMFC", "PEMFC"),
    EnergyKind("연료전지", "SOFC", "SOFC"),
)

# 긴 표기를 먼저 바꿔야 '태양광 BIPV'가 PV로 새지 않는다.
_ALIASES = (
    ("태양광 BIPV", "BIPV"),
    ("태양광BIPV", "BIPV"),
    ("태양광 집광채광", "집광채광"),
    ("태양광집광채광", "집광채광"),
    ("연료전지 PEMFC", "PEMFC"),
    ("연료전지 SOFC", "SOFC"),
    ("태양광 고정식", "PV"),
    ("태양광고정식", "PV"),
    ("태양광", "PV"),
    ("지열 수직밀폐형", "지열"),
    ("지열수직밀폐형", "지열"),
)

_ALIAS_CODES = dict(_ALIASES)


def _kind(row: sqlite3.Row) -> EnergyKind:
    return EnergyKind(row["source"], row["form"], row["code"])


def load_kinds(conn: sqlite3.Connection) -> list[EnergyKind]:
    rows = conn.execute("SELECT code, source, form FROM energy_kind ORDER BY sort, code")
    return [_kind(r) for r in rows]


def kind_for(conn: sqlite3.Connection, source: str, form: str) -> EnergyKind:
    """(에너지원, 형식)의 종류. 목록에 없으면 단가 없이 더한다. 커밋은 부른 쪽이 한다.

    시트 표기('태양광 고정식')는 정확히 같을 때만 기존 종류로 읽는다 —
    '태양광'만 보고 PV로 읽으면 추적식 같은 다른 형식에 PV 단가가 붙는다.
    """
    source, form = source.strip(), form.strip()
    row = conn.execute(
        "SELECT code, source, form FROM energy_kind WHERE source = ? AND form = ?", (source, form)
    ).fetchone()
    if row is None and (alias := _ALIAS_CODES.get(f"{source} {form}")):
        row = conn.execute(
            "SELECT code, source, form FROM energy_kind WHERE code = ?", (alias,)
        ).fetchone()
    if row is not None:
        return _kind(row)
    code = f"{source} {form}".strip()
    sort = conn.execute("SELECT COALESCE(MAX(sort), 0) + 10 FROM energy_kind").fetchone()[0]
    conn.execute(
        "INSERT OR IGNORE INTO energy_kind (code, source, form, sort) VALUES (?, ?, ?, ?)",
        (code, source, form, sort),
    )
    return EnergyKind(source, form, code)


# (?<![A-Z]) 로 BIPV 안의 PV를 걸러낸다.
_TOKEN = re.compile(r"(BIPV|(?<![A-Z])PV|지열|PEMFC|SOFC|집광채광)\s*:?\s*([\d,]+(?:\.\d*)?)")


@dataclass(frozen=True)
class EnergyItem:
    source_type: str
    capacity_kw: float


def parse_energy_plan(text: str) -> list[EnergyItem]:
    """'PV: 21.96kW BIPV: 72.6kW' → [EnergyItem('PV', 21.96), EnergyItem('BIPV', 72.6)]"""
    s = text or ""
    for old, new in _ALIASES:
        s = s.replace(old, new)

    items = []
    for source, number in _TOKEN.findall(s):
        capacity = float(number.rstrip(".").replace(",", ""))
        if capacity > 0:
            items.append(EnergyItem(source, capacity))
    return items


def estimate_cost(items: list[EnergyItem], prices: dict[str, int]) -> dict[str, int]:
    """에너지원별 예상가. 단가표에 없는 에너지원은 뺀다."""
    totals: dict[str, int] = {}
    for item in items:
        if item.source_type not in prices:
            continue
        cost = round(item.capacity_kw * prices[item.source_type])
        totals[item.source_type] = totals.get(item.source_type, 0) + cost
    return totals
