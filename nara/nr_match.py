"""설치계획서와 사업의 짝 찾기. DB는 후보를 읽을 때만 쓴다.

기준 값은 실제 설치계획서로 만든 정답표(tests/fixtures/nr_answer_key.json)로 맞춘다.
"""

import re
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass

AUTO_SCORE = 0.8
AUTO_MARGIN = 0.2
NEW_BELOW = 0.4
ADDRESS_BONUS = 0.1

# 2023~2024년에 이름이 바뀐 광역 지자체. 설치계획서 기관명에는 옛 이름이 남아 있다
# (실측: 관심기관 71곳 중 이름이 같은 곳 16곳 — '전라북도 완주군', '강원도 강릉시').
_REGION_RENAMES = (
    ("전라북도", "전북특별자치도"),
    ("강원도", "강원특별자치도"),
    ("제주도", "제주특별자치도"),
)
# '서초구청'·'부산광역시청'의 '청'. '교육청'은 앞 글자가 시·군·구가 아니라 남는다.
_OFFICE = re.compile(r"(?<=[시군구])청$")
_BRACKET = re.compile(r"[\[(（【][^\])）】]*[\])）】]")
# 사업명(공고명)에 붙는 조달·공사 낱말. 여기서부터 뒤를 버린다.
_CUT = ("설계", "용역", "공모", "공고", "입찰", "건립", "신축", "증축", "리모델링", "공사", "사업")
# '사업소'·'공사관'처럼 낱말 가운데 든 '사업'·'공사'에서 자르면 다른 건물이 같은 짧은
# 이름('하수처리')이 된다. 이 둘은 낱말이 끝나는 자리에서만 자른다('조성사업', '건립공사').
_CUT_AT_WORD_END = ("사업", "공사")
_PUNCT = re.compile(r"[\s·,.\-_/]")
_ROAD = re.compile(r"\S+(?:로|길)(?=\s|\d|$)")


# 시·도 이름. 설치계획서 기관명은 이것을 빼거나('강서구청') 붙여 쓴다('부산광역시기장군청').
_REGION = re.compile(r"(특별시|광역시|특별자치시|특별자치도|도)$")
_JOINED = re.compile(r"^(\S+?(?:특별시|광역시|특별자치시|특별자치도|도))(\S+[시군구])$")


def _renamed(text: str) -> str:
    for old, new in _REGION_RENAMES:
        if text.startswith(old):
            return new + text[len(old) :]
    return text


def canonical_org(
    name: str, aliases: Mapping[str, str] | None = None, address: str | None = None
) -> str:
    """나라 앱 기관명 꼴로. 시·도가 빠졌으면 주소의 시·도를 붙인다.

    '강서구청'은 서울에도 부산에도 있다. 주소 두 번째 낱말이 기관명과 같을 때만 붙인다 —
    주소가 다른 곳(본청 소재지 등)이면 잘못 붙이느니 그대로 둔다.
    """
    text = " ".join((name or "").split())
    if aliases and text in aliases:
        return aliases[text]
    text = _OFFICE.sub("", _renamed(text))
    joined = _JOINED.match(text)
    if joined:
        text = f"{joined[1]} {joined[2]}"
    words = text.split()
    addr = (address or "").split()
    if words and not _REGION.search(words[0]) and len(addr) > 1 and addr[1] == words[0]:
        region = _renamed(addr[0])
        if _REGION.search(region):
            text = f"{region} {text}"
    return text


def org_key(name: str, aliases: Mapping[str, str] | None = None, address: str | None = None) -> str:
    return canonical_org(name, aliases, address).replace(" ", "")


def _cut_index(text: str, marker: str) -> int:
    i = text.find(marker)
    while i > 0 and marker in _CUT_AT_WORD_END:
        end = i + len(marker)
        if end == len(text) or text[end].isspace():
            break
        i = text.find(marker, i + 1)
    return i


def name_key(name: str, org_name: str = "") -> str:
    """비교용 이름. 조달 낱말 뒤를 자르고 맨 앞의 시·군·구 이름을 뗀다.

    '완주군 다목적체육관 건립 설계용역'과 '완주 다목적체육관'이 둘 다 '다목적체육관'이 된다.
    """
    text = _BRACKET.sub(" ", name or "")
    cut = min((i for m in _CUT if (i := _cut_index(text, m)) > 0), default=-1)
    if cut > 0:
        text = text[:cut]
    words = text.split()
    org_words = canonical_org(org_name).split()
    town = org_words[-1] if org_words else ""
    stem = town[:-1] if len(town) > 2 and town[-1] in "시군구" else town
    if len(words) > 1 and town and words[0] in (town, stem):
        words = words[1:]
    key = _PUNCT.sub("", "".join(words))
    return key if len(key) >= 2 else _PUNCT.sub("", _BRACKET.sub("", name or ""))


def _bigrams(text: str) -> set[str]:
    return {text[i : i + 2] for i in range(len(text) - 1)} or {text}


def name_score(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if min(len(a), len(b)) >= 4 and (a in b or b in a):
        return 0.9
    x, y = _bigrams(a), _bigrams(b)
    return len(x & y) / len(x | y)


def same_road(a: str | None, b: str | None) -> bool:
    return bool(set(_ROAD.findall(a or "")) & set(_ROAD.findall(b or "")))


@dataclass(frozen=True)
class Candidate:
    project_id: int
    name: str
    org_name: str
    score: float


@dataclass(frozen=True)
class Decision:
    state: str  # auto | new | pending
    project_id: int | None
    score: float | None


def candidates(
    conn: sqlite3.Connection,
    org: str,
    name: str,
    addr: str,
    aliases: Mapping[str, str] | None = None,
    limit: int = 5,
) -> list[Candidate]:
    """같은 기관(정규화 뒤)의 사업을 점수 순으로. 숨긴 사업도 넣는다."""
    key = org_key(org, aliases, addr)
    orgs = {
        r["id"]: r["name"]
        for r in conn.execute("SELECT id, name FROM org")
        if org_key(r["name"], aliases) == key
    }
    if not orgs:
        return []
    mine = name_key(name, org)
    marks = ", ".join("?" * len(orgs))
    rows = conn.execute(
        f"SELECT id, org_id, name, address FROM project WHERE org_id IN ({marks})", list(orgs)
    ).fetchall()
    found = []
    for r in rows:
        score = name_score(mine, name_key(r["name"], orgs[r["org_id"]]))
        if score > 0 and same_road(addr, r["address"]):
            score = min(1.0, score + ADDRESS_BONUS)
        found.append(Candidate(r["id"], r["name"], orgs[r["org_id"]], round(score, 3)))
    found.sort(key=lambda c: (-c.score, c.project_id))
    return found[:limit]


def decide(cands: list[Candidate]) -> Decision:
    if not cands or cands[0].score < NEW_BELOW:
        return Decision("new", None, cands[0].score if cands else None)
    top = cands[0]
    second = cands[1].score if len(cands) > 1 else 0.0
    if top.score >= AUTO_SCORE and top.score - second >= AUTO_MARGIN:
        return Decision("auto", top.project_id, top.score)
    return Decision("pending", None, top.score)
