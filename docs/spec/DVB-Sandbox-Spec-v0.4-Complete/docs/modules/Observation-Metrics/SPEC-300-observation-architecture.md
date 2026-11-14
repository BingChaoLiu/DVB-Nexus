# SPEC-300 — Observation & Metrics Architecture

## 1. Goal

Provide one coherent observation plane for the DVB Sandbox. It ingests normalized events and state snapshots, derives metrics and health signals, persists a searchable timeline, and exposes read-only query interfaces to the UI, diagnosis modules, and training reports.

## 2. Scope

### In scope
- Event ingestion, validation, normalization and deduplication.
- Correlation across session, topology node, TS service/PID and fault identifiers.
- Metric derivation and time-window aggregation.
- Timeline persistence, checkpoints, export and deterministic-time support.
- Health rules and alert lifecycle.
- Read-only query service for timeline, metrics, alerts and health summaries.
- Provenance, data-quality indicators and retention controls.

### Explicitly out of scope
- Creating or mutating simulation sessions.
- Advancing virtual time or scheduling tasks.
- Mutating topology or L0/L1 state.
- Injecting or removing faults.
- Parsing raw TS packets as a primary parser. TS Core owns parsing and emits normalized observations.
- Making root-cause decisions. Diagnosis Engine consumes observation data.
- Frontend rendering and user interaction.
- Live device acquisition. Live adapters publish through the same event contract.

## 3. Architectural position

```text
 TS Core ─────────────┐
 Simulation Engine ───┼──> Event Gateway ──> Event Journal ──┬──> Metrics Engine
 Live Adapter (later) ┘                                      ├──> Timeline Recorder
                                                             ├──> Health/Alert Engine
                                                             └──> Read Query API
                                                                      │
                                                         UI / Diagnosis / Reports
```

The Observation module is downstream of producers. It MUST NOT call producer mutation APIs during ingestion or evaluation.

## 4. Components

### 4.1 Event Gateway
Responsibilities:
- Validate schema version and required fields.
- Enforce payload size and supported event types.
- Assign `observed_at` if the producer did not provide it.
- Preserve source timestamp and clock-domain metadata.
- Deduplicate by `(producer_id, event_id)`.
- Route accepted events to the journal and subscribers.

It MUST reject malformed events with a structured error and MUST NOT silently repair semantically invalid payloads.

### 4.2 Event Journal
Responsibilities:
- Append accepted events in ingestion order.
- Support cursor-based reads.
- Retain immutable event records for configured retention.
- Store a monotonic journal sequence independent of source timestamp.
- Record ingestion failures in a separate diagnostic stream, without recursively publishing them as ordinary domain events.

### 4.3 Metrics Engine
Consumes events and periodic state snapshots, updates metric series and aggregate windows. It MUST retain the source event IDs or derivation watermark needed to explain each aggregate.

### 4.4 Timeline Recorder
Builds a unified timeline across events, state snapshots, fault lifecycle, and checkpoints. It supports query and export, not simulation replay execution.

### 4.5 Health & Alert Engine
Evaluates configured rules over event/metric inputs and manages alert lifecycle. It does not determine root cause or automatically repair the simulated system.

### 4.6 Query API
Read-only interface for UI and downstream analysis. It supports filters, bounded time ranges, pagination, and explicit time domains.

## 5. Data ownership

| Data | Authoritative owner | Observation behavior |
|---|---|---|
| Session lifecycle | Simulation Runtime | Mirror as events |
| Virtual clock | Virtual Clock | Preserve clock domain/time |
| Topology state | L0 State Engine | Store snapshots/events |
| TS syntax/continuity facts | TS Core | Ingest normalized facts |
| Fault lifecycle | Fault Injection | Record events |
| Scenario progress | Scenario Engine | Record progress events |
| Recovery verdict | Recovery Verification | Record verdict/evidence |
| Metrics and timeline | Observation | Authoritative derived records |
| Alert lifecycle | Observation | Authoritative alert records |

## 6. Clock model

Every timestamp MUST carry:
- `value_ns`: signed 64-bit integer.
- `clock_domain`: stable identifier, e.g. `sim:<session_id>` or `wall:utc`.
- `semantics`: `source`, `observed`, or `derived`.

Rules:
1. `sim:<session_id>` values are comparable only within the same session and clock epoch.
2. Wall-clock UTC is represented separately and MUST NOT be used to order simulation events.
3. Cross-domain correlation uses explicit mapping metadata, never implicit arithmetic.
4. Event journal sequence is the canonical ingestion order.
5. If a producer restarts its clock, it MUST increment `clock_epoch`.

## 7. Data flow

1. Producer emits an event conforming to SPEC-301.
2. Gateway validates envelope and event-specific payload.
3. Gateway checks idempotency key.
4. Journal appends event and returns `journal_seq`.
5. Internal consumers receive the committed event.
6. Metrics, timeline and alert components update idempotently.
7. Query API exposes committed records only.

A consumer MUST checkpoint its last fully processed journal sequence. Restart recovery MUST resume from that sequence and safely tolerate duplicate delivery.

## 8. Reliability and backpressure

- Event ingestion MUST be bounded by configurable queue and payload limits.
- When downstream consumers lag, the journal remains the source of truth.
- A consumer may be paused and replayed from its checkpoint.
- The gateway MUST expose queue depth, rejected count, duplicate count and consumer lag.
- No event may be dropped silently.
- If the journal cannot commit, ingestion returns `OBS_STORAGE_UNAVAILABLE`; producer retry policy is defined by producer integration contract.
- Backpressure MUST be explicit to callers; do not block the simulation clock thread on slow UI/query clients.

## 9. Security and isolation

- Every record is scoped by `tenant_id` and `session_id` where applicable.
- Query filters MUST enforce scope before returning records.
- Raw payloads are size-limited and must not contain credentials, private keys or decryption keys.
- Secrets such as BISS keys MUST never be recorded in events, labels, logs or metric dimensions.
- Export must support redaction policy hooks.

## 10. Performance targets (initial, subject to benchmark)

| Workload | Target |
|---|---:|
| Event gateway sustained ingest | 20,000 events/s per process |
| Event gateway burst | 50,000 events/s for 10 s |
| p95 accepted-event append latency | <= 20 ms |
| Metric query, 1 h / <= 20 series | <= 300 ms |
| Timeline page, <= 500 records | <= 250 ms |
| Alert evaluation lag | <= 2 s wall time or 1 virtual-time tick batch |
| Memory bound | Configurable; no unbounded in-memory event history |

These are engineering targets, not guarantees. Benchmark on the target deployment profile and record hardware/software details.

## 11. Configuration

All configuration is validated at startup. Unknown keys MUST fail in strict mode.

```yaml
observation:
  journal:
    backend: sqlite
    path: ./data/observation.db
    max_event_bytes: 262144
    retention_days: 30
  ingestion:
    queue_capacity: 10000
    duplicate_cache_size: 100000
  metrics:
    enabled: true
    default_step_ms: 1000
    retention:
      raw_seconds: 86400
      1m_seconds: 2592000
      1h_seconds: 31536000
  timeline:
    checkpoint_interval_events: 5000
  alerts:
    enabled: true
    evaluation_batch_size: 1000
```

The concrete persistence backend is a replaceable implementation detail; the logical contracts MUST remain backend-neutral.

## 12. Required interfaces

The Python package MUST expose protocol-level interfaces equivalent to:
- `EventPublisher.publish(event) -> PublishReceipt`
- `EventGateway.accept(event) -> IngestResult`
- `EventJournal.append(event) -> JournalRecord`
- `EventJournal.read(cursor, limit, filters) -> Page[JournalRecord]`
- `MetricsService.query(request) -> MetricQueryResult`
- `TimelineService.query(request) -> TimelinePage`
- `AlertService.list(request) -> AlertPage`
- `ObservationQueryService.get_session_summary(session_id) -> SessionObservationSummary`

Exact Python names may differ only through an approved Change Request.

## 13. Failure model

Errors MUST use stable `error_code`, `message`, `retryable`, and `details` fields. At minimum:
- `OBS_INVALID_ENVELOPE`
- `OBS_UNSUPPORTED_SCHEMA`
- `OBS_UNSUPPORTED_EVENT_TYPE`
- `OBS_PAYLOAD_TOO_LARGE`
- `OBS_DUPLICATE_EVENT`
- `OBS_STORAGE_UNAVAILABLE`
- `OBS_QUERY_RANGE_TOO_LARGE`
- `OBS_CURSOR_EXPIRED`
- `OBS_SCOPE_FORBIDDEN`
- `OBS_CONSUMER_LAGGING`
- `OBS_METRIC_NOT_FOUND`
- `OBS_INVALID_TIME_DOMAIN`

Duplicate event submission is idempotent success at the API boundary and MUST return the original journal sequence.

## 14. Acceptance criteria

- All producers can publish events without importing Observation implementation internals.
- Events retain source and observation timestamps plus clock domain.
- Duplicate submission does not create a second journal record.
- Consumer restart and catch-up are deterministic and idempotent.
- Virtual time and wall time cannot be accidentally compared.
- Metrics expose provenance and data-quality flags.
- Timeline export is stable and redaction-aware.
- Read APIs enforce tenant/session scope and bounded queries.
- No Observation component mutates simulation or TS Core state.
