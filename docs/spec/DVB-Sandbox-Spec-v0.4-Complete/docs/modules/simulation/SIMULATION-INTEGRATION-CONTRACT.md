# Simulation Engine Integration Contract
Status: DRAFT_FOR_REVIEW

## Dependency direction
API/UI -> Runtime(200) -> Clock(201), L0(202), L1 adapter(203)->TS Core(100..108), Faults(204), Scenarios(205), Verification(206). Observation/Diagnosis consume events/artifacts. TS Core must not import Simulation Engine.

## Canonical IDs
session_id, run_id, fault_id, scenario_id, artifact_id, node_id, edge_id are opaque UUID strings. Consumers must not parse semantic meaning. Revision is monotonically increasing per session.

## Event envelope
```json
{
  "event_id": "uuid",
  "event_type": "simulation.run.progress",
  "schema_version": 1,
  "session_id": "uuid",
  "run_id": "uuid",
  "sequence": 12,
  "virtual_time_ns": 1000000000,
  "wall_time": "operational-only",
  "payload": {}
}
```
Sequence increases per session. Wall time is excluded from deterministic hashes. Events include lifecycle.changed, snapshot.updated, run.started/progress/completed/failed, fault.scheduled/applied/removed, verification.completed.

## Snapshot and artifact
Snapshot is a full-state replacement with session/revision/lifecycle/virtual time/topology revision/nodes/edges/active faults/latest run. Artifact record has ID, kind, status complete/partial/failed, opaque URI, size, SHA-256, producing run ID and metadata. Never accept client filesystem paths.

## Backpressure
Progress/metrics may be coalesced and rate-limited. Fault, lifecycle, terminal run and verification events must not be silently dropped. WebSocket is best-effort; clients recover with snapshot + sequence cursor. Raw packets are fetched through bounded evidence APIs, not broadcast per packet.

## Versioning
Every event/scenario has schema_version. Additive optional fields are compatible; semantic/unit changes or removals require a breaking version and migration.
