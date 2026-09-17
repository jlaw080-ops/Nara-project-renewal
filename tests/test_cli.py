from typer.testing import CliRunner

from nara import __version__
from nara.cli import app


def test_version_command_prints_package_version():
    result = CliRunner().invoke(app, ["version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout
