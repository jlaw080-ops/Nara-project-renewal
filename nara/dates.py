"""API가 주는 여러 날짜 표기를 ISO 한 가지로 모은다."""

import re

_DIGITS = re.compile(r"^(\d{4})(\d{2})(\d{2})")
_SEPARATED = re.compile(r"^(\d{4})[-./](\d{1,2})[-./](\d{1,2})")


def to_iso_date(value: str) -> str:
    """'202609151030' · '20260915' · '2026-09-15 10:30:00' → '2026-09-15'."""
    s = (value or "").strip()
    if not s:
        return ""
    if m := _DIGITS.match(s):
        year, month, day = m.groups()
    elif m := _SEPARATED.match(s):
        year, month, day = m.groups()
    else:
        return ""
    return f"{year}-{int(month):02d}-{int(day):02d}"


def to_display_date(iso: str) -> str:
    """'2026-09-15' → '2026.09.15'. 시트 표기에 맞춘다."""
    return iso.replace("-", ".") if iso else ""
