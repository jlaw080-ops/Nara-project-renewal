"""웹 조회 화면. 요청을 받아 query·data에 넘기고 템플릿을 그린다."""

import sqlite3
from dataclasses import replace
from pathlib import Path

from flask import Flask, abort, current_app, g, render_template, request, url_for

from nara.web.data import (
    DatabaseMissing,
    last_runs,
    list_projects,
    open_readonly,
    org_options,
    project_detail,
)
from nara.web.query import (
    NO_VERDICT,
    SORT_KEYS,
    VERDICT_CHOICES,
    Filters,
    parse_filters,
    to_args,
)


def get_conn() -> sqlite3.Connection:
    """요청마다 읽기 전용 연결 하나. sqlite3 연결은 만든 스레드에서만 쓸 수 있다."""
    if "conn" not in g:
        g.conn = open_readonly(current_app.config["DB_PATH"])
    return g.conn


def _dash(value):
    return "—" if value is None or value == "" else value


def _won(value):
    return "—" if value is None or value == "" else f"{int(value):,}원"


def _conditions(f: Filters, org_names: dict[int, str]) -> list[str]:
    """결과 머리에 되풀이할 조건. 없는 기관 id도 지우지 않고 그대로 보인다."""
    parts = [org_names.get(i, f"없는 기관 #{i}") for i in f.orgs]
    if f.focus_only:
        parts.append("관심기관만")
    if f.q:
        parts.append(f'"{f.q}"')
    if f.has_date:
        parts.append(f"공고일 {f.date_from}~{f.date_to}")
    parts.extend(f.verdicts)
    return parts


def _sort_links(f: Filters) -> dict[str, str]:
    """열 머리 링크. 지금 정렬 중인 열이면 방향을 뒤집고, 다른 열이면 오름차순으로 간다."""
    links = {}
    for key in SORT_KEYS:
        desc = (not f.desc) if key == f.sort else False
        links[key] = url_for("index", **to_args(replace(f, sort=key, desc=desc)))
    return links


def create_app(db_path: Path) -> Flask:
    app = Flask(__name__)
    app.config["DB_PATH"] = Path(db_path)
    app.add_template_filter(_dash, "dash")
    app.add_template_filter(_won, "won")

    @app.teardown_appcontext
    def _close(_exc):
        conn = g.pop("conn", None)
        if conn is not None:
            conn.close()

    @app.errorhandler(DatabaseMissing)
    def _missing(exc):
        # 서버를 띄운 뒤 DB 파일이 사라진 경우다. 추적 화면 대신 이유를 말한다.
        return str(exc), 503, {"Content-Type": "text/plain; charset=utf-8"}

    @app.get("/")
    def index():
        f, notes = parse_filters({k: request.args.getlist(k) for k in request.args})
        conn = get_conn()
        orgs = org_options(conn)
        return render_template(
            "list.html",
            f=f,
            notes=notes,
            result=list_projects(conn, f),
            runs=last_runs(conn),
            orgs=orgs,
            conditions=_conditions(f, {o["id"]: o["name"] for o in orgs}),
            sort_links=_sort_links(f),
            verdict_choices=VERDICT_CHOICES,
            no_verdict=NO_VERDICT,
        )

    @app.get("/project/<int:project_id>")
    def detail(project_id: int):
        d = project_detail(get_conn(), project_id)
        if d is None:
            abort(404)
        return render_template("detail.html", d=d)

    return app
