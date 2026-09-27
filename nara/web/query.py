"""조회 조건을 해석하고 SQL로 바꾼다. DB도 HTTP도 모른다."""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date

from nara.verdict import BEFORE, BUILDING, DONE, UNKNOWN

SORT_KEYS = ("org", "name", "notice_date", "open_date", "verdict")
DEFAULT_SORT = "notice_date"
NO_VERDICT = "판정 전"
VERDICT_CHOICES = (BEFORE, BUILDING, DONE, UNKNOWN, NO_VERDICT)

_ISO_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
# 18자리까지만 받는다. 그보다 크면 SQLite 정수 범위(2^63-1)를 넘어 바인딩에서 터진다.
_ORG_ID = re.compile(r"[0-9]{1,18}")


@dataclass(frozen=True)
class Filters:
    orgs: tuple[int, ...] = ()
    focus_only: bool = False
    q: str = ""
    date_from: str = ""
    date_to: str = ""
    verdicts: tuple[str, ...] = ()
    sort: str = DEFAULT_SORT
    desc: bool = True

    @property
    def has_date(self) -> bool:
        return bool(self.date_from or self.date_to)


def _first(args: Mapping[str, list[str]], key: str) -> str:
    values = args.get(key) or []
    return values[0] if values else ""


def _iso_date(raw: str) -> str | None:
    """'YYYY-MM-DD'이고 실제로 있는 날짜면 그대로, 아니면 None.

    date.fromisoformat만 쓰면 '20260101'도 받아들인다. DB는 'YYYY-MM-DD'
    문자열로 비교하므로 다른 꼴이 들어오면 비교가 조용히 어긋난다.
    """
    if not _ISO_DATE.fullmatch(raw):
        return None
    try:
        date.fromisoformat(raw)
    except ValueError:
        return None
    return raw


def _parse_orgs(raw_values: list[str], notes: list[str]) -> tuple[int, ...]:
    orgs: list[int] = []
    for raw in raw_values:
        # isdigit()은 '²'에도 참이다. 그 뒤의 int()가 터진다. ASCII 숫자만 받는다.
        if not _ORG_ID.fullmatch(raw):
            notes.append(f"수요기관 값 '{raw}'은 쓸 수 없어 무시했습니다")
        elif int(raw) not in orgs:
            orgs.append(int(raw))
    return tuple(orgs)


def _parse_dates(args: Mapping[str, list[str]], notes: list[str]) -> tuple[str, str]:
    found = {"from": "", "to": ""}
    for key, label in (("from", "시작일"), ("to", "끝일")):
        raw = _first(args, key).strip()
        if not raw:
            continue
        value = _iso_date(raw)
        if value is None:
            notes.append(f"{label} 형식이 맞지 않아 무시했습니다")
        else:
            found[key] = value
    if found["from"] and found["to"] and found["from"] > found["to"]:
        notes.append("시작일이 끝일보다 늦어 걸리는 사업이 없습니다")
    return found["from"], found["to"]


def _parse_verdicts(raw_values: list[str], notes: list[str]) -> tuple[str, ...]:
    verdicts: list[str] = []
    for raw in raw_values:
        if raw not in VERDICT_CHOICES:
            notes.append(f"진행현황 값 '{raw}'은 알 수 없어 무시했습니다")
        elif raw not in verdicts:
            verdicts.append(raw)
    return tuple(verdicts)


def _parse_sort(raw: str, notes: list[str]) -> str:
    if not raw:
        return DEFAULT_SORT
    if raw not in SORT_KEYS:
        notes.append(f"정렬 기준 '{raw}'은 쓸 수 없어 공고일로 바꿨습니다")
        return DEFAULT_SORT
    return raw


def parse_filters(args: Mapping[str, list[str]]) -> tuple[Filters, list[str]]:
    """URL 인자를 조회 조건으로 바꾼다.

    못 쓰는 값은 버리고 그 사실을 notes에 적는다. 오류 화면을 띄우지 않지만
    조용히 버리지도 않는다 — 무엇을 왜 무시했는지 결과 머리에 나온다.
    """
    notes: list[str] = []
    orgs = _parse_orgs(args.get("org") or [], notes)
    date_from, date_to = _parse_dates(args, notes)
    verdicts = _parse_verdicts(args.get("verdict") or [], notes)
    sort = _parse_sort(_first(args, "sort"), notes)
    filters = Filters(
        orgs=orgs,
        focus_only=_first(args, "focus") == "1",
        q=_first(args, "q").strip(),
        date_from=date_from,
        date_to=date_to,
        verdicts=verdicts,
        sort=sort,
        desc=_first(args, "desc") != "0",
    )
    return filters, notes


def to_args(f: Filters) -> dict[str, list[str]]:
    """조회 조건을 URL 인자로 되돌린다. parse_filters와 짝이다.

    열 머리를 눌러 정렬만 바꿔도 걸어 둔 조건이 그대로 남아야 한다.
    """
    args: dict[str, list[str]] = {}
    if f.orgs:
        args["org"] = [str(i) for i in f.orgs]
    if f.focus_only:
        args["focus"] = ["1"]
    if f.q:
        args["q"] = [f.q]
    if f.date_from:
        args["from"] = [f.date_from]
    if f.date_to:
        args["to"] = [f.date_to]
    if f.verdicts:
        args["verdict"] = list(f.verdicts)
    args["sort"] = [f.sort]
    args["desc"] = ["1" if f.desc else "0"]
    return args
