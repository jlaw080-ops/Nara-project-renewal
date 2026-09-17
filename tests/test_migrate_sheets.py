from pathlib import Path

import pytest

from nara.award import pending_award_bid_nos
from nara.config import load_settings
from nara.db import connect, migrate
from nara.migrate_sheets import import_tab
from nara.runlog import RunCounters

SETTINGS = load_settings(Path(__file__).resolve().parents[1] / "config.toml")
NOW = "2026-09-17T09:00:00"

HEADER = [
    "수요기관",
    "공고명",
    "주소",
    "착공일",
    "준공(예정)일",
    "담당부서",
    "낙찰업체 설계사무소",
    "예정공사비",
    "진행현황",
    "설치계획내용",
    "업데이트일시",
    "공고번호",
    "낙찰일(개찰일)",
    "ZEB 인증등급",
]


def _tsv(rows: list[list[str]]) -> str:
    return "\n".join(["\t".join(HEADER), *["\t".join(r) for r in rows]])


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "test.db")
    migrate(c)
    return c


def test_import_tab_creates_notice_for_row_with_bid_number(conn):
    text = _tsv(
        [
            [
                "전북특별자치도 완주군",
                "완주 체육관 실시설계용역",
                "",
                "",
                "",
                "",
                "가건축사사무소",
                "100,000,000원(추정가격)",
                "착공 전(설계 단계) - 낙찰",
                "",
                "2026.09.16",
                "R26BK01418098",
                "",
                "",
            ]
        ]
    )
    stats = import_tab(conn, "전북특별자치도", text, SETTINGS, NOW)
    assert stats.notices == 1
    assert conn.execute("SELECT COUNT(*) FROM notice").fetchone()[0] == 1
    assert conn.execute("SELECT winner FROM award").fetchone()["winner"] == "가건축사사무소"


def test_import_tab_links_the_org_on_imported_notices(conn):
    """org_id가 비면 이관된 공고가 낙찰 조회 대상에서 빠진다."""
    text = _tsv(
        [
            [
                "전북특별자치도 완주군",
                "완주 체육관 실시설계용역",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "R1",
                "",
                "",
            ]
        ]
    )
    import_tab(conn, "전북특별자치도", text, SETTINGS, NOW)
    org_id = conn.execute(
        "SELECT id FROM org WHERE name = ?", ("전북특별자치도 완주군",)
    ).fetchone()[0]
    assert conn.execute("SELECT org_id FROM notice WHERE bid_no = 'R1'").fetchone()[0] == org_id


def test_import_tab_creates_manual_project_for_row_without_bid_number(conn):
    text = _tsv(
        [
            [
                "전북특별자치도 고창군",
                "고창터미널",
                "전북특별자치도 고창군 고창읍 중앙로 191",
                "20270311",
                "20270312",
                "건설과",
                "",
                "",
                "",
                "지열 수직밀폐형 1031.044kW",
                "",
                "",
                "",
                "",
            ]
        ]
    )
    stats = import_tab(conn, "전북특별자치도", text, SETTINGS, NOW)
    assert stats.projects == 1
    assert conn.execute("SELECT COUNT(*) FROM notice").fetchone()[0] == 0
    row = conn.execute("SELECT source, address, start_date, end_date FROM project").fetchone()
    assert row["source"] == "manual"
    assert row["address"] == "전북특별자치도 고창군 고창읍 중앙로 191"
    assert row["start_date"] == "2027-03-11"
    assert row["end_date"] == "2027-03-12"


def test_import_tab_splits_energy_plan_into_rows(conn):
    text = _tsv(
        [
            [
                "전북특별자치도 고창군",
                "고창갯벌 센터",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "PV: 21.96kW BIPV: 72.6kW",
                "",
                "",
                "",
                "",
            ]
        ]
    )
    stats = import_tab(conn, "전북특별자치도", text, SETTINGS, NOW)
    assert stats.energy == 2
    rows = {
        r["source_type"]: r["capacity_kw"]
        for r in conn.execute("SELECT source_type, capacity_kw FROM energy_plan")
    }
    assert rows == {"PV": 21.96, "BIPV": 72.6}


def test_import_tab_records_status_as_imported(conn):
    text = _tsv(
        [
            [
                "전북특별자치도 완주군",
                "완주 체육관",
                "",
                "",
                "",
                "",
                "",
                "",
                "시공 중 - 2026.08.28 기공식",
                "",
                "",
                "R1",
                "",
                "",
            ]
        ]
    )
    import_tab(conn, "전북특별자치도", text, SETTINGS, NOW)
    row = conn.execute("SELECT verdict, reason, decided_by FROM status_check").fetchone()
    assert row["verdict"] == "시공 중"
    assert row["reason"] == "2026.08.28 기공식"
    assert row["decided_by"] == "imported"


def test_import_tab_records_department_as_imported(conn):
    text = _tsv(
        [
            [
                "전북특별자치도 고창군",
                "고창갯벌 센터",
                "",
                "",
                "",
                "세계유산과",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
            ]
        ]
    )
    import_tab(conn, "전북특별자치도", text, SETTINGS, NOW)
    row = conn.execute("SELECT exec_dept, decided_by FROM dept_check").fetchone()
    assert row["exec_dept"] == "세계유산과"
    assert row["decided_by"] == "imported"


def test_import_tab_skips_rows_without_org_or_title(conn):
    text = _tsv([["", "", "", "", "", "", "", "", "", "", "", "", "", ""]])
    stats = import_tab(conn, "전북특별자치도", text, SETTINGS, NOW)
    assert stats.skipped == 1
    assert conn.execute("SELECT COUNT(*) FROM project").fetchone()[0] == 0


def test_import_tab_counts_every_row_for_reconciliation(conn):
    """시트 행 수와 DB 건수 대조가 stats.rows로 성립해야 한다."""
    text = _tsv(
        [
            [
                "전북특별자치도 완주군",
                "공고 있는 사업",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "R1",
                "",
                "",
            ],
            ["전북특별자치도 고창군", "수기 사업", "", "", "", "", "", "", "", "", "", "", "", ""],
            ["", "", "", "", "", "", "", "", "", "", "", "", "", ""],
        ]
    )
    stats = import_tab(conn, "전북특별자치도", text, SETTINGS, NOW)
    assert stats.rows == 3
    assert stats.imported == 2


def test_import_tab_reconciles_on_a_second_run(conn):
    """같은 탭을 다시 넣어도 대조가 성립해야 한다. 재실행은 오류가 아니다."""
    text = _tsv(
        [
            [
                "전북특별자치도 완주군",
                "완주 체육관",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "R1",
                "",
                "",
            ]
        ]
    )
    import_tab(conn, "전북특별자치도", text, SETTINGS, NOW)
    again = import_tab(conn, "전북특별자치도", text, SETTINGS, NOW)
    assert again.notices == 0


def test_import_tab_puts_sheet_budget_on_project_note_not_notice_budget_basis(conn):
    """시트의 예정공사비는 건물 공사비 자유 텍스트이지, notice.budget_basis가 뜻하는
    API 산정근거 이름("추정가격"/"배정예산")이 아니다. 같은 칸에 두면 나중에 backfill이
    API 값으로 덮어써 시트 값이 사라지므로 project.note로 분리해야 한다."""
    text = _tsv(
        [
            [
                "전북특별자치도 완주군",
                "완주 체육관",
                "",
                "",
                "",
                "",
                "",
                "1,777억원",
                "",
                "",
                "",
                "R1",
                "",
                "",
            ]
        ]
    )
    import_tab(conn, "전북특별자치도", text, SETTINGS, NOW)
    project = conn.execute("SELECT note FROM project WHERE name = '완주 체육관'").fetchone()
    assert project["note"] == "예정공사비: 1,777억원"
    notice = conn.execute("SELECT budget_basis FROM notice WHERE bid_no = 'R1'").fetchone()
    assert not notice["budget_basis"]


def test_import_tab_reads_columns_by_header_not_position(conn):
    """열 순서가 바뀐 탭에서도 헤더 이름으로 찾아야 한다."""
    shuffled = ["공고명", "공고번호", "수요기관", "담당부서"]
    text = "\n".join(
        [
            "\t".join(shuffled),
            "\t".join(["완주 체육관", "R9", "전북특별자치도 완주군", "건설과"]),
        ]
    )
    import_tab(conn, "전북특별자치도", text, SETTINGS, NOW)
    row = conn.execute("SELECT org_name, title FROM notice WHERE bid_no = 'R9'").fetchone()
    assert row["org_name"] == "전북특별자치도 완주군"
    assert row["title"] == "완주 체육관"
    assert conn.execute("SELECT exec_dept FROM dept_check").fetchone()["exec_dept"] == "건설과"


def test_import_tab_merges_row_split_by_embedded_newline(conn):
    text = "\n".join(
        [
            "\t".join(HEADER),
            "전북특별자치도 진안군\t진안고원 마이스테이\t\t\t\t\t\t\t\t지열 수직밀폐형: 663.988",
            " 태양광 고정식: 113.280\t\t\t",
        ]
    )
    stats = import_tab(conn, "전북특별자치도", text, SETTINGS, NOW)
    assert stats.projects == 1
    assert stats.energy == 2


def test_import_tab_is_idempotent(conn):
    text = _tsv(
        [
            [
                "전북특별자치도 완주군",
                "완주 체육관 실시설계용역",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "PV: 10kW",
                "",
                "R1",
                "",
                "",
            ]
        ]
    )
    import_tab(conn, "전북특별자치도", text, SETTINGS, NOW)
    import_tab(conn, "전북특별자치도", text, SETTINGS, NOW)
    assert conn.execute("SELECT COUNT(*) FROM project").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM energy_plan").fetchone()[0] == 1


def test_import_tab_stores_open_date_for_award_lookup(conn):
    """open_date를 넣지 않으면 이관된 공고가 낙찰 대기 목록에 영영 못 들어온다."""
    text = _tsv(
        [
            [
                "전북특별자치도 완주군",
                "완주 체육관 실시설계용역",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "R1",
                "2026.05.01",
                "",
            ]
        ]
    )
    import_tab(conn, "전북특별자치도", text, SETTINGS, NOW)
    assert (
        conn.execute("SELECT open_date FROM notice WHERE bid_no = 'R1'").fetchone()[0]
        == "2026-05-01"
    )
    pending = pending_award_bid_nos(conn, "2026-09-17", None, None, 100)
    assert "R1" in pending


def test_import_tab_reports_zero_new_projects_on_second_run(conn):
    """수기 사업 재이관은 신규가 아니다 — projects는 새로 만든 건수만 세야 한다."""
    text = _tsv(
        [
            [
                "전북특별자치도 고창군",
                "고창터미널",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
            ]
        ]
    )
    import_tab(conn, "전북특별자치도", text, SETTINGS, NOW)
    again = import_tab(conn, "전북특별자치도", text, SETTINGS, NOW)
    assert again.projects == 0


def test_import_tab_flags_skipped_rows_that_have_data(conn):
    """수요기관·공고명만 빈 행은 내용이 있으면 미리보기로 남겨야 한다.
    완전히 빈 행은 미리보기에 넣지 않는다."""
    text = _tsv(
        [
            [
                "전북특별자치도 완주군",
                "",
                "전북특별자치도 완주군 어딘가",
                "",
                "",
                "",
                "",
                "50,000,000원",
                "",
                "PV: 10kW",
                "",
                "",
                "",
                "",
            ],
            ["", "", "", "", "", "", "", "", "", "", "", "", "", ""],
        ]
    )
    stats = import_tab(conn, "전북특별자치도", text, SETTINGS, NOW)
    assert stats.skipped == 2
    assert len(stats.skipped_with_data) == 1
    assert "50,000,000원" in stats.skipped_with_data[0]


def test_import_tab_advances_counters_processed_per_row(conn):
    """run_log 카운터는 행마다 올라가야 한다 — 중간에 죽어도 진행 상황이 남는다."""
    text = _tsv(
        [
            [
                "전북특별자치도 완주군",
                "완주 체육관",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "R1",
                "",
                "",
            ],
            ["", "", "", "", "", "", "", "", "", "", "", "", "", ""],
        ]
    )
    counters = RunCounters()
    stats = import_tab(conn, "전북특별자치도", text, SETTINGS, NOW, counters)
    assert counters.processed == 2
    assert stats.rows == 2
