"""웹 조회 화면이 읽는 자료. DB는 읽기 전용으로만 연다."""

import sqlite3
from pathlib import Path
from urllib.parse import quote


class DatabaseMissing(FileNotFoundError):
    """DB 파일이 없다. 빈 DB를 새로 만들지 않고 멈춘다."""


def open_readonly(db_path: Path) -> sqlite3.Connection:
    """읽기 전용 연결을 연다.

    `nara.db.connect`를 쓰지 않는다. 그 함수는 폴더를 만들고 일반 모드로 열어
    없는 파일을 새로 만든다 — 오타 난 경로가 '자료 0건'으로 조용히 보인다.

    경로는 URL 인코딩한다. '#'이 든 경로를 URI에 그대로 넣으면 SQLite가 그
    뒤를 조각으로 잘라 엉뚱한 DB를 열고, 오류 대신 'no such table'만 낸다.
    """
    if not db_path.exists():
        raise DatabaseMissing(f"DB 파일이 없다: {db_path}")
    uri = f"file:{quote(db_path.resolve().as_posix(), safe='/:')}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn
