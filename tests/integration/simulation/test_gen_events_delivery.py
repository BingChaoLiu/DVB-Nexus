"""gen.* / t2mi.* / bbframe.* / biss.* delivery through the registry-stub
path (ticket #128, SPEC-303 §Phase2, ruling §10-7 — integration half).

The unit layer (``tests/unit/simulation/test_gen_events_emission.py``)
pins the payload shapes and the guard's default world without fixtures;
this module proves the FULL envelope path end-to-end: with the registry
stubbed to accept the Phase 2 types, the envelopes pass
``parse_envelope`` + ``ensure_publishable`` and reach the sink — exactly
the shapes #129 will register.
"""

from __future__ import annotations

import asyncio

import pytest

pytestmark = pytest.mark.integration

from domain.observation import parse_envelope
from simulation.events import SimulationEventEmitter

from tests.unit.simulation.runtime.test_events import RecordingSink

PHASE2_EVENT_TYPES = (
    "gen.stage_started",
    "gen.stage_completed",
    "gen.packet_sampled",
    "t2mi.stage_summary",
    "bbframe.recovery_failed",
    "biss.scramble_applied",
)


def _stub_registry(monkeypatch: pytest.MonkeyPatch, types) -> None:
    """Registry stub path: the lookup accepts exactly ``types``.

    Patched at BOTH consumption points — the emitter's guard reads
    ``simulation.events.is_registered`` while the envelope's
    ``validate_event_type`` reads the registry module's own global — so
    the stubbed types take the full parse_envelope path.
    """
    lookup = lambda event_type: event_type in types  # noqa: E731
    monkeypatch.setattr("simulation.events.is_registered", lookup)
    monkeypatch.setattr("domain.observation.registry.is_registered", lookup)


class TestRegistryStubEnvelopePath:
    """Registry stub path: stubbed types take the FULL envelope path."""

    @pytest.mark.parametrize(
        ("event_type", "payload"),
        [
            ("gen.stage_started", {"layer": "TS"}),
            ("gen.stage_completed", {"layer": "BBFRAME", "item_count": 12}),
            (
                "gen.packet_sampled",
                {
                    "layer": "T2MI",
                    "packet_index": 3,
                    "byte_size": 213,
                    "sha256": "a" * 64,
                },
            ),
            (
                "t2mi.stage_summary",
                {
                    "packet_count": 3,
                    "padding_count": 0,
                    "packet_type_distribution": {"bbframe": 3},
                    "plp_distribution": {"0": 3},
                },
            ),
            (
                "bbframe.recovery_failed",
                {"failure_count": 1, "first_failed_frame_index": 4},
            ),
            (
                "biss.scramble_applied",
                {
                    "pid_scope": [256],
                    "packet_count": 5,
                    "key_fingerprint": "sha256:" + "b" * 16,
                    "mutation_log_ref": "artifact-1",
                    "mode": "1",
                },
            ),
        ],
    )
    def test_phase2_shapes_publish_through_the_real_envelope(
        self, monkeypatch: pytest.MonkeyPatch, event_type: str, payload: dict
    ) -> None:
        _stub_registry(monkeypatch, PHASE2_EVENT_TYPES)
        sink = RecordingSink()
        emitter = SimulationEventEmitter(sink, wall_ns_source=lambda: 1)
        document = emitter.run_event(
            event_type,
            "session-1",
            "run-1",
            virtual_time_ns=7,
            payload=payload,
        )
        assert document is not None
        published = sink.events[0]
        assert published["event_type"] == event_type
        assert published["payload"] == payload
        # parse_envelope conformance is the construction guarantee.
        assert parse_envelope(published).event_type == event_type

    def test_runtime_emits_run_scoped_phase2_events(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from simulation.runtime import SimulationRuntime

        _stub_registry(monkeypatch, ["gen.stage_completed"])
        sink = RecordingSink()
        runtime = SimulationRuntime(event_sink=sink)

        async def main() -> None:
            await runtime.create_session(_spec("ev-gen-1"))
            await runtime.validate_session("ev-gen-1")
            await runtime.start("ev-gen-1")
            run_view = await runtime.start_run("ev-gen-1")
            runtime.emit_generation_event(
                "ev-gen-1",
                run_view.run_id,
                "gen.stage_completed",
                payload={"layer": "T2MI", "item_count": 4},
            )
            await runtime.complete_run("ev-gen-1", run_view.run_id)

        asyncio.run(main())
        assert "gen.stage_completed" in sink.types()
        emitted = next(
            event
            for event in sink.events
            if event["event_type"] == "gen.stage_completed"
        )
        assert emitted["payload"] == {"layer": "T2MI", "item_count": 4}
        assert isinstance(emitted["scope"]["run_id"], str)
        assert emitted["scope"]["run_id"]


def _spec(session_id: str):
    from simulation.clock import SimulationClockConfig
    from simulation.runtime import SimulationSessionSpec
    from simulation.state import TopologyGraph

    return SimulationSessionSpec(
        session_id=session_id,
        topology=TopologyGraph(
            topology_id="topo-1", revision=1, nodes=(), connections=()
        ),
        seed=1,
        deterministic=True,
        clock_config=SimulationClockConfig(mode="deterministic"),
    )
