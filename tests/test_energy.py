import pytest

from nara.db import connect, migrate
from nara.energy import (
    ENERGY_KINDS,
    EnergyItem,
    EnergyKind,
    estimate_cost,
    kind_for,
    load_kinds,
    parse_energy_plan,
)

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


def test_energy_kinds_follow_the_unit_price_sheet():
    """입력 화면의 에너지원·형식 목록. 단가표(원/kW) 시트와 같은 6가지다."""
    assert [(k.source, k.form, k.code) for k in ENERGY_KINDS] == [
        ("태양광", "BIPV", "BIPV"),
        ("태양광", "PV", "PV"),
        ("태양광", "집광채광", "집광채광"),
        ("지열", "수직밀폐형", "지열"),
        ("연료전지", "PEMFC", "PEMFC"),
        ("연료전지", "SOFC", "SOFC"),
    ]


def test_parse_energy_plan_does_not_read_daylighting_as_pv():
    """'태양광 집광채광'을 '태양광'(PV)으로 읽으면 단가가 2.5배로 잡힌다."""
    assert parse_energy_plan("태양광 집광채광: 10kW PV: 5kW") == [
        EnergyItem("집광채광", 10.0),
        EnergyItem("PV", 5.0),
    ]


def _db(tmp_path):
    conn = connect(tmp_path / "k.db")
    migrate(conn)
    return conn


def test_load_kinds_starts_with_the_six_sheet_kinds(tmp_path):
    assert load_kinds(_db(tmp_path)) == list(ENERGY_KINDS)


def test_kind_for_reads_the_sheet_wording_of_an_existing_kind(tmp_path):
    """설치계획서는 PV를 '태양광 고정식'으로 적는다. 새 종류로 만들면 단가가 빠진다."""
    conn = _db(tmp_path)
    assert kind_for(conn, "태양광", "고정식").code == "PV"
    assert kind_for(conn, "지열", "수직밀폐형").code == "지열"
    assert len(load_kinds(conn)) == 6


def test_kind_for_adds_an_unknown_kind_without_a_price(tmp_path):
    conn = _db(tmp_path)
    kind = kind_for(conn, "태양열", "평판형")
    assert kind == EnergyKind("태양열", "평판형", "태양열 평판형")
    assert load_kinds(conn)[-1] == kind
    price = conn.execute(
        "SELECT 1 FROM energy_unit_price WHERE source_type = ?", (kind.code,)
    ).fetchone()
    assert price is None
    assert kind_for(conn, "태양열", "평판형") == kind
    assert len(load_kinds(conn)) == 7


def test_kind_for_does_not_read_another_solar_form_as_pv(tmp_path):
    """'태양광'만 보고 PV로 읽으면 추적식에 고정식 단가가 붙는다."""
    assert kind_for(_db(tmp_path), "태양광", "추적식").code == "태양광 추적식"
