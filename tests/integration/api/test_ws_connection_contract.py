"""WS connection contract — SPEC-501 §3/§4/§8 (REQ-WS-501-001/002), integration.

Route ``/ws/v1/sessions/{session_id}``, single connection single session,
the §8 close-code matrix (4404 session unknown/disposed, 4400 subscribe
mismatch), the §4.2 upstream ping/pong, and hint frames pointing at REST
pull (§4.1). Real stack: SQLite journal + EventGateway + hub + factory app.
"""

import pytest
from fastapi.testclient import TestClient

from api.ws.frames import CLOSE_SESSION_UNKNOWN, CLOSE_SUBSCRIBE_MISMATCH

from tests.integration.api.ws_stack import build_stack, drain_committed, publish


class _Directory:
    """In-memory session directory stand-in (simulation owns the real one)."""

    def __init__(self, sessions: dict[str, str]) -> None:
        self._sessions = dict(sessions)

    def status(self, session_id: str) -> str | None:
        return self._sessions.get(session_id)


def _subscribe(ws, session_id: str = "sess-1", last_journal_seq=None) -> None:
    msg = {"type": "subscribe", "session_id": session_id}
    if last_journal_seq is not None:
        msg["last_journal_seq"] = last_journal_seq
    ws.send_json(msg)


# --- route + session directory (REQ-WS-501-001) --------------------------------


def test_unknown_session_closes_4404(journal) -> None:
    stack = build_stack(journal, session_directory=_Directory({}))
    with TestClient(stack.app) as client, client.websocket_connect(
        "/ws/v1/sessions/nope"
    ) as ws:
        with pytest.raises(Exception) as excinfo:
            ws.receive_json()
        assert excinfo.value.code == CLOSE_SESSION_UNKNOWN


def test_disposed_session_closes_4404(journal) -> None:
    stack = build_stack(
        journal, session_directory=_Directory({"sess-1": "DISPOSED"})
    )
    with TestClient(stack.app) as client, client.websocket_connect(
        "/ws/v1/sessions/sess-1"
    ) as ws:
        with pytest.raises(Exception) as excinfo:
            ws.receive_json()
        assert excinfo.value.code == CLOSE_SESSION_UNKNOWN


def test_subscribe_session_mismatch_closes_4400(journal) -> None:
    stack = build_stack(journal, session_directory=_Directory({"sess-1": "ACTIVE"}))
    with TestClient(stack.app) as client, client.websocket_connect(
        "/ws/v1/sessions/sess-1"
    ) as ws:
        _subscribe(ws, session_id="other-session")
        with pytest.raises(Exception) as excinfo:
            ws.receive_json()
        assert excinfo.value.code == CLOSE_SUBSCRIBE_MISMATCH


def test_subscribe_without_directory_accepts_known_session(journal) -> None:
    """MVP wiring: no session directory injected → the hub must not fabricate
    session truth; connections are accepted (the registry check is a wired
    policy, not a hardcoded bypass)."""
    stack = build_stack(journal)
    with TestClient(stack.app) as client, client.websocket_connect(
        "/ws/v1/sessions/sess-1"
    ) as ws:
        _subscribe(ws)
        ready = ws.receive_json()
        assert ready == {"type": "ready", "replayed_from": 1}


# --- upstream ping/pong (SPEC-501 §4.2) -----------------------------------------


def test_upstream_ping_answers_pong(journal) -> None:
    stack = build_stack(journal)
    with TestClient(stack.app) as client, client.websocket_connect(
        "/ws/v1/sessions/sess-1"
    ) as ws:
        _subscribe(ws)
        assert ws.receive_json() == {"type": "ready", "replayed_from": 1}
        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}


# --- dual frames live (REQ-WS-501-002) -------------------------------------------


def test_journal_frame_carries_full_stamped_envelope(journal) -> None:
    stack = build_stack(journal)
    seq_source: list[int] = []
    publish(stack.gateway, seq_source)
    drain_committed(stack.gateway)
    with TestClient(stack.app) as client, client.websocket_connect(
        "/ws/v1/sessions/sess-1"
    ) as ws:
        _subscribe(ws, last_journal_seq=0)
        frame = ws.receive_json()
        assert frame["type"] == "journal"
        envelope = frame["envelope"]
        # The envelope is the SPEC-301 envelope with the journal stamp —
        # exactly what the journal stores (no fourth envelope, REQ-005).
        row = stack.journal.query("sess-1", after_seq=0)[0]
        assert envelope == row.envelope
        assert envelope["journal_seq"] == 1
        ready = ws.receive_json()
        assert ready == {"type": "ready", "replayed_from": 2}


def test_hint_frame_delivered_to_subscribed_client(journal) -> None:
    """Record-state state (alert) never enters the event stream — the WS
    layer transports it only as a hint to pull via REST (SPEC-501 §4.1)."""
    stack = build_stack(journal)
    with TestClient(stack.app) as client, client.websocket_connect(
        "/ws/v1/sessions/sess-1"
    ) as ws:
        _subscribe(ws)
        assert ws.receive_json() == {"type": "ready", "replayed_from": 1}
        stack.hub.publish_hint(
            "sess-1", "observation.alert_changed", {"session_id": "sess-1"}
        )
        frame = ws.receive_json()
        assert frame == {
            "type": "hint",
            "topic": "observation.alert_changed",
            "data": {"session_id": "sess-1"},
        }


def test_hint_to_other_session_not_delivered(journal) -> None:
    """Single connection single session: hints for other sessions never leak
    onto this connection (SPEC-501 §3, ticket #13 Q4)."""
    stack = build_stack(journal)
    seq_source: list[int] = []
    publish(stack.gateway, seq_source)
    drain_committed(stack.gateway)
    with TestClient(stack.app) as client, client.websocket_connect(
        "/ws/v1/sessions/sess-1"
    ) as ws:
        _subscribe(ws, last_journal_seq=0)
        assert ws.receive_json()["type"] == "journal"
        assert ws.receive_json() == {"type": "ready", "replayed_from": 2}
        stack.hub.publish_hint(
            "sess-2", "observation.alert_changed", {"session_id": "sess-2"}
        )
        stack.hub.publish_hint(
            "sess-1", "observation.metric_updated", {"session_id": "sess-1"}
        )
        frame = ws.receive_json()
        assert frame["topic"] == "observation.metric_updated"
