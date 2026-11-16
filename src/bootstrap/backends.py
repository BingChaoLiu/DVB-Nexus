"""Production SPEC-500 port backends — the composition-root adapters
(ticket #53, 裁定 1d: rest_stack 生产化; ticket #80: the scenario-session
branch + the TSDuck call-records face).

These classes are the REAL bindings of the M3-wired ports
(sessions/runs/artifacts) over the #41/#43/#42 backends. They used to live
in the test-only ``tests/integration/api/rest_stack.py``; ticket #53 moves
them into the production composition module so both the production factory
(:func:`bootstrap.app.build_production_app`) and the test stack compose the
identical code — the "测试组合根 → 生产组合根" value.

Ticket #80 adds:

- the ``SimulationSessionsBackend.create`` scenario branch: a
  ``CreateSessionRequest.scenario_id`` resolves through the
  :class:`~bootstrap.scenarios.ScenarioRegistry` and rides the #45 loader
  full semantics (``open_scenario_session`` — 加载即建 session, 版本/内容
  哈希钉扎, the VALIDATING double gate); the reconstructed spec lands in
  ``session_specs`` so the runs seam accepts scenario sessions, and the
  session-creation hook (observation plane) fires as on the plain path;
- ``TSDuckCallsBackend`` — the SPEC-500 §4.8 read face over the call
  store, with the ``GET .../diagnoses`` existence semantics (no stored
  rows AND an empty journal → 404 unknown session).

Domain error translation lives here too (composition-root concern): the
simulation/adapters exception families map onto the application categories
with their registry codes, and ``api.errors`` renders the SPEC-500 §6 rows.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
import uuid
from typing import Any, Callable, Optional, Sequence

from adapters.storage.artifact_store import ArtifactStore
from adapters.storage.artifact_errors import (
    ArtifactCorruptError,
    ArtifactNotFoundError,
)
from adapters.storage.errors import StorageUnavailableError
from adapters.storage.journal import SqliteEventJournal
from adapters.storage.repositories import SqliteArtifactRepository
from adapters.storage.tsduck_calls import (
    TSDuckCallRecord as StoredTSDuckCallRecord,
    SqliteTSDuckCallStore,
)
from simulation.clock import SimulationClockConfig
from simulation.errors import (
    InvalidLifecycleTransitionError,
    SessionNotFoundError,
    SimulationValidationError,
)
from simulation.runtime import (
    ResourceLimits,
    SimulationRuntime,
    SimulationSessionSpec,
    SimulationSnapshot,
    SessionView,
    ValidationReport,
)
from simulation.scenario.loader import open_scenario_session
from simulation.scenario.schema import ScenarioSchemaInvalidError
from simulation.state import TopologyGraph
from simulation.ts_runtime import (
    StoreArtifactSink,
    TSConfigInvalidError,
    TSPlanInvalidError,
    TSRuntime,
)
from ts.generator.config import GeneratorConfig

from api.dto.artifacts import ArtifactMetaDTO
from api.dto.faults import FaultDefinitionDTO
from api.dto.generator import GeneratorConfigDTO
from api.dto.runs import (
    RunAcceptedDTO,
    RunArtifactDTO,
    RunListItemDTO,
    RunStatusDTO,
    RunSubmitRequest,
)
from api.dto.scenarios import ScenarioSummaryDTO
from api.dto.sessions import (
    CreateSessionRequest,
    SessionDetailDTO,
    SessionListItemDTO,
    SessionValidationDTO,
    SessionViewDTO,
    SnapshotDTO,
)
from api.dto.tsduck_calls import TSDuckCallDTO, tsduck_call_dto
from application.errors import (
    ConflictError,
    NotFoundError,
    SemanticValidationError,
    ServiceUnavailableError,
)


from bootstrap.scenarios import translate_scenario_error


# --- error translation (composition-root concern) -------------------------------


def _translate_simulation_error(exc: Exception) -> Exception:
    """Simulation adapter families → application error categories."""
    if isinstance(exc, SessionNotFoundError):
        return NotFoundError("SIM_SESSION_NOT_FOUND", str(exc))
    if isinstance(exc, InvalidLifecycleTransitionError):
        allowed = [
            str(getattr(item, "value", item)) for item in (exc.allowed or ())
        ]
        return ConflictError(
            "SIM_INVALID_LIFECYCLE_TRANSITION",
            str(exc),
            details={
                "current": str(getattr(exc.current, "value", exc.current)),
                "target": str(getattr(exc.target, "value", exc.target)),
                "allowed": allowed,
            },
        )
    if isinstance(exc, SimulationValidationError):
        report = exc.report
        violations = []
        for v in getattr(report, "violations", ()):
            if isinstance(v, str):
                # The scenario VALIDATING gate (ticket #45) reports plain
                # path-addressed strings —
                # "SIM_SCENARIO_FAULT_PLAN_INVALID: fault_plan[0].…: …".
                # The leading token is the registry code; the full string
                # stays the message so the path-addressed detail survives.
                violations.append(
                    {"code": v.split(":", 1)[0], "path": "", "message": v}
                )
            else:
                violations.append(
                    {"code": v.code, "path": v.path, "message": v.message}
                )
        return SemanticValidationError(
            "SIM_VALIDATION_FAILED", str(exc), details={"violations": violations}
        )
    # Remaining runtime ValueErrors are lifecycle guards (runs require a
    # RUNNING session, duplicate identities) — the 409 row.
    return ConflictError("SIM_INVALID_LIFECYCLE_TRANSITION", str(exc))


# --- sessions port over the #41 runtime ------------------------------------------


def _view_to_dto(view: SessionView) -> SessionViewDTO:
    return SessionViewDTO(
        session_id=view.session_id,
        revision=view.revision,
        lifecycle=str(getattr(view.lifecycle, "value", view.lifecycle)),
        virtual_time_ns=view.virtual_time_ns,
        topology_revision=view.topology_revision,
        node_states={
            node_id: {
                "node_id": state.node_id,
                "health": str(getattr(state.health, "value", state.health)),
                "ports": [
                    {
                        "port_id": port.port_id,
                        "health": str(getattr(port.health, "value", port.health)),
                    }
                    for port in state.ports
                ],
            }
            for node_id, state in view.node_states.items()
        },
        active_faults=[
            {"fault_id": fault.fault_id, "state": fault.state}
            for fault in view.active_faults
        ],
        latest_artifact_refs=[
            {
                "artifact_id": ref.artifact_id,
                "kind": ref.kind,
                "status": ref.status,
            }
            for ref in view.latest_artifact_refs
        ],
    )


def _snapshot_to_dto(snapshot: SimulationSnapshot) -> SnapshotDTO:
    base = _view_to_dto(
        SessionView(
            session_id=snapshot.session_id,
            revision=snapshot.revision,
            lifecycle=snapshot.lifecycle,
            virtual_time_ns=snapshot.virtual_time_ns,
            topology_revision=snapshot.topology_revision,
            node_states=snapshot.node_states,
            active_faults=snapshot.active_faults,
            latest_artifact_refs=snapshot.latest_artifact_refs,
        )
    )
    connections = [
        {
            "connection_id": link.connection_id,
            "from_node": link.from_node,
            "from_port": link.from_port,
            "to_node": link.to_node,
            "to_port": link.to_port,
        }
        for link in snapshot.connection_states
    ]
    return SnapshotDTO(
        **base.model_dump(),
        connection_states=connections,
        journal_seq_cursor=snapshot.journal_seq_cursor,
    )


class _SessionMetaRecord:
    """Session-level provenance metadata (SPEC-408 §6.1/§6.2, ticket #94).

    Recorded by the composition layer at creation — the frozen
    ``SimulationSessionSpec`` stays untouched (no wall clock, no scenario
    id). ``created_at_ms`` is wall clock at the successful create;
    ``scenario_id`` closes the write-only provenance gap (the create
    request consumed the id and dropped it). Popped on dispose so the
    list face answers only LIVE sessions.
    """

    __slots__ = ("created_at_ms", "scenario_id")

    def __init__(self, created_at_ms: int, scenario_id: str | None) -> None:
        self.created_at_ms = created_at_ms
        self.scenario_id = scenario_id


def _default_now_ms() -> int:
    return time.time_ns() // 1_000_000


class SimulationSessionsBackend:
    """``SessionsPort`` over the #41 ``SimulationRuntime``.

    The ``scenario_id`` consumption branch (ticket #80 scope item 2): when
    the request names a scenario, the document governs — the #45 loader
    opens the session from the scenario's own initial_topology / seed /
    clock / deterministic flag (加载即建, SPEC-205 §5; the request's
    topology/seed/clock fields are permissive-ignored, orchestrator
    OQ-6 — the DTO docstring + the #67 downstream contract document this
    loudly). Everything else rides the plain path byte-identically.
    """

    def __init__(
        self,
        runtime: SimulationRuntime,
        topology_provider: Callable[[str, int], TopologyGraph],
        session_specs: dict[str, SimulationSessionSpec],
        on_session_created: Callable[[str], None] | None = None,
        scenario_registry: Any = None,
        now_ms: Optional[Callable[[], int]] = None,
    ) -> None:
        self._runtime = runtime
        self._topology_provider = topology_provider
        self._session_specs = session_specs
        self._on_session_created = on_session_created
        self._scenario_registry = scenario_registry
        # SPEC-408 §6 metadata clock (ticket #94): injectable for
        # deterministic ordering tests; default is wall clock in ms.
        self._now_ms = now_ms or _default_now_ms
        self._session_meta: dict[str, _SessionMetaRecord] = {}

    async def create(self, request: CreateSessionRequest) -> SessionViewDTO:
        if request.scenario_id is not None and self._scenario_registry is not None:
            return await self._create_scenario_session(request)
        clock = SimulationClockConfig(
            mode=request.clock_config.mode,
            start_time_ns=request.clock_config.start_time_ns,
            speed_num=request.clock_config.speed_num,
            speed_den=request.clock_config.speed_den,
            tick_quantum_ns=request.clock_config.tick_quantum_ns,
        )
        limits = (
            ResourceLimits(
                bitrate_bps=request.resource_limits.bitrate_bps,
                memory_bytes=request.resource_limits.memory_bytes,
                duration_ns=request.resource_limits.duration_ns,
            )
            if request.resource_limits is not None
            else ResourceLimits()
        )
        graph = self._topology_provider(
            request.topology_id, request.topology_revision
        )
        spec = SimulationSessionSpec(
            session_id=str(uuid.uuid4()),
            topology=graph,
            seed=request.seed,
            deterministic=request.deterministic,
            clock_config=clock,
            resource_limits=limits,
        )
        self._session_specs[spec.session_id] = spec
        try:
            view = await self._runtime.create_session(spec)
        except Exception as exc:
            self._session_specs.pop(spec.session_id, None)
            raise _translate_simulation_error(exc) from exc
        # SPEC-408 §6 provenance record (ticket #94): wall clock at the
        # successful create + the request's scenario binding.
        self._session_meta[spec.session_id] = _SessionMetaRecord(
            created_at_ms=self._now_ms(), scenario_id=request.scenario_id
        )
        if self._on_session_created is not None:
            self._on_session_created(spec.session_id)
        return _view_to_dto(view)

    async def _create_scenario_session(
        self, request: CreateSessionRequest
    ) -> SessionViewDTO:
        """The #45 loader full semantics over a registry document.

        open_scenario_session: parse (registry documents re-parse from
        their normalized raw mapping — valid by construction) → new
        session (CREATED, fresh uuid4) → VALIDATING (the #41 topology
        gate + the scenario fault-plan gate) → READY/FAILED. The
        reconstructed spec lands in ``session_specs`` (equal-valued, not
        loader-internal identity — ``prepare`` reads fields) so the runs
        seam accepts scenario sessions, and the creation hook attaches
        the observation plane exactly as on the plain path.
        """
        document = self._scenario_registry.require(request.scenario_id)
        try:
            binding = await open_scenario_session(self._runtime, document.raw)
        except Exception as exc:
            translated = translate_scenario_error(exc)
            if translated is not None:
                raise translated from exc
            raise _translate_simulation_error(exc) from exc
        spec = SimulationSessionSpec(
            session_id=binding.session_id,
            topology=binding.document.topology,
            seed=binding.document.seed,
            deterministic=binding.document.deterministic,
            clock_config=binding.document.clock_config,
        )
        self._session_specs[spec.session_id] = spec
        # SPEC-408 §6 provenance record (ticket #94): the DOCUMENT's
        # scenario id is the authoritative binding (the request echoed it).
        self._session_meta[spec.session_id] = _SessionMetaRecord(
            created_at_ms=self._now_ms(),
            scenario_id=binding.document.scenario_id,
        )
        if self._on_session_created is not None:
            self._on_session_created(spec.session_id)
        view = SessionView(
            session_id=binding.snapshot.session_id,
            revision=binding.snapshot.revision,
            lifecycle=binding.snapshot.lifecycle,
            virtual_time_ns=binding.snapshot.virtual_time_ns,
            topology_revision=binding.snapshot.topology_revision,
            node_states=binding.snapshot.node_states,
            active_faults=binding.snapshot.active_faults,
            latest_artifact_refs=binding.snapshot.latest_artifact_refs,
        )
        return _view_to_dto(view)

    async def validate_session(self, session_id: str) -> SessionValidationDTO:
        try:
            report: ValidationReport = await self._runtime.validate_session(
                session_id
            )
        except Exception as exc:
            raise _translate_simulation_error(exc) from exc
        return SessionValidationDTO(
            ok=report.ok,
            violations=[
                {"code": v.code, "path": v.path, "message": v.message}
                for v in report.violations
            ],
        )

    async def _command(self, session_id: str, command: str) -> SessionViewDTO:
        try:
            view = await getattr(self._runtime, command)(session_id)
        except Exception as exc:
            raise _translate_simulation_error(exc) from exc
        return _view_to_dto(view)

    async def start(self, session_id: str) -> SessionViewDTO:
        return await self._command(session_id, "start")

    async def pause(self, session_id: str) -> SessionViewDTO:
        return await self._command(session_id, "pause")

    async def resume(self, session_id: str) -> SessionViewDTO:
        return await self._command(session_id, "resume")

    async def stop(self, session_id: str) -> SessionViewDTO:
        return await self._command(session_id, "stop")

    async def dispose(self, session_id: str) -> None:
        try:
            await self._runtime.dispose(session_id)
        except Exception as exc:
            raise _translate_simulation_error(exc) from exc
        # The session no longer exists — the §6.1 list face must not
        # answer with it (the metadata record is the list's live set).
        self._session_meta.pop(session_id, None)

    async def snapshot(
        self, session_id: str, *, journal_seq_cursor: int | None
    ) -> SnapshotDTO:
        try:
            snapshot = await self._runtime.get_snapshot(
                session_id, journal_seq_cursor=journal_seq_cursor
            )
        except Exception as exc:
            raise _translate_simulation_error(exc) from exc
        return _snapshot_to_dto(snapshot)

    async def list_sessions(self, *, limit: int) -> list[SessionListItemDTO]:
        """The SPEC-408 §6.1 read face (ticket #94): newest-first, capped
        by ``limit``, no pagination.

        Ordering rides the creation metadata (a stable sort keeps creation
        order among equal stamps); ``lifecycle``/``topology_revision`` are
        LIVE runtime values read per row. A session disposed between the
        sort and its snapshot read is skipped — it vanished mid-list.
        """
        records = sorted(
            self._session_meta.items(),
            key=lambda item: item[1].created_at_ms,
            reverse=True,
        )[:limit]
        items: list[SessionListItemDTO] = []
        for session_id, record in records:
            try:
                snapshot = await self._runtime.get_snapshot(session_id)
            except Exception as exc:
                translated = _translate_simulation_error(exc)
                if isinstance(translated, NotFoundError):
                    continue
                raise translated from exc
            items.append(
                SessionListItemDTO(
                    session_id=session_id,
                    lifecycle=str(
                        getattr(snapshot.lifecycle, "value", snapshot.lifecycle)
                    ),
                    created_at_ms=record.created_at_ms,
                    scenario_id=record.scenario_id,
                    topology_revision=snapshot.topology_revision,
                )
            )
        return items

    async def get_session_detail(
        self, session_id: str
    ) -> SessionDetailDTO | None:
        """The SPEC-408 §6.2 read face (ticket #94): the existing view
        shape plus the provenance pair. ``None`` renders the uniform 404
        (SPEC-500 §6 row 404)."""
        try:
            snapshot = await self._runtime.get_snapshot(session_id)
        except Exception as exc:
            raise _translate_simulation_error(exc) from exc
        record = self._session_meta.get(session_id)
        if record is None:
            # Composition invariant: every live session visible through
            # this backend recorded its metadata at create time. A miss
            # means the session was created outside this face — the first
            # metadata observation is the honest fallback (no fabrication
            # of a false creation moment beyond the observed-at stamp).
            record = _SessionMetaRecord(
                created_at_ms=self._now_ms(), scenario_id=None
            )
        base = _view_to_dto(
            SessionView(
                session_id=snapshot.session_id,
                revision=snapshot.revision,
                lifecycle=snapshot.lifecycle,
                virtual_time_ns=snapshot.virtual_time_ns,
                topology_revision=snapshot.topology_revision,
                node_states=snapshot.node_states,
                active_faults=snapshot.active_faults,
                latest_artifact_refs=snapshot.latest_artifact_refs,
            )
        )
        return SessionDetailDTO(
            **base.model_dump(),
            scenario_id=record.scenario_id,
            created_at_ms=record.created_at_ms,
        )


# --- runs port over the #43 TS runtime --------------------------------------------


class RunIdAllocator:
    """Run-face shim: the 202 ``run_id`` is the run-face run identity.

    ``TSRuntime.run`` opens the run itself through
    ``runtime.start_run(session_id)``; the shim hands it the run id the
    REST layer already staged at submit time, so the 202 answer, the
    session run registry and the ``run_*`` events share one identity.
    Everything else delegates straight through.
    """

    def __init__(self, runtime: SimulationRuntime) -> None:
        self._runtime = runtime
        self._staged: dict[str, str] = {}

    def stage(self, session_id: str, run_id: str) -> None:
        self._staged[session_id] = run_id

    async def start_run(self, session_id: str) -> Any:
        run_id = self._staged.pop(session_id, None)
        return await self._runtime.start_run(session_id, run_id=run_id)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._runtime, name)


class _JobRecord:
    """One async-generation job tracked by the runs port.

    The SPEC-408 §6.3 read-back pair rides the record (ticket #94):
    ``submitted_at_ms`` is wall clock at submission (injectable clock);
    ``fault_plan_present`` mirrors whether the request carried a non-empty
    plan.
    """

    __slots__ = (
        "task",
        "session_id",
        "config_hash",
        "submitted_at_ms",
        "fault_plan_present",
    )

    def __init__(
        self,
        task: asyncio.Task,
        session_id: str,
        config_hash: str,
        submitted_at_ms: int,
        fault_plan_present: bool,
    ) -> None:
        self.task = task
        self.session_id = session_id
        self.config_hash = config_hash
        self.submitted_at_ms = submitted_at_ms
        self.fault_plan_present = fault_plan_present


class IdentityFaultFilter:
    """Slot-preserving identity filter (#44 supplies the production one).

    The tee path needs *a* filter to execute; identity is slot-preserving
    (ADR-0007 item 4) and mutation-log shaped, so the REST job completes
    end-to-end without pretending to own fault semantics.
    """

    def apply(self, index: int, packet: TSPacket) -> TSPacket:
        return packet

    def mutation_log(self) -> bytes:
        return json.dumps({"mutations": []}, sort_keys=True).encode("utf-8")


def _config_from_dto(dto: GeneratorConfigDTO) -> GeneratorConfig:
    """SPEC-108 §4 wire shape → the frozen domain dataclass (hex → bytes)."""
    return GeneratorConfig(
        schema_version=dto.schema_version,
        profile=dto.profile,
        deterministic=dto.deterministic,
        seed=dto.seed,
        initial_media_clock_27mhz=dto.initial_media_clock_27mhz,
        target_bitrate_bps=dto.target_bitrate_bps,
        output_packet_count=dto.output_packet_count,
        program=_program_from_dto(dto),
        pat_period_ms=dto.pat_period_ms,
        pmt_period_ms=dto.pmt_period_ms,
        pcr_interval_ms=dto.pcr_interval_ms,
        pcr_insertion_policy=dto.pcr_insertion_policy,
    )


def _program_from_dto(dto: GeneratorConfigDTO) -> Any:
    from ts.generator.config import ProgramConfig

    program = dto.program
    return ProgramConfig(
        transport_stream_id=program.transport_stream_id,
        program_number=program.program_number,
        pmt_pid=program.pmt_pid,
        pcr_pid=program.pcr_pid,
        version_number=program.version_number,
        streams=[_stream_from_dto(s) for s in program.streams],
        program_descriptors=bytes.fromhex(program.program_descriptors),
    )


def _stream_from_dto(stream: Any) -> Any:
    from ts.generator.config import ElementaryStreamConfig

    return ElementaryStreamConfig(
        pid=stream.pid,
        stream_type=stream.stream_type,
        stream_id=stream.stream_id,
        bitrate_bps=stream.bitrate_bps,
        payload_profile=stream.payload_profile,
        payload_seed_offset=stream.payload_seed_offset,
    )


def _fault_from_dto(dto: FaultDefinitionDTO) -> Any:
    """Wire shape → the ``simulation.fault_plan`` seam class (SPEC-204 §3).

    Absent ``fault_id`` is server-generated uuid4 — identity, not
    semantics; it never enters the prepare fingerprint.
    """
    from simulation.fault_plan import FaultActivation, FaultDefinition

    return FaultDefinition(
        fault_id=dto.fault_id or str(uuid.uuid4()),
        fault_type=dto.fault_type,
        target_id=dto.target_id,
        parameters=dict(dto.parameters),
        activation=FaultActivation(
            kind=dto.activation.kind, packet_index=dto.activation.packet_index
        ),
        expected_observations=tuple(dto.expected_observations),
    )


def wire_generator_config(config: GeneratorConfig) -> dict:
    """Domain config → the SPEC-108 §4 wire payload (bytes → hex).

    Test-side inverse of ``_config_from_dto``: the canonical
    ``make_generator_config()`` fixture becomes the REST request body, so
    the DTO mapping is exercised against the frozen domain shapes. Returns
    a plain JSON-able dict (the wire payload for ``json=``).
    """
    program = config.program
    return {
        "schema_version": config.schema_version,
        "profile": config.profile,
        "deterministic": config.deterministic,
        "seed": config.seed,
        "initial_media_clock_27mhz": config.initial_media_clock_27mhz,
        "target_bitrate_bps": config.target_bitrate_bps,
        "output_packet_count": config.output_packet_count,
        "program": {
            "transport_stream_id": program.transport_stream_id,
            "program_number": program.program_number,
            "pmt_pid": program.pmt_pid,
            "pcr_pid": program.pcr_pid,
            "version_number": program.version_number,
            "streams": [
                {
                    "pid": stream.pid,
                    "stream_type": stream.stream_type,
                    "stream_id": stream.stream_id,
                    "bitrate_bps": stream.bitrate_bps,
                    "payload_profile": stream.payload_profile,
                    "payload_seed_offset": stream.payload_seed_offset,
                }
                for stream in program.streams
            ],
            "program_descriptors": program.program_descriptors.hex(),
        },
        "pat_period_ms": config.pat_period_ms,
        "pmt_period_ms": config.pmt_period_ms,
        "pcr_interval_ms": config.pcr_interval_ms,
        "pcr_insertion_policy": config.pcr_insertion_policy,
    }


class SimulationRunsBackend:
    """``RunsPort`` over the #43 ``TSRuntime`` (prepare-bound async jobs)."""

    def __init__(
        self,
        ts_runtime: TSRuntime,
        runtime: SimulationRuntime,
        session_specs: dict[str, SimulationSessionSpec],
        sink: StoreArtifactSink,
        allocator: RunIdAllocator,
        now_ms: Optional[Callable[[], int]] = None,
    ) -> None:
        self._ts_runtime = ts_runtime
        self._runtime = runtime
        self._session_specs = session_specs
        self._sink = sink
        self._allocator = allocator
        # SPEC-408 §6 metadata clock (ticket #94): injectable for
        # deterministic ordering tests; default is wall clock in ms.
        self._now_ms = now_ms or _default_now_ms
        self._jobs: dict[str, _JobRecord] = {}

    async def submit(
        self, session_id: str, request: RunSubmitRequest
    ) -> RunAcceptedDTO:
        spec = self._session_specs.get(session_id)
        if spec is None:
            raise NotFoundError(
                "SIM_SESSION_NOT_FOUND",
                f"unknown session {session_id!r}; the fault plan binds at "
                "prepare (AC-204-01) so nothing was scheduled",
            )
        # Synchronous lifecycle gate: the 202 must never precede a run face
        # rejection that is knowable now — runs open only in a RUNNING
        # session (SPEC-200 run face). The authoritative gate stays
        # runtime.start_run inside the scheduled task.
        snapshot = await self._runtime.get_snapshot(session_id)
        lifecycle = str(getattr(snapshot.lifecycle, "value", snapshot.lifecycle))
        if lifecycle != "running":
            raise ConflictError(
                "SIM_INVALID_LIFECYCLE_TRANSITION",
                f"session {session_id!r} is {lifecycle!r}; runs require a "
                "RUNNING session (SPEC-200 run face)",
                details={"current": lifecycle, "target": "running"},
            )
        config = _config_from_dto(request.config)
        plan = tuple(_fault_from_dto(fault) for fault in request.fault_plan)
        try:
            # Prepare binds the plan into the fingerprint and validates
            # BEFORE any scheduling (ADR-0007 item 2, AC-204-01).
            prepared = self._ts_runtime.prepare(spec, config, plan)
        except TSPlanInvalidError as exc:
            raise SemanticValidationError(
                "SIM_TS_PLAN_INVALID",
                str(exc),
                details={"errors": list(exc.details)},
            ) from exc
        except TSConfigInvalidError as exc:
            raise SemanticValidationError(
                "SIM_TS_CONFIG_INVALID", str(exc)
            ) from exc
        run_id = str(uuid.uuid4())
        self._allocator.stage(session_id, run_id)
        task = asyncio.create_task(self._ts_runtime.run(prepared, self._sink))
        self._jobs[run_id] = _JobRecord(
            task=task,
            session_id=session_id,
            config_hash=prepared.config_hash,
            submitted_at_ms=self._now_ms(),
            fault_plan_present=bool(request.fault_plan),
        )
        return RunAcceptedDTO(run_id=run_id, config_hash=prepared.config_hash)

    async def get_run(self, session_id: str, run_id: str) -> RunStatusDTO | None:
        job = self._jobs.get(run_id)
        if job is None or job.session_id != session_id:
            return None
        if not job.task.done():
            return RunStatusDTO(
                run_id=run_id, status="running", config_hash=job.config_hash
            )
        exc = job.task.exception()
        if exc is not None:
            translated = _translate_simulation_error(exc)
            code = getattr(translated, "error_code", type(exc).__name__)
            return RunStatusDTO(
                run_id=run_id,
                status="failed",
                config_hash=job.config_hash,
                warnings=[f"{code}: {translated}"],
            )
        result = job.task.result()
        return RunStatusDTO(
            run_id=result.run_id,
            status=result.status,
            config_hash=result.config_hash,
            generator_version=result.generator_version,
            packet_count=result.packet_count,
            byte_count=result.byte_count,
            virtual_duration_ns=result.virtual_duration_ns,
            artifacts=[
                RunArtifactDTO(
                    artifact_id=ref.artifact_id,
                    kind=ref.kind,
                    sha256=ref.sha256,
                    byte_size=ref.byte_size,
                    packet_count=ref.packet_count,
                    partial=ref.partial,
                )
                for ref in result.artifacts
            ],
            warnings=list(result.warnings),
        )

    async def list_runs(self, session_id: str) -> list[RunListItemDTO]:
        """The SPEC-408 §6.3 read face (ticket #94): submission-order ASC
        (the eight-step narrative order), no pagination.

        The bound is pinned here and declared on the ticket: the in-memory
        job registry is process-page-scoped, so the list is the FULL
        registry for the session (no truncation). Unknown session →
        ``SIM_SESSION_NOT_FOUND`` (404); a known session without runs
        answers 200 ``[]``. ``packet_count`` passes through from the
        per-job status face (``None`` while running / on failure).
        """
        if session_id not in self._session_specs:
            raise NotFoundError(
                "SIM_SESSION_NOT_FOUND",
                f"unknown session {session_id!r} (SPEC-200 §6)",
            )
        records = sorted(
            (
                (run_id, job)
                for run_id, job in self._jobs.items()
                if job.session_id == session_id
            ),
            key=lambda pair: pair[1].submitted_at_ms,
        )
        items: list[RunListItemDTO] = []
        for run_id, job in records:
            status = await self.get_run(session_id, run_id)
            # The record owns this session, so the status face cannot miss.
            packet_count = status.packet_count if status is not None else None
            items.append(
                RunListItemDTO(
                    run_id=run_id,
                    status=status.status if status is not None else "running",
                    submitted_at_ms=job.submitted_at_ms,
                    fault_plan_present=job.fault_plan_present,
                    packet_count=packet_count,
                )
            )
        return items


# --- artifacts port over the #42 store ---------------------------------------------


class ArtifactStoreBackend:
    """``ArtifactsPort`` over the #42 read boundary (consume-only)."""

    def __init__(
        self, store: ArtifactStore, repository: SqliteArtifactRepository
    ) -> None:
        self._store = store
        self._repository = repository

    def get_meta(self, artifact_id: str) -> ArtifactMetaDTO | None:
        row = self._repository.get(artifact_id)
        if row is None:
            return None
        return ArtifactMetaDTO(
            artifact_id=row.artifact_id,
            run_id=row.run_id,
            session_id=row.session_id,
            kind=row.kind,
            relative_path=row.relative_path,
            byte_size=row.byte_size,
            sha256=row.sha256,
            packet_size=row.packet_size,
            packet_count=row.packet_count,
            generator_version=row.generator_version,
            config_hash=row.config_hash,
            fault_profile_ids=list(row.fault_profile_ids or ()),
            created_at_utc_ms=row.created_at_utc_ms,
        )

    def read_content(self, artifact_id: str) -> bytes:
        try:
            data = self._store.read_by_artifact(artifact_id)
        except ArtifactNotFoundError as exc:
            raise NotFoundError("PLT_ARTIFACT_NOT_FOUND", str(exc)) from exc
        except ArtifactCorruptError as exc:
            raise ServiceUnavailableError(exc.code, str(exc)) from exc
        except StorageUnavailableError as exc:
            raise ServiceUnavailableError(exc.code, str(exc)) from exc
        # Corruption gate (SPEC-503 §7 row 4): read_by_artifact streams
        # without verify; the index row carries the registered sha256, so
        # the download boundary verifies against it — a mismatch is the
        # OBS_STORAGE_WRITE_FAILURE 503 family, raiser-owned.
        row = self._repository.get(artifact_id)
        if row is not None:
            actual = hashlib.sha256(data).hexdigest()
            if actual != row.sha256:
                corrupt = ArtifactCorruptError(
                    f"stored content digest {actual!r} does not match the "
                    f"registered digest for artifact {artifact_id!r}"
                )
                raise ServiceUnavailableError(corrupt.code, str(corrupt)) from corrupt
        return data



def default_topology_provider(topology_id: str, revision: int) -> TopologyGraph:
    """Resolve known MVP topology ids to the empty deterministic graph."""
    if topology_id != "topo-1":
        raise NotFoundError(
            "SIM_TOPOLOGY_NOT_FOUND",
            f"unknown topology {topology_id!r} (topology persistence "
            "arrives with SPEC-502; the MVP registry carries 'topo-1')",
        )
    return TopologyGraph(
        topology_id=topology_id, revision=revision, nodes=(), connections=()
    )




# --- TSDuck call records (SPEC-500 §4.8, ticket #80) -------------------------------


class TSDuckCallsBackend:
    """The §4.8 read face over the SPEC-308 §7 call-record store.

    Existence semantics mirror ``DiagnosisService.list_diagnoses``: no
    stored rows AND an empty journal for the session → 404 unknown
    session; otherwise the (possibly empty) ``started_at_utc_ms``-ASC
    list. The production stack makes no real TSDuck calls (MVP, 裁定 E) —
    rows arrive through the store's write face (fixture seeding today,
    future emission wiring)."""

    def __init__(
        self,
        store: SqliteTSDuckCallStore,
        journal: SqliteEventJournal,
    ) -> None:
        self._store = store
        self._journal = journal

    def list_calls(
        self, session_id: str, *, run_id: Optional[str] = None
    ) -> list[TSDuckCallDTO]:
        rows: list[StoredTSDuckCallRecord] = self._store.query(
            session_id, run_id=run_id
        )
        if not rows and self._journal.max_seq(session_id) == 0:
            raise NotFoundError(
                "SIM_SESSION_NOT_FOUND",
                f"unknown session {session_id!r}: no stored call records"
                " and no journal events (SPEC-500 §6 row 404)",
            )
        return [tsduck_call_dto(row) for row in rows]
