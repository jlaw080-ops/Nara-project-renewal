"""SQLite 연결과 스키마 적용."""

import sqlite3
from datetime import datetime
from importlib import resources
from pathlib import Path

from nara.sheet_memory import seed as seed_sheet_memory

SCHEMA_VERSION = 1


def attachments_dir(db_path: Path) -> Path:
    """받은 첨부를 두는 폴더. 명령과 웹이 같은 규칙으로 찾는다."""
    return Path(db_path).parent / "attachments"


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def _add_column(conn: sqlite3.Connection, table: str, column: str, decl: str) -> None:
    """표에 칸이 없으면 더한다. table·column은 이 파일의 고정 값만 받는다."""
    columns = [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


def migrate(conn: sqlite3.Connection) -> int:
    """스키마를 적용하고 버전을 돌려준다. 여러 번 불러도 결과가 같다."""
    sql = resources.files("nara").joinpath("schema.sql").read_text(encoding="utf-8")
    conn.executescript(sql)
    # CREATE TABLE IF NOT EXISTS는 이미 있는 표에 칸을 더하지 않는다. 2단계 때 만든 DB용.
    _add_column(conn, "edit_log", "user_id", "INTEGER REFERENCES app_user(id)")
    _add_column(conn, "dept_check", "confirmed", "INTEGER NOT NULL DEFAULT 1")
    _add_column(conn, "dept_check", "note", "TEXT")
    _add_column(conn, "attachment", "seq", "INTEGER")
    conn.execute(
        "INSERT INTO app_state (key, value) VALUES ('schema_version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (str(SCHEMA_VERSION),),
    )
    # 2단계 도입 때 한 번. 이미 채웠으면 아무것도 하지 않는다.
    seed_sheet_memory(conn, datetime.now().isoformat(timespec="seconds"))
    conn.commit()
    return SCHEMA_VERSION
