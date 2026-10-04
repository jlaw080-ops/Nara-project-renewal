"""설치계획서 받은 행 — 검사와 저장."""

import pytest

from nara.db import connect, migrate
from nara.nr_plan import NrEnergy, NrRow, load_energy, parse_nr_row, save_nr_plan

NOW = "2026-10-04T09:00:00"
RAW = {
    "key": "2026-001",
    "org": "전라북도 완주군",
    "name": "완주 다목적체육관",
    "addr": "전북특별자치도 완주군 봉동읍 완주로 1",
    "start": "2027-03-01",
    "end": "2028-06-30",
    "dept": "체육진흥과",
    "energy": [{"source": "지열", "form": "수직밀폐형", "capacity_kw": 336.06}],
}


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "p.db")
    migrate(c)
    return c


def test_parse_nr_row_reads_a_full_row():
    row = parse_nr_row(RAW)
    assert row == NrRow(
        "2026-001", "전라북도 완주군", "완주 다목적체육관",
        "전북특별자치도 완주군 봉동읍 완주로 1", "2027-03-01", "2028-06-30", "체육진흥과",
        (NrEnergy("지열", "수직밀폐형", 336.06),),
    )  # fmt: skip


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"key": ""}, "key·org·name은 꼭 있어야 합니다"),
        ({"org": None}, "key·org·name은 꼭 있어야 합니다"),
        ({"start": "2027.03.01"}, "착공 날짜는 YYYY-MM-DD로 보내세요: 2027.03.01"),
        ({"end": "2028-02-30"}, "준공 날짜는 YYYY-MM-DD로 보내세요: 2028-02-30"),
        ({"energy": "지열 336"}, "energy는 배열이어야 합니다"),
        ({"energy": [{"source": "지열", "form": "", "capacity_kw": "336"}]},
         "용량은 0보다 큰 수여야 합니다: 지열"),
        ({"energy": [{"source": "지열", "form": "", "capacity_kw": float("nan")}]},
         "용량은 0보다 큰 수여야 합니다: 지열"),
        ({"energy": [{"source": "", "form": "x", "capacity_kw": 1}]},
         "energy에 에너지원이 없습니다"),
    ],
)  # fmt: skip
def test_parse_nr_row_names_what_is_wrong(change, reason):
    assert parse_nr_row({**RAW, **change}) == reason


def test_parse_nr_row_refuses_a_non_object():
    assert parse_nr_row(["2026-001"]) == "행은 객체여야 합니다"


def test_parse_nr_row_cuts_long_text_and_allows_missing_dates():
    row = parse_nr_row({**RAW, "name": "가" * 500, "start": "", "end": None, "energy": None})
    assert len(row.name) == 200
    assert (row.start, row.end, row.energy) == (None, None, ())


def test_save_nr_plan_creates_then_reports_unchanged_then_updates(conn):
    row = parse_nr_row(RAW)
    plan_id, saved = save_nr_plan(conn, row, NOW)
    assert saved == "created"
    assert save_nr_plan(conn, row, "2026-10-05T09:00:00") == (plan_id, "unchanged")
    changed = parse_nr_row({**RAW, "end": "2028-12-31"})
    assert save_nr_plan(conn, changed, "2026-10-06T09:00:00") == (plan_id, "updated")
    stored = conn.execute("SELECT * FROM nr_plan").fetchall()
    assert len(stored) == 1
    assert stored[0]["end_date"] == "2028-12-31"
    assert stored[0]["received_at"] == NOW
    assert stored[0]["updated_at"] == "2026-10-06T09:00:00"
    assert stored[0]["match_state"] == "pending"
    assert load_energy(stored[0]["energy_json"]) == (NrEnergy("지열", "수직밀폐형", 336.06),)
