# 공고 첨부에서 실행부서 찾기(4단계) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 공고 첨부(공고문·과업지시서)를 다운로드 주소로 받아 읽고, 규칙과 Claude(원문 대조)로 실행부서를 찾아 확정 또는 "검토 필요"로 기록하며, 예약 슬롯과 웹 화면에 붙인다.

**Architecture:** 받기(`nara/g2b/attach.py`), 읽기(`nara/doctext.py`), 판정 규칙(`nara/dept_rules.py`), Claude 질문(`nara/llm.py`), 흐름과 기록(`nara/dept.py`)을 나눈다. 앞의 넷은 DB를 모른다. 흐름만 DB와 첨부 폴더를 만진다. `dept_check`에 확정 여부 칸을 더해, 자동 조회가 남긴 후보가 확정값처럼 쓰이지 않게 한다.

**Tech Stack:** Python 3.14, SQLite, httpx(나라장터), anthropic SDK(Claude), pypdf·olefile(새 의존성), Flask, Typer, pytest, ruff.

**Spec:** `docs/superpowers/specs/2026-09-29-dept-lookup-design.md`

## Global Constraints

- 구현은 git worktree(`../Nara-project-renewal-dept`, 브랜치 `feat/dept-lookup`)에서 한다. 작업 스케줄러가 09·12·15·03시에 원래 폴더의 코드를 실제 DB에 돌리므로, 만드는 도중의 코드가 거기 있으면 안 된다
- 원본 `data/nara.db`에는 쓰지 않는다. 실데이터 확인은 사본으로 한다
- 새 의존성은 `pypdf`, `olefile` 두 개뿐이다. PyMuPDF(AGPL)는 쓰지 않는다. 브라우저(Playwright·Chromium)도 쓰지 않는다
- 문서에서 읽은 것만 확정한다. 조직도나 사업 성격으로 부서를 짐작하지 않는다. 근거가 없으면 빈칸이다
- 나라장터 요청은 한 번에 한 건, 요청 사이 0.5초 쉼, 파일당 30초 제한, 30MB 상한
- Claude 모델 이름은 `claude-opus-5`를 그대로 둔다(지금도 쓸 수 있는 모델이다. 2026-09-30 claude-api 참고 자료로 확인)
- 실행부서는 과 단위로 적는다. 팀 이름은 근거 문장에만 남는다
- 코드 스타일: ruff line-length 100, 규칙 E·F·I·UP·B. 테스트는 `PYTHONIOENCODING=utf-8 uv run pytest`
- 커밋 메시지는 한국어 `<type>: <설명>`, 끝에 `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`
- `git commit`과 `grep -n`을 한 명령에 넣지 않는다(훅이 `-n`을 `--no-verify`로 오인해 막는다)

## Review Focus

1. **나라장터가 200으로 HTML·JSON 안내 페이지를 돌려준다** — 기대: 파일로 저장하지 않는다. 순번 요청은 거기서 멈추고, 목록에 있던 파일이면 다운로드 실패로 친다 → Task 3
2. **서버가 보낸 파일 이름에 `../`, `\`, 제어 문자가 섞였다** — 기대: 공고 폴더 밖에 쓰지 않는다. 웹 내려받기도 첨부 폴더 밖 경로면 404다 → Task 3, Task 8
3. **자동 조회가 남긴 후보(`confirmed=0`)** — 기대: 목록의 실행부서 칸, 동시 수정 버전 표시, 시트 재이관의 "지금 값" 어디에서도 확정값으로 쓰이지 않는다 → Task 1
4. **Claude 근거 문장의 띄어쓰기·줄바꿈이 추출본과 다르다**(PDF는 줄을 아무 데서나 끊는다) — 기대: 공백을 빼고 비교해 맞춘다. 말을 바꾼 문장은 불일치다 → Task 4
5. **수집이 최근 3일 공고를 날마다 다시 받아 `collected_at`이 바뀐다** — 기대: 같은 사업을 회차마다 다시 받지 않는다. 가장 최근 공고번호가 바뀔 때만 다시 본다 → Task 6

---

## 파일 구조

| 파일 | 책임 |
|---|---|
| `nara/schema.sql`, `nara/db.py` | `dept_check.confirmed`·`note`, `attachment.seq` 칸. `attachments_dir(db_path)` |
| `nara/doctext.py` (새) | 파일 형식 판별, HWPX·PDF·HWP 텍스트 추출 |
| `nara/g2b/attach.py` (새) | 파일 목록(API 원본·순번 요청), 고르기, 받기, 이름 다듬기 |
| `nara/dept_rules.py` (새) | 후보 찾기, 규칙 확정, Claude 발췌, 원문 대조 |
| `nara/llm.py` | `ask_dept` 추가, 호출부 공통화 |
| `nara/dept.py` (새) | 대상 고르기, 한 사업 처리, 기록 |
| `nara/cli.py`, `nara/slot.py`, `nara/web/data.py` | `enrich dept` 명령, 슬롯 단계, 목록 머리 단계 |
| `nara/web/query.py`, `app.py`, `data.py`, 템플릿 | 확정값만 보이기, 검토 필요 표시·필터, 첨부 목록·내려받기 |
| `nara/web/edit.py`, `nara/migrate_sheets.py` | 확정값만 읽기 |
| `tests/test_doctext.py`·`test_attach.py`·`test_dept_rules.py`·`test_dept.py` (새), 기존 테스트 | 테스트 |

---

### Task 0: 작업 폴더 준비

**Files:** 없음(작업 환경)

- [ ] **Step 1: 계획을 main에 커밋하고 worktree를 만든다**

```bash
cd /c/Users/jlaw8/dev/Nara-project-renewal
git add docs/superpowers/plans/2026-09-30-dept-lookup.md
git commit -m "docs: 공고 첨부에서 실행부서 찾기(4단계) 구현 계획

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git worktree add ../Nara-project-renewal-dept -b feat/dept-lookup
cd ../Nara-project-renewal-dept
uv sync
PYTHONIOENCODING=utf-8 uv run pytest -q
```

Expected: 전체 테스트 통과. 이후 모든 작업은 `C:/Users/jlaw8/dev/Nara-project-renewal-dept`에서 한다.

---

### Task 1: 확정 여부 칸과 확정값만 읽기

**Files:**
- Modify: `nara/schema.sql`, `nara/db.py`, `nara/web/query.py`, `nara/web/edit.py`, `nara/migrate_sheets.py`
- Modify: `docs/superpowers/specs/2026-09-29-dept-lookup-design.md`(모델·재시도 기록 정정)
- Test: `tests/test_db.py`, `tests/test_web.py`, `tests/test_migrate_sheets.py`

**Interfaces:**
- Produces (DB): `dept_check.confirmed INTEGER NOT NULL DEFAULT 1`, `dept_check.note TEXT`, `attachment.seq INTEGER`
- Produces (`nara.db`): `attachments_dir(db_path: Path) -> Path` — `db_path.parent / "attachments"`
- 규칙: "지금 실행부서"를 읽는 모든 곳은 `confirmed = 1`인 줄만 본다

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_db.py` 끝에 더한다:

```python
def test_migrate_adds_the_lookup_columns_to_an_older_database(tmp_path):
    """3단계 때 만든 DB에는 확정 여부 칸이 없다. 옛 줄은 확정으로 남아야 한다."""
    conn = connect(tmp_path / "old.db")
    migrate(conn)
    conn.execute("DROP TABLE dept_check")
    conn.execute(
        "CREATE TABLE dept_check (id INTEGER PRIMARY KEY, bid_no TEXT, project_id INTEGER, "
        "exec_dept TEXT, contract_dept TEXT, head_tel TEXT, snippet TEXT, source_file TEXT, "
        "decided_by TEXT NOT NULL, checked_at TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT INTO dept_check (project_id, exec_dept, decided_by, checked_at) "
        "VALUES (1, '건축과', 'imported', '2026-09-01T09:00:00')"
    )
    conn.execute("DROP TABLE attachment")
    conn.execute(
        "CREATE TABLE attachment (id INTEGER PRIMARY KEY, bid_no TEXT NOT NULL, "
        "filename TEXT NOT NULL, path TEXT, sha256 TEXT, text_path TEXT, "
        "status TEXT NOT NULL DEFAULT 'ok', attempts INTEGER NOT NULL DEFAULT 0, "
        "downloaded_at TEXT)"
    )
    conn.commit()
    migrate(conn)
    assert conn.execute("SELECT confirmed, note FROM dept_check").fetchone() == (1, None)
    assert "seq" in [r[1] for r in conn.execute("PRAGMA table_info(attachment)")]


def test_attachments_live_next_to_the_database(tmp_path):
    assert attachments_dir(tmp_path / "data" / "nara.db") == tmp_path / "data" / "attachments"
```

`tests/test_db.py` 맨 위 import에 `attachments_dir`를 더한다(`from nara.db import attachments_dir, connect, migrate` 꼴로. 이미 있는 import 줄에 이름만 더한다).

`tests/test_web.py`의 `_verdict` 함수 아래에 도우미를 더한다:

```python
def _dept(conn, project_id, dept, when, decided_by="imported", confirmed=1, note=None):
    conn.execute(
        "INSERT INTO dept_check (project_id, exec_dept, decided_by, confirmed, note, "
        "checked_at) VALUES (?, ?, ?, ?, ?, ?)",
        (project_id, dept, decided_by, confirmed, note, when),
    )
```

`tests/test_web.py` 끝에 더한다:

```python
def test_a_candidate_is_never_shown_as_the_department(world):
    """자동 조회가 남긴 후보가 확정값처럼 목록에 뜨면 안 된다."""
    path, ids = world
    conn = connect(path)
    _dept(conn, ids["gym"], "건축과", "2026-09-01T09:00:00")
    _dept(conn, ids["gym"], "문화관광과", "2026-09-28T09:00:00", "rule", confirmed=0)
    _dept(conn, ids["culture"], "도시재생과", "2026-09-28T09:00:00", "rule", confirmed=0)
    conn.commit()
    conn.close()
    rows = {r["id"]: r for r in _list(path).rows}
    assert rows[ids["gym"]]["exec_dept"] == "건축과"
    assert rows[ids["culture"]]["exec_dept"] is None


def test_a_new_candidate_does_not_block_a_save_in_progress(world):
    """폼을 연 사이 자동 조회가 후보를 남겨도 확정값은 그대로라 저장이 막히면 안 된다."""
    path, ids = world
    client = _client(path)
    version = _version(client, ids["gym"], "dept")
    conn = connect(path)
    _dept(conn, ids["gym"], "문화관광과", "2026-09-28T09:00:00", "rule", confirmed=0)
    conn.commit()
    conn.close()
    resp = client.post(
        f"/project/{ids['gym']}/edit/dept",
        data={"exec_dept": "건축과", "snippet": "", "version": version},
        headers=ORIGIN,
    )
    assert resp.status_code == 302
```

`tests/test_migrate_sheets.py`에 시트 재이관 테스트를 더한다. 이 파일에서 실행부서가 든 TSV 한 줄을 이관하는 기존 테스트(이름에 `dept`가 들어간 것)를 찾아, 그 테스트가 쓰는 도우미와 같은 방식으로 아래 뜻의 테스트를 쓴다: **이관 전에 그 사업에 `confirmed=0`인 후보 줄(`exec_dept='문화관광과'`)만 있으면, 시트의 실행부서가 `imported`·`confirmed=1` 줄로 새로 들어가고 `overwritten` 목록은 비어 있다.** 이름은 `test_sheet_department_is_imported_over_an_unconfirmed_candidate`로 한다.

- [ ] **Step 2: 실패를 확인한다**

Run: `PYTHONIOENCODING=utf-8 uv run pytest tests/test_db.py tests/test_web.py tests/test_migrate_sheets.py -q -k "lookup_columns or next_to_the_database or candidate"`
Expected: FAIL — `ImportError: cannot import name 'attachments_dir'`, 칸 없음 오류

- [ ] **Step 3: 표와 이관**

`nara/schema.sql`의 `dept_check` 표에서 `source_file   TEXT,` 줄 아래에 두 줄을 더한다:

```sql
  confirmed     INTEGER NOT NULL DEFAULT 1,     -- 0 = 자동 조회가 남긴 후보·못 찾음 기록
  note          TEXT,                           -- 못 찾은 사유·후보 출처
```

같은 파일의 `attachment` 표에서 `bid_no        TEXT NOT NULL REFERENCES notice(bid_no),` 줄 아래에 더한다:

```sql
  seq           INTEGER,                        -- 나라장터 파일 순번
```

`nara/db.py`의 `migrate`에서 `_add_column(conn, "edit_log", ...)` 줄 아래에 더한다:

```python
    _add_column(conn, "dept_check", "confirmed", "INTEGER NOT NULL DEFAULT 1")
    _add_column(conn, "dept_check", "note", "TEXT")
    _add_column(conn, "attachment", "seq", "INTEGER")
```

`nara/db.py`의 `connect` 위에 더한다:

```python
def attachments_dir(db_path: Path) -> Path:
    """받은 첨부를 두는 폴더. 명령과 웹이 같은 규칙으로 찾는다."""
    return Path(db_path).parent / "attachments"
```

- [ ] **Step 4: 확정값만 읽게 한다**

`nara/web/query.py`의 `ld` CTE에서
`    WHERE d.project_id IS NOT NULL AND COALESCE(d.exec_dept, '') != ''`
를 이것으로 바꾼다:

```sql
    WHERE d.project_id IS NOT NULL AND d.confirmed = 1 AND COALESCE(d.exec_dept, '') != ''
```

`nara/web/edit.py`의 `save_dept` 첫 조회에서
`"AND COALESCE(exec_dept, '') != '' ORDER BY checked_at DESC, id DESC LIMIT 1",`
를 `"AND confirmed = 1 AND COALESCE(exec_dept, '') != '' ORDER BY checked_at DESC, id DESC LIMIT 1",`로 바꾼다. 줄이 100자를 넘으면 문자열을 두 조각으로 나눈다.

같은 파일 `version_of`의 dept 분기에서 `"AND COALESCE(exec_dept, '') != ''"`를 `"AND confirmed = 1 AND COALESCE(exec_dept, '') != ''"`로 바꾼다.

`nara/migrate_sheets.py`의 실행부서 이관 함수(`values = (bid_no, 부서, 전화, 근거)` 설명이 있는 함수) 첫 조회에서 `"AND COALESCE(exec_dept, '') != '' ORDER BY checked_at DESC, id DESC LIMIT 1",`를 `"AND confirmed = 1 AND COALESCE(exec_dept, '') != '' "`와 `"ORDER BY checked_at DESC, id DESC LIMIT 1",` 두 조각으로 바꾼다.

- [ ] **Step 5: 설계 문서를 정정한다**

`docs/superpowers/specs/2026-09-29-dept-lookup-design.md`에서 세 곳을 고친다.

1. `### 모델` 아래 문단 전체를 이것으로 바꾼다:

```markdown
진행현황 판정과 실행부서 판정은 `nara/llm.py`의 모델 이름 하나(`claude-opus-5`)를 함께 쓴다. 이 이름은 지금도 쓸 수 있는 모델이라 바꾸지 않는다(2026-09-30 claude-api 참고 자료로 확인. 설계 때 "목록에 없는 이름"이라고 적은 것은 잘못이었다).
```

2. `### 표 변경` 표의 `attachment` 행을 이것으로 바꾼다:

```markdown
| `attachment` | `seq INTEGER`(파일 순번) 칸을 더한다 |
```

3. `### 조회 대상`의 두 하위 항목과 `## 오류 처리`의 다운로드 실패 항목을 이것으로 바꾼다:

```markdown
  - 가장 최근 공고의 번호가 마지막 자동 조회 때 기록한 공고번호와 다르다(재공고 등). 수집은 최근 3일 공고를 날마다 다시 받아 수집 시각이 바뀌므로 시각이 아니라 공고번호로 비교한다
  - 마지막 자동 조회가 "다운로드 실패"로 끝났다
```

```markdown
- 다운로드 실패는 `dept_check`에 사유 "다운로드 실패" 줄로 남고 다음 회차에 다시 본다. 같은 공고에서 연달아 3회 실패하면 "수동 확인"으로 남기고 새 공고가 오기 전에는 다시 시도하지 않는다
```

- [ ] **Step 6: 통과를 확인한다**

Run: `PYTHONIOENCODING=utf-8 uv run pytest -q`
Expected: PASS 전부

- [ ] **Step 7: 전체 검사와 커밋**

```bash
uv run ruff check --fix . && uv run ruff format . && uv run ruff check . && uv run ruff format --check .
git add nara/schema.sql nara/db.py nara/web/query.py nara/web/edit.py nara/migrate_sheets.py docs/superpowers/specs/2026-09-29-dept-lookup-design.md tests
git commit -m "feat: 실행부서 기록에 확정 여부를 둔다 — 후보는 확정값으로 읽지 않는다

목록·동시 수정 버전·시트 재이관은 confirmed=1인 줄만 본다. 첨부 순번 칸과
첨부 폴더 규칙을 더했다. 설계 문서의 모델 이름 오판과 재시도 기록 위치를
바로잡았다.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: 문서 읽기

**Files:**
- Create: `nara/doctext.py`, `tests/test_doctext.py`
- Modify: `pyproject.toml`, `uv.lock`

**Interfaces:**
- Produces (`nara.doctext`): `kind_of(data: bytes) -> str | None`('hwpx'|'pdf'|'hwp'), `extract_text(data: bytes) -> str`(못 읽으면 `""`), `hwp_records_text(data: bytes) -> str`

- [ ] **Step 1: 의존성을 더한다**

```bash
uv add pypdf olefile
PYTHONIOENCODING=utf-8 uv run python -c "import pypdf, olefile; print(pypdf.__version__, olefile.__version__)"
```

Expected: 두 버전이 찍힌다

- [ ] **Step 2: 실패하는 테스트를 쓴다**

`tests/test_doctext.py`:

```python
"""첨부 문서 읽기 — 형식은 확장자가 아니라 파일 앞부분으로 가린다."""

import io
import zipfile

from nara.doctext import extract_text, hwp_records_text, kind_of

OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def _hwpx(sections: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("mimetype", "application/hwp+zip")
        for name, xml in sections.items():
            z.writestr(f"Contents/{name}", xml)
    return buf.getvalue()


def _pdf(text: str) -> bytes:
    """글자 한 줄짜리 최소 PDF. 오프셋 표를 직접 계산한다."""
    stream = f"BT /F1 12 Tf 20 100 Td ({text}) Tj ET".encode()
    bodies = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 144] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(bodies, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(bodies) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(bodies) + 1,
        xref,
    )
    return bytes(out)


def _record(tag: int, payload: bytes) -> bytes:
    if len(payload) < 0xFFF:
        return (tag | (len(payload) << 20)).to_bytes(4, "little") + payload
    return (tag | (0xFFF << 20)).to_bytes(4, "little") + len(payload).to_bytes(4, "little") + (
        payload
    )


def test_kind_is_read_from_the_first_bytes():
    assert kind_of(b"PK\x03\x04rest") == "hwpx"
    assert kind_of(b"%PDF-1.7") == "pdf"
    assert kind_of(OLE + b"rest") == "hwp"
    assert kind_of(b'{"ErrorMsg": "no file"}') is None
    assert kind_of(b"<!DOCTYPE html>") is None


def test_hwpx_text_keeps_paragraphs_and_section_order():
    data = _hwpx(
        {
            "section10.xml": "<hp:p><hp:t>열한째</hp:t></hp:p>",
            "section2.xml": "<hp:p><hp:t>셋째</hp:t></hp:p>",
            "section0.xml": "<hp:p><hp:t>계약 문의: 재무과</hp:t></hp:p>"
            "<hp:p><hp:t>사업 담당: 건축과 &amp; 건축팀</hp:t></hp:p>",
        }
    )
    text = extract_text(data)
    assert "계약 문의: 재무과\n사업 담당: 건축과 & 건축팀" in text
    assert text.index("셋째") < text.index("열한째")


def test_pdf_text_is_extracted():
    assert "Dept Office" in extract_text(_pdf("Dept Office"))


def test_hwp_records_keep_only_paragraph_text():
    para = _record(67, "행정과 담당\r".encode("utf-16-le"))
    other = _record(66, b"\x00" * 10)
    long_para = _record(67, ("가" * 3000).encode("utf-16-le"))
    text = hwp_records_text(other + para + long_para)
    assert text.startswith("행정과 담당\n")
    assert text.count("가") == 3000


def test_a_broken_file_reads_as_empty_instead_of_failing():
    assert extract_text(b"%PDF-1.4 broken") == ""
    assert extract_text(b"PK\x03\x04 broken zip") == ""
    assert extract_text(OLE + b"broken") == ""
    assert extract_text(b"plain text") == ""
```

- [ ] **Step 3: 실패를 확인한다**

Run: `PYTHONIOENCODING=utf-8 uv run pytest tests/test_doctext.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'nara.doctext'`

- [ ] **Step 4: 구현한다**

`nara/doctext.py`:

```python
"""첨부 문서에서 글자를 뽑는다. 형식은 확장자가 아니라 파일 앞부분으로 판별한다.

서버가 보낸 파일 이름은 깨져 있을 수 있다. 지자체 문서는 형식이 제각각이라
한 파일을 못 읽어도 빈 문자열을 돌려주고 넘어간다.
"""

import html
import io
import re
import zipfile
import zlib

import olefile
from pypdf import PdfReader

_OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_PARA_TEXT = 67  # HWPTAG_PARA_TEXT
_SECTION = re.compile(r"Contents/section(\d+)\.xml$")


def kind_of(data: bytes) -> str | None:
    if data.startswith(b"PK\x03\x04"):
        return "hwpx"
    if data.startswith(b"%PDF"):
        return "pdf"
    if data.startswith(_OLE):
        return "hwp"
    return None


def extract_text(data: bytes) -> str:
    """읽지 못하면 빈 문자열이다."""
    readers = {"hwpx": _hwpx, "pdf": _pdf, "hwp": _hwp}
    reader = readers.get(kind_of(data) or "")
    if reader is None:
        return ""
    try:
        text = reader(data)
    except Exception:  # 형식이 제각각이다. 한 파일 때문에 조회 전체가 멈추면 안 된다.
        return ""
    # HWP 본문에 섞인 서로게이트는 UTF-8로 저장할 수 없다. 대체 문자로 바꾼다.
    return text.encode("utf-8", "replace").decode("utf-8")


def _hwpx(data: bytes) -> str:
    parts = []
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        sections = [n for n in archive.namelist() if _SECTION.search(n)]
        sections.sort(key=lambda n: int(_SECTION.search(n).group(1)))
        for name in sections:
            xml = archive.read(name).decode("utf-8", "ignore")
            xml = xml.replace("</hp:p>", "\n")
            parts.append(html.unescape(re.sub(r"<[^>]+>", "", xml)))
    return "\n".join(parts)


def _pdf(data: bytes) -> str:
    reader = PdfReader(io.BytesIO(data))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _hwp(data: bytes) -> str:
    with olefile.OleFileIO(io.BytesIO(data)) as ole:
        compressed = bool(ole.openstream("FileHeader").read()[36] & 1)
        sections = [e for e in ole.listdir() if e[0] == "BodyText"]
        sections.sort(key=lambda e: int(re.sub(r"\D", "", e[-1]) or 0))
        parts = []
        for entry in sections:
            raw = ole.openstream("/".join(entry)).read()
            parts.append(hwp_records_text(zlib.decompress(raw, -15) if compressed else raw))
    return "\n".join(parts)


def hwp_records_text(data: bytes) -> str:
    """HWP 본문 레코드에서 문단 글자(태그 67)만 모은다."""
    out, i, n = [], 0, len(data)
    while i + 4 <= n:
        header = int.from_bytes(data[i : i + 4], "little")
        i += 4
        tag, size = header & 0x3FF, (header >> 20) & 0xFFF
        if size == 0xFFF:
            if i + 4 > n:
                break
            size = int.from_bytes(data[i : i + 4], "little")
            i += 4
        if i + size > n:
            break
        if tag == _PARA_TEXT:
            out.append(_para_text(data[i : i + size]))
        i += size
    return "\n".join(out)


def _para_text(raw: bytes) -> str:
    chars = []
    for k in range(0, len(raw) - 1, 2):
        code = int.from_bytes(raw[k : k + 2], "little")
        if code in (10, 13):
            chars.append("\n")
        elif code < 32:
            chars.append(" ")  # 표·그림 같은 조종 문자
        else:
            chars.append(chr(code))
    return "".join(chars)
```

- [ ] **Step 5: 통과를 확인한다**

Run: `PYTHONIOENCODING=utf-8 uv run pytest tests/test_doctext.py -q`
Expected: PASS (5개)

- [ ] **Step 6: 전체 검사와 커밋**

```bash
uv run ruff check --fix . && uv run ruff format . && PYTHONIOENCODING=utf-8 uv run pytest -q && uv run ruff check . && uv run ruff format --check .
git add pyproject.toml uv.lock nara/doctext.py tests/test_doctext.py
git commit -m "feat: 첨부 문서 읽기 — HWPX·PDF·HWP를 파일 앞부분으로 가려 읽는다

PDF는 AGPL인 PyMuPDF 대신 pypdf, HWP는 olefile로 읽는다. 못 읽으면 빈
문자열로 넘어간다.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: 첨부 받기

**Files:**
- Create: `nara/g2b/attach.py`, `tests/test_attach.py`

**Interfaces:**
- Consumes: Task 2의 `kind_of`
- Produces (`nara.g2b.attach`): `AttachError`, `RemoteFile(seq: int, name: str, url: str, kind: str = "")`, `Download(seq: int, name: str, content: bytes, kind: str)`, `files_from_raw(raw_json: str | None) -> list[RemoteFile]`, `probe_url(bid_no: str, bid_ord: str | None, seq: int) -> str`, `safe_name(raw: str) -> str`, `choose(files: list[RemoteFile]) -> list[RemoteFile]`, `fetch(client: httpx.Client, url: str) -> tuple[str, bytes, str]`, `gather(client, bid_no, bid_ord, raw_json, sleep=time.sleep) -> list[Download]`, 상수 `PAUSE_SECONDS = 0.5`, `MAX_BYTES`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_attach.py`:

```python
"""첨부 받기 — 다운로드 주소로 직접, 파일이 아니면 저장하지 않는다."""

import json

import httpx
import pytest

from nara.g2b import attach
from nara.g2b.attach import (
    AttachError,
    RemoteFile,
    choose,
    fetch,
    files_from_raw,
    gather,
    probe_url,
    safe_name,
)

HWPX = b"PK\x03\x04" + b"\x00" * 20
PDF = b"%PDF-1.4" + b"\x00" * 20
HWP = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 20


def _client(files: dict[int, tuple[int, dict, bytes]], seen: list | None = None):
    """fileSeq별 (상태, 머리, 본문). 없는 순번은 나라장터처럼 422와 JSON."""

    def handler(request: httpx.Request) -> httpx.Response:
        seq = int(request.url.params["fileSeq"])
        if seen is not None:
            seen.append(seq)
        status, headers, body = files.get(
            seq, (422, {"content-type": "application/json"}, b'{"ErrorMsg":"x"}')
        )
        return httpx.Response(status, headers=headers, content=body)

    return httpx.Client(transport=httpx.MockTransport(handler))


def _disp(name: str) -> dict:
    from urllib.parse import quote

    return {"content-disposition": f"attachment;filename={quote(name)};"}


def _raw(*pairs: tuple[str, str]) -> str:
    raw = {}
    for i in range(1, 11):
        name, url = pairs[i - 1] if i <= len(pairs) else ("", "")
        raw[f"ntceSpecFileNm{i}"] = name
        raw[f"ntceSpecDocUrl{i}"] = url
    return json.dumps(raw, ensure_ascii=False)


def test_files_from_raw_reads_names_and_urls():
    raw = _raw(("공고문.hwpx", "https://g2b/1"), ("", ""), ("과업지시서.hwp", "https://g2b/3"))
    assert files_from_raw(raw) == [
        RemoteFile(1, "공고문.hwpx", "https://g2b/1"),
        RemoteFile(3, "과업지시서.hwp", "https://g2b/3"),
    ]
    assert files_from_raw(None) == []
    assert files_from_raw("not json") == []


def test_probe_url_uses_the_bid_number_and_order():
    url = probe_url("R26BK01", None, 2)
    assert "bidPbancNo=R26BK01" in url and "bidPbancOrd=000" in url and "fileSeq=2" in url


def test_choose_prefers_the_notice_then_the_task_and_one_format_each():
    files = [
        RemoteFile(1, "참가신청서.hwp", "u1"),
        RemoteFile(2, "공고문.hwp", "u2"),
        RemoteFile(3, "공고문.pdf", "u3"),
        RemoteFile(4, "공고문.hwpx", "u4"),
        RemoteFile(5, "과업지시서.pdf", "u5"),
        RemoteFile(6, "설계공모지침서.hwp", "u6"),
        RemoteFile(7, "도면.zip", "u7"),
    ]
    assert [f.seq for f in choose(files)] == [4, 5]


def test_choose_falls_back_to_task_documents_and_skips_unreadable_files():
    files = [RemoteFile(1, "제안요청서.hwp", "u1"), RemoteFile(2, "공고.xlsx", "u2")]
    assert [f.seq for f in choose(files)] == [1]
    assert choose([RemoteFile(1, "도면.zip", "u1")]) == []


def test_safe_name_keeps_files_inside_the_folder():
    """서버가 보낸 이름으로 폴더 밖에 쓰면 안 된다."""
    assert safe_name("../../evil.hwp") == "evil.hwp"
    assert safe_name("a\\b\\c.pdf") == "c.pdf"
    assert safe_name("공고\x00문:?.hwp") == "공고_문__.hwp"
    assert safe_name("..") == "첨부"
    assert len(safe_name("가" * 300 + ".pdf")) == 100


def test_fetch_reads_the_name_from_the_header():
    client = _client({1: (200, _disp("공고문(청사).hwpx"), HWPX)})
    name, content, kind = fetch(client, probe_url("B1", "000", 1))
    assert (name, kind) == ("공고문(청사).hwpx", "hwpx")
    star = _client(
        {1: (200, {"content-disposition": "attachment; filename*=UTF-8''%EA%B3%B5.pdf"}, PDF)}
    )
    assert fetch(star, probe_url("B1", "000", 1))[0] == "공.pdf"


def test_fetch_refuses_a_page_that_is_not_a_file():
    """나라장터가 200으로 안내 페이지를 줘도 파일로 저장하면 안 된다."""
    client = _client({1: (200, {"content-type": "text/html"}, b"<!DOCTYPE html>")})
    with pytest.raises(AttachError):
        fetch(client, probe_url("B1", "000", 1))


def test_fetch_refuses_a_file_over_the_size_limit(monkeypatch):
    monkeypatch.setattr(attach, "MAX_BYTES", 10)
    client = _client({1: (200, _disp("공고문.pdf"), PDF)})
    with pytest.raises(AttachError, match="30MB"):
        fetch(client, probe_url("B1", "000", 1))


def test_gather_uses_the_listed_files_when_the_raw_notice_has_them():
    seen: list[int] = []
    client = _client({2: (200, _disp("x"), PDF)}, seen)
    raw = _raw(("참가신청서.hwp", probe_url("B1", "000", 1)), ("공고문.pdf", probe_url("B1", "000", 2)))
    got = gather(client, "B1", "000", raw, sleep=lambda s: None)
    assert [(d.seq, d.name, d.kind) for d in got] == [(2, "공고문.pdf", "pdf")]
    assert seen == [2]


def test_gather_reports_a_listed_file_that_does_not_download():
    client = _client({1: (200, {"content-type": "text/html"}, b"<html>")})
    raw = _raw(("공고문.pdf", probe_url("B1", "000", 1)))
    with pytest.raises(AttachError):
        gather(client, "B1", "000", raw, sleep=lambda s: None)


def test_gather_probes_numbers_until_the_first_non_file():
    """옛 공고는 원본이 없다. 순번을 차례로 받다가 파일이 아니면 멈춘다."""
    seen: list[int] = []
    client = _client(
        {
            1: (200, _disp("공고문.hwpx"), HWPX),
            2: (200, _disp("과업지시서.hwp"), HWP),
            3: (200, {"content-type": "text/html"}, b"<html>"),
            4: (200, _disp("공고문.pdf"), PDF),
        },
        seen,
    )
    got = gather(client, "B1", None, None, sleep=lambda s: None)
    assert [(d.seq, d.name) for d in got] == [(1, "공고문.hwpx"), (2, "과업지시서.hwp")]
    assert seen == [1, 2, 3]


def test_gather_waits_between_requests():
    waits: list[float] = []
    client = _client({1: (200, _disp("공고문.pdf"), PDF)})
    gather(client, "B1", None, None, sleep=waits.append)
    assert waits and all(w == attach.PAUSE_SECONDS for w in waits)
```

- [ ] **Step 2: 실패를 확인한다**

Run: `PYTHONIOENCODING=utf-8 uv run pytest tests/test_attach.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'nara.g2b.attach'`

- [ ] **Step 3: 구현한다**

`nara/g2b/attach.py`:

```python
"""나라장터 공고 첨부를 받는다. 브라우저 없이 다운로드 주소로 직접 받는다.

공고 API 원본에 파일 이름과 주소가 있으면 그것을 쓴다. 없으면(시트에서 옮긴 옛
공고) 공고번호와 순번으로 주소를 만들어 차례로 받아 보고, 파일이 아닌 응답이
오면 멈춘다. 2026-09-29 실측: 없는 순번은 422와 JSON 오류를 돌려준다.
"""

import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import unquote

import httpx

from nara.doctext import kind_of

DOWNLOAD_URL = (
    "https://www.g2b.go.kr/pn/pnp/pnpe/UntyAtchFile/downloadFile.do"
    "?bidPbancNo={bid_no}&bidPbancOrd={bid_ord}&fileType=&fileSeq={seq}&prcmBsneSeCd=05"
)
MAX_FILES = 10
MAX_BYTES = 30 * 1024 * 1024
TIMEOUT_SECONDS = 30.0
PAUSE_SECONDS = 0.5  # 나라장터에 부담을 주지 않도록 요청 사이에 쉰다
MAX_DOCS = 2
READABLE = ("hwpx", "pdf", "hwp")  # 같은 문서가 여러 형식이면 이 순서로 하나만
_GROUPS = (re.compile(r"공고"), re.compile(r"과업|지침|제안"))
_NAME_LIMIT = 100
_FILENAME_STAR = re.compile(r"filename\*\s*=\s*[Uu][Tt][Ff]-8''([^;]+)")
_FILENAME = re.compile(r'filename\s*=\s*"?([^";]+)"?')


class AttachError(Exception):
    """파일이 아닌 응답(오류 안내 JSON·HTML)이거나 너무 큰 파일."""


@dataclass(frozen=True)
class RemoteFile:
    seq: int
    name: str
    url: str
    kind: str = ""  # 받아 본 뒤에 안 형식. 모르면 확장자로 가린다


@dataclass(frozen=True)
class Download:
    seq: int
    name: str
    content: bytes
    kind: str


def files_from_raw(raw_json: str | None) -> list[RemoteFile]:
    if not raw_json:
        return []
    try:
        raw = json.loads(raw_json)
    except ValueError:
        return []
    files = []
    for i in range(1, MAX_FILES + 1):
        name = (raw.get(f"ntceSpecFileNm{i}") or "").strip()
        url = (raw.get(f"ntceSpecDocUrl{i}") or "").strip()
        if name and url:
            files.append(RemoteFile(i, name, url))
    return files


def probe_url(bid_no: str, bid_ord: str | None, seq: int) -> str:
    return DOWNLOAD_URL.format(bid_no=bid_no, bid_ord=bid_ord or "000", seq=seq)


def safe_name(raw: str) -> str:
    """서버가 보낸 이름에서 경로·제어 문자를 걷어 낸다. 폴더 밖으로 나가지 못하게 한다."""
    name = raw.replace("\\", "/").rsplit("/", 1)[-1]
    name = re.sub(r'[\x00-\x1f<>:"|?*]', "_", name).strip(" .")
    return name[:_NAME_LIMIT] or "첨부"


def _ext(name: str) -> str:
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def _stem(name: str) -> str:
    return name.rsplit(".", 1)[0] if "." in name else name


def _kind(f: RemoteFile) -> str:
    return f.kind or _ext(f.name)


def choose(files: list[RemoteFile]) -> list[RemoteFile]:
    """공고 → 과업·지침·제안 순으로 최대 두 문서. 같은 문서가 여러 형식이면 하나만."""
    readable = [f for f in files if _kind(f) in READABLE]
    picked: list[RemoteFile] = []
    for pattern in _GROUPS:
        group = [f for f in readable if pattern.search(f.name) and f not in picked]
        if not group:
            continue
        stem = _stem(group[0].name)
        same = [f for f in group if _stem(f.name) == stem]
        picked.append(min(same, key=lambda f: READABLE.index(_kind(f))))
        if len(picked) == MAX_DOCS:
            break
    return picked


def _header_name(disposition: str) -> str:
    match = _FILENAME_STAR.search(disposition) or _FILENAME.search(disposition)
    return unquote(match.group(1).strip()) if match else ""


def fetch(client: httpx.Client, url: str) -> tuple[str, bytes, str]:
    """(서버가 알려 준 이름, 내용, 형식). 파일이 아니면 AttachError."""
    with client.stream("GET", url, timeout=TIMEOUT_SECONDS, follow_redirects=True) as response:
        if response.status_code != 200:
            raise AttachError(f"HTTP {response.status_code}")
        chunks, size = [], 0
        for chunk in response.iter_bytes():
            size += len(chunk)
            if size > MAX_BYTES:
                raise AttachError("30MB를 넘는 파일")
            chunks.append(chunk)
        disposition = response.headers.get("content-disposition", "")
    content = b"".join(chunks)
    kind = kind_of(content)
    if kind is None:
        raise AttachError("PDF·HWPX·HWP 파일이 아님")
    return _header_name(disposition), content, kind


def gather(
    client: httpx.Client,
    bid_no: str,
    bid_ord: str | None,
    raw_json: str | None,
    sleep: Callable[[float], None] = time.sleep,
) -> list[Download]:
    """고른 문서를 받아 돌려준다. 받을 문서가 없으면 빈 목록.

    목록에 있던 파일을 못 받으면 AttachError·httpx.HTTPError를 그대로 올린다.
    """
    listed = files_from_raw(raw_json)
    if listed:
        downloads = []
        for f in choose(listed):
            sleep(PAUSE_SECONDS)
            _, content, kind = fetch(client, f.url)
            downloads.append(Download(f.seq, safe_name(f.name), content, kind))
        return downloads

    probed: list[RemoteFile] = []
    contents: dict[int, tuple[bytes, str]] = {}
    for seq in range(1, MAX_FILES + 1):
        sleep(PAUSE_SECONDS)
        try:
            name, content, kind = fetch(client, probe_url(bid_no, bid_ord, seq))
        except AttachError:
            break  # 없는 순번이다. 여기까지가 그 공고의 파일이다
        probed.append(RemoteFile(seq, safe_name(name or f"첨부{seq}.{kind}"), "", kind))
        contents[seq] = (content, kind)
    return [Download(f.seq, f.name, *contents[f.seq]) for f in choose(probed)]
```

- [ ] **Step 4: 통과를 확인한다**

Run: `PYTHONIOENCODING=utf-8 uv run pytest tests/test_attach.py -q`
Expected: PASS (13개)

- [ ] **Step 5: 전체 검사와 커밋**

```bash
uv run ruff check --fix . && uv run ruff format . && PYTHONIOENCODING=utf-8 uv run pytest -q && uv run ruff check . && uv run ruff format --check .
git add nara/g2b/attach.py tests/test_attach.py
git commit -m "feat: 공고 첨부를 다운로드 주소로 받는다 — 브라우저 없이

API 원본의 파일 목록을 쓰고, 없으면 공고번호와 순번으로 차례로 받아 본다.
파일 앞부분이 PDF·HWPX·HWP가 아니면 저장하지 않고, 서버가 보낸 이름에서
경로 문자를 걷어 낸다. 요청 사이 0.5초 쉬고 30MB 상한을 둔다.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: 부서 판정 규칙과 원문 대조

**Files:**
- Create: `nara/dept_rules.py`, `tests/test_dept_rules.py`

**Interfaces:**
- Produces (`nara.dept_rules`): `Candidate(name: str, weight: int, snippet: str, near: bool)`, `DeptAnswer(exec_dept: str | None, contract_dept: str | None, quote: str)`, `unspace(text) -> str`, `squash(text) -> str`, `find_candidates(text) -> list[Candidate]`(무게 큰 순), `find_contract_dept(text) -> str | None`, `decide_by_rule(candidates) -> Candidate | None`, `excerpt_for_llm(text) -> str`, `is_division(name) -> bool`, `verify_answer(text, answer: DeptAnswer) -> bool`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_dept_rules.py`:

```python
"""실행부서 판정 규칙 — 스킬에 적힌 실제 실패 사례를 옮겼다."""

from nara.dept_rules import (
    DeptAnswer,
    decide_by_rule,
    excerpt_for_llm,
    find_candidates,
    find_contract_dept,
    unspace,
    verify_answer,
)

PAIR = (
    "13. 기타사항\n"
    "가. 계약관련 문의: 재무과 계약팀 (063-000-0000)\n"
    "나. 사업관련 문의: 문화관광과 관광팀 (063-000-0001)\n"
)


def _names(text):
    return [c.name for c in find_candidates(text)]


def test_the_pair_structure_gives_the_executing_department():
    """공고문은 계약부서와 실행부서를 짝으로 적는다. 실행부서 쪽을 고른다."""
    candidates = find_candidates(PAIR)
    assert [c.name for c in candidates] == ["문화관광과"]
    assert candidates[0].near
    assert "사업관련 문의" in candidates[0].snippet
    assert decide_by_rule(candidates).name == "문화관광과"
    assert find_contract_dept(PAIR) == "재무과"


def test_contract_departments_are_never_candidates():
    assert _names("문의처: 재무과 경리팀 063-000-0000") == []
    assert _names("사업 담당 부서: 회계과") == []


def test_a_conjunction_is_not_a_department():
    """조사 '과'(=and)가 붙은 말은 부서가 아니다. '동 용역과'처럼 지시어 뒤도 그렇다."""
    assert _names("과업 관련 문의: 동 용역과 관련하여 도시계획과로 문의") == ["도시계획과"]
    assert _names("사업관련 문의는 다음과 같이 건축과 건축팀으로 한다") == ["건축과"]


def test_spaced_out_names_are_joined():
    """칸을 맞추려고 부서명 글자 사이를 띄운 공고문이 있다."""
    assert unspace("사업 담당 부서 : 행 정 과") == "사업 담당 부서 : 행정과"
    assert _names("사업 담당 부서 : 행 정 과 (063-000-0000)") == ["행정과"]


def test_a_team_name_is_reduced_to_its_division():
    assert _names("사업담당: 문화관광과 문화유산팀") == ["문화관광과"]


def test_two_candidates_are_not_decided_by_rule():
    text = "사업관련 문의: 건축과\n설계서 열람 문의: 도시재생과"
    assert sorted(_names(text)) == ["건축과", "도시재생과"]
    assert decide_by_rule(find_candidates(text)) is None


def test_a_department_far_from_the_cue_is_not_decided_by_rule():
    text = "사업관련 문의: " + "가" * 120 + " 건축과"
    candidates = find_candidates(text)
    assert [c.name for c in candidates] == ["건축과"]
    assert not candidates[0].near
    assert decide_by_rule(candidates) is None


def test_the_excerpt_keeps_the_contact_sections_and_the_end():
    body = "가" * 5000 + "\n사업관련 문의: 건축과\n" + "나" * 5000 + "\n문의처: 행정과 끝"
    excerpt = excerpt_for_llm(body)
    assert "사업관련 문의: 건축과" in excerpt
    assert excerpt.endswith("문의처: 행정과 끝")
    assert len(excerpt) <= 6000


def _answer(dept, quote, contract=None):
    return DeptAnswer(exec_dept=dept, contract_dept=contract, quote=quote)


def test_a_quote_found_in_the_text_confirms_the_answer():
    assert verify_answer(PAIR, _answer("문화관광과", "사업관련 문의: 문화관광과 관광팀"))


def test_spacing_and_line_breaks_do_not_break_the_match():
    """PDF는 줄을 아무 데서나 끊는다. 공백을 빼고 비교한다."""
    text = "나. 사업관련\n문의: 문화 관광과 관광팀"
    assert verify_answer(text, _answer("문화관광과", "사업관련 문의: 문화관광과 관광팀"))


def test_a_reworded_quote_is_rejected():
    assert not verify_answer(PAIR, _answer("문화관광과", "사업 문의는 문화관광과에서 받습니다"))


def test_a_department_missing_from_its_own_quote_is_rejected():
    assert not verify_answer(PAIR, _answer("건축과", "사업관련 문의: 문화관광과 관광팀"))


def test_a_contract_department_answer_is_rejected():
    assert not verify_answer(PAIR, _answer("재무과", "계약관련 문의: 재무과 계약팀"))


def test_a_team_only_or_empty_answer_is_rejected():
    text = "사업관련 문의: 관광팀 (063-000-0001)"
    assert not verify_answer(text, _answer("관광팀", "사업관련 문의: 관광팀"))
    assert not verify_answer(PAIR, _answer(None, "사업관련 문의: 문화관광과 관광팀"))
    assert not verify_answer(PAIR, _answer("문화관광과", "관광과"))
```

- [ ] **Step 2: 실패를 확인한다**

Run: `PYTHONIOENCODING=utf-8 uv run pytest tests/test_dept_rules.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'nara.dept_rules'`

- [ ] **Step 3: 구현한다**

`nara/dept_rules.py`:

```python
"""공고문에서 실행부서 후보를 찾고, Claude 답을 원문과 대조한다.

notice-dept-contact-lookup 스킬의 find_dept.py를 옮겼다. 규칙은 후보만 좁힌다.
후보가 하나이고 신호어 바로 뒤에서 찾았을 때만 확정한다. 조직도나 사업
성격으로 짐작하지 않는다 — 문서에서 읽은 것만 쓴다.
"""

import re
from collections import Counter
from dataclasses import dataclass

# 계약·회계 계열 = 실행부서가 아니다
EXCL = re.compile(r"^(재무|회계|경리|세정|예산|기획예산|계약|감사|재정관리)")
# 부서처럼 보이지만 아닌 것들 (시설명·법령·기관명)
BAD = re.compile(
    r"국가법령정보센터|조달청|나라장터|지방자치단|개찰|열람장소|기술사사무소"
    r"|소방시설|정보센터|본점소|건축사사무소|엔지니어링|전시실|회의실|사무실"
    r"|민원실|교실|도서관|숙소|화장실|창고|기계실|전기실|단련실|프로그램실|자료실"
)
# 조사 '과'(=and)가 붙어 부서명처럼 보이는 것들. "이 사업과 관련된" → 가짜 부서 "사업과"
JOSA = re.compile(
    r"^(사업|다음|역할|향상|방안|제반|기관|수단|입찰|군민|방문객|성찰|업무|계획|내용"
    r"|목적|결과|기준|조건|자격|서류|절차|방법|현황)과$"
)
# 앞에 지시관형사가 오면 조사 결합이다: "이 사업과", "본 사업과", "동 용역과"
DEICTIC = re.compile(r"(이|본|동|해당|당해|위)\s*$")
DEPT = re.compile(
    r"([가-힣]{2,12}(?:과|국|실|단|소|센터|본부|사업소|담당관))"
    r"(\s*([가-힣]{2,10}(?:팀|계|담당)))?"
)
# 실행부서를 가리키는 신호어 — 계약부서 신호어와 짝을 이뤄 등장하는 경우가 많다
CUE = re.compile(
    r"사업\s*담당|사업\s*부서|사업\s*관련|담당\s*부서|주관\s*부서|열람\s*문의"
    r"|설계서\s*열람|과업\s*(?:관련|문의|지시서)|설계\s*(?:관련|문의)"
    r"|용역에\s*관한|문의처|접수\s*처|장\s*소\s*:"
)
CONTRACT_CUE = re.compile(r"계약\s*(?:관련|문의|에\s*관한)|입찰\s*(?:관련|문의|에\s*관한)")
_SPACED = re.compile(r"(?<![가-힣])((?:[가-힣] ){2,}[과국실소단])(?![가-힣])")
_WS = re.compile(r"\s+")
WINDOW = 200  # 신호어 뒤로 부서를 찾는 폭
NEAR = 90  # 이 안에서 찾으면 신호어 바로 뒤로 본다
EXCERPT_AROUND = 300
EXCERPT_TAIL = 1500  # 문의처는 대개 공고문 끝에 있다
EXCERPT_LIMIT = 6000
MIN_QUOTE = 8


@dataclass(frozen=True)
class Candidate:
    name: str  # 과 단위 부서 이름
    weight: int
    snippet: str  # 근거 문장
    near: bool  # 신호어 바로 뒤(90자 안)에서 찾았는가


@dataclass(frozen=True)
class DeptAnswer:
    exec_dept: str | None
    contract_dept: str | None
    quote: str


def unspace(text: str) -> str:
    """칸을 맞추려고 띄운 부서명(`행 정 과`)을 붙인다."""
    return _SPACED.sub(lambda m: m.group(1).replace(" ", ""), text)


def squash(text: str) -> str:
    return _WS.sub("", text)


def _clean(text: str) -> str:
    return re.sub(r"[ \t]+", " ", unspace(text))


def _is_candidate(name: str, before: str) -> bool:
    if EXCL.match(name) or BAD.search(name) or len(name) < 3:
        return False
    return not (JOSA.match(name) or DEICTIC.search(before))


def find_candidates(text: str) -> list[Candidate]:
    txt = _clean(text)
    weights: Counter[str] = Counter()
    first: dict[str, tuple[str, bool]] = {}
    for cue in CUE.finditer(txt):
        start = cue.start()
        # 줄바꿈을 한 칸으로 바꿔 글자 위치를 그대로 둔다
        window = txt[start : start + WINDOW].replace("\n", " ")
        for m in DEPT.finditer(window):
            name = m.group(1)
            if not _is_candidate(name, window[: m.start()]):
                continue
            near = m.start() < NEAR
            weights[name] += 3 if near else 1
            end = start + max(150, m.end() + 20)
            snippet = _WS.sub(" ", txt[max(0, start - 40) : end]).strip()[:250]
            if name not in first or (near and not first[name][1]):
                first[name] = (snippet, near)
    return [Candidate(n, w, first[n][0], first[n][1]) for n, w in weights.most_common()]


def find_contract_dept(text: str) -> str | None:
    txt = _clean(text)
    for cue in CONTRACT_CUE.finditer(txt):
        window = txt[cue.start() : cue.start() + WINDOW].replace("\n", " ")
        for m in DEPT.finditer(window):
            if EXCL.match(m.group(1)):
                return m.group(1)
    return None


def decide_by_rule(candidates: list[Candidate]) -> Candidate | None:
    """후보가 하나뿐이고 신호어 바로 뒤에서 찾았을 때만 확정한다."""
    if len(candidates) == 1 and candidates[0].near:
        return candidates[0]
    return None


def excerpt_for_llm(text: str) -> str:
    """신호어 앞뒤 구간과 문서 끝. 끝부분은 잘리지 않게 남기고 앞쪽을 줄인다."""
    txt = _clean(text)
    tail_start = max(0, len(txt) - EXCERPT_TAIL)
    cues = [*CUE.finditer(txt), *CONTRACT_CUE.finditer(txt)]
    spans = sorted(
        (max(0, c.start() - EXCERPT_AROUND), min(tail_start, c.end() + EXCERPT_AROUND))
        for c in cues
        if c.start() < tail_start
    )
    merged: list[tuple[int, int]] = []
    for a, b in spans:
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        elif b > a:
            merged.append((a, b))
    budget = EXCERPT_LIMIT - (len(txt) - tail_start) - 3
    head = "\n…\n".join(txt[a:b] for a, b in merged)[: max(0, budget)]
    return (head + "\n…\n" if head else "") + txt[tail_start:]


def is_division(name: str) -> bool:
    """과 단위 이름인가. 팀·계·담당이 붙었거나 부서 꼴이 아니면 거짓."""
    m = DEPT.fullmatch(name)
    return m is not None and m.group(2) is None


def verify_answer(text: str, answer: DeptAnswer) -> bool:
    """근거 문장이 원문에 글자 그대로 있고, 그 안에 부서명이 있고, 계약 계열이 아니면 참.

    공백과 줄바꿈은 빼고 비교한다 — PDF 추출본은 줄을 아무 데서나 끊는다.
    """
    if not answer.exec_dept or not answer.quote:
        return False
    dept, quote = squash(answer.exec_dept), squash(answer.quote)
    if len(quote) < MIN_QUOTE or quote not in squash(text) or dept not in quote:
        return False
    return is_division(dept) and not EXCL.match(dept)
```

- [ ] **Step 4: 통과를 확인한다**

Run: `PYTHONIOENCODING=utf-8 uv run pytest tests/test_dept_rules.py -q`
Expected: PASS (15개). 기대와 다르면 규칙을 고치되, 테스트가 담은 사례(스킬 문서의 실패 사례)는 바꾸지 않는다

- [ ] **Step 5: 전체 검사와 커밋**

```bash
uv run ruff check --fix . && uv run ruff format . && PYTHONIOENCODING=utf-8 uv run pytest -q && uv run ruff check . && uv run ruff format --check .
git add nara/dept_rules.py tests/test_dept_rules.py
git commit -m "feat: 실행부서 판정 규칙과 원문 대조

스킬의 find_dept를 옮겼다. 계약·실행 짝에서 실행부서 후보를 찾고, 후보가
하나이고 신호어 바로 뒤일 때만 확정한다. Claude 답은 근거 문장이 원문에
공백 무시로 그대로 있고, 부서명이 그 안에 있고, 과 단위이고 계약 계열이
아닐 때만 받는다.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Claude에게 실행부서 묻기

**Files:**
- Modify: `nara/llm.py`
- Test: `tests/test_llm.py`

**Interfaces:**
- Consumes: Task 4의 `DeptAnswer`
- Produces (`nara.llm`): `ask_dept(secrets: Secrets, excerpt: str, client=None) -> DeptAnswer | None`. 모델은 `MODEL`(`claude-opus-5`) 그대로

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_llm.py`의 import 줄 `from nara.llm import adjudicate`를 `from nara.llm import adjudicate, ask_dept`로 바꾸고, `from nara.dept_rules import DeptAnswer`를 더한다. 파일 끝에 더한다:

```python
def test_ask_dept_reads_the_three_lines():
    client = _FakeClient(
        _Response("실행부서: 문화관광과\n계약부서: 재무과\n근거: 사업관련 문의: 문화관광과 관광팀")
    )
    answer = ask_dept(KEYED, "발췌", client=client)
    assert answer == DeptAnswer("문화관광과", "재무과", "사업관련 문의: 문화관광과 관광팀")


def test_ask_dept_treats_none_as_no_department():
    client = _FakeClient(_Response("실행부서: 없음\n계약부서: 없음\n근거: 없음"))
    answer = ask_dept(KEYED, "발췌", client=client)
    assert (answer.exec_dept, answer.contract_dept) == (None, None)


def test_ask_dept_without_a_key_does_not_call():
    client = _FakeClient(_Response("실행부서: 건축과"))
    assert ask_dept(KEYLESS, "발췌", client=client) is None


def test_ask_dept_fails_closed_on_a_truncated_answer():
    response = _Response("실행부서: 건축과")
    response.stop_reason = "max_tokens"
    assert ask_dept(KEYED, "발췌", client=_FakeClient(response)) is None
```

이 파일의 `_FakeClient`가 받은 인자를 기록한다면, 첫 테스트에 `system`이 실행부서 지시문이고 `model`이 `claude-opus-5`인지 확인하는 줄을 더한다(기록하지 않으면 더하지 않는다).

- [ ] **Step 2: 실패를 확인한다**

Run: `PYTHONIOENCODING=utf-8 uv run pytest tests/test_llm.py -q`
Expected: FAIL — `ImportError: cannot import name 'ask_dept'`

- [ ] **Step 3: 구현한다**

`nara/llm.py`의 import에 `from nara.dept_rules import DeptAnswer`를 더한다. `SYSTEM` 아래에 더한다:

```python
SYSTEM_DEPT = (
    "너는 한국 지자체 입찰 공고문에서 사업을 맡은 실행부서를 찾는다.\n"
    "다음 세 줄로만 답한다:\n"
    "실행부서: <부서 이름 또는 없음>\n"
    "계약부서: <부서 이름 또는 없음>\n"
    "근거: <공고문에서 글자를 바꾸지 않고 그대로 옮긴 문장>\n"
    "규칙:\n"
    "- 공고문에 적힌 것만 답한다. 조직도나 사업 성격으로 짐작하지 않는다.\n"
    "- 계약·입찰·개찰·회계 문의 부서(재무과·회계과 등)는 실행부서가 아니다.\n"
    "- 실행부서는 과 단위로 적는다. 팀 이름은 적지 않는다.\n"
    "- 확신이 없으면 '실행부서: 없음'이라고 적는다."
)
_NONE = {"", "없음", "없음.", "-"}
```

`adjudicate` 위에 공통 호출부를 더한다:

```python
def _complete(secrets: Secrets, system: str, content: str, client=None) -> str | None:
    """정상 종료한 답의 글자. 키가 없거나 실패하면 None."""
    if not secrets.anthropic_api_key:
        return None
    api = client or _shared_client(secrets.anthropic_api_key)
    try:
        response = api.messages.create(
            model=MODEL,
            max_tokens=1000,
            system=system,
            thinking={"type": "adaptive"},
            output_config={"effort": "low"},
            messages=[{"role": "user", "content": content}],
        )
    except anthropic.APIError:
        return None
    # 화이트리스트: 자연 종료(end_turn)만 받아들인다. tool·정지 시퀀스를
    # 쓰지 않으니 end_turn이 유일한 정상 종료다. refusal은 물론
    # max_tokens(중간에 잘린 근거를 그대로 판정으로 쓰게 됨) 같은 낯선
    # stop_reason도 전부 닫힌 쪽으로 실패한다.
    if getattr(response, "stop_reason", "") != "end_turn":
        return None
    return "".join(b.text for b in response.content if getattr(b, "type", "") == "text")
```

`adjudicate` 본문(키 확인부터 `text = ...`까지)을 이것으로 바꾼다. 어휘 확인 이후는 그대로 둔다:

```python
    text = _complete(secrets, SYSTEM, _prompt(project_name, articles, question), client)
    if text is None:
        return None
    head, _, tail = text.strip().partition("\n")
```

파일 끝에 더한다:

```python
def _field(text: str, label: str) -> str:
    for line in text.splitlines():
        head, sep, value = line.partition(":")
        if sep and head.strip() == label:
            return value.strip()
    return ""


def ask_dept(secrets: Secrets, excerpt: str, client=None) -> DeptAnswer | None:
    """공고문 발췌를 보여 주고 실행부서·계약부서·근거 문장을 받는다.

    답을 믿지 않는다 — 호출부가 근거 문장을 원문과 대조한 뒤에만 확정한다.
    """
    text = _complete(secrets, SYSTEM_DEPT, f"공고문 발췌:\n{excerpt}", client)
    if text is None:
        return None
    exec_dept, contract = _field(text, "실행부서"), _field(text, "계약부서")
    return DeptAnswer(
        exec_dept=None if exec_dept in _NONE else exec_dept,
        contract_dept=None if contract in _NONE else contract,
        quote=_field(text, "근거"),
    )
```

- [ ] **Step 4: 통과를 확인한다**

Run: `PYTHONIOENCODING=utf-8 uv run pytest tests/test_llm.py tests/test_status.py -q`
Expected: PASS 전부(진행현황 테스트는 공통 호출부로 바꾼 뒤에도 그대로 통과)

- [ ] **Step 5: 전체 검사와 커밋**

```bash
uv run ruff check --fix . && uv run ruff format . && PYTHONIOENCODING=utf-8 uv run pytest -q && uv run ruff check . && uv run ruff format --check .
git add nara/llm.py tests/test_llm.py
git commit -m "feat: Claude에게 실행부서를 묻는다 — 세 줄 답, 정상 종료만 받는다

진행현황 판정과 호출부를 함께 쓴다. 모델 이름은 그대로 둔다.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: 조회 흐름과 기록

**Files:**
- Create: `nara/dept.py`, `tests/test_dept.py`

**Interfaces:**
- Consumes: Task 1 `attachments_dir`·칸, Task 2 `extract_text`, Task 3 `gather`·`AttachError`·`Download`·`safe_name`, Task 4 규칙, Task 5 `ask_dept`의 모양(`asker(secrets, excerpt) -> DeptAnswer | None`)
- Produces (`nara.dept`): `DeptRun`(checked, confirmed_rule, confirmed_llm, review, not_found, failed, asked_llm, llm_unanswered, stopped_early), `pending_dept_projects(conn, tier, group, limit) -> list[sqlite3.Row]`, `update_depts(conn, client, secrets, attach_root, tier, group, limit, counters, asker, budget_seconds=1200, now_fn=time.monotonic, sleep=time.sleep) -> DeptRun`, 사유 상수 `NOTE_*`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_dept.py`:

```python
"""실행부서 조회 흐름 — 받기·읽기·판정·기록, 다시 볼 때와 멈출 때."""

import io
import json
import zipfile
from pathlib import Path

import httpx
import pytest

from nara.config import Secrets
from nara.db import connect, migrate
from nara.dept import (
    NOTE_DOWNLOAD_FAILED,
    NOTE_LLM_UNVERIFIED,
    NOTE_MANUAL,
    NOTE_NO_FILES,
    NOTE_NOT_FOUND,
    NOTE_RULE_CANDIDATE,
    pending_dept_projects,
    update_depts,
)
from nara.dept_rules import DeptAnswer
from nara.g2b.attach import probe_url
from nara.runlog import RunCounters

NOW = "2026-09-30T09:00:00"
KEYED = Secrets(g2b_api_key="g", naver_client_id=None, naver_client_secret=None, anthropic_api_key="k")
KEYLESS = Secrets(g2b_api_key="g", naver_client_id=None, naver_client_secret=None, anthropic_api_key=None)
ONE = "나. 사업관련 문의: 문화관광과 관광팀 (063-000-0001)\n가. 계약관련 문의: 재무과"
TWO = "사업관련 문의: 건축과\n설계서 열람 문의: 도시재생과\n계약관련 문의: 재무과"


def _hwpx(text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        paras = "".join(f"<hp:p><hp:t>{line}</hp:t></hp:p>" for line in text.split("\n"))
        z.writestr("Contents/section0.xml", paras)
    return buf.getvalue()


def _raw(bid_no, name="공고문.hwpx"):
    raw = {f"ntceSpecFileNm{i}": "" for i in range(1, 11)}
    raw |= {f"ntceSpecDocUrl{i}": "" for i in range(1, 11)}
    raw["ntceSpecFileNm1"], raw["ntceSpecDocUrl1"] = name, probe_url(bid_no, "000", 1)
    return json.dumps(raw, ensure_ascii=False)


@pytest.fixture
def db(tmp_path):
    conn = connect(tmp_path / "n.db")
    migrate(conn)
    conn.execute(
        "INSERT INTO org (id, name, tier, weekday_group, added_at) "
        "VALUES (1, '관심군', 'focus', NULL, ?), (2, '비관심시', 'rest', 3, ?)",
        (NOW, NOW),
    )
    conn.commit()
    return conn


def _project(conn, pid, org_id=1, bid_no=None, notice_date="2026-09-01", raw=True):
    conn.execute(
        "INSERT INTO project (id, org_id, name, source, created_at, updated_at) "
        "VALUES (?, ?, ?, 'g2b', ?, ?)",
        (pid, org_id, f"사업{pid}", NOW, NOW),
    )
    if bid_no:
        _notice(conn, pid, org_id, bid_no, notice_date, raw)
    conn.commit()


def _notice(conn, pid, org_id, bid_no, notice_date, raw=True):
    conn.execute(
        "INSERT INTO notice (bid_no, bid_ord, project_id, org_id, org_name, title, notice_date, "
        "raw_json, collected_at) VALUES (?, '000', ?, ?, '기관', '공고', ?, ?, ?)",
        (bid_no, pid, org_id, notice_date, _raw(bid_no) if raw else None, NOW),
    )
    conn.commit()


def _server(texts: dict[str, str], fail: set[str] = frozenset(), calls: list | None = None):
    """공고번호별 공고문. fail에 든 공고번호는 네트워크 오류."""

    def handler(request: httpx.Request) -> httpx.Response:
        bid_no = request.url.params["bidPbancNo"]
        seq = int(request.url.params["fileSeq"])
        if calls is not None:
            calls.append((bid_no, seq))
        if bid_no in fail:
            raise httpx.ConnectError("down")
        if seq == 1 and bid_no in texts:
            return httpx.Response(
                200,
                headers={"content-disposition": "attachment;filename=%EA%B3%B5%EA%B3%A0%EB%AC%B8.hwpx"},
                content=_hwpx(texts[bid_no]),
            )
        return httpx.Response(422, json={"ErrorMsg": "없음"})

    return httpx.Client(transport=httpx.MockTransport(handler))


def _run(conn, root, client, secrets=KEYLESS, asker=None, **kw):
    counters = RunCounters()
    run = update_depts(
        conn,
        client,
        secrets,
        root,
        kw.pop("tier", None),
        kw.pop("group", None),
        kw.pop("limit", 300),
        counters,
        asker=asker or (lambda s, e: None),
        sleep=lambda s: None,
        **kw,
    )
    return run, counters


def _rows(conn, pid):
    return [
        dict(r)
        for r in conn.execute(
            "SELECT exec_dept, contract_dept, decided_by, confirmed, note, source_file, bid_no "
            "FROM dept_check WHERE project_id = ? ORDER BY id",
            (pid,),
        )
    ]


def test_one_clear_candidate_is_confirmed_by_rule_and_the_file_is_kept(db, tmp_path):
    root = tmp_path / "attachments"
    _project(db, 1, bid_no="B1")
    run, counters = _run(db, root, _server({"B1": ONE}))
    [row] = _rows(db, 1)
    assert (row["exec_dept"], row["contract_dept"], row["decided_by"], row["confirmed"]) == (
        "문화관광과",
        "재무과",
        "rule",
        1,
    )
    assert row["source_file"] == "B1/1_공고문.hwpx"
    assert (root / "B1" / "1_공고문.hwpx").is_file()
    assert "문화관광과" in (root / "B1" / "1_공고문.hwpx.txt").read_text(encoding="utf-8")
    assert (run.confirmed_rule, counters.updated) == (1, 1)


def test_a_verified_claude_answer_is_confirmed(db, tmp_path):
    _project(db, 1, bid_no="B1")
    asker = lambda s, e: DeptAnswer("도시재생과", "재무과", "설계서 열람 문의: 도시재생과")  # noqa: E731
    run, _ = _run(db, tmp_path / "a", _server({"B1": TWO}), KEYED, asker)
    [row] = _rows(db, 1)
    assert (row["exec_dept"], row["decided_by"], row["confirmed"]) == ("도시재생과", "llm", 1)
    assert run.confirmed_llm == 1


def test_an_unverified_answer_leaves_candidates_for_review(db, tmp_path):
    _project(db, 1, bid_no="B1")
    asker = lambda s, e: DeptAnswer("문화예술과", None, "문화예술과에서 담당합니다")  # noqa: E731
    run, _ = _run(db, tmp_path / "a", _server({"B1": TWO}), KEYED, asker)
    rows = _rows(db, 1)
    assert all(r["confirmed"] == 0 for r in rows)
    assert {(r["exec_dept"], r["note"]) for r in rows} == {
        ("문화예술과", NOTE_LLM_UNVERIFIED),
        ("건축과", NOTE_RULE_CANDIDATE),
        ("도시재생과", NOTE_RULE_CANDIDATE),
    }
    assert run.review == 1


def test_without_a_key_rule_candidates_wait_for_review(db, tmp_path):
    _project(db, 1, bid_no="B1")
    run, _ = _run(db, tmp_path / "a", _server({"B1": TWO}))
    assert sorted(r["exec_dept"] for r in _rows(db, 1)) == ["건축과", "도시재생과"]
    assert (run.review, run.asked_llm) == (1, 0)


def test_nothing_found_is_recorded_with_a_reason(db, tmp_path):
    _project(db, 1, bid_no="B1")
    _project(db, 2, bid_no="B2", raw=False)  # 원본 없음 + 서버에 파일 없음 = 첨부 없음
    _run(db, tmp_path / "a", _server({"B1": "계약관련 문의: 재무과"}))
    assert _rows(db, 1)[0]["note"] == "공고문에 계약부서만 있음"
    assert _rows(db, 1)[0]["exec_dept"] is None
    assert _rows(db, 2)[0]["note"] == NOTE_NO_FILES


def test_old_notices_without_raw_data_are_probed(db, tmp_path):
    _project(db, 1, bid_no="B1", raw=False)
    calls: list = []
    _run(db, tmp_path / "a", _server({"B1": ONE}, calls=calls))
    assert _rows(db, 1)[0]["exec_dept"] == "문화관광과"
    assert calls == [("B1", 1), ("B1", 2)]


def test_confirmed_departments_are_left_alone(db, tmp_path):
    _project(db, 1, bid_no="B1")
    _project(db, 2, bid_no="B2")
    db.execute(
        "INSERT INTO dept_check (project_id, exec_dept, decided_by, checked_at) "
        "VALUES (1, '건축과', 'imported', ?), (2, '행정과', 'human', ?)",
        (NOW, NOW),
    )
    db.commit()
    calls: list = []
    run, _ = _run(db, tmp_path / "a", _server({"B1": ONE, "B2": ONE}, calls=calls))
    assert run.checked == 0 and calls == []


def test_a_project_is_looked_up_again_only_when_a_newer_notice_arrives(db, tmp_path):
    """수집이 최근 공고를 날마다 다시 받아 수집 시각이 바뀌어도 다시 받지 않는다."""
    _project(db, 1, bid_no="B1")
    server = _server({"B1": TWO, "B2": ONE})
    _run(db, tmp_path / "a", server)
    db.execute("UPDATE notice SET collected_at = '2026-10-01T09:00:00'")
    db.commit()
    assert pending_dept_projects(db, None, None, 300) == []
    _notice(db, 1, 1, "B2", "2026-09-20")  # 재공고
    run, _ = _run(db, tmp_path / "a", server)
    assert run.checked == 1
    assert _rows(db, 1)[-1]["exec_dept"] == "문화관광과"


def test_download_failures_are_retried_then_left_for_a_person(db, tmp_path):
    _project(db, 1, bid_no="B1")
    down = _server({}, fail={"B1"})
    for _ in range(3):
        run, counters = _run(db, tmp_path / "a", down)
        assert run.failed == 1 and counters.failed == 1
    notes = [r["note"] for r in _rows(db, 1)]
    assert notes == [NOTE_DOWNLOAD_FAILED, NOTE_DOWNLOAD_FAILED, NOTE_MANUAL]
    assert pending_dept_projects(db, None, None, 300) == []


def test_saved_files_are_read_again_without_downloading(db, tmp_path):
    root = tmp_path / "a"
    _project(db, 1, bid_no="B1")
    (root / "B1").mkdir(parents=True)
    (root / "B1" / "1_공고문.hwpx").write_bytes(b"x")
    (root / "B1" / "1_공고문.hwpx.txt").write_text(ONE, encoding="utf-8")
    db.execute(
        "INSERT INTO attachment (bid_no, seq, filename, path, text_path, status, attempts, "
        "downloaded_at) VALUES ('B1', 1, '공고문.hwpx', 'B1/1_공고문.hwpx', "
        "'B1/1_공고문.hwpx.txt', 'ok', 1, ?)",
        (NOW,),
    )
    db.commit()
    calls: list = []
    _run(db, root, _server({}, calls=calls))
    assert calls == []
    assert _rows(db, 1)[0]["exec_dept"] == "문화관광과"


def test_tier_and_group_select_the_projects(db, tmp_path):
    _project(db, 1, org_id=1, bid_no="B1")
    _project(db, 2, org_id=2, bid_no="B2")
    assert [r["id"] for r in pending_dept_projects(db, "rest", 3, 300)] == [2]
    assert [r["id"] for r in pending_dept_projects(db, "focus", None, 300)] == [1]
    assert pending_dept_projects(db, "rest", 4, 300) == []


def test_the_time_budget_stops_the_run(db, tmp_path):
    for pid in (1, 2, 3):
        _project(db, pid, bid_no=f"B{pid}")
    ticks = iter([0, 0, 100, 2000, 2000, 2000])
    run, _ = _run(db, tmp_path / "a", _server({}), budget_seconds=1200, now_fn=lambda: next(ticks))
    assert run.stopped_early and run.checked == 2
```

- [ ] **Step 2: 실패를 확인한다**

Run: `PYTHONIOENCODING=utf-8 uv run pytest tests/test_dept.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'nara.dept'`

- [ ] **Step 3: 구현한다**

`nara/dept.py`:

```python
"""실행부서 조회 흐름. 첨부를 받아 읽고, 규칙과 Claude로 부서를 찾아 기록한다.

확정된 부서(시트·사람·자동 확정)가 있는 사업은 보지 않는다. 한 번 본 사업은
가장 최근 공고번호가 바뀌었거나 지난번이 다운로드 실패였을 때만 다시 본다.
수집이 최근 3일 공고를 날마다 다시 받아 collected_at이 바뀌므로 시각이 아니라
공고번호로 비교한다.
"""

import hashlib
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import httpx

from nara.config import Secrets
from nara.dept_rules import (
    Candidate,
    DeptAnswer,
    decide_by_rule,
    excerpt_for_llm,
    find_candidates,
    find_contract_dept,
    squash,
    verify_answer,
)
from nara.doctext import extract_text
from nara.g2b.attach import AttachError, Download, gather, safe_name
from nara.runlog import RunCounters

BUDGET_SECONDS = 1200
MAX_DOWNLOAD_FAILURES = 3
NOTE_RULE_CANDIDATE = "규칙 후보"
NOTE_LLM_UNVERIFIED = "Claude 답이 원문과 맞지 않음"
NOTE_NO_FILES = "첨부 없음"
NOTE_READ_FAILED = "첨부를 읽지 못함"
NOTE_CONTRACT_ONLY = "공고문에 계약부서만 있음"
NOTE_NOT_FOUND = "공고문에서 실행부서를 찾지 못함"
NOTE_DOWNLOAD_FAILED = "다운로드 실패"
NOTE_MANUAL = "수동 확인"
_AUTO = "decided_by IN ('rule', 'llm')"

Asker = Callable[[Secrets, str], DeptAnswer | None]


@dataclass
class DeptRun:
    checked: int = 0
    confirmed_rule: int = 0
    confirmed_llm: int = 0
    review: int = 0
    not_found: int = 0
    failed: int = 0
    asked_llm: int = 0
    llm_unanswered: int = 0
    stopped_early: bool = False


@dataclass(frozen=True)
class _Doc:
    path: str  # 첨부 폴더 기준 경로. dept_check.source_file에 남는다
    text: str


def _newest_bid(conn: sqlite3.Connection, project_id: int) -> str | None:
    row = conn.execute(
        "SELECT bid_no FROM notice WHERE project_id = ? "
        "ORDER BY COALESCE(notice_date, '') DESC, bid_no DESC LIMIT 1",
        (project_id,),
    ).fetchone()
    return row[0] if row else None


def _last_auto(conn: sqlite3.Connection, project_id: int) -> sqlite3.Row | None:
    return conn.execute(
        f"SELECT bid_no, note FROM dept_check WHERE project_id = ? AND {_AUTO} "
        "ORDER BY checked_at DESC, id DESC LIMIT 1",
        (project_id,),
    ).fetchone()


def _due(conn: sqlite3.Connection, project_id: int) -> bool:
    newest = _newest_bid(conn, project_id)
    if newest is None:
        return False
    last = _last_auto(conn, project_id)
    if last is None:
        return True
    return last["bid_no"] != newest or last["note"] == NOTE_DOWNLOAD_FAILED


def pending_dept_projects(
    conn: sqlite3.Connection, tier: str | None, group: int | None, limit: int
) -> list[sqlite3.Row]:
    """확정 부서가 없고 다시 볼 이유가 있는 사업. 한 번도 안 본 사업부터."""
    sql = [
        "SELECT p.id, p.name,",
        f"  (SELECT MAX(d.checked_at) FROM dept_check d WHERE d.project_id = p.id AND {_AUTO})",
        "    AS last_auto",
        "FROM project p JOIN org o ON o.id = p.org_id",
        "WHERE EXISTS (SELECT 1 FROM notice n WHERE n.project_id = p.id)",
        "  AND NOT EXISTS (SELECT 1 FROM dept_check d WHERE d.project_id = p.id",
        "                  AND d.confirmed = 1 AND COALESCE(d.exec_dept, '') != '')",
    ]
    params: list[object] = []
    if tier:
        sql.append("  AND o.tier = ?")
        params.append(tier)
    if group is not None:
        sql.append("  AND o.weekday_group = ?")
        params.append(group)
    sql.append("ORDER BY last_auto IS NOT NULL, last_auto, p.id")
    rows = conn.execute("\n".join(sql), params).fetchall()
    return [row for row in rows if _due(conn, row["id"])][:limit]


def _record(
    conn: sqlite3.Connection,
    project_id: int,
    bid_no: str,
    now: str,
    *,
    exec_dept: str | None = None,
    contract_dept: str | None = None,
    snippet: str | None = None,
    source_file: str | None = None,
    decided_by: str = "rule",
    confirmed: int = 0,
    note: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO dept_check (project_id, bid_no, exec_dept, contract_dept, snippet, "
        "source_file, decided_by, confirmed, note, checked_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            project_id,
            bid_no,
            exec_dept,
            contract_dept,
            snippet,
            source_file,
            decided_by,
            confirmed,
            note,
            now,
        ),
    )


def _save(conn: sqlite3.Connection, root: Path, bid_no: str, d: Download, now: str) -> _Doc:
    rel = f"{safe_name(bid_no)}/{d.seq}_{d.name}"
    (root / rel).parent.mkdir(parents=True, exist_ok=True)
    (root / rel).write_bytes(d.content)
    text = extract_text(d.content)
    (root / f"{rel}.txt").write_text(text, encoding="utf-8")
    conn.execute(
        "INSERT INTO attachment (bid_no, seq, filename, path, sha256, text_path, status, "
        "attempts, downloaded_at) VALUES (?, ?, ?, ?, ?, ?, 'ok', 1, ?)",
        (bid_no, d.seq, d.name, rel, hashlib.sha256(d.content).hexdigest(), f"{rel}.txt", now),
    )
    return _Doc(rel, text)


def _documents(
    conn: sqlite3.Connection,
    client: httpx.Client,
    root: Path,
    notice: sqlite3.Row,
    now: str,
    sleep: Callable[[float], None],
) -> list[_Doc]:
    saved = conn.execute(
        "SELECT path, text_path FROM attachment WHERE bid_no = ? AND status = 'ok' ORDER BY seq",
        (notice["bid_no"],),
    ).fetchall()
    if saved:
        return [
            _Doc(r["path"], (root / r["text_path"]).read_text(encoding="utf-8")) for r in saved
        ]
    downloads = gather(client, notice["bid_no"], notice["bid_ord"], notice["raw_json"], sleep)
    return [_save(conn, root, notice["bid_no"], d, now) for d in downloads]


def _recent_failures(conn: sqlite3.Connection, project_id: int, marker: str) -> int:
    notes = conn.execute(
        f"SELECT note FROM dept_check WHERE project_id = ? AND {_AUTO} AND bid_no = ? "
        "ORDER BY checked_at DESC, id DESC",
        (project_id, marker),
    ).fetchall()
    count = 0
    for (note,) in notes:
        if note != NOTE_DOWNLOAD_FAILED:
            break
        count += 1
    return count


def _first_candidates(docs: list[_Doc]) -> tuple[list[Candidate], str | None]:
    """공고문에서 먼저 찾고, 없으면 과업지시서·지침서를 본다."""
    for doc in docs:
        found = find_candidates(doc.text)
        if found:
            return found, doc.path
    return [], None


def _source_of(docs: list[_Doc], quote: str) -> str | None:
    needle = squash(quote)
    return next((d.path for d in docs if needle in squash(d.text)), None)


def _process(
    conn: sqlite3.Connection,
    client: httpx.Client,
    secrets: Secrets,
    root: Path,
    project_id: int,
    asker: Asker,
    now: str,
    sleep: Callable[[float], None],
    run: DeptRun,
) -> None:
    notices = conn.execute(
        "SELECT bid_no, bid_ord, raw_json FROM notice WHERE project_id = ? "
        "ORDER BY COALESCE(notice_date, '') DESC, bid_no DESC",
        (project_id,),
    ).fetchall()
    marker = notices[0]["bid_no"]
    docs: list[_Doc] = []
    try:
        for notice in notices:
            docs = _documents(conn, client, root, notice, now, sleep)
            if docs:
                break
    except (httpx.HTTPError, AttachError, OSError):
        failures = _recent_failures(conn, project_id, marker) + 1
        note = NOTE_MANUAL if failures >= MAX_DOWNLOAD_FAILURES else NOTE_DOWNLOAD_FAILED
        _record(conn, project_id, marker, now, note=note)
        run.failed += 1
        return

    if not docs:
        _record(conn, project_id, marker, now, note=NOTE_NO_FILES)
        run.not_found += 1
        return
    readable = [d for d in docs if d.text.strip()]
    if not readable:
        _record(conn, project_id, marker, now, note=NOTE_READ_FAILED)
        run.not_found += 1
        return

    full_text = "\n".join(d.text for d in readable)
    contract = find_contract_dept(full_text)
    candidates, source = _first_candidates(readable)
    chosen = decide_by_rule(candidates)
    if chosen is not None:
        _record(
            conn, project_id, marker, now, exec_dept=chosen.name, contract_dept=contract,
            snippet=chosen.snippet, source_file=source, confirmed=1,
        )
        run.confirmed_rule += 1
        return

    answer = None
    if secrets.anthropic_api_key:
        run.asked_llm += 1
        answer = asker(secrets, excerpt_for_llm(full_text))
        if answer is None:
            run.llm_unanswered += 1
    if answer is not None and verify_answer(full_text, answer):
        _record(
            conn, project_id, marker, now, exec_dept=answer.exec_dept,
            contract_dept=answer.contract_dept or contract, snippet=answer.quote,
            source_file=_source_of(readable, answer.quote), decided_by="llm", confirmed=1,
        )
        run.confirmed_llm += 1
        return

    if answer is not None and answer.exec_dept:
        _record(
            conn, project_id, marker, now, exec_dept=answer.exec_dept, contract_dept=contract,
            snippet=answer.quote, decided_by="llm", note=NOTE_LLM_UNVERIFIED,
        )
    for c in candidates:
        _record(
            conn, project_id, marker, now, exec_dept=c.name, contract_dept=contract,
            snippet=c.snippet, source_file=source, note=NOTE_RULE_CANDIDATE,
        )
    if candidates or (answer is not None and answer.exec_dept):
        run.review += 1
        return
    note = NOTE_CONTRACT_ONLY if contract else NOTE_NOT_FOUND
    _record(conn, project_id, marker, now, contract_dept=contract, note=note)
    run.not_found += 1


def update_depts(
    conn: sqlite3.Connection,
    client: httpx.Client,
    secrets: Secrets,
    attach_root: Path,
    tier: str | None,
    group: int | None,
    limit: int,
    counters: RunCounters,
    asker: Asker,
    budget_seconds: int = BUDGET_SECONDS,
    now_fn: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> DeptRun:
    """대상을 돌며 부서를 찾는다. 사업마다 커밋해 중간에 멈춰도 거기까지는 남는다."""
    run = DeptRun()
    started = now_fn()
    for row in pending_dept_projects(conn, tier, group, limit):
        if now_fn() - started > budget_seconds:
            run.stopped_early = True
            break
        counters.processed += 1
        run.checked += 1
        failed_before = run.failed
        now = datetime.now().isoformat(timespec="seconds")
        try:
            _process(conn, client, secrets, attach_root, row["id"], asker, now, sleep, run)
        except sqlite3.Error:
            raise  # 저장 계층이 망가졌다. 사업 한 건의 실패가 아니다
        except Exception:
            # 한 건이 터져도 나머지를 본다. 기록이 없으니 다음 회차에 다시 본다.
            conn.rollback()
            run.failed += 1
        conn.commit()
        if run.failed > failed_before:
            counters.failed += 1
    counters.updated = run.confirmed_rule + run.confirmed_llm
    return run
```

- [ ] **Step 4: 통과를 확인한다**

Run: `PYTHONIOENCODING=utf-8 uv run pytest tests/test_dept.py -q`
Expected: PASS (13개). `test_the_time_budget_stops_the_run`의 시계 값은 "시작 0 → 첫 사업 전 0 → 둘째 사업 전 100 → 셋째 사업 전 2000"이다. 호출 횟수가 달라 실패하면 구현의 `now_fn()` 호출 위치를 스펙(사업 시작 전 한 번)대로 맞춘다

- [ ] **Step 5: 전체 검사와 커밋**

```bash
uv run ruff check --fix . && uv run ruff format . && PYTHONIOENCODING=utf-8 uv run pytest -q && uv run ruff check . && uv run ruff format --check .
git add nara/dept.py tests/test_dept.py
git commit -m "feat: 실행부서 조회 흐름 — 받아 읽고 판정해 확정·후보·사유로 남긴다

확정된 부서가 없는 사업만 보고, 가장 최근 공고번호가 바뀌었거나 지난번이
다운로드 실패였을 때만 다시 본다. 같은 공고에서 3번 연달아 실패하면 수동
확인으로 남긴다. 받은 첨부와 추출 텍스트는 첨부 폴더에 두고 다시 받지 않는다.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: 명령과 예약

**Files:**
- Modify: `nara/cli.py`, `nara/slot.py`, `nara/web/data.py`
- Test: `tests/test_slot.py`, `tests/test_web.py`, `tests/test_dept.py`

**Interfaces:**
- Consumes: Task 6 `update_depts`, `DeptRun`; Task 5 `ask_dept`; Task 1 `attachments_dir`
- Produces: `nara enrich dept [--tier] [--group] [--limit] [--budget] [--db]`, 슬롯 단계 `Step("enrich dept", {"tier": ..., "group": ...})`, 목록 머리 단계 `("enrich dept", "실행부서")`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_slot.py`에서 슬롯 계획 테스트 두 개의 기대를 바꾼다.

`test_morning_and_afternoon_slots_follow_the_schedule`의 목록을:

```python
        assert plan(slot, 1) == [
            Step("collect", {"days": 3}),
            Step("enrich award", {"tier": "focus", "group": None}),
            Step("enrich status", {"tier": "focus"}),
            Step("enrich dept", {"tier": "focus", "group": None}),
        ]
```

`test_noon_slot_checks_awards_for_todays_weekday_group`의 목록을:

```python
    assert plan("12", 3) == [
        Step("collect", {"days": 3}),
        Step("enrich award", {"tier": "rest", "group": 3}),
        Step("enrich dept", {"tier": "rest", "group": 3}),
    ]
```

같은 파일 `_fake_runners`의 이름 튜플 `("collect", "enrich award", "enrich status")`를 `("collect", "enrich award", "enrich status", "enrich dept")`로 바꾸고, `test_run_slot_keeps_going_after_a_failed_step`의 기대를 `["collect", "enrich award", "enrich status", "enrich dept"]`로 바꾼다.

`tests/test_web.py`의 단계 이름 기대 두 곳을 바꾼다: `["수집", "낙찰 조회", "진행현황", "백업"]` → `["수집", "낙찰 조회", "진행현황", "실행부서", "백업"]`, `{"수집", "낙찰 조회", "진행현황", "백업"}` → `{"수집", "낙찰 조회", "진행현황", "실행부서", "백업"}`. 그 테스트가 `run_log`에 단계마다 줄을 넣는다면 `enrich dept` 줄도 같은 방식으로 넣는다.

`tests/test_dept.py` 맨 위 import 묶음에 `from typer.testing import CliRunner`, `from nara import cli`를 더하고, `from nara.dept import (...)` 목록에 `DeptRun`을 더한다. 파일 끝에 명령 테스트를 더한다:

```python
def test_enrich_dept_command_reports_and_logs(tmp_path, monkeypatch):
    db_path = tmp_path / "data" / "n.db"
    conn = connect(db_path)
    migrate(conn)
    conn.close()
    seen = {}

    def fake(conn, client, secrets, root, tier, group, limit, counters, asker, budget_seconds):
        seen.update(root=root, tier=tier, group=group, budget=budget_seconds)
        counters.processed = 3
        return DeptRun(checked=3, confirmed_rule=1, confirmed_llm=1, review=1)

    monkeypatch.setattr(cli, "update_depts", fake)
    result = CliRunner().invoke(
        cli.app, ["enrich", "dept", "--tier", "rest", "--group", "2", "--db", str(db_path)]
    )
    assert result.exit_code == 0, result.output
    assert "실행부서 — 조회 3건 / 확정 규칙 1·Claude 1 / 검토 필요 1 / 못 찾음 0 / 실패 0" in (
        result.output
    )
    assert seen == {"root": tmp_path / "data" / "attachments", "tier": "rest", "group": 2, "budget": 1200}
    conn = connect(db_path)
    assert conn.execute("SELECT status FROM run_log WHERE command = 'enrich dept'").fetchone()[0] == "ok"


def test_enrich_dept_refuses_an_unknown_tier(tmp_path):
    result = CliRunner().invoke(cli.app, ["enrich", "dept", "--tier", "x", "--db", str(tmp_path / "n.db")])
    assert result.exit_code == 1
```

- [ ] **Step 2: 실패를 확인한다**

Run: `PYTHONIOENCODING=utf-8 uv run pytest tests/test_slot.py tests/test_web.py tests/test_dept.py -q -k "slot or runs or enrich_dept"`
Expected: FAIL — 계획에 `enrich dept` 없음, `No such command 'dept'`

- [ ] **Step 3: 구현한다**

`nara/slot.py`의 `plan`에서 12시 분기의 `steps.append(Step("enrich award", {"tier": "rest", "group": weekday}))` 아래에 같은 들여쓰기로 더한다:

```python
            steps.append(Step("enrich dept", {"tier": "rest", "group": weekday}))
```

같은 함수 끝 `steps.append(Step("enrich status", {"tier": "focus"}))` 아래에 더한다:

```python
    steps.append(Step("enrich dept", {"tier": "focus", "group": None}))
```

`LOCK_MAX_AGE` 위 주석의 `(수집 + 낙찰 + 진행현황 예산 20분)`을 `(수집 + 낙찰 + 진행현황 20분 + 실행부서 20분)`으로 바꾼다.

`nara/web/data.py`의 `PIPELINE_STAGES`에서 `("enrich status", "진행현황"),` 아래에 `("enrich dept", "실행부서"),`를 더한다.

`nara/cli.py`의 import에 더한다:

```python
from nara.db import attachments_dir
from nara.dept import update_depts
from nara.llm import ask_dept
```

(`from nara.db import connect, migrate`가 이미 있으면 그 줄에 `attachments_dir`만 더한다. `nara.llm` import가 이미 있으면 `ask_dept`만 더한다.)

`enrich_status` 명령 함수 아래에 더한다:

```python
@enrich_app.command("dept")
def enrich_dept(
    tier: str = typer.Option("all", help="focus | rest | all"),
    group: int | None = typer.Option(None, help="비관심 기관 요일 그룹 1~5"),
    limit: int = typer.Option(300, min=1, help="한 번에 볼 최대 사업 수"),
    budget: int = typer.Option(1200, min=1, help="시간 예산(초). 넘기면 저장하고 멈춘다"),
    db: Path = typer.Option(DEFAULT_DB),
) -> None:
    """공고 첨부에서 실행부서를 찾는다."""
    if tier not in {"focus", "rest", "all"}:
        typer.echo(f"--tier는 focus | rest | all 중 하나여야 한다: {tier!r}", err=True)
        raise typer.Exit(code=1)
    secrets = load_secrets(DEFAULT_ENV)
    conn = _open_db(db)
    selected = None if tier == "all" else tier
    with run_log(conn, "enrich dept", f"--tier {tier}") as counters:
        with httpx.Client() as client:
            run = update_depts(
                conn,
                client,
                secrets,
                attachments_dir(db),
                selected,
                group,
                limit,
                counters,
                asker=ask_dept,
                budget_seconds=budget,
            )
    typer.echo(
        f"실행부서 — 조회 {run.checked}건 / 확정 규칙 {run.confirmed_rule}·"
        f"Claude {run.confirmed_llm} / 검토 필요 {run.review} / 못 찾음 {run.not_found} / "
        f"실패 {run.failed}"
    )
    if not secrets.anthropic_api_key:
        typer.echo("Claude API 키가 없어 애매한 건을 검토 필요로 남긴다")
    if run.stopped_early:
        typer.echo("시간 예산을 넘겨 멈췄다 — 다음 회차가 이어서 본다")
    if run.failed and run.failed == run.checked:
        typer.echo("전체 조회 실패 — 네트워크를 확인한다.", err=True)
        raise typer.Exit(code=1)
```

`_STEP_RUNNERS`에 더한다(`"enrich status": ...` 항목 아래):

```python
    "enrich dept": lambda db, config, tier, group: enrich_dept(
        tier=tier, group=group, limit=300, budget=1200, db=db
    ),
```

- [ ] **Step 4: 통과를 확인한다**

Run: `PYTHONIOENCODING=utf-8 uv run pytest -q`
Expected: PASS 전부

- [ ] **Step 5: 전체 검사와 커밋**

```bash
uv run ruff check --fix . && uv run ruff format . && PYTHONIOENCODING=utf-8 uv run pytest -q && uv run ruff check . && uv run ruff format --check .
git add nara/cli.py nara/slot.py nara/web/data.py tests
git commit -m "feat: nara enrich dept와 슬롯 단계 — 관심 09·15시, 비관심 평일 12시 요일별

목록 머리의 단계별 마지막 실행에 실행부서를 더했다.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: 화면 — 검토 필요, 판정 주체, 첨부 내려받기

**Files:**
- Modify: `nara/web/query.py`, `nara/web/app.py`, `nara/web/data.py`, `nara/web/templates/list.html`, `nara/web/templates/detail.html`
- Test: `tests/test_web.py`, `tests/test_web_query.py`

**Interfaces:**
- Consumes: Task 1 `attachments_dir`, 칸
- Produces: `Filters.dept_review: bool`, URL 인자 `dept=review`, 목록 행 `dept_review`, `ProjectDetail.attachments`, 라우트 `attachment`(`GET /attachment/<int:attachment_id>`), `app.config["ATTACH_DIR"]`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_web_query.py` 끝에 더한다(이 파일이 `parse_filters`·`to_args`를 import하는 방식을 따른다):

```python
def test_the_review_filter_round_trips_through_the_url():
    f, notes = parse_filters({"dept": ["review"]})
    assert f.dept_review and notes == []
    assert to_args(f)["dept"] == ["review"]
    assert "dept" not in to_args(parse_filters({})[0])
```

`tests/test_web.py` 끝에 더한다:

```python
def test_a_project_with_only_candidates_is_marked_for_review(world):
    path, ids = world
    conn = connect(path)
    _dept(conn, ids["culture"], "도시재생과", "2026-09-28T09:00:00", "rule", confirmed=0)
    _dept(conn, ids["gym"], "건축과", "2026-09-01T09:00:00")
    _dept(conn, ids["gym"], "문화관광과", "2026-09-28T09:00:00", "rule", confirmed=0)
    conn.commit()
    conn.close()
    client = _client(path)
    rows = {r["id"]: r for r in _list(path).rows}
    assert rows[ids["culture"]]["dept_review"] and not rows[ids["gym"]]["dept_review"]
    only = _list(path, dept_review=True).rows
    assert [r["id"] for r in only] == [ids["culture"]]
    text = _text(client.get("/?dept=review"))
    assert "검토 필요" in text and "실행부서 검토 필요" in text


def test_detail_shows_candidates_with_their_source_and_reason(world):
    path, ids = world
    conn = connect(path)
    conn.execute(
        "INSERT INTO dept_check (project_id, exec_dept, snippet, source_file, decided_by, "
        "confirmed, note, checked_at) VALUES (?, '도시재생과', '설계서 열람 문의: 도시재생과', "
        "'N6/1_공고문.hwpx', 'rule', 0, '규칙 후보', '2026-09-28T09:00:00')",
        (ids["culture"],),
    )
    conn.execute(
        "INSERT INTO dept_check (project_id, decided_by, confirmed, note, checked_at) "
        "VALUES (?, 'rule', 0, '첨부 없음', '2026-09-27T09:00:00')",
        (ids["culture"],),
    )
    conn.commit()
    conn.close()
    text = _text(_client(path).get(f"/project/{ids['culture']}"))
    for expected in ("도시재생과", "후보", "규칙", "N6/1_공고문.hwpx", "규칙 후보", "첨부 없음"):
        assert expected in text


def _attachment(path, rel, filename="공고문.pdf", body=b"%PDF-1.4 test"):
    root = path.parent / "attachments"
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(body)
    conn = connect(path)
    cur = conn.execute(
        "INSERT INTO attachment (bid_no, seq, filename, path, status, attempts, downloaded_at) "
        "VALUES ('N6', 1, ?, ?, 'ok', 1, '2026-09-28T09:00:00')",
        (filename, rel),
    )
    conn.commit()
    conn.close()
    return cur.lastrowid


def test_a_saved_attachment_is_listed_and_downloads(world):
    path, ids = world
    aid = _attachment(path, "N6/1_공고문.pdf")
    client = _client(path)
    assert "공고문.pdf" in _text(client.get(f"/project/{ids['culture']}"))
    resp = client.get(f"/attachment/{aid}")
    assert resp.status_code == 200
    assert resp.data == b"%PDF-1.4 test"
    assert "attachment" in resp.headers["Content-Disposition"]


def test_attachment_download_needs_login(world):
    path, _ = world
    aid = _attachment(path, "N6/1_공고문.pdf")
    assert _app(path).test_client().get(f"/attachment/{aid}").status_code == 302


def test_attachment_download_never_leaves_the_folder(world):
    """DB에 적힌 경로가 폴더 밖을 가리켜도 내주면 안 된다."""
    path, _ = world
    aid = _attachment(path, "N6/1_공고문.pdf")
    conn = connect(path)
    conn.execute("UPDATE attachment SET path = '../w.db' WHERE id = ?", (aid,))
    conn.commit()
    conn.close()
    client = _client(path)
    assert client.get(f"/attachment/{aid}").status_code == 404
    assert client.get("/attachment/999999").status_code == 404
```

- [ ] **Step 2: 실패를 확인한다**

Run: `PYTHONIOENCODING=utf-8 uv run pytest tests/test_web.py tests/test_web_query.py -q -k "review or candidates_with or attachment"`
Expected: FAIL — `dept_review` 없음, 라우트 없음

- [ ] **Step 3: 조회를 바꾼다**

`nara/web/query.py`:

1. `Filters`에 `verdicts` 아래 `dept_review: bool = False`를 더한다.
2. `parse_filters`의 `Filters(...)` 인자에 `dept_review=_first(args, "dept") == "review",`를 더한다.
3. `to_args`의 `if f.verdicts:` 블록 아래에 더한다:

```python
    if f.dept_review:
        args["dept"] = ["review"]
```

4. `_LATEST`의 `ld AS (...)` 뒤, 닫는 `"""` 앞에 CTE를 더한다(앞 CTE 끝의 `)` 뒤에 쉼표를 붙인다):

```sql
lr AS (
    SELECT DISTINCT d.project_id
    FROM dept_check d
    WHERE d.project_id IS NOT NULL AND d.confirmed = 0 AND COALESCE(d.exec_dept, '') != ''
)
```

5. `_FROM`의 `LEFT JOIN ld ...` 줄 아래에 `LEFT JOIN lr ON lr.project_id = p.id`를 더한다.
6. `_where`의 `if f.verdicts:` 블록 아래에 더한다:

```python
    if f.dept_review:
        clauses.append("(lr.project_id IS NOT NULL AND ld.exec_dept IS NULL)")
```

7. `build_list_query`의 선택 목록 `+ "ld.exec_dept, p.zeb_grade, "`를 `+ "ld.exec_dept, (lr.project_id IS NOT NULL AND ld.exec_dept IS NULL) AS dept_review, "` 와 `+ "p.zeb_grade, "` 두 줄로 바꾼다.

`nara/web/app.py`의 `_conditions`에서 `parts.extend(f.verdicts)` 아래에 더한다:

```python
    if f.dept_review:
        parts.append("실행부서 검토 필요")
```

- [ ] **Step 4: 상세 자료와 첨부 라우트**

`nara/web/data.py`:

1. `ProjectDetail`에 `edits` 아래 `attachments: list[sqlite3.Row] = ()`를 더한다.
2. `project_detail`의 `depts = conn.execute(...)` 전체를 이것으로 바꾼다:

```python
    depts = [
        {**dict(row), "by_label": DECIDED_BY_LABELS.get(row["decided_by"], row["decided_by"])}
        for row in conn.execute(
            "SELECT id, exec_dept, contract_dept, snippet, source_file, decided_by, confirmed, "
            "note, checked_at FROM dept_check "
            "WHERE project_id = ? ORDER BY checked_at DESC, id DESC",
            (project_id,),
        )
    ]
    attachments = conn.execute(
        "SELECT a.id, a.bid_no, a.filename, a.downloaded_at FROM attachment a "
        "JOIN notice n ON n.bid_no = a.bid_no "
        "WHERE n.project_id = ? AND a.status = 'ok' ORDER BY a.bid_no DESC, a.seq",
        (project_id,),
    ).fetchall()
```

3. `return ProjectDetail(` 인자에 `attachments=attachments,`를 더한다.
4. `ProjectDetail.depts`의 타입을 `list[dict]`로 바꾼다.

`nara/web/app.py`:

1. flask import 목록에 `send_file`을 더한다. `from nara.db import attachments_dir`를 더한다.
2. `create_app`의 `app.config["DB_PATH"] = Path(db_path)` 아래에 `app.config["ATTACH_DIR"] = attachments_dir(Path(db_path))`를 더한다.
3. `detail` 라우트 아래에 더한다:

```python
    @app.get("/attachment/<int:attachment_id>")
    def attachment(attachment_id: int):
        row = get_conn().execute(
            "SELECT filename, path FROM attachment WHERE id = ? AND status = 'ok'",
            (attachment_id,),
        ).fetchone()
        if row is None or not row["path"]:
            abort(404)
        root = Path(current_app.config["ATTACH_DIR"]).resolve()
        target = (root / row["path"]).resolve()
        # DB에 적힌 경로를 믿지 않는다. 첨부 폴더 밖이면 없는 것으로 친다.
        if not target.is_relative_to(root) or not target.is_file():
            abort(404)
        return send_file(target, as_attachment=True, download_name=row["filename"])
```

- [ ] **Step 5: 템플릿**

`nara/web/templates/list.html`:

1. `관심기관만` 체크박스가 든 `<span>` 줄 아래에 더한다:

```html
    <span><input type="checkbox" name="dept" value="review"{% if f.dept_review %} checked{% endif %}> 실행부서 검토 필요</span>
```

2. `<td>{{ r.exec_dept|dash }}</td>`를 이것으로 바꾼다:

```html
  <td>{% if r.exec_dept %}{{ r.exec_dept }}{% elif r.dept_review %}<span class="muted">검토 필요</span>{% else %}—{% endif %}</td>
```

`nara/web/templates/detail.html`:

1. 공고 표의 `</table></div>` 다음, `{% else %}`(공고가 없습니다) 앞에 더한다:

```html
{% if d.attachments %}
<p class="muted">받아 둔 첨부 {{ d.attachments|length }}건</p>
<ul>
{% for a in d.attachments %}
  <li><a href="{{ url_for('attachment', attachment_id=a.id) }}">{{ a.filename }}</a> <span class="muted">{{ a.bid_no }} · {{ a.downloaded_at }}</span></li>
{% endfor %}
</ul>
{% endif %}
```

2. 실행부서 기록 표의 머리 `<thead><tr><th>실행부서</th><th>계약부서</th><th>근거 문장</th><th>출처</th><th>조회 시각</th></tr></thead>`를 이것으로 바꾼다:

```html
<thead><tr><th>실행부서</th><th>상태</th><th>판정</th><th>계약부서</th><th>근거 문장</th><th>출처</th><th>사유</th><th>조회 시각</th></tr></thead>
```

3. 그 표의 행 `<td>{{ p.exec_dept|dash }}</td>` 아래에 두 칸, `<td>{{ p.source_file|dash }}</td>` 아래에 한 칸을 더한다:

```html
  <td>{% if p.confirmed %}확정{% elif p.exec_dept %}후보{% else %}—{% endif %}</td>
  <td>{{ p.by_label }}</td>
```

```html
  <td>{{ p.note|dash }}</td>
```

- [ ] **Step 6: 통과를 확인한다**

Run: `PYTHONIOENCODING=utf-8 uv run pytest -q`
Expected: PASS 전부. 2단계의 부서 편집 테스트가 `d.depts` 행을 `sqlite3.Row`로 가정해 깨지면, dict에서도 같은 키로 읽히므로 테스트가 아니라 `_candidates`(app.py)가 `row["id"]` 꼴로 읽는지 확인한다

- [ ] **Step 7: 전체 검사와 커밋**

```bash
uv run ruff check --fix . && uv run ruff format . && PYTHONIOENCODING=utf-8 uv run pytest -q && uv run ruff check . && uv run ruff format --check .
git add nara/web tests
git commit -m "feat: 화면 — 실행부서 검토 필요 표시·필터, 판정 주체, 첨부 내려받기

후보만 있는 사업은 목록에 '검토 필요'로 보이고 필터로 모아 본다. 상세에는
확정·후보, 판정 주체, 사유, 원본 파일이 보인다. 첨부는 로그인한 사람만 받고
첨부 폴더 밖 경로는 404다.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: 실데이터 검증, 문서, 검수

**Files:**
- Modify: `README.md`
- Create (scratchpad, 커밋하지 않음): 검증 스크립트

- [ ] **Step 1: README**

`README.md`의 `### 로그인과 서버` 절 위에 더한다:

```markdown
### 실행부서 찾기

`uv run nara enrich dept`가 공고 첨부(공고문·과업지시서)를 받아 읽고 실행부서를 찾는다.
후보가 하나로 좁혀지면 확정하고, 애매하면 Claude가 고른 근거 문장을 원문과 대조해 맞을
때만 확정한다. 나머지는 목록에서 "실행부서 검토 필요"로 모아 사람이 고른다. 받은 첨부는
DB 옆 `attachments` 폴더에 둔다. 예약 슬롯이 관심기관은 09·15시, 비관심기관은 평일 12시에 돌린다.
```

- [ ] **Step 2: 정답지 비교 (DB 사본)**

원본은 건드리지 않는다. 원래 폴더의 `data/nara.db`를 SQLite 백업 API로 scratchpad에 복사한다. 사본에서, 시트에서 옮긴 실행부서(`decided_by='imported'`)가 있고 공고가 있는 사업의 부서 값을 정답지로 따로 저장한 뒤 그 사업들의 `dept_check` 줄을 지운다. 그다음 사본에 대고 돌린다:

```bash
PYTHONIOENCODING=utf-8 uv run nara enrich dept --tier all --limit 400 --budget 3600 --db <사본 경로>
```

비교 규칙: 정답지 값과 자동 확정값(`confirmed=1`, `decided_by IN ('rule','llm')`)을 공백을 빼고, 정답지 쪽은 `DEPT` 정규식의 첫 무리(과 단위)로 줄여 비교한다. 보고할 것: 대상 수, 자동 확정 수(규칙·Claude), 일치·불일치 수, 검토 필요 수, 못 찾음 사유별 수, 다운로드 실패 수, 불일치 사례 전부(사업명·정답·자동값·근거 문장).

**목표: 자동 확정 불일치 0건.** 불일치가 있으면 원인을 본다. 규칙이 틀렸으면 `tests/test_dept_rules.py`에 그 사례를 먼저 실패하는 테스트로 넣고 규칙을 고친 뒤(RED→GREEN) 다시 비교한다. 규칙으로 가를 수 없는 유형이면 그 유형은 확정하지 않고 후보로 돌리도록 고치고 같은 방식으로 테스트한다. 정답지(시트 값) 쪽이 틀린 것으로 보이면 고치지 않고 사례로 보고한다. Claude 키가 비어 있으면 Claude 경로는 실데이터로 검증하지 못한 것으로 보고한다.

- [ ] **Step 3: 화면 확인과 디자인 검수**

사본 DB와 임시 `.env`(`NARA_SECRET_KEY`만)로 `nara serve`를 띄우고 로그인해 확인한다: 목록 "실행부서 검토 필요" 필터, 검토 필요 표시, 상세 실행부서 표(상태·판정·사유·출처), 첨부 목록과 내려받기. 목록·상세 HTML을 파일로 떠서 hallmark 검수(웹 열, 색·폰트는 기록만)를 돌린다. `critical`·`major` 0이 될 때까지 템플릿을 고치고 Task 8 테스트를 다시 돌린다.

- [ ] **Step 4: 전체 검사와 커밋**

```bash
uv run ruff check --fix . && uv run ruff format . && PYTHONIOENCODING=utf-8 uv run pytest -q && uv run ruff check . && uv run ruff format --check .
git add README.md nara tests
git commit -m "docs: 실행부서 찾기 사용법과 실데이터 검증 반영

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## 스펙 대응

| 스펙 요구 | 작업 |
|---|---|
| 다운로드 주소로 직접 받기, API 원본·순번 요청, 파일 고르기·형식 순서, 최대 두 문서 | Task 3 |
| 파일 앞부분으로 형식 판별, HWPX·PDF(pypdf)·HWP(olefile) 추출, 서로게이트 처리 | Task 2 |
| 규칙(신호어·무게·뺄 목록·조사·띄운 이름·과 단위·계약부서), 규칙 확정 조건 | Task 4 |
| Claude 발췌·세 줄 답·원문 대조 세 조건 | Task 4, Task 5 |
| `dept_check.confirmed`·`note`, `attachment.seq`, 확정값만 읽기 | Task 1 |
| 결과별 기록, 조회 대상, 다시 볼 조건, 다운로드 실패 3회 → 수동 확인 | Task 6 |
| 첨부 폴더(DB 옆 `attachments`), 받은 파일 재사용, 첨부는 백업하지 않음 | Task 1, Task 6(백업 코드 변경 없음) |
| `nara enrich dept`, 실행 요약, 슬롯 단계, 목록 머리 단계 | Task 7 |
| 목록 검토 필요·필터, 상세 판정 주체·후보·사유, 첨부 목록·내려받기(로그인, 폴더 밖 404) | Task 8 |
| 오류 처리(30초·30MB·서명 확인·0.5초 쉼·이름 다듬기·추출 실패·Claude 실패·시간 예산) | Task 3, Task 6 |
| 실데이터 정답지 검증(자동 확정 불일치 0건 목표) | Task 9 |
| 모델 이름 | 설계 문서 정정(Task 1) — `claude-opus-5` 유지 |

**스펙에서 바꾼 것(설계 문서도 Task 1에서 고친다):**
- 모델을 `claude-sonnet-5`로 바꾸지 않는다. `claude-opus-5`는 지금도 쓸 수 있는 이름이었다
- 다시 볼 조건을 수집 시각이 아니라 공고번호로 비교한다. 수집이 최근 공고를 날마다 다시 받아 수집 시각이 바뀌기 때문이다
- 다운로드 실패 횟수는 `attachment.attempts`가 아니라 `dept_check`의 "다운로드 실패" 줄로 센다. 파일 이름을 알기 전(순번 요청 중)의 실패도 같은 방식으로 셀 수 있다
