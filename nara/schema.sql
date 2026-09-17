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
  updated_at  TEXT NOT NULL
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
  decided_by    TEXT NOT NULL,
  checked_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS attachment (
  id            INTEGER PRIMARY KEY,
  bid_no        TEXT NOT NULL REFERENCES notice(bid_no),
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
  effective_from TEXT
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

INSERT OR IGNORE INTO energy_unit_price (source_type, price_per_kw, effective_from) VALUES
  ('BIPV',   5000000,  '2026-09-16'),
  ('PV',     2500000,  '2026-09-16'),
  ('지열',   2500000,  '2026-09-16'),
  ('PEMFC',  32000000, '2026-09-16'),
  ('SOFC',   98250000, '2026-09-16');
