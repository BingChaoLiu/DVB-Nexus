"""Cursor replay recovery — SPEC-501 §5 (REQ-WS-501-003), integration.

The §5 protocol end to end over the real SQLite journal: subscribe with
``last_journal_seq`` → journal frames replayed in stamped order (连续无洞)
→ ``ready`` with the first live seq → live delivery; a reconnect with the
last received cursor fills exactly the gap (no holes, no duplicates across
reconnects — the ADR-0006 decision 2 replay implementation).
"""

from fastapi.testclient import TestClient

from tests.integration.api.ws_stack import build_stack, drain_committed, publish


def _subscribe(ws, session_id: str = "sess-1", last_journal_seq=None) -> None:
    msg = {"type": "subscribe", "session_id": session_id}
    if last_journal_seq is not None:
        msg["last_journal_seq"] = last_journal_seq
    ws.send_json(msg)


def _receive_until_ready(ws, *, max_frames: int = 5000) -> tuple[list[int], int]:
    """Collect journal-frame seqs until ``ready``; returns (seqs, replayed_from)."""
    seqs: list[int] = []
    for _ in range(max_frames):
        frame = ws.receive_json()
        if frame["type"] == "ready":
            return seqs, frame["replayed_from"]
        assert frame["type"] == "journal", frame
        seqs.append(frame["envelope"]["journal_seq"])
    raise AssertionError("ready never arrived")


def test_replay_is_contiguous_across_batch_boundaries(journal) -> None:
    """250 pre-committed events (replay batch size is 100 → 3 query rounds)
    replay as seqs 1..250 with no holes, then ready(replayed_from=251)."""
    stack = build_stack(journal)
    seq_source: list[int] = []
    for _ in range(250):
        publish(stack.gateway, seq_source, event_type="simulation.run_started")
    drain_committed(stack.gateway)
    with TestClient(stack.app) as client, client.websocket_connect(
        "/ws/v1/sessions/sess-1"
    ) as ws:
        _subscribe(ws, last_journal_seq=0)
        seqs, replayed_from = _receive_until_ready(ws)
        assert seqs == list(range(1, 251))
        assert replayed_from == 251


def test_cursor_replay_resumes_after_cursor(journal) -> None:
    """subscribe(last_journal_seq=2) replays exactly seqs 3..4 + ready(5)."""
    stack = build_stack(journal)
    seq_source: list[int] = []
    for _ in range(4):
        publish(stack.gateway, seq_source)
    drain_committed(stack.gateway)
    with TestClient(stack.app) as client, client.websocket_connect(
        "/ws/v1/sessions/sess-1"
    ) as ws:
        _subscribe(ws, last_journal_seq=2)
        seqs, replayed_from = _receive_until_ready(ws)
        assert seqs == [3, 4]
        assert replayed_from == 5


def test_cursor_omitted_starts_live_without_replay(journal) -> None:
    """§5: 缺省 = 从当前起，不重放 — committed history is not replayed; only
    events committed after the subscribe arrive live."""
    stack = build_stack(journal)
    seq_source: list[int] = []
    publish(stack.gateway, seq_source)
    drain_committed(stack.gateway)
    with TestClient(stack.app) as client, client.websocket_connect(
        "/ws/v1/sessions/sess-1"
    ) as ws:
        _subscribe(ws)  # no cursor
        assert ws.receive_json() == {"type": "ready", "replayed_from": 2}
        # The historical event (seq 1) never arrives; the next event does.
        publish(stack.gateway, seq_source)
        drain_committed(stack.gateway)
        frame = ws.receive_json()
        assert frame["envelope"]["journal_seq"] == 2


def test_reconnect_replay_fills_gap_no_holes_no_duplicates(journal) -> None:
    """The §9 acceptance core: disconnect mid-stream, events commit during
    the outage, reconnect with the last seen cursor → the union of both
    connections is exactly seqs 1..6 (无洞无重)."""
    stack = build_stack(journal)
    seq_source: list[int] = []
    received: list[int] = []

    with TestClient(stack.app) as client, client.websocket_connect(
        "/ws/v1/sessions/sess-1"
    ) as ws:
        _subscribe(ws, last_journal_seq=0)
        assert ws.receive_json() == {"type": "ready", "replayed_from": 1}
        # Live delivery of three facts, received one by one.
        for _ in range(3):
            publish(stack.gateway, seq_source)
        drain_committed(stack.gateway)
        for _ in range(3):
            frame = ws.receive_json()
            assert frame["type"] == "journal"
            received.append(frame["envelope"]["journal_seq"])
    # Abrupt disconnect: connection closed without a goodbye cursor.

    # Facts keep landing while the client is gone — nothing is lost.
    for _ in range(3):
        publish(stack.gateway, seq_source)
    drain_committed(stack.gateway)

    with TestClient(stack.app) as client, client.websocket_connect(
        "/ws/v1/sessions/sess-1"
    ) as ws:
        _subscribe(ws, last_journal_seq=max(received))
        seqs, replayed_from = _receive_until_ready(ws)
        received.extend(seqs)
        assert replayed_from == 7
        assert received == [1, 2, 3, 4, 5, 6]


def test_live_and_other_sessions_do_not_interleave_replay(journal) -> None:
    """Replay is per-session: another session's committed events never
    appear in this connection's stream (single connection single session)."""
    stack = build_stack(journal)
    seq_source: list[int] = []
    publish(stack.gateway, seq_source)
    drain_committed(stack.gateway)
    with TestClient(stack.app) as client, client.websocket_connect(
        "/ws/v1/sessions/sess-1"
    ) as ws:
        _subscribe(ws, last_journal_seq=0)
        assert ws.receive_json()["envelope"]["journal_seq"] == 1
        assert ws.receive_json() == {"type": "ready", "replayed_from": 2}
        # Another session's facts + this session's next fact.
        publish(stack.gateway, seq_source, session_id="sess-2")
        drain_committed(stack.gateway)
        publish(stack.gateway, seq_source)
        drain_committed(stack.gateway)
        frame = ws.receive_json()
        assert frame["envelope"]["journal_seq"] == 2
        assert frame["envelope"]["scope"]["session_id"] == "sess-1"
