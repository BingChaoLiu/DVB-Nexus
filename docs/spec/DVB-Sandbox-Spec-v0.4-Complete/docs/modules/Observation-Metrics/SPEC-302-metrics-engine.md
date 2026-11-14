# SPEC-302 — Metrics Engine

## 1. Purpose

Define derived metric series and aggregation semantics for TS, simulation, topology and observation health.

## 2. Metric model

A metric definition contains:
- `metric_name`: stable dotted identifier.
- `value_type`: `counter|gauge|histogram`.
- `unit`: explicit unit.
- `description`.
- `allowed_dimensions`: finite dimension allow-list.
- `source_event_types` and/or snapshot source.
- `aggregation`: supported operation.
- `temporality`: `cumulative|delta|instant`.
- `quality_policy`: handling for gaps, late and invalid samples.

A sample contains metric name, timestamp and domain, value, dimensions, source event IDs or source watermark, and quality flags.

## 3. Initial metric catalog

| Metric | Type | Unit | Source / derivation |
|---|---|---|---|
| `ts.packet_rate` | gauge | packets/s | packet batch count / source-time delta |
| `ts.bitrate` | gauge | bit/s | bytes * 8 / source-time delta |
| `ts.continuity_error_total` | counter | errors | `ts.continuity_error` |
| `ts.pcr_jitter_ns` | histogram | ns | PCR observation |
| `ts.pcr_repetition_gap_ns` | gauge | ns | PCR observation |
| `ts.null_packet_ratio` | gauge | ratio | PID 0x1FFF packet count / total |
| `ts.scrambled_packet_ratio` | gauge | ratio | TS scrambling control bits |
| `psi.section_repetition_gap_ms` | gauge | ms | section observation |
| `simulation.virtual_time_ns` | gauge | ns | virtual clock |
| `simulation.event_lag_ns` | gauge | ns | observed/source mapped difference only when mapping exists |
| `topology.degraded_node_count` | gauge | nodes | topology snapshot |
| `observation.ingest_events_total` | counter | events | gateway |
| `observation.duplicate_events_total` | counter | events | gateway |
| `observation.consumer_lag_events` | gauge | events | journal sequence minus checkpoint |
| `observation.alerts_active` | gauge | alerts | alert store |

No metric may use high-cardinality dimensions such as arbitrary payload text, raw URLs, BISS keys, full service names from untrusted sources, or event IDs.

## 4. Dimensions

Allowed baseline dimensions:
- `session_id`
- `scenario_id`
- `source_id`
- `service_id`
- `pid` (bounded numeric dimension; optional)
- `node_id`
- `fault_type`
- `severity`
- `stream_id`

Every metric MUST declare its allowed dimensions. Unknown dimensions are rejected or dropped according to strictness configuration; default is reject.

## 5. Aggregation

Supported operations:
- `sum`, `min`, `max`, `avg`, `last`
- histogram `count`, `sum`, quantiles from configured buckets
- counter `rate` and `increase`

Time windows are half-open `[start, end)`. `step` is explicit. The response MUST identify the actual bucket boundary convention and time domain.

Late samples:
- A configurable lateness window is allowed.
- Samples arriving after finalization are retained in raw journal but do not silently rewrite finalized aggregates.
- If backfill is enabled, revised aggregates MUST increment `revision` and expose `is_final=false` until finalized.

Gaps:
- Missing samples are not zero by default.
- Query response includes `null` plus quality `missing` unless the metric definition explicitly specifies zero-fill.

## 6. Cardinality and retention

- Enforce per-metric active-series limits.
- Reject or quarantine samples exceeding dimension/cardinality policies.
- Retention tiers: raw, 1-minute, 1-hour.
- Downsampling MUST preserve aggregate semantics; counter resets must be detected.
- Retention deletion is asynchronous and observable.

## 7. Query contract

Request fields:
- `metric_names[]`
- `start`, `end`, `step`
- `clock_domain`
- `filters`
- `max_points`
- optional `aggregation_override` only from allowed operations.

The service MUST reject:
- `start >= end`
- missing/ambiguous clock domain
- excessive range or point count
- unknown metric unless `allow_unknown=true`
- filters on non-allowed dimensions.

Response includes series metadata, points, unit, aggregation, domain, revision, provenance summary and quality flags.

## 8. Determinism

For simulation metrics, calculations MUST be based on virtual-time timestamps and stable event ordering. Re-running the same event journal with the same metric definitions MUST produce identical metric values and bucket boundaries.

Wall-clock operational metrics are separate series and MUST NOT be merged into virtual-time series.

## 9. Acceptance tests

- Counter increase/rate including reset.
- Histogram aggregation and quantiles.
- Missing bucket quality semantics.
- Late sample and revision behavior.
- Cardinality enforcement.
- Deterministic replay equivalence.
- Unit and clock-domain validation.
