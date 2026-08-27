-- Dossier manifest (SQLite). The single source of truth: artifacts, their events,
-- provenance, and organization. Everything Claude reads is a projection of this.
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- One row per original artifact (file/message). Originals are never mutated.
CREATE TABLE IF NOT EXISTS artifact (
  id            INTEGER PRIMARY KEY,
  sha256        TEXT NOT NULL,                 -- chain of custody + dedup key
  original_path TEXT NOT NULL,                 -- canonical location in sources/
  organized_path TEXT,                         -- symlink target (non-destructive)
  exhibit_id    TEXT,                          -- A, B, C… assigned at schedule time
  kind          TEXT,                          -- pdf|image|email|imessage|whatsapp|other
  pages         INTEGER,
  bytes         INTEGER,
  ocr_path      TEXT,                          -- sources -> ocr/<base>.txt
  title         TEXT,                          -- extracted/human; may be null
  duplicate_of  INTEGER REFERENCES artifact(id), -- set when sha256 already seen
  flags         TEXT,                          -- json: ["filename!=content","illegible@..",..]
  created_at    TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_artifact_sha   ON artifact(sha256);
CREATE INDEX IF NOT EXISTS ix_artifact_kind  ON artifact(kind);

-- Every temporally-relevant event, provenance-tagged. The chronology is built from this.
CREATE TABLE IF NOT EXISTS event (
  id            INTEGER PRIMARY KEY,
  artifact_id   INTEGER NOT NULL REFERENCES artifact(id) ON DELETE CASCADE,
  kind          TEXT,        -- sent|received|created|captured|content|signed|effective|expires|...
  value_raw     TEXT,        -- exactly as found
  value_utc     TEXT,        -- ISO8601 UTC, NULL when zone unknown (never invented)
  value_wall    TEXT,        -- stated wall-clock (offset-free) when zone unknown
  granularity   TEXT,        -- year|month|day|second
  zone_status   TEXT,        -- explicit|derived-gps|unknown
  source        TEXT,        -- email.Date|email.Received|exif.DateTimeOriginal|pdf./Info|fs.birthtime|content@<off>|export.line
  location      TEXT,        -- page/offset/line
  resolution    TEXT DEFAULT 'parsed', -- parsed|reinspect|corroborated|human-attested|model-inferred
  provenance    TEXT,        -- document-backed|human-attested|model-inferred|asserted
  confidence    REAL
);
CREATE INDEX IF NOT EXISTS ix_event_artifact ON event(artifact_id);
CREATE INDEX IF NOT EXISTS ix_event_utc      ON event(value_utc);

-- Full-text search over ocr text for find(); content stays on disk, FTS holds tokens only.
CREATE VIRTUAL TABLE IF NOT EXISTS doc_fts USING fts5(
  body, artifact_id UNINDEXED, tokenize = 'porter'
);

-- Per-op metering, tagged by task, for the dual-baseline savings report.
CREATE TABLE IF NOT EXISTS metric (
  id          INTEGER PRIMARY KEY,
  ts          TEXT DEFAULT (datetime('now')),
  task        TEXT,
  file        TEXT,
  rung        TEXT,        -- R1|R2|R3|R4|R4a|R5|ingest|...
  model       TEXT,
  prompt_tok  INTEGER,     -- on-device VLM only (its tokenizer; never summed with Claude)
  gen_tok     INTEGER,
  ms          INTEGER,
  peak_mem_mb INTEGER
);

-- Open provenance gaps / evidence requests (the remediation list).
CREATE TABLE IF NOT EXISTS gap (
  id          INTEGER PRIMARY KEY,
  artifact_id INTEGER REFERENCES artifact(id) ON DELETE CASCADE,
  gap_type    TEXT,        -- zone-unknown|no-received-chain|exif-stripped|illegible|order-ambiguous
  detail      TEXT,
  remediation TEXT,        -- suggested action (Claude-phrased), surfaced to user
  status      TEXT DEFAULT 'open'  -- open|resolved|wontfix
);
