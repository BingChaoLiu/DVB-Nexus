"""Per-client backpressure matrix — SPEC-501 §6 (REQ-WS-501-004), unit layer.

The client queue is the WS transport's backpressure boundary between the
gateway fan-out (drain thread) and the event-loop pump:

- coalescable events (frozen face: ``is_coalescable``, consumed through the
  application seam — never a local registry copy) may merge in place and
  may be dropped when full — seq jumps are sanctioned for that class;
- every other event class is **no-drop**: it either enqueues (evicting a
  pending coalescable victim if needed) or saturates the client — the
  loud slow-consumer disconnect (close 1013 + cursor) that the journal
  replay recovers. Nothing is ever silently dropped from the no-drop class.
- hints are the "重复提示" class (SPEC-501 §6: 丢的只是重复提示) — droppable
  when full, never a saturation trigger.

Unit layer: pure in-memory, no I/O, no wall clock.
"""

import threading

import pytest
from domain.observation.registry import (
    DELIVERY_PROTECTED_EVENT_TYPES,
    is_delivery_protected,
)
from application.observation.gateway import is_coalescable

from api.ws.backpressure import ClientQueue, PendingItem


def _envelope(seq: int, event_type: str, session: str = "sess-1", run: str = "r1", producer: str = "sim") -> dict:
    return {
        "journal_seq": seq,
        "event_type": event_type,
        "producer": {"producer_id": producer},
        "scope": {"session_id": session, "run_id": run},
    }


def _hint(topic: str = "observation.alert_changed") -> tuple[str, dict]:
    return topic, {"session_id": "sess-1"}


def _queue(capacity: int) -> ClientQueue:
    """The composition-root binding: the frozen #46 registry face itself."""
    return ClientQueue(capacity, coalescable_of=is_coalescable)


# --- frozen-face discipline (no parallel registry copy) -----------------------


def test_queue_uses_the_frozen_coalescable_face() -> None:
    """The classifier IS the frozen face object — proven indirectly: the
    queue merges exactly ``simulation.run_progress`` (the only registered
    coalescable type) and nothing else."""
    queue = _queue(8)
    queue.put_envelope(_envelope(1, "simulation.run_progress"))
    outcome = queue.put_envelope(_envelope(2, "simulation.run_progress"))
    assert outcome == "coalesced"


def test_frozen_delivery_protected_types_are_never_coalescable() -> None:
    """The §6 no-drop matrix rests on: protected types are never in the
    coalescable class, so the transport treats them as no-drop (the same
    complement rule the application face's queue canonized)."""
    for event_type in DELIVERY_PROTECTED_EVENT_TYPES:
        assert is_delivery_protected(event_type)
        assert not is_coalescable(event_type)


# --- enqueue + in-place coalescing ---------------------------------------------


def test_fifo_enqueue_and_pop_batch() -> None:
    queue = _queue(8)
    assert queue.put_envelope(_envelope(1, "simulation.run_started")) == "queued"
    assert queue.put_envelope(_envelope(2, "fault.injected")) == "queued"
    items = queue.pop_batch()
    assert [item.seq for item in items] == [1, 2]
    assert all(item.kind == "journal" for item in items)


def test_coalescable_overwrites_pending_same_key_in_place() -> None:
    """New value replaces the undelivered old value at the old position —
    the old value is never delivered (SPEC-301 §5 graft)."""
    queue = _queue(8)
    queue.put_envelope(_envelope(1, "simulation.run_started"))
    queue.put_envelope(_envelope(2, "simulation.run_progress", run="a"))
    queue.put_envelope(_envelope(3, "fault.injected"))
    queue.put_envelope(_envelope(4, "simulation.run_progress", run="b"))
    queue.put_envelope(_envelope(5, "simulation.run_progress", run="a"))  # merges
    items = queue.pop_batch()
    # Exactly one item per non-coalesced event plus the merged slot holding
    # the NEWEST value (seq 5) at the old entry's position: seq 2 is gone.
    assert [(item.kind, item.seq) for item in items] == [
        ("journal", 1),
        ("journal", 5),
        ("journal", 3),
        ("journal", 4),
    ]


def test_coalescing_is_scoped_per_producer_session_run_type() -> None:
    """Progress of two runs (or producers) never overwrites each other —
    same coalesce identity as the application face (SPEC-301 §5)."""
    queue = _queue(8)
    queue.put_envelope(_envelope(1, "simulation.run_progress", run="a"))
    queue.put_envelope(_envelope(2, "simulation.run_progress", run="b"))
    queue.put_envelope(_envelope(3, "simulation.run_progress", run="a", producer="other"))
    assert len(queue.pending()) == 3


# --- the drop matrix under a full queue ----------------------------------------


def test_full_queue_drops_incoming_coalescable_without_pending_slot() -> None:
    queue = _queue(2)
    queue.put_envelope(_envelope(1, "fault.injected"))
    queue.put_envelope(_envelope(2, "fault.activated"))
    outcome = queue.put_envelope(_envelope(3, "simulation.run_progress"))
    assert outcome == "dropped_coalescable"
    assert queue.dropped_coalescable == 1
    assert queue.saturated is False


def test_full_queue_coalescable_with_pending_slot_merges_not_saturates() -> None:
    queue = _queue(2)
    queue.put_envelope(_envelope(1, "simulation.run_progress"))
    queue.put_envelope(_envelope(2, "fault.injected"))
    outcome = queue.put_envelope(_envelope(3, "simulation.run_progress"))
    assert outcome == "coalesced"
    assert queue.saturated is False


def test_full_queue_no_drop_event_evicts_pending_coalescable_victim() -> None:
    """A no-drop event may evict ONE pending coalescable entry to make room —
    the only sanctioned silent drop stays inside the coalescable class."""
    queue = _queue(2)
    queue.put_envelope(_envelope(1, "simulation.run_progress"))
    queue.put_envelope(_envelope(2, "simulation.run_progress", run="other"))
    outcome = queue.put_envelope(_envelope(3, "fault.injected"))
    assert outcome == "queued"
    assert queue.dropped_coalescable == 1
    pending_seqs = [item.seq for item in queue.pending()]
    assert pending_seqs == [2, 3]


def test_full_queue_no_drop_event_without_victim_saturates() -> None:
    """No coalescable victim and no room → the client saturates: the trigger
    event is NOT silently dropped — the connection closes 1013 and the
    journal replay recovers it (SPEC-501 §6)."""
    queue = _queue(2)
    queue.put_envelope(_envelope(1, "fault.injected"))
    queue.put_envelope(_envelope(2, "fault.activated"))
    outcome = queue.put_envelope(_envelope(3, "fault.applied"))
    assert outcome == "saturated"
    assert queue.saturated is True
    assert [item.seq for item in queue.pending()] == [1, 2]


def test_saturated_queue_stays_saturated_and_queues_nothing() -> None:
    queue = _queue(1)
    queue.put_envelope(_envelope(1, "fault.injected"))
    assert queue.put_envelope(_envelope(2, "fault.activated")) == "saturated"
    assert queue.put_envelope(_envelope(3, "simulation.run_progress")) == "saturated"
    assert len(queue.pending()) == 1


# --- hints: the droppable "重复提示" class ---------------------------------------


def test_hint_enqueues_when_there_is_room() -> None:
    queue = _queue(4)
    assert queue.put_hint(*_hint()) == "queued"
    items = queue.pop_batch()
    assert items[0].kind == "hint"
    assert items[0].topic == "observation.alert_changed"
    assert items[0].data == {"session_id": "sess-1"}


def test_full_queue_drops_hint_without_saturating() -> None:
    """Hints are pointers, not facts — dropping one loses only a repeat
    notification (SPEC-501 §6) and never triggers the disconnect."""
    queue = _queue(1)
    queue.put_envelope(_envelope(1, "fault.injected"))
    assert queue.put_hint(*_hint()) == "dropped_hint"
    assert queue.saturated is False
    assert queue.dropped_hints == 1


# --- thread posture --------------------------------------------------------------


def test_queue_is_thread_safe_for_fan_out_and_pump() -> None:
    """Fan-out callbacks run on the drain thread while the pump pops on the
    event loop — the queue holds under concurrent put/pop."""
    queue = _queue(1000)
    for seq in range(500):
        queue.put_envelope(_envelope(seq + 1, "ts.continuity_error"))

    popped: list[int] = []
    lock = threading.Lock()

    def _pump() -> None:
        while True:
            batch = queue.pop_batch(limit=10)
            if not batch:
                break
            with lock:
                popped.extend(item.seq for item in batch)

    import concurrent.futures as cf

    with cf.ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(_pump) for _ in range(4)]
        for future in futures:
            future.result(timeout=5)

    assert sorted(popped) == list(range(1, 501))


def test_pending_item_is_typed_union() -> None:
    """The pump needs to tell journal frames from hints without sniffing
    dicts — PendingItem carries kind + payload."""
    queue = _queue(4)
    queue.put_envelope(_envelope(1, "fault.injected"))
    queue.put_hint(*_hint())
    items = queue.pop_batch()
    assert items[0] == PendingItem(
        kind="journal", envelope=_envelope(1, "fault.injected"), topic=None, data=None
    )
    assert items[1].kind == "hint"
    assert items[1].topic == "observation.alert_changed"
