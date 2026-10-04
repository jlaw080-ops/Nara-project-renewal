CREATE TABLE IF NOT EXISTS org (
  id            INTEGER PRIMARY KEY,
  name          TEXT NOT NULL UNIQUE,
  tier          TEXT NOT NULL DEFAULT 'rest',   -- 'focus' | 'rest'
  weekday_group INTEGER,                        -- 1~5, 비관심 기관만
  sheet_tab     TEXT,
  added_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS project (
  id          INTEGER PRIMARY KEY,
  org_id      INTEGER NOT NULL REFERENCES org(id),
  name        TEXT NOT NULL,
  source      TEXT NOT NULL,                    -- 'g2b' | 'manual'
  address     TEXT,
  start_date  TEXT,
  end_date    TEXT,
  floor_area  REAL,
  zeb_grade   TEXT,
  re_ratio    TEXT,
  etc_cert    TEXT,
  guide_equip TEXT,
  note        TEXT,
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL,
  hidden_at     TEXT,                           -- 사람이 목록에서 숨긴 때. NULL이면 보임
  hidden_by     INTEGER REFERENCES app_user(id),
  hidden_reason TEXT
);
CREATE INDEX IF NOT EXISTS idx_project_org ON project(org_id);

CREATE TABLE IF NOT EXISTS notice (
  bid_no       TEXT PRIMARY KEY,
  bid_ord      TEXT,
  project_id   INTEGER REFERENCES project(id),
  org_id       INTEGER REFERENCES org(id),
  org_name     TEXT NOT NULL,
  title        TEXT NOT NULL,
  kind         TEXT,
  notice_date  TEXT,
  open_date    TEXT,
  close_date   TEXT,
  url          TEXT,
  budget_krw   INTEGER,
  budget_basis TEXT,
  officer_name TEXT,
  officer_tel  TEXT,
  raw_json     TEXT,
  collected_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_notice_open ON notice(open_date);
CREATE INDEX IF NOT EXISTS idx_notice_project ON notice(project_id);
CREATE INDEX IF NOT EXISTS idx_notice_org ON notice(org_id);

CREATE TABLE IF NOT EXISTS award (
  bid_no     TEXT PRIMARY KEY REFERENCES notice(bid_no),
  winner     TEXT,
  award_date TEXT,
  raw_json   TEXT,
  checked_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS status_check (
  id            INTEGER PRIMARY KEY,
  project_id    INTEGER NOT NULL REFERENCES project(id),
  verdict       TEXT NOT NULL,
  reason        TEXT,
  decided_by    TEXT NOT NULL,                  -- 'rule' | 'llm' | 'human' | 'imported'
  evidence_json TEXT,
  checked_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_status_project ON status_check(project_id, checked_at);

CREATE TABLE IF NOT EXISTS dept_check (
  id            INTEGER PRIMARY KEY,
  bid_no        TEXT REFERENCES notice(bid_no),
  project_id    INTEGER REFERENCES project(id),
  exec_dept     TEXT,
  contract_dept TEXT,
  head_tel      TEXT,
  snippet       TEXT,
  source_file   TEXT,
  confirmed     INTEGER NOT NULL DEFAULT 1,     -- 0 = 자동 조회가 남긴 후보·못 찾음 기록
  note          TEXT,                           -- 못 찾은 사유·후보 출처
  decided_by    TEXT NOT NULL,
  checked_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS attachment (
  id            INTEGER PRIMARY KEY,
  bid_no        TEXT NOT NULL REFERENCES notice(bid_no),
  seq           INTEGER,                        -- 나라장터 파일 순번
  filename      TEXT NOT NULL,
  path          TEXT,
  sha256        TEXT,
  text_path     TEXT,
  status        TEXT NOT NULL DEFAULT 'ok',     -- 'ok' | 'failed'
  attempts      INTEGER NOT NULL DEFAULT 0,
  downloaded_at TEXT
);

CREATE TABLE IF NOT EXISTS energy_plan (
  id          INTEGER PRIMARY KEY,
  project_id  INTEGER NOT NULL REFERENCES project(id),
  source_type TEXT NOT NULL,
  capacity_kw REAL NOT NULL,
  entered_by  TEXT NOT NULL,                    -- 'human' | 'doc' | 'imported'
  updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_energy_project ON energy_plan(project_id);

CREATE TABLE IF NOT EXISTS energy_unit_price (
  source_type    TEXT PRIMARY KEY,
  price_per_kw   INTEGER NOT NULL,
  effective_from TEXT,
  updated_by     INTEGER REFERENCES app_user(id)  -- 웹에서 고친 사람. 처음 값은 NULL
);

CREATE TABLE IF NOT EXISTS run_log (
  id          INTEGER PRIMARY KEY,
  command     TEXT NOT NULL,
  args        TEXT,
  started_at  TEXT NOT NULL,
  finished_at TEXT,
  processed   INTEGER NOT NULL DEFAULT 0,
  updated     INTEGER NOT NULL DEFAULT 0,
  failed      INTEGER NOT NULL DEFAULT 0,
  status      TEXT,                             -- 'ok' | 'partial' | 'error'
  message     TEXT
);

CREATE TABLE IF NOT EXISTS app_state (
  key   TEXT PRIMARY KEY,
  value TEXT
);

CREATE TABLE IF NOT EXISTS edit_log (
  id         INTEGER PRIMARY KEY,
  project_id INTEGER NOT NULL REFERENCES project(id),
  field      TEXT NOT NULL,
  old_value  TEXT,
  new_value  TEXT,
  edited_at  TEXT NOT NULL,
  user_id    INTEGER REFERENCES app_user(id)
);
CREATE INDEX IF NOT EXISTS idx_edit_project ON edit_log(project_id, field);

-- 칸마다 지난 이관 때의 시트 값. 시트에서 실제로 바뀐 칸만 웹 입력을 덮게 한다.
CREATE TABLE IF NOT EXISTS sheet_memory (
  project_id  INTEGER NOT NULL REFERENCES project(id),
  field       TEXT NOT NULL,
  value       TEXT NOT NULL,
  imported_at TEXT NOT NULL,
  PRIMARY KEY (project_id, field)
);

CREATE TABLE IF NOT EXISTS app_user (
  id            INTEGER PRIMARY KEY,
  email         TEXT NOT NULL UNIQUE,
  name          TEXT NOT NULL,
  password_hash TEXT NOT NULL,
  must_change   INTEGER NOT NULL DEFAULT 1,
  active        INTEGER NOT NULL DEFAULT 1,
  created_at    TEXT NOT NULL,
  last_login_at TEXT
);

CREATE TABLE IF NOT EXISTS login_attempt (
  id    INTEGER PRIMARY KEY,
  email TEXT NOT NULL,
  ok    INTEGER NOT NULL,
  at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_login_email ON login_attempt(email, at);

INSERT OR IGNORE INTO energy_unit_price (source_type, price_per_kw, effective_from) VALUES
  ('BIPV',   5000000,  '2026-09-16'),
  ('PV',     2500000,  '2026-09-16'),
  ('지열',   2500000,  '2026-09-16'),
  ('PEMFC',  32000000, '2026-09-16'),
  ('SOFC',   98250000, '2026-09-16'),
  ('집광채광', 1000000,  '2026-10-02');

-- 입력 화면의 에너지원·형식 목록. 설치계획서에서 새 종류가 오면 단가 없이 더한다.
CREATE TABLE IF NOT EXISTS energy_kind (
  code   TEXT PRIMARY KEY,   -- energy_plan·energy_unit_price의 source_type
  source TEXT NOT NULL,      -- 에너지원
  form   TEXT NOT NULL,      -- 형식
  sort   INTEGER NOT NULL,
  UNIQUE (source, form)
);
INSERT OR IGNORE INTO energy_kind (code, source, form, sort) VALUES
  ('BIPV',     '태양광',   'BIPV',       10),
  ('PV',       '태양광',   'PV',         20),
  ('집광채광', '태양광',   '집광채광',   30),
  ('지열',     '지열',     '수직밀폐형', 40),
  ('PEMFC',    '연료전지', 'PEMFC',      50),
  ('SOFC',     '연료전지', 'SOFC',       60);

-- 신재생에너지센터 설치계획서. 크롬 확장 프로그램이 보낸 원문을 신청번호(key)마다 한 줄로 둔다.
CREATE TABLE IF NOT EXISTS nr_plan (
  id            INTEGER PRIMARY KEY,
  key           TEXT NOT NULL UNIQUE,              -- 신청번호, 작성중이면 기관명+건물명
  org_name      TEXT NOT NULL,
  building_name TEXT NOT NULL,
  address       TEXT,
  start_date    TEXT,
  end_date      TEXT,
  dept          TEXT,                              -- 의무기관 담당자 부서
  energy_json   TEXT NOT NULL DEFAULT '[]',        -- [{source, form, capacity_kw}]
  received_at   TEXT NOT NULL,
  updated_at    TEXT NOT NULL,
  project_id    INTEGER REFERENCES project(id),
  match_state   TEXT NOT NULL DEFAULT 'pending',   -- pending|auto|new|human|ignored
  match_score   REAL,
  skipped       TEXT                               -- 웹 수정 때문에 반영하지 않은 칸, 쉼표로
);
CREATE INDEX IF NOT EXISTS idx_nr_plan_project ON nr_plan(project_id);
