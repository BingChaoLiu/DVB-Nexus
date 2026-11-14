# Observation Integration Contract

**Status:** Draft — requires joint approval from TS Core, Simulation Engine and Architecture Owner.

## 1. Producer obligations

Every producer MUST:
1. Emit SPEC-301 envelope v1.0.
2. Generate stable `event_id` before first publish and reuse it on retry.
3. Supply source clock domain and timestamp.
4. Supply producer identity/version/instance.
5. Avoid secrets and unbounded/high-cardinality labels.
6. Treat Observation as a downstream sink; do not depend on private Observation classes.
7. Handle explicit retryable/non-retryable publish errors.

## 2. Simulation Engine mapping

| Simulation source | Observation event |
|---|---|
| Runtime lifecycle | `simulation.session_*` |
| Virtual Clock | `simulation.clock_advanced` (batch/coalesced; do not emit every scheduler tick unless configured) |
| L0 state change | `topology.state_changed` |
| Fault Injection | `fault.injected`, `fault.activated`, `fault.cleared` |
| Scenario Engine | `scenario.step_started`, `scenario.step_completed` |
| Recovery Verification | `recovery.verification_completed` |

The authoritative session/clock/topology/fault state remains in Simulation Engine. Observation stores copies for analysis.

## 3. TS Core mapping

| TS Core fact | Observation event |
|---|---|
| Packet batch stats | `ts.packet_batch_observed` |
| Continuity counter mismatch | `ts.continuity_error` |
| PCR sample/jitter | `ts.pcr_jitter_observed` |
| PSI/SI section parsed | `ts.psi_section_observed` |
| Service/PID state | `ts.service_state_changed` |

TS Core MUST publish normalized facts with explicit units and parser/version provenance. It SHOULD batch high-frequency packet statistics; it MUST NOT emit one event per TS packet by default.

## 4. Idempotency

Producer event identity MUST survive retries and process-level retry queues. If a producer cannot guarantee event ID stability, it is not conformant.

## 5. Backpressure

- Observation returns accepted/duplicate/rejected with structured result.
- Retryable storage errors use bounded exponential backoff with jitter at producer side.
- Producer queues MUST be bounded and expose dropped/rejected counts.
- Simulation's virtual clock thread MUST NOT block on synchronous disk I/O.
- Critical lifecycle events SHOULD use a durable producer outbox or equivalent.

## 6. Contract freeze checklist

- [ ] Event envelope schema v1.0 approved.
- [ ] Clock-domain naming and epoch behavior approved.
- [ ] Initial event type registry approved.
- [ ] Producer retry and outbox behavior approved.
- [ ] TS packet batch event payload approved.
- [ ] Topology snapshot version and identity approved.
- [ ] Security/redaction policy approved.
- [ ] Performance profile and retention approved.

## 7. Integration sequence

1. Contract tests shared with producers.
2. Event gateway + journal.
3. Simulation Engine lifecycle/fault events.
4. TS Core normalized events.
5. Metrics and timeline.
6. Health/alerts.
7. Query API and frontend integration.
8. Load, replay determinism and retention verification.

## 8. Non-negotiable boundary

Observation MUST NOT import or invoke Simulation Engine mutation interfaces, TS Core parser internals, or Diagnosis Engine decision APIs. Integration is through published contracts only.
