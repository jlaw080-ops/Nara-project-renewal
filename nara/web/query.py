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


LIST_LIMIT = 1000

# 사업마다 가장 최근 공고·판정·실행부서를 하나씩 고른다. 판정 순서는
# 파이프라인 전체가 쓰는 규칙(checked_at 내림차순, 같으면 id)과 같다.
# 실행부서는 이름이 있는 줄만 본다 — 최근 조회가 빈 값이어도 앞서 찾은 부서를
# 지우지 않는다.
_LATEST = """
WITH ln AS (
    SELECT n.project_id, n.bid_no, n.title, n.notice_date, n.open_date,
           ROW_NUMBER() OVER (
               PARTITION BY n.project_id
               ORDER BY COALESCE(n.notice_date, '') DESC, n.bid_no DESC
           ) AS rn
    FROM notice n
    WHERE n.project_id IS NOT NULL
),
ls AS (
    SELECT s.project_id, s.verdict,
           ROW_NUMBER() OVER (
               PARTITION BY s.project_id ORDER BY s.checked_at DESC, s.id DESC
           ) AS rn
    FROM status_check s
),
ld AS (
    SELECT d.project_id, d.exec_dept,
           ROW_NUMBER() OVER (
               PARTITION BY d.project_id ORDER BY d.checked_at DESC, d.id DESC
           ) AS rn
    FROM dept_check d
    WHERE d.project_id IS NOT NULL AND COALESCE(d.exec_dept, '') != ''
)
"""

_FROM = """
FROM project p
JOIN org o ON o.id = p.org_id
LEFT JOIN ln ON ln.project_id = p.id AND ln.rn = 1
LEFT JOIN ls ON ls.project_id = p.id AND ls.rn = 1
LEFT JOIN ld ON ld.project_id = p.id AND ld.rn = 1
LEFT JOIN award a ON a.bid_no = ln.bid_no
"""

_ORDER_EXPR = {
    "org": "o.name",
    "name": "p.name",
    "notice_date": "NULLIF(ln.notice_date, '')",
    "open_date": "NULLIF(ln.open_date, '')",
    # 가나다순이면 '미확인·시공 중·준공 완료·착공 전'이 된다. 단계순으로 매긴다.
    "verdict": "CASE ls.verdict WHEN ? THEN 1 WHEN ? THEN 2 WHEN ? THEN 3 WHEN ? THEN 4 END",
}
_STAGE_ORDER = (BEFORE, BUILDING, DONE, UNKNOWN)
_ESCAPE = "ESCAPE '\\'"


def like_pattern(text: str) -> str:
    """LIKE용 '%…%'. 사용자가 친 %·_·\\는 글자 그대로 찾는다.

    '100%'를 찾을 때 %가 와일드카드면 모든 행이 걸린다.
    """
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _where(f: Filters, include_dates: bool) -> tuple[str, list]:
    clauses: list[str] = []
    params: list = []
    if f.orgs:
        clauses.append(f"p.org_id IN ({', '.join('?' * len(f.orgs))})")
        params.extend(f.orgs)
    if f.focus_only:
        clauses.append("o.tier = 'focus'")
    if f.q:
        # 공고명만 찾으면 시트에서 이관한 사업(공고 없음)은 이름으로 영영 못 찾는다.
        clauses.append(f"(p.name LIKE ? {_ESCAPE} OR ln.title LIKE ? {_ESCAPE})")
        params.extend([like_pattern(f.q)] * 2)
    # 기간은 행에 보이는 그 공고의 공고일로 거른다. 공고 없는 사업은 여기서 빠진다.
    if include_dates and f.date_from:
        clauses.append("ln.notice_date >= ?")
        params.append(f.date_from)
    if include_dates and f.date_to:
        clauses.append("ln.notice_date <= ?")
        params.append(f.date_to)
    if f.verdicts:
        known = [v for v in f.verdicts if v != NO_VERDICT]
        parts: list[str] = []
        if known:
            parts.append(f"ls.verdict IN ({', '.join('?' * len(known))})")
            params.extend(known)
        if NO_VERDICT in f.verdicts:
            parts.append("ls.verdict IS NULL")
        clauses.append(f"({' OR '.join(parts)})")
    return (" WHERE " + " AND ".join(clauses)) if clauses else "", params


def _order(f: Filters) -> tuple[str, list]:
    # 정렬 값을 여기서도 믿지 않는다. Filters는 parse_filters 없이도 만들 수 있다.
    key = f.sort if f.sort in _ORDER_EXPR else DEFAULT_SORT
    expr = _ORDER_EXPR[key]
    direction = "DESC" if f.desc else "ASC"
    # 값이 없는 행은 방향과 관계없이 맨 뒤. 같으면 id로 순서를 고정한다 —
    # 새로고침할 때마다 순서가 바뀌면 안 된다. expr이 두 번 나오므로 인자도 두 벌이다.
    sql = f" ORDER BY ({expr}) IS NULL, {expr} {direction}, p.id"
    params = list(_STAGE_ORDER) * 2 if key == "verdict" else []
    return sql, params


def build_list_query(f: Filters) -> tuple[str, list]:
    """목록 SQL과 인자. 자리표시자의 순서와 인자의 순서가 같아야 한다."""
    matched_sql, matched_params = "NULL", []
    if f.q:
        # 목록엔 사업명만 보인다. 공고명으로만 걸린 행은 그 공고명을 함께 돌려준다.
        matched_sql = (
            f"CASE WHEN p.name NOT LIKE ? {_ESCAPE} AND ln.title LIKE ? {_ESCAPE} THEN ln.title END"
        )
        matched_params = [like_pattern(f.q)] * 2
    where_sql, where_params = _where(f, include_dates=True)
    order_sql, order_params = _order(f)
    sql = (
        _LATEST
        + "SELECT p.id, o.name AS org_name, p.name, ln.title AS notice_title, "
        + "ln.notice_date, ln.open_date, ls.verdict, a.winner, ld.exec_dept, p.zeb_grade, "
        + f"{matched_sql} AS matched_title"
        + _FROM
        + where_sql
        + order_sql
        + " LIMIT ?"
    )
    return sql, [*matched_params, *where_params, *order_params, LIST_LIMIT]


def build_count_query(f: Filters) -> tuple[str, list]:
    where_sql, params = _where(f, include_dates=True)
    return _LATEST + "SELECT COUNT(*)" + _FROM + where_sql, params


def build_excluded_query(f: Filters) -> tuple[str, list] | None:
    """기간 조건 때문에 빠진 '공고 없는 사업' 수. 기간 조건이 없으면 None.

    고정값 95가 아니다. 그때의 다른 조건에 걸리는 공고 없는 사업만 센다.
    """
    if not f.has_date:
        return None
    where_sql, params = _where(f, include_dates=False)
    joiner = " AND " if where_sql else " WHERE "
    sql = _LATEST + "SELECT COUNT(*)" + _FROM + where_sql + joiner + "ln.bid_no IS NULL"
    return sql, params
