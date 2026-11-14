# SPEC-203 — L1 TS Runtime Integration
Version 0.4.0 | DRAFT_FOR_REVIEW | Phase MVP

## Boundary
TS Core owns packet/section/PES/PCR/mux/generator semantics. Simulation Engine owns lifecycle, clock policy, cancellation, resource limits and artifact lifecycle. Do not duplicate TS serialization or CC logic.

## Interface
```python
class TSRuntimeAdapter(Protocol):
    async def prepare(self, session: SessionContext, config: TSGeneratorConfig) -> PreparedTSRun: ...
    async def run(self, prepared: PreparedTSRun, sink: ArtifactSink) -> TSRunResult: ...
    async def cancel(self, run_id: str) -> None: ...
```

Use TS Core public contracts only. Long synchronous generation must not block FastAPI event loop; use bounded worker execution or subprocess based on measured load.

## Result
Contains run ID, completed/cancelled/failed status, packet and byte counts, virtual duration, artifact ID/hash, warnings/errors, generator version and effective config hash. MVP output is 188-byte TS; byte count must equal packet_count*188 for completed output.

## Cancellation and determinism
Check cancellation at bounded batches. Partial artifacts must be labeled partial, never complete. Identical config/seed/clock/fault plan and versions yield identical SHA-256. Wall time and session ID must not affect TS bytes.

## Acceptance
- AC-203-01 only public TS Core API is used.
- AC-203-02 188-byte alignment and count consistency.
- AC-203-03 cancellation bounded; partial output labeled.
- AC-203-04 deterministic SHA-256.
- AC-203-05 event loop remains responsive.
- AC-203-06 artifact records reproducibility metadata.
