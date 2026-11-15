"""Transport frame contract — SPEC-501 §4 (REQ-WS-501-002/005), unit layer.

The frame layer is pure encoding/decoding: journal frames carry the full
SPEC-301 envelope **untouched** (the transport adds only the ``type``
wrapper — ADR-0006 decision 4, no fourth envelope); hint frames are the
SPEC-305 §8 five-topic notification pointer. Unit layer: no I/O, no wall
clock, no fixtures.
"""

import copy

import pytest

from api.ws.frames import (
    CLOSE_PONG_TIMEOUT,
    CLOSE_SESSION_UNKNOWN,
    CLOSE_SLOW_CONSUMER,
    CLOSE_STORAGE_UNAVAILABLE,
    CLOSE_SUBSCRIBE_MISMATCH,
    HINT_TOPICS,
    WsFrameError,
    encode_hint_frame,
    encode_journal_frame,
    encode_ready,
    encode_pong,
    parse_upstream,
)


# --- journal frames (SPEC-501 §4.1) ------------------------------------------


def test_journal_frame_wraps_envelope_with_type_only() -> None:
    envelope = {"event_id": "evt-1", "journal_seq": 7, "payload": {"x": 1}}
    frame = encode_journal_frame(envelope)
    assert frame == {"type": "journal", "envelope": envelope}


def test_journal_frame_envelope_is_untouched_deep_copy() -> None:
    """The envelope rides through verbatim — no added/stripped fields, and
    the frame cannot mutate the caller's dict (transport is not the owner)."""
    envelope = {
        "schema_version": "1.0",
        "scope": {"session_id": "sess-1"},
        "journal_seq": 3,
    }
    frozen = copy.deepcopy(envelope)
    frame = encode_journal_frame(envelope)
    assert frame["envelope"] == frozen
    frame["envelope"]["scope"]["session_id"] = "tampered"
    assert envelope == frozen


def test_journal_frame_rejects_unstamped_envelope() -> None:
    """A journal frame without the stamped ``journal_seq`` is illegal: the
    seq is the replay cursor's anchor (ADR-0006 decision 2) — the transport
    layer never fabricates one, it refuses."""
    with pytest.raises(WsFrameError):
        encode_journal_frame({"event_id": "evt-1"})


# --- hint frames (SPEC-501 §4.1, topics = SPEC-305 §8 five) ------------------


def test_hint_topics_are_exactly_the_spec_305_five() -> None:
    assert HINT_TOPICS == frozenset(
        {
            "observation.event_appended",
            "observation.metric_updated",
            "observation.alert_changed",
            "observation.health_changed",
            "observation.export_progress",
        }
    )


def test_hint_frame_shape() -> None:
    frame = encode_hint_frame("observation.alert_changed", {"session_id": "s"})
    assert frame == {
        "type": "hint",
        "topic": "observation.alert_changed",
        "data": {"session_id": "s"},
    }


def test_hint_frame_rejects_topic_outside_the_five() -> None:
    with pytest.raises(WsFrameError):
        encode_hint_frame("fault.injected", {})  # envelope event, not a topic
    with pytest.raises(WsFrameError):
        encode_hint_frame("observation.nonexistent", {})


# --- upstream messages (SPEC-501 §4.2) ----------------------------------------


def test_parse_upstream_subscribe_defaults_cursor_to_none() -> None:
    msg = parse_upstream({"type": "subscribe", "session_id": "sess-1"})
    assert msg.type == "subscribe"
    assert msg.session_id == "sess-1"
    assert msg.last_journal_seq is None


def test_parse_upstream_subscribe_carries_cursor() -> None:
    msg = parse_upstream(
        {"type": "subscribe", "session_id": "sess-1", "last_journal_seq": 1234}
    )
    assert msg.last_journal_seq == 1234


@pytest.mark.parametrize(
    "raw",
    [
        {"type": "subscribe", "session_id": "sess-1", "last_journal_seq": -1},
        {"type": "subscribe", "session_id": "sess-1", "last_journal_seq": "7"},
        {"type": "subscribe"},  # no session_id
        {"type": "unsubscribe", "session_id": "sess-1"},  # unknown type
        "not-an-object",
    ],
)
def test_parse_upstream_rejects_malformed_messages(raw) -> None:
    with pytest.raises(WsFrameError):
        parse_upstream(raw)


def test_parse_upstream_ping() -> None:
    msg = parse_upstream({"type": "ping"})
    assert msg.type == "ping"


# --- server control replies (SPEC-501 §4.2) -----------------------------------


def test_ready_frame_carries_replayed_from() -> None:
    assert encode_ready(replayed_from=1235) == {
        "type": "ready",
        "replayed_from": 1235,
    }


def test_pong_frame() -> None:
    assert encode_pong() == {"type": "pong"}


# --- close-code matrix (SPEC-501 §8) ------------------------------------------


def test_close_code_matrix() -> None:
    assert CLOSE_SESSION_UNKNOWN == 4404
    assert CLOSE_SUBSCRIBE_MISMATCH == 4400
    assert CLOSE_SLOW_CONSUMER == 1013
    assert CLOSE_STORAGE_UNAVAILABLE == 1011
    # Heartbeat timeout is not enumerated in SPEC-501 §8; the transport
    # defines 1008 (policy violation) as the pong-timeout code — recorded
    # in the ticket report for spec review.
    assert CLOSE_PONG_TIMEOUT == 1008
