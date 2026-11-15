"""Shared WS test stack — gateway + journal + hub + app assembly (ticket #49).

The composition-root posture for SPEC-501 integration tests: the real SQLite
journal (``journal`` fixture), the #47 EventGateway with the hub attached as
its commit subscriber, and the SPEC-501 app factory. Tests drain the gateway
synchronously in the test thread where determinism allows; the flood test
runs its own dispatcher thread (the SPEC-300 §8 composition posture).
"""

from __future__ import annotations

import dataclasses
import typing

from adapters.storage.db import connect
from adapters.storage.journal import SqliteEventJournal
from application.observation.gateway import EventGateway
from domain.observation.registry import is_coalescable

from api.app import create_ws_app
from api.ws.hub import SessionHub, WsConfig


@dataclasses.dataclass
class WsStack:
    journal: SqliteEventJournal
    gateway: EventGateway
    hub: SessionHub
    app: typing.Any


def build_stack(
    journal_handle,
    *,
    config: WsConfig | None = None,
    session_directory: typing.Any = None,
) -> WsStack:
    jrn = SqliteEventJournal(connect(journal_handle.db_path, check_same_thread=False))
    gateway = EventGateway(journal=jrn)
    hub = SessionHub(
        journal=jrn,
        coalescable_of=is_coalescable,
        config=config,
        session_directory=session_directory,
    )
    hub.attach_gateway(gateway)
    app = create_ws_app(hub=hub)
    return WsStack(journal=jrn, gateway=gateway, hub=hub, app=app)


def publish(
    gateway: EventGateway,
    seq_source: list[int],
    *,
    event_type: str = "simulation.run_started",
    session_id: str = "sess-1",
    run_id: str | None = None,
    producer_id: str = "sim-engine",
) -> dict:
    """Publish one raw envelope through the gateway; returns the raw dict.

    ``seq_source`` tracks how many events this test session has pushed so
    tests can build deterministic scope values without touching journal
    internals (the seq itself is stamped by the journal at drain).
    """
    from tests.unit.application.observation.test_gateway_accept import _raw_envelope

    index = len(seq_source)
    seq_source.append(index)
    run = run_id if run_id is not None else f"run-{index}"
    raw = _raw_envelope(
        event_type=event_type, session_id=session_id, producer_id=producer_id
    )
    raw["event_id"] = f"evt-{producer_id}-{index}"
    raw["scope"]["run_id"] = run
    raw["scope"]["session_id"] = session_id
    result = gateway.accept(raw)
    assert result.outcome.value == "accepted", result
    return raw


def drain_committed(gateway: EventGateway) -> int:
    """Commit everything queued (test-thread dispatcher slice)."""
    return gateway.drain()
