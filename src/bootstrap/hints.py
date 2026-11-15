"""Hub hint bindings — the SPEC-305 §8 five topics wired to the real
``SessionHub`` (ticket #53, 裁定 C/J).

The application plane stays transport-agnostic: it publishes through the
``ObservationHintPublisher`` protocol (and #52's ``AlertHintEmitter``
port); this module binds those ports to the ``api.ws.hub.SessionHub``'s
``publish_hint`` generic channel — no hub-side structural change. Hints
are best-effort record-state pointers (SPEC-301 §5 / SPEC-305 §8): the
backpressure layer may drop them, the journal frames stay authoritative,
and every recovery goes through REST pulls.

Production emission points (declared per the dispatch's 申报 requirement):

- ``observation.event_appended`` — a gateway commit subscriber installed
  by the composition root (one pointer per committed event);
- ``observation.alert_changed`` — #52's ``AlertService`` hint port bound
  here (:class:`HubAlertHintEmitter`);
- ``observation.metric_updated`` — emitted by the stack driver after a
  metrics-consumer tick that advanced the checkpoint (see
  ``bootstrap.app.ProductionStack.process_observation``);
- ``observation.health_changed`` — emitted by the query service's health
  face when the roll-up overall status moves (application side);
- ``observation.export_progress`` — emitted by the export task registry on
  task completion (application side).
"""

from __future__ import annotations

from typing import Any, Protocol

from application.observation.alerts.service import AlertHint


class ObservationHintPublisher(Protocol):
    """The composition-side hint face (:class:`HubHintPublisher`)."""

    def publish(self, session_id: str, topic: str, data: dict[str, Any]) -> None: ...


class HubHintPublisher:
    """``ObservationHintPublisher`` adapter over the real hub."""

    def __init__(self, hub: ObservationHintPublisher) -> None:
        self._hub = hub

    def publish(self, session_id: str, topic: str, data: dict[str, Any]) -> None:
        # publish_hint validates the topic against the SPEC-305 §8 five;
        # route-level failures are transport contract errors — raise.
        self._hub.publish_hint(session_id, topic, data)


class HubAlertHintEmitter:
    """#52 ``AlertHintEmitter`` port → the real hub (裁定 C). The hint is a
    projection of the persisted record; emission failures propagate to the
    service's counter (never break the record-authority write path)."""

    def __init__(self, hub: ObservationHintPublisher) -> None:
        self._hub = hub

    def emit(self, hint: AlertHint) -> None:
        self._hub.publish_hint(hint.session_id, hint.topic, hint.model_dump())


class EventAppendedHintSubscriber:
    """Gateway commit subscriber emitting ``observation.event_appended``.

    Installed AFTER the hub's own commit fan-out (journal frames go out
    first — the hint is the pull pointer, not the transport record).
    Subscriber exceptions are counted by the gateway and never break
    ingestion (SPEC-300 §7).
    """

    TOPIC = "observation.event_appended"

    def __init__(self, hub: ObservationHintPublisher) -> None:
        self._hub = hub

    def __call__(self, stamped: dict[str, Any]) -> None:
        scope = stamped.get("scope") or {}
        session_id = scope.get("session_id")
        if not session_id:
            return
        self._hub.publish(
            session_id,
            self.TOPIC,
            {
                "journal_seq": stamped.get("journal_seq"),
                "event_id": stamped.get("event_id"),
                "event_type": stamped.get("event_type"),
            },
        )


__all__ = [
    "EventAppendedHintSubscriber",
    "HubAlertHintEmitter",
    "HubHintPublisher",
    "ObservationHintPublisher",
]
