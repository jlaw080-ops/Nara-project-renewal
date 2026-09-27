"""웹 조회 화면. 요청을 받아 query·data에 넘기고 템플릿을 그린다."""

import sqlite3
from contextlib import closing
from dataclasses import replace
from datetime import datetime
from itertools import zip_longest
from pathlib import Path

from flask import Flask, abort, current_app, g, redirect, render_template, request, url_for

from nara.web import edit
from nara.web.data import (
    BUSY_TIMEOUT_SECONDS,
    DatabaseMissing,
    ProjectDetail,
    last_runs,
    list_projects,
    open_readonly,
    open_readwrite,
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

EDIT_SECTIONS = ("info", "verdict", "dept", "energy")
BUSY_MESSAGE = "수집이 DB를 쓰고 있습니다. 잠시 뒤 다시 저장하세요"
BLANK_ENERGY_ROWS = 3


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


def _same_origin() -> bool:
    """다른 사이트가 내 브라우저로 보낸 저장 요청(CSRF)을 거른다."""
    origin = request.headers.get("Origin")
    if origin is not None:
        return origin == request.host_url.rstrip("/")
    return request.headers.get("Sec-Fetch-Site") == "same-origin"


def _candidates(d: ProjectDetail) -> dict[int, tuple[str, str | None]]:
    return {row["id"]: (row["exec_dept"], row["snippet"]) for row in d.depts if row["exec_dept"]}


def _check(section: str, d: ProjectDetail) -> edit.Checked:
    form = request.form
    if section == "info":
        latest = d.history[0].verdict if d.history else None
        return edit.check_info(form, d.project, latest)
    if section == "verdict":
        return edit.check_verdict(form)
    if section == "dept":
        return edit.check_dept(form, _candidates(d))
    return edit.check_energy(form.getlist("source"), form.getlist("capacity"))


def _save(section: str, conn: sqlite3.Connection, project_id: int, values: dict) -> list[str]:
    now = datetime.now().isoformat(timespec="seconds")
    if section == "info":
        return edit.save_info(conn, project_id, values, now)
    if section == "verdict":
        return edit.save_verdict(conn, project_id, values["verdict"], values["reason"], now)
    if section == "dept":
        return edit.save_dept(conn, project_id, values["exec_dept"], values["snippet"], now)
    return edit.save_energy(conn, project_id, values["items"], now)


def _energy_rows(d: ProjectDetail, posted: bool) -> list[tuple[str, str]]:
    """신재생 폼의 줄. 다시 보일 때는 사용자가 친 그대로, 처음에는 지금 계획 + 빈 줄."""
    if posted:
        pairs = zip_longest(
            request.form.getlist("source"), request.form.getlist("capacity"), fillvalue=""
        )
        return list(pairs)
    rows = [(e.source_type, f"{e.capacity_kw:.10g}") for e in d.energy]
    return rows + [("", "")] * BLANK_ENERGY_ROWS


def _render_detail(d: ProjectDetail, section: str | None, errors: dict, status: int = 200):
    posted = request.method == "POST"
    return (
        render_template(
            "detail.html",
            d=d,
            edit=section,
            form=request.form if posted else {},
            errors=errors,
            saved=request.args.get("saved"),
            released=request.args.get("released"),
            info_fields=edit.INFO_FORM,
            verdict_choices=edit.EDIT_VERDICTS,
            dept_candidates=[row for row in d.depts if row["exec_dept"]],
            energy_rows=_energy_rows(d, posted),
        ),
        status,
    )


def create_app(db_path: Path) -> Flask:
    app = Flask(__name__)
    app.config["DB_PATH"] = Path(db_path)
    app.add_template_filter(_dash, "dash")
    app.add_template_filter(_won, "won")
    # DNS 리바인딩으로 외부 페이지가 이 화면을 읽지 못하게 한다.
    app.config["TRUSTED_HOSTS"] = ["127.0.0.1", "localhost"]
    app.config["WRITE_TIMEOUT"] = BUSY_TIMEOUT_SECONDS

    @app.before_request
    def _guard_writes():
        if request.method == "POST" and not _same_origin():
            abort(403)

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
        section = request.args.get("edit")
        return _render_detail(d, section if section in EDIT_SECTIONS else None, {})

    @app.post("/project/<int:project_id>/edit/<section>")
    def save(project_id: int, section: str):
        if section not in EDIT_SECTIONS:
            abort(404)
        d = project_detail(get_conn(), project_id)
        if d is None:
            abort(404)
        checked = _check(section, d)
        if not checked.ok:
            return _render_detail(d, section, checked.errors, 422)
        db_path = current_app.config["DB_PATH"]
        try:
            with closing(open_readwrite(db_path, current_app.config["WRITE_TIMEOUT"])) as conn:
                changed = _save(section, conn, project_id, checked.values)
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc):
                raise
            return _render_detail(d, section, {"_form": BUSY_MESSAGE}, 503)
        return redirect(url_for("detail", project_id=project_id, saved="·".join(changed) or "-"))

    @app.post("/project/<int:project_id>/release")
    def release(project_id: int):
        if project_detail(get_conn(), project_id) is None:
            abort(404)
        now = datetime.now().isoformat(timespec="seconds")
        db_path = current_app.config["DB_PATH"]
        with closing(open_readwrite(db_path, current_app.config["WRITE_TIMEOUT"])) as conn:
            edit.release_verdict(conn, project_id, now)
        return redirect(url_for("detail", project_id=project_id, released="1"))

    return app
