"""SPEC-205 §5 — scenario step events on the ADR-0006 envelope (SIM-F #45).

场景进度经包级契约发射 ``scenario.step_started/step_completed``（SPEC-205
§5；注册表权威 = SPEC-301 §4 的 #46 冻结清单）。Producers mark identity
and the dual clock only (CONTEXT.md 事件信封): ``event_id`` uuid4 opaque,
``journal_seq`` never filled by the producer, every built document passes
:func:`domain.observation.parse_envelope` before it reaches the sink — no
fourth envelope, no invented types (``scope.scenario_id`` is the SPEC-301
§3 attribution field).

Sink is the structural ``publish`` protocol (same seam shape as
:attr:`simulation.runtime.SessionEventSink`); ``None`` = build-and-validate
only.
"""

from __future__ import annotations

import time
from typing import Any, Callable

from domain.observation import new_event_id, parse_envelope
from simulation.events import (
    PRODUCER_VERSION,
    WALL_CLOCK_DOMAIN,
    session_clock_domain,
)

__all__ = [
    "SCENARIO_STEP_EVENT_TYPES",
    "SCENARIO_STEP_PAYLOAD_KEY",
    "SCENARIO_PRODUCER_ID",
    "ScenarioStepEmitter",
]

#: Producer identity for the scenario engine face.
SCENARIO_PRODUCER_ID = "simulation-scenario"

#: The registered scenario step event types (SPEC-301 §4 registry).
SCENARIO_STEP_EVENT_TYPES = frozenset(
    {"scenario.step_started", "scenario.step_completed"}
)

#: The payload key carrying the scenario step identity.
SCENARIO_STEP_PAYLOAD_KEY = "step_id"


class ScenarioStepEmitter:
    """Build, schema-validate and publish ``scenario.step_*`` envelopes."""

    def __init__(
        self,
        sink: Any | None,
        *,
        instance_id: str | None = None,
        wall_ns_source: Callable[[], int] | None = None,
    ) -> None:
        self._sink = sink
        self._instance_id = instance_id or str(new_event_id())
        self._wall_ns_source: Callable[[], int] = (
            wall_ns_source if wall_ns_source is not None else time.time_ns
        )

    def step_event(
        self,
        event_type: str,
        *,
        session_id: str,
        scenario_id: str,
        step_id: str,
        virtual_time_ns: int,
        run_id: str | None = None,
        extra_payload: dict[str, Any] | None = None,
        severity: str = "info",
    ) -> dict[str, Any] | None:
        """Build one scenario step event and publish through the sink.

        Returns the built document (even when the sink is ``None`` — the
        document passed :func:`parse_envelope` and is publishable), or
        ``None`` only when the sink declined (it returns ``None``).
        """
        payload: dict[str, Any] = {SCENARIO_STEP_PAYLOAD_KEY: step_id}
        if extra_payload:
            payload.update(extra_payload)
        document: dict[str, Any] = {
            "schema_version": "1.0",
            "event_id": str(new_event_id()),
            "event_type": event_type,
            "producer": {
                "producer_id": SCENARIO_PRODUCER_ID,
                "producer_version": PRODUCER_VERSION,
                "instance_id": self._instance_id,
            },
            "scope": {
                "tenant_id": "local",
                "session_id": session_id,
                "run_id": run_id,
                "scenario_id": scenario_id,
            },
            "time": {
                "source": {
                    "value_ns": virtual_time_ns,
                    "clock_domain": session_clock_domain(session_id),
                    "clock_epoch": 0,
                },
                "observed": {
                    "value_ns": self._wall_ns_source(),
                    "clock_domain": WALL_CLOCK_DOMAIN,
                    "clock_epoch": 0,
                },
            },
            "correlation": None,
            "severity": severity,
            "payload": payload,
            "tags": ["simulation", "scenario"],
        }
        # Registry + schema conformance is a construction guarantee: an
        # unregistered or non-conforming event never reaches the sink.
        envelope = parse_envelope(document)
        envelope.ensure_publishable()
        if self._sink is None:
            return document
        self._sink.publish(document)
        return document
