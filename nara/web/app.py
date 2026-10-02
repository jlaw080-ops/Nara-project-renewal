"""웹 조회 화면. 요청을 받아 query·data에 넘기고 템플릿을 그린다."""

import sqlite3
from collections.abc import Sequence
from contextlib import closing
from dataclasses import replace
from datetime import datetime, timedelta
from itertools import zip_longest
from pathlib import Path

from flask import (
    Flask,
    abort,
    current_app,
    flash,
    g,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from werkzeug.middleware.proxy_fix import ProxyFix

from nara import auth
from nara.db import attachments_dir
from nara.energy import ENERGY_KINDS, kind_of
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
    print_rows,
    project_detail,
    unit_prices,
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
ENERGY_SOURCES = tuple(dict.fromkeys(k.source for k in ENERGY_KINDS))
MAX_ID = 2**63 - 1
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
    if f.dept_review:
        parts.append("실행부서 검토 필요")
    if f.hidden:
        parts.append("숨긴 사업만")
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


def _project_ids(raw: list[str]) -> list[int]:
    """체크한 사업 id. 숫자가 아니거나 범위를 넘는 값은 버린다 — 없는 id와 같다."""
    return [int(v) for v in raw if v.isdigit() and int(v) <= MAX_ID]


def _set_hidden(project_ids: list[int], hide: bool, reason: str = "") -> int | None:
    """숨기거나 푼 건수. 수집이 DB를 쓰고 있어 못 했으면 None."""
    now = datetime.now().isoformat(timespec="seconds")
    try:
        with closing(_rw_conn()) as conn:
            if hide:
                return edit.hide_projects(conn, project_ids, reason, now, g.user.id)
            return edit.unhide_projects(conn, project_ids, now, g.user.id)
    except sqlite3.OperationalError as exc:
        if "locked" not in str(exc):
            raise
        return None


def _flash_hidden(count: int | None, hide: bool) -> None:
    if count is None:
        flash(BUSY_MESSAGE)
    elif hide:
        flash(f"{count}건을 숨겼습니다" if count else "숨길 사업이 없습니다")
    else:
        flash(f"{count}건의 숨김을 풀었습니다" if count else "숨김을 풀 사업이 없습니다")


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
    return edit.check_energy(form.getlist("source"), form.getlist("kind"), form.getlist("capacity"))


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


def _energy_rows(d: ProjectDetail, posted: bool) -> list[tuple[str, str, str]]:
    """신재생 폼의 줄 (에너지원, 형식, 용량). 다시 보일 때는 사용자가 친 그대로,
    처음에는 지금 계획 + 빈 줄. 목록에 없는 옛 이름은 에너지원을 비워 다시 고르게 한다."""
    if posted:
        form = request.form
        rows = zip_longest(
            form.getlist("source"), form.getlist("kind"), form.getlist("capacity"), fillvalue=""
        )
        return list(rows)
    rows = []
    for e in d.energy:
        kind = kind_of(e.source_type)
        rows.append((kind.source if kind else "", e.source_type, f"{e.capacity_kw:.10g}"))
    return rows + [("", "", "")] * BLANK_ENERGY_ROWS


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
            energy_sources=ENERGY_SOURCES,
            prices={p.kind.code: p.price for p in unit_prices(get_conn())},
            versions={s: edit.version_of(get_conn(), d.project["id"], s) for s in EDIT_SECTIONS},
        ),
        status,
    )


def create_app(
    db_path: Path,
    secret_key: str,
    host: str | None = None,
    lan_hosts: Sequence[str] = (),
) -> Flask:
    if not secret_key:
        raise ValueError("세션 서명 키가 없다 — .env의 NARA_SECRET_KEY를 채운다")
    app = Flask(__name__)
    app.secret_key = secret_key
    app.config["DB_PATH"] = Path(db_path)
    app.config["ATTACH_DIR"] = attachments_dir(Path(db_path))
    app.add_template_filter(_dash, "dash")
    app.add_template_filter(_won, "won")
    app.add_template_global(kind_of, "kind_of")
    app.add_template_global(ENERGY_KINDS, "energy_kinds")
    # DNS 리바인딩으로 외부 페이지가 이 화면을 읽지 못하게 한다.
    # 사내망 공유(lan_hosts)는 http라 host와 달리 Secure 쿠키·프록시 설정을 켜지 않는다.
    app.config["TRUSTED_HOSTS"] = [
        "127.0.0.1",
        "localhost",
        *lan_hosts,
        *([host] if host else []),
    ]
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

    @app.get("/print")
    def print_list():
        """목록 조건 그대로 시트 양식(A4 가로) 인쇄 화면. 브라우저 인쇄로 PDF를 만든다."""
        f, _ = parse_filters({k: request.args.getlist(k) for k in request.args})
        rows, result = print_rows(get_conn(), f)
        return render_template("print.html", rows=rows, result=result)

    @app.get("/project/<int:project_id>")
    def detail(project_id: int):
        d = project_detail(get_conn(), project_id)
        if d is None:
            abort(404)
        section = request.args.get("edit")
        return _render_detail(d, section if section in EDIT_SECTIONS else None, {})

    @app.get("/attachment/<int:attachment_id>")
    def attachment(attachment_id: int):
        row = (
            get_conn()
            .execute(
                "SELECT filename, path FROM attachment WHERE id = ? AND status = 'ok'",
                (attachment_id,),
            )
            .fetchone()
        )
        if row is None or not row["path"]:
            abort(404)
        root = Path(current_app.config["ATTACH_DIR"]).resolve()
        target = (root / row["path"]).resolve()
        # DB에 적힌 경로를 믿지 않는다. 첨부 폴더 밖이면 없는 것으로 친다.
        if not target.is_relative_to(root) or not target.is_file():
            abort(404)
        return send_file(target, as_attachment=True, download_name=row["filename"])

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
                # 비교부터 저장까지 쓰기 잠금 하나로 묶는다.
                # 둘이 동시에 비교를 통과하면 나중 것이 덮는다.
                conn.execute("BEGIN IMMEDIATE")
                if sent is not None and sent != edit.version_of(conn, project_id, section):
                    who = edit.last_editor(conn, project_id, section)
                    conn.rollback()
                    message = CONFLICT_BY.format(who) if who else CONFLICT
                    fresh = project_detail(get_conn(), project_id)
                    return _render_detail(fresh, section, {"_form": message}, 409)
                changed = _save(section, conn, project_id, checked.values)
                conn.commit()  # 바뀐 것이 없어 저장 함수가 트랜잭션을 닫지 않은 경우
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc):
                raise
            return _render_detail(d, section, {"_form": BUSY_MESSAGE}, 503)
        return redirect(url_for("detail", project_id=project_id, saved="·".join(changed) or "-"))

    @app.route("/prices", methods=["GET", "POST"])
    def prices():
        rows = unit_prices(get_conn())
        if request.method == "GET":
            return render_template(
                "prices.html", rows=rows, form={}, errors={}, saved=request.args.get("saved")
            )
        form = request.form
        checked = edit.check_prices(form.getlist("code"), form.getlist("price"))
        if not checked.ok:
            entered = dict(zip(form.getlist("code"), form.getlist("price"), strict=False))
            page = render_template(
                "prices.html", rows=rows, form=entered, errors=checked.errors, saved=None
            )
            return page, 422
        today = datetime.now().date().isoformat()
        try:
            with closing(_rw_conn()) as conn:
                changed = edit.save_prices(conn, checked.values["prices"], today, g.user.id)
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc):
                raise
            entered = dict(zip(form.getlist("code"), form.getlist("price"), strict=False))
            page = render_template(
                "prices.html", rows=rows, form=entered, errors={"_form": BUSY_MESSAGE}, saved=None
            )
            return page, 503
        return redirect(url_for("prices", saved="·".join(changed) or "-"))

    @app.post("/hide")
    def hide():
        count = _set_hidden(
            _project_ids(request.form.getlist("pid")), True, request.form.get("hide_reason", "")
        )
        _flash_hidden(count, True)
        return redirect(_safe_next(request.form.get("next")))

    @app.post("/unhide")
    def unhide():
        count = _set_hidden(_project_ids(request.form.getlist("pid")), False)
        _flash_hidden(count, False)
        return redirect(_safe_next(request.form.get("next")))

    @app.post("/project/<int:project_id>/hide")
    def hide_one(project_id: int):
        count = _set_hidden([project_id], True, request.form.get("hide_reason", ""))
        _flash_hidden(count, True)
        return redirect(url_for("detail", project_id=project_id))

    @app.post("/project/<int:project_id>/unhide")
    def unhide_one(project_id: int):
        count = _set_hidden([project_id], False)
        _flash_hidden(count, False)
        return redirect(url_for("detail", project_id=project_id))

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
