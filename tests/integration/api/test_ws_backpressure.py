"""Backpressure end to end — SPEC-501 §6/§9 (REQ-WS-501-004), integration.

Slow-consumer saturation (close 1013 + continuation cursor in the reason),
journal replay recovery after reconnect, and the coalesce matrix observed
on the wire: the newest run_progress wins, protected events arrive intact.
"""

import threading

import pytest
from fastapi.testclient import TestClient

from api.ws.frames import CLOSE_SLOW_CONSUMER, parse_slow_consumer_cursor
from api.ws.hub import WsConfig

from tests.integration.api.ws_stack import build_stack, drain_committed, publish


def _subscribe(ws, session_id: str = "sess-1", last_journal_seq=None) -> None:
    msg = {"type": "subscribe", "session_id": session_id}
    if last_journal_seq is not None:
        msg["last_journal_seq"] = last_journal_seq
    ws.send_json(msg)


def _flood(gateway, total: int, *, protected_last: bool) -> None:
    """Dispatcher-thread flood of no-drop-class events, then one protected.

    Every event is committed synchronously (accept → drain), so the journal
    keeps all of them while the per-client queue overflows. The events are
    non-coalescable (``ts.continuity_error``) — a full queue with no
    coalescable victim saturates the client (the §6 slow-consumer close).
    """
    from tests.unit.application.observation.test_gateway_accept import _raw_envelope

    for index in range(total):
        raw = _raw_envelope(event_type="ts.continuity_error", session_id="sess-1")
        raw["event_id"] = f"flood-{index:04d}"
        raw["scope"]["run_id"] = f"run-{index:04d}"
        raw["payload"] = {"source": "tsduck", "confidence": "parsed"}
        if protected_last and index == total - 1:
            raw["event_type"] = "fault.injected"
            raw["event_id"] = "flood-fault"
            raw["scope"]["run_id"] = "run-fault"
            raw["payload"] = {}
        assert gateway.accept(raw).outcome.value == "accepted"
        gateway.drain()


def test_slow_consumer_disconnected_1013_with_cursor_and_replay_recovers(
    journal,
) -> None:
    """§6/§9: a consumer too slow for its bounded queue is disconnected with
    close 1013 + a continuation cursor; reconnecting with that cursor replays
    the journal so the union of both connections covers every committed seq
    with no holes and no duplicates."""
    config = WsConfig(queue_depth=2, send_pace=0.05, pump_poll=0.01)
    stack = build_stack(journal, config=config)
    seq_source: list[int] = []
    first_connection_seqs: list[int] = []
    disconnect: Exception | None = None

    with TestClient(stack.app) as client, client.websocket_connect(
        "/ws/v1/sessions/sess-1"
    ) as ws:
        _subscribe(ws)
        assert ws.receive_json()["type"] == "ready"
        flooder = threading.Thread(
            target=_flood, args=(stack.gateway, 20), kwargs={"protected_last": True},
            daemon=True,
        )
        flooder.start()
        try:
            while True:
                try:
                    frame = ws.receive_json()
                except Exception as exc:  # WebSocketDisconnect carries the matrix
                    disconnect = exc
                    break
                assert frame["type"] == "journal"
                first_connection_seqs.append(frame["envelope"]["journal_seq"])
        finally:
            flooder.join(timeout=10)

    assert disconnect is not None, "slow consumer was never disconnected"
    assert disconnect.code == CLOSE_SLOW_CONSUMER
    cursor = parse_slow_consumer_cursor(disconnect.reason)
    assert cursor is not None, disconnect.reason
    # The cursor is a truthful delivery watermark: everything up to it was
    # delivered in order; nothing beyond it was ever sent.
    assert first_connection_seqs == list(range(1, cursor + 1))

    max_committed = len(seq_source) or 0
    # The flood committed 20 events; read the journal watermark from the
    # journal itself (the transport must not guess the total order).
    rows = stack.journal.query("sess-1", after_seq=0, limit=1000)
    max_committed = rows[-1].journal_seq
    assert max_committed == 20

    with TestClient(stack.app) as client, client.websocket_connect(
        "/ws/v1/sessions/sess-1"
    ) as ws:
        _subscribe(ws, last_journal_seq=cursor)
        replayed: list[int] = []
        while True:
            frame = ws.receive_json()
            if frame["type"] == "ready":
                break
            replayed.append(frame["envelope"]["journal_seq"])
        assert replayed == list(range(cursor + 1, max_committed + 1))
        # Union of both connections: every committed seq, no holes, no dups.
        assert sorted(set(first_connection_seqs) | set(replayed)) == list(
            range(1, max_committed + 1)
        )


def test_coalesce_on_the_wire_newest_progress_wins_protected_arrives(journal) -> None:
    """§9 合并限流: a burst of same-run run_progress merges down to the newest
    value; the protected fault event arrives intact (禁静默丢弃) and the
    client stays connected (no saturation — only the coalescable class ever
    gets dropped)."""
    config = WsConfig(queue_depth=8, send_pace=0.02, pump_poll=0.01)
    stack = build_stack(journal, config=config)
    from tests.unit.application.observation.test_gateway_accept import _raw_envelope

    with TestClient(stack.app) as client, client.websocket_connect(
        "/ws/v1/sessions/sess-1"
    ) as ws:
        _subscribe(ws)
        assert ws.receive_json()["type"] == "ready"

        # Committed one by one (ingest queue emptied each round), so the
        # journal keeps all six and the TRANSPORT queue is where the §5
        # merge has to happen.
        for index in range(6):
            raw = _raw_envelope(
                event_type="simulation.run_progress", session_id="sess-1"
            )
            raw["event_id"] = f"burst-{index:04d}"
            raw["scope"]["run_id"] = "run-a"  # one coalesce slot
            assert stack.gateway.accept(raw).outcome.value == "accepted"
            drain_committed(stack.gateway)
        fault = _raw_envelope(event_type="fault.injected", session_id="sess-1")
        fault["event_id"] = "burst-fault-1"
        fault["scope"]["run_id"] = "run-fault"
        assert stack.gateway.accept(fault).outcome.value == "accepted"
        drain_committed(stack.gateway)

        progress_seqs: list[int] = []
        fault_seq: int | None = None
        for _ in range(20):
            frame = ws.receive_json()
            if frame["type"] == "hint":
                continue
            envelope = frame["envelope"]
            if envelope["event_type"] == "fault.injected":
                fault_seq = envelope["journal_seq"]
                break
            assert envelope["event_type"] == "simulation.run_progress"
            progress_seqs.append(envelope["journal_seq"])
        assert fault_seq is not None, "protected fault event never arrived"

        # Newest-wins: every delivered progress frame is strictly ascending
        # and the newest published progress is present (intermediate values
        # may have merged away — that is the sanctioned §5 drop).
        assert progress_seqs == sorted(set(progress_seqs))
        assert progress_seqs[-1] == 6
        # The fault (delivery-protected class) was never merged away.
        assert fault_seq == 7


def test_no_drop_class_cannot_be_silently_dropped_without_disconnect(journal) -> None:
    """A queue full of coalescable entries makes room for a no-drop event by
    evicting ONE coalescable victim (the only sanctioned silent drop) — the
    no-drop event itself always arrives or the client saturates."""
    config = WsConfig(queue_depth=1, send_pace=0.0, pump_poll=0.01)
    stack = build_stack(journal, config=config)
    from tests.unit.application.observation.test_gateway_accept import _raw_envelope

    with TestClient(stack.app) as client, client.websocket_connect(
        "/ws/v1/sessions/sess-1"
    ) as ws:
        _subscribe(ws)
        assert ws.receive_json()["type"] == "ready"
        progress = _raw_envelope(
            event_type="simulation.run_progress", session_id="sess-1"
        )
        progress["event_id"] = "progress-0001"
        progress["scope"]["run_id"] = "run-a"
        assert stack.gateway.accept(progress).outcome.value == "accepted"
        fault = _raw_envelope(event_type="fault.injected", session_id="sess-1")
        fault["event_id"] = "fault-000001"
        fault["scope"]["run_id"] = "run-fault"
        assert stack.gateway.accept(fault).outcome.value == "accepted"
        drain_committed(stack.gateway)

        seen_types: list[str] = []
        for _ in range(5):
            frame = ws.receive_json()
            if frame["type"] == "hint":
                continue
            seen_types.append(frame["envelope"]["event_type"])
            if frame["envelope"]["event_type"] == "fault.injected":
                break
        assert "fault.injected" in seen_types
