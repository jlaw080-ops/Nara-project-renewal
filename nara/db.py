"""SQLite 연결과 스키마 적용."""

import sqlite3
from datetime import datetime
from importlib import resources
from pathlib import Path

from nara.sheet_memory import seed as seed_sheet_memory

SCHEMA_VERSION = 1


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def migrate(conn: sqlite3.Connection) -> int:
    """스키마를 적용하고 버전을 돌려준다. 여러 번 불러도 결과가 같다."""
    sql = resources.files("nara").joinpath("schema.sql").read_text(encoding="utf-8")
    conn.executescript(sql)
    conn.execute(
        "INSERT INTO app_state (key, value) VALUES ('schema_version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (str(SCHEMA_VERSION),),
    )
    # 2단계 도입 때 한 번. 이미 채웠으면 아무것도 하지 않는다.
    seed_sheet_memory(conn, datetime.now().isoformat(timespec="seconds"))
    conn.commit()
    return SCHEMA_VERSION
