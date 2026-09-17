"""설정과 자격 증명을 읽는다. 설정은 config.toml, 자격 증명은 .env."""

import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    title_required: tuple[str, ...]
    title_excluded: tuple[str, ...]
    org_excluded: tuple[str, ...]
    focus_orgs: tuple[str, ...]
    service_div_name: str
    skip_cancelled: bool


@dataclass(frozen=True)
class Secrets:
    g2b_api_key: str | None
    naver_client_id: str | None
    naver_client_secret: str | None
    anthropic_api_key: str | None


def load_settings(path: Path) -> Settings:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    collect = data.get("collect", {})
    focus = data.get("focus", {})
    return Settings(
        title_required=tuple(collect.get("title_required", [])),
        title_excluded=tuple(collect.get("title_excluded", [])),
        org_excluded=tuple(collect.get("org_excluded", [])),
        focus_orgs=tuple(focus.get("orgs", [])),
        service_div_name=collect.get("service_div_name", "기술용역"),
        skip_cancelled=bool(collect.get("skip_cancelled", True)),
    )


def _read_env(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    pairs = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        pairs[key.strip()] = value.strip()
    return pairs


def load_secrets(env_path: Path | None = None) -> Secrets:
    raw = _read_env(env_path) if env_path else {}
    pick = lambda key: raw.get(key) or None  # noqa: E731
    return Secrets(
        g2b_api_key=pick("G2B_API_KEY"),
        naver_client_id=pick("NAVER_CLIENT_ID"),
        naver_client_secret=pick("NAVER_CLIENT_SECRET"),
        anthropic_api_key=pick("ANTHROPIC_API_KEY"),
    )
