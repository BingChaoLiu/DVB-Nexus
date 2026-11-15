-- Ticket #56 (SPEC-206 §4/§5) — verification verdicts, migration 0003.
--
-- SPEC-206 §4/§5 items 3: "verdict 与全部 per-criterion 结果持久化并关联
-- run/scenario 版本，支持事后审计与重放". The SPEC-502 §4 frozen tables are
-- unchanged — this migration only ADDS a table (exactly what the numbered
-- migration mechanism exists for, 002 precedent).
--
-- Projection of the §4 result structure: verdict + per-criterion results
-- (JSON TEXT, R8 convention like the diagnoses list fields) + evidence
-- refs (journal_seq / artifact / mutation-log / prepared-plan-absence
-- locators) + the run/scenario version identity. R8 (ticket #23 register):
-- *_utc_ms = epoch-ms INTEGER — verified_at is the operational timestamp
-- (the one SPEC-206 §4-permitted non-deterministic field; the criteria and
-- evidence projections stay replay-deterministic).
CREATE TABLE verification_verdicts (
    verdict_id             TEXT    NOT NULL PRIMARY KEY,
    session_id             TEXT    NOT NULL,
    run_id                 TEXT    NOT NULL,
    baseline_run_id        TEXT    NOT NULL,
    scenario_id            TEXT    NOT NULL,
    scenario_version       TEXT    NOT NULL,
    scenario_content_hash  TEXT    NOT NULL,
    verdict                TEXT    NOT NULL CHECK (verdict IN ('PASS', 'FAIL', 'INCONCLUSIVE')),
    criteria_json          TEXT    NOT NULL,
    evidence_refs_json     TEXT    NOT NULL,
    summary                TEXT    NOT NULL,
    verified_at_utc_ms     INTEGER NOT NULL
);

CREATE INDEX idx_verification_verdicts_session
    ON verification_verdicts (session_id, verified_at_utc_ms);

CREATE INDEX idx_verification_verdicts_run
    ON verification_verdicts (run_id);
