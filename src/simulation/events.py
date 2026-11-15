"""SPEC-200 §7.4 — SPEC-301 event emission builders (ticket #41).

Producers mark **identity and the dual clock only** (CONTEXT.md 事件信封):
``event_id`` is uuid4 opaque (ADR-0006 decision 3), the producer block
carries id/version/instance, ``time.source`` is the session's virtual clock
(``sim:<session_id>`` domain, SPEC-300 §6 clock-domain vocabulary) and
``time.observed`` is the ingestion wall clock (``wall:utc``).
``journal_seq`` is NEVER filled by the producer — the gateway stamps the
total order at durable append (ADR-0006 decision 2); every built envelope
passes :func:`domain.observation.parse_envelope` *before* it is handed to
the sink, so a non-conforming event cannot leave the runtime, and
``ensure_publishable`` guards the publish view.

Event types come exclusively from the #46 frozen registry families
(``simulation.session_*`` / ``simulation.run_*``); no fourth envelope, no
invented types, no producer-side total-order fields.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Mapping

from domain.observation import new_event_id, parse_envelope
from simulation.lifecycle import LifecycleState

__all__ = [
    "PRODUCER_ID",
    "PRODUCER_VERSION",
    "SESSION_EVENT_PAYLOAD_KEY",
    "SimulationEventEmitter",
    "WALL_CLOCK_DOMAIN",
    "session_clock_domain",
]

#: Producer identity (SIMULATION-INTEGRATION-CONTRACT §4 producer duty).
PRODUCER_ID = "simulation-runtime"

#: Bumped with the simulation package's spec baseline.
PRODUCER_VERSION = "0.5.0"

#: The lifecycle-state payload key shared by every session_* event.
SESSION_EVENT_PAYLOAD_KEY = "lifecycle"

#: Ingestion observation domain (SPEC-300 §6 vocabulary).
WALL_CLOCK_DOMAIN = "wall:utc"

#: Virtual-clock domain prefix: ``sim:<session_id>`` (SPEC-300 §6: values
#: are comparable only within the same session and clock epoch).
SESSION_CLOCK_DOMAIN_PREFIX = "sim:"


def session_clock_domain(session_id: str) -> str:
    """The session-scoped virtual clock domain name."""
    return f"{SESSION_CLOCK_DOMAIN_PREFIX}{session_id}"


class SimulationEventEmitter:
    """Builds, schema-validates and hands off lifecycle/run events.

    ``sink`` is the structural :class:`simulation.runtime.SessionEventSink`
    seam — the composition root injects the #47 gateway/publisher face.
    ``wall_ns_source`` follows the SPEC-201 injection discipline (tests
    inject exact integers; production passes nothing → ``time.time_ns``).
    """

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

    def session_event(
        self,
        event_type: str,
        session_id: str,
        *,
        virtual_time_ns: int,
        lifecycle: LifecycleState | None = None,
        extra_payload: Mapping[str, Any] | None = None,
        severity: str = "info",
    ) -> dict[str, Any] | None:
        """Build one session-scoped event and publish through the sink."""
        payload: dict[str, Any] = {}
        if lifecycle is not None:
            payload[SESSION_EVENT_PAYLOAD_KEY] = lifecycle.value
        if extra_payload:
            payload.update(extra_payload)
        return self._emit(
            event_type,
            session_id=session_id,
            run_id=None,
            virtual_time_ns=virtual_time_ns,
            payload=payload,
            severity=severity,
        )

    def run_event(
        self,
        event_type: str,
        session_id: str,
        run_id: str,
        *,
        virtual_time_ns: int,
        payload: Mapping[str, Any] | None = None,
        severity: str = "info",
    ) -> dict[str, Any] | None:
        """Build one run-scoped event (``scope.run_id`` attribution)."""
        return self._emit(
            event_type,
            session_id=session_id,
            run_id=run_id,
            virtual_time_ns=virtual_time_ns,
            payload=dict(payload or {}),
            severity=severity,
        )

    # --- internals ------------------------------------------------------------

    def _emit(
        self,
        event_type: str,
        *,
        session_id: str,
        run_id: str | None,
        virtual_time_ns: int,
        payload: dict[str, Any],
        severity: str,
    ) -> dict[str, Any] | None:
        document = {
            "schema_version": "1.0",
            "event_id": new_event_id(),
            "event_type": event_type,
            "producer": {
                "producer_id": PRODUCER_ID,
                "producer_version": PRODUCER_VERSION,
                "instance_id": self._instance_id,
            },
            "scope": {
                "tenant_id": "local",
                "session_id": session_id,
                "run_id": run_id,
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
            "tags": ["simulation"],
        }
        # Schema conformance is a construction guarantee (REQ-SIM-200-007):
        # refuse to hand a non-conforming document to the sink.
        envelope = parse_envelope(document)
        envelope.ensure_publishable()
        if self._sink is None:
            return None
        self._sink.publish(document)
        return document
