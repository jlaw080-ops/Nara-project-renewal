"""설치계획내용 문자열을 에너지원·용량으로 쪼개고 예상가를 계산한다."""

import re
from dataclasses import dataclass

# 긴 표기를 먼저 바꿔야 '태양광 BIPV'가 PV로 새지 않는다.
_ALIASES = (
    ("태양광 BIPV", "BIPV"),
    ("태양광BIPV", "BIPV"),
    ("연료전지 PEMFC", "PEMFC"),
    ("연료전지 SOFC", "SOFC"),
    ("태양광 고정식", "PV"),
    ("태양광고정식", "PV"),
    ("태양광", "PV"),
    ("지열 수직밀폐형", "지열"),
    ("지열수직밀폐형", "지열"),
)

# (?<![A-Z]) 로 BIPV 안의 PV를 걸러낸다.
_TOKEN = re.compile(r"(BIPV|(?<![A-Z])PV|지열|PEMFC|SOFC)\s*:?\s*([\d,]+(?:\.\d*)?)")


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
