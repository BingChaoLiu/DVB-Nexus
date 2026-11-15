"""Producer contract conformance checklist — ticket #57 (OBS-G).

Behavioral half of the OBSERVATION-INTEGRATION-CONTRACT (IC) §2 seven
producer obligations + §3/§4 event mappings, exercised against the REAL
producer faces (#41 emitter, #56 fault emitter, #54 diagnosis publisher,
the #50 metric-catalog fixture contract) and the REAL #47 gateway face.
The tabular checklist (obligation-by-obligation PASS/in-flight) lives in
the ticket report; this module pins the behavior each row cites.

Boundary discipline (IC §9, behavior face — the structural face is the
lint-imports contracts C1-C9): Observation consumption/query never calls
producer mutation interfaces. Source code is read-only for #57 (dispatch
seam ownership): a failure here is a defect report to the owning ticket,
never a fix in place.

Integration layer: real SQLite journal via the ``journal``-shaped
``bootstrap`` composition or in-memory doubles per the wiring-test
precedent (``tests/integration/simulation/test_runtime_gateway_wiring.py``).
"""

from __future__ import annotations

import asyncio
import uuid

import pytest

from adapters.storage.checkpoints import SqliteCheckpointStore
from adapters.storage.db import connect
from adapters.storage.journal import SqliteEventJournal
from application.observation import (
    EventGateway,
    EventPublisher,
    GatewayConfig,
    IngestOutcome,
    JournalTailingConsumer,
)
from application.observation.metrics.engine import MetricsEngine
from domain.observation import (
    REGISTERED_EVENT_TYPES,
    EventEnvelope,
    parse_envelope,
)
from domain.observation.registry import (
    is_coalescable,
    is_delivery_protected,
    validate_event_type,
)
from simulation.events import PRODUCER_ID, PRODUCER_VERSION, session_clock_domain
from simulation.runtime import SimulationRuntime

from tests.unit.application.observation.test_gateway_accept import _raw_envelope
from tests.unit.simulation.runtime import _sim_c_builders as b

SESSION = "sess-obs-g-contract"
DOMAIN = session_clock_domain(SESSION)


class MemoryJournal:
    """Minimal EventJournal double (wiring-test precedent): monotonic
    per-session seqs, no disk."""

    def __init__(self) -> None:
        self.appended: list[dict] = []
        self._seq = 0

    def append(self, envelope: dict) -> tuple[int, bool]:
        self._seq += 1
        self.appended.append(dict(envelope))
        return self._seq, False

    def query(self, session_id: str, *, after_seq: int = 0, limit: int = 100):
        return [
            row
            for row in self.appended
            if row["scope"]["session_id"] == session_id
        ][after_seq:after_seq + limit]

    def max_seq(self, session_id: str) -> int:
        return self._seq


def _envelope(
    event_type: str,
    *,
    session_id: str = SESSION,
    producer_id: str = "sim-engine",
    run_id: str | None = None,
    value_ns: int = 1,
    payload: dict | None = None,
) -> dict:
    """One contract-shaped envelope with a fresh stable event_id."""
    return _raw_envelope(
        event_id=str(uuid.uuid4()),
        event_type=event_type,
        producer_id=producer_id,
        session_id=session_id,
        payload=payload,
    ) | {
        "time": {
            "source": {
                "value_ns": value_ns,
                "clock_domain": session_clock_domain(session_id),
                "clock_epoch": 0,
            },
            "observed": {
                "value_ns": 1_000_000,
                "clock_domain": "wall:utc",
                "clock_epoch": 0,
            },
        },
        "scope": {
            "tenant_id": "local",
            "session_id": session_id,
            "run_id": run_id,
        },
    }


# ============================================================================
# IC §8 step 1 — producers share the contract (registry is the shared truth)
# ============================================================================


class TestSharedRegistryContract:
    """CONTRACT §8 step 1: 与生产者共享契约测试 — every mapped producer
    event name resolves against the one frozen registry (SPEC-301 §4)."""

    def test_every_contract_mapping_name_is_registered(self):
        """IC §3/§4 mapping tables ⊆ REGISTERED_EVENT_TYPES (SPEC-301 §4).

        The mapping names are read from the CONTRACT authority, restated
        here as the shared-contract fixture; a producer drift (rename,
        withdrawal) breaks this line before any dispatch code does.
        """
        mapped = (
            # §3 Simulation Engine mappings
            "simulation.session_created",
            "simulation.session_started",
            "simulation.session_paused",
            "simulation.session_resumed",
            "simulation.session_stopped",
            "simulation.run_started",
            "simulation.run_progress",
            "simulation.run_completed",
            "simulation.run_failed",
            "simulation.clock_advanced",
            "topology.state_changed",
            "fault.injected",
            "fault.activated",
            "fault.applied",
            "fault.cleared",
            "scenario.step_started",
            "scenario.step_completed",
            "recovery.verification_completed",
            # §4 TS Core mappings (G3: analysis bridge in-flight, #58)
            "ts.packet_batch_observed",
            "ts.continuity_error",
            "ts.pcr_jitter_observed",
            "ts.psi_section_observed",
            "ts.service_state_changed",
            # #54 diagnosis publisher mapping (SPEC-306 §7)
            "diagnosis.raised",
            "diagnosis.updated",
            "diagnosis.cleared",
        )
        unregistered = [
            name for name in mapped if name not in REGISTERED_EVENT_TYPES
        ]
        assert not unregistered, (
            "CONTRACT §3/§4 mapping names must all be registered "
            f"(SPEC-301 §4); unregistered={unregistered}"
        )
        for name in mapped:
            validate_event_type(name)  # must not raise

    def test_withdrawn_producer_names_are_refused(self):
        """SPEC-301 §4 withdrawals stay refused at the envelope layer — a
        producer cannot resurrect ``observation.*`` or ``snapshot.updated``
        (MVP: alert record is the authority, SPEC-304 §5)."""
        from domain.observation import WITHDRAWN_EVENT_TYPES

        assert "snapshot.updated" in WITHDRAWN_EVENT_TYPES
        for name in ("snapshot.updated", "observation.ingest_rate"):
            with pytest.raises(Exception, match="OBS_INVALID_ENVELOPE"):
                validate_event_type(name)


# ============================================================================
# IC §2 obligations 1-4 — the #41 emitter over the real publisher face
# ============================================================================


class TestSimulationEmitterObligations:
    """CONTRACT §2 producer obligations, behaviorally, through
    ``SimulationRuntime`` + ``EventPublisher`` (SPEC-300 §12 producer face)
    over the real #47 gateway."""

    def test_emitted_envelopes_round_trip_with_dual_clock_and_identity(
        self,
    ):
        """Obligations 1/3/4 (SPEC-301 v1.0 shape, source clock domain
        ``sim:<session_id>`` — never wall substitution — plus producer
        identity/version/instance). Round-trip via the frozen parse face."""

        async def main() -> None:
            journal = MemoryJournal()
            gateway = EventGateway(journal, GatewayConfig())
            runtime = SimulationRuntime(event_sink=EventPublisher(gateway))
            await runtime.create_session(b.session_spec(session_id=SESSION))
            await runtime.validate_session(SESSION)
            await runtime.start(SESSION)
            await runtime.start_run(SESSION, run_id="r-1")
            gateway.drain()

            assert journal.appended, "runtime emits lifecycle events"
            for raw in journal.appended:
                envelope = parse_envelope(raw)
                assert envelope.producer.producer_id == PRODUCER_ID
                assert envelope.producer.producer_version == PRODUCER_VERSION
                assert envelope.producer.instance_id
                source = envelope.time.source
                assert source.clock_domain == DOMAIN
                observed = envelope.time.observed
                assert observed.clock_domain == "wall:utc"
                # Dual clocks never collapse into one domain (SPEC-300 §6
                # rule 1/2; the sim source stays sim even though observed
                # is wall).
                assert source.clock_domain != observed.clock_domain

        asyncio.run(main())

    def test_event_id_stable_on_retry_duplicate_returns_original_seq(self):
        """Obligation 2 + IC §5 idempotency: a producer retry reuses the
        same ``event_id``; the gateway answers ``duplicate`` with the
        ORIGINAL journal_seq and the journal grows by zero rows
        (SPEC-300 §13 幂等成功)."""
        journal = MemoryJournal()
        gateway = EventGateway(journal, GatewayConfig())
        stamped: list[int] = []
        gateway.subscribe(lambda event: stamped.append(event["journal_seq"]))
        envelope = _envelope("simulation.run_started", run_id="r-1")

        first = gateway.accept(envelope)
        assert first.outcome is IngestOutcome.ACCEPTED
        # First accept carries no seq yet — the stamp rides the durable
        # append (SPEC-300 §7 step 4).
        assert first.journal_seq is None
        assert gateway.drain() == 1
        assert stamped == [1]
        stamped_seq = stamped[0]

        retry = gateway.accept(dict(envelope))  # same producer_id+event_id
        assert retry.outcome is IngestOutcome.DUPLICATE
        assert retry.journal_seq == stamped_seq
        assert gateway.drain() == 0  # nothing re-appended
        assert len(journal.appended) == 1

    def test_producer_never_fills_journal_seq(self):
        """The stamp is gateway/journal territory: a producer-filled
        ``journal_seq`` is refused before queueing (SPEC-301 §3; the
        ``ensure_publishable`` publish-view discipline)."""
        envelope = _envelope("simulation.session_started")
        envelope["journal_seq"] = 99
        with pytest.raises(Exception, match="journal_seq"):
            EventEnvelope.model_validate(envelope).ensure_publishable()

    def test_run_progress_coalescable_but_terminal_and_fault_protected(self):
        """SPEC-301 §5 delivery policy through the gateway (IC §3 note):
        ``run_progress`` may coalesce; terminal-run / fault / verification
        events are DELIVERY_PROTECTED — the same coalesce key never drops
        them."""
        assert is_coalescable("simulation.run_progress")
        for protected in (
            "simulation.run_completed",
            "simulation.run_failed",
            "fault.injected",
            "fault.activated",
            "fault.applied",
            "fault.cleared",
            "recovery.verification_completed",
            "simulation.session_stopped",
        ):
            assert is_delivery_protected(protected), protected
            assert not is_coalescable(protected), protected

    def test_burst_queue_full_is_explicit_rejection_never_silent(self):
        """IC §6 backpressure: a protected-family burst past the bounded
        queue yields structured ``rejected`` (retryable ``OBS_QUEUE_FULL``)
        — never a silent drop; everything accepted lands in the journal;
        accepted + rejected + duplicates account for every submission."""
        journal = MemoryJournal()
        gateway = EventGateway(journal, GatewayConfig(queue_capacity=4))
        fault_id = str(uuid.uuid4())
        accepted, rejected = 0, 0
        for index in range(12):
            envelope = _envelope(
                "fault.injected",
                run_id="r-1",
                payload={
                    "fault_id": fault_id,
                    "fault_type": "PAT_MISSING",
                    "injection_index": index,
                    "expected_observations": ["ts.psi_section_observed"],
                },
            )
            # distinct event_ids per injection, same dedup family — the
            # queue fills because nothing is drained mid-burst.
            result = gateway.accept(envelope)
            if result.outcome is IngestOutcome.ACCEPTED:
                accepted += 1
            elif result.outcome is IngestOutcome.REJECTED:
                rejected += 1
                assert result.retryable is True
                assert result.error_code == "OBS_QUEUE_FULL"
            else:
                pytest.fail(f"unexpected outcome {result.outcome}")
        assert accepted == 4
        assert rejected == 8

        # The 4 admitted protected events all commit on the next drain —
        # rejection was explicit backpressure, not a loss.
        committed = gateway.drain()
        assert committed == accepted == 4
        assert len(journal.appended) == 4
        assert accepted + rejected == 12  # full accountability (IC §6)

        results = gateway.metrics()
        assert results.rejected == 8
        assert results.accepted == 4


# ============================================================================
# IC §4 — TS Core producer contract. Status (ticket #57 checklist): the
# 裁定 A analysis bridge is LANDED (ticket #58, merged during the #57
# window): ``application.analysis.AnalysisService`` publishes ``ts.*``
# facts with producer identity ``internal-parser-analysis`` over the real
# ts semantic layer; the fixture/catalog payload keys below remain the
# shared contract the bridge's payloads satisfy.
# ============================================================================


class TestTsCoreProducerContract:
    """CONTRACT §4: TS Core publishes normalized facts with explicit units
    and provenance axes; batch statistics — never per-packet events."""

    def test_analysis_bridge_producer_identity_is_registered(self):
        """IC §2 obligation 4 for the landed bridge: a stable producer
        identity/version pair (the one #58 registered)."""
        from application.analysis import service as analysis_service_module

        assert analysis_service_module.PRODUCER_ID == "internal-parser-analysis"
        assert analysis_service_module.PRODUCER_VERSION

    def test_ts_family_requires_observation_axes(self):
        """#13 Q3-i: every ``ts.*`` payload carries ``source`` (five-value
        axis) + ``confidence`` (four-value axis); missing or off-vocabulary
        axes are refused with ``OBS_INVALID_ENVELOPE`` at the envelope
        layer."""
        from domain.observation import EnvelopeError, EnvelopeErrorCode

        base = {
            "packet_count": 100,
            "byte_count": 18_800,
            "duration_ns": 1_000_000,
        }
        with pytest.raises(EnvelopeError) as missing:
            parse_envelope(
                _envelope("ts.packet_batch_observed", payload=dict(base))
            )
        assert missing.value.code is EnvelopeErrorCode.OBS_INVALID_ENVELOPE

        ok = dict(base, source="internal_parser", confidence="simulated")
        parse_envelope(_envelope("ts.packet_batch_observed", payload=ok))

        bad_axis = dict(base, source="internal_parser", confidence="high")
        with pytest.raises(EnvelopeError) as off_axis:
            parse_envelope(
                _envelope("ts.packet_batch_observed", payload=bad_axis)
            )
        assert off_axis.value.code is EnvelopeErrorCode.OBS_INVALID_ENVELOPE

    def test_ts_payload_keys_drive_catalog_derivations(self, journal):
        """The metric-catalog fixture contract (application/observation/
        metrics/catalog.py): ``ts.packet_batch_observed`` keys
        packet_count/byte_count/duration_ns derive ``ts.packet_rate`` and
        ``ts.bitrate``; ``ts.continuity_error`` derives the cumulative
        ``ts.continuity_error_total``. Feeding the fixture-shaped events
        through the REAL gateway → SQLite journal → checkpointed metrics
        consumer yields queryable series (IC §8 steps 2-5 with the TS
        producer slot; the production consumption posture, not a dict
        shortcut)."""
        session = "sess-obs-g-ts"
        connection = connect(journal.db_path)
        store = SqliteEventJournal(connection)
        gateway = EventGateway(journal=store, config=GatewayConfig())
        engine = MetricsEngine()
        consumer = JournalTailingConsumer(
            journal=store,
            checkpoints=SqliteCheckpointStore(connection),
            session_id=session,
            consumer_id="metrics-engine",
            handler=engine.handle_record,
        )

        batch = _envelope(
            "ts.packet_batch_observed",
            session_id=session,
            value_ns=0,
            payload={
                "packet_count": 1000,
                "byte_count": 188_000,
                "duration_ns": 50_000_000,  # 50 ms → 20k packets/s
                "source": "internal_parser",
                "confidence": "simulated",
            },
        )
        cc = _envelope(
            "ts.continuity_error",
            session_id=session,
            value_ns=1,
            payload={"source": "internal_parser", "confidence": "parsed"},
        )
        for envelope in (batch, cc):
            assert gateway.accept(envelope).outcome is IngestOutcome.ACCEPTED
        gateway.drain()
        assert consumer.catch_up() == 2

        result = _query_metrics(gateway, engine, session)
        names = {series.metric_name for series in result.series}
        assert {"ts.packet_rate", "ts.bitrate", "ts.continuity_error_total"} <= names
        rate = next(
            s for s in result.series if s.metric_name == "ts.packet_rate"
        )
        # 缺失 ≠ 零 (SPEC-302 §6.3): buckets without samples stay None —
        # the asserted point is the bucket the batch event landed in.
        filled = [p for p in rate.points if p.value is not None]
        assert filled and filled[0].value == pytest.approx(20_000.0)
        # The counter's cumulative sample face: one event → +1 (the query
        # bucket anchor semantics belong to the #50 service; the derivation
        # contract under test is the recorded sample).
        counter_samples = engine.samples(
            "ts.continuity_error_total",
            clock_domain=session_clock_domain(session),
            dimensions={"session_id": session},
        )
        assert counter_samples and counter_samples[-1].value == 1


def _query_metrics(gateway, engine, session: str):
    from application.observation.metrics.service import (
        MetricQueryRequest,
        MetricsService,
    )

    return MetricsService(engine).query(
        MetricQueryRequest(
            metric_names=(
                "ts.packet_rate",
                "ts.bitrate",
                "ts.continuity_error_total",
            ),
            start_ns=0,
            end_ns=10_000_000_000,
            step_ns=1_000_000_000,
            clock_domain=session_clock_domain(session),
            filters={"session_id": session},
        )
    )


# ============================================================================
# IC §2/#54 — diagnosis producer contract keys vs the shared fixture area
# ============================================================================


class TestDiagnosisProducerContract:
    """SPEC-306 §7 shared payload shape (#54 registration) — the
    publisher's envelope must pass the registry branch and the shared
    fixture constructor (``tests/_support/diagnosis_fixtures.py``) must
    produce registry-valid documents (one contract, two producers of the
    truth must not drift)."""

    def test_diagnosis_raised_shape_matches_registry_and_fixture(self):
        from domain.diagnosis.events import PRODUCER_ID as DIA_PRODUCER_ID
        from domain.diagnosis.events import raised_envelope
        from domain.diagnosis.model import (
            DiagnosisConfidence,
            DiagnosisSeverity,
        )
        from domain.diagnosis.report import (
            DiagnosisCandidate,
            EvidenceRef,
            ObservationRef,
        )

        candidate = DiagnosisCandidate(
            diagnosis_id=str(uuid.uuid4()),
            run_id="run-d",
            rule_id="DIA-PAT-MISSING",
            rule_version="1.0.0",
            code="PAT_WINDOW_MISSING",
            priority=10,
            severity=DiagnosisSeverity.ERROR,
            confidence=DiagnosisConfidence.HIGH,
            title="PAT window missing",
            summary="No PAT section in the observation window.",
            observation_refs=[
                ObservationRef(journal_seq=7, event_type="ts.psi_section_observed")
            ],
            affected_node_ids=["mux-0"],
            suggested_actions=["Inspect PID 0 repetition."],
            evidence=EvidenceRef(
                artifact_id=str(uuid.uuid4()), pid=0, packet_index=12
            ),
        )
        document = raised_envelope(
            candidate,
            session_id=SESSION,
            source_ns=1_000,
            observed_ns=1_005,
        )
        envelope = parse_envelope(document)
        assert envelope.event_type == "diagnosis.raised"
        assert envelope.producer.producer_id == DIA_PRODUCER_ID
        assert envelope.scope.run_id == "run-d"
        assert envelope.payload["rule_version"] == "1.0.0"
        assert envelope.payload["evidence"]["packet_index"] == 12

    def test_fixture_observation_envelopes_are_registry_valid(self):
        """The shared diagnosis-fixture ``ts.*`` documents carry the
        mandatory observation axes and parse cleanly — the #55/#58 shared
        fixture area and the registry agree (brief: fixture-contract key
        alignment)."""
        from tests._support.diagnosis_fixtures import (
            PSI_PID,
            _psi_payload,
            observation_envelope,
        )

        document = observation_envelope(
            event_type="ts.psi_section_observed",
            payload=_psi_payload(section="PAT", present=False, packet_index=12),
            pid=PSI_PID,
        )
        envelope = parse_envelope(document)
        assert envelope.payload["source"] == "internal_parser"
        assert envelope.payload["confidence"] == "parsed"


# ============================================================================
# IC §9 — non-negotiable boundaries, behavior face
# ============================================================================


class TestNonNegotiableBoundaries:
    """CONTRACT §9: Observation never calls producer mutation interfaces;
    ingest/evaluation never mutates the producer. Structural face =
    lint-imports C1-C9; this pins the RUNTIME behavior."""

    def test_ingest_and_consumption_never_mutate_simulation_state(
        self, journal
    ):
        """A live runtime session is observed (events ingested, journal
        consumed, queried) without any state change: revision, lifecycle
        and virtual time stay frozen across the whole observation pass
        (IC §9 — the observation plane is a downstream sink only)."""
        connection = connect(journal.db_path)
        store = SqliteEventJournal(connection)

        async def main() -> None:
            gateway = EventGateway(store, GatewayConfig())
            runtime = SimulationRuntime(event_sink=EventPublisher(gateway))
            await runtime.create_session(b.session_spec(session_id=SESSION))
            await runtime.validate_session(SESSION)
            await runtime.start(SESSION)
            await runtime.start_run(SESSION, run_id="r-1")
            gateway.drain()
            before = await runtime.get_snapshot(SESSION)

            # Full observation pass against the SAME journal the runtime
            # published into — metrics derivation + query reads only.
            engine = MetricsEngine()
            consumer = JournalTailingConsumer(
                journal=store,
                checkpoints=SqliteCheckpointStore(connection),
                session_id=SESSION,
                consumer_id="metrics-engine",
                handler=engine.handle_record,
            )
            consumer.catch_up()
            _query_metrics(gateway, engine, SESSION)

            after = await runtime.get_snapshot(SESSION)
            assert after.revision == before.revision
            assert after.lifecycle == before.lifecycle
            assert after.virtual_time_ns == before.virtual_time_ns

        asyncio.run(main())

    def test_registered_classification_functions_are_gateway_sole_source(
        self,
    ):
        """SPEC-301 §5 classification is imported, never re-implemented:
        the gateway binds ``is_coalescable`` from the frozen registry (the
        delivery-protected discipline is realized structurally — the
        coalesce key is computed ONLY for registry-coalescable types, so
        protected families can never be silently overwritten) — source
        inspection as the behavioral twin of the registry unit tests."""
        import inspect

        import application.observation.gateway as gateway_module

        source = inspect.getsource(gateway_module)
        assert "from domain.observation import EventEnvelope, is_coalescable" in source
        # no local copy of the classification sets (registry constants are
        # the single authority — a duplicated set here would drift)
        assert "COALESCABLE_EVENT_TYPES = {" not in source
        assert "DELIVERY_PROTECTED_EVENT_TYPES = {" not in source
