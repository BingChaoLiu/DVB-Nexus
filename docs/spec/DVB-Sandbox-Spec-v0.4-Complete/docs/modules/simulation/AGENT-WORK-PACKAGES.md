# Agent Work Packages

| Package | Spec | Work | Dependency |
|---|---|---|---|
| SIM-A | 201 | Clock + deterministic scheduler | shared types frozen |
| SIM-B | 202 | Topology validation + pure L0 evaluators | port/domain model frozen |
| SIM-C | 200 | Session manager/lifecycle | 201 interface |
| SIM-D | 203 | TS Core adapter/artifact sink | TS Core API |
| SIM-E | 204 | Fault schemas/scheduler/hooks | 202 + 203 |
| SIM-F | 205 | Scenario schema/loader/action policy | 200 + 204 |
| SIM-G | 206 | Evidence-based recovery evaluator | observation adapter |

Every Agent must submit an implementation plan before coding, list allowed files, tests and acceptance criteria, avoid unrelated edits, raise a Spec Change Request for contract changes, and submit IMPLEMENTATION_REPORT with exact test commands/results. Do not parallelize against unstable shared interfaces.
