"""SPEC-205 §5 scenario step events (SIM-F #45).

场景进度经包级契约发射 ``scenario.step_started/step_completed``（ADR-0006
信封，SPEC-301 §4 注册表权威）—— no fourth envelope; the payload rides the
#46 frozen registry and ``scope.scenario_id`` attribution.
"""

from __future__ import annotations

import pytest

from domain.observation import parse_envelope
from simulation.scenario.events import (
    SCENARIO_STEP_EVENT_TYPES,
    SCENARIO_STEP_PAYLOAD_KEY,
    ScenarioStepEmitter,
)

from ._scenario_builders import SCENARIO_ID


class _RecordingSink:
    def __init__(self) -> None:
        self.published: list[dict] = []

    def publish(self, event: dict) -> None:
        self.published.append(event)


@pytest.fixture()
def sink() -> _RecordingSink:
    return _RecordingSink()


def test_step_events_registered_names_only():
    assert SCENARIO_STEP_EVENT_TYPES == frozenset(
        {"scenario.step_started", "scenario.step_completed"}
    )


def test_step_started_round_trips_through_the_envelope(sink):
    emitter = ScenarioStepEmitter(sink, wall_ns_source=lambda: 1_000)
    document = emitter.step_event(
        "scenario.step_started",
        session_id="8b6ad63c-1e2f-4a1b-9d16-8e0f0d0cbeef",
        scenario_id=SCENARIO_ID,
        step_id="step-generate",
        virtual_time_ns=42,
    )
    assert document is not None
    envelope = parse_envelope(document)
    assert envelope.event_type == "scenario.step_started"
    assert envelope.scope.scenario_id == SCENARIO_ID
    assert envelope.payload[SCENARIO_STEP_PAYLOAD_KEY] == "step-generate"
    assert sink.published == [document]


def test_step_completed_and_no_sink_returns_built_document():
    emitter = ScenarioStepEmitter(None, wall_ns_source=lambda: 2_000)
    document = emitter.step_event(
        "scenario.step_completed",
        session_id="8b6ad63c-1e2f-4a1b-9d16-8e0f0d0cbeef",
        scenario_id=SCENARIO_ID,
        step_id="step-generate",
        virtual_time_ns=43,
    )
    assert document is not None
    assert parse_envelope(document).event_type == "scenario.step_completed"


def test_unregistered_event_type_refused(sink):
    emitter = ScenarioStepEmitter(sink, wall_ns_source=lambda: 3_000)
    with pytest.raises(Exception):
        emitter.step_event(
            "scenario.step_failed",  # not in the SPEC-301 registry
            session_id="8b6ad63c-1e2f-4a1b-9d16-8e0f0d0cbeef",
            scenario_id=SCENARIO_ID,
            step_id="step-x",
            virtual_time_ns=1,
        )
    assert sink.published == []
