"""Shared REST test stack — composition root for the SPEC-500 §4 routes
(ticket #48).

The #49 ``ws_stack.py`` posture for the REST surface: the route modules
(``api.routes``) are structural — ports in, application-error categories
out — because import-linter C6 pins ``api`` to ``application``-only
imports. This module is the composition seam that binds the real backends:

- sessions port → the #41 ``SimulationRuntime`` (SPEC-200 lifecycle);
- runs port → the #43 ``TSRuntime`` (prepare + bounded-worker execution)
  with the run face through a run-id allocating shim (the 202 ``run_id``
  is the same identity the session run registry and the ``run_*`` events
  carry);
- artifacts port → the #42 ``ArtifactStore`` + ``SqliteArtifactRepository``
  (read boundary: ``read_by_artifact``, 404 / corruption semantics).

Domain error translation lives here (composition-root concern): the
simulation/adapters exception families are mapped onto the application
categories with their registry codes, and ``api.errors`` renders the
SPEC-500 §6 rows.

Fault-filter note: the production filter belongs to #44 (in flight); the
stack wires a slot-preserving identity filter so the tee path can execute
end-to-end. Fault *transformation semantics* are not this ticket's face.

Bytes discipline (tests/README.md §5): every TS byte comes from the real
SPEC-108 generator via ``tests.unit.simulation._ts_runtime_builders``.
"""

from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import json
import uuid
from pathlib import Path
from typing import Any, Callable

from adapters.storage import db
from adapters.storage.artifact_store import ArtifactStore
from adapters.storage.artifact_errors import (
    ArtifactCorruptError,
    ArtifactNotFoundError,
)
from adapters.storage.errors import StorageUnavailableError
from adapters.storage.repositories import SqliteArtifactRepository
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
)
from simulation.runtime import ValidationReport
from simulation.state import TopologyGraph
from simulation.ts_runtime import (
    StoreArtifactSink,
    TSConfigInvalidError,
    TSPlanInvalidError,
    TSRuntime,
)
from ts.generator.config import GeneratorConfig
from ts.packet import TSPacket

from api.app import create_app
from api.dto.artifacts import ArtifactMetaDTO
from api.dto.faults import FaultDefinitionDTO
from api.dto.generator import GeneratorConfigDTO
from api.dto.runs import (
    RunAcceptedDTO,
    RunArtifactDTO,
    RunStatusDTO,
    RunSubmitRequest,
)
from api.dto.sessions import (
    CreateSessionRequest,
    SessionValidationDTO,
    SessionViewDTO,
    SnapshotDTO,
)
from api.routes import build_spec500_routers
from application.errors import (
    ConflictError,
    NotFoundError,
    SemanticValidationError,
    ServiceUnavailableError,
)
from tests._support.sqlite_support import apply_sql_migrations, default_migrations_dir
from tests.unit.simulation._ts_runtime_builders import make_generator_config


@dataclasses.dataclass
class RestStack:
    """Everything a REST integration test needs in one handle."""

    app: Any
    sessions_backend: "SimulationSessionsBackend"
    runs_backend: "SimulationRunsBackend"
    artifacts_backend: "ArtifactStoreBackend"
    runtime: SimulationRuntime
    ts_runtime: TSRuntime
    store: ArtifactStore
    repository: SqliteArtifactRepository
    session_specs: dict[str, SimulationSessionSpec]


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
        violations = [
            {"code": v.code, "path": v.path, "message": v.message}
            for v in getattr(report, "violations", ())
        ]
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


class SimulationSessionsBackend:
    """``SessionsPort`` over the #41 ``SimulationRuntime``."""

    def __init__(
        self,
        runtime: SimulationRuntime,
        topology_provider: Callable[[str, int], TopologyGraph],
        session_specs: dict[str, SimulationSessionSpec],
    ) -> None:
        self._runtime = runtime
        self._topology_provider = topology_provider
        self._session_specs = session_specs

    async def create(self, request: CreateSessionRequest) -> SessionViewDTO:
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
    """One async-generation job tracked by the runs port."""

    __slots__ = ("task", "session_id", "config_hash")

    def __init__(self, task: asyncio.Task, session_id: str, config_hash: str) -> None:
        self.task = task
        self.session_id = session_id
        self.config_hash = config_hash


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
    ) -> None:
        self._ts_runtime = ts_runtime
        self._runtime = runtime
        self._session_specs = session_specs
        self._sink = sink
        self._allocator = allocator
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
            task=task, session_id=session_id, config_hash=prepared.config_hash
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


# --- the stack ----------------------------------------------------------------------


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


def build_rest_stack(
    root: Path,
    *,
    topology_provider: Callable[[str, int], TopologyGraph] | None = None,
    filter_factory: Any = None,
) -> RestStack:
    """Compose the full SPEC-500 §4 app over the real M3 backends."""
    # check_same_thread=False: the #43 bounded-worker pool writes the tee
    # legs from its worker threads (same posture as the ws_stack journal).
    connection = db.connect(root / "rest-api.sqlite3", check_same_thread=False)
    apply_sql_migrations(connection, default_migrations_dir())
    repository = SqliteArtifactRepository(connection)
    store = ArtifactStore(root / "artifacts", index=repository)
    sink = StoreArtifactSink(store, index=repository)

    runtime = SimulationRuntime()
    session_specs: dict[str, SimulationSessionSpec] = {}
    sessions_backend = SimulationSessionsBackend(
        runtime,
        topology_provider or default_topology_provider,
        session_specs,
    )
    allocator = RunIdAllocator(runtime)
    ts_runtime = TSRuntime(
        runtime=allocator,  # structural shim: duck-types the run face
        filter_factory=filter_factory or (lambda plan, config: IdentityFaultFilter()),
    )
    runs_backend = SimulationRunsBackend(
        ts_runtime, runtime, session_specs, sink, allocator
    )
    artifacts_backend = ArtifactStoreBackend(store, repository)

    app = create_app(
        *build_spec500_routers(
            sessions_port=sessions_backend,
            runs_port=runs_backend,
            artifacts_port=artifacts_backend,
        )
    )
    return RestStack(
        app=app,
        sessions_backend=sessions_backend,
        runs_backend=runs_backend,
        artifacts_backend=artifacts_backend,
        runtime=runtime,
        ts_runtime=ts_runtime,
        store=store,
        repository=repository,
        session_specs=session_specs,
    )
