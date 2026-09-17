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
