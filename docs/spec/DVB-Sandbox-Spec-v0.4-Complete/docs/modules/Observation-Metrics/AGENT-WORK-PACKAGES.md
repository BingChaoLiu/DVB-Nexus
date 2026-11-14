# Agent Work Packages — SPEC-3XX

## Global rules for all agents

- Read `README.md`, `SPEC-300`, `SPEC-301`, and the integration contract first.
- Do not change public contracts without an approved Change Request.
- Submit an implementation plan before editing.
- Stay within assigned paths and responsibilities.
- Do not add dependencies without justification and approval.
- Provide unit, integration and negative tests.
- Submit `IMPLEMENTATION_REPORT.md` with files changed, tests, limitations and traceability.

## OBS-A — Event Contract & Schema
**Owns:** SPEC-301, `schemas/event-envelope.schema.json`, event type registry and validation tests.  
**Depends on:** Architecture Owner.  
**Must not:** implement journal persistence or metric logic.  
**Exit:** contract fixtures pass; schema compatibility tests included.

## OBS-B — Gateway & Journal
**Owns:** SPEC-300 Event Gateway/Event Journal implementation.  
**Depends on:** OBS-A.  
**Must not:** parse TS or derive metrics.  
**Exit:** append/idempotency/cursor/checkpoint/restart tests; bounded queue and explicit errors.

## OBS-C — Metrics Engine
**Owns:** SPEC-302 and metric schemas/catalog.  
**Depends on:** OBS-A, OBS-B.  
**Must not:** alter source events or introduce diagnosis conclusions.  
**Exit:** deterministic replay, aggregation, quality and cardinality tests.

## OBS-D — Timeline Recorder
**Owns:** SPEC-303, export manifest schema and export implementation.  
**Depends on:** OBS-B.  
**Must not:** execute simulation replay or mutate checkpoints upstream.  
**Exit:** pagination, multi-clock, export integrity and redaction tests.

## OBS-E — Health & Alerts
**Owns:** SPEC-304 and rule/alert state machine.  
**Depends on:** OBS-C, OBS-D.  
**Must not:** auto-repair or clear injected faults.  
**Exit:** deterministic virtual-time lifecycle and evidence tests.

## OBS-F — Query API
**Owns:** SPEC-305 service/API layer and API contract tests.  
**Depends on:** OBS-B through OBS-E.  
**Must not:** expose storage internals or mutation operations.  
**Exit:** scope, bounds, pagination, errors and reconnect tests.

## OBS-G — Integration & Performance
**Owns:** cross-module integration suite, load profile and operational dashboards.  
**Depends on:** OBS-A through OBS-F and producer contract conformance.  
**Must not:** silently alter producer contracts.  
**Exit:** end-to-end acceptance report with throughput, latency, lag, memory and retention evidence.

## Recommended parallelism

OBS-A first. OBS-B can begin only after event envelope is frozen. OBS-C and OBS-D may proceed in parallel after journal interfaces stabilize. OBS-E follows metrics/timeline contracts. OBS-F can build service interfaces against approved mocks, then integrate. OBS-G is final.
