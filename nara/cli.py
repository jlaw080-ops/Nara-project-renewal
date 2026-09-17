from datetime import datetime, timedelta
from pathlib import Path

import httpx
import typer

from nara import __version__
from nara.collect import collect_range
from nara.config import load_secrets, load_settings
from nara.db import connect, migrate
from nara.runlog import run_log

app = typer.Typer(help="나라장터 설계용역 수집·조사 도구")

DEFAULT_DB = Path("data/nara.db")
DEFAULT_CONFIG = Path("config.toml")
DEFAULT_ENV = Path(".env")


def _open_db(db: Path):
    conn = connect(db)
    migrate(conn)
    return conn


@app.callback()
def callback() -> None:
    """나라장터 설계용역 수집·조사 도구."""


@app.command()
def version() -> None:
    """버전을 출력한다."""
    typer.echo(f"nara {__version__}")


@app.command()
def collect(
    days: int = typer.Option(3, min=1, help="오늘로부터 며칠 전까지 조회할지"),
    db: Path = typer.Option(DEFAULT_DB, help="SQLite 경로"),
    config: Path = typer.Option(DEFAULT_CONFIG),
) -> None:
    """최근 N일치 설계용역 공고를 수집한다."""
    settings = load_settings(config)
    secrets = load_secrets(DEFAULT_ENV)
    if not secrets.g2b_api_key:
        typer.echo("G2B_API_KEY가 .env에 없습니다.", err=True)
        raise typer.Exit(code=1)

    end = datetime.now()
    begin = end - timedelta(days=days)
    conn = _open_db(db)
    with run_log(conn, "collect", f"--days {days}") as counters:
        with httpx.Client() as client:
            added = collect_range(
                conn, client, secrets.g2b_api_key, settings, begin, end, counters
            )
    typer.echo(f"수집 완료 — 조회 {counters.processed}건 / 신규 {added}건")


if __name__ == "__main__":
    app()
