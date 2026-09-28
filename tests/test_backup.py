"""백업 — 쓰는 중에도 깨지지 않는 복사본, 서버 밖으로 보내기."""

import gzip
import sqlite3
from datetime import date

import pytest
from typer.testing import CliRunner

from nara import cli
from nara.backup import make_backup, prune_local, upload
from nara.db import connect, migrate

TODAY = date(2026, 9, 28)


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "n.db"
    c = connect(path)
    migrate(c)
    c.execute("INSERT INTO app_state (key, value) VALUES ('marker', 'committed')")
    c.commit()
    c.close()
    return path


def _open_packed(packed, tmp_path):
    raw = tmp_path / "restored.db"
    raw.write_bytes(gzip.decompress(packed.read_bytes()))
    return sqlite3.connect(raw)


def test_backup_is_a_compressed_database_that_opens(db, tmp_path):
    packed = make_backup(db, tmp_path / "out", TODAY)
    assert packed.name == "nara-20260928.db.gz"
    restored = _open_packed(packed, tmp_path)
    assert restored.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert restored.execute("SELECT value FROM app_state WHERE key = 'marker'").fetchone()[0] == (
        "committed"
    )
    restored.close()
    assert not (tmp_path / "out" / "nara-20260928.db").exists()


def test_backup_while_collection_writes_leaves_out_uncommitted_rows(db, tmp_path):
    """수집이 쓰는 도중에 백업해도 깨지지 않고, 커밋 전 줄은 들어가지 않는다."""
    writer = sqlite3.connect(db)
    writer.execute("BEGIN IMMEDIATE")
    writer.execute("INSERT INTO app_state (key, value) VALUES ('pending', 'x')")
    try:
        packed = make_backup(db, tmp_path / "out", TODAY)
    finally:
        writer.rollback()
        writer.close()
    restored = _open_packed(packed, tmp_path)
    assert restored.execute("SELECT 1 FROM app_state WHERE key = 'pending'").fetchone() is None
    restored.close()


def test_prune_keeps_the_last_seven_days(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    for day in ("20260920", "20260921", "20260922", "20260928"):
        (out / f"nara-{day}.db.gz").write_bytes(b"x")
    (out / "other.txt").write_text("keep")
    removed = prune_local(out, TODAY)
    assert sorted(p.name for p in removed) == ["nara-20260920.db.gz", "nara-20260921.db.gz"]
    assert (out / "other.txt").exists()


def test_upload_copies_then_trims_the_remote(tmp_path):
    calls = []
    upload(
        tmp_path / "nara-20260928.db.gz", "gdrive:nara-backup", run=lambda a, check: calls.append(a)
    )
    assert calls == [
        ["rclone", "copy", str(tmp_path / "nara-20260928.db.gz"), "gdrive:nara-backup"],
        ["rclone", "delete", "gdrive:nara-backup", "--min-age", "30d"],
    ]


def _env(tmp_path, **values):
    path = tmp_path / ".env"
    path.write_text("".join(f"{k}={v}\n" for k, v in values.items()), encoding="utf-8")
    return path


def _last_backup(db):
    c = connect(db)
    row = c.execute(
        "SELECT status FROM run_log WHERE command = 'backup' ORDER BY id DESC"
    ).fetchone()
    c.close()
    return row["status"]


def test_backup_without_a_remote_keeps_a_local_copy_and_says_partial(db, tmp_path):
    out = tmp_path / "out"
    result = CliRunner().invoke(
        cli.app, ["backup", "--db", str(db), "--out", str(out), "--env", str(_env(tmp_path))]
    )
    assert result.exit_code == 1
    assert "NARA_BACKUP_REMOTE" in result.output
    assert list(out.glob("nara-*.db.gz"))
    assert _last_backup(db) == "partial"


def test_backup_with_a_remote_uploads(db, tmp_path, monkeypatch):
    sent = []
    monkeypatch.setattr(cli, "upload_backup", lambda packed, remote: sent.append(remote))
    env = _env(tmp_path, NARA_BACKUP_REMOTE="gdrive:nara-backup")
    result = CliRunner().invoke(
        cli.app, ["backup", "--db", str(db), "--out", str(tmp_path / "out"), "--env", str(env)]
    )
    assert result.exit_code == 0, result.output
    assert sent == ["gdrive:nara-backup"]
    assert _last_backup(db) == "ok"
