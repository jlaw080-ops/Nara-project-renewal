"""첨부 문서에서 글자를 뽑는다. 형식은 확장자가 아니라 파일 앞부분으로 판별한다.

서버가 보낸 파일 이름은 깨져 있을 수 있다. 지자체 문서는 형식이 제각각이라
한 파일을 못 읽어도 빈 문자열을 돌려주고 넘어간다.
"""

import html
import io
import re
import zipfile
import zlib

import olefile
from pypdf import PdfReader

_OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_PARA_TEXT = 67  # HWPTAG_PARA_TEXT
_SECTION = re.compile(r"Contents/section(\d+)\.xml$")
# 태그를 지우기 전에 칸 띄움을 글자로 바꾼다. 문의처 줄은 탭으로 칸을 맞추는데,
# 그냥 지우면 '사업담당<탭>도시재생과'가 '사업담당도시재생과' 한 낱말이 된다.
_HWPX_GAPS = (
    (re.compile(r"<hp:tab\b[^>]*/>"), "\t"),
    (re.compile(r"<hp:lineBreak\b[^>]*/>"), "\n"),
    (re.compile(r"<hp:(?:nbSpace|fwSpace)\b[^>]*/>"), " "),
)


def kind_of(data: bytes) -> str | None:
    if data.startswith(b"PK\x03\x04"):
        return "hwpx"
    if data.startswith(b"%PDF"):
        return "pdf"
    if data.startswith(_OLE):
        return "hwp"
    return None


def extract_text(data: bytes) -> str:
    """읽지 못하면 빈 문자열이다."""
    readers = {"hwpx": _hwpx, "pdf": _pdf, "hwp": _hwp}
    reader = readers.get(kind_of(data) or "")
    if reader is None:
        return ""
    try:
        text = reader(data)
    except Exception:  # 형식이 제각각이다. 한 파일 때문에 조회 전체가 멈추면 안 된다.
        return ""
    # HWP 본문에 섞인 서로게이트는 UTF-8로 저장할 수 없다. 대체 문자로 바꾼다.
    return text.encode("utf-8", "replace").decode("utf-8")


def _hwpx(data: bytes) -> str:
    parts = []
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        sections = [n for n in archive.namelist() if _SECTION.search(n)]
        sections.sort(key=lambda n: int(_SECTION.search(n).group(1)))
        for name in sections:
            xml = archive.read(name).decode("utf-8", "ignore")
            xml = xml.replace("</hp:p>", "\n")
            for gap, char in _HWPX_GAPS:
                xml = gap.sub(char, xml)
            parts.append(html.unescape(re.sub(r"<[^>]+>", "", xml)))
    return "\n".join(parts)


def _pdf(data: bytes) -> str:
    reader = PdfReader(io.BytesIO(data))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _hwp(data: bytes) -> str:
    with olefile.OleFileIO(io.BytesIO(data)) as ole:
        compressed = bool(ole.openstream("FileHeader").read()[36] & 1)
        sections = [e for e in ole.listdir() if e[0] == "BodyText"]
        sections.sort(key=lambda e: int(re.sub(r"\D", "", e[-1]) or 0))
        parts = []
        for entry in sections:
            raw = ole.openstream("/".join(entry)).read()
            parts.append(hwp_records_text(zlib.decompress(raw, -15) if compressed else raw))
    return "\n".join(parts)


def hwp_records_text(data: bytes) -> str:
    """HWP 본문 레코드에서 문단 글자(태그 67)만 모은다."""
    out, i, n = [], 0, len(data)
    while i + 4 <= n:
        header = int.from_bytes(data[i : i + 4], "little")
        i += 4
        tag, size = header & 0x3FF, (header >> 20) & 0xFFF
        if size == 0xFFF:
            if i + 4 > n:
                break
            size = int.from_bytes(data[i : i + 4], "little")
            i += 4
        if i + size > n:
            break
        if tag == _PARA_TEXT:
            out.append(_para_text(data[i : i + size]))
        i += size
    return "\n".join(out)


def _para_text(raw: bytes) -> str:
    chars = []
    for k in range(0, len(raw) - 1, 2):
        code = int.from_bytes(raw[k : k + 2], "little")
        if code in (10, 13):
            chars.append("\n")
        elif code < 32:
            chars.append(" ")  # 표·그림 같은 조종 문자
        else:
            chars.append(chr(code))
    return "".join(chars)
