from pathlib import Path

from typer.testing import CliRunner

import nara.cli as cli
from nara.cli import app
from nara.config import Secrets, load_settings
from nara.db import connect, migrate
from nara.store import ensure_project, upsert_org

SETTINGS = load_settings(Path(__file__).resolve().parents[1] / "config.toml")
NOW = "2026-09-18T09:00:00"
runner = CliRunner()


def _db(tmp_path, projects=1):
    db = tmp_path / "test.db"
    conn = connect(db)
    migrate(conn)
    org_id = upsert_org(conn, "전북특별자치도 완주군", SETTINGS, NOW)
    for i in range(projects):
        ensure_project(conn, org_id, f"사업 {i}", "manual", NOW)
    conn.close()
    return db


def test_enrich_status_rejects_a_bad_tier(tmp_path):
    result = runner.invoke(app, ["enrich", "status", "--tier", "oops", "--db", str(_db(tmp_path))])
    assert result.exit_code == 1
    assert "focus" in result.output


def test_enrich_status_rejects_nonpositive_limit(tmp_path):
    result = runner.invoke(app, ["enrich", "status", "--limit", "0", "--db", str(_db(tmp_path))])
    assert result.exit_code != 0


def test_enrich_status_says_which_steps_it_skipped(tmp_path, monkeypatch):
    """키가 없으면 그 사실이 화면에 나와야 한다 — 스펙이 요구한다."""
    monkeypatch.setattr(
        cli,
        "load_secrets",
        lambda path: Secrets(
            g2b_api_key="x", naver_client_id=None, naver_client_secret=None, anthropic_api_key=None
        ),
    )
    result = runner.invoke(app, ["enrich", "status", "--db", str(_db(tmp_path))])
    assert result.exit_code == 0
    assert "네이버" in result.output
    assert "Claude" in result.output


def test_enrich_status_reports_counts(tmp_path, monkeypatch):
    monkeypatch.setattr(
        cli,
        "load_secrets",
        lambda path: Secrets(
            g2b_api_key="x", naver_client_id=None, naver_client_secret=None, anthropic_api_key=None
        ),
    )
    result = runner.invoke(app, ["enrich", "status", "--db", str(_db(tmp_path, projects=3))])
    # R2: 출력 어디에든 3이 있으면 통과하는 느슨한 단언은 카운터가 망가져도
    # 통과한다. 실제 문구로 좁혀 "확인 3건"이 무엇을 센 값인지 함께 확인한다.
    assert "확인 3건" in result.output


def test_enrich_status_writes_a_run_log_row(tmp_path, monkeypatch):
    monkeypatch.setattr(
        cli,
        "load_secrets",
        lambda path: Secrets(
            g2b_api_key="x", naver_client_id=None, naver_client_secret=None, anthropic_api_key=None
        ),
    )
    db = _db(tmp_path)
    runner.invoke(app, ["enrich", "status", "--db", str(db)])
    conn = connect(db)
    row = conn.execute(
        "SELECT command, processed, status FROM run_log ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert row["command"] == "enrich status"
    assert row["processed"] == 1
    assert row["status"] == "ok"


def _db_with_ambiguous_project(tmp_path):
    """LLM까지 내려가야 하는 애매한 사업 하나를 담은 DB.

    tests/test_status.py의 판정 테스트들과 같은 기사(착공 '예정' 문구)를
    써서 read_news가 needs_llm=True를 내도록 만든다 — real update_statuses가
    실제로 adjudicator를 부르게 하려면 이 애매함이 필요하다.
    """
    db = tmp_path / "test.db"
    conn = connect(db)
    migrate(conn)
    org_id = upsert_org(conn, "전북특별자치도 완주군", SETTINGS, NOW)
    ensure_project(conn, org_id, "완주군 다목적체육관", "manual", NOW)
    conn.close()
    return db


def test_enrich_status_reports_llm_unanswered_when_key_present(tmp_path, monkeypatch):
    """R25: 키가 있는데 LLM이 답을 못 준 건수는 CLI가 따로 보고해야 한다.

    update_statuses를 가짜 결과로 바꿔치기하면 그 아래 진짜 파이프라인이
    llm_unanswered를 실제로 만들어내는지는 검증하지 못한다 — R25 경고
    블록을 통째로 지워도 이 테스트는 그대로 통과했다(fix round 1에서
    확인). 여기서는 진짜 update_statuses를 그대로 두고, 애매한 뉴스로
    LLM까지 내려가게 한 뒤 그 LLM이 답을 못 하도록(adjudicate → None)
    막아 llm_unanswered > 0을 실제로 만든다.
    """
    from nara.naver import SearchResult
    from nara.verdict import Article

    monkeypatch.setattr(
        cli,
        "load_secrets",
        lambda path: Secrets(
            g2b_api_key="x",
            naver_client_id=None,
            naver_client_secret=None,
            anthropic_api_key="fake-key",
        ),
    )
    ambiguous = SearchResult(
        articles=[
            Article("완주군 다목적체육관 2026년 9월 착공 예정", "", "https://n/2", "2026-08-01")
        ],
        searched=True,
    )
    monkeypatch.setattr(cli, "search_news", lambda client, secrets_, query: ambiguous)
    monkeypatch.setattr(cli, "adjudicate", lambda *args, **kwargs: None)

    result = runner.invoke(
        app, ["enrich", "status", "--db", str(_db_with_ambiguous_project(tmp_path))]
    )

    assert result.exit_code == 0
    # Claude 키가 있으니 "키가 없어…" 안내는 나오지 않는다.
    assert "Claude API 키가 없어" not in result.output
    # R25 경고 — 이 줄이 없으면 이 테스트가 실패해야 한다(fix round 1에서
    # 블록을 지우고 직접 확인함).
    assert "LLM에 물었으나 답을 못 받은 건" in result.output
    assert "1건" in result.output


def test_enrich_status_warns_when_llm_answers_go_missing(tmp_path, monkeypatch):
    """R25: LLM에 물었는데 답을 못 받은 건이 있으면 stderr로 경고한다."""
    monkeypatch.setattr(
        cli,
        "load_secrets",
        lambda path: Secrets(
            g2b_api_key="x",
            naver_client_id=None,
            naver_client_secret=None,
            anthropic_api_key="fake-key",
        ),
    )

    def fake_update_statuses(*args, **kwargs):
        from nara.status import StatusRun

        return StatusRun(
            checked=1, recorded=1, skipped=0, searched=1, asked_llm=1, llm_unanswered=1
        )

    monkeypatch.setattr(cli, "update_statuses", fake_update_statuses)
    result = runner.invoke(app, ["enrich", "status", "--db", str(_db(tmp_path))])
    assert result.exit_code == 0
    assert "LLM에 물었으나 답을 못 받은 건" in result.output
    assert "1건" in result.output


# --- Fix round 2: I1 — 네이버 검색 실패는 화면에 나와야 한다 ---


def test_enrich_status_warns_when_news_searches_failed(tmp_path, monkeypatch):
    """I1: 401로 검색이 전부 실패해도 예전에는 stderr 한 줄 없었다.

    유일한 흔적이 status_check.reason 안의 문자열 조각이었다 — 무인 스케줄
    실행에서는 아무도 안 읽는다. LLM 무응답에는 R25 경고가 있는데 네이버에는
    대칭이 없었다.

    가짜 결과로 update_statuses를 통째로 바꿔치기하지 않는다. 진짜
    파이프라인을 그대로 두고 search_news만 401로 만들어, 실패 건수가 실제로
    만들어져 올라오는지까지 확인한다.
    """
    from nara.naver import SearchResult

    monkeypatch.setattr(
        cli,
        "load_secrets",
        lambda path: Secrets(
            g2b_api_key="x",
            naver_client_id="id",
            naver_client_secret="sec",
            anthropic_api_key=None,
        ),
    )
    monkeypatch.setattr(
        cli,
        "search_news",
        lambda client, secrets_, query: SearchResult(note="뉴스 검색 실패: HTTP 401", failed=True),
    )

    result = runner.invoke(app, ["enrich", "status", "--db", str(_db(tmp_path, projects=2))])

    assert result.exit_code == 0
    assert "뉴스 검색에 실패한 건" in result.output
    assert "2건" in result.output


def test_enrich_status_stays_quiet_when_no_news_search_failed(tmp_path, monkeypatch):
    """반대 방향 — 실패가 없으면 그 경고를 내지 않는다. 키가 없어 건너뛴 것은 실패가 아니다."""
    monkeypatch.setattr(
        cli,
        "load_secrets",
        lambda path: Secrets(
            g2b_api_key="x", naver_client_id=None, naver_client_secret=None, anthropic_api_key=None
        ),
    )
    result = runner.invoke(app, ["enrich", "status", "--db", str(_db(tmp_path))])
    assert result.exit_code == 0
    assert "뉴스 검색에 실패한 건" not in result.output
