import pytest

from nara.dates import to_display_date, to_iso_date


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("202609151030", "2026-09-15"),
        ("20260915", "2026-09-15"),
        ("2026-09-15 10:30:00", "2026-09-15"),
        ("2026.09.15", "2026-09-15"),
        ("", ""),
        ("미정", ""),
    ],
)
def test_to_iso_date_normalises_known_shapes(raw, expected):
    assert to_iso_date(raw) == expected


def test_to_display_date_uses_dots():
    assert to_display_date("2026-09-15") == "2026.09.15"


def test_to_display_date_passes_through_empty():
    assert to_display_date("") == ""
