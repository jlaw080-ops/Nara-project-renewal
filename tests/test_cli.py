from pathlib import Path

from typer.testing import CliRunner

from nara import __version__
from nara.cli import app


def test_version_command_prints_package_version():
    result = CliRunner().invoke(app, ["version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_nr_dupes_lists_pairs_without_changing_anything(tmp_path):
    from nara.config import load_settings
    from nara.db import connect, migrate
    from nara.store import ensure_project, upsert_org

    path = tmp_path / "d.db"
    conn = connect(path)
    migrate(conn)
    settings = load_settings(Path("config.toml"))
    org = upsert_org(conn, "부산광역시 동구", settings, "2026-10-07T00:00:00")
    g2b = ensure_project(conn, org, "좌천 어울림파크 설계용역", "g2b", "2026-10-07T00:00:00")
    nr = ensure_project(conn, org, "좌천 어울림파크", "nr", "2026-10-07T00:00:00")
    conn.close()
    result = CliRunner().invoke(app, ["nr-dupes", "--db", str(path)])
    assert result.exit_code == 0
    assert f"#{nr}" in result.output and f"#{g2b}" in result.output
    empty = CliRunner().invoke(app, ["nr-dupes", "--db", str(path), "--region", "서울특별시"])
    assert "겹치는 후보가 없습니다" in empty.output
