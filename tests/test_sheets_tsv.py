from nara.sheets_tsv import read_tsv

HEADER = ["수요기관", "공고명", "설치계획내용", "업데이트일시"]


def _tsv(lines: list[str]) -> str:
    return "\n".join(["\t".join(HEADER), *lines])


def test_read_tsv_returns_header_and_rows():
    text = _tsv(["전북특별자치도 완주군\t완주 체육관\tPV: 10kW\t2026.09.16"])
    header, rows = read_tsv(text)
    assert header == HEADER
    assert rows == [["전북특별자치도 완주군", "완주 체육관", "PV: 10kW", "2026.09.16"]]


def test_read_tsv_merges_row_split_by_embedded_newline():
    """설치계획내용 칸의 줄바꿈이 행을 둘로 쪼갠 경우."""
    text = _tsv([
        "전북특별자치도 진안군\t진안고원 마이스테이\t지열 수직밀폐형: 663.988",
        " 태양광 고정식: 113.280\t2026.09.16",
    ])
    _, rows = read_tsv(text)
    assert len(rows) == 1
    assert rows[0][2] == "지열 수직밀폐형: 663.988 태양광 고정식: 113.280"
    assert rows[0][3] == "2026.09.16"


def test_read_tsv_pads_short_final_row():
    text = _tsv(["전북특별자치도 완주군\t완주 체육관"])
    _, rows = read_tsv(text)
    assert rows == [["전북특별자치도 완주군", "완주 체육관", "", ""]]


def test_read_tsv_keeps_blank_rows():
    text = _tsv(["\t\t\t", "전북특별자치도 완주군\t완주 체육관\t\t"])
    _, rows = read_tsv(text)
    assert len(rows) == 2
    assert rows[0] == ["", "", "", ""]


def test_read_tsv_handles_empty_body():
    header, rows = read_tsv("\t".join(HEADER))
    assert header == HEADER
    assert rows == []


def test_read_tsv_survives_a_blank_line_inside_a_cell():
    """셀 안에 문단 구분용 빈 줄이 있으면 그 물리 줄은 칸이 0개다."""
    text = "\n".join([
        "\t".join(HEADER),
        "전북특별자치도 진안군\t진안고원\t첫 줄",
        "",
        "셋째 줄\t2026.09.16",
    ])
    _, rows = read_tsv(text)
    assert len(rows) == 1
    assert rows[0][2] == "첫 줄 셋째 줄"
    assert rows[0][3] == "2026.09.16"


def test_read_tsv_truncates_a_row_wider_than_the_header():
    """칸이 남으면 자른다 — 헤더에 대응하는 열이 없어 읽을 수 없는 값이다."""
    text = "\n".join([
        "\t".join(HEADER),
        "전북특별자치도 완주군\t완주 체육관\tPV: 10kW\t2026.09.16\t여분",
    ])
    _, rows = read_tsv(text)
    assert len(rows[0]) == len(HEADER)
    assert rows[0][3] == "2026.09.16"
