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

import logging
import time
from typing import Any, Callable, Mapping

from domain.observation import new_event_id, parse_envelope
from domain.observation.registry import is_registered
from simulation.lifecycle import LifecycleState

__all__ = [
    "PRODUCER_ID",
    "PRODUCER_VERSION",
    "SESSION_EVENT_PAYLOAD_KEY",
    "SimulationEventEmitter",
    "WALL_CLOCK_DOMAIN",
    "session_clock_domain",
]

_LOGGER = logging.getLogger(__name__)

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

    def fault_event(
        self,
        event_type: str,
        session_id: str,
        run_id: str,
        *,
        virtual_time_ns: int,
        fault_id: str,
        fault_type: str,
        target_node_id: str | None,
        target_pid: int | None,
        payload: Mapping[str, Any] | None = None,
        severity: str = "info",
    ) -> dict[str, Any] | None:
        """Build one ``fault.*`` lifecycle event and publish it (ticket #56).

        SPEC-204 §9: ``scope.run_id`` attribution, correlation addressing by
        ``fault_id`` + ``node_id`` + ``pid`` (the ADR-0006 decision 3 dual
        target form), and the registered SPEC-204 §9 payload shape
        (fault_id / fault_type / injection index / before-after summary
        pointer). Everything else follows the shared ``_emit`` discipline:
        parse_envelope is a construction guarantee, ``journal_seq`` stays
        unassigned (gateway-stamped), and the fault family is
        DELIVERY_PROTECTED (registry constant — never coalesced or dropped).
        """
        return self._emit(
            event_type,
            session_id=session_id,
            run_id=run_id,
            virtual_time_ns=virtual_time_ns,
            payload=dict(payload or {}),
            severity=severity,
            correlation={
                "trace_id": None,
                "span_id": None,
                "parent_event_id": None,
                "fault_id": fault_id,
                "node_id": target_node_id,
                "port_id": None,
                "service_id": None,
                "pid": target_pid,
            },
            tags=["simulation", "fault"],
        )

    def state_event(
        self,
        event_type: str,
        session_id: str,
        run_id: str,
        *,
        virtual_time_ns: int,
        node_id: str | None,
        payload: Mapping[str, Any] | None = None,
        severity: str = "info",
    ) -> dict[str, Any] | None:
        """Build one run-scoped, node-addressed state event (ticket #164).

        SPEC-303 §Phase3 state snapshots: ``scope.run_id`` attribution and
        correlation addressing by ``node_id`` alone (the ADR-0006
        decision 3 node-level form — the observed node, never a pid and
        never a fault id).  Everything else follows the shared ``_emit``
        discipline: parse_envelope is a construction guarantee,
        ``journal_seq`` stays unassigned (gateway-stamped) and the
        unregistered-type guard skips before envelope construction.
        """
        return self._emit(
            event_type,
            session_id=session_id,
            run_id=run_id,
            virtual_time_ns=virtual_time_ns,
            payload=dict(payload or {}),
            severity=severity,
            correlation={
                "trace_id": None,
                "span_id": None,
                "parent_event_id": None,
                "fault_id": None,
                "node_id": node_id,
                "port_id": None,
                "service_id": None,
                "pid": None,
            },
            tags=["simulation", "state"],
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
        correlation: Mapping[str, Any] | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any] | None:
        # Unregistered-type guard (ticket #128, ruling §10-7): the Phase 2
        # namespaces (gen.* / t2mi.* / bbframe.* / biss.*) are emitted by
        # the layered pipeline before #129 lands their registry entries.
        # ``parse_envelope`` would raise ``EnvelopeError`` on them, so the
        # guard skips delivery BEFORE envelope construction — debug-logged,
        # never silent, never a crash into the run outcome.  When #129
        # registers the types, ``is_registered`` passes them through and
        # the guard becomes a no-op (verified by both test paths in
        # tests/unit/simulation/test_gen_events_emission.py).
        if not is_registered(event_type):
            _LOGGER.debug(
                "event type %r is not in the observation registry "
                "(SPEC-301 section 4) — delivery skipped until the type "
                "is registered (#129); payload keys: %s",
                event_type,
                sorted(payload),
            )
            return None
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
            "correlation": dict(correlation) if correlation is not None else None,
            "severity": severity,
            "payload": payload,
            "tags": tags if tags is not None else ["simulation"],
        }
        # Schema conformance is a construction guarantee (REQ-SIM-200-007):
        # refuse to hand a non-conforming document to the sink.
        envelope = parse_envelope(document)
        envelope.ensure_publishable()
        if self._sink is None:
            return None
        self._sink.publish(document)
        return document
