# SPEC-204 — Fault Injection Framework
Version 0.4.0 | DRAFT_FOR_REVIEW | Phase MVP

## Purpose
Typed, deterministic faults for synthetic sandbox streams. A fault must alter actual state or stream evidence, never merely paint the UI red.

## Fault model
```python
@dataclass(frozen=True)
class FaultDefinition:
    fault_id: str
    fault_type: str
    target_id: str
    injection_point: str
    parameters: Mapping[str, object]
    activation: FaultActivation
    expected_observations: tuple[str, ...]
```
Activation supports session start, virtual time, packet index or manual trigger. Never schedule with wall-clock sleeps.

## MVP types
- PAT_MISSING: suppress PAT for a configured run/window.
- PMT_INVALID_CRC: corrupt selected PMT section CRC.
- CC_DISCONTINUITY: alter selected PID CC at a specified packet index; define payload/adaptation-only semantics.
- PMT_PID_MISMATCH: PAT points to a different PMT PID than the emitted table.

Each fault has a versioned parameter schema. Unknown types/keys are rejected.

## Lifecycle and evidence
DEFINED -> SCHEDULED -> ACTIVE -> APPLIED -> REMOVED, or FAILED. Fault application is atomic at a defined packet/config boundary. Emit fault ID/type, target, injection point, virtual time or packet index, before/after summary, run/artifact reference and parameters. Never log secrets.

## Acceptance
- AC-204-01 invalid fault rejected before session mutation.
- AC-204-02 identical seed/config/schedule reproduces result.
- AC-204-03 L1 fault changes artifact hash.
- AC-204-04 every applied fault has event and evidence locator.
- AC-204-05 reversible fault restores baseline.
- AC-204-06 no UI-only fault.
- AC-204-07 packet-index injection is stable.
Safety: MVP faults apply only to locally generated synthetic streams, not live production streams or real DVB hardware.
