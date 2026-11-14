# DVB Sandbox — Observation & Metrics Module

- **Module:** Observation & Metrics (SPEC-3XX)
- **Architecture baseline:** DVB Sandbox v0.4
- **Status:** `DRAFT_FOR_REVIEW`
- **Backend baseline:** Python
- **Primary stream baseline:** MPEG-2 Transport Stream (TS)
- **Simulation baseline:** Hybrid (deterministic virtual-time core + real-time/live adapters)

## Purpose

This package defines the observation plane that turns events and state emitted by TS Core, Simulation Engine, and (later) Live adapters into a consistent, queryable, time-aligned operational record.

It is deliberately an observer: it MUST NOT become a second simulation engine, mutate topology, schedule faults, rewrite TS packets, or make recovery decisions.

## Package contents

| File | Purpose |
|---|---|
| `SPEC-300-observation-architecture.md` | Module boundary, architecture, lifecycle, data flow |
| `SPEC-301-event-contract.md` | Canonical event envelope, ordering, delivery and deduplication |
| `SPEC-302-metrics-engine.md` | Metric definitions, aggregation, labels and retention |
| `SPEC-303-timeline-recorder.md` | Timeline, checkpoints, replay and export |
| `SPEC-304-health-and-alerts.md` | Health rules, alert lifecycle and evidence |
| `SPEC-305-query-api.md` | Internal service API and query semantics |
| `OBSERVATION-INTEGRATION-CONTRACT.md` | Cross-module frozen contracts and integration sequence |
| `TRACEABILITY.md` | Requirements-to-spec-to-test mapping |
| `AGENT-WORK-PACKAGES.md` | Bounded work packages for implementation agents |
| `CHANGE-REQUEST-TEMPLATE.md` | Controlled change process |
| `IMPLEMENTATION-REPORT-TEMPLATE.md` | Required implementation evidence |
| `schemas/*.schema.json` | JSON Schemas for canonical records |
| `examples/*` | Normative examples for event, metric and alert records |
| `MANIFEST.sha256` | Integrity manifest |

## Normative language

The terms MUST, MUST NOT, REQUIRED, SHOULD, SHOULD NOT and MAY are normative.

## Authority and implementation rules

1. This package is the implementation source of truth for SPEC-3XX after approval.
2. No agent may infer or introduce cross-module behavior not specified here.
3. If a required field, state transition, ordering rule, or error behavior is missing, submit a Change Request before implementation.
4. Public contracts are versioned. Additive optional fields are allowed only when compatibility rules are met.
5. Every implementation package must include tests and an `IMPLEMENTATION_REPORT.md`.
6. This draft is not authorization to freeze APIs or begin integration. Architecture owner approval is required.

## Baseline decisions

- Internal timestamps are signed integer nanoseconds on the originating clock domain.
- Events preserve both source time and observation/ingestion time.
- Simulation virtual time and wall-clock time are distinct domains and MUST never be silently mixed.
- Event delivery is at-least-once; consumers deduplicate by `event_id`.
- Metrics are derived from events/state snapshots and carry provenance.
- Timeline storage is append-oriented; corrections are represented by new records, not in-place mutation.
- Query APIs are read-only.

## Suggested implementation order

1. SPEC-301 event envelope and validation.
2. SPEC-300 architecture interfaces and event ingestion.
3. SPEC-302 metrics.
4. SPEC-303 timeline persistence and export.
5. SPEC-304 health/alert evaluation.
6. SPEC-305 query API.
7. End-to-end integration and load/retention tests.
