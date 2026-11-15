-- Ticket #47 (SPEC-300 §7) — consumer checkpoints, migration 0002.
--
-- SPEC-300 §7: "消费者必须对其最后完整处理的 journal_seq 做检查点；重启恢复
-- 从该序号继续并安全容忍重复投递." The checkpoint is durable per-platform
-- state, stored next to the journal it tails (SPEC-502 database; the SPEC-502
-- §4 frozen tables are unchanged — this migration only ADDS a table, which is
-- exactly what the numbered-migration mechanism exists for).
--
-- (consumer_id, session_id) is the natural key: consumers tail per session
-- and journal_seq is per session monotonic (ADR-0006 decision 2).
-- R6 (ticket #23 register): *_utc = ISO-8601 TEXT, set by the adapter.
CREATE TABLE consumer_checkpoints (
    consumer_id    TEXT    NOT NULL,
    session_id     TEXT    NOT NULL,
    last_seq       INTEGER NOT NULL,
    updated_at_utc TEXT    NOT NULL,
    PRIMARY KEY (consumer_id, session_id)
);
