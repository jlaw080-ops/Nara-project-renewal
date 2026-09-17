import shutil
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx
import typer

from nara import __version__
from nara.award import update_awards
from nara.collect import backfill as run_backfill
from nara.collect import collect_range
from nara.config import load_secrets, load_settings
from nara.db import connect, migrate
from nara.doctor import run_checks
from nara.migrate_sheets import import_tab
from nara.runlog import run_log

app = typer.Typer(help="나라장터 설계용역 수집·조사 도구")

DEFAULT_DB = Path("data/nara.db")
DEFAULT_CONFIG = Path("config.toml")
DEFAULT_ENV = Path(".env")
BACKUP_DIR = Path("data/sheet_backup")


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
            added = collect_range(conn, client, secrets.g2b_api_key, settings, begin, end, counters)
    typer.echo(f"수집 완료 — 조회 {counters.processed}건 / 신규 {added}건")


@app.command()
def backfill(
    days: int = typer.Option(365, min=1, help="며칠 전까지 소급할지"),
    chunk: int = typer.Option(3, min=1, help="한 번에 조회할 기간(일)"),
    db: Path = typer.Option(DEFAULT_DB),
    config: Path = typer.Option(DEFAULT_CONFIG),
) -> None:
    """과거 공고를 소급 수집한다. 중단해도 다음 실행에서 이어진다."""
    settings = load_settings(config)
    secrets = load_secrets(DEFAULT_ENV)
    if not secrets.g2b_api_key:
        typer.echo("G2B_API_KEY가 .env에 없습니다.", err=True)
        raise typer.Exit(code=1)

    conn = _open_db(db)
    with run_log(conn, "backfill", f"--days {days}") as counters:
        with httpx.Client() as client:
            result = run_backfill(
                conn, client, secrets.g2b_api_key, settings, days, chunk, counters
            )
    state = "완료" if result.done else f"진행 중 — {result.cursor}까지"
    typer.echo(f"소급 수집 {state} / 신규 {result.added}건")


@app.command()
def doctor(db: Path = typer.Option(DEFAULT_DB, help="SQLite 경로")) -> None:
    """데이터가 서로 맞는지 점검한다. 아무것도 고치지 않는다."""
    # _open_db를 쓰지 않는다. 그건 migrate를 돌려 없는 파일을 만들어 버리므로,
    # --db에 오타를 내면 빈 DB를 새로 만들고 "이상 없음"이라고 답한다.
    # 문제를 시끄럽게 만드는 것이 이 명령의 존재 이유인데 정반대가 된다.
    if not db.exists():
        typer.echo(f"DB 파일이 없다: {db}", err=True)
        raise typer.Exit(code=1)
    conn = connect(db)
    findings = run_checks(conn, date.today().isoformat())
    if not findings:
        typer.echo("점검 통과 — 이상 없음")
        return
    for finding in findings:
        typer.echo(f"[{finding.check}] {finding.detail}")
    typer.echo(f"\n총 {len(findings)}건")
    raise typer.Exit(code=1)


enrich_app = typer.Typer(help="수집한 공고에 정보를 덧붙인다")
app.add_typer(enrich_app, name="enrich")


@enrich_app.command("award")
def enrich_award(
    tier: str = typer.Option("all", help="focus | rest | all"),
    group: int | None = typer.Option(None, help="비관심 기관 요일 그룹 1~5"),
    limit: int = typer.Option(300, min=1, help="한 번에 조회할 최대 건수"),
    db: Path = typer.Option(DEFAULT_DB),
) -> None:
    """낙찰업체를 조회해 채운다."""
    if tier not in {"focus", "rest", "all"}:
        typer.echo(f"--tier는 focus | rest | all 중 하나여야 한다: {tier!r}", err=True)
        raise typer.Exit(code=1)
    secrets = load_secrets(DEFAULT_ENV)
    if not secrets.g2b_api_key:
        typer.echo("G2B_API_KEY가 .env에 없습니다.", err=True)
        raise typer.Exit(code=1)

    conn = _open_db(db)
    selected = None if tier == "all" else tier
    with run_log(conn, "enrich award", f"--tier {tier}") as counters:
        with httpx.Client() as client:
            updated = update_awards(
                conn,
                client,
                secrets.g2b_api_key,
                date.today().isoformat(),
                selected,
                group,
                limit,
                counters,
            )
    typer.echo(
        f"낙찰 조회 — 조회 {counters.processed}건 / 기록 {updated}건 / 실패 {counters.failed}건"
    )
    if counters.failed and not updated:
        typer.echo("전체 조회 실패 — API 키나 네트워크를 확인한다.", err=True)
        raise typer.Exit(code=1)


migrate_app = typer.Typer(help="외부 데이터를 가져온다")
app.add_typer(migrate_app, name="migrate")


@migrate_app.command("tsv")
def migrate_tsv(
    path: Path = typer.Argument(..., help="내려받은 시트 탭 TSV 파일"),
    tab: str = typer.Option(..., help="탭 이름"),
    db: Path = typer.Option(DEFAULT_DB),
    config: Path = typer.Option(DEFAULT_CONFIG),
) -> None:
    """시트 탭 TSV 한 개를 DB로 옮긴다. 원본은 그대로 보관한다."""
    settings = load_settings(config)
    conn = _open_db(db)
    now = datetime.now().isoformat(timespec="seconds")

    # 되돌릴 수 있도록 원본을 먼저 복사해 둔다.
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = BACKUP_DIR / f"{stamp}_{tab}.tsv"
    shutil.copy2(path, backup)

    with run_log(conn, "migrate tsv", f"{tab}") as counters:
        stats = import_tab(conn, tab, path.read_text(encoding="utf-8"), settings, now, counters)
        counters.updated = stats.notices + stats.projects
        counters.failed = stats.skipped

    typer.echo(f"원본 보관: {backup}")
    typer.echo(
        f"[{tab}] 시트 행 {stats.rows} / 처리 {stats.imported} / 신규 공고 {stats.notices} / "
        f"신규 수기사업 {stats.projects} / 설비 {stats.energy} / 진행현황 {stats.status} / "
        f"부서 {stats.dept} / 건너뜀 {stats.skipped}"
    )
    if stats.skipped_with_data:
        typer.echo(
            f"내용이 있는데 수요기관·공고명이 비어 건너뛴 행 {len(stats.skipped_with_data)}건:",
            err=True,
        )
        for preview in stats.skipped_with_data:
            typer.echo(f"  {preview}", err=True)
        typer.echo("원본 TSV를 열어 확인한다. 자동으로 채우지 않는다.", err=True)
    typer.echo(
        f"물리 줄 {stats.physical_lines} / 복원 행 {stats.rows} / "
        f"병합 {stats.merges} / 절단 {stats.truncations}"
    )
    if stats.truncations:
        typer.echo(
            f"헤더보다 칸이 많아 잘린 행이 {stats.truncations}건 있다. "
            f"원본 TSV에서 열이 밀리지 않았는지 확인한다.",
            err=True,
        )
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
