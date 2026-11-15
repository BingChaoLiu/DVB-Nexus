-- Ticket #80 (SPEC-308 §7 / SPEC-500 §4.8) — TSDuck call records, migration 0004.
--
-- SPEC-308 §7: "每次调用记录（SPEC-001 §7 义务）：版本 / 可执行路径 / argv /
-- 起止时间 / 退出码 / stdout / stderr / 输入 Artifact SHA-256，关联 run_id
-- （有则填）." The SPEC-502 §4 frozen tables are unchanged — this migration
-- only ADDS a table (exactly what the numbered-migration mechanism exists
-- for, 002/003 precedent).
--
-- Projection of the nine-field record + the optional run_id association,
-- plus the REST scoping key session_id (SPEC-500 §4.8 is session-scoped)
-- and a record_id PK. Failure-path fields carry explicit NULL (SPEC-308 §7
-- no-fabrication rule). R8 (ticket #23 register): *_utc_ms = epoch-ms
-- INTEGER operational timestamps. argv is JSON TEXT (the diagnoses
-- list-columns precedent). stdout/stderr are display-only decodes — GBK
-- stderr is never parsed (SPEC-308 §7).
CREATE TABLE tsduck_calls (
    record_id              TEXT    NOT NULL PRIMARY KEY,
    session_id             TEXT    NOT NULL,
    run_id                 TEXT,
    version                TEXT,
    executable_path        TEXT,
    argv_json              TEXT    NOT NULL,
    started_at_utc_ms      INTEGER NOT NULL,
    finished_at_utc_ms     INTEGER NOT NULL,
    exit_code              INTEGER,
    stdout_text            TEXT,
    stderr_text            TEXT,
    input_artifact_sha256  TEXT
);

CREATE INDEX idx_tsduck_calls_session_started
    ON tsduck_calls (session_id, started_at_utc_ms);

CREATE INDEX idx_tsduck_calls_session_run
    ON tsduck_calls (session_id, run_id);
