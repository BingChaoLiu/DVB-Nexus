"""fault.* envelope emission through the #41 emitter seam (ticket #56, 裁定 2).

SPEC-204 §8/§9: the four lifecycle states SCHEDULED → ACTIVE → APPLIED →
REMOVED map onto the four registered ``fault.*`` event codes; the payload
carries fault_id / fault_type / injection index (+ the L1 confirmation
indexes on ``fault.applied``) and the correlation block addresses the
target stream (``fault_id`` + ``node_id`` + ``pid`` — ADR-0006 decision 3
dual form). ``scope.run_id`` attributes every fault event to its run.

Discipline (identical to the #41 session/run emitters): producers mark
identity and the dual clock only; every built document passes
``domain.observation.parse_envelope`` BEFORE it reaches the sink, and
``ensure_publishable`` guards the publish view (no producer-side
``journal_seq``). Producer identity stays ``simulation-runtime`` — the
fault execution is part of the simulation runtime's TS orchestration
(recorded in the ticket #56 report).
"""

from __future__ import annotations

import asyncio

import pytest

pytestmark = pytest.mark.unit

from domain.observation import parse_envelope
from domain.observation.registry import (
    FAULT_EVENT_TYPES,
    is_delivery_protected,
    validate_payload,
)
from simulation.events import (
    PRODUCER_ID,
    PRODUCER_VERSION,
    SimulationEventEmitter,
    session_clock_domain,
)
from simulation.errors import SessionNotFoundError
from simulation.runtime import SimulationRuntime

from tests.unit.simulation.runtime import _sim_c_builders as b


class RecordingSink:
    """Minimal SessionEventSink double (records validated envelope dicts)."""

    def __init__(self) -> None:
        self.events: list[dict] = []

    def publish(self, event) -> None:
        self.events.append(dict(event))

    def types(self) -> list[str]:
        return [event["event_type"] for event in self.events]


def _payload(**overrides):
    payload = {
        "fault_id": "fd000000-0000-4000-8000-000000000001",
        "fault_type": "CC_DISCONTINUITY",
        "injection_index": 50,
        "expected_observations": ["ts.continuity_error"],
        "applied_packet_indexes": [50],
        "mutation_log_ref": "mutation-log:fd000000#50",
    }
    payload.update(overrides)
    return payload


class TestEmitterFaultEvent:
    """``SimulationEventEmitter.fault_event`` — the additive seam (#41 face)."""

    def test_fault_event_passes_envelope_schema_and_registry(self) -> None:
        sink = RecordingSink()
        emitter = SimulationEventEmitter(sink, wall_ns_source=lambda: 10**9)
        document = emitter.fault_event(
            "fault.injected",
            "sess-fault-1",
            "run-fault-1",
            virtual_time_ns=5_000,
            fault_id="fd000000-0000-4000-8000-000000000001",
            fault_type="CC_DISCONTINUITY",
            target_node_id="demux-0",
            target_pid=0x0100,
            payload={
                "fault_id": "fd000000-0000-4000-8000-000000000001",
                "fault_type": "CC_DISCONTINUITY",
                "injection_index": 50,
                "expected_observations": ["ts.continuity_error"],
            },
        )

        assert document is not None
        assert sink.types() == ["fault.injected"]
        envelope = parse_envelope(document)
        envelope.ensure_publishable()  # producers never fill journal_seq
        assert envelope.scope.run_id == "run-fault-1"
        assert envelope.scope.session_id == "sess-fault-1"
        assert envelope.correlation is not None
        assert envelope.correlation.fault_id == (
            "fd000000-0000-4000-8000-000000000001"
        )
        assert envelope.correlation.node_id == "demux-0"
        assert envelope.correlation.pid == 0x0100
        # Dual clock: source = the session virtual domain (injected value),
        # observed = the injected wall reading.
        assert envelope.time.source.value_ns == 5_000
        assert envelope.time.source.clock_domain == session_clock_domain(
            "sess-fault-1"
        )
        assert envelope.time.observed.value_ns == 10**9
        # Producer identity: the simulation runtime face (report-recorded).
        assert envelope.producer.producer_id == PRODUCER_ID
        assert envelope.producer.producer_version == PRODUCER_VERSION

    def test_every_fault_family_event_validates(self) -> None:
        sink = RecordingSink()
        emitter = SimulationEventEmitter(sink, wall_ns_source=lambda: 1)
        for index, event_type in enumerate(sorted(FAULT_EVENT_TYPES)):
            emitter.fault_event(
                event_type,
                "sess-fault-2",
                "run-fault-2",
                virtual_time_ns=index,
                fault_id="fd000000-0000-4000-8000-000000000002",
                fault_type="PAT_MISSING",
                target_node_id="demux-0",
                target_pid=0,
                payload=_payload(
                    fault_id="fd000000-0000-4000-8000-000000000002",
                    fault_type="PAT_MISSING",
                ),
            )
        assert sink.types() == sorted(FAULT_EVENT_TYPES)
        for document in sink.events:
            # The registry branch (ticket #56) accepts every emitted payload.
            validate_payload(document["event_type"], document["payload"])
            parse_envelope(document)

    def test_none_sink_still_refuses_nonconforming_construction(self) -> None:
        # The #41 emitter posture (session_event/run_event): a ``None`` sink
        # means build-and-validate with no publish (returns ``None``) — the
        # parse_envelope construction guarantee runs BEFORE the sink check,
        # so an unregistered/non-conforming document cannot be built either.
        emitter = SimulationEventEmitter(None, wall_ns_source=lambda: 1)
        assert (
            emitter.fault_event(
                "fault.cleared",
                "sess-fault-3",
                "run-fault-3",
                virtual_time_ns=1,
                fault_id="fd000000-0000-4000-8000-000000000003",
                fault_type="PAT_MISSING",
                target_node_id="demux-0",
                target_pid=0,
                payload={
                    "fault_id": "fd000000-0000-4000-8000-000000000003",
                    "fault_type": "PAT_MISSING",
                    "injection_index": 0,
                },
            )
            is None
        )
        with pytest.raises(Exception):
            emitter.fault_event(
                "fault.cleared",
                "sess-fault-3",
                "run-fault-3",
                virtual_time_ns=1,
                fault_id="fd000000-0000-4000-8000-000000000003",
                fault_type="PAT_MISSING",
                target_node_id="demux-0",
                target_pid=0,
                payload={},  # missing every registered obligation
            )

    def test_nonconforming_payload_is_refused_at_construction(self) -> None:
        emitter = SimulationEventEmitter(None, wall_ns_source=lambda: 1)
        with pytest.raises(Exception):
            emitter.fault_event(
                "fault.injected",
                "sess-fault-4",
                "run-fault-4",
                virtual_time_ns=1,
                fault_id="fd000000-0000-4000-8000-000000000004",
                fault_type="PAT_MISSING",
                target_node_id="demux-0",
                target_pid=0,
                payload={"fault_id": "only-id"},  # missing the rest
            )


class TestRuntimeEmitFaultEvent:
    """``SimulationRuntime.emit_fault_event`` — the session-clock anchor."""

    def test_emission_uses_the_session_virtual_clock(self) -> None:
        async def main() -> None:
            sink = RecordingSink()
            runtime = SimulationRuntime(event_sink=sink)
            await runtime.create_session(b.session_spec(session_id="fe-1"))
            await runtime.validate_session("fe-1")
            await runtime.start("fe-1")
            baseline_types = list(sink.types())
            assert "simulation.session_started" in baseline_types

            runtime.emit_fault_event(
                "fe-1",
                "run-fe-1",
                "fault.injected",
                fault_id="fd000000-0000-4000-8000-000000000005",
                fault_type="CC_DISCONTINUITY",
                target_node_id="demux-0",
                target_pid=0x0100,
                payload={
                    "fault_id": "fd000000-0000-4000-8000-000000000005",
                    "fault_type": "CC_DISCONTINUITY",
                    "injection_index": 50,
                    "expected_observations": ["ts.continuity_error"],
                },
            )

            assert sink.types()[-1] == "fault.injected"
            document = sink.events[-1]
            envelope = parse_envelope(document)
            # The virtual-time anchor is the SESSION's clock, not a wall read.
            assert (
                envelope.time.source.clock_domain
                == session_clock_domain("fe-1")
            )
            assert envelope.time.source.value_ns >= 0

        asyncio.run(main())

    def test_unknown_session_raises_session_not_found(self) -> None:
        sink = RecordingSink()
        runtime = SimulationRuntime(event_sink=sink)
        with pytest.raises(SessionNotFoundError):
            runtime.emit_fault_event(
                "sess-ghost",
                "run-ghost",
                "fault.injected",
                fault_id="fd000000-0000-4000-8000-000000000006",
                fault_type="PAT_MISSING",
                target_node_id="demux-0",
                target_pid=0,
                payload={
                    "fault_id": "fd000000-0000-4000-8000-000000000006",
                    "fault_type": "PAT_MISSING",
                    "injection_index": 0,
                    "expected_observations": ["ts.psi_section_observed"],
                },
            )
        assert sink.events == []


class TestDeliveryProtection:
    """The fault family + the verdict stay delivery-protected (§5)."""

    @pytest.mark.parametrize(
        "event_type", sorted(FAULT_EVENT_TYPES | {"recovery.verification_completed"})
    )
    def test_fault_family_and_verdict_are_delivery_protected(
        self, event_type
    ):
        assert is_delivery_protected(event_type)
