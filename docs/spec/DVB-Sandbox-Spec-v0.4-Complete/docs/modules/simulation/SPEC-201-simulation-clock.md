# SPEC-201 — Simulation Clock and Deterministic Scheduler
Version 0.4.0 | DRAFT_FOR_REVIEW | Phase MVP

## Time domains
`virtual_time_ns` is monotonic integer nanoseconds from a session epoch. Wall time is operational metadata only. PCR/PTS/DTS ticks remain TS Core domains (SPEC-105/104); never conflate them.

## Configuration
```python
@dataclass(frozen=True)
class SimulationClockConfig:
    mode: Literal["deterministic", "realtime"]
    start_time_ns: int = 0
    speed_num: int = 1
    speed_den: int = 1
    tick_quantum_ns: int = 1_000_000
```
All numeric values are range-validated; speed uses rational integers, not float.

## Interface
```python
class SimulationClock(Protocol):
    def now_ns(self) -> int: ...
    async def advance_to(self, target_ns: int) -> int: ...
    async def advance_by(self, delta_ns: int) -> int: ...
    async def pause(self) -> None: ...
    async def resume(self) -> None: ...
    def is_paused(self) -> bool: ...
```

Deterministic mode advances only through scheduler commits/explicit advance. Realtime mode scales elapsed wall time by speed ratio. Scheduler order is `(deadline_ns, priority, insertion_sequence)`; lower priority number first, insertion sequence breaks ties. Enforce a work budget to prevent zero-time callback starvation. Callbacks cannot block.

## Reproducibility
Identical engine version, config, seed, topology and fault plan must produce identical event order and TS bytes. Do not embed wall-clock time, random session ID, PID or absolute path in deterministic TS bytes.

## Acceptance
- AC-201-01 monotonic time; backwards movement rejected.
- AC-201-02 stable tie ordering and priority.
- AC-201-03 pause freezes virtual time.
- AC-201-04 rational speed avoids float drift.
- AC-201-05 scheduler cancellation and work budget prevent starvation.
- AC-201-06 conversions to PCR/PTS use explicit tested functions.
