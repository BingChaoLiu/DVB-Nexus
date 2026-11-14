# SPEC-206 — Recovery Verification
Version 0.4.0 | DRAFT_FOR_REVIEW | Phase MVP

## Purpose
Verify that a learner fixed the fault using new run evidence. A green UI state alone is never sufficient.

## Inputs
Scenario revision/pass criteria, baseline run/fault evidence, candidate recovery run, normalized observations, topology/fault snapshots, artifact hash and engine versions. Until Observation/Diagnosis specs are implemented, use a local adapter and fixtures without coupling to their internals.

## Result
`verdict`: PASS / FAIL / INCONCLUSIVE; per-criterion PASS / FAIL / NOT_EVALUATED; evidence refs; summary; run/scenario version identifiers and operational verification timestamp.

## Rules
A PASS requires every mandatory criterion to pass. Any mandatory FAIL => FAIL. Missing mandatory evidence => INCONCLUSIVE. Distinguish no observation from clean observation, unsupported analyzer from invalid protocol, missing value from zero, and expected discontinuity from unexpected CC error.

Example criteria: PAT present/CRC valid; PAT-to-PMT PID mapping valid; PMT CRC valid; selected PID CC valid under defined packet semantics; fault inactive.

## Acceptance
- AC-206-01 UI state without evidence cannot pass.
- AC-206-02 missing mandatory evidence is INCONCLUSIVE.
- AC-206-03 each criterion has evidence or explicit not-evaluated reason.
- AC-206-04 recovery run differs from baseline.
- AC-206-05 criteria evaluated deterministically.
- AC-206-06 verdict persisted with run/scenario revisions.
