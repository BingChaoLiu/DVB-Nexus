-- SPEC-502 section 4 — Schema v1 (frozen tables), migration 0001.
--
-- Column names, order, uniqueness and keys come from the SPEC-502 §4 table
-- text; DDL details the spec text does not pin (nullability, timestamp
-- encodings, index predicates) follow the interpretations R1..R8/R11 recorded
-- in .scratch/task-23/IMPLEMENTATION_PLAN.md section 7 and are pinned by
-- tests/integration/adapters/storage/test_schema.py literals.
--
-- Pragmas (WAL, foreign_keys) are connection-level and live in db.connect(),
-- not in this script. user_version is set by the migration runner inside the
-- same transaction, not here.

-- §4 row 1: "(topology_id, revision) 复合唯一；spec_json（SPEC-003 §2.1 配置
-- 模型，含 schema_version）；created_at_utc / updated_at_utc" — 每 revision
-- 一行，支持 topologyRevision 防旧配置覆盖. R6: *_utc = ISO-8601 TEXT.
-- R7: the composite uniqueness is the primary key (no other PK is named).
CREATE TABLE topologies (
    topology_id    TEXT    NOT NULL,
    revision       INTEGER NOT NULL,
    spec_json      TEXT    NOT NULL,
    created_at_utc TEXT    NOT NULL,
    updated_at_utc TEXT    NOT NULL,
    PRIMARY KEY (topology_id, revision)
);

-- §4 row 2: "session_id PK（uuid4）；topology_id + topology_revision；seed；
-- deterministic；clock_config_json；resource_limits_json；lifecycle_state；
-- revision（SessionView 单调序）；scenario_json（SPEC-205 实验包，nullable）；
-- 时间戳" — R5: virtual_time_ns added (§5 SessionRepository.update_state
-- stores it); R6: "时间戳" → created_at_utc / updated_at_utc.
CREATE TABLE sessions (
    session_id          TEXT    NOT NULL PRIMARY KEY,
    topology_id         TEXT    NOT NULL,
    topology_revision   INTEGER NOT NULL,
    seed                INTEGER,
    deterministic       INTEGER NOT NULL,
    clock_config_json   TEXT    NOT NULL,
    resource_limits_json TEXT   NOT NULL,
    lifecycle_state     TEXT    NOT NULL,
    revision            INTEGER NOT NULL,
    virtual_time_ns     INTEGER NOT NULL,
    scenario_json       TEXT,
    created_at_utc      TEXT    NOT NULL,
    updated_at_utc      TEXT    NOT NULL
);

-- §4 row 3: "run_id PK（uuid4）；session_id FK；RunContext 全字段（mode/
-- fidelity/started_at_utc_ms/generator_version/config_hash/seed）；status；
-- ended_at_utc_ms" — R1: "全字段" read literally = every RunContext field
-- (topology_id/topology_revision/sequence_number included, domain
-- domain/observation/run_context.py field order) so a row reconstructs its
-- RunContext. The session_id FK is the one FK §4 declares.
CREATE TABLE runs (
    run_id             TEXT    NOT NULL PRIMARY KEY,
    session_id         TEXT    NOT NULL REFERENCES sessions (session_id),
    topology_id        TEXT    NOT NULL,
    topology_revision  INTEGER NOT NULL,
    sequence_number    INTEGER NOT NULL,
    mode               TEXT    NOT NULL,
    fidelity           TEXT    NOT NULL,
    started_at_utc_ms  INTEGER NOT NULL,
    generator_version  TEXT,
    config_hash        TEXT,
    seed               INTEGER,
    status             TEXT    NOT NULL,
    ended_at_utc_ms    INTEGER
);

-- §4 row 4: "(session_id, journal_seq) 复合 PK；event_type / severity /
-- producer_id 查询列展开；envelope_json 全量单列（权威内容）；(producer_id,
-- event_id) 部分唯一索引" — R2: event_id materialized for the dedup index;
-- R3: the partial predicate is WHERE event_id IS NOT NULL (spec pins no
-- predicate; event_id is a required envelope field, SPEC-301 §3).
-- journal_seq is stamped by the journal append transaction (§6), per session
-- monotonic (ADR-0006 decision 2).
CREATE TABLE events (
    session_id   TEXT    NOT NULL,
    journal_seq  INTEGER NOT NULL,
    event_type   TEXT    NOT NULL,
    severity     TEXT    NOT NULL,
    producer_id  TEXT    NOT NULL,
    event_id     TEXT    NOT NULL,
    envelope_json TEXT   NOT NULL,
    PRIMARY KEY (session_id, journal_seq)
);

-- §4 row 4: the partial unique dedup index.
CREATE UNIQUE INDEX ux_events_producer_event
    ON events (producer_id, event_id)
    WHERE event_id IS NOT NULL;

-- §8 row 1: "event_type 上索引供过滤查询".
CREATE INDEX idx_events_event_type
    ON events (event_type);

-- §4 row 5: "artifact_id PK（uuid4）；sha256（非唯一——同内容可被多个 run
-- 引用）；kind（SPEC-003 §2.7 六类）；relative_path；byte_size；packet_size /
-- packet_count / generator_version / config_hash / fault_profile_ids_json；
-- run_id / session_id；created_at_utc_ms" — physical files are SPEC-503.
CREATE TABLE artifacts (
    artifact_id           TEXT    NOT NULL PRIMARY KEY,
    sha256                TEXT    NOT NULL,
    kind                  TEXT    NOT NULL,
    relative_path         TEXT    NOT NULL,
    byte_size             INTEGER NOT NULL,
    packet_size           INTEGER,
    packet_count          INTEGER,
    generator_version     TEXT,
    config_hash           TEXT,
    fault_profile_ids_json TEXT,
    run_id                TEXT    NOT NULL,
    session_id            TEXT    NOT NULL,
    created_at_utc_ms     INTEGER NOT NULL
);

-- §4 row 6: "diagnosis_id PK（uuid4）；session_id / run_id；rule_id +
-- rule_version；code；severity；confidence（三档枚举 low/medium/high）；
-- observation_refs_json；affected_node_ids_json；suggested_actions_json；
-- state（raised/cleared）；raised_at / cleared_at" — R8: raised_at/cleared_at
-- epoch-ms INTEGER.
CREATE TABLE diagnoses (
    diagnosis_id           TEXT    NOT NULL PRIMARY KEY,
    session_id             TEXT    NOT NULL,
    run_id                 TEXT    NOT NULL,
    rule_id                TEXT    NOT NULL,
    rule_version           TEXT    NOT NULL,
    code                   TEXT    NOT NULL,
    severity               TEXT    NOT NULL,
    confidence             TEXT    NOT NULL,
    observation_refs_json  TEXT    NOT NULL,
    affected_node_ids_json TEXT    NOT NULL,
    suggested_actions_json TEXT    NOT NULL,
    state                  TEXT    NOT NULL,
    raised_at              INTEGER NOT NULL,
    cleared_at             INTEGER
);

-- §4 row 7: "alert-record.schema.json 全字段（alert_id PK、fingerprint、
-- rule_id、state 五态、severity、scope、time、evidence_refs_json、
-- suppression_json）" — R8: 全字段 read literally → all 11 fields of
-- schemas/alert-record.schema.json (adds rule_version and summary); the
-- JSON-object fields scope/time keep their schema names, stored as JSON TEXT.
CREATE TABLE alerts (
    alert_id           TEXT    NOT NULL PRIMARY KEY,
    fingerprint        TEXT    NOT NULL,
    rule_id            TEXT    NOT NULL,
    rule_version       TEXT    NOT NULL,
    state              TEXT    NOT NULL,
    severity           TEXT    NOT NULL,
    scope              TEXT    NOT NULL,
    time               TEXT    NOT NULL,
    summary            TEXT,
    evidence_refs_json TEXT    NOT NULL,
    suppression_json   TEXT
);
