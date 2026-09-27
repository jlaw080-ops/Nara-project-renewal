"""웹 조회 조건 — DB 없이 확인한다."""

from nara.verdict import BEFORE, BUILDING, UNKNOWN
from nara.web.query import DEFAULT_SORT, NO_VERDICT, Filters, parse_filters, to_args


def test_parse_filters_defaults_to_newest_notice_first():
    f, notes = parse_filters({})
    assert f == Filters()
    assert (f.sort, f.desc) == ("notice_date", True)
    assert notes == []


def test_parse_filters_keeps_several_orgs_once_each():
    f, _ = parse_filters({"org": ["3", "7", "3"]})
    assert f.orgs == (3, 7)


def test_parse_filters_ignores_an_unusable_org_and_says_so():
    """'abc'는 숫자가 아니고, '²'는 isdigit()이 참인데 int()가 실패하고,
    20자리는 SQLite 정수 범위를 넘어 바인딩에서 터진다. 셋 다 500이 아니라 안내다.
    """
    f, notes = parse_filters({"org": ["3", "abc", "²", "99999999999999999999"]})
    assert f.orgs == (3,)
    assert len(notes) == 3
    assert all("수요기관" in n for n in notes)


def test_parse_filters_treats_a_blank_search_as_no_search():
    """공백 한 칸 때문에 모든 행이 걸러지면 안 된다."""
    assert parse_filters({"q": ["   "]})[0].q == ""
    assert parse_filters({"q": ["  체육관 "]})[0].q == "체육관"


def test_parse_filters_keeps_valid_dates():
    f, notes = parse_filters({"from": ["2026-01-01"], "to": ["2026-06-30"]})
    assert (f.date_from, f.date_to) == ("2026-01-01", "2026-06-30")
    assert notes == []


def test_parse_filters_ignores_a_malformed_date_and_says_so():
    """'20260101'은 date.fromisoformat이 받아들이지만 DB는 'YYYY-MM-DD' 문자열로
    비교한다. 다른 꼴이 들어오면 비교가 조용히 어긋난다.
    """
    for bad in ("어제", "2026-02-30", "20260101", "2026-1-1"):
        f, notes = parse_filters({"from": [bad]})
        assert f.date_from == "", bad
        assert notes == ["시작일 형식이 맞지 않아 무시했습니다"], bad


def test_parse_filters_explains_a_reversed_range():
    """시작일이 끝일보다 늦으면 결과가 비는 이유를 적는다. 날짜를 몰래 바꾸지 않는다."""
    f, notes = parse_filters({"from": ["2026-06-30"], "to": ["2026-01-01"]})
    assert (f.date_from, f.date_to) == ("2026-06-30", "2026-01-01")
    assert notes == ["시작일이 끝일보다 늦어 걸리는 사업이 없습니다"]


def test_parse_filters_keeps_known_verdicts_and_no_verdict():
    f, notes = parse_filters({"verdict": [BEFORE, NO_VERDICT, BEFORE]})
    assert f.verdicts == (BEFORE, NO_VERDICT)
    assert notes == []


def test_parse_filters_ignores_an_unknown_verdict_and_says_so():
    f, notes = parse_filters({"verdict": ["착공전"]})  # 괄호가 빠진 오타
    assert f.verdicts == ()
    assert len(notes) == 1


def test_parse_filters_falls_back_on_an_unknown_sort_and_says_so():
    """사용자 입력을 ORDER BY에 그대로 붙이면 주입 구멍이 된다."""
    f, notes = parse_filters({"sort": ["name; DROP TABLE project"]})
    assert f.sort == DEFAULT_SORT
    assert len(notes) == 1


def test_parse_filters_reads_the_direction():
    assert parse_filters({"desc": ["0"]})[0].desc is False
    assert parse_filters({"desc": ["1"]})[0].desc is True


def test_to_args_round_trips_through_parse_filters():
    """URL이 곧 상태다. 열 머리를 눌러 정렬을 바꿔도 걸어 둔 조건이 남아야 한다."""
    cases = [
        Filters(),
        Filters(
            orgs=(3, 7),
            focus_only=True,
            q="체육관",
            date_from="2026-01-01",
            date_to="2026-06-30",
            verdicts=(BUILDING, NO_VERDICT),
            sort="verdict",
            desc=False,
        ),
        Filters(q="100%", verdicts=(UNKNOWN,)),
    ]
    for f in cases:
        assert parse_filters(to_args(f)) == (f, [])
