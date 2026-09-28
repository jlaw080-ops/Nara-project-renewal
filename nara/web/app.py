"""웹 조회 화면. 요청을 받아 query·data에 넘기고 템플릿을 그린다."""

import sqlite3
from contextlib import closing
from dataclasses import replace
from datetime import datetime, timedelta
from itertools import zip_longest
from pathlib import Path

from flask import (
    Flask,
    abort,
    current_app,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.middleware.proxy_fix import ProxyFix

from nara import auth
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
CONFLICT_BY = "그사이 {}님이 고쳤습니다. 지금 값을 확인하고 다시 저장하세요"
CONFLICT = "그사이 값이 바뀌었습니다. 지금 값을 확인하고 다시 저장하세요"
BLANK_ENERGY_ROWS = 3
SESSION_LIFETIME = timedelta(days=14)
PUBLIC_ENDPOINTS = {"login", "static"}
PASSWORD_ENDPOINTS = {"change_password", "logout"}


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


def _safe_next(raw: str | None) -> str:
    """로그인 뒤 돌아갈 곳. 이 사이트 안의 경로만 받는다."""
    target = (raw or "").strip()
    if target.startswith("/") and not target.startswith(("//", "/\\")):
        return target
    return "/"


def _current_user() -> auth.User | None:
    uid = session.get("uid")
    if not isinstance(uid, int):
        return None
    return auth.get_user(get_conn(), uid)


def _rw_conn() -> sqlite3.Connection:
    return open_readwrite(current_app.config["DB_PATH"], current_app.config["WRITE_TIMEOUT"])


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
    uid = g.user.id
    if section == "info":
        return edit.save_info(conn, project_id, values, now, uid)
    if section == "verdict":
        return edit.save_verdict(conn, project_id, values["verdict"], values["reason"], now, uid)
    if section == "dept":
        return edit.save_dept(conn, project_id, values["exec_dept"], values["snippet"], now, uid)
    return edit.save_energy(conn, project_id, values["items"], now, uid)


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
            versions={s: edit.version_of(get_conn(), d.project["id"], s) for s in EDIT_SECTIONS},
        ),
        status,
    )


def create_app(db_path: Path, secret_key: str, host: str | None = None) -> Flask:
    if not secret_key:
        raise ValueError("세션 서명 키가 없다 — .env의 NARA_SECRET_KEY를 채운다")
    app = Flask(__name__)
    app.secret_key = secret_key
    app.config["DB_PATH"] = Path(db_path)
    app.add_template_filter(_dash, "dash")
    app.add_template_filter(_won, "won")
    # DNS 리바인딩으로 외부 페이지가 이 화면을 읽지 못하게 한다.
    app.config["TRUSTED_HOSTS"] = ["127.0.0.1", "localhost", *([host] if host else [])]
    app.config["WRITE_TIMEOUT"] = BUSY_TIMEOUT_SECONDS
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=bool(host),
        PERMANENT_SESSION_LIFETIME=SESSION_LIFETIME,
    )
    if host:
        # Caddy 뒤에서는 요청이 http로 들어온다. 브라우저 Origin은 https라 그대로 두면
        # 같은 출처 확인이 모든 저장을 막는다. Caddy 한 단만 믿는다.
        app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1)

    @app.before_request
    def _guard_writes():
        if request.method == "POST" and not _same_origin():
            abort(403)

    @app.before_request
    def _require_login():
        # 경로가 안 맞거나 믿지 않는 Host면 Flask가 404·400을 낸다. 로그인 화면으로 돌리지 않는다.
        if request.endpoint is None or request.endpoint in PUBLIC_ENDPOINTS:
            return None
        get_conn()  # DB 파일이 없으면 로그인 화면 대신 이유를 말한다(DatabaseMissing → 503)
        user = _current_user()
        if user is None:
            session.clear()
            nxt = request.full_path.rstrip("?") if request.method == "GET" else None
            return redirect(url_for("login", next=nxt))
        g.user = user
        if user.must_change and request.endpoint not in PASSWORD_ENDPOINTS:
            return redirect(url_for("change_password"))
        return None

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "GET":
            nxt = request.args.get("next", "")
            return render_template("login.html", email="", error=None, next=nxt)
        email = request.form.get("email", "")
        with closing(_rw_conn()) as conn:
            user, error = auth.authenticate(
                conn, email, request.form.get("password", ""), datetime.now()
            )
        if user is None:
            nxt = request.form.get("next", "")
            return render_template("login.html", email=email, error=error, next=nxt), 401
        session.clear()
        session.permanent = True
        session["uid"] = user.id
        return redirect(_safe_next(request.form.get("next")))

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.route("/password", methods=["GET", "POST"])
    def change_password():
        if request.method == "GET":
            return render_template("password.html", error=None)
        new = request.form.get("new", "")
        if new != request.form.get("confirm", ""):
            return render_template("password.html", error="새 비밀번호 두 칸이 다릅니다"), 422
        with closing(_rw_conn()) as conn:
            error = auth.change_password(
                conn,
                g.user.id,
                request.form.get("current", ""),
                new,
                datetime.now().isoformat(timespec="seconds"),
            )
        if error:
            return render_template("password.html", error=error), 422
        return redirect(url_for("index"))

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
        try:
            with closing(_rw_conn()) as conn:
                sent = request.form.get("version")
                if sent is not None and sent != edit.version_of(conn, project_id, section):
                    who = edit.last_editor(conn, project_id, section)
                    message = CONFLICT_BY.format(who) if who else CONFLICT
                    fresh = project_detail(get_conn(), project_id)
                    return _render_detail(fresh, section, {"_form": message}, 409)
                changed = _save(section, conn, project_id, checked.values)
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc):
                raise
            return _render_detail(d, section, {"_form": BUSY_MESSAGE}, 503)
        return redirect(url_for("detail", project_id=project_id, saved="·".join(changed) or "-"))

    @app.post("/project/<int:project_id>/release")
    def release(project_id: int):
        d = project_detail(get_conn(), project_id)
        if d is None:
            abort(404)
        now = datetime.now().isoformat(timespec="seconds")
        db_path = current_app.config["DB_PATH"]
        try:
            with closing(open_readwrite(db_path, current_app.config["WRITE_TIMEOUT"])) as conn:
                released = edit.release_verdict(conn, project_id, now, g.user.id)
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc):
                raise
            return _render_detail(d, None, {"_form": BUSY_MESSAGE}, 503)
        if not released:
            return redirect(url_for("detail", project_id=project_id))
        return redirect(url_for("detail", project_id=project_id, released="1"))

    return app
