from datetime import datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from nara import cli
from nara.award import pending_award_bid_nos
from nara.config import load_settings
from nara.db import connect, migrate
from nara.energy import EnergyItem
from nara.migrate_sheets import ImportStats, _apply_energy, _to_float, import_tab
from nara.runlog import RunCounters
from nara.store import ensure_project, upsert_org

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
    "연면적(㎡, jootek)",
    "신재생 공급의무비율",
    "기타 인증요건",
    "지침서 명시 설비",
    "전화번호",
    "부서장",
    "직위",
    "공고일(예정일)",
    "공고URL",
    "공고종류",
    "입찰마감일",
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
    row = conn.execute("SELECT exec_dept, decided_by FROM dept_check").fetchone()
    assert row["exec_dept"] == "세계유산과"
    assert row["decided_by"] == "imported"


def test_import_tab_skips_rows_without_org_or_title(conn):
    text = _tsv([[""] * len(HEADER)])
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
            ],
            [
                "전북특별자치도 고창군",
                "수기 사업",
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
            ],
            [""] * len(HEADER),
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
            ],
            [""] * len(HEADER),
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
            ],
            [""] * len(HEADER),
        ]
    )
    counters = RunCounters()
    stats = import_tab(conn, "전북특별자치도", text, SETTINGS, NOW, counters)
    assert counters.processed == 2
    assert stats.rows == 2


def test_import_tab_maps_new_sheet_columns(conn):
    """새로 매핑한 헤더가 각자의 목적지 테이블·칼럼에 정확히 들어가야 한다."""
    text = _tsv(
        [
            [
                "전북특별자치도 완주군",
                "완주 체육관 신축공사",
                "",
                "",
                "",
                "건설과",
                "",
                "",
                "",
                "",
                "",
                "R1",
                "",
                "",
                "12,345.67",
                "20%",
                "지열 인증 필요",
                "냉난방기 3대",
                "063-000-0000",
                "홍길동",
                "과장",
                "2026.09.10",
                "http://example.com/notice/1",
                "일반공고",
                "2026.09.30",
            ]
        ]
    )
    import_tab(conn, "전북특별자치도", text, SETTINGS, NOW)

    project = conn.execute(
        "SELECT floor_area, re_ratio, etc_cert, guide_equip FROM project "
        "WHERE name = '완주 체육관 신축공사'"
    ).fetchone()
    assert project["floor_area"] == 12345.67
    assert isinstance(project["floor_area"], float)
    assert project["re_ratio"] == "20%"
    assert project["etc_cert"] == "지열 인증 필요"
    assert project["guide_equip"] == "냉난방기 3대"

    notice = conn.execute(
        "SELECT notice_date, close_date, url, kind FROM notice WHERE bid_no = 'R1'"
    ).fetchone()
    assert notice["notice_date"] == "2026-09-10"
    assert notice["close_date"] == "2026-09-30"
    assert notice["url"] == "http://example.com/notice/1"
    assert notice["kind"] == "일반공고"

    dept = conn.execute("SELECT head_tel, snippet FROM dept_check").fetchone()
    assert dept["head_tel"] == "063-000-0000"
    assert dept["snippet"] == "부서장 홍길동 과장"


def test_import_tab_leaves_snippet_null_when_head_and_position_are_blank(conn):
    """담당부서는 있어도 부서장·직위가 둘 다 비면 snippet은 NULL이어야 한다."""
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
    dept = conn.execute("SELECT head_tel, snippet FROM dept_check").fetchone()
    assert dept["head_tel"] is None
    assert dept["snippet"] is None


def test_import_tab_does_not_clobber_existing_project_values_with_empty_cells(conn):
    """빈 칸이 이미 채워진 project 값을 지우면 안 된다 — COALESCE 규칙은 새 칼럼에도 적용된다."""
    first = _tsv(
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
                "",
                "",
                "",
                "100.5",
                "10%",
                "인증A",
                "장비A",
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
    second = _tsv(
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
                "",
                "",
            ]
        ]
    )
    import_tab(conn, "전북특별자치도", first, SETTINGS, NOW)
    import_tab(conn, "전북특별자치도", second, SETTINGS, NOW)
    project = conn.execute(
        "SELECT floor_area, re_ratio, etc_cert, guide_equip FROM project WHERE name = '완주 체육관'"
    ).fetchone()
    assert project["floor_area"] == 100.5
    assert project["re_ratio"] == "10%"
    assert project["etc_cert"] == "인증A"
    assert project["guide_equip"] == "장비A"


def test_to_float_returns_none_for_empty_string():
    assert _to_float("") is None


def test_to_float_returns_none_for_unparseable_text():
    assert _to_float("면적 미상") is None


def test_to_float_parses_thousands_separator():
    assert _to_float("1,234.56") == 1234.56


def test_import_tab_reports_floor_area_it_could_not_read_as_a_number(conn):
    """연면적은 REAL 칼럼이라 '2,686㎡' 같은 칸은 원문조차 남길 수 없다.
    조용히 버리면 아무도 모른다 — 건너뛴 행과 같은 방식으로 숫자와 원문을 보고한다."""
    row = [""] * len(HEADER)
    row[HEADER.index("수요기관")] = "전북특별자치도 완주군"
    row[HEADER.index("공고명")] = "완주 체육관 실시설계용역"
    row[HEADER.index("연면적(㎡, jootek)")] = "2,686㎡"

    stats = import_tab(conn, "전북특별자치도", _tsv([row]), SETTINGS, NOW)

    assert stats.unparsed_numbers == 1
    assert len(stats.unparsed_preview) == 1
    assert "2,686㎡" in stats.unparsed_preview[0]
    assert "완주 체육관 실시설계용역" in stats.unparsed_preview[0]
    # 값은 넣지 않는다 — 추측으로 채우느니 비워 두고 보고한다.
    assert conn.execute("SELECT floor_area FROM project").fetchone()["floor_area"] is None


def test_import_tab_does_not_report_blank_floor_area_as_unreadable(conn):
    """빈 칸은 읽지 못한 게 아니라 없는 것이다. 헛경보를 내면 안 된다."""
    row = [""] * len(HEADER)
    row[HEADER.index("수요기관")] = "전북특별자치도 완주군"
    row[HEADER.index("공고명")] = "완주 체육관 실시설계용역"

    stats = import_tab(conn, "전북특별자치도", _tsv([row]), SETTINGS, NOW)

    assert stats.unparsed_numbers == 0
    assert stats.unparsed_preview == []


ORG = "전북특별자치도 완주군"
TITLE = "완주 체육관 증축"


def _row(cells: dict[str, str]) -> list[str]:
    """헤더 이름으로 칸을 채운 한 행. 적지 않은 칸은 빈칸."""
    return [cells.get(name, "") for name in HEADER]


def _sheet(**extra: str) -> str:
    return _tsv([_row({"수요기관": ORG, "공고명": TITLE, **extra})])


def _pid(conn):
    return conn.execute("SELECT id FROM project WHERE name = ?", (TITLE,)).fetchone()[0]


def _web_edit(conn, field, value, when=NOW):
    """웹 저장이 하는 일을 흉내 낸다: 값을 바꾸고 edit_log를 남긴다."""
    pid = _pid(conn)
    old = conn.execute(f"SELECT {field} FROM project WHERE id = ?", (pid,)).fetchone()[0]
    conn.execute(f"UPDATE project SET {field} = ? WHERE id = ?", (value, pid))
    conn.execute(
        "INSERT INTO edit_log (project_id, field, old_value, new_value, edited_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (pid, field, old, value, when),
    )
    conn.commit()


def _project_value(conn, field):
    return conn.execute(f"SELECT {field} FROM project WHERE id = ?", (_pid(conn),)).fetchone()[0]


def test_reimport_keeps_a_web_edit_when_the_sheet_did_not_change(conn):
    """옛 시트 값이 그대로 남아 있을 뿐이면 웹 입력을 되돌리지 않는다."""
    import_tab(conn, "완주", _sheet(**{"착공일": "2026.03.01"}), SETTINGS, NOW)
    _web_edit(conn, "start_date", "2026-04-01")
    stats = import_tab(conn, "완주", _sheet(**{"착공일": "2026.03.01"}), SETTINGS, NOW)
    assert _project_value(conn, "start_date") == "2026-04-01"
    assert stats.overwritten == []


def test_reimport_takes_a_sheet_change_and_reports_the_web_edit_it_replaced(conn):
    """팀원이 시트를 고쳤으면 시트가 이긴다. 내 웹 입력이 사라진 사실은 알린다."""
    import_tab(conn, "완주", _sheet(**{"착공일": "2026.03.01"}), SETTINGS, NOW)
    _web_edit(conn, "start_date", "2026-04-01")
    stats = import_tab(conn, "완주", _sheet(**{"착공일": "2026.05.01"}), SETTINGS, NOW)
    assert _project_value(conn, "start_date") == "2026-05-01"
    assert stats.overwritten == [f"{TITLE} · 착공일 · 2026-04-01 → 2026-05-01"]


def test_reimport_takes_a_sheet_change_quietly_when_nobody_edited_on_web(conn):
    import_tab(conn, "완주", _sheet(**{"연면적(㎡, jootek)": "1,000"}), SETTINGS, NOW)
    stats = import_tab(conn, "완주", _sheet(**{"연면적(㎡, jootek)": "1,200"}), SETTINGS, NOW)
    assert _project_value(conn, "floor_area") == 1200.0
    assert stats.overwritten == []


def test_unreadable_sheet_number_does_not_overwrite_a_web_value(conn):
    """'약 1,000'은 숫자로 못 읽는다. 빈 칸과 같이 다뤄야 웹 값이 남는다."""
    import_tab(conn, "완주", _sheet(**{"연면적(㎡, jootek)": "1,000"}), SETTINGS, NOW)
    _web_edit(conn, "floor_area", 1500.0)
    stats = import_tab(conn, "완주", _sheet(**{"연면적(㎡, jootek)": "약 1,000"}), SETTINGS, NOW)
    assert _project_value(conn, "floor_area") == 1500.0
    assert stats.overwritten == []
    assert stats.unparsed_numbers == 1


def test_migrate_tsv_prints_the_web_edits_it_replaced(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "BACKUP_DIR", tmp_path / "backup")
    db = tmp_path / "n.db"
    sheet = tmp_path / "s.tsv"
    runner = CliRunner()
    sheet.write_text(_sheet(**{"착공일": "2026.03.01"}), encoding="utf-8")
    assert runner.invoke(cli.app, ["migrate", "tsv", str(sheet), "--tab", "완주", "--db", str(db)])
    c = connect(db)
    # CLI 이관은 지금 시각으로 기록한다. 웹 수정도 그 뒤여야 한다.
    _web_edit(c, "start_date", "2026-04-01", when=datetime.now().isoformat(timespec="seconds"))
    c.close()
    sheet.write_text(_sheet(**{"착공일": "2026.05.01"}), encoding="utf-8")
    result = runner.invoke(
        cli.app, ["migrate", "tsv", str(sheet), "--tab", "완주", "--db", str(db)]
    )
    assert result.exit_code == 0, result.output
    assert "웹에서 고친 칸을 시트 값으로 덮은 것 1건" in result.output
    assert f"{TITLE} · 착공일 · 2026-04-01 → 2026-05-01" in result.output


LATER = "2026-09-25T09:00:00"  # 재이관은 사람 입력(09-20)보다 뒤에 돈다


def _web_verdict(conn, verdict):
    pid = _pid(conn)
    old = conn.execute(
        "SELECT verdict FROM status_check WHERE project_id = ? ORDER BY checked_at DESC, id DESC",
        (pid,),
    ).fetchone()
    conn.execute(
        "INSERT INTO status_check (project_id, verdict, reason, decided_by, checked_at) "
        "VALUES (?, ?, '현장 확인', 'human', '2026-09-20T00:00:00')",
        (pid, verdict),
    )
    conn.execute(
        "INSERT INTO edit_log (project_id, field, old_value, new_value, edited_at) "
        "VALUES (?, 'verdict', ?, ?, ?)",
        (pid, old[0] if old else None, verdict, NOW),
    )
    conn.commit()


def _latest_verdict(conn):
    return conn.execute(
        "SELECT verdict, decided_by FROM status_check WHERE project_id = ? "
        "ORDER BY checked_at DESC, id DESC LIMIT 1",
        (_pid(conn),),
    ).fetchone()


def _energy(conn):
    return sorted(
        (r[0], r[1])
        for r in conn.execute(
            "SELECT source_type, capacity_kw FROM energy_plan WHERE project_id = ?",
            (_pid(conn),),
        )
    )


def test_reimport_keeps_a_human_verdict_when_the_sheet_did_not_change(conn):
    import_tab(conn, "완주", _sheet(**{"진행현황": "착공 전(설계 단계) - 낙찰"}), SETTINGS, NOW)
    _web_verdict(conn, "시공 중")
    stats = import_tab(
        conn, "완주", _sheet(**{"진행현황": "착공 전(설계 단계) - 낙찰"}), SETTINGS, LATER
    )
    assert tuple(_latest_verdict(conn)) == ("시공 중", "human")
    assert stats.status == 0


def test_reimport_records_a_changed_sheet_verdict_over_a_human_one_and_says_so(conn):
    import_tab(conn, "완주", _sheet(**{"진행현황": "착공 전(설계 단계) - 낙찰"}), SETTINGS, NOW)
    _web_verdict(conn, "준공 완료")
    stats = import_tab(conn, "완주", _sheet(**{"진행현황": "시공 중 - 기공식"}), SETTINGS, LATER)
    assert tuple(_latest_verdict(conn)) == ("시공 중", "imported")
    assert stats.overwritten == [f"{TITLE} · 진행현황 · 준공 완료 → 시공 중"]


def test_reimport_does_not_bring_back_an_energy_line_deleted_on_web(conn):
    import_tab(conn, "완주", _sheet(**{"설치계획내용": "PV: 20kW 지열: 10kW"}), SETTINGS, NOW)
    pid = _pid(conn)
    conn.execute("DELETE FROM energy_plan WHERE project_id = ? AND source_type = '지열'", (pid,))
    conn.execute(
        "INSERT INTO edit_log (project_id, field, old_value, new_value, edited_at) "
        "VALUES (?, 'energy', 'PV 20, 지열 10', 'PV 20', ?)",
        (pid, NOW),
    )
    conn.commit()
    import_tab(conn, "완주", _sheet(**{"설치계획내용": "PV: 20kW 지열: 10kW"}), SETTINGS, NOW)
    assert _energy(conn) == [("PV", 20.0)]


def test_reimport_replaces_the_energy_plan_when_the_sheet_changed(conn):
    import_tab(conn, "완주", _sheet(**{"설치계획내용": "PV: 20kW"}), SETTINGS, NOW)
    pid = _pid(conn)
    conn.execute(
        "UPDATE energy_plan SET capacity_kw = 25, entered_by = 'human' WHERE project_id = ?",
        (pid,),
    )
    conn.execute(
        "INSERT INTO edit_log (project_id, field, old_value, new_value, edited_at) "
        "VALUES (?, 'energy', 'PV 20', 'PV 25', ?)",
        (pid, NOW),
    )
    conn.commit()
    stats = import_tab(conn, "완주", _sheet(**{"설치계획내용": "PV: 30kW"}), SETTINGS, NOW)
    assert _energy(conn) == [("PV", 30.0)]
    assert stats.overwritten == [f"{TITLE} · 신재생 · PV 25 → PV 30"]


def test_reimport_department_follows_the_same_rule(conn):
    import_tab(conn, "완주", _sheet(**{"담당부서": "체육진흥과"}), SETTINGS, NOW)
    pid = _pid(conn)
    conn.execute(
        "INSERT INTO dept_check (project_id, exec_dept, decided_by, checked_at) "
        "VALUES (?, '문화체육과', 'human', '2026-09-20T00:00:00')",
        (pid,),
    )
    conn.execute(
        "INSERT INTO edit_log (project_id, field, old_value, new_value, edited_at) "
        "VALUES (?, 'exec_dept', '체육진흥과', '문화체육과', ?)",
        (pid, NOW),
    )
    conn.commit()

    def latest_dept():
        return conn.execute(
            "SELECT exec_dept FROM dept_check WHERE project_id = ? "
            "ORDER BY checked_at DESC, id DESC LIMIT 1",
            (pid,),
        ).fetchone()[0]

    import_tab(conn, "완주", _sheet(**{"담당부서": "체육진흥과"}), SETTINGS, LATER)
    assert latest_dept() == "문화체육과"
    stats = import_tab(conn, "완주", _sheet(**{"담당부서": "시설과"}), SETTINGS, LATER)
    assert latest_dept() == "시설과"
    assert stats.overwritten == [f"{TITLE} · 실행부서 · 문화체육과 → 시설과"]


def test_a_web_edit_is_reported_once_not_on_every_later_sheet_change(conn):
    """웹 수정 뒤 시트가 두 번 바뀌면 두 번째는 시트 값을 시트 값으로 덮는 것이다."""
    import_tab(conn, "완주", _sheet(**{"착공일": "2026.03.01"}), SETTINGS, NOW)
    _web_edit(conn, "start_date", "2026-04-01")
    first = import_tab(conn, "완주", _sheet(**{"착공일": "2026.05.01"}), SETTINGS, LATER)
    second = import_tab(
        conn, "완주", _sheet(**{"착공일": "2026.06.01"}), SETTINGS, "2026-09-26T09:00:00"
    )
    assert len(first.overwritten) == 1
    assert second.overwritten == []


def test_sheet_department_is_imported_over_an_unconfirmed_candidate(conn):
    """자동 조회가 남긴 후보는 '지금 값'이 아니다. 시트 값이 확정으로 들어와야 한다."""
    import_tab(conn, "완주", _sheet(**{"담당부서": ""}), SETTINGS, NOW)
    pid = _pid(conn)
    conn.execute(
        "INSERT INTO dept_check (project_id, exec_dept, decided_by, confirmed, checked_at) "
        "VALUES (?, '시설과', 'rule', 0, '2026-09-20T00:00:00')",
        (pid,),
    )
    conn.commit()
    stats = import_tab(conn, "완주", _sheet(**{"담당부서": "시설과"}), SETTINGS, LATER)
    confirmed = conn.execute(
        "SELECT exec_dept, decided_by FROM dept_check WHERE project_id = ? AND confirmed = 1",
        (pid,),
    ).fetchall()
    assert [tuple(r) for r in confirmed] == [("시설과", "imported")]
    assert stats.overwritten == []


def test_the_sheet_does_not_overwrite_energy_from_an_installation_plan(tmp_path):
    """설치계획서는 기관이 공단에 낸 공식 자료다. 시트 값이 덮으면 안 된다."""
    conn = connect(tmp_path / "s.db")
    migrate(conn)
    org = upsert_org(conn, "전북특별자치도 완주군", SETTINGS, NOW)
    pid = ensure_project(conn, org, "체육관", "nr", NOW)
    conn.execute(
        "INSERT INTO energy_plan (project_id, source_type, capacity_kw, entered_by, updated_at) "
        "VALUES (?, '지열', 300, 'nr', ?)",
        (pid, NOW),
    )
    _apply_energy(conn, pid, "체육관", [EnergyItem("PV", 10.0)], NOW, ImportStats())
    rows = conn.execute("SELECT source_type, entered_by FROM energy_plan").fetchall()
    assert [tuple(r) for r in rows] == [("지열", "nr")]
