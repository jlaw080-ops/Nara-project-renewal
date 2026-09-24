from pathlib import Path

import pytest
from typer.testing import CliRunner

import nara.cli as cli
from nara.cli import app
from nara.config import Secrets, load_settings
from nara.db import connect, migrate
from nara.naver import SearchResult
from nara.store import ensure_project, upsert_org
from nara.verdict import Article

SETTINGS = load_settings(Path(__file__).resolve().parents[1] / "config.toml")
NOW = "2026-09-18T09:00:00"
runner = CliRunner()


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """테스트가 실제 구글에 나가지 않게 막는다.

    네이버 시절에는 키가 없으면 search_news가 일찍 돌아와 호출이 없었다.
    구글 RSS는 키를 요구하지 않아 그 우연한 차단이 사라졌다 — 실제로
    news.google.com에 9번 나가는 것을 확인하고 막았다. 망에 기대는
    테스트는 오프라인에서 깨지고 느리고 들쭉날쭉하다.
    """
    monkeypatch.setattr(
        cli, "search_news", lambda client, secrets, query: SearchResult(searched=True)
    )


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
    """줄어든 기능과 건너뛴 단계가 화면에 나와야 한다 — 스펙이 요구한다.

    구글 뉴스는 키를 요구하지 않아 '검색을 건너뛴다'는 안내가 없다. 대신
    본문이 오지 않는다는 사실을 말해야 한다 — 그게 판정을 약하게 만드는
    줄어든 기능이고, 조용히 넘어가면 제목만 읽은 회차를 온전한 판정으로
    착각하게 된다.
    """
    monkeypatch.setattr(
        cli,
        "load_secrets",
        lambda path: Secrets(
            g2b_api_key="x", naver_client_id=None, naver_client_secret=None, anthropic_api_key=None
        ),
    )
    result = runner.invoke(app, ["enrich", "status", "--db", str(_db(tmp_path))])
    assert result.exit_code == 0
    assert "본문" in result.output
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


# --- Fix round 2: I3 — 무테스트로 살아남던 CLI 블록 두 개 ---


def test_enrich_status_exits_nonzero_when_every_project_failed(tmp_path, monkeypatch):
    """전건 실패는 exit 1이다 — 기록 0건은 조용한 정상 회차와 똑같이 보인다.

    이 블록은 `if False:`로 막아도 288개 테스트가 전부 통과했다. 무인
    스케줄이 이 종료 코드로 회차 실패를 알아차리므로, 여기가 조용해지면
    판정 로직이 전부 죽은 날과 아무것도 안 바뀐 날이 구분되지 않는다.

    update_statuses를 바꿔치기하지 않는다 — 진짜 파이프라인을 두고
    search가 사업마다 터지게 해서 실패를 실제로 만든다.
    """
    monkeypatch.setattr(
        cli,
        "load_secrets",
        lambda path: Secrets(
            g2b_api_key="x", naver_client_id=None, naver_client_secret=None, anthropic_api_key=None
        ),
    )

    def exploding_search(client, secrets_, query):
        raise RuntimeError("판정이 죽었다")

    monkeypatch.setattr(cli, "search_news", exploding_search)

    result = runner.invoke(app, ["enrich", "status", "--db", str(_db(tmp_path, projects=3))])

    assert result.exit_code == 1
    assert "전체 판정 실패" in result.output


def test_enrich_status_exits_zero_when_only_some_projects_failed(tmp_path, monkeypatch):
    """반대 방향 — 일부만 실패하면 회차는 성공이다. 나머지 판정은 쓸모가 있다."""
    monkeypatch.setattr(
        cli,
        "load_secrets",
        lambda path: Secrets(
            g2b_api_key="x", naver_client_id=None, naver_client_secret=None, anthropic_api_key=None
        ),
    )

    def flaky_search(client, secrets_, query):
        if "사업 1" in query:
            raise RuntimeError("한 건만 죽는다")
        from nara.naver import SearchResult

        return SearchResult(note="네이버 검색 키가 없어 뉴스 검색을 건너뛰었다")

    monkeypatch.setattr(cli, "search_news", flaky_search)

    result = runner.invoke(app, ["enrich", "status", "--db", str(_db(tmp_path, projects=3))])

    assert result.exit_code == 0
    assert "전체 판정 실패" not in result.output


def test_enrich_status_says_it_stopped_on_the_time_budget(tmp_path, monkeypatch):
    """시간 예산으로 멈춘 회차는 그 사실을 말해야 한다.

    이 안내도 `if False:`로 막아도 전부 통과했다. 말하지 않으면 예산에
    걸려 절반만 본 회차가 전부 본 회차와 똑같아 보인다 — 남은 대상이
    계속 밀리고 있어도 아무도 모른다.
    """
    monkeypatch.setattr(
        cli,
        "load_secrets",
        lambda path: Secrets(
            g2b_api_key="x", naver_client_id=None, naver_client_secret=None, anthropic_api_key=None
        ),
    )
    # 진짜 update_statuses를 그대로 돌리고 시계만 갈아 끼운다. 가짜 결과로
    # 바꿔치기하면 stopped_early가 실제로 만들어지는지 검증하지 못한다.
    # now_fn은 기본값으로 import 시점에 묶여 있어 모듈 속성을 갈아도 안 먹는다.
    real_update = cli.update_statuses
    calls = {"n": -1}

    def fake_now():
        calls["n"] += 1
        return calls["n"] * 100.0  # 0, 100, 200 — --budget 1초를 두 번째 호출에서 넘긴다

    monkeypatch.setattr(
        cli,
        "update_statuses",
        lambda *args, **kwargs: real_update(*args, **kwargs, now_fn=fake_now),
    )

    result = runner.invoke(
        app,
        ["enrich", "status", "--budget", "1", "--db", str(_db(tmp_path, projects=3))],
    )

    assert result.exit_code == 0
    assert "시간 예산 1초를 넘겨 멈췄다" in result.output


def test_enrich_status_stays_quiet_when_the_budget_was_enough(tmp_path, monkeypatch):
    """반대 방향 — 예산 안에 다 봤으면 그 안내를 내지 않는다."""
    monkeypatch.setattr(
        cli,
        "load_secrets",
        lambda path: Secrets(
            g2b_api_key="x", naver_client_id=None, naver_client_secret=None, anthropic_api_key=None
        ),
    )
    result = runner.invoke(app, ["enrich", "status", "--db", str(_db(tmp_path, projects=3))])
    assert result.exit_code == 0
    assert "시간 예산" not in result.output


def test_enrich_status_label_says_it_counts_searches_not_news_verdicts(tmp_path, monkeypatch):
    """'뉴스 근거 N건'은 뉴스로 판정한 건수가 아니라 검색이 돌아간 건수였다.

    검색해서 아무 신호도 못 찾은 건까지 세므로, 라벨을 믿으면 뉴스 근거가
    N건 있다고 읽는다. 숫자는 그대로 두고 라벨만 실제로 세는 것에 맞춘다.
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
    # 검색은 성공하지만 판정에 쓸 신호가 없는 기사 — 뉴스로 판정한 건은 0이다.
    monkeypatch.setattr(
        cli,
        "search_news",
        lambda client, secrets_, query: SearchResult(
            articles=[Article("완주군 군민 체육대회 성황", "", "https://n/x", "2026-08-01")],
            searched=True,
        ),
    )

    result = runner.invoke(app, ["enrich", "status", "--db", str(_db(tmp_path))])

    assert result.exit_code == 0
    assert "뉴스 검색 1건" in result.output
    assert "뉴스 근거" not in result.output
