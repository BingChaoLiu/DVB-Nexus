"""Heartbeat — SPEC-501 §3 (REQ-WS-501-001 posture), integration.

The server pings periodically; a client that goes silent past the pong
timeout is disconnected (close 1008); a client answering the §4.2
application-level ping/pong stays alive. Real stack, tiny intervals — the
assertions wait on received events, never on wall-clock sleeps.
"""

from fastapi.testclient import TestClient

from api.ws.frames import CLOSE_PONG_TIMEOUT
from api.ws.hub import WsConfig

from tests.integration.api.ws_stack import build_stack


def _config() -> WsConfig:
    return WsConfig(heartbeat_interval=0.05, pong_timeout=0.3, pump_poll=0.02)


def _subscribe(ws, session_id: str = "sess-1") -> None:
    ws.send_json({"type": "subscribe", "session_id": session_id})


def test_silent_client_is_disconnected_on_pong_timeout(journal) -> None:
    stack = build_stack(journal, config=_config())
    saw_server_ping = False
    disconnect: Exception | None = None

    with TestClient(stack.app) as client, client.websocket_connect(
        "/ws/v1/sessions/sess-1"
    ) as ws:
        _subscribe(ws)
        assert ws.receive_json()["type"] == "ready"
        # Go silent: receive whatever the server pushes until it closes us.
        for _ in range(50):
            try:
                frame = ws.receive_json()
            except Exception as exc:
                disconnect = exc
                break
            assert frame["type"] == "ping", frame
            saw_server_ping = True

    assert saw_server_ping, "the server never pinged the silent client"
    assert disconnect is not None, "silent client was never disconnected"
    assert disconnect.code == CLOSE_PONG_TIMEOUT


def test_answering_client_stays_alive_across_multiple_heartbeats(journal) -> None:
    """The §4.2 reply loop (downstream ping → upstream ping → pong) refreshes
    liveness: the connection survives many windows longer than one timeout."""
    stack = build_stack(journal, config=_config())
    with TestClient(stack.app) as client, client.websocket_connect(
        "/ws/v1/sessions/sess-1"
    ) as ws:
        _subscribe(ws)
        assert ws.receive_json()["type"] == "ready"
        pongs = 0
        for _ in range(20):
            frame = ws.receive_json()
            if frame["type"] != "ping":
                continue
            ws.send_json({"type": "ping"})
            reply = ws.receive_json()
            assert reply == {"type": "pong"}
            pongs += 1
            if pongs >= 8:  # ~8 heartbeat windows ≫ one pong timeout
                break
        assert pongs >= 8
