# SPEC-200 — Simulation Runtime and Session Lifecycle
Version 0.4.0 | DRAFT_FOR_REVIEW | Phase MVP

## Purpose and scope
Own one local sandbox session lifecycle, task/resource ownership, orchestration of L0 and L1, and snapshot publication. Does not encode TS packets or implement protocol parsing.

## Lifecycle
States: CREATED, VALIDATING, READY, RUNNING, PAUSED, STOPPING, STOPPED, FAILED, DISPOSED.
Allowed: CREATED->VALIDATING->READY->RUNNING; RUNNING<->PAUSED; RUNNING/PAUSED/READY/FAILED->STOPPING->STOPPED->DISPOSED. VALIDATING may fail; RUNNING/PAUSED may fail. Illegal transitions raise `InvalidLifecycleTransition`. STOPPED cannot restart; create a new session.

## Interface
```python
class SimulationRuntime(Protocol):
    async def create_session(self, spec: SimulationSessionSpec) -> SessionView: ...
    async def validate_session(self, session_id: str) -> ValidationReport: ...
    async def start(self, session_id: str) -> SessionView: ...
    async def pause(self, session_id: str) -> SessionView: ...
    async def resume(self, session_id: str) -> SessionView: ...
    async def stop(self, session_id: str, reason: str = "user") -> SessionView: ...
    async def dispose(self, session_id: str) -> None: ...
    async def get_snapshot(self, session_id: str) -> SimulationSnapshot: ...
```

## Session contract
Session spec includes server-generated UUID, sandbox mode, topology, uint64 seed, deterministic flag, clock config and resource limits. Snapshot is a full replacement view containing session ID, monotonically increasing revision, virtual time, lifecycle, topology revision, node/edge states, active faults and latest artifact refs.

## Concurrency and errors
Serialize commands per session with an async lock. Sessions must not share mutable state. Stop is idempotent. Disposal joins/cancels owned tasks and child processes. Failures use stable categories VALIDATION, CONFIGURATION, RESOURCE_LIMIT, ENGINE, IO, CANCELLED, INTERNAL. Redact secrets.

## Acceptance
- AC-200-01 legal/illegal transition tests cover the transition table.
- AC-200-02 duplicate start cannot spawn duplicate workers.
- AC-200-03 stop is idempotent and bounded by shutdown timeout.
- AC-200-04 dispose leaves no owned task/process.
- AC-200-05 sessions are isolated.
- AC-200-06 snapshot revision increases monotonically.
