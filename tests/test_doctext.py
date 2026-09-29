"""첨부 문서 읽기 — 형식은 확장자가 아니라 파일 앞부분으로 가린다."""

import io
import zipfile

from nara.doctext import extract_text, hwp_records_text, kind_of

OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def _hwpx(sections: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("mimetype", "application/hwp+zip")
        for name, xml in sections.items():
            z.writestr(f"Contents/{name}", xml)
    return buf.getvalue()


def _pdf(text: str) -> bytes:
    """글자 한 줄짜리 최소 PDF. 오프셋 표를 직접 계산한다."""
    stream = f"BT /F1 12 Tf 20 100 Td ({text}) Tj ET".encode()
    bodies = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 144] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(bodies, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(bodies) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(bodies) + 1,
        xref,
    )
    return bytes(out)


def _record(tag: int, payload: bytes) -> bytes:
    if len(payload) < 0xFFF:
        return (tag | (len(payload) << 20)).to_bytes(4, "little") + payload
    return (
        (tag | (0xFFF << 20)).to_bytes(4, "little") + len(payload).to_bytes(4, "little") + (payload)
    )


def test_kind_is_read_from_the_first_bytes():
    assert kind_of(b"PK\x03\x04rest") == "hwpx"
    assert kind_of(b"%PDF-1.7") == "pdf"
    assert kind_of(OLE + b"rest") == "hwp"
    assert kind_of(b'{"ErrorMsg": "no file"}') is None
    assert kind_of(b"<!DOCTYPE html>") is None


def test_hwpx_text_keeps_paragraphs_and_section_order():
    data = _hwpx(
        {
            "section10.xml": "<hp:p><hp:t>열한째</hp:t></hp:p>",
            "section2.xml": "<hp:p><hp:t>셋째</hp:t></hp:p>",
            "section0.xml": "<hp:p><hp:t>계약 문의: 재무과</hp:t></hp:p>"
            "<hp:p><hp:t>사업 담당: 건축과 &amp; 건축팀</hp:t></hp:p>",
        }
    )
    text = extract_text(data)
    assert "계약 문의: 재무과\n사업 담당: 건축과 & 건축팀" in text
    assert text.index("셋째") < text.index("열한째")


def test_pdf_text_is_extracted():
    assert "Dept Office" in extract_text(_pdf("Dept Office"))


def test_hwp_records_keep_only_paragraph_text():
    para = _record(67, "행정과 담당\r".encode("utf-16-le"))
    other = _record(66, b"\x00" * 10)
    long_para = _record(67, ("가" * 3000).encode("utf-16-le"))
    text = hwp_records_text(other + para + long_para)
    assert text.startswith("행정과 담당\n")
    assert text.count("가") == 3000


def test_a_broken_file_reads_as_empty_instead_of_failing():
    assert extract_text(b"%PDF-1.4 broken") == ""
    assert extract_text(b"PK\x03\x04 broken zip") == ""
    assert extract_text(OLE + b"broken") == ""
    assert extract_text(b"plain text") == ""


def test_hwpx_tabs_and_line_breaks_keep_words_apart():
    """문의처 줄은 탭으로 칸을 맞춘다. 태그를 지우며 글자를 붙이면 안 된다."""
    xml = (
        '<hp:p><hp:t>사업담당<hp:tab width="4000" leader="0" type="1"/>도시재생과'
        "<hp:lineBreak/>홍길동</hp:t></hp:p>"
    )
    assert "사업담당\t도시재생과\n홍길동" in extract_text(_hwpx({"section0.xml": xml}))
