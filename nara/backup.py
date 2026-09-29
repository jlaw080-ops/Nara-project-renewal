"""DB 백업. SQLite 백업 API로 쓰는 중에도 깨지지 않는 복사본을 만들어 서버 밖으로 보낸다."""

import gzip
import shutil
import sqlite3
import subprocess
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path

from nara.web.data import open_readonly

KEEP_LOCAL_DAYS = 7
KEEP_REMOTE = "30d"
KEEP_COPY_DAYS = 30


def make_backup(db_path: Path, out_dir: Path, today: date) -> Path:
    """nara-YYYYMMDD.db.gz를 만든다. 무결성 검사를 통과한 것만 남긴다."""
    out_dir.mkdir(parents=True, exist_ok=True)
    raw = out_dir / f"nara-{today:%Y%m%d}.db"
    source = open_readonly(db_path)
    target = sqlite3.connect(raw)
    try:
        source.backup(target)
        result = target.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        source.close()
        target.close()
    if result != "ok":
        raw.unlink()
        raise RuntimeError(f"백업본 무결성 검사 실패: {result}")
    packed = raw.with_name(raw.name + ".gz")
    with raw.open("rb") as fin, gzip.open(packed, "wb") as fout:
        shutil.copyfileobj(fin, fout)
    raw.unlink()
    return packed


def prune_local(out_dir: Path, today: date, keep_days: int = KEEP_LOCAL_DAYS) -> list[Path]:
    """서버 안에는 최근 keep_days일만 남긴다. 이름이 백업 꼴이 아닌 파일은 건드리지 않는다."""
    removed = []
    for path in out_dir.glob("nara-*.db.gz"):
        try:
            day = datetime.strptime(path.name[5:13], "%Y%m%d").date()
        except ValueError:
            continue
        if (today - day).days >= keep_days:
            path.unlink()
            removed.append(path)
    return removed


def copy_to_dir(packed: Path, dest: Path, today: date, keep_days: int = KEEP_COPY_DAYS) -> Path:
    """다른 폴더(예: Dropbox)에 복사하고, 그 폴더에는 최근 keep_days일만 남긴다.

    동기화 프로그램이 쓰다 만 파일을 올리지 않게 임시 이름으로 쓴 뒤 이름을 바꾼다.
    """
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / packed.name
    partial = target.with_name(target.name + ".part")
    shutil.copy2(packed, partial)
    partial.replace(target)
    prune_local(dest, today, keep_days)
    return target


def upload(packed: Path, remote: str, run: Callable = subprocess.run) -> None:
    """rclone으로 올리고, 원격에서 30일 지난 백업을 지운다."""
    run(["rclone", "copy", str(packed), remote], check=True)
    run(["rclone", "delete", remote, "--min-age", KEEP_REMOTE], check=True)
