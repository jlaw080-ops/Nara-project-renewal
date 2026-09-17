import pytest

from nara.energy import EnergyItem, estimate_cost, parse_energy_plan

PRICES = {
    "BIPV": 5_000_000,
    "PV": 2_500_000,
    "지열": 2_500_000,
    "PEMFC": 32_000_000,
    "SOFC": 98_250_000,
}


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("PV: 21.96kW BIPV: 72.6kW", [EnergyItem("PV", 21.96), EnergyItem("BIPV", 72.6)]),
        ("지열 수직밀폐형 1031.044kW", [EnergyItem("지열", 1031.044)]),
        (
            "PV: 42.24kW 지열 수직밀폐형: 220.938kW",
            [EnergyItem("PV", 42.24), EnergyItem("지열", 220.938)],
        ),
        (
            "태양광 BIPV: 1,756.800 연료전지 PEMFC: 120.000",
            [EnergyItem("BIPV", 1756.8), EnergyItem("PEMFC", 120.0)],
        ),
        ("태양광 고정식: 337.920", [EnergyItem("PV", 337.92)]),
        ("지열: 280.000", [EnergyItem("지열", 280.0)]),
        (
            "PV: 69.12kW PEMFC: 15kW(에스퓨얼셀)",
            [EnergyItem("PV", 69.12), EnergyItem("PEMFC", 15.0)],
        ),
        ("PV: 46.kW BIPV: 41.07kW", [EnergyItem("PV", 46.0), EnergyItem("BIPV", 41.07)]),
        (
            "지열 수직밀폐형: 663.988 태양광 고정식: 113.280",
            [EnergyItem("지열", 663.988), EnergyItem("PV", 113.28)],
        ),
    ],
)
def test_parse_energy_plan_reads_real_sheet_values(text, expected):
    assert parse_energy_plan(text) == expected


def test_parse_energy_plan_does_not_read_bipv_as_pv():
    assert parse_energy_plan("BIPV: 78kW") == [EnergyItem("BIPV", 78.0)]


def test_parse_energy_plan_returns_empty_for_blank():
    assert parse_energy_plan("") == []


def test_parse_energy_plan_returns_empty_when_no_capacity():
    assert parse_energy_plan("설비 계획 미정") == []


def test_parse_energy_plan_skips_zero_capacity():
    assert parse_energy_plan("PV: 0kW") == []


def test_estimate_cost_multiplies_capacity_by_unit_price():
    items = [EnergyItem("PV", 21.96), EnergyItem("BIPV", 72.6)]
    assert estimate_cost(items, PRICES) == {"PV": 54_900_000, "BIPV": 363_000_000}


def test_estimate_cost_matches_unit_price_tab_worked_example():
    """단가 탭에 적힌 예시 계산과 같은 값이 나와야 한다."""
    assert estimate_cost([EnergyItem("BIPV", 21.21)], PRICES) == {"BIPV": 106_050_000}
    assert estimate_cost([EnergyItem("PV", 117.18)], PRICES) == {"PV": 292_950_000}
    assert estimate_cost([EnergyItem("지열", 247.046)], PRICES) == {"지열": 617_615_000}


def test_estimate_cost_skips_unknown_source():
    assert estimate_cost([EnergyItem("풍력", 100.0)], PRICES) == {}
