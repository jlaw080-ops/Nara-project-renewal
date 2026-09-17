import typer

from nara import __version__

app = typer.Typer(help="나라장터 설계용역 수집·조사 도구")


@app.callback()
def callback() -> None:
    """나라장터 설계용역 수집·조사 도구."""


@app.command()
def version() -> None:
    """버전을 출력한다."""
    typer.echo(f"nara {__version__}")


if __name__ == "__main__":
    app()
