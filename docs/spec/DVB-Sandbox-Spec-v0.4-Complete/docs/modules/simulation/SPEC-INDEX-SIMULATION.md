# Simulation Engine Spec Index

| ID | Module | Depends on |
|---|---|---|
| SPEC-200 | Simulation Runtime / Session Lifecycle | 201, 202, 203 |
| SPEC-201 | Virtual Clock / Deterministic Scheduler | 001, 003 |
| SPEC-202 | L0 State Engine / Topology Evaluation | 003, 201 |
| SPEC-203 | L1 TS Runtime Adapter | 100..108, 200, 201 |
| SPEC-204 | Fault Injection | 202, 203 |
| SPEC-205 | Scenario / Training Lab Engine | 200, 204 |
| SPEC-206 | Recovery Verification | 204, 205, Observation contracts |

Dependency direction: Simulation Engine may call TS Core public APIs; TS Core must not import Simulation Engine. Observation/Diagnosis consume runtime events and artifacts.
