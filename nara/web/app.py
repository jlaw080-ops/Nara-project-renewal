"""웹 조회 화면. 요청을 받아 query·data에 넘기고 템플릿을 그린다."""

import hmac
import sqlite3
from collections.abc import Sequence
from contextlib import closing
from dataclasses import asdict, replace
from datetime import datetime, timedelta
from io import BytesIO
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
from werkzeug.datastructures import MultiDict
from werkzeug.middleware.proxy_fix import ProxyFix

from nara import auth, settings_store
from nara.config import Settings
from nara.db import attachments_dir
from nara.energy import EnergyKind, load_kinds
from nara.nr_apply import ignore_plan, ingest, link_plan
from nara.nr_match import candidates
from nara.nr_plan import load_energy
from nara.runlog import run_log
from nara.settings_store import current_settings, seed_settings
from nara.web import edit, xlsx
from nara.web.data import (
    BUSY_TIMEOUT_SECONDS,
    NR_STATE_LABELS,
    DatabaseMissing,
    ProjectDetail,
    last_runs,
    list_projects,
    nr_counts,
    nr_plan_detail,
    nr_rows,
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
# 상세 화면에서 열 수 있는 폼. 부서장 연락처는 사업이 아니라 기관+부서 단위라 따로 저장한다.
BUSY_MESSAGE = "수집이 DB를 쓰고 있습니다. 잠시 뒤 다시 저장하세요"
CONFLICT_BY = "그사이 {}님이 고쳤습니다. 지금 값을 확인하고 다시 저장하세요"
CONFLICT = "그사이 값이 바뀌었습니다. 지금 값을 확인하고 다시 저장하세요"
BLANK_ENERGY_ROWS = 3
MAX_ID = 2**63 - 1
SESSION_LIFETIME = timedelta(days=14)
NR_MAX_ROWS = 200
MAX_BODY = 1024 * 1024
# 확장 프로그램이 부르는 주소. 로그인·같은 출처 검사 대신 토큰으로 막는다.
API_ENDPOINTS = {"nr_import", "nr_ping"}
PUBLIC_ENDPOINTS = {"login", "static", *API_ENDPOINTS}
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


def _check_token() -> None:
    """Authorization: Bearer <토큰>이 정확히 같아야 한다. 토큰이 없으면 주소 자체가 없다."""
    token = current_app.config.get("IMPORT_TOKEN")
    if not token:
        abort(404)
    sent = request.headers.get("Authorization", "")
    if not hmac.compare_digest(sent.encode(), f"Bearer {token}".encode()):
        abort(401)


def _current_user() -> auth.User | None:
    uid = session.get("uid")
    if not isinstance(uid, int):
        return None
    return auth.get_user(get_conn(), uid)


def _rw_conn() -> sqlite3.Connection:
    return open_readwrite(current_app.config["DB_PATH"], current_app.config["WRITE_TIMEOUT"])


def _settings(conn: sqlite3.Connection) -> Settings | None:
    """요청마다 DB에서 읽는다. 설정 화면에서 바꾸면 서버를 다시 띄우지 않아도 쓰인다."""
    base = current_app.config.get("SETTINGS")
    return current_settings(conn, base) if base is not None else None


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
        dept, contact = edit.check_dept(form, _candidates(d)), edit.check_contact(form)
        return edit.Checked({**dept.values, **contact.values}, {**dept.errors, **contact.errors})
    return edit.check_energy(
        form.getlist("source"), form.getlist("kind"), form.getlist("capacity"), _kinds()
    )


def _save(section: str, conn: sqlite3.Connection, project_id: int, values: dict) -> list[str]:
    now = datetime.now().isoformat(timespec="seconds")
    uid = g.user.id
    if section == "info":
        return edit.save_info(conn, project_id, values, now, uid)
    if section == "verdict":
        return edit.save_verdict(conn, project_id, values["verdict"], values["reason"], now, uid)
    if section == "dept":
        changed = edit.save_dept(conn, project_id, values["exec_dept"], values["snippet"], now, uid)
        org_id = conn.execute("SELECT org_id FROM project WHERE id = ?", (project_id,)).fetchone()[
            0
        ]
        contact = {k: values[k] for k in edit.CONTACT_FIELDS}
        # 연락처는 저장한 실행부서 이름의 기관+부서에 붙는다
        if edit.save_contact(conn, org_id, values["exec_dept"], contact, now, uid):
            changed = [*changed, "연락처"]
        return changed
    return edit.save_energy(conn, project_id, values["items"], now, uid)


def _kinds() -> dict[str, EnergyKind]:
    """이 요청의 에너지원·형식 목록. 순서를 지킨다(dict는 넣은 순서)."""
    return {k.code: k for k in load_kinds(get_conn())}


def _energy_rows(d: ProjectDetail, posted: bool) -> list[tuple[str, str, str]]:
    """신재생 폼의 줄 (에너지원, 형식, 용량). 다시 보일 때는 사용자가 친 그대로,
    처음에는 지금 계획 + 빈 줄. 목록에 없는 옛 이름은 에너지원을 비워 다시 고르게 한다."""
    if posted:
        form = request.form
        rows = zip_longest(
            form.getlist("source"), form.getlist("kind"), form.getlist("capacity"), fillvalue=""
        )
        return list(rows)
    known = _kinds()
    rows = []
    for e in d.energy:
        kind = known.get(e.source_type)
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
            energy_kinds=list(_kinds().values()),
            kinds_by_code=_kinds(),
            energy_sources=list(dict.fromkeys(k.source for k in _kinds().values())),
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
    import_token: str | None = None,
    settings: Settings | None = None,
) -> Flask:
    if not secret_key:
        raise ValueError("세션 서명 키가 없다 — .env의 NARA_SECRET_KEY를 채운다")
    app = Flask(__name__)
    app.secret_key = secret_key
    app.config["DB_PATH"] = Path(db_path)
    app.config["ATTACH_DIR"] = attachments_dir(Path(db_path))
    app.add_template_filter(_dash, "dash")
    app.add_template_filter(_won, "won")
    app.add_template_global(load_energy, "load_energy")
    # DNS 리바인딩으로 외부 페이지가 이 화면을 읽지 못하게 한다.
    # 사내망 공유(lan_hosts)는 http라 host와 달리 Secure 쿠키·프록시 설정을 켜지 않는다.
    app.config["TRUSTED_HOSTS"] = [
        "127.0.0.1",
        "localhost",
        *lan_hosts,
        *([host] if host else []),
    ]
    app.config["WRITE_TIMEOUT"] = BUSY_TIMEOUT_SECONDS
    # 확장 프로그램이 설치계획서를 보내는 주소용. 토큰이 없으면 그 주소를 끈다.
    app.config["IMPORT_TOKEN"] = import_token
    app.config["SETTINGS"] = settings
    # 설정 목록은 DB가 정본이다. 처음 띄울 때 한 번 파일 목록을 옮긴다.
    # 없는 DB 파일은 만들지 않는다(DatabaseMissing 안내가 먼저다).
    if settings is not None and Path(db_path).exists():
        with closing(open_readwrite(Path(db_path), BUSY_TIMEOUT_SECONDS)) as conn:
            seed_settings(conn, settings, datetime.now().isoformat(timespec="seconds"))
    app.config["MAX_CONTENT_LENGTH"] = MAX_BODY
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
        if request.endpoint in API_ENDPOINTS:
            return None
        if request.method == "POST" and not _same_origin():
            abort(403)
        return None

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
            nr_pending=nr_counts(conn).get("pending", 0),
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

    @app.get("/export.xlsx")
    def export_xlsx():
        """목록 조건 그대로 출력 양식 15칸을 엑셀로 내려받는다."""
        f, _ = parse_filters({k: request.args.getlist(k) for k in request.args})
        rows, result = print_rows(get_conn(), f)
        note = (
            f"조건에 맞는 {result.matched}건 중 {len(rows)}건만 담았습니다 — 조건을 좁혀 주세요."
            if result.truncated
            else ""
        )
        return send_file(
            BytesIO(xlsx.workbook(rows, note)),
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            as_attachment=True,
            download_name=f"{datetime.now():%Y.%m.%d}_사업조회.xlsx",
        )

    def _setting_items(conn) -> dict[str, list]:
        return {k: settings_store.items(conn, k) for k in settings_store.KINDS}

    def _render_settings(form: MultiDict, errors, status=200):
        conn = get_conn()
        return render_template(
            "settings.html",
            kinds=settings_store.KINDS,
            labels=settings_store.LABELS,
            values=_setting_items(conn),
            log=settings_store.recent_log(conn),
            form=form,
            errors=errors,
        ), status

    def _setting_plan():
        """폼을 검사하고 미리보기를 만든다. (plan, warnings) 또는 (오류 응답, None)."""
        conn = get_conn()
        current = {k: {r["value"] for r in v} for k, v in _setting_items(conn).items()}
        checked = edit.check_settings(request.form, current)
        if not checked.ok:
            return _render_settings(request.form, checked.errors, 422), None
        change = checked.values["change"]
        if change.empty:
            flash("바뀐 것이 없습니다")
            return redirect(url_for("settings")), None
        plan = settings_store.plan_change(conn, current_app.config["SETTINGS"], change)
        return plan, checked.values["warnings"]

    def _render_preview(plan, warnings, message=None, status=200):
        return render_template(
            "settings_preview.html",
            plan=plan,
            warnings=warnings,
            labels=settings_store.LABELS,
            form=request.form,
            kinds=settings_store.KINDS,
            message=message,
        ), status

    @app.get("/settings")
    def settings():
        return _render_settings(MultiDict(), {})

    @app.post("/settings/preview")
    def settings_preview():
        plan, warnings = _setting_plan()
        if warnings is None:
            return plan
        return _render_preview(plan, warnings)

    @app.post("/settings/apply")
    def settings_apply():
        plan, warnings = _setting_plan()
        if warnings is None:
            return plan
        stale = "그사이 설정이 바뀌었습니다. 다시 확인하세요"
        if request.form.get("fingerprint") != plan.fingerprint:
            return _render_preview(plan, warnings, stale, 409)
        hide_ids = {int(v) for v in request.form.getlist("hide") if v.isdigit()}
        now = datetime.now().isoformat(timespec="seconds")
        try:
            with closing(_rw_conn()) as conn:
                done = settings_store.apply_change(conn, plan, hide_ids, g.user.id, now)
        except settings_store.StaleSettings:
            return _render_preview(plan, warnings, stale, 409)
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc):
                raise
            return _render_preview(plan, warnings, BUSY_MESSAGE, 503)
        flash(
            f"설정 {done['items']}건을 바꿨습니다 — 숨김 {done['hidden']}건, "
            f"관심 내림 {done['demoted']}곳, 관심 올림 {done['promoted']}곳"
        )
        return redirect(url_for("settings"))

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
        checked = edit.check_prices(
            form.getlist("code"), form.getlist("price"), {r.kind.code: r.price for r in rows}
        )
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

    @app.get("/api/nr-plans/ping")
    def nr_ping():
        _check_token()
        return {"ok": True}

    @app.post("/api/nr-plans")
    def nr_import():
        _check_token()
        if (request.content_length or 0) > MAX_BODY:
            return {"ok": False, "error": "본문이 1MB를 넘습니다"}, 413
        body = request.get_json(silent=True)
        rows = body.get("rows") if isinstance(body, dict) else None
        if not isinstance(rows, list):
            return {"ok": False, "error": "rows 배열이 없습니다"}, 400
        if len(rows) > NR_MAX_ROWS:
            return {"ok": False, "error": f"한 번에 {NR_MAX_ROWS}행까지 받습니다"}, 413
        if current_app.config.get("SETTINGS") is None:
            return {"ok": False, "error": "설정 파일을 읽지 못해 받을 수 없습니다"}, 500
        now = datetime.now().isoformat(timespec="seconds")
        try:
            with closing(_rw_conn()) as conn, run_log(conn, "nr import", f"{len(rows)}행") as c:
                results = ingest(conn, rows, _settings(conn), now, c)
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc):
                raise
            return {"ok": False, "error": BUSY_MESSAGE}, 503
        return {"ok": True, "results": [asdict(r) for r in results]}

    @app.get("/nr")
    def nr_list():
        state = request.args.get("state", "pending")
        if state not in NR_STATE_LABELS:
            state = "pending"
        conn = get_conn()
        return render_template(
            "nr_list.html",
            rows=nr_rows(conn, state),
            state=state,
            counts=nr_counts(conn),
            labels=NR_STATE_LABELS,
        )

    @app.get("/nr/<int:plan_id>")
    def nr_detail(plan_id: int):
        conn = get_conn()
        plan = nr_plan_detail(conn, plan_id)
        if plan is None:
            abort(404)
        settings = _settings(conn)
        aliases = dict(settings.nr_org_aliases) if settings else {}
        found = candidates(
            conn, plan["org_name"], plan["building_name"], plan["address"] or "", aliases
        )
        return render_template(
            "nr_detail.html", plan=plan, candidates=found, labels=NR_STATE_LABELS
        )

    def _nr_write(plan_id: int, action):
        """설치계획서 쓰기 공통. 잠금이면 이유를 띄우고 그 설치계획서로 돌아간다."""
        if current_app.config.get("SETTINGS") is None:
            abort(503)
        now = datetime.now().isoformat(timespec="seconds")
        try:
            with closing(_rw_conn()) as conn:
                return action(conn, _settings(conn), now)
        except LookupError:
            abort(404)
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc):
                raise
            flash(BUSY_MESSAGE)
            return redirect(url_for("nr_detail", plan_id=plan_id))

    @app.post("/nr/<int:plan_id>/link")
    def nr_link(plan_id: int):
        raw = request.form.get("project_id", "").strip()
        if request.form.get("new"):
            target = None
        elif raw.isdigit() and int(raw) <= MAX_ID:
            target = int(raw)
        else:
            flash("연결할 사업 번호를 숫자로 적으세요")
            return redirect(url_for("nr_detail", plan_id=plan_id))

        def act(conn, settings, now):
            pid = link_plan(conn, plan_id, target, settings, now)
            flash("설치계획서를 이 사업에 연결했습니다")
            return redirect(url_for("detail", project_id=pid))

        return _nr_write(plan_id, act)

    @app.post("/nr/<int:plan_id>/ignore")
    def nr_ignore(plan_id: int):
        def act(conn, settings, now):
            ignore_plan(conn, plan_id, now)
            flash("설치계획서를 무시했습니다")
            return redirect(url_for("nr_list"))

        return _nr_write(plan_id, act)

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
