# 실행부서 담당자 연락처 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 실행부서 고치기 폼 하나로 부서명·부서장·실무 담당자 연락처를 저장하고, 공고문에서 실행부서를 찾을 때 실무 담당자 연락처도 읽어 빈 칸을 채운다.

**Architecture:** `dept_contact` 표에 실무 담당자 3칸과 `auto_fields`를 더한다. `dept_rules.find_staff`가 공고문에서 부서 뒤의 번호·이름·직위를 읽고, `llm.ask_dept`가 같은 질문에서 두 줄을 더 받으며, `dept.fill_contact`가 확정 경로 끝에서 빈 칸만 채운다. 웹은 `dept` 섹션 폼에 6칸을 합치고 `/contact` 경로를 없앤다. `nara enrich contacts`가 받아 둔 첨부로 기존 사업을 한 번 채운다.

**Tech Stack:** Python 3.14, SQLite, Flask/Jinja, Typer, pytest, ruff(줄 100). 실행은 `uv run --no-sync`.

**Spec:** `docs/superpowers/specs/2026-10-10-dept-contacts-design.md`

## Global Constraints

- 자동 채움은 **빈 칸만** 채우고 `auto_fields`에 칸 이름을 쉼표로 잇는다. 사람이 저장하면 `auto_fields = NULL`.
- 번호 규칙: `0`으로 시작하는 2~3자리-3~4자리-4자리를 `0xx-xxx-xxxx`로 정리. `1588·1577·1544·080` 시작은 뺀다. 직위 목록: 주무관·사무관·서기관·주사보·주사·주임·계장·팀장.
- 부서 뒤 120자 창. 다른 부서 이름이 먼저 나오면 거기서 끊는다.
- 폼 칸 이름: `head_name head_position head_tel staff_name staff_position staff_tel`. 이름·직위 50자, 번호는 `[0-9-]+`에 숫자 9~11자리. 오류 문구는 기존 그대로.
- 출력 양식 전화번호 칸: 부서장 직통 → 실무 담당자 직통 → 공고 기재 번호.
- 기존 테스트는 모두 통과한다. `/project/<id>/contact`는 404.

## Review Focus

- "건축과(051-605-6231)"처럼 괄호가 바로 붙은 번호도 읽는다 → Task 1 테스트.
- 번호가 "051 - 605 - 6231"로 띄어 적혀도 읽는다 → Task 1 테스트.
- 부서명 뒤에 "팀" 이름이 끼어도("문화관광과 관광팀 (063-000-0001)") 번호를 읽는다 → Task 1 테스트.
- 폼에서 실행부서 검사가 실패하면 연락처 칸 값도 그대로 다시 보인다 → Task 4 테스트.
- 자동 채움이 줄을 새로 만들 때 `updated_by`는 NULL이고 화면이 "공고문"만 보여 준다 → Task 3·4 테스트.

## File Structure

| 파일 | 역할 |
|---|---|
| `nara/schema.sql`, `nara/db.py` (수정) | `dept_contact` 새 칸 |
| `nara/dept_rules.py` (수정) | `StaffContact`, `find_staff`, `verify_staff`, `DeptAnswer.staff` |
| `nara/llm.py` (수정) | 담당자·전화 두 줄 |
| `nara/dept.py` (수정) | `fill_contact`, `DeptRun.contacts_filled`, `fill_saved_contacts` |
| `nara/cli.py` (수정) | `enrich contacts` |
| `nara/web/edit.py` (수정) | `check_contact`·`save_contact` 6칸 |
| `nara/web/data.py` (수정) | `ProjectDetail.contact_auto`, 출력 전화번호 순서 |
| `nara/web/app.py` (수정) | dept 섹션에 연락처 합치기, `/contact` 제거 |
| `nara/web/templates/detail.html` (수정) | 폼·보기 |
| `tests/test_dept_rules.py`, `tests/test_llm.py`, `tests/test_dept.py`, `tests/test_web_edit.py`, `tests/test_web.py` | 테스트 |

---

### Task 1: 표 칸과 규칙 추출

**Files:**
- Modify: `nara/schema.sql` (dept_contact), `nara/db.py` (`migrate`)
- Modify: `nara/dept_rules.py`
- Test: `tests/test_dept_rules.py`

**Interfaces:**
- Produces: `StaffContact(name: str | None, position: str | None, tel: str | None)` with `.empty`; `find_staff(text: str, dept: str) -> StaffContact | None`; `normalize_tel(raw: str) -> str | None`; `STAFF_FIELDS = ("staff_name", "staff_position", "staff_tel")`.

- [ ] **Step 1: Write the failing tests**

`tests/test_dept_rules.py` import에 `StaffContact, find_staff` 추가, 끝에:

```python
def test_find_staff_reads_the_number_after_the_department_not_the_contract_one():
    text = (
        "【 세부사항 확인 및 문의처 안내 】 전자입찰 이용안내: 조달청 콜센터 ☎ 1588-0800 "
        "용역에 관한 사항: 부산진구청 건축과 ☎ 051-605-6231 "
        "입찰공고에 관한 사항: 부산진구청 재무과 ☎ 051-605-4154"
    )
    assert find_staff(text, "건축과") == StaffContact(None, None, "051-605-6231")
    assert find_staff(text, "재무과") == StaffContact(None, None, "051-605-4154")


def test_find_staff_stops_at_the_next_department():
    text = "건축과와 협의하여 작성한다. 입찰에 관한 사항은 재무과(051-709-4141)로 문의"
    assert find_staff(text, "건축과") is None


def test_find_staff_accepts_brackets_spaces_and_a_team_in_between():
    assert find_staff("문의: 건축과(051-605-6231)", "건축과").tel == "051-605-6231"
    assert find_staff("문의: 건축과 ☎ 051 - 605 - 6231", "건축과").tel == "051-605-6231"
    pair = "사업관련 문의: 문화관광과 관광팀 (063-000-0001)"
    assert find_staff(pair, "문화관광과").tel == "063-000-0001"


def test_find_staff_reads_a_name_with_a_position_or_after_a_label():
    got = find_staff("용역 문의: 건축과 김철수 주무관 (☎ 051-605-6231)", "건축과")
    assert got == StaffContact("김철수", "주무관", "051-605-6231")
    assert find_staff("사업담당: 건축과 담당자: 홍길동", "건축과") == StaffContact(
        "홍길동", None, None
    )


def test_find_staff_ignores_call_centre_numbers_and_returns_none_when_nothing():
    assert find_staff("문의: 건축과 콜센터 1588-0800", "건축과") is None
    assert find_staff("건축과에서 시행한다. 담당 주무관이 안내한다.", "건축과") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --no-sync pytest -q -o addopts="" tests/test_dept_rules.py`
Expected: FAIL — `ImportError: cannot import name 'StaffContact'`

- [ ] **Step 3: Write minimal implementation**

`nara/schema.sql`의 `dept_contact`에 `head_tel` 줄 다음:

```sql
  staff_name     TEXT,                            -- 실무 담당자
  staff_position TEXT,
  staff_tel      TEXT,                            -- 직통번호
  auto_fields    TEXT,                            -- 공고문에서 자동으로 채운 칸. 쉼표로 잇는다
```

`nara/db.py` `migrate`의 `_add_column` 줄들 끝에:

```python
    _add_column(conn, "dept_contact", "staff_name", "TEXT")
    _add_column(conn, "dept_contact", "staff_position", "TEXT")
    _add_column(conn, "dept_contact", "staff_tel", "TEXT")
    _add_column(conn, "dept_contact", "auto_fields", "TEXT")
```

`nara/dept_rules.py` — `DeptAnswer` 앞에 `StaffContact`, 끝에 함수들:

```python
STAFF_FIELDS = ("staff_name", "staff_position", "staff_tel")
STAFF_WINDOW = 120
POSITION = r"주무관|사무관|서기관|주사보|주사|주임|계장|팀장"
_TEL = re.compile(r"(?<!\d)(0\d{1,2})\s*[-.)]?\s*(\d{3,4})\s*[-.]\s*(\d{4})(?!\d)")
_CALL_CENTRE = re.compile(r"^(1588|1577|1544|080)")
_NAME_POS = re.compile(rf"(?<![가-힣])([가-힣]{{2,4}})\s*({POSITION})(?![가-힣])")
_LABEL_NAME = re.compile(r"담당(?:자)?\s*[:：]\s*([가-힣]{2,4})(?![가-힣])")
# '담당 주무관'·'건축과 주무관'의 앞 낱말은 이름이 아니다
_NOT_NAME = re.compile(r"(담당|부서|소속|문의|과|팀|계|실|국)$")


@dataclass(frozen=True)
class StaffContact:
    name: str | None
    position: str | None
    tel: str | None

    @property
    def empty(self) -> bool:
        return not (self.name or self.position or self.tel)


def normalize_tel(raw: str) -> str | None:
    """'☎ 051 - 605 - 6231' → '051-605-6231'. 콜센터 번호는 None."""
    m = _TEL.search(raw or "")
    if m is None or _CALL_CENTRE.match(m.group(1)):
        return None
    return "-".join(m.groups())


def _staff_window(txt: str, start: int, dept: str) -> str:
    """부서 이름 뒤 120자. 다른 부서 이름이 나오면 거기서 끊는다."""
    window = txt[start : start + STAFF_WINDOW]
    for m in DEPT.finditer(window):
        if m.group(1) != dept and is_division(m.group(1)):
            return window[: m.start()]
    return window


def find_staff(text: str, dept: str) -> StaffContact | None:
    """실행부서 뒤에 적힌 직통번호·담당자. 번호가 있는 자리를 먼저, 없으면 이름이 있는 자리."""
    txt = _clean(text).replace("\n", " ")
    # 뒤에 조사가 붙어도('건축과에서') 찾는다. 앞은 낱말 경계여야 '도시건축과'를 피한다.
    pattern = r"(?<![가-힣])" + r"\s*".join(map(re.escape, dept))
    found: list[StaffContact] = []
    for m in re.finditer(pattern, txt):
        window = _staff_window(txt, m.end(), dept)
        tel = normalize_tel(window)
        name = position = None
        if (np := _NAME_POS.search(window)) and not _NOT_NAME.search(np.group(1)):
            name, position = np.group(1), np.group(2)
        elif ln := _LABEL_NAME.search(window):
            name = ln.group(1)
        staff = StaffContact(name, position, tel)
        if not staff.empty:
            found.append(staff)
    return next((s for s in found if s.tel), found[0] if found else None)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --no-sync pytest -q -o addopts="" tests/test_dept_rules.py tests/test_db.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add nara/schema.sql nara/db.py nara/dept_rules.py tests/test_dept_rules.py
git commit -m "feat: 공고문에서 실행부서 뒤의 담당자 번호·이름을 읽는다"
```

---

### Task 2: Claude 답에 담당자·전화

**Files:**
- Modify: `nara/dept_rules.py` (`DeptAnswer.staff`, `verify_staff`), `nara/llm.py`
- Test: `tests/test_llm.py`, `tests/test_dept_rules.py`

**Interfaces:**
- Consumes: `StaffContact`, `normalize_tel`, `POSITION` (Task 1)
- Produces: `DeptAnswer(exec_dept, contract_dept, quote, staff: StaffContact | None = None)`; `verify_staff(text: str, staff: StaffContact | None) -> StaffContact | None`.

- [ ] **Step 1: Write the failing tests**

`tests/test_llm.py` 끝에:

```python
def test_ask_dept_reads_the_staff_lines_too():
    client = _FakeClient(
        _Response(
            "실행부서: 건축과\n계약부서: 재무과\n근거: 용역 문의: 건축과 김철수 주무관\n"
            "담당자: 김철수 주무관\n전화: ☎ 051-605-6231"
        )
    )
    answer = ask_dept(KEYED, "발췌", client=client)
    assert answer.staff == StaffContact("김철수", "주무관", "051-605-6231")
    assert "담당자:" in SYSTEM_DEPT and "계약부서 전화" in SYSTEM_DEPT


def test_ask_dept_staff_none_when_both_lines_say_none():
    client = _FakeClient(_Response("실행부서: 건축과\n계약부서: 없음\n근거: x\n담당자: 없음\n전화: 없음"))
    assert ask_dept(KEYED, "발췌", client=client).staff is None
```

(`from nara.dept_rules import DeptAnswer, StaffContact`로 import 수정.)

`tests/test_dept_rules.py` 끝에:

```python
def test_verify_staff_keeps_only_what_the_notice_really_says():
    from nara.dept_rules import verify_staff

    text = "용역 문의: 건축과 김철수 주무관 (☎ 051-605-6231)"
    assert verify_staff(text, StaffContact("김철수", "주무관", "051-605-6231")) == StaffContact(
        "김철수", "주무관", "051-605-6231"
    )
    assert verify_staff(text, StaffContact("박영희", "주무관", "051-605-9999")) is None
    assert verify_staff(text, StaffContact("김철수", "과장", None)) == StaffContact(
        "김철수", None, None
    )
    assert verify_staff(text, None) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --no-sync pytest -q -o addopts="" tests/test_llm.py tests/test_dept_rules.py`
Expected: FAIL — `DeptAnswer` has no attribute `staff` / `cannot import name 'verify_staff'`

- [ ] **Step 3: Write minimal implementation**

`nara/dept_rules.py` — `DeptAnswer`에 `staff: StaffContact | None = None` 추가(`StaffContact` 정의가 앞에 와야 한다). 끝에:

```python
def verify_staff(text: str, staff: StaffContact | None) -> StaffContact | None:
    """번호는 숫자만 남겨 원문에 있을 때, 이름은 글자 그대로 있을 때만. 직위는 이름이 살았을 때만."""
    if staff is None:
        return None
    flat = squash(text)
    digits = re.sub(r"\D", "", flat)
    tel = staff.tel if staff.tel and re.sub(r"\D", "", staff.tel) in digits else None
    name = staff.name if staff.name and staff.name in flat else None
    position = staff.position if name and staff.position and staff.position in flat else None
    kept = StaffContact(name, position, tel)
    return None if kept.empty else kept
```

`nara/llm.py` — `SYSTEM_DEPT`를 다음으로 바꾼다:

```python
SYSTEM_DEPT = (
    "너는 한국 지자체 입찰 공고문에서 사업을 맡은 실행부서를 찾는다.\n"
    "다음 다섯 줄로만 답한다:\n"
    "실행부서: <부서 이름 또는 없음>\n"
    "계약부서: <부서 이름 또는 없음>\n"
    "근거: <공고문에서 글자를 바꾸지 않고 그대로 옮긴 문장>\n"
    "담당자: <실행부서 담당자 이름 직위 또는 없음>\n"
    "전화: <실행부서 전화번호 또는 없음>\n"
    "규칙:\n"
    "- 공고문에 적힌 것만 답한다. 조직도나 사업 성격으로 짐작하지 않는다.\n"
    "- 계약·입찰·개찰·회계 문의 부서(재무과·회계과 등)는 실행부서가 아니다.\n"
    "- 실행부서는 과 단위로 적는다. 팀 이름은 적지 않는다.\n"
    "- 담당자·전화도 공고문에 적힌 것만 적는다. 계약부서 전화는 적지 않는다.\n"
    "- 확신이 없으면 '실행부서: 없음'이라고 적는다."
)
```

`ask_dept` 끝을:

```python
    exec_dept, contract = _field(text, "실행부서"), _field(text, "계약부서")
    return DeptAnswer(
        exec_dept=None if exec_dept in _NONE else exec_dept,
        contract_dept=None if contract in _NONE else contract,
        quote=_field(text, "근거"),
        staff=_staff(_field(text, "담당자"), _field(text, "전화")),
    )


def _staff(who: str, tel: str) -> StaffContact | None:
    """'김철수 주무관' → 이름·직위. 직위 낱말이 없으면 전부 이름."""
    name = position = None
    if who not in _NONE:
        m = re.fullmatch(rf"\s*([가-힣]{{2,4}})\s*({POSITION})?\s*", who)
        if m:
            name, position = m.group(1), m.group(2)
    staff = StaffContact(name, position, None if tel in _NONE else normalize_tel(tel))
    return None if staff.empty else staff
```

(`import re`와 `from nara.dept_rules import POSITION, DeptAnswer, StaffContact, normalize_tel`.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --no-sync pytest -q -o addopts="" tests/test_llm.py tests/test_dept_rules.py`
Expected: PASS (기존 `test_ask_dept_reads_the_three_lines`는 `staff=None`이라 그대로 통과)

- [ ] **Step 5: Commit**

```bash
git add nara/dept_rules.py nara/llm.py tests/test_llm.py tests/test_dept_rules.py
git commit -m "feat: Claude에게 실행부서 담당자·전화도 함께 묻고 원문과 대조한다"
```

---

### Task 3: 확정 경로에서 연락처 채우기

**Files:**
- Modify: `nara/dept.py`
- Test: `tests/test_dept.py`

**Interfaces:**
- Consumes: `find_staff`, `verify_staff`, `StaffContact`, `STAFF_FIELDS` (Task 1·2)
- Produces: `fill_contact(conn, project_id: int, dept: str, staff: StaffContact | None, now: str) -> list[str]` (채운 칸 이름); `DeptRun.contacts_filled: int`; `merge_staff(rule, llm) -> StaffContact | None`.

- [ ] **Step 1: Write the failing tests**

`tests/test_dept.py` 끝에 (`ONE`은 "문화관광과 관광팀 (063-000-0001)"을 담고 있다):

```python
def _contact(conn, org_id, dept):
    row = conn.execute(
        "SELECT staff_name, staff_position, staff_tel, auto_fields, updated_by "
        "FROM dept_contact WHERE org_id = ? AND dept = ?",
        (org_id, dept),
    ).fetchone()
    return tuple(row) if row else None


def test_a_rule_confirmed_department_fills_the_staff_number_from_the_notice(db, tmp_path):
    _project(db, 1, bid_no="B1")
    run, _ = _run(db, tmp_path / "a", _server({"B1": ONE}))
    assert _contact(db, 1, "문화관광과") == (None, None, "063-000-0001", "staff_tel", None)
    assert run.contacts_filled == 1


def test_a_claude_confirmed_department_fills_only_verified_staff(db, tmp_path):
    _project(db, 1, bid_no="B1")
    text = TWO + "\n도시재생과 박영희 주무관 ☎ 063-000-0002"
    answer = DeptAnswer(
        "도시재생과", "재무과", "설계서 열람 문의: 도시재생과",
        staff=StaffContact("박영희", "과장", "063-000-9999"),
    )  # fmt: skip
    run, _ = _run(db, tmp_path / "a", _server({"B1": text}), KEYED, lambda s, e: answer)
    # 규칙이 먼저 읽고(이름·직위·번호 모두 원문에 있음), Claude의 틀린 직위·번호는 버린다
    assert _contact(db, 1, "도시재생과") == (
        "박영희", "주무관", "063-000-0002", "staff_name,staff_position,staff_tel", None
    )


def test_auto_fill_never_overwrites_a_value_a_person_entered(db, tmp_path):
    db.execute(
        "INSERT INTO dept_contact (org_id, dept, staff_tel, updated_at, updated_by) "
        "VALUES (1, '문화관광과', '063-000-7777', ?, 1)",
        (NOW,),
    )
    db.commit()
    _project(db, 1, bid_no="B1")
    run, _ = _run(db, tmp_path / "a", _server({"B1": ONE}))
    assert _contact(db, 1, "문화관광과") == (None, None, "063-000-7777", None, 1)
    assert run.contacts_filled == 0
```

(import에 `from nara.dept_rules import DeptAnswer, StaffContact`.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --no-sync pytest -q -o addopts="" tests/test_dept.py -k "staff or overwrite"`
Expected: FAIL — `_contact(...)` is None / `DeptRun` has no `contacts_filled`

- [ ] **Step 3: Write minimal implementation**

`nara/dept.py`:

- `DeptRun`에 `contacts_filled: int = 0`.
- import에 `from nara.dept_rules import STAFF_FIELDS, StaffContact, find_staff, verify_staff` 추가(기존 import 줄에 합친다).
- 함수 추가:

```python
def merge_staff(rule: StaffContact | None, llm: StaffContact | None) -> StaffContact | None:
    """규칙이 읽은 값이 먼저. Claude 값은 빈 칸만 채운다."""
    if rule is None:
        return llm
    if llm is None:
        return rule
    return StaffContact(rule.name or llm.name, rule.position or llm.position, rule.tel or llm.tel)


def fill_contact(
    conn: sqlite3.Connection, project_id: int, dept: str, staff: StaffContact | None, now: str
) -> list[str]:
    """기관+부서 연락처의 빈 칸만 채우고 auto_fields에 남긴다. 채운 칸 이름을 돌려준다."""
    if staff is None or staff.empty:
        return []
    org_id = conn.execute("SELECT org_id FROM project WHERE id = ?", (project_id,)).fetchone()[0]
    row = conn.execute(
        "SELECT staff_name, staff_position, staff_tel, auto_fields FROM dept_contact "
        "WHERE org_id = ? AND dept = ?",
        (org_id, dept),
    ).fetchone()
    current = dict(zip(STAFF_FIELDS, row[:3] if row else (None, None, None), strict=True))
    wanted = dict(zip(STAFF_FIELDS, (staff.name, staff.position, staff.tel), strict=True))
    filled = [f for f in STAFF_FIELDS if wanted[f] and not current[f]]
    if not filled:
        return []
    auto = [a for a in (row["auto_fields"] or "").split(",") if a] if row else []
    auto_fields = ",".join(dict.fromkeys(auto + filled))
    if row is None:
        conn.execute(
            "INSERT INTO dept_contact (org_id, dept, staff_name, staff_position, staff_tel, "
            "auto_fields, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (org_id, dept, *(wanted[f] if f in filled else None for f in STAFF_FIELDS),
             auto_fields, now),
        )  # fmt: skip
    else:
        sets = ", ".join(f"{f} = ?" for f in filled)
        conn.execute(
            f"UPDATE dept_contact SET {sets}, auto_fields = ? WHERE org_id = ? AND dept = ?",
            (*(wanted[f] for f in filled), auto_fields, org_id, dept),
        )
    return filled
```

- `_process`의 규칙 확정 블록(`chosen is not None`)에서 `_record(...)` 뒤, `run.confirmed_rule += 1` 앞에:

```python
        run.contacts_filled += bool(
            fill_contact(conn, project_id, chosen.name, find_staff(full_text, chosen.name), now)
        )
```

- Claude 확정 블록(`verify_answer(...)` 참)에서 `_record(...)` 뒤, `run.confirmed_llm += 1` 앞에:

```python
        staff = merge_staff(
            find_staff(full_text, answer.exec_dept), verify_staff(full_text, answer.staff)
        )
        run.contacts_filled += bool(fill_contact(conn, project_id, answer.exec_dept, staff, now))
```

`dept_contact`의 `row["auto_fields"]`를 쓰려면 `conn.row_factory`가 `sqlite3.Row`여야 한다. `connect`가 그렇게 연다(기존 `_rows` 테스트가 `dict(r)`를 쓴다). 

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --no-sync pytest -q -o addopts="" tests/test_dept.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add nara/dept.py tests/test_dept.py
git commit -m "feat: 실행부서를 확정할 때 담당자 연락처의 빈 칸을 공고문으로 채운다"
```

---

### Task 4: 폼 하나로 7칸, 화면 표시

**Files:**
- Modify: `nara/web/edit.py`, `nara/web/data.py`, `nara/web/app.py`, `nara/web/templates/detail.html`
- Test: `tests/test_web_edit.py`, `tests/test_web.py`

**Interfaces:**
- Consumes: `STAFF_FIELDS` (Task 1)
- Produces: `edit.CONTACT_FIELDS` = 6칸; `edit.check_contact(form) -> Checked` (6칸); `edit.save_contact(conn, org_id, dept, values, now, user_id) -> bool` (사람 저장 → `auto_fields = NULL`); `ProjectDetail.contact_auto: frozenset[str]`.

- [ ] **Step 1: Write the failing tests**

`tests/test_web_edit.py` — 기존 세 `check_contact` 테스트의 기대값을 6칸으로 바꾼다:

```python
def test_check_contact_reads_name_position_and_direct_line():
    checked = check_contact(
        {"head_name": " 홍길동 ", "head_position": "과장", "head_tel": "051-000-0000",
         "staff_name": "김철수", "staff_position": "주무관", "staff_tel": "051-000-0001"}
    )  # fmt: skip
    assert checked.ok
    assert checked.values == {
        "head_name": "홍길동", "head_position": "과장", "head_tel": "051-000-0000",
        "staff_name": "김철수", "staff_position": "주무관", "staff_tel": "051-000-0001",
    }  # fmt: skip


def test_check_contact_allows_clearing_everything():
    """여섯 칸 다 비우면 그 부서의 연락처를 지운다."""
    checked = check_contact({})
    assert checked.ok
    assert checked.values == dict.fromkeys(CONTACT_FIELDS)


def test_check_contact_rejects_a_number_that_cannot_be_dialled_and_long_text():
    tel = "숫자와 -로 9~11자리를 적으세요 (예: 051-000-0000)"
    assert check_contact({"head_tel": "내선 1234"}).errors == {"head_tel": tel}
    assert check_contact({"staff_tel": "1234-5678"}).errors == {"staff_tel": tel}
    assert check_contact({"head_tel": "051-000-00000-1"}).errors == {"head_tel": tel}
    assert check_contact({"staff_name": "가" * 51}).errors == {
        "staff_name": "50자까지 적을 수 있습니다"
    }
```

(`CONTACT_FIELDS`를 import에 추가.) `test_save_contact_is_one_row_per_org_and_department`의 `values`·`empty`를 6칸으로 바꾸고 끝에 추가:

```python
def test_a_person_saving_clears_the_notice_marks(db):
    path, pid = db
    with closing(open_readwrite(path)) as conn:
        org = conn.execute("SELECT org_id FROM project WHERE id = ?", (pid,)).fetchone()[0]
        conn.execute(
            "INSERT INTO dept_contact (org_id, dept, staff_tel, auto_fields, updated_at) "
            "VALUES (?, '체육진흥과', '051-000-0001', 'staff_tel', ?)",
            (org, NOW),
        )
        conn.commit()
        values = {**dict.fromkeys(CONTACT_FIELDS), "staff_tel": "051-000-0001", "head_name": "홍"}
        assert save_contact(conn, org, "체육진흥과", values, NOW, 7) is True
        row = conn.execute("SELECT auto_fields, updated_by FROM dept_contact").fetchone()
        assert tuple(row) == (None, 7)
```

`tests/test_web.py` — 기존 `/contact` 테스트 5개(`test_a_department_head_entered_once_shows_on_every_project_of_that_department`, `test_the_print_sheet_fills_head_position_and_direct_line`, `test_a_project_without_a_department_asks_for_one_first`, `test_a_bad_direct_line_is_shown_again_with_the_reason`, `test_contact_save_refuses_another_site`)를 지우고 아래로 바꾼다:

```python
CONTACT = {
    "head_name": "홍길동", "head_position": "과장", "head_tel": "063-000-0000",
    "staff_name": "김철수", "staff_position": "주무관", "staff_tel": "063-000-0001",
}  # fmt: skip


def _dept_form(client, pid, **extra):
    page = _text(client.get(f"/project/{pid}?edit=dept"))
    version = re.search(r'name="version" value="([^"]*)"', page).group(1)
    return {"exec_dept": "체육진흥과", "snippet": "", "version": version, **extra}


def test_the_department_form_saves_the_name_and_both_contacts_at_once(world):
    path, ids = world
    _two_projects_in_one_department(path, ids)
    client = _client(path)
    page = _text(client.get(f"/project/{ids['gym']}?edit=dept"))
    for field in CONTACT:
        assert f'name="{field}"' in page
    resp = _post(client, f"/project/{ids['gym']}/edit/dept", _dept_form(client, ids["gym"], **CONTACT))
    assert resp.status_code == 302
    assert "연락처" in _text(client.get(resp.headers["Location"]))
    other = _text(client.get(f"/project/{ids['welfare']}"))
    assert "홍길동" in other and "김철수" in other and "063-000-0001" in other
    assert client.post(f"/project/{ids['gym']}/contact", data=CONTACT, headers=ORIGIN).status_code == 404


def test_the_form_opens_with_the_current_contacts_and_marks_notice_values(world):
    path, ids = world
    _two_projects_in_one_department(path, ids)
    conn = connect(path)
    org = conn.execute("SELECT org_id FROM project WHERE id = ?", (ids["gym"],)).fetchone()[0]
    conn.execute(
        "INSERT INTO dept_contact (org_id, dept, staff_tel, auto_fields, updated_at) "
        "VALUES (?, '체육진흥과', '063-000-0001', 'staff_tel', ?)",
        (org, NOW),
    )
    conn.commit()
    conn.close()
    client = _client(path)
    shown = _text(client.get(f"/project/{ids['gym']}"))
    assert "063-000-0001" in shown and "공고문" in shown
    form = _text(client.get(f"/project/{ids['gym']}?edit=dept"))
    assert 'name="staff_tel" value="063-000-0001"' in form
    _post(client, f"/project/{ids['gym']}/edit/dept", _dept_form(client, ids["gym"], **CONTACT))
    assert "공고문" not in _text(client.get(f"/project/{ids['gym']}"))


def test_renaming_the_department_moves_the_contacts_to_the_new_name(world):
    path, ids = world
    _two_projects_in_one_department(path, ids)
    client = _client(path)
    form = _dept_form(client, ids["gym"], **CONTACT)
    _post(client, f"/project/{ids['gym']}/edit/dept", {**form, "exec_dept": "문화체육과"})
    conn = connect(path)
    rows = conn.execute("SELECT dept, head_name FROM dept_contact ORDER BY dept").fetchall()
    conn.close()
    assert [tuple(r) for r in rows] == [("문화체육과", "홍길동")]
    assert "홍길동" not in _text(client.get(f"/project/{ids['welfare']}"))  # 아직 체육진흥과


def test_the_print_sheet_fills_head_position_and_direct_line(world):
    path, ids = world
    _two_projects_in_one_department(path, ids)
    client = _client(path)
    _post(client, f"/project/{ids['gym']}/edit/dept", _dept_form(client, ids["gym"], **CONTACT))
    sheet = _text(client.get("/print"))
    assert "<td>홍길동</td>" in sheet and "<td>과장</td>" in sheet
    assert "<td>063-000-0000</td>" in sheet


def test_a_bad_direct_line_keeps_the_other_fields_and_says_why(world):
    path, ids = world
    _two_projects_in_one_department(path, ids)
    client = _client(path)
    form = _dept_form(client, ids["gym"], **{**CONTACT, "staff_tel": "내선 12"})
    resp = _post(client, f"/project/{ids['gym']}/edit/dept", form)
    assert resp.status_code == 422
    text = _text(resp)
    assert "9~11자리" in text and 'value="내선 12"' in text and 'value="홍길동"' in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --no-sync pytest -q -o addopts="" tests/test_web_edit.py tests/test_web.py -k "contact or department_form or renaming or direct_line or print_sheet"`
Expected: FAIL — 6칸 기대값 불일치, 폼에 `staff_*` 없음

- [ ] **Step 3: Write minimal implementation**

`nara/web/edit.py`:

```python
CONTACT_FIELDS = ("head_name", "head_position", "head_tel", *STAFF_FIELDS)
_TEL_FIELDS = ("head_tel", "staff_tel")


def check_contact(form: Mapping[str, str]) -> Checked:
    """부서장·실무 담당자 이름·직위·직통번호. 여섯 칸 다 비우면 지운다."""
    values: dict[str, str | None] = {}
    errors: dict[str, str] = {}
    for key in CONTACT_FIELDS:
        text = _text(form, key)
        if key in _TEL_FIELDS:
            digits = re.sub(r"[^0-9]", "", text)
            if text and (not _TEL.fullmatch(text) or not 9 <= len(digits) <= 11):
                errors[key] = "숫자와 -로 9~11자리를 적으세요 (예: 051-000-0000)"
        elif len(text) > CONTACT_LIMIT:
            errors[key] = f"{CONTACT_LIMIT}자까지 적을 수 있습니다"
        values[key] = text or None
    return Checked(values, errors)


def save_contact(conn, org_id, dept, values, now, user_id=None) -> bool:
    """기관+부서의 연락처를 바꾼다. 사람이 저장하면 공고문 표시(auto_fields)를 지운다."""
    cols = ", ".join(CONTACT_FIELDS)
    old = conn.execute(
        f"SELECT {cols}, auto_fields FROM dept_contact WHERE org_id = ? AND dept = ?",
        (org_id, dept),
    ).fetchone()
    new = tuple(values[k] for k in CONTACT_FIELDS)
    if old is not None and tuple(old)[: len(CONTACT_FIELDS)] == new and old["auto_fields"] is None:
        return False
    if old is None and not any(new):
        return False
    with conn:
        if not any(new):
            conn.execute("DELETE FROM dept_contact WHERE org_id = ? AND dept = ?", (org_id, dept))
        else:
            sets = ", ".join(f"{k} = excluded.{k}" for k in CONTACT_FIELDS)
            marks = ", ".join("?" * (len(CONTACT_FIELDS) + 4))
            conn.execute(
                f"INSERT INTO dept_contact (org_id, dept, {cols}, auto_fields, updated_at, "
                f"updated_by) VALUES ({marks}) ON CONFLICT(org_id, dept) DO UPDATE SET {sets}, "
                "auto_fields = NULL, updated_at = excluded.updated_at, "
                "updated_by = excluded.updated_by",
                (org_id, dept, *new, None, now, user_id),
            )
    return True
```

(`from nara.dept_rules import STAFF_FIELDS` 추가. `old["auto_fields"]`를 쓰므로 `conn.row_factory`가 Row여야 한다 — 웹의 `open_readwrite`가 그렇게 연다.)

`nara/web/data.py`:
- `ProjectDetail`에 `contact_auto: frozenset[str] = frozenset()` 추가하고, `project_detail`에서 `contact=` 다음에 지역변수 `contact = dept_contact(conn, project["org_id"], current_dept(conn, project_id))`를 먼저 두고 `contact=contact`, `contact_auto=frozenset(a for a in ((contact["auto_fields"] if contact else "") or "").split(",") if a)`로 채운다 — 빈 문자열은 표시가 아니다.
- `_print_row`의 `dept_tel=` 줄을 `dept_tel=(contact and (contact["head_tel"] or contact["staff_tel"])) or (tel["head_tel"] if tel else None),`로.

`nara/web/app.py`:
- `FORM_SECTIONS = (*EDIT_SECTIONS, "contact")` 줄을 지우고 `FORM_SECTIONS` 사용처를 `EDIT_SECTIONS`로 바꾼다.
- `_check`의 dept 분기:

```python
    if section == "dept":
        dept, contact = edit.check_dept(form, _candidates(d)), edit.check_contact(form)
        return edit.Checked({**dept.values, **contact.values}, {**dept.errors, **contact.errors})
```

- `_save`의 dept 분기:

```python
    if section == "dept":
        changed = edit.save_dept(conn, project_id, values["exec_dept"], values["snippet"], now, uid)
        org_id = conn.execute("SELECT org_id FROM project WHERE id = ?", (project_id,)).fetchone()[0]
        contact = {k: values[k] for k in edit.CONTACT_FIELDS}
        if edit.save_contact(conn, org_id, values["exec_dept"], contact, now, uid):
            changed.append("연락처")
        return changed
```

(`save_dept`가 `list[str]`를 돌려주는지 확인하고, 튜플이면 `list(...)`로 감싼다.)
- `/project/<int:project_id>/contact` 경로 함수 전체를 지운다.

`nara/web/templates/detail.html` — dept 폼의 `근거 문장` label 다음, `{{ buttons() }}` 앞에:

```html
  {% set c = d.contact %}
  <fieldset><legend>부서장</legend>
    <label>이름 <input type="text" name="head_name" value="{{ val('head_name', c.head_name if c else none) }}">{{ err('head_name') }}</label>
    <label>직위 <input type="text" name="head_position" value="{{ val('head_position', c.head_position if c else none) }}">{{ err('head_position') }}</label>
    <label>직통번호 <input type="text" name="head_tel" inputmode="tel" value="{{ val('head_tel', c.head_tel if c else none) }}">{{ err('head_tel') }}</label>
  </fieldset>
  <fieldset><legend>실무 담당자 {% if d.contact_auto %}<span class="muted">(공고문) 표시는 공고문에서 읽은 값입니다. 저장하면 확인한 값이 됩니다</span>{% endif %}</legend>
    <label>이름{% if 'staff_name' in d.contact_auto %} <span class="muted">(공고문)</span>{% endif %} <input type="text" name="staff_name" value="{{ val('staff_name', c.staff_name if c else none) }}">{{ err('staff_name') }}</label>
    <label>직위{% if 'staff_position' in d.contact_auto %} <span class="muted">(공고문)</span>{% endif %} <input type="text" name="staff_position" value="{{ val('staff_position', c.staff_position if c else none) }}">{{ err('staff_position') }}</label>
    <label>직통번호{% if 'staff_tel' in d.contact_auto %} <span class="muted">(공고문)</span>{% endif %} <input type="text" name="staff_tel" inputmode="tel" value="{{ val('staff_tel', c.staff_tel if c else none) }}">{{ err('staff_tel') }}</label>
  </fieldset>
  <p class="muted">연락처는 {{ d.project.org_name }}의 그 부서 공통입니다. 같은 부서가 실행부서인 사업에 모두 보입니다.</p>
```

기존 `{% if d.exec_dept %}` … `{% endif %}` 블록(부서장 줄·contact 폼·"실행부서를 먼저 확정하세요")을 다음으로 바꾼다:

```html
{% if d.exec_dept %}
{% set c = d.contact %}
<p>부서장 <strong>{{ (c.head_name if c else none)|dash }}</strong> · {{ (c.head_position if c else none)|dash }} · {{ (c.head_tel if c else none)|dash }}<br>
실무 담당자 <strong>{{ (c.staff_name if c else none)|dash }}</strong>{% if 'staff_name' in d.contact_auto %} <span class="muted">(공고문)</span>{% endif %} · {{ (c.staff_position if c else none)|dash }}{% if 'staff_position' in d.contact_auto %} <span class="muted">(공고문)</span>{% endif %} · {{ (c.staff_tel if c else none)|dash }}{% if 'staff_tel' in d.contact_auto %} <span class="muted">(공고문)</span>{% endif %}<br>
<span class="muted">— {{ d.project.org_name }} {{ d.exec_dept }} 공통{% if c %} · {{ c.updated_at[:10] }} {{ c.updated_by_name or '' }}{% endif %}</span></p>
{% else %}
<p class="muted">실행부서를 확정하면 연락처를 적을 수 있습니다</p>
{% endif %}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --no-sync pytest -q -o addopts="" tests/test_web_edit.py tests/test_web.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add nara/web tests/test_web_edit.py tests/test_web.py
git commit -m "feat: 실행부서 폼 하나로 부서명·부서장·실무 담당자를 저장한다"
```

---

### Task 5: 받아 둔 공고문으로 기존 사업 채우기

**Files:**
- Modify: `nara/dept.py` (`fill_saved_contacts`), `nara/cli.py` (`enrich contacts`)
- Test: `tests/test_dept.py`

**Interfaces:**
- Consumes: `fill_contact`, `find_staff` (Task 1·3)
- Produces: `fill_saved_contacts(conn, root: Path, dry_run: bool) -> list[tuple[str, str, int, list[str], StaffContact]]` — (기관, 부서, 사업 id, 채운 칸, 찾은 값).

- [ ] **Step 1: Write the failing tests**

`tests/test_dept.py` 끝에:

```python
def _confirm_dept(conn, pid, dept, decided_by="human"):
    conn.execute(
        "INSERT INTO dept_check (project_id, exec_dept, decided_by, confirmed, checked_at) "
        "VALUES (?, ?, ?, 1, ?)",
        (pid, dept, decided_by, NOW),
    )
    conn.commit()


def test_saved_notices_fill_contacts_for_already_confirmed_departments(db, tmp_path):
    from nara.dept import fill_saved_contacts

    _project(db, 1, bid_no="B1")
    _run(db, tmp_path / "a", _server({"B1": ONE}))  # 받아 둔다 + 규칙 확정
    db.execute("DELETE FROM dept_contact")  # 자동 채움 전 상태로
    _project(db, 2, bid_no="B2")  # 사람이 확정한 사업, 첨부 없음
    _confirm_dept(db, 2, "건축과")
    db.commit()
    preview = fill_saved_contacts(db, tmp_path / "a", dry_run=True)
    assert [(p[0], p[1], p[2], p[3]) for p in preview] == [("관심군", "문화관광과", 1, ["staff_tel"])]
    assert db.execute("SELECT COUNT(*) FROM dept_contact").fetchone()[0] == 0
    done = fill_saved_contacts(db, tmp_path / "a", dry_run=False)
    assert len(done) == 1
    assert _contact(db, 1, "문화관광과") == (None, None, "063-000-0001", "staff_tel", None)
    assert fill_saved_contacts(db, tmp_path / "a", dry_run=False) == []  # 이미 찼다


def test_enrich_contacts_command_previews_then_fills(tmp_path, monkeypatch):
    db_path = tmp_path / "data" / "n.db"
    conn = connect(db_path)
    migrate(conn)
    conn.close()
    seen = []

    def fake(conn, root, dry_run):
        seen.append((root, dry_run))
        return [("관심군", "문화관광과", 1, ["staff_tel"], StaffContact(None, None, "063-000-0001"))]

    monkeypatch.setattr(cli, "fill_saved_contacts", fake)
    result = CliRunner().invoke(cli.app, ["enrich", "contacts", "--dry-run", "--db", str(db_path)])
    assert result.exit_code == 0, result.output
    assert "관심군 문화관광과 #1: staff_tel=063-000-0001" in result.output
    assert "미리보기 1건 — 실제로 채우려면 --dry-run 없이" in result.output
    result = CliRunner().invoke(cli.app, ["enrich", "contacts", "--db", str(db_path)])
    assert "연락처 1건을 채웠습니다" in result.output
    assert seen == [(tmp_path / "data" / "attachments", True), (tmp_path / "data" / "attachments", False)]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --no-sync pytest -q -o addopts="" tests/test_dept.py -k "saved_notices or enrich_contacts"`
Expected: FAIL — `cannot import name 'fill_saved_contacts'`

- [ ] **Step 3: Write minimal implementation**

`nara/dept.py` 끝에:

```python
def fill_saved_contacts(
    conn: sqlite3.Connection, root: Path, dry_run: bool
) -> list[tuple[str, str, int, list[str], StaffContact]]:
    """확정된 실행부서의 실무 담당자 칸이 다 비어 있으면 받아 둔 첨부로 채운다.

    내려받기·Claude 호출은 하지 않는다. dry_run이면 쓰지 않고 무엇을 채울지만 돌려준다.
    """
    targets = conn.execute(
        "SELECT p.id, p.org_id, o.name AS org_name, "
        "(SELECT exec_dept FROM dept_check d WHERE d.project_id = p.id AND d.confirmed = 1 "
        " AND COALESCE(d.exec_dept, '') != '' ORDER BY d.checked_at DESC, d.id DESC LIMIT 1) "
        "AS dept FROM project p JOIN org o ON o.id = p.org_id "
        "WHERE p.hidden_at IS NULL ORDER BY o.name, p.id"
    ).fetchall()
    done = []
    for t in targets:
        if not t["dept"]:
            continue
        row = conn.execute(
            "SELECT staff_name, staff_position, staff_tel FROM dept_contact "
            "WHERE org_id = ? AND dept = ?",
            (t["org_id"], t["dept"]),
        ).fetchone()
        if row and any(row):
            continue
        texts = conn.execute(
            "SELECT a.text_path FROM attachment a JOIN notice n ON n.bid_no = a.bid_no "
            "WHERE n.project_id = ? AND a.status = 'ok' "
            "ORDER BY COALESCE(n.notice_date, '') DESC, n.bid_no DESC, a.seq",
            (t["id"],),
        ).fetchall()
        staff = None
        for (text_path,) in texts:
            path = root / text_path
            if path.is_file():
                staff = find_staff(path.read_text(encoding="utf-8"), t["dept"])
            if staff:
                break
        if staff is None:
            continue
        now = datetime.now().isoformat(timespec="seconds")
        filled = fill_contact(conn, t["id"], t["dept"], staff, now)
        if dry_run:
            conn.rollback()
        else:
            conn.commit()
        if filled:
            done.append((t["org_name"], t["dept"], t["id"], filled, staff))
    return done
```

`nara/cli.py` — import에 `from nara.dept import fill_saved_contacts, update_depts`(기존 `update_depts` import 줄에 합친다). `enrich_dept` 다음에:

```python
@enrich_app.command("contacts")
def enrich_contacts(
    dry_run: bool = typer.Option(False, "--dry-run", help="무엇을 채울지만 보여 주고 쓰지 않는다"),
    db: Path = typer.Option(DEFAULT_DB),
) -> None:
    """받아 둔 공고문으로 확정된 실행부서의 실무 담당자 연락처를 한 번 채운다."""
    conn = _open_db(db)
    found = fill_saved_contacts(conn, attachments_dir(db), dry_run)
    for org, dept, pid, fields, staff in found:
        values = {"staff_name": staff.name, "staff_position": staff.position, "staff_tel": staff.tel}
        shown = ", ".join(f"{f}={values[f]}" for f in fields)
        typer.echo(f"{org} {dept} #{pid}: {shown}")
    if dry_run:
        typer.echo(f"미리보기 {len(found)}건 — 실제로 채우려면 --dry-run 없이 실행")
    else:
        typer.echo(f"연락처 {len(found)}건을 채웠습니다")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --no-sync pytest -q -o addopts="" tests/test_dept.py tests/test_cli.py`
Expected: PASS. 그다음 `ruff check`·`ruff format --check`·전체 `pytest`.

- [ ] **Step 5: Commit**

```bash
git add nara/dept.py nara/cli.py tests/test_dept.py
git commit -m "feat: 받아 둔 공고문으로 기존 사업의 담당자 연락처를 채우는 enrich contacts"
```

---

## 실제 DB 적용 (실행자 메모)

병합 뒤: DB 백업 → `uv run --no-sync nara enrich contacts --dry-run`으로 미리보기 보고 → 사용자 확인 → `--dry-run` 없이 실행. 병합·푸시·실제 DB 쓰기는 사용자 확인 뒤에 한다.
