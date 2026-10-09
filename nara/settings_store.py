"""웹 설정 화면이 정본인 수집·관심기관 설정. 처음 한 번만 config.toml 목록을 옮긴다."""

import hashlib
import sqlite3
from dataclasses import dataclass, replace

from nara.config import Settings
from nara.filters import is_focus_org, org_passes, title_passes
from nara.store import WEEKDAY_GROUPS

KINDS = (
    "title_required", "title_excluded", "org_excluded",
    "focus_org", "focus_exact_org", "nr_alias",
)  # fmt: skip
LABELS = {
    "title_required": "제목 필수 키워드",
    "title_excluded": "제목 제외 키워드",
    "org_excluded": "기관 제외 키워드",
    "focus_org": "관심기관 (이름에 포함)",
    "focus_exact_org": "관심기관 (이름이 정확히 같음)",
    "nr_alias": "설치계획서 기관 별칭",
}
# kind → Settings 칸. nr_alias는 (value, target) 쌍이라 따로 다룬다.
FIELDS = {
    "title_required": "title_required",
    "title_excluded": "title_excluded",
    "org_excluded": "org_excluded",
    "focus_org": "focus_orgs",
    "focus_exact_org": "focus_exact_orgs",
}
SEEDED_KEY = "settings_seeded"


def _pairs(settings: Settings) -> list[tuple[str, str, str | None]]:
    rows = [(kind, v, None) for kind, attr in FIELDS.items() for v in getattr(settings, attr)]
    return rows + [("nr_alias", a, b) for a, b in settings.nr_org_aliases]


def is_seeded(conn: sqlite3.Connection) -> bool:
    return (
        conn.execute("SELECT 1 FROM app_state WHERE key = ?", (SEEDED_KEY,)).fetchone() is not None
    )


def seed_settings(conn: sqlite3.Connection, base: Settings, now: str) -> bool:
    """처음 한 번만 파일 목록을 DB로 옮긴다. 옮겼으면 True."""
    if is_seeded(conn):
        return False
    with conn:
        for kind, value, target in _pairs(base):
            cur = conn.execute(
                "INSERT OR IGNORE INTO setting_item (kind, value, target, added_at) "
                "VALUES (?, ?, ?, ?)",
                (kind, value, target, now),
            )
            if cur.rowcount:
                conn.execute(
                    "INSERT INTO setting_log (at, kind, action, value, target) "
                    "VALUES (?, ?, 'seed', ?, ?)",
                    (now, kind, value, target),
                )
        conn.execute(
            "INSERT OR IGNORE INTO app_state (key, value) VALUES (?, ?)", (SEEDED_KEY, now)
        )
    return True


def items(conn: sqlite3.Connection, kind: str) -> list[sqlite3.Row]:
    """넣은 순서대로. 파일에서 옮긴 순서가 화면에도 그대로 보인다."""
    cur = conn.cursor()
    cur.row_factory = sqlite3.Row  # 부른 쪽 연결의 row_factory는 건드리지 않는다
    return cur.execute(
        "SELECT kind, value, target, added_at, added_by FROM setting_item "
        "WHERE kind = ? ORDER BY rowid",
        (kind,),
    ).fetchall()


def current_settings(conn: sqlite3.Connection, base: Settings) -> Settings:
    """DB 목록으로 base의 목록 칸을 바꾼다. 아직 옮기기 전이면 base 그대로."""
    if not is_seeded(conn):
        return base
    lists = {attr: tuple(r["value"] for r in items(conn, kind)) for kind, attr in FIELDS.items()}
    aliases = tuple((r["value"], r["target"]) for r in items(conn, "nr_alias"))
    return replace(base, **lists, nr_org_aliases=aliases)


def fingerprint(conn: sqlite3.Connection) -> str:
    """지금 설정 전체의 지문. 확인 화면 뒤 누가 바꿨는지 가린다."""
    rows = conn.execute(
        "SELECT kind, value, COALESCE(target, '') FROM setting_item ORDER BY kind, value"
    ).fetchall()
    text = "\n".join("\t".join(r) for r in rows)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Change:
    adds: tuple[tuple[str, str, str | None], ...] = ()  # (kind, value, target)
    removes: tuple[tuple[str, str], ...] = ()  # (kind, value)

    @property
    def empty(self) -> bool:
        return not self.adds and not self.removes

    def apply_to(self, settings: Settings) -> Settings:
        """빼고 나서 더한다. 더한 값은 목록 끝에 붙는다."""
        gone = set(self.removes)
        lists = {}
        for kind, attr in FIELDS.items():
            kept = [v for v in getattr(settings, attr) if (kind, v) not in gone]
            kept += [v for k, v, _ in self.adds if k == kind and v not in kept]
            lists[attr] = tuple(kept)
        aliases = [(a, b) for a, b in settings.nr_org_aliases if ("nr_alias", a) not in gone]
        aliases += [(v, t) for k, v, t in self.adds if k == "nr_alias"]
        return replace(settings, **lists, nr_org_aliases=tuple(aliases))


class StaleSettings(Exception):
    """확인 화면을 띄운 뒤 다른 사람이 설정을 바꿨다."""


@dataclass(frozen=True)
class HideCandidate:
    project_id: int
    name: str
    org_name: str
    reason: str


@dataclass(frozen=True)
class OrgMove:
    org_id: int
    name: str
    projects: int


@dataclass(frozen=True)
class Plan:
    change: Change
    hide: tuple[HideCandidate, ...]
    demote: tuple[OrgMove, ...]
    promote: tuple[OrgMove, ...]
    widened: bool
    fingerprint: str


def _first_hit(text: str, words: list[str]) -> str | None:
    return next((w for w in words if w in text), None)


def _hide_candidates(
    conn: sqlite3.Connection, before: Settings, after: Settings, change: Change
) -> tuple[HideCandidate, ...]:
    """바뀌기 전에는 통과했고 바뀐 뒤에는 막히는 사업만. 공고 없는 사업은 제목으로 고르지 않는다."""
    new_title = [v for k, v, _ in change.adds if k == "title_excluded"]
    gone_required = [v for k, v in change.removes if k == "title_required"]
    new_org = [v for k, v, _ in change.adds if k == "org_excluded"]
    rows = conn.execute(
        "SELECT p.id, p.name, o.name, n.title FROM project p "
        "JOIN org o ON o.id = p.org_id LEFT JOIN notice n ON n.project_id = p.id "
        "WHERE p.hidden_at IS NULL ORDER BY o.name, p.id"
    ).fetchall()
    projects: dict[int, dict] = {}
    for r in rows:
        p = projects.setdefault(r[0], {"name": r[1], "org": r[2], "titles": []})
        if r[3]:
            p["titles"].append(r[3])
    found = []
    for pid, p in projects.items():
        reason = None
        if org_passes(p["org"], before) and not org_passes(p["org"], after):
            reason = f"설정 변경: 기관 제외 키워드 '{_first_hit(p['org'], new_org)}'"
        elif (
            p["titles"]
            and any(title_passes(t, before) for t in p["titles"])
            and not any(title_passes(t, after) for t in p["titles"])
        ):
            hit = next(filter(None, (_first_hit(t, new_title) for t in p["titles"])), None)
            reason = (
                f"설정 변경: 제외 키워드 '{hit}'"
                if hit
                else f"설정 변경: 필수 키워드 '{', '.join(gone_required)}' 뺌"
            )
        if reason:
            found.append(HideCandidate(pid, p["name"], p["org"], reason))
    return tuple(found)


def _org_moves(
    conn: sqlite3.Connection, before: Settings, after: Settings
) -> tuple[tuple[OrgMove, ...], tuple[OrgMove, ...]]:
    demote, promote = [], []
    for r in conn.execute(
        "SELECT o.id, o.name, o.tier, COUNT(p.id) FROM org o "
        "LEFT JOIN project p ON p.org_id = o.id AND p.hidden_at IS NULL "
        "GROUP BY o.id ORDER BY o.name"
    ):
        was, will = is_focus_org(r[1], before), is_focus_org(r[1], after)
        if r[2] == "focus" and was and not will:
            demote.append(OrgMove(r[0], r[1], r[3]))
        elif r[2] == "rest" and will:
            promote.append(OrgMove(r[0], r[1], r[3]))
    return tuple(demote), tuple(promote)


def plan_change(conn: sqlite3.Connection, base: Settings, change: Change) -> Plan:
    """저장 전 확인 화면. DB를 바꾸지 않는다."""
    before = current_settings(conn, base)
    after = change.apply_to(before)
    demote, promote = _org_moves(conn, before, after)
    widened = any(k in ("title_excluded", "org_excluded") for k, _ in change.removes) or any(
        k == "title_required" for k, _, _ in change.adds
    )
    return Plan(
        change,
        _hide_candidates(conn, before, after, change),
        demote,
        promote,
        widened,
        fingerprint(conn),
    )


def apply_change(
    conn: sqlite3.Connection, plan: Plan, hide_ids: set[int], user_id: int | None, now: str
) -> dict[str, int]:
    """설정·숨김·관심 조정·기록을 한 트랜잭션으로. 확인 화면 뒤 설정이 바뀌었으면 거부한다."""
    from nara.web.edit import mark_hidden  # 웹 숨김과 같은 기록을 남긴다(모듈끼리 순환 방지)

    if fingerprint(conn) != plan.fingerprint:
        raise StaleSettings
    done = {"items": 0, "hidden": 0, "demoted": 0, "promoted": 0}
    with conn:
        for kind, value in plan.change.removes:
            conn.execute("DELETE FROM setting_item WHERE kind = ? AND value = ?", (kind, value))
            conn.execute(
                "INSERT INTO setting_log (at, user_id, kind, action, value) "
                "VALUES (?, ?, ?, 'remove', ?)",
                (now, user_id, kind, value),
            )
            done["items"] += 1
        for kind, value, target in plan.change.adds:
            conn.execute(
                "INSERT INTO setting_item (kind, value, target, added_at, added_by) "
                "VALUES (?, ?, ?, ?, ?)",
                (kind, value, target, now, user_id),
            )
            conn.execute(
                "INSERT INTO setting_log (at, user_id, kind, action, value, target) "
                "VALUES (?, ?, ?, 'add', ?, ?)",
                (now, user_id, kind, value, target),
            )
            done["items"] += 1
        for c in plan.hide:
            if c.project_id in hide_ids:
                done["hidden"] += mark_hidden(conn, [c.project_id], c.reason, now, user_id)
        for m in plan.demote:
            conn.execute(
                "UPDATE org SET tier = 'rest', weekday_group = ? WHERE id = ?",
                (m.org_id % WEEKDAY_GROUPS + 1, m.org_id),
            )
            done["demoted"] += 1
        for m in plan.promote:
            conn.execute(
                "UPDATE org SET tier = 'focus', weekday_group = NULL WHERE id = ?", (m.org_id,)
            )
            done["promoted"] += 1
    return done


def recent_log(conn: sqlite3.Connection, limit: int = 50) -> list[sqlite3.Row]:
    cur = conn.cursor()
    cur.row_factory = sqlite3.Row
    return cur.execute(
        "SELECT l.at, u.name AS user_name, l.kind, l.action, l.value, l.target "
        "FROM setting_log l LEFT JOIN app_user u ON u.id = l.user_id "
        "WHERE l.action != 'seed' ORDER BY l.id DESC LIMIT ?",
        (limit,),
    ).fetchall()
