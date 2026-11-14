# SPEC-301 — Canonical Event Contract

## 1. Purpose

Define the single event envelope shared by TS Core, Simulation Engine, Live adapters and Observation. Event payloads are domain-specific; the envelope and delivery semantics are common.

## 2. Canonical envelope

```json
{
  "schema_version": "1.0",
  "event_id": "01J...ULID",
  "event_type": "ts.continuity_error",
  "producer": {
    "producer_id": "ts-core",
    "producer_version": "0.4.0",
    "instance_id": "ts-core-1"
  },
  "scope": {
    "tenant_id": "local",
    "session_id": "sess-001",
    "scenario_id": "scenario-cc-discontinuity"
  },
  "time": {
    "source": {"value_ns": 1200000000, "clock_domain": "sim:sess-001", "clock_epoch": 0},
    "observed": {"value_ns": 1730000000000000000, "clock_domain": "wall:utc", "clock_epoch": 0}
  },
  "correlation": {
    "trace_id": "trace-001",
    "span_id": "span-001",
    "parent_event_id": null,
    "fault_id": "fault-001",
    "node_id": "demux-0",
    "service_id": "service-100",
    "pid": 256
  },
  "severity": "warning",
  "payload": {
    "expected_cc": 4,
    "actual_cc": 6,
    "discontinuity_indicator": false
  },
  "tags": ["ts", "continuity"]
}
```

## 3. Required fields

- `schema_version`: semantic version string.
- `event_id`: globally unique, stable across retries.
- `event_type`: lowercase dotted identifier, e.g. `simulation.session_started`.
- `producer.producer_id`, `producer.producer_version`, `producer.instance_id`.
- `scope.tenant_id`; `scope.session_id` is nullable only for system-level events.
- `time.source` and `time.observed`.
- `severity`: `debug|info|notice|warning|error|critical`.
- `payload`: JSON object, event-specific schema validated by registry.
- `tags`: array of bounded strings.

## 4. Event type namespace

Recommended initial event types:
- `simulation.session_created`
- `simulation.session_started`
- `simulation.session_paused`
- `simulation.session_resumed`
- `simulation.session_stopped`
- `simulation.clock_advanced`
- `topology.state_changed`
- `ts.packet_batch_observed`
- `ts.continuity_error`
- `ts.pcr_jitter_observed`
- `ts.psi_section_observed`
- `ts.service_state_changed`
- `fault.injected`
- `fault.activated`
- `fault.cleared`
- `scenario.step_started`
- `scenario.step_completed`
- `recovery.verification_completed`
- `observation.alert_opened`
- `observation.alert_updated`
- `observation.alert_resolved`

New event types require registry/schema additions and compatibility review.

## 5. Ordering and delivery

- Producers MUST generate stable `event_id` before first publish.
- Delivery is at-least-once.
- Observation deduplicates using `(producer_id, event_id)`.
- `journal_seq` is assigned only after durable append.
- Source timestamps do not define total order.
- Within a producer instance, producers SHOULD include a monotonically increasing `producer_seq`.
- Causality SHOULD be expressed using `parent_event_id` and trace identifiers.
- Consumers MUST be idempotent.

## 6. Clock semantics

`time.source` is the event's originating clock. `time.observed` is assigned by the gateway if absent and always denotes ingestion observation time. For deterministic simulation, source time MUST use the session virtual clock domain.

A producer MUST NOT stamp a virtual-time event using wall-clock time merely because it is easier to obtain.

## 7. Payload rules

- Payload is a JSON object, not an arbitrary string.
- Maximum serialized event size defaults to 256 KiB.
- Binary data MUST be stored out-of-line and referenced by a scoped content identifier.
- No secrets, BISS keys, credentials, or private keys.
- Units MUST be explicit in field names or schema metadata (`*_ns`, `*_bps`, `*_count`).
- Missing, unknown and not-applicable values MUST be distinguishable; use null only when schema permits.

## 8. Compatibility

- Minor schema versions may add optional fields.
- Removing/renaming fields or changing units requires a major schema version and migration plan.
- Consumers MUST ignore unknown optional fields.
- Unknown required fields or unsupported major versions are rejected.
- Event type payload schema is independently versioned.

## 9. Error handling

Malformed events are rejected before journal commit. The producer receives a structured error. Duplicate event IDs return the original `journal_seq` with `duplicate=true`.

## 10. Required tests

- Envelope validation for each required/nullable field.
- Duplicate retry idempotency.
- Out-of-order source timestamp behavior.
- Clock-domain mismatch rejection in time-range queries.
- Unknown optional field forward compatibility.
- Unsupported major schema rejection.
- Payload size and secret-field policy tests.
