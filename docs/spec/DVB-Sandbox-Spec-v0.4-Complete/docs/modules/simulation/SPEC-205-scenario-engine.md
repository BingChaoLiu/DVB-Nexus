# SPEC-205 — Scenario and Training Lab Engine
Version 0.4.0 | DRAFT_FOR_REVIEW | Phase MVP

## Scenario definition
A versioned declarative document includes scenario ID/version/title/difficulty, required engine versions, initial topology, simulation config, fault plan, objectives, staged hints, pass criteria and optional hidden reference solution.

## Safety and validation
JSON/YAML schema validation is mandatory. Never execute Python or arbitrary code from a scenario package. Learner actions are allow-listed: inspect topology/evidence, modify approved config fields, change permitted faults, regenerate/analyze, submit verification. No arbitrary shell commands or arbitrary filesystem paths.

## Execution
Loading a scenario creates a new session and pins scenario version/content hash. It does not mutate a running session. Re-run creates a distinct run record. Reference solution must not leak before reveal policy allows it.

## Hints
Each hint has ID, trigger, level, content, related requirement IDs and optional precise standard reference. Do not invent ETSI/ITU clause numbers.

## Acceptance
- AC-205-01 malformed schema rejected.
- AC-205-02 scenario immutable after session creation.
- AC-205-03 reference solution protected.
- AC-205-04 deterministic initial run reproducible.
- AC-205-05 learner actions allow-listed.
- AC-205-06 import/export contains no executable content.
