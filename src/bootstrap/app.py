"""Production composition root — ``build_production_app`` (ticket #53).

The single place where the whole platform is wired (裁定 K: the bootstrap
top-level package; 裁定 1: the M3 leftover composition items land here):

- **Observation plane** (SPEC-300 §7 data flow, end to end): SQLite
  journal + ``EventGateway`` → ``SessionHub`` (commit fan-out, the #49
  binding with the ``is_coalescable`` classifier injected) + timeline
  recorder + the metrics engine's checkpointed consumer + the alert
  service (its #52 hint port bound to the real hub) + the diagnosis
  service (run-end trigger) + the #53 observation query service and the
  export task registry.
- **REST/WS app**: the full SPEC-500 §4 router set (sessions/runs/
  artifacts wired, observation §4.5 switched via
  ``ServiceObservationQueryPort``, diagnosis §4.4 via
  ``ServiceDiagnosisPort``, topology §4.1 via ``RepositoryTopologyPort``
  over the SPEC-502 topologies table, scenario §4.7 + the solution-reveal
  gate via ``RegistryScenarioPort``, the §4.8 TSDuck call-records face —
  ticket #80) under the frozen ``/api/v1`` prefix plus the SPEC-501
  WebSocket route.
- **#44 filter factory**: the production semantic filter
  (``faults.factory.build_semantic_filter_factory()``) is the default for
  the TS runtime — the identity-filter placeholder is retired (裁定 1b).

The factory NEVER starts threads or servers and introduces no
uvicorn/entrypoint dependency (dispatch posture): it returns the ASGI app
plus the driving faces (``drain_gateway``/``process_observation``) an
embedder — or a test — uses to pump the deterministic pipeline. The
journal and its checkpointed consumers keep the recovery discipline
(SPEC-300 §8): restart and ``process_observation`` continues from the
durable checkpoints.

The hub's ``session_directory`` stays unbound by default (the #49 MVP
posture — the hub does not fabricate session truth); pass the simulation
plane's directory face when one exists.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional
from uuid import uuid4

from adapters.storage.alerts import SqliteAlertStore
from adapters.storage.checkpoints import SqliteCheckpointStore
from adapters.storage.db import connect, migrate
from adapters.storage.journal import SqliteEventJournal
from adapters.storage.repositories import (
    SqliteArtifactRepository,
    SqliteDiagnosisRepository,
    SqliteVerificationRepository,
)
from adapters.storage.topologies import SqliteTopologyRepository
from adapters.storage.tsduck_calls import SqliteTSDuckCallStore
from adapters.storage.artifact_store import ArtifactStore
from application.analysis import AnalysisService
from application.diagnosis import DiagnosisService, bind_run_completion_trigger
from application.observation.alerts.rules import default_rule_set
from application.observation.alerts.service import AlertService
from application.observation.consumer import ConsumerConfig, JournalTailingConsumer
from application.observation.gateway import EventGateway
from application.observation.metrics.engine import MetricsEngine
from application.observation.metrics.service import MetricsService
from application.observation.query import ObservationQueryService
from application.observation.query.exports import ExportTaskRegistry
from application.observation.timeline.recorder import TimelineRecorder
from application.observation.timeline.service import TimelineService
from domain.diagnosis.rules.loader import builtin_rules_provider
from domain.observation.registry import is_coalescable
from faults.factory import build_semantic_filter_factory
from simulation.runtime import SimulationRuntime
from simulation.ts_runtime import StoreArtifactSink, TSRuntime
from simulation.verification import VerificationService

from api.app import create_app
from api.routes import build_spec500_routers
from api.routes.observation import ServiceObservationQueryPort
from api.routes.pending import ServiceDiagnosisPort, ServiceVerificationPort
from api.ws.hub import SessionHub, WsConfig
from api.ws.router import build_ws_router

from bootstrap.backends import (
    ArtifactStoreBackend,
    RunIdAllocator,
    SimulationRunsBackend,
    SimulationSessionsBackend,
    TSDuckCallsBackend,
    default_topology_provider,
)
from bootstrap.hints import (
    EventAppendedHintSubscriber,
    HubAlertHintEmitter,
    HubHintPublisher,
)
from bootstrap.scenarios import (
    RegistryScenarioPort,
    RegistrySolutionGate,
    ScenarioRegistry,
)
from bootstrap.topologies import (
    RepositoryTopologyPort,
    RepositoryTopologyProvider,
)

#: The SPEC-305 §8 topic emitted after a metrics-consumer tick.
METRIC_UPDATED_TOPIC = "observation.metric_updated"

#: Consumer batch size for the observation-plane tailing consumers.
_CONSUMER_BATCH_SIZE = 100


@dataclass
class ProductionStack:
    """Everything the embedder (or a test) drives, in one handle."""

    app: Any
    connection: Any
    journal: SqliteEventJournal
    gateway: EventGateway
    hub: SessionHub
    metrics_engine: MetricsEngine
    metrics_service: MetricsService
    timeline_recorder: TimelineRecorder
    timeline_service: TimelineService
    alert_service: AlertService
    diagnosis_service: DiagnosisService
    query_service: ObservationQueryService
    exports: ExportTaskRegistry
    analysis_service: AnalysisService
    runtime: SimulationRuntime
    ts_runtime: TSRuntime
    store: ArtifactStore
    repository: SqliteArtifactRepository
    session_specs: dict[str, Any]
    sessions_backend: SimulationSessionsBackend
    runs_backend: SimulationRunsBackend
    artifacts_backend: ArtifactStoreBackend
    hint_publisher: HubHintPublisher
    topology_repository: SqliteTopologyRepository
    topology_port: RepositoryTopologyPort
    scenario_registry: ScenarioRegistry
    tsduck_call_store: SqliteTSDuckCallStore
    consumers: dict[str, JournalTailingConsumer] = field(default_factory=dict)

    # --- driver faces (no threads; the embedder pumps deterministically) ----

    def drain_gateway(self) -> int:
        """Commit the queued events (the SPEC-300 §8 dispatcher slice).

        Every commit fans out to the hub, the timeline recorder, the
        diagnosis trigger and the event_appended hint emitter — in that
        subscription order.
        """
        return self.gateway.drain()

    def attach_session(self, session_id: str) -> None:
        """Create the checkpointed metrics consumer for one session (the
        SPEC-300 §7 consumption posture; wired on session creation)."""
        if session_id in self.consumers:
            return
        self.consumers[session_id] = JournalTailingConsumer(
            journal=self.journal,
            checkpoints=SqliteCheckpointStore(self.connection),
            session_id=session_id,
            consumer_id="metrics-engine",
            handler=self.metrics_engine.handle_record,
            config=ConsumerConfig(batch_size=_CONSUMER_BATCH_SIZE),
        )

    def process_observation(self, session_id: Optional[str] = None) -> int:
        """Tick the observation consumers; a checkpoint advance emits one
        ``observation.metric_updated`` pointer hint per session (SPEC-305
        §8). Returns the total processed record count."""
        targets = (
            [self.consumers[session_id]]
            if session_id is not None
            else list(self.consumers.values())
        )
        processed = 0
        for consumer in targets:
            before = consumer.checkpoint_seq()
            count = consumer.catch_up()
            processed += count
            if count > 0:
                self.hint_publisher.publish(
                    consumer._session_id,  # noqa: SLF001 — same-package handle
                    METRIC_UPDATED_TOPIC,
                    {
                        "session_id": consumer._session_id,  # noqa: SLF001
                        "journal_seq_watermark": consumer.checkpoint_seq(),
                        "previous_watermark": before,
                        "processed": count,
                    },
                )
        return processed

    def evaluate_alerts(
        self,
        session_id: str,
        *,
        now_ns: int,
        clock_domain: str,
        clock_epoch: int = 0,
        reader=None,
    ):
        """One alert-evaluation tick (the #52 face over the wired metric
        reader); transitions persist + emit ``observation.alert_changed``.
        ``reader`` overrides the wired metrics reader (deterministic
        tests inject canned inputs)."""
        from application.observation.alerts.inputs import MetricsWindowReader

        return self.alert_service.evaluate_session(
            session_id,
            reader=reader if reader is not None else MetricsWindowReader(self.metrics_engine),
            now_ns=now_ns,
            clock_domain=clock_domain,
            clock_epoch=clock_epoch,
        )

    def close(self) -> None:
        """Close the SQLite connection (tests; single-user embedders)."""
        try:
            self.connection.close()
        except Exception:  # pragma: no cover — defensive
            pass


def _export_records_provider(timeline_service: TimelineService):
    """Timeline records for one export over the #51 query face (the
    filters ride the service's ordering/lanes discipline — the export is
    a query, never a storage reach-through)."""

    def provider(
        session_id: str,
        *,
        clock_domain: Optional[str] = None,
        clock_epoch: Optional[int] = None,
        start_ns: Optional[int] = None,
        end_ns: Optional[int] = None,
        record_kinds: tuple[str, ...] = (),
    ):
        from application.observation.timeline.service import TimelineFilter

        collected: list[Any] = []
        cursor: Optional[str] = None
        while True:
            page = timeline_service.query(
                TimelineFilter(
                    session_id=session_id,
                    record_kinds=tuple(record_kinds),
                    clock_domain=clock_domain,
                    clock_epoch=clock_epoch,
                    start_ns=start_ns,
                    end_ns=end_ns,
                    lanes=clock_domain is None,
                ),
                page_size=2000,
                cursor=cursor,
            )
            collected.extend(page.records)
            if page.lanes:
                for lane in page.lanes:
                    collected.extend(lane.records)
                return collected
            cursor = page.next_cursor
            if cursor is None:
                return collected

    return provider


def build_production_app(
    *,
    db_path: Path,
    session_directory: Any = None,
    topology_provider: Optional[Callable[[str, int], Any]] = None,
    filter_factory: Any = None,
    hub_config: Optional[WsConfig] = None,
    tenant_id: str = "local",
    now_wall_ns: Optional[Callable[[], int]] = None,
    max_exports_per_session: int = 32,
    export_id_factory: Optional[Callable[[], str]] = None,
    alert_rule_set: Optional[Any] = None,
    scenario_dir: Optional[Path] = None,
) -> ProductionStack:
    """Compose the full production app + observation plane.

    Args:
        db_path: SQLite database path (migrated in place — SPEC-502 §4).
        session_directory: optional hub session-existence face (#49 MVP:
            unbound — the hub does not fabricate session truth).
        topology_provider: optional topology resolver override; the
            default is the ticket #80 repository-backed provider (saved
            SPEC-502 rows resolve to the exact (id, revision); a miss
            falls back to the MVP ``topo-1`` empty graph).
        filter_factory: optional #44 filter factory override; the default
            is the production semantic filter (裁定 1b).
        hub_config: optional SPEC-501 transport knobs.
        tenant_id: the fixed local tenant (Q4 posture).
        now_wall_ns: injectable wall-clock source (deterministic tests);
            default ``time.time_ns`` (operational timestamps only).
        max_exports_per_session: the SPEC-305 §9 export throttle budget.
        export_id_factory: injectable export id source (deterministic
            tests); default ``uuid4``.
        scenario_dir: the SPEC-205 registry scan root (ticket #80, 裁定 F
            fallback: repo-top-level ``scenarios/``, resolved against the
            working directory; a missing directory is an empty registry).
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    wall_ns = now_wall_ns or (lambda: time.time_ns())

    connection = connect(db_path, check_same_thread=False)
    migrate(connection)
    journal = SqliteEventJournal(connection)
    artifact_repository = SqliteArtifactRepository(connection)
    artifact_root = db_path.parent / "artifacts"
    store = ArtifactStore(artifact_root, index=artifact_repository)

    gateway = EventGateway(journal=journal)
    hub = SessionHub(
        journal=journal,
        coalescable_of=is_coalescable,
        config=hub_config,
        session_directory=session_directory,
    )
    hub.attach_gateway(gateway)
    hint_publisher = HubHintPublisher(hub)
    # Journal frames first (the hub's own subscription), then the hint
    # pointer subscriber — the §8 pull pointer rides the commit and goes
    # through the same publisher seam as every other topic.
    gateway.subscribe(EventAppendedHintSubscriber(hint_publisher))

    timeline_recorder = TimelineRecorder()
    timeline_recorder.attach_gateway(gateway)

    metrics_engine = MetricsEngine()
    alert_service = AlertService(
        SqliteAlertStore(connection),
        alert_rule_set if alert_rule_set is not None else default_rule_set(),
        hint_emitter=HubAlertHintEmitter(hub),
    )
    exports = ExportTaskRegistry(
        records_provider=_export_records_provider(
            TimelineService(timeline_recorder)
        ),
        export_id_factory=export_id_factory or (lambda: uuid4().hex),
        created_at_factory=lambda: _wall_timepoint(wall_ns),
        hint_publisher=hint_publisher,
        tenant_id=tenant_id,
        max_exports_per_session=max_exports_per_session,
    )
    query_service = ObservationQueryService(
        journal=journal,
        metrics=MetricsService(metrics_engine),
        timeline=TimelineService(timeline_recorder),
        alerts=alert_service,
        session_exists=None,  # journal watermark is the existence authority
        tenant_id=tenant_id,
        hint_publisher=hint_publisher,
        exports=exports,
        reader=_build_metrics_reader(metrics_engine),
    )
    diagnosis_service = DiagnosisService(
        journal,
        gateway,
        SqliteDiagnosisRepository(connection),
        rules_provider=builtin_rules_provider,
    )
    bind_run_completion_trigger(gateway, diagnosis_service.evaluate)

    # The 裁定 A analysis bridge (ticket #58): run artifacts → ts.* events
    # over the real ts semantic layer. The 裁定 B in-process Analyze anchor
    # — the REST analyze route stays frozen (SPEC-500 §4.6); callers drive
    # this service face (no threads; publish-then-drain discipline).
    analysis_service = AnalysisService(gateway, store=store, now_wall_ns=wall_ns)

    # The SPEC-206 verification service (ticket #56) behind the verify
    # endpoint (ticket #58 composition binding, orchestrator 批复: the
    # #56-report composition bound here additively — the unbound port used
    # to keep the 501 freeze answer).
    verification_port = ServiceVerificationPort(
        VerificationService(journal, gateway, SqliteVerificationRepository(connection))
    )

    runtime = SimulationRuntime(event_sink=gateway)
    session_specs: dict[str, Any] = {}
    allocator = RunIdAllocator(runtime)
    ts_runtime = TSRuntime(
        runtime=allocator,  # structural shim: duck-types the run face
        filter_factory=filter_factory or build_semantic_filter_factory(),
    )
    # The session-creation hook wires the per-session metrics consumer into
    # the stack being built (bound after construction via the holder).
    stack_holder: dict[str, Any] = {}

    def _on_session_created(session_id: str) -> None:
        stack = stack_holder.get("stack")
        if stack is not None:
            stack.attach_session(session_id)

    # --- ticket #80 faces: SPEC-502 topology persistence, the SPEC-205
    # scenario registry (裁定 F scan root) + solution gate, and the
    # SPEC-308 call-record store.
    topology_repository = SqliteTopologyRepository(connection)
    topology_port = RepositoryTopologyPort(topology_repository)
    resolved_topology_provider = topology_provider or RepositoryTopologyProvider(
        topology_repository, fallback=default_topology_provider
    )
    resolved_scenario_dir = Path(scenario_dir) if scenario_dir else Path("scenarios")
    scenario_registry = ScenarioRegistry(resolved_scenario_dir)
    solution_gate = RegistrySolutionGate(
        scenario_registry, SqliteVerificationRepository(connection)
    )
    tsduck_call_store = SqliteTSDuckCallStore(connection)

    sessions_backend = SimulationSessionsBackend(
        runtime,
        resolved_topology_provider,
        session_specs,
        on_session_created=_on_session_created,
        scenario_registry=scenario_registry,
    )
    runs_backend = SimulationRunsBackend(
        ts_runtime, runtime, session_specs, StoreArtifactSink(store, index=artifact_repository), allocator
    )
    artifacts_backend = ArtifactStoreBackend(store, artifact_repository)
    tsduck_calls_backend = TSDuckCallsBackend(tsduck_call_store, journal)

    app = create_app(
        *build_spec500_routers(
            sessions_port=sessions_backend,
            runs_port=runs_backend,
            artifacts_port=artifacts_backend,
            diagnosis_port=ServiceDiagnosisPort(diagnosis_service),
            observation_port=ServiceObservationQueryPort(query_service, tenant_id=tenant_id),
            verification_port=verification_port,
            topology_port=topology_port,
            scenario_port=RegistryScenarioPort(scenario_registry, solution_gate),
            tsduck_calls_port=tsduck_calls_backend,
        )
    )
    app.include_router(build_ws_router(hub))

    stack = ProductionStack(
        app=app,
        connection=connection,
        journal=journal,
        gateway=gateway,
        hub=hub,
        metrics_engine=metrics_engine,
        metrics_service=MetricsService(metrics_engine),
        timeline_recorder=timeline_recorder,
        timeline_service=TimelineService(timeline_recorder),
        alert_service=alert_service,
        diagnosis_service=diagnosis_service,
        query_service=query_service,
        exports=exports,
        analysis_service=analysis_service,
        runtime=runtime,
        ts_runtime=ts_runtime,
        store=store,
        repository=artifact_repository,
        session_specs=session_specs,
        sessions_backend=sessions_backend,
        runs_backend=runs_backend,
        artifacts_backend=artifacts_backend,
        hint_publisher=hint_publisher,
        topology_repository=topology_repository,
        topology_port=topology_port,
        scenario_registry=scenario_registry,
        tsduck_call_store=tsduck_call_store,
    )
    stack_holder["stack"] = stack
    return stack


def _wall_timepoint(wall_ns: Callable[[], int]):
    from domain.observation import TimelineTimepoint, TimepointSemantics

    return TimelineTimepoint(
        value_ns=wall_ns(),
        clock_domain="wall:utc",
        clock_epoch=0,
        semantics=TimepointSemantics.OBSERVED,
    )


def _build_metrics_reader(metrics_engine: MetricsEngine):
    """The Ruling-H adapter: the query/alert faces read metric windows
    through the #50 public face only."""
    from application.observation.alerts.inputs import MetricsWindowReader

    return MetricsWindowReader(metrics_engine)
