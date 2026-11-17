"""SPEC-200 — Simulation Runtime and session lifecycle (ticket #41).

The runtime is the single authority for session lifecycle (SPEC-200
section 1): it owns every session's :class:`SimulationClock` (SPEC-201, #39)
and L0 State Engine graph (SPEC-202, #40), serializes all mutating commands
per session on one :class:`asyncio.Lock` (section 7 item 1), drives the
exhaustive section 5 transition table through
:mod:`simulation.lifecycle`, publishes the pull-API snapshot (section 4,
:mod:`simulation.snapshot`) and carries the section 7.4 event emission
obligation for the ``simulation.session_*`` / ``simulation.run_*`` families
through an injected :class:`SessionEventSink`.

Import-contract note (ADR-0005 D4-4 + M3 ruling): this package may depend
on ``ts``/``faults``/``adapters`` plus the canonical ``domain.observation``
envelope, but NOT on ``application``. The #47 gateway/publisher is
therefore consumed through the structural :class:`SessionEventSink`
protocol — the composition root (or a test) injects whichever publisher
face it has; the runtime never imports the application layer and never
invents a fourth envelope (events are built and schema-validated through
``domain.observation.parse_envelope`` in :mod:`simulation.events`).

Seams owned elsewhere (declared, not implemented — boundary discipline):

- ``ArtifactRef`` / artifact persistence: ticket #42 (storage adapter) /
  #43 (SIM-D artifact sink). The runtime only carries references.
- ``FaultView`` / fault scheduling: ticket #44 (SIM-E, SPEC-204).
- ``runner_factory`` / the real engine loop: SPEC-203 / SIM-D (#43).
- ``ResourceLimits`` numeric values: OPEN-006 ruling (#16); structure only.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol, Sequence

from simulation.clock import SimulationClock, SimulationClockConfig
from simulation.errors import (
    SIM_ENGINE_ERROR,
    SIM_SESSION_NOT_FOUND,
    SessionNotFoundError,
    SimulationEngineError,
    SimulationValidationError,
)
from simulation.lifecycle import LifecycleState, require_transition
from simulation.events import SimulationEventEmitter
from simulation.errors import TopologyCycleError
from simulation.state import (
    Connection,
    Health,
    PortState,
    TopologyEvalResult,
    TopologyGraph,
    TopologyViolation,
    evaluate_topology,
    validate_topology,
)

__all__ = [
    "ArtifactRef",
    "ConnectionView",
    "FaultView",
    "NodeState",
    "ResourceLimits",
    "RunView",
    "SessionEventSink",
    "SessionView",
    "SimulationRuntime",
    "SimulationSessionSpec",
    "ValidationReport",
    "new_session_spec",
    # ticket #45 appended face (see VALIDATION_GATES below)
    "VALIDATION_GATES",
]

# --- ticket #45 appended face (SPEC-205, SIM-F) ---------------------------------
#
# Session-validation gates consulted inside ``validate_session`` while the
# session is in the VALIDATING phase (SPEC-200 section 5). Each gate
# receives the session spec and returns path-addressed violation strings
# (empty = pass); violations are appended to the topology violations and
# ride the same ``SIM_VALIDATION_FAILED`` report path.
#
# Appended-face discipline: the default-empty list preserves #41 behavior
# byte-identically for every existing caller — no gate, no change. The
# scenario engine (simulation.scenario.loader, #45) registers its
# fault-plan gate (缺 expected_observations 的 scenario 在 VALIDATING 被
# 拒绝 — ticket #45 acceptance core) through
# ``install_scenario_validation_gate``; no existing signature or export
# changed.
VALIDATION_GATES: list[Callable[[SimulationSessionSpec], Sequence[str]]] = []


# --- SPEC-200 section 4 data model -------------------------------------------


@dataclass(frozen=True)
class ResourceLimits:
    """码率/内存/时长上限（SPEC-200 §4）。

    Structure frozen by SPEC-200; the numeric envelope is OPEN-006's ruling
    (#16) — this ticket freezes the shape only. ``None`` = unset.
    """

    bitrate_bps: int | None = None
    memory_bytes: int | None = None
    duration_ns: int | None = None

    def __post_init__(self) -> None:
        for name in ("bitrate_bps", "memory_bytes", "duration_ns"):
            value = getattr(self, name)
            if value is None:
                continue
            if not isinstance(value, int) or isinstance(value, bool):
                raise TypeError(f"{name} must be int or None")
            if value < 1:
                raise ValueError(f"{name} must be >= 1, got {value}")


@dataclass(frozen=True)
class SimulationSessionSpec:
    """The immutable session contract (SPEC-200 section 4)."""

    session_id: str
    topology: TopologyGraph
    seed: int
    deterministic: bool
    clock_config: SimulationClockConfig
    resource_limits: ResourceLimits = field(default_factory=ResourceLimits)

    def __post_init__(self) -> None:
        if not isinstance(self.session_id, str) or not self.session_id:
            raise ValueError("session_id must be a non-empty string")
        if not isinstance(self.topology, TopologyGraph):
            raise TypeError(
                f"topology must be TopologyGraph, got "
                f"{type(self.topology).__name__}"
            )
        if not isinstance(self.seed, int) or isinstance(self.seed, bool):
            raise TypeError(f"seed must be int, got {type(self.seed).__name__}")
        if not 0 <= self.seed < 2**64:
            raise ValueError(
                f"seed must be a uint64 (0 <= seed < 2**64), got {self.seed}"
            )
        if not isinstance(self.deterministic, bool):
            raise TypeError("deterministic must be bool")
        if not isinstance(self.clock_config, SimulationClockConfig):
            raise TypeError(
                "clock_config must be SimulationClockConfig, got "
                f"{type(self.clock_config).__name__}"
            )
        if not isinstance(self.resource_limits, ResourceLimits):
            raise TypeError(
                "resource_limits must be ResourceLimits, got "
                f"{type(self.resource_limits).__name__}"
            )


def new_session_spec(
    topology: TopologyGraph,
    *,
    seed: int,
    deterministic: bool,
    clock_config: SimulationClockConfig,
    resource_limits: ResourceLimits | None = None,
) -> SimulationSessionSpec:
    """Build a spec with a server-generated uuid4 ``session_id`` (ADR-0006
    decision 3: machine entity IDs are uuid4 opaque)."""
    return SimulationSessionSpec(
        session_id=str(uuid.uuid4()),
        topology=topology,
        seed=seed,
        deterministic=deterministic,
        clock_config=clock_config,
        resource_limits=resource_limits or ResourceLimits(),
    )


@dataclass(frozen=True)
class NodeState:
    """One node's snapshot-facing state (SPEC-003 section 3 vocabulary)."""

    node_id: str
    health: Health
    ports: tuple[PortState, ...] = ()


@dataclass(frozen=True)
class ConnectionView:
    """One connection's identity inside a snapshot (read-only mirror)."""

    connection_id: str
    from_node: str
    from_port: str
    to_node: str
    to_port: str


@dataclass(frozen=True)
class FaultView:
    """Active-fault reference (seam for #44 / SPEC-204 — id + state only)."""

    fault_id: str
    state: str


@dataclass(frozen=True)
class ArtifactRef:
    """Latest-artifact reference (seam for #42/#43 — identity only).

    Artifact storage/records are #42's adapter face; the runtime carries
    opaque references and never touches file paths (SPEC-200 section 2.2).
    """

    artifact_id: str
    kind: str
    status: str


@dataclass(frozen=True)
class SessionView:
    """The per-command session answer (SPEC-200 section 4)."""

    session_id: str
    revision: int
    lifecycle: LifecycleState
    virtual_time_ns: int
    topology_revision: int
    node_states: Mapping[str, NodeState]
    active_faults: tuple[FaultView, ...] = ()
    latest_artifact_refs: tuple[ArtifactRef, ...] = ()


@dataclass(frozen=True)
class RunView:
    """Run-dimension record (SPEC-200 section 7.4 run_* obligations).

    Minimal producer-side run registry consumed by SPEC-203 / SIM-D (#43):
    the runtime tracks run identity/lifecycle so ``run_*`` events can be
    emitted; run execution itself is the adapter's concern.
    """

    run_id: str
    state: str  # "running" | "completed" | "failed"
    started_virtual_ns: int
    ended_virtual_ns: int | None = None


@dataclass(frozen=True)
class ValidationReport:
    """SPEC-202 path-addressed validation answer (SPEC-200 section 6)."""

    violations: tuple[TopologyViolation, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.violations


@dataclass(frozen=True)
class SimulationSnapshot:
    """Full replacement view + ``journal_seq`` cursor echo (SPEC-200 §4).

    Defined beside the data model to avoid an import cycle; the pull-API
    documentation lives in :mod:`simulation.snapshot`.
    """

    session_id: str = ""
    revision: int = 0
    lifecycle: LifecycleState = LifecycleState.CREATED
    virtual_time_ns: int = 0
    topology_revision: int = 0
    node_states: Mapping[str, NodeState] = field(default_factory=dict)
    connection_states: tuple[ConnectionView, ...] = ()
    active_faults: tuple[FaultView, ...] = ()
    latest_artifact_refs: tuple[ArtifactRef, ...] = ()
    journal_seq_cursor: int | None = None


class SessionEventSink(Protocol):
    """Event emission port (SPEC-200 section 7.4 obligation).

    Structural seam: any object with a synchronous ``publish`` works — in
    production the composition root injects the #47
    ``application.observation.EventGateway``/``EventPublisher`` face; the
    runtime itself never imports the application layer (import contract).
    The sink receives fully validated SPEC-301 envelope documents (dicts);
    ``journal_seq`` is stamped downstream by the gateway at durable append
    — producers never fill it.
    """

    def publish(self, event: Mapping[str, Any]) -> None: ...


# --- internal session record ---------------------------------------------------


class _Session:
    """One session's authoritative mutable state (command-lock guarded)."""

    __slots__ = (
        "spec",
        "graph",
        "clock",
        "lock",
        "lifecycle",
        "revision",
        "node_states",
        "runs",
        "tasks",
        "latest_artifact_refs",
    )

    def __init__(
        self,
        spec: SimulationSessionSpec,
        *,
        wall_ns_source: Callable[[], int] | None = None,
    ) -> None:
        self.spec = spec
        self.graph = spec.topology
        self.clock = SimulationClock(
            spec.clock_config, wall_ns_source=wall_ns_source
        )
        # Per-session command lock: every mutating command serializes here
        # (SPEC-200 section 7 item 1). Session isolation item 2 follows
        # from one record + one lock per session.
        self.lock = asyncio.Lock()
        self.lifecycle = LifecycleState.CREATED
        self.revision = 0
        eval_result = _safe_initial_eval(self.graph)
        self.node_states: Mapping[str, NodeState] = _node_states(eval_result)
        self.runs: dict[str, RunView] = {}
        self.tasks: set[asyncio.Task] = set()
        self.latest_artifact_refs: tuple[ArtifactRef, ...] = ()


def _node_states(eval_result: TopologyEvalResult) -> Mapping[str, NodeState]:
    """Project an eval result into the snapshot-facing NodeState mapping."""
    return {
        result.node_id: NodeState(
            node_id=result.node_id,
            health=result.health,
            ports=tuple(result.port_states),
        )
        for result in eval_result.node_results
    }


def _safe_initial_eval(graph: TopologyGraph) -> TopologyEvalResult:
    """Initial (idle-skeleton) evaluation, tolerant of invalid topologies.

    A cyclic (or otherwise structurally un evaluatable) graph must still be
    CREATED so ``validate_session`` can *report* the path-addressed
    violations and drive the session to FAILED — construction never raises
    for what validation owns (SPEC-202 section 5 非变更可重复报告纪律).
    """
    try:
        return evaluate_topology(graph)
    except TopologyCycleError:
        return TopologyEvalResult(
            topology_id=graph.topology_id,
            revision=graph.revision,
            order=(),
            node_results=tuple(),
            graph_health=Health.IDLE,
        )


def _default_runner(spec: SimulationSessionSpec):
    """The placeholder engine loop (SIM-D #43 supplies the real runner).

    Cancel-safe: it waits on a never-set event, so the bounded stop path
    cancels it deterministically; no wall clock, no IO.
    """
    return asyncio.Event().wait()


# --- the runtime ----------------------------------------------------------------


class SimulationRuntime:
    """SPEC-200 section 6 public interface implementation."""

    def __init__(
        self,
        *,
        event_sink: SessionEventSink | None = None,
        runner_factory: Callable[[SimulationSessionSpec], Any] | None = None,
        shutdown_timeout_s: float = 5.0,
        wall_ns_source: Callable[[], int] | None = None,
    ) -> None:
        self._sessions: dict[str, _Session] = {}
        self._event_sink = event_sink
        self._runner_factory = runner_factory or _default_runner
        self._shutdown_timeout_s = shutdown_timeout_s
        # SPEC-201 wall-source injection discipline (#39): production code
        # passes nothing (time.monotonic_ns); tests inject exact integers.
        self._wall_ns_source = wall_ns_source
        # §7.4 emitter: builds + schema-validates SPEC-301 envelopes and
        # hands them to the injected sink (None sink = emission opt-in).
        self._emitter = SimulationEventEmitter(
            event_sink, wall_ns_source=wall_ns_source
        )

    # --- section 6 commands ---------------------------------------------------

    async def create_session(self, spec: SimulationSessionSpec) -> SessionView:
        if not isinstance(spec, SimulationSessionSpec):
            raise TypeError(
                f"spec must be SimulationSessionSpec, got {type(spec).__name__}"
            )
        if spec.session_id in self._sessions:
            # Duplicate identity is a caller programming error, not a
            # session state (the section 8 table has no row for it).
            raise ValueError(
                f"session_id {spec.session_id!r} already exists on this "
                "runtime; session identity is uuid4-opaque and unique"
            )
        session = _Session(spec, wall_ns_source=self._wall_ns_source)
        self._sessions[spec.session_id] = session
        self._emit_session_event("simulation.session_created", session)
        return self._view(session)

    async def validate_session(self, session_id: str) -> ValidationReport:
        session = self._require(session_id)
        async with session.lock:
            require_transition(session.lifecycle, LifecycleState.VALIDATING)
            self._transition(session, LifecycleState.VALIDATING)
            violations = tuple(validate_topology(session.graph))
            # ticket #45 appended face: scenario/validation gates ride the
            # same VALIDATING phase (default-empty list = no-op for #41).
            for gate in VALIDATION_GATES:
                violations = violations + tuple(gate(session.spec))
            report = ValidationReport(violations=violations)
            if report.ok:
                require_transition(session.lifecycle, LifecycleState.READY)
                self._transition(session, LifecycleState.READY)
                return report
            # 验证失败直达 FAILED（#12 裁决边）；report rides on the error.
            require_transition(session.lifecycle, LifecycleState.FAILED)
            self._transition(session, LifecycleState.FAILED)
            raise SimulationValidationError(
                f"session {session_id} validation failed with "
                f"{len(violations)} path-addressed violation(s)",
                report=report,
            )

    async def start(self, session_id: str) -> SessionView:
        session = self._require(session_id)
        async with session.lock:
            require_transition(session.lifecycle, LifecycleState.RUNNING)
            try:
                runner = self._runner_factory(session.spec)
                task = asyncio.get_running_loop().create_task(
                    runner, name=f"session:{session_id}"
                )
            except Exception as exc:
                # start 失败可直达 FAILED（READY -> FAILED edge）。
                require_transition(session.lifecycle, LifecycleState.FAILED)
                self._transition(session, LifecycleState.FAILED)
                raise SimulationEngineError(
                    f"session {session_id} start failed: {exc}"
                ) from exc
            session.tasks.add(task)
            task.add_done_callback(session.tasks.discard)
            self._transition(session, LifecycleState.RUNNING)
            self._emit_session_event("simulation.session_started", session)
            return self._view(session)

    async def pause(self, session_id: str) -> SessionView:
        """RUNNING -> PAUSED + ``clock.pause()`` in the SAME critical section.

        SPEC-200 section 5.1: the state transition and the clock freeze are
        one atomic step — both happen under the session command lock, so no
        observer (snapshot, concurrent command) can ever see a PAUSED
        session with a running clock. Realtime mode freezes the wall-clock
        accumulator (wall time elapsed during the pause never counts);
        deterministic mode rejects every advance while frozen
        (``SIM_CLOCK_PAUSED`` — the clock's own frozen gate).
        """
        session = self._require(session_id)
        async with session.lock:
            require_transition(session.lifecycle, LifecycleState.PAUSED)
            await session.clock.pause()
            self._transition(session, LifecycleState.PAUSED)
            self._emit_session_event("simulation.session_paused", session)
            return self._view(session)

    async def resume(self, session_id: str) -> SessionView:
        """PAUSED -> RUNNING + ``clock.resume()`` — symmetric to :meth:`pause`."""
        session = self._require(session_id)
        async with session.lock:
            require_transition(session.lifecycle, LifecycleState.RUNNING)
            await session.clock.resume()
            self._transition(session, LifecycleState.RUNNING)
            self._emit_session_event("simulation.session_resumed", session)
            return self._view(session)

    async def stop(self, session_id: str, reason: str = "user") -> SessionView:
        """Bounded stop; idempotent against STOPPING/STOPPED (§6).

        ``current -> STOPPING`` -> cancel owned tasks under the shutdown
        timeout -> ``STOPPING -> STOPPED``. A timeout escalates to forced
        cancellation and the ``session_stopped`` payload annotates it
        (section 7 item 5). Repeated calls on STOPPING/STOPPED return the
        current view without re-cleaning.
        """
        session = self._require(session_id)
        async with session.lock:
            if session.lifecycle in (LifecycleState.STOPPING, LifecycleState.STOPPED):
                return self._view(session)
            require_transition(session.lifecycle, LifecycleState.STOPPING)
            self._transition(session, LifecycleState.STOPPING)
            forced = await self._drain_tasks(session)
            require_transition(session.lifecycle, LifecycleState.STOPPED)
            self._transition(session, LifecycleState.STOPPED)
            self._emit_session_event(
                "simulation.session_stopped",
                session,
                {"reason": reason, "forced": forced},
            )
            return self._view(session)

    async def dispose(self, session_id: str) -> None:
        session = self._require(session_id)
        async with session.lock:
            require_transition(session.lifecycle, LifecycleState.DISPOSED)
            await self._drain_tasks(session)
            self._transition(session, LifecycleState.DISPOSED)

    async def get_snapshot(
        self, session_id: str, *, journal_seq_cursor: int | None = None
    ) -> SimulationSnapshot:
        self._require(session_id)
        if journal_seq_cursor is not None:
            if not isinstance(journal_seq_cursor, int) or isinstance(
                journal_seq_cursor, bool
            ):
                raise TypeError(
                    "journal_seq_cursor must be int or None, got "
                    f"{type(journal_seq_cursor).__name__}"
                )
            if journal_seq_cursor < 0:
                raise ValueError(
                    f"journal_seq_cursor must be >= 0, got {journal_seq_cursor}"
                )
        # 只读命令不持命令锁：the whole read below is one synchronous block
        # with no await, so the event loop cannot interleave a mutating
        # command inside it — the view is consistent by construction
        # (SPEC-200 section 7 item 1).
        session = self._sessions[session_id]
        view = self._view(session)
        return SimulationSnapshot(
            session_id=view.session_id,
            revision=view.revision,
            lifecycle=view.lifecycle,
            virtual_time_ns=view.virtual_time_ns,
            topology_revision=view.topology_revision,
            node_states=view.node_states,
            connection_states=tuple(
                ConnectionView(
                    connection_id=link.connection_id,
                    from_node=link.from_node,
                    from_port=link.from_port,
                    to_node=link.to_node,
                    to_port=link.to_port,
                )
                for link in session.graph.connections
            ),
            active_faults=view.active_faults,
            latest_artifact_refs=view.latest_artifact_refs,
            journal_seq_cursor=journal_seq_cursor,
        )

    # --- run dimension (SPEC-203 / SIM-D #43 seam) ------------------------------

    async def start_run(
        self, session_id: str, *, run_id: str | None = None
    ) -> RunView:
        """Open a run in a RUNNING session and emit ``run_started``.

        Minimal producer-side run registry: the runtime records run
        identity/lifecycle so the §7.4 run_* obligation can be met; run
        execution itself is the SPEC-203 adapter's concern (SIM-D).
        """
        session = self._require(session_id)
        async with session.lock:
            if session.lifecycle is not LifecycleState.RUNNING:
                raise ValueError(
                    f"session {session_id} is "
                    f"{session.lifecycle.value!r}; runs require a RUNNING "
                    "session (start the session first)"
                )
            effective_run_id = run_id or str(uuid.uuid4())
            if effective_run_id in session.runs:
                raise ValueError(
                    f"run_id {effective_run_id!r} already exists in session "
                    f"{session_id}; run identity is unique per session"
                )
            run_view = RunView(
                run_id=effective_run_id,
                state="running",
                started_virtual_ns=session.clock.now_ns(),
            )
            session.runs[effective_run_id] = run_view
            self._emit_run_event(
                "simulation.run_started", session, effective_run_id
            )
            return run_view

    async def report_run_progress(
        self,
        session_id: str,
        run_id: str,
        progress: Mapping[str, Any],
    ) -> None:
        """Emit ``run_progress`` (coalescable per SPEC-301 §5)."""
        session = self._require(session_id)
        async with session.lock:
            self._require_live_run(session, run_id)
            self._emit_run_event(
                "simulation.run_progress",
                session,
                run_id,
                payload={"run_id": run_id, "progress": dict(progress)},
            )

    async def complete_run(
        self,
        session_id: str,
        run_id: str,
        *,
        artifacts: tuple[ArtifactRef, ...] = (),
    ) -> RunView:
        """Close a run as completed; emits ``run_completed`` and appends
        artifact references (values come from #42/#43, never paths)."""
        session = self._require(session_id)
        async with session.lock:
            run_view = self._require_live_run(session, run_id)
            closed = RunView(
                run_id=run_view.run_id,
                state="completed",
                started_virtual_ns=run_view.started_virtual_ns,
                ended_virtual_ns=session.clock.now_ns(),
            )
            session.runs[run_id] = closed
            if artifacts:
                session.latest_artifact_refs = (
                    session.latest_artifact_refs + tuple(artifacts)
                )
            self._emit_run_event(
                "simulation.run_completed", session, run_id
            )
            return closed

    async def fail_run(
        self, session_id: str, run_id: str, *, reason: str
    ) -> RunView:
        """Close a run as failed; emits ``run_failed`` (severity error)."""
        session = self._require(session_id)
        async with session.lock:
            run_view = self._require_live_run(session, run_id)
            closed = RunView(
                run_id=run_view.run_id,
                state="failed",
                started_virtual_ns=run_view.started_virtual_ns,
                ended_virtual_ns=session.clock.now_ns(),
            )
            session.runs[run_id] = closed
            self._emit_run_event(
                "simulation.run_failed",
                session,
                run_id,
                payload={"run_id": run_id, "reason": reason},
                severity="error",
            )
            return closed

    def emit_fault_event(
        self,
        session_id: str,
        run_id: str,
        event_type: str,
        *,
        fault_id: str,
        fault_type: str,
        target_node_id: str | None,
        target_pid: int | None,
        payload=None,
        severity: str = "info",
    ) -> None:
        """Emit one ``fault.*`` lifecycle event on this session's clock
        (ticket #56, SPEC-204 §8/§9 real-emission seam).

        Public additive face next to the run face: the SPEC-203 TS runtime
        calls it at the fault execution points (prepare-passed plan binding,
        activation crossing, applied confirmation, window close). Read-only
        emission — it never mutates session state and takes no command lock
        (SPEC-200 section 7 item 1 reserves the lock for mutating
        commands); the virtual-time anchor is this session's clock.
        Unknown sessions raise :class:`SessionNotFoundError` (no silent
        drops for a DELIVERY_PROTECTED family).
        """
        session = self._require(session_id)
        self._emitter.fault_event(
            event_type,
            session_id,
            run_id,
            virtual_time_ns=session.clock.now_ns(),
            fault_id=fault_id,
            fault_type=fault_type,
            target_node_id=target_node_id,
            target_pid=target_pid,
            payload=payload,
            severity=severity,
        )

    def emit_generation_event(
        self,
        session_id: str,
        run_id: str,
        event_type: str,
        *,
        payload=None,
        severity: str = "info",
    ) -> None:
        """Emit one run-scoped generation event on this session's clock
        (ticket #128 — the layered pipeline's ``gen.*`` / ``t2mi.*`` /
        ``bbframe.*`` / ``biss.*`` emission face, SPEC-303 §Phase2).

        Same posture as :meth:`emit_fault_event`: read-only emission, no
        command lock, run-scoped attribution; the envelope path is the
        shared emitter (ADR-0006 — no fourth envelope), whose
        unregistered-type guard (ruling §10-7) skips the Phase 2 types
        until #129 lands their registry entries.
        """
        session = self._require(session_id)
        self._emitter.run_event(
            event_type,
            session_id,
            run_id,
            virtual_time_ns=session.clock.now_ns(),
            payload=payload,
            severity=severity,
        )

    # --- internals --------------------------------------------------------------

    def _require(self, session_id: str) -> _Session:
        session = self._sessions.get(session_id)
        if session is None:
            raise SessionNotFoundError(
                f"session_id {session_id!r} does not exist on this runtime"
            )
        return session

    def _require_live_run(self, session: _Session, run_id: str) -> RunView:
        run_view = session.runs.get(run_id)
        if run_view is None:
            raise ValueError(
                f"run_id {run_id!r} does not exist in session "
                f"{session.spec.session_id}"
            )
        if run_view.state != "running":
            raise ValueError(
                f"run {run_id!r} in session {session.spec.session_id} is "
                f"{run_view.state!r}; only a running run can be reported on"
            )
        return run_view

    def _transition(self, session: _Session, target: LifecycleState) -> None:
        """Commit one transition: state + strictly monotonic revision.

        Caller holds the session lock and has passed ``require_transition``.
        """
        session.lifecycle = target
        session.revision += 1

    def _view(self, session: _Session) -> SessionView:
        return SessionView(
            session_id=session.spec.session_id,
            revision=session.revision,
            lifecycle=session.lifecycle,
            virtual_time_ns=session.clock.now_ns(),
            topology_revision=session.graph.revision,
            node_states=session.node_states,
            active_faults=(),
            latest_artifact_refs=session.latest_artifact_refs,
        )

    async def _drain_tasks(self, session: _Session) -> bool:
        """Cancel owned tasks; bounded graceful pass, then forced cancel.

        Returns True when the forced (timeout escalation) path was needed —
        the stop event payload carries it (SPEC-200 section 7 item 5).
        """
        tasks = set(session.tasks)
        if not tasks:
            return False
        for task in tasks:
            task.cancel()
        done, pending = await asyncio.wait(
            tasks, timeout=self._shutdown_timeout_s
        )
        if not pending:
            await asyncio.gather(*done, return_exceptions=True)
            return False
        # Shutdown timeout exhausted: escalate to forced cancellation and
        # let the event payload annotate it (section 7 item 5).
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        return True

    def _emit_session_event(
        self, event_type: str, session: _Session, extra_payload=None
    ) -> None:
        """One session_* envelope per committed transition (§7.4 item 4).

        Called while holding the session lock and AFTER the transition is
        committed, so the emission order matches the transition order
        (event-stream / snapshot consistency, section 11 risk note).
        """
        self._emitter.session_event(
            event_type,
            session.spec.session_id,
            virtual_time_ns=session.clock.now_ns(),
            lifecycle=session.lifecycle,
            extra_payload=extra_payload,
        )

    def _emit_run_event(
        self,
        event_type: str,
        session: _Session,
        run_id: str,
        *,
        payload=None,
        severity: str = "info",
    ) -> None:
        self._emitter.run_event(
            event_type,
            session.spec.session_id,
            run_id,
            virtual_time_ns=session.clock.now_ns(),
            payload=payload,
            severity=severity,
        )
