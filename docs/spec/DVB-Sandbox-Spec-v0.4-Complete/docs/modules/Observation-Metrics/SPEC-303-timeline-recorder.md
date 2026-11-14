# SPEC-303 — Timeline Recorder

## 1. Purpose

Persist a unified, auditable timeline of session events, topology changes, TS observations, fault lifecycle, scenario progress, recovery results, metrics annotations and checkpoints.

## 2. Record types

- `event`: canonical SPEC-301 event.
- `snapshot`: state snapshot with source owner and version.
- `annotation`: operator or system note.
- `checkpoint`: recorder/consumer progress marker.
- `bookmark`: named location for training or diagnosis.
- `export_manifest`: metadata for a generated export.

Timeline records MUST retain original event IDs and journal sequence where derived from events.

## 3. Ordering

Default ordering is by `journal_seq` for records originating from the event journal. For cross-source snapshots without journal sequence, ordering uses `(clock_domain, timestamp, source_id, source_seq)` and MUST remain explicit in query output.

A timeline query MUST NOT claim a single chronological order across incompatible clock domains. The caller must provide a domain or request grouped lanes.

## 4. Checkpoints

A checkpoint contains:
- `checkpoint_id`
- `session_id`
- `journal_seq`
- `clock_domain`
- `virtual_time_ns` where applicable
- `schema_version`
- `producer_state_versions`
- `created_at`
- optional integrity digest

Checkpoint creation is observational and MUST NOT pause or mutate simulation. The Simulation Engine remains responsible for authoritative simulation snapshots.

## 5. Query and pagination

Filters:
- session, scenario, event type, severity, producer, node, service, PID, fault ID, time range and text-free tags.
- Pagination uses opaque cursor tokens bound to filter hash and scope.
- Maximum page size defaults to 500 and hard maximum is 2000.
- Cursors expire; expired cursor returns `OBS_CURSOR_EXPIRED`.

## 6. Export

Supported initial formats:
- JSONL: canonical machine-readable export.
- CSV: tabular event index; nested payload represented as compact JSON string.
- ZIP bundle: JSONL plus metadata, optional metric series and redaction report.

Every export manifest MUST include:
- export ID, creation time, requested scope and filters.
- time domain(s), start/end.
- record counts by type.
- schema versions.
- redaction policy/version.
- SHA-256 digest per file.

Export MUST be reproducible for the same immutable journal range and export options, except generated metadata such as export creation time and export ID.

## 7. Retention and deletion

Timeline data follows configured retention. Legal/administrative deletion must be scoped and audited. Deletion MUST NOT leave dangling references that appear as valid records; return explicit tombstone or redaction metadata according to policy.

## 8. Acceptance tests

- Journal sequence ordering.
- Multi-clock lane query behavior.
- Cursor binding to filter/scope.
- Cursor expiry.
- JSONL/CSV/ZIP round-trip and digest validation.
- Redaction and secret scanning.
- Checkpoint does not mutate simulation.
