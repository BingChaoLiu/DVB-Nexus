# SPEC-3XX Traceability Matrix

| Requirement ID | Requirement | Spec | Required verification |
|---|---|---|---|
| OBS-001 | Canonical versioned event envelope | 301 | Schema validation tests |
| OBS-002 | At-least-once delivery with idempotent ingest | 300, 301 | Duplicate/retry tests |
| OBS-003 | Preserve source and observed clocks | 300, 301 | Clock-domain tests |
| OBS-004 | Durable append journal and consumer checkpoints | 300 | Restart/catch-up tests |
| OBS-005 | Deterministic simulation metric derivation | 302 | Replay equivalence tests |
| OBS-006 | Bounded cardinality and retention | 302 | Cardinality/retention tests |
| OBS-007 | Unified timeline and cursor pagination | 303 | Query/export tests |
| OBS-008 | Redaction-aware export and integrity digests | 303 | Secret scan/digest tests |
| OBS-009 | Rule-based health and alert lifecycle | 304 | State-machine tests |
| OBS-010 | Evidence-backed alert records | 304 | Evidence referential tests |
| OBS-011 | Read-only bounded query APIs | 305 | API contract/security tests |
| OBS-012 | Scope isolation | 300, 305 | Cross-tenant/session tests |
| OBS-013 | Producer contract conformance | Integration Contract | Shared producer contract suite |
| OBS-014 | No mutation of upstream state | 300, Integration Contract | Dependency/import boundary tests |
| OBS-015 | Observable backpressure and consumer lag | 300, 302 | Load/lag tests |

A requirement is complete only when implementation, automated test, and `IMPLEMENTATION_REPORT.md` evidence are present.
