"""설치계획서 받는 주소 — 확장 프로그램이 부른다. 로그인 대신 토큰."""

import sqlite3
from pathlib import Path

import pytest

from nara.config import load_settings
from nara.db import connect, migrate
from nara.store import ensure_project, upsert_org
from nara.web.app import create_app

SETTINGS = load_settings(Path(__file__).resolve().parents[1] / "config.toml")
TOKEN = "test-import-token"
NOW = "2026-10-04T09:00:00"
ROW = {
    "key": "2026-001",
    "org": "전라북도 완주군",
    "name": "완주 다목적체육관",
    "addr": "",
    "start": "2027-03-01",
    "end": "2028-06-30",
    "dept": "체육진흥과",
    "energy": [{"source": "지열", "form": "수직밀폐형", "capacity_kw": 336.06}],
}


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "w.db"
    conn = connect(path)
    migrate(conn)
    org = upsert_org(conn, "전북특별자치도 완주군", SETTINGS, NOW)
    pid = ensure_project(conn, org, "완주군 다목적체육관 건립 설계용역", "g2b", NOW)
    conn.close()
    return path, pid


def _client(path, token=TOKEN, **config):
    app = create_app(path, secret_key="test-secret", import_token=token, settings=SETTINGS)
    app.testing = True
    app.config.update(config)
    return app.test_client()


def _send(client, body, auth=f"Bearer {TOKEN}", **headers):
    if auth is not None:
        headers["Authorization"] = auth
    return client.post("/api/nr-plans", json=body, headers=headers)


def _count(path, table):
    conn = sqlite3.connect(path)
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


def test_a_plan_with_the_right_token_is_saved_and_linked(db):
    path, pid = db
    resp = _send(_client(path), {"rows": [ROW]})
    assert resp.status_code == 200
    assert resp.get_json() == {
        "ok": True,
        "results": [
            {"key": "2026-001", "saved": "created", "match": "linked", "project_id": pid,
             "error": None}
        ],
    }  # fmt: skip
    assert _count(path, "energy_plan") == 1
    conn = sqlite3.connect(path)
    run = conn.execute("SELECT command, processed FROM run_log ORDER BY id DESC").fetchone()
    conn.close()
    assert run == ("nr import", 1)


@pytest.mark.parametrize(
    "auth", [None, "Bearer wrong", f"bearer {TOKEN}", f"Bearer  {TOKEN}", f"Bearer {TOKEN} ", TOKEN]
)
def test_the_token_must_match_exactly(db, auth):
    path, _ = db
    assert _send(_client(path), {"rows": [ROW]}, auth=auth).status_code == 401
    assert _count(path, "nr_plan") == 0


def test_without_a_configured_token_the_address_does_not_exist(db):
    path, _ = db
    client = _client(path, token=None)
    assert _send(client, {"rows": [ROW]}).status_code == 404
    assert client.get("/api/nr-plans/ping").status_code == 404


def test_ping_answers_with_the_token_only(db):
    path, _ = db
    client = _client(path)
    ok = client.get("/api/nr-plans/ping", headers={"Authorization": f"Bearer {TOKEN}"})
    assert (ok.status_code, ok.get_json()) == (200, {"ok": True})
    assert client.get("/api/nr-plans/ping").status_code == 401


def test_another_origin_is_fine_with_the_token(db):
    """확장 프로그램의 요청은 Origin이 chrome-extension://이다. 같은 출처 검사에서 뺀다."""
    path, _ = db
    resp = _send(_client(path), {"rows": [ROW]}, Origin="chrome-extension://abc")
    assert resp.status_code == 200


def test_a_body_that_is_not_json_is_400(db):
    path, _ = db
    client = _client(path)
    headers = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}
    assert client.post("/api/nr-plans", data="{not json", headers=headers).status_code == 400
    assert _send(client, {"row": [ROW]}).status_code == 400
    assert _send(client, ["2026-001"]).status_code == 400


def test_too_many_rows_or_too_big_a_body_is_413(db):
    path, _ = db
    client = _client(path)
    assert _send(client, {"rows": [ROW] * 201}).status_code == 413
    big = {"rows": [{**ROW, "addr": "가" * (1024 * 1024)}]}
    assert _send(client, big).status_code == 413
    assert _count(path, "nr_plan") == 0


def test_a_busy_database_answers_503(db):
    path, _ = db
    client = _client(path, WRITE_TIMEOUT=0.2)
    blocker = sqlite3.connect(path)
    blocker.execute("BEGIN IMMEDIATE")
    try:
        resp = _send(client, {"rows": [ROW]})
    finally:
        blocker.rollback()
        blocker.close()
    assert resp.status_code == 503
    assert resp.get_json()["ok"] is False
    assert _count(path, "nr_plan") == 0
