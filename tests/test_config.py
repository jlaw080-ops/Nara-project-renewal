from pathlib import Path

from nara.config import load_secrets, load_settings

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_load_settings_reads_repo_config():
    settings = load_settings(REPO_ROOT / "config.toml")
    assert settings.title_required == ("설계",)
    assert "감리" in settings.title_excluded
    assert "교육청" in settings.org_excluded
    assert "전북특별자치도" in settings.focus_orgs
    assert settings.service_div_name == "기술용역"
    assert settings.skip_cancelled is True


def test_load_settings_keeps_every_focus_org():
    """목록이 잘려서 들어오지 않았는지 본다.

    확인해야 하는 것은 '목록이 잘리지 않았다'이다. 위 판정 표대로 관심 기관 19개,
    제목 제외 68개를 config.toml에 그대로 옮겼으면 그대로 통과한다.
    """
    settings = load_settings(REPO_ROOT / "config.toml")
    assert len(settings.focus_orgs) == 19
    assert len(settings.title_excluded) == 68
    assert len(settings.org_excluded) == 7


def test_load_secrets_reads_env_file(tmp_path):
    env = tmp_path / ".env"
    env.write_text("G2B_API_KEY=abc123\nNAVER_CLIENT_ID=\n", encoding="utf-8")
    secrets = load_secrets(env)
    assert secrets.g2b_api_key == "abc123"
    assert secrets.naver_client_id is None


def test_load_secrets_returns_none_when_file_missing(tmp_path):
    secrets = load_secrets(tmp_path / "nope.env")
    assert secrets.g2b_api_key is None
