from pathlib import Path

from nara.config import load_secrets, load_settings

REPO_ROOT = Path(__file__).resolve().parents[1]
# 2026-10-01 사용자 지시. '제설'·'보도'·'거리'는 '국제설계'·'정보도서관'·'사거리' 안에 들어
# 있어 건축 공고까지 빠지므로, 사용자가 고른 대체어(제설기지류·보도 공사류·거리 조성류)로 넣었다.
ADDED_2026_10_01 = (
    "옹벽", "스프링클러", "계통", "수관", "도시숲", "연결로", "램프", "관리사업",
    "보수공사", "교통사고", "안전시설", "산책로", "대교", "가로숲", "유지용수",
    "저류조", "빗물펌프장", "오르락", "엘리베이터",
    "제설 전진기지", "제설전진기지", "제설기지", "제설창고",
    "횡단보도", "보도확장", "보도정비", "보도블록", "보도블럭",
    "거리 조성", "거리조성", "거리 정비", "거리정비",
)  # fmt: skip


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

    확인해야 하는 것은 '목록이 잘리지 않았다'이다. 시트 설정 탭에서 옮긴
    관심 기관 23개 · 제목 제외 80개 · 기관 제외 8개가 기준선이고, 여기에
    사용자가 지시한 산림 작업 3개와 2026-10-01 지시 32개를 더해 제목 제외는
    115개다. 서울은 본청과 25개 구청만 이름이 정확히 같을 때 관심이다
    (2026-09-30 사용자 지시). 시트 설정 탭에 그것들을 넣으면 숫자는 그대로 간다.
    """
    settings = load_settings(REPO_ROOT / "config.toml")
    assert len(settings.focus_orgs) == 23
    assert len(settings.title_excluded) == 115
    assert len(settings.org_excluded) == 8
    # 시트보다 앞서 있는 것들. 시트에 반영되기 전까지 여기가 유일한 기록이다.
    for keyword in ("덩굴제거", "숲가꾸기", "산불예방", *ADDED_2026_10_01):
        assert keyword in settings.title_excluded
    seoul = settings.focus_exact_orgs
    assert "서울특별시" in seoul and "서울특별시" not in settings.focus_orgs
    districts = [n for n in seoul if n.startswith("서울특별시 ") and n.endswith("구")]
    assert len(districts) == len(set(districts)) == 25
    assert len(seoul) == 26


def test_load_secrets_reads_env_file(tmp_path):
    env = tmp_path / ".env"
    env.write_text("G2B_API_KEY=abc123\nNAVER_CLIENT_ID=\n", encoding="utf-8")
    secrets = load_secrets(env)
    assert secrets.g2b_api_key == "abc123"
    assert secrets.naver_client_id is None


def test_load_secrets_returns_none_when_file_missing(tmp_path):
    secrets = load_secrets(tmp_path / "nope.env")
    assert secrets.g2b_api_key is None


def test_load_secrets_reads_the_import_token(tmp_path):
    env = tmp_path / ".env"
    env.write_text("NARA_IMPORT_TOKEN=test-import-token\n", encoding="utf-8")
    assert load_secrets(env).import_token == "test-import-token"


def test_load_settings_reads_org_aliases_for_installation_plans(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text(
        (REPO_ROOT / "config.toml").read_text(encoding="utf-8")
        + '\n[nr.org_aliases]\n"전라북도교육청" = "전북특별자치도교육청"\n',
        encoding="utf-8",
    )
    settings = load_settings(config)
    assert settings.nr_org_aliases == (("전라북도교육청", "전북특별자치도교육청"),)


def test_load_settings_has_no_org_aliases_by_default():
    assert load_settings(REPO_ROOT / "config.toml").nr_org_aliases == ()
