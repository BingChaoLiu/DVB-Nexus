"""SPEC-203 — L1 TS Runtime integration (SIM_TS orchestration, ticket #43).

SIM_TS assembles the TS Core public contract (SPEC-100~108) into a
controlled deterministic generation run: lifecycle-coupled run identity,
bounded-worker event-loop isolation, bounded-batch cancellation, tee
double-write (ADR-0007 item 2) and artifact correlation. TS serialization
and CC logic are **never** re-implemented here — the Generator
(:class:`ts.generator.generator.TSGenerator`, SPEC-108, #34) owns the
generation chain and stays zero-fault-branch (REQ-TS-108-006): the fault
transformation is a slot-preserving filter *downstream of the
Generator→sink edge*, wired in through the structural
:class:`FaultFilter` seam (the #44 faults package supplies the production
filter; SIM-D owns only the binding and the tee plumbing).

Public face (SPEC-203 §4):

- :class:`TSRuntime` — ``prepare(session, config, fault_plan=())`` /
  ``run(prepared, sink)`` / ``cancel(run_id)``.
- :class:`PreparedTSRun` — frozen, carries the deterministic
  ``config_hash`` fingerprint (§5.1: generator version + effective config
  + seed/initial virtual clock + canonical fault-plan serialization; wall
  clock, session_id, run_id and paths never enter it). The plan binds at
  prepare and is validated there (AC-204-01); ``run()`` takes no plan.
- :class:`TSRunResult` — §5.2: list-form ``artifacts`` with the three
  kinds ``generated_ts`` / ``faulted_ts`` / ``log``, the 188-byte
  invariant counts and the completed/cancelled/failed status.

Artifact landing protocol: the runtime consumes the #42 storage adapter
through the structural :class:`ArtifactSink` port —
:class:`StoreArtifactSink` adapts :class:`adapters.storage.artifact_store.
ArtifactStore` (tmp → atomic rename → 先文件后索引 register; baseline
dedup = SHA-256 content addressing, 引用不复制). The runtime itself never
touches paths (SPEC-203 §2.2 / SPEC-503 §6).

Event-loop isolation (§6 item 2): synchronous generation runs on a
bounded in-process thread pool (MVP thread pool per SPEC-507's
process-selection latitude); submit/collect boundaries are async.
Cancellation (§6 item 3) is checked at bounded batch boundaries — after a
cancel, produced bytes stop growing and landed artifacts are marked
``partial`` (§6 item 4).

Run dimension: when a :class:`simulation.runtime.SimulationRuntime` is
wired, runs open/close through its run face (``start_run`` /
``report_run_progress`` / ``complete_run`` / ``fail_run``), so the SPEC-200
lifecycle state machine gates runs and the §7.4 ``run_*`` emission
obligation is met through #41's emitter (producers never fill
``journal_seq``; no fourth envelope).

Import-contract note (ADR-0005 D4-4): this module imports only
``ts.*`` public surfaces, ``adapters.storage`` (consume-only) and
``simulation.*`` — REQ-SIM-203-001's import whitelist is pinned by a
static test.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from itertools import islice
from typing import Any, Callable, Literal, Mapping, Protocol

from adapters.storage.artifact_errors import ArtifactNotFoundError
from adapters.storage.artifact_store import ArtifactStore, SinkCommit
from faults.errors import SIM_FAULT_EXEC_FAILED, FaultExecutionError
from faults.targets import parse_target_id
from simulation.clock import SimulationClockConfig
from simulation.errors import (
    SIM_TS_CANCELLED,
    SIM_TS_CONFIG_INVALID,
    SIM_TS_GENERATION_FAILED,
    SIM_TS_PLAN_INVALID,
    SIM_TS_SINK_IO_ERROR,
    TSConfigInvalidError,
    TSGenerationFailedError,
    TSPlanInvalidError,
    TSSinkIOError,
    TSWorkerUnavailableError,
)
from simulation.fault_plan import FaultDefinition, validate_fault_plan
from simulation.runtime import ArtifactRef as SessionArtifactRef
from simulation.runtime import SimulationRuntime, SimulationSessionSpec
from ts.canonical_json import canonical_json
from ts.errors import TSCoreError
from ts.generator.config import GeneratorConfig
from ts.generator.generator import GENERATOR_VERSION, TSGenerator

__all__ = [
    "DEFAULT_BATCH_SIZE",
    "DEFAULT_PROGRESS_EVERY_BATCHES",
    "DEFAULT_WORKER_MAX",
    "SIM_TS_CANCELLED",
    "SIM_TS_CONFIG_INVALID",
    "SIM_TS_PLAN_INVALID",
    "ArtifactRef",
    "ArtifactSink",
    "FaultFilter",
    "PreparedTSRun",
    "SinkLeg",
    "StoreArtifactSink",
    "TSRunResult",
    "TSRuntime",
    "TeeLegs",
]

#: Default bounded-batch size: the cancel flag is checked every this many
#: packets (SPEC-203 §6 item 3 — bounded-batch cancellation).
DEFAULT_BATCH_SIZE = 256

#: Default worker-pool width (SPEC-203 §6 item 2: bounded worker; SPEC-507
#: owns the thread-vs-process re-check, ADR-0008 the envelope).
DEFAULT_WORKER_MAX = 2

#: Progress coalescing: one ``run_progress`` emission every this many
#: batches (SPEC-203 §6 item 6 / SPEC-301 §5 合并限流).
DEFAULT_PROGRESS_EVERY_BATCHES = 4

TS_PACKET_SIZE = 188

ARTIFACT_KIND_GENERATED = "generated_ts"
ARTIFACT_KIND_FAULTED = "faulted_ts"
ARTIFACT_KIND_LOG = "log"


# --- SPEC-203 §5 data model -----------------------------------------------------


@dataclass(frozen=True)
class ArtifactRef:
    """Run-dimension artifact reference (SPEC-203 §5.2, exact field set).

    ``kind`` is one of the three tee kinds; ``partial`` is True only for
    cancelled/failed runs' landed artifacts (never complete; a partial
    artifact is never reusable as a baseline, §6 item 4).
    """

    artifact_id: str  # uuid4 opaque (ADR-0006 item 3)
    kind: Literal["generated_ts", "faulted_ts", "log"]
    sha256: str
    byte_size: int
    packet_count: int | None  # required for the two TS kinds
    partial: bool


@dataclass(frozen=True)
class TSRunResult:
    """One run's digest (SPEC-203 §5.2, exact field set).

    ``packet_count`` / ``byte_count`` describe the baseline stream; a tee
    run's faulted stream shares the same packet frame (ADR-0007 item 4,
    slot-preserving), so the counts coincide — the 188 invariant
    ``byte_count == packet_count * 188`` holds for both streams.
    """

    run_id: str
    status: Literal["completed", "cancelled", "failed"]
    packet_count: int
    byte_count: int
    virtual_duration_ns: int
    artifacts: tuple[ArtifactRef, ...]
    warnings: tuple[str, ...]
    generator_version: str
    config_hash: str  # includes the fault-plan fingerprint


@dataclass(frozen=True)
class PreparedTSRun:
    """The frozen prepare answer (SPEC-203 §4/§5.1).

    Repeated ``run(prepared)`` calls produce new runs with the same
    fingerprint (fresh uuid4 ``run_id`` each time). The fault plan is
    bound here and nowhere else; ``fault_id`` uuids are identity, not
    semantics, and do not enter the fingerprint.
    """

    session_id: str
    config: GeneratorConfig
    fault_plan: tuple[FaultDefinition, ...]
    config_hash: str
    generator_version: str


# --- structural ports ------------------------------------------------------------


class SinkLeg(Protocol):
    """One tee leg's write/commit/abort protocol.

    Shape-compatible with :class:`adapters.storage.artifact_store.
    ArtifactWriteSink` (incremental writes, atomic commit, abort) but kept
    structural so unit tests can supply in-memory legs without touching
    the filesystem.
    """

    def write(self, chunk: bytes) -> None: ...

    def commit(self) -> Any: ...  # → Mapping with sha256/byte_size/relative_path

    def abort(self) -> None: ...


class TeeLegs:
    """The per-run legs handed out by :meth:`ArtifactSink.open_legs`.

    ``faulted`` / ``log`` are present only for tee runs (plan non-empty).
    """

    __slots__ = ("baseline", "faulted", "log")

    def __init__(
        self,
        baseline: SinkLeg,
        faulted: SinkLeg | None = None,
        log: SinkLeg | None = None,
    ) -> None:
        self.baseline = baseline
        self.faulted = faulted
        self.log = log


class ArtifactSink(Protocol):
    """The tee landing port (structural; production impl:
    :class:`StoreArtifactSink` over the #42 store).

    The runtime never accepts client filesystem paths — the sink owns the
    physical landing (SPEC-503) and the record registration (SPEC-502
    index). ``find_reusable_baseline`` is the record-level dedup hook
    (SPEC-203 §5.2 基线去重: same fingerprint + same bytes → reuse the
    existing artifact record).
    """

    def open_legs(self, *, tee: bool, run_id: str, session_id: str) -> TeeLegs: ...

    def register(
        self,
        *,
        run_id: str,
        session_id: str,
        kind: str,
        commit: Mapping[str, Any],
        packet_count: int | None,
        config_hash: str,
        generator_version: str,
        partial: bool,
    ) -> str: ...

    def find_reusable_baseline(
        self, sha256: str, config_hash: str, packet_count: int
    ) -> str | None: ...


class FaultFilter(Protocol):
    """The semantic stream-filter seam (production impl: #44 faults).

    Slot-preserving only (ADR-0007 item 4): ``apply`` maps one packet to
    one packet at the SAME shared-frame index — no insertion, no removal —
    so the tee streams stay index-aligned and CBR-constant.
    """

    def apply(self, index: int, packet: Any) -> Any: ...

    def mutation_log(self) -> bytes: ...


#: Builds the filter for a bound plan (composition-root seam; ``None``
#: return is only valid for an empty plan).  The production factory is
#: ``faults.factory.build_semantic_filter_factory()`` (#44); a factory may
#: additionally accept a keyword-only ``run_id`` — the runtime injects it
#: when the signature declares it, so the mutation log can carry the run
#: binding (SPEC-204 §8.2).
FilterFactory = Callable[[tuple[FaultDefinition, ...], GeneratorConfig], FaultFilter]


# --- fingerprint (SPEC-203 §5.1) --------------------------------------------------


def _canonical_config(config: GeneratorConfig) -> dict[str, Any]:
    """JSON-canonical config projection (bytes → hex; tuples → lists)."""
    document = asdict(config)
    program = document["program"]
    program["program_descriptors"] = bytes(
        config.program.program_descriptors
    ).hex()
    return document


def _canonical_plan(plan: tuple[FaultDefinition, ...]) -> list[dict[str, Any]]:
    """§5.1 item 3: fault_type + parameters + activation, key-sorted.

    ``fault_id`` is excluded (uuid4 identity, not semantics — see the
    :class:`FaultDefinition` note); ``target_id`` and
    ``expected_observations`` are included so different plans cannot
    collide on one fingerprint.
    """
    entries: list[dict[str, Any]] = []
    for fault in plan:
        entries.append(
            {
                "fault_type": fault.fault_type,
                "target_id": fault.target_id,
                "parameters": {
                    key: fault.parameters[key] for key in sorted(fault.parameters)
                },
                "activation": {
                    "kind": fault.activation.kind,
                    "packet_index": fault.activation.packet_index,
                },
                "expected_observations": list(fault.expected_observations),
            }
        )
    return entries


def compute_config_hash(
    config: GeneratorConfig,
    *,
    clock_config: SimulationClockConfig,
    fault_plan: tuple[FaultDefinition, ...],
) -> str:
    """The deterministic run fingerprint (SPEC-203 §5.1).

    Inputs, explicitly: the generator version (SPEC-108), the effective
    :class:`GeneratorConfig` (seed and initial media clock included), the
    SPEC-201 clock config (start_time_ns et al.) and the canonical fault
    plan. Wall clock, session_id, run_id and paths never enter. The plan
    fingerprint uses key-sorted canonical serialization: same plan ⇒ same
    hash, different plan ⇒ different hash.
    """
    document = {
        "generator_version": GENERATOR_VERSION,
        "config": _canonical_config(config),
        "clock": asdict(clock_config),
        "fault_plan": _canonical_plan(fault_plan),
    }
    canonical = canonical_json(document)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# --- production sink adapter (consumes #42, owns no paths) ------------------------


class StoreArtifactSink:
    """:class:`ArtifactSink` over the #42 store (SPEC-503 landing protocol).

    Consume-only adapter (boundary discipline): every leg is an
    :class:`adapters.storage.artifact_store.ArtifactWriteSink` — tmp file →
    incremental SHA-256 → atomic rename onto the content-addressed path →
    先文件后索引 register. The baseline dedup decision (SPEC-203 §5.2) is
    wired here at the record level: a complete baseline reuses an existing
    ``generated_ts`` index row only when the full fingerprint triple
    (sha256 + config_hash + packet_count) matches, so a partial artifact
    is never reused as a baseline (§6 item 4).

    The store itself converges the physical half: identical content lands
    on one content-addressed file (引用不复制 — ``os.replace`` atomic
    rename), and ``faulted_ts`` / ``log`` rows are never deduplicated
    across runs.
    """

    def __init__(
        self,
        store: ArtifactStore,
        *,
        index: Any | None = None,
        ts_ext: str = "ts",
        log_ext: str = "log",
    ) -> None:
        self._store = store
        # The index half is the same repository the store registers into;
        # resolved through the store's public ``index`` accessor (an
        # explicit ``index`` kwarg still wins for composition roots that
        # keep the repository separate). A store without any index can
        # never satisfy the record-level dedup contract, so that case is
        # an explicit construction error — never a silent dedup disable.
        resolved = index if index is not None else store.index
        if resolved is None:
            raise ArtifactNotFoundError(
                "StoreArtifactSink requires an index repository: attach one "
                "to the ArtifactStore (ArtifactStore(root, index=...)) or "
                "pass index= explicitly — baseline dedup (SPEC-203 §5.2) "
                "cannot be silently disabled"
            )
        self._index = resolved
        self._ts_ext = ts_ext
        self._log_ext = log_ext

    def open_legs(self, *, tee: bool, run_id: str, session_id: str) -> TeeLegs:
        baseline = self._store.open_sink(self._ts_ext)
        faulted = self._store.open_sink(self._ts_ext) if tee else None
        log = self._store.open_sink(self._log_ext) if tee else None
        return TeeLegs(baseline=baseline, faulted=faulted, log=log)

    def register(
        self,
        *,
        run_id: str,
        session_id: str,
        kind: str,
        commit: Mapping[str, Any],
        packet_count: int | None,
        config_hash: str,
        generator_version: str,
        partial: bool,
    ) -> str:
        sink_commit = SinkCommit(
            sha256=commit["sha256"],
            byte_size=commit["byte_size"],
            relative_path=commit["relative_path"] or "",
        )
        return self._store.register(
            sink_commit,
            run_id=run_id,
            session_id=session_id,
            kind=kind,
            packet_size=TS_PACKET_SIZE if kind in (ARTIFACT_KIND_GENERATED, ARTIFACT_KIND_FAULTED) else None,
            packet_count=packet_count,
            generator_version=generator_version,
            config_hash=config_hash,
        )

    def find_reusable_baseline(
        self, sha256: str, config_hash: str, packet_count: int
    ) -> str | None:
        for row in self._index.find_by_sha256(sha256):
            if (
                getattr(row, "kind", None) == ARTIFACT_KIND_GENERATED
                and getattr(row, "config_hash", None) == config_hash
                and getattr(row, "packet_count", None) == packet_count
            ):
                return row.artifact_id
        return None


# --- the adapter ------------------------------------------------------------------


class TSRuntime:
    """SPEC-203 §4 ``TSRuntimeAdapter`` implementation (SIM_TS)."""

    def __init__(
        self,
        *,
        runtime: SimulationRuntime | None = None,
        filter_factory: FilterFactory | None = None,
        worker_max: int = DEFAULT_WORKER_MAX,
        batch_size: int = DEFAULT_BATCH_SIZE,
        progress_every_batches: int = DEFAULT_PROGRESS_EVERY_BATCHES,
    ) -> None:
        if worker_max < 1:
            raise ValueError(f"worker_max must be >= 1, got {worker_max}")
        if batch_size < 1:
            raise ValueError(f"batch_size must be >= 1, got {batch_size}")
        if progress_every_batches < 1:
            raise ValueError(
                f"progress_every_batches must be >= 1, got {progress_every_batches}"
            )
        self._runtime = runtime
        self._filter_factory = filter_factory
        self._worker_max = worker_max
        self._batch_size = batch_size
        self._progress_every_batches = progress_every_batches
        self._generator = TSGenerator()
        self._pool: ThreadPoolExecutor | None = None
        # run_id → threading.Event; cancel(run_id) sets the flag and the
        # worker honors it at the next batch boundary (§6 item 3).
        self._cancel_flags: dict[str, Any] = {}

    # --- SPEC-203 §4 prepare ----------------------------------------------------

    def prepare(
        self,
        session: SimulationSessionSpec,
        config: GeneratorConfig,
        fault_plan=(),
    ) -> PreparedTSRun:
        """Validate and bind: config + plan → frozen :class:`PreparedTSRun`.

        The plan binds here (ADR-0007 item 2) and is validated BEFORE any
        session mutation (AC-204-01): unknown fault_type / unknown
        parameter keys / out-of-range activation are rejected with
        ``SIM_TS_PLAN_INVALID`` detail; an illegal
        :class:`GeneratorConfig` is rejected with ``SIM_TS_CONFIG_INVALID``
        through the SPEC-108 public validator (never re-implemented).
        """
        if not isinstance(session, SimulationSessionSpec):
            raise TypeError(
                f"session must be SimulationSessionSpec, got "
                f"{type(session).__name__}"
            )
        if not isinstance(config, GeneratorConfig):
            raise TypeError(
                f"config must be GeneratorConfig, got {type(config).__name__}"
            )
        error_findings = [
            finding
            for finding in self._generator.validate_config(config)
            if finding.severity == "error"
        ]
        if error_findings:
            first = error_findings[0]
            raise TSConfigInvalidError(
                f"{first.code}: {first.message} (field {first.field!r}; "
                "SPEC-108 §5 via the public validator)"
            )
        plan = validate_fault_plan(
            fault_plan,
            actual_pmt_pid=config.program.pmt_pid,
            # SPEC-204 §11 SIM_FAULT_ACTIVATION_OUT_OF_RANGE: the frame
            # length is budgetable at prepare (REQ-SIM-204-001 validates
            # the activation against the prepared output frame).
            # #44 append-only: see the module changelog note in faults docs.
            expected_packet_count=config.output_packet_count,
        )
        return PreparedTSRun(
            session_id=session.session_id,
            config=config,
            fault_plan=plan,
            config_hash=compute_config_hash(
                config,
                clock_config=session.clock_config,
                fault_plan=plan,
            ),
            generator_version=GENERATOR_VERSION,
        )

    # --- SPEC-203 §4 run / cancel ------------------------------------------------

    @property
    def active_run_ids(self) -> frozenset[str]:
        """Run ids currently executing (bounded-batch cancel addressing)."""
        return frozenset(self._cancel_flags)

    def cancel(self, run_id: str) -> None:
        """Request cancellation of one running generation (SPEC-203 §6 item 3).

        Cooperative and bounded: the worker checks the flag at the next
        batch boundary, so the request takes effect within one batch;
        produced bytes stop growing and the landed artifacts are marked
        ``partial`` (§6 item 4). Unknown run ids are a caller programming
        error (``ValueError``); repeated cancels are idempotent.
        """
        flag = self._cancel_flags.get(run_id)
        if flag is None:
            raise ValueError(
                f"run_id {run_id!r} is not active on this TS runtime; "
                "only a running generation can be cancelled"
            )
        flag.set()

    async def run(self, prepared: PreparedTSRun, sink: ArtifactSink) -> TSRunResult:
        """Execute one deterministic generation run (SPEC-203 §4).

        A fresh uuid4 ``run_id`` per call; repeated runs of one
        :class:`PreparedTSRun` share the fingerprint (§4: 重复 run 产生同指
        纹的新 Run). When a :class:`SimulationRuntime` is wired, the run
        opens/closes through its run face so the SPEC-200 lifecycle gates
        runs and ``run_*`` events emit (§6 item 6).

        Returns the completed/cancelled result; failed runs raise the
        SPEC-203 §8 error (``SIM_TS_SINK_IO_ERROR`` /
        ``SIM_TS_GENERATION_FAILED`` with the root cause code attached)
        after the partial artifacts are landed and marked.
        """
        if not isinstance(prepared, PreparedTSRun):
            raise TypeError(
                f"prepared must be PreparedTSRun, got {type(prepared).__name__}"
            )
        tee = bool(prepared.fault_plan)
        if tee and self._filter_factory is None:
            raise ValueError(
                "a non-empty fault plan requires a wired fault filter (the "
                "FaultFilter seam must be injected at TSRuntime "
                "construction; the #44 faults package supplies the "
                "production filter)"
            )

        run_id = str(uuid.uuid4())
        if self._runtime is not None:
            # Lifecycle coupling: runs require a RUNNING session (SPEC-200
            # run face) and emit ``run_started``.
            run_view = await self._runtime.start_run(prepared.session_id)
            run_id = run_view.run_id
            if prepared.fault_plan:
                # SPEC-204 §8.1: DEFINED = prepare validation passed — the
                # validated plan is now SCHEDULED on this run (one
                # ``fault.injected`` per plan fault, scope.run_id attributed).
                self._emit_plan_injected(prepared, run_id)

        cancel_flag = threading.Event()
        self._cancel_flags[run_id] = cancel_flag
        loop = asyncio.get_running_loop()
        try:
            pool = self._ensure_pool()
            payload = _RunPayload(
                run_id=run_id,
                session_id=prepared.session_id,
                config=prepared.config,
                fault_plan=prepared.fault_plan,
                config_hash=prepared.config_hash,
                tee=tee,
                cancel_flag=cancel_flag,
                loop=loop,
                sink=sink,
            )
            outcome = await loop.run_in_executor(pool, self._execute_run, payload)
        except TSWorkerUnavailableError:
            await self._close_run(prepared.session_id, run_id, "worker unavailable")
            raise
        except Exception:
            await self._close_run(prepared.session_id, run_id, "dispatch failed")
            raise
        finally:
            self._cancel_flags.pop(run_id, None)

        artifacts = self._build_artifact_refs(prepared, sink, outcome)
        if self._runtime is not None and prepared.fault_plan:
            # SPEC-204 §8.1 terminal states: APPLIED confirmations (L1, from
            # the §8.2 mutation-log attribution) and the REMOVED window close
            # at run end. A FAILED run leaves the fault in the FAILED state —
            # no applied/cleared (the fault_inactive baseline anchor stays
            # open on failed baseline runs by construction).
            self._emit_fault_terminal_events(
                prepared, run_id, outcome.status, artifacts, outcome
            )
        await self._close_run(
            prepared.session_id,
            run_id,
            outcome.status,
            artifacts=artifacts,
            error=outcome.error,
        )
        if outcome.status == "failed":
            outcome.error.raise_now()
        return TSRunResult(
            run_id=run_id,
            status=outcome.status,
            packet_count=outcome.packet_count,
            byte_count=outcome.packet_count * TS_PACKET_SIZE,
            virtual_duration_ns=outcome.virtual_duration_ns,
            artifacts=tuple(artifacts),
            warnings=tuple(outcome.warnings),
            generator_version=GENERATOR_VERSION,
            config_hash=prepared.config_hash,
        )

    # --- internals -----------------------------------------------------------------

    def _ensure_pool(self) -> ThreadPoolExecutor:
        if self._pool is None:
            self._pool = ThreadPoolExecutor(
                max_workers=self._worker_max,
                thread_name_prefix="sim-ts-worker",
            )
        return self._pool

    def shutdown(self) -> None:
        """Tear down the worker pool (composition-root teardown hook)."""
        if self._pool is not None:
            self._pool.shutdown(wait=True)
            self._pool = None

    def _build_artifact_refs(
        self, prepared: PreparedTSRun, sink: ArtifactSink, outcome: _RunOutcome
    ) -> list[ArtifactRef]:
        """Assemble §5.2 artifact refs: record-level baseline dedup + per-leg
        registration (the sink owns physical landing and the index row)."""
        artifacts: list[ArtifactRef] = []
        partial = outcome.status != "completed"
        for kind, commit in outcome.commits.items():
            fields = _commit_fields(commit)
            is_ts_kind = kind in (ARTIFACT_KIND_GENERATED, ARTIFACT_KIND_FAULTED)
            if kind == ARTIFACT_KIND_GENERATED and not partial:
                # 基线去重（SPEC-203 §5.2): same fingerprint + same bytes →
                # reuse the existing record; a partial baseline is never a
                # dedup source (§6 item 4).
                artifact_id = sink.find_reusable_baseline(
                    fields["sha256"], prepared.config_hash, outcome.packet_count
                )
            else:
                artifact_id = None
            if artifact_id is None:
                artifact_id = sink.register(
                    run_id=outcome.run_id,
                    session_id=prepared.session_id,
                    kind=kind,
                    commit=fields,
                    packet_count=outcome.packet_count if is_ts_kind else None,
                    config_hash=prepared.config_hash,
                    generator_version=GENERATOR_VERSION,
                    partial=partial,
                )
            artifacts.append(
                ArtifactRef(
                    artifact_id=artifact_id,
                    kind=kind,  # type: ignore[arg-type]
                    sha256=fields["sha256"],
                    byte_size=fields["byte_size"],
                    packet_count=outcome.packet_count if is_ts_kind else None,
                    partial=partial,
                )
            )
        return artifacts

    # --- fault.* emission points (ticket #56, SPEC-204 §8/§9) -----------------------

    @staticmethod
    def _fault_addressing(fault: FaultDefinition) -> tuple[str | None, int | None, int]:
        """(node_id, pid, injection_index) for one plan fault.

        The target slug is prepare-validated (AC-204-01); the defensive
        ``None`` fallback only keeps a malformed slug from breaking an
        emission. ``session_start`` opens its window at shared-frame
        index 0 (ADR-0007 item 3).
        """
        try:
            target = parse_target_id(fault.target_id)
            node_id: str | None = target.node_id
            pid: int | None = target.pid
        except ValueError:
            node_id, pid = None, None
        injection_index = (
            0
            if fault.activation.kind == "session_start"
            else fault.activation.packet_index or 0
        )
        return node_id, pid, injection_index

    def _emit_plan_injected(self, prepared: PreparedTSRun, run_id: str) -> None:
        """One ``fault.injected`` (SCHEDULED) per prepare-validated fault.

        Fired right after the run opens: the validated plan is now bound to
        a run identity, so the SCHEDULED state is observable per run and
        scope.run_id attribution holds (SPEC-204 §9).
        """
        for fault in prepared.fault_plan:
            node_id, pid, injection_index = self._fault_addressing(fault)
            self._emit_fault_event_safe(
                prepared.session_id,
                run_id,
                "fault.injected",
                fault,
                node_id,
                pid,
                {
                    "fault_id": fault.fault_id,
                    "fault_type": fault.fault_type,
                    "injection_index": injection_index,
                    "expected_observations": list(fault.expected_observations),
                },
            )

    def _emit_fault_terminal_events(
        self,
        prepared: PreparedTSRun,
        run_id: str,
        status: str,
        artifacts: list[ArtifactRef],
        outcome: "_RunOutcome",
    ) -> None:
        """APPLIED confirmations + the REMOVED window close (run end).

        ``fault.applied`` (L1 only) is attributed per fault from the §8.2
        mutation-log document the tee partner produced — the runtime never
        re-derives fault semantics. Completed AND cancelled runs close their
        windows (REMOVED at run end, SPEC-204 §8.1); a failed run leaves the
        fault FAILED (no applied/cleared).
        """
        log_artifact_id = next(
            (ref.artifact_id for ref in artifacts if ref.kind == ARTIFACT_KIND_LOG),
            None,
        )
        for fault in prepared.fault_plan:
            node_id, pid, injection_index = self._fault_addressing(fault)
            summary = outcome.fault_lifecycle.get(fault.fault_id)
            if status in ("completed", "cancelled") and summary and summary.get(
                "applied_packet_indexes"
            ):
                payload = {
                    "fault_id": fault.fault_id,
                    "fault_type": fault.fault_type,
                    "injection_index": injection_index,
                    "applied_packet_indexes": list(
                        summary["applied_packet_indexes"]
                    ),
                }
                if log_artifact_id is not None:
                    payload["mutation_log_ref"] = log_artifact_id
                self._emit_fault_event_safe(
                    prepared.session_id,
                    run_id,
                    "fault.applied",
                    fault,
                    node_id,
                    pid,
                    payload,
                )
            if status in ("completed", "cancelled"):
                self._emit_fault_event_safe(
                    prepared.session_id,
                    run_id,
                    "fault.cleared",
                    fault,
                    node_id,
                    pid,
                    {
                        "fault_id": fault.fault_id,
                        "fault_type": fault.fault_type,
                        "injection_index": injection_index,
                        "cleared_reason": "run_end",
                    },
                )

    def _emit_fault_event_safe(
        self,
        session_id: str,
        run_id: str,
        event_type: str,
        fault: FaultDefinition,
        node_id: str | None,
        pid: int | None,
        payload: dict[str, Any],
    ) -> None:
        """Emission wrapper that never breaks the run's SPEC-203 outcome.

        The gateway (DELIVERY_PROTECTED handling) is the authoritative
        non-drop point; this guard only covers the session-teardown race
        (a vanished session between the run face and an emission), which is
        recorded as the ticket #56 MVP posture.
        """
        try:
            self._runtime.emit_fault_event(  # type: ignore[union-attr]
                session_id,
                run_id,
                event_type,
                fault_id=fault.fault_id,
                fault_type=fault.fault_type,
                target_node_id=node_id,
                target_pid=pid,
                payload=payload,
            )
        except Exception:  # noqa: BLE001 — teardown race only
            pass

    def _schedule_fault_activated(
        self,
        payload: "_RunPayload",
        fault: FaultDefinition,
        node_id: str | None,
        pid: int | None,
    ) -> None:
        """Marshal one ``fault.activated`` to the event loop (ACTIVE).

        The worker thread detects the activation-index crossing; the
        emission runs on the loop thread (same posture as the coalesced
        progress emission — cross-thread sink calls stay off the worker).
        """
        if payload.loop is None or self._runtime is None:
            return
        _, _, injection_index = self._fault_addressing(fault)

        def _emit() -> None:
            try:
                self._runtime.emit_fault_event(  # type: ignore[union-attr]
                    payload.session_id,
                    payload.run_id,
                    "fault.activated",
                    fault_id=fault.fault_id,
                    fault_type=fault.fault_type,
                    target_node_id=node_id,
                    target_pid=pid,
                    payload={
                        "fault_id": fault.fault_id,
                        "fault_type": fault.fault_type,
                        "injection_index": injection_index,
                    },
                )
            except Exception:  # noqa: BLE001 — teardown race only
                pass

        try:
            payload.loop.call_soon_threadsafe(_emit)
        except RuntimeError:  # loop closed mid-run
            pass

    async def _close_run(
        self,
        session_id: str,
        run_id: str,
        status: str,
        *,
        artifacts: list[ArtifactRef] | None = None,
        error: "_RunError | None" = None,
    ) -> None:
        """Close the run through the #41 run face (no-op unwired)."""
        if self._runtime is None:
            return
        try:
            if status == "completed" and artifacts is not None:
                session_refs = tuple(
                    SessionArtifactRef(
                        artifact_id=ref.artifact_id,
                        kind=ref.kind,
                        status="partial" if ref.partial else "complete",
                    )
                    for ref in artifacts
                )
                await self._runtime.complete_run(
                    session_id, run_id, artifacts=session_refs
                )
            else:
                reason = status
                if error is not None:
                    reason = error.code
                elif status == "cancelled":
                    reason = SIM_TS_CANCELLED
                await self._runtime.fail_run(session_id, run_id, reason=reason)
        except ValueError:
            # A concurrent close (stop/fail path) already terminated the
            # run record; the run face is the authority — never override.
            pass

    # --- worker-side execution (runs on the bounded pool thread) --------------------

    def _instantiate_filter(self, payload: "_RunPayload") -> Any:
        """Call the wired filter factory (#44 append-only hook).

        The default two-argument call ``(plan, config)`` is unchanged for
        every existing factory.  When the factory declares support for it,
        the run binding (``run_id``) is injected as a keyword argument so
        the SPEC-204 §8.2 mutation log can carry the run reference — the
        production faults-package factory accepts it; #43 fakes don't and
        keep working untouched.
        """
        factory = self._filter_factory
        assert factory is not None  # guarded by the tee gate in run()
        try:
            parameters = inspect.signature(factory).parameters
            accepts_run_id = "run_id" in parameters or any(
                parameter.kind is inspect.Parameter.VAR_KEYWORD
                for parameter in parameters.values()
            )
        except (TypeError, ValueError):  # C builtins without signatures
            accepts_run_id = False
        if accepts_run_id:
            return factory(
                payload.fault_plan, payload.config, run_id=payload.run_id
            )
        return factory(payload.fault_plan, payload.config)

    def _execute_run(self, payload: "_RunPayload") -> "_RunOutcome":
        outcome = _RunOutcome(run_id=payload.run_id)
        cancel_flag = payload.cancel_flag
        tee = payload.tee
        try:
            legs = self._sink_open_legs(payload)
        except Exception as exc:  # noqa: BLE001 — surfaced as sink failure
            outcome.fail_with(_RunError.sink_io(exc))
            return outcome
        baseline_leg = legs.baseline
        faulted_leg = legs.faulted
        log_leg = legs.log
        filter_instance = None
        if tee:
            try:
                filter_instance = self._instantiate_filter(payload)
            except Exception as exc:  # noqa: BLE001
                outcome.fail_with(_RunError.generation(exc))
                return outcome

        def write_chunk(chunk: bytes, leg, what: str) -> bool:
            try:
                leg.write(chunk)
                return True
            except Exception as exc:  # noqa: BLE001 — store raises its own types
                outcome.fail_with(_RunError.sink_io(exc, what=what))
                return False

        try:
            iterator = iter(self._generator.iter_packets(payload.config))
        except Exception as exc:  # noqa: BLE001
            outcome.fail_with(_RunError.generation(exc))
            _abort_legs(baseline_leg, faulted_leg, log_leg)
            return outcome

        index = 0
        batches_done = 0
        # Activation marks (SPEC-204 §8.1: ACTIVE = window start): one
        # crossing per plan fault, in shared-frame order.
        marks = sorted(
            (
                (*self._fault_addressing(fault), fault)
                for fault in payload.fault_plan
            ),
            key=lambda item: item[2],
        )
        mark_cursor = 0
        while True:
            if cancel_flag.is_set():
                outcome.status = "cancelled"
                break
            batch = list(islice(iterator, self._batch_size))
            if not batch:
                outcome.status = "completed"
                break
            for packet in batch:
                while mark_cursor < len(marks) and marks[mark_cursor][2] <= index:
                    node_id, pid, _, mark_fault = marks[mark_cursor]
                    self._schedule_fault_activated(payload, mark_fault, node_id, pid)
                    mark_cursor += 1
                data = packet.to_bytes()
                if not write_chunk(data, baseline_leg, "baseline"):
                    break
                if tee:
                    try:
                        faulted_data = filter_instance.apply(
                            index, packet
                        ).to_bytes()
                    except FaultExecutionError as exc:
                        # SPEC-204 §11: a run-stage transform failure puts
                        # the fault in FAILED; the run fails per SPEC-203
                        # semantics with the fault code as the root cause.
                        outcome.fail_with(_RunError.fault_exec(exc))
                        break
                    except Exception as exc:  # noqa: BLE001 — filter faults
                        outcome.fail_with(_RunError.generation(exc))
                        break
                    if not write_chunk(faulted_data, faulted_leg, "faulted"):
                        break
                index += 1
            if outcome.error is not None:
                break
            outcome.packet_count = index
            batches_done += 1
            if (
                payload.loop is not None
                and self._runtime is not None
                and batches_done % self._progress_every_batches == 0
            ):
                self._schedule_progress(payload, index)

        if outcome.status == "failed":
            # Sink IO failure: the failing leg was discarded by the store;
            # nothing may land half-written. Abort the remaining legs.
            _abort_legs(baseline_leg, faulted_leg, log_leg)
            return outcome
        if tee and log_leg is not None:
            log_bytes = filter_instance.mutation_log()
            if not write_chunk(log_bytes, log_leg, "log"):
                _abort_legs(baseline_leg, faulted_leg, log_leg)
                return outcome
            # APPLIED attribution (ticket #56): read back the §8.2 document
            # the tee partner produced — per-fault identity, target and the
            # confirmed slot list. A log without the shape (identity fakes)
            # yields no attribution and ``fault.applied`` does not fire.
            outcome.fault_lifecycle = _parse_fault_lifecycle(log_bytes)
        # cancelled / completed: commit the landed (partial or full) legs.
        for name, leg in (
            (ARTIFACT_KIND_GENERATED, baseline_leg),
            (ARTIFACT_KIND_FAULTED, faulted_leg),
            (ARTIFACT_KIND_LOG, log_leg),
        ):
            if leg is None:
                continue
            try:
                outcome.commits[name] = leg.commit()
            except Exception as exc:  # noqa: BLE001
                outcome.fail_with(_RunError.sink_io(exc, what=name))
                _abort_legs(baseline_leg, faulted_leg, log_leg)
                return outcome
        return outcome

    def _sink_open_legs(self, payload: "_RunPayload") -> Any:
        return payload.sink.open_legs(
            tee=payload.tee, run_id=payload.run_id, session_id=payload.session_id
        )

    def _schedule_progress(self, payload: "_RunPayload", packets: int) -> None:
        """Coalesced ``run_progress`` from the worker thread (SPEC-301 §5)."""

        def _emit() -> None:
            task = asyncio.create_task(
                self._runtime.report_run_progress(  # type: ignore[union-attr]
                    payload.session_id,
                    payload.run_id,
                    {"packets": packets},
                )
            )
            task.add_done_callback(_swallow_progress_error)

        try:
            payload.loop.call_soon_threadsafe(_emit)
        except RuntimeError:  # loop closed mid-run
            pass


def _swallow_progress_error(task: "asyncio.Task") -> None:
    """A coalesced progress emission racing a terminal close is dropped
    (合并限流语义) — never surfaced as an unhandled task exception."""
    if not task.cancelled() and task.exception() is not None:
        pass


def _abort_legs(*legs) -> None:
    for leg in legs:
        if leg is None:
            continue
        try:
            leg.abort()
        except Exception:  # noqa: BLE001 — abort is best-effort
            pass


def _parse_fault_lifecycle(log_bytes: bytes) -> dict[str, dict[str, Any]]:
    """Per-fault APPLIED attribution from the §8.2 log document (ticket #56).

    The tee partner (production: ``SemanticFaultFilter``) owns the fault
    semantics and documents its actual transforms per SPEC-204 §8.2; the
    runtime only reads back that documented evidence shape. Anything
    without the shape parses to an empty attribution — never a crash.
    """
    try:
        document = json.loads(log_bytes.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return {}
    if not isinstance(document, Mapping):
        return {}
    lifecycle: dict[str, dict[str, Any]] = {}
    entries = document.get("faults") or []
    if not isinstance(entries, list):
        return {}
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        fault_id = entry.get("fault_id")
        if not isinstance(fault_id, str) or not fault_id:
            continue
        target = entry.get("target")
        target_map = target if isinstance(target, Mapping) else {}
        applied = (entry.get("lifecycle") or {}).get("fault.applied")
        indexes = (
            [value for value in applied if isinstance(value, int)]
            if isinstance(applied, list)
            else []
        )
        lifecycle[fault_id] = {
            "node_id": target_map.get("node_id"),
            "pid": target_map.get("pid"),
            "applied_packet_indexes": indexes,
        }
    return lifecycle


def _commit_fields(commit: Any) -> dict[str, Any]:
    """Normalize a leg commit (Mapping or attribute object) to fields."""
    if isinstance(commit, Mapping):
        return {
            "sha256": commit["sha256"],
            "byte_size": commit["byte_size"],
            "relative_path": commit.get("relative_path"),
        }
    return {
        "sha256": commit.sha256,
        "byte_size": commit.byte_size,
        "relative_path": getattr(commit, "relative_path", None),
    }


class _RunPayload:
    """Everything the worker thread needs (no shared mutable runtime state)."""

    __slots__ = (
        "run_id",
        "session_id",
        "config",
        "fault_plan",
        "config_hash",
        "tee",
        "cancel_flag",
        "loop",
        "sink",
    )

    def __init__(
        self,
        *,
        run_id: str,
        session_id: str,
        config: GeneratorConfig,
        fault_plan: tuple[FaultDefinition, ...],
        config_hash: str,
        tee: bool,
        cancel_flag: threading.Event,
        loop: asyncio.AbstractEventLoop | None,
        sink: ArtifactSink,
    ) -> None:
        self.run_id = run_id
        self.session_id = session_id
        self.config = config
        self.fault_plan = fault_plan
        self.config_hash = config_hash
        self.tee = tee
        self.cancel_flag = cancel_flag
        self.loop = loop
        self.sink = sink


class _RunError:
    """Worker-side failure snapshot; re-raised on the async side."""

    __slots__ = ("kind", "code", "message", "root_code", "exc")

    def __init__(self, kind: str, code: str, message: str, exc: Exception) -> None:
        self.kind = kind
        self.code = code
        self.message = message
        self.exc = exc
        self.root_code = None

    @classmethod
    def sink_io(cls, exc: Exception, what: str = "") -> "_RunError":
        error = cls("sink", SIM_TS_SINK_IO_ERROR, f"sink write failed ({what}): {exc}", exc)
        return error

    @classmethod
    def generation(cls, exc: Exception) -> "_RunError":
        root_code = exc.code if isinstance(exc, TSCoreError) else None
        error = cls("generation", SIM_TS_GENERATION_FAILED, str(exc), exc)
        error.root_code = root_code
        return error

    @classmethod
    def fault_exec(cls, exc: Exception) -> "_RunError":
        """SPEC-204 §11: a run-stage transform failure (fault FAILED).

        The run keeps its SPEC-203 semantics (generation-failed public face,
        partial artifacts marked); the fault code rides as the root cause
        and the ``run_failed`` reason carries ``SIM_FAULT_EXEC_FAILED``.
        """
        error = cls(
            "fault_exec",
            SIM_FAULT_EXEC_FAILED,
            f"fault transform failed during the run: {exc}",
            exc,
        )
        error.root_code = SIM_FAULT_EXEC_FAILED
        return error

    def raise_now(self) -> None:
        if self.kind == "sink":
            raise TSSinkIOError(self.message) from self.exc
        raise TSGenerationFailedError(self.message, root_code=self.root_code) from self.exc


class _RunOutcome:
    """Worker result: status, counts, per-leg commits, error snapshot."""

    __slots__ = (
        "run_id",
        "status",
        "packet_count",
        "commits",
        "error",
        "warnings",
        "virtual_duration_ns",
        "fault_lifecycle",
    )

    def __init__(self, run_id: str = "") -> None:
        self.run_id = run_id
        self.status = "failed"
        self.packet_count = 0
        self.commits: dict[str, Any] = {}
        self.error: _RunError | None = None
        self.warnings: tuple[str, ...] = ()
        self.virtual_duration_ns = 0
        #: Per-fault APPLIED attribution parsed from the §8.2 log document
        #: (ticket #56); empty when the log lacks the shape or the run
        #: failed before the log leg was written.
        self.fault_lifecycle: dict[str, dict[str, Any]] = {}

    def fail_with(self, error: _RunError) -> None:
        self.status = "failed"
        self.error = error
