"""웹 설정 화면이 정본인 수집·관심기관 설정. 처음 한 번만 config.toml 목록을 옮긴다."""

import hashlib
import sqlite3
from dataclasses import dataclass, replace

from nara.config import Settings

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
