"""Bounded ingestion queue with coalescing admission (SPEC-300 §8/§11).

The queue is the gateway's backpressure boundary between producers and the
journal writer: producers ``put`` (never blocking — full is an immediate
explicit error or a sanctioned coalesce), the dispatcher ``pop_batch``-es
into the journal. Backpressure is therefore always explicit: nothing is
silently dropped.

Coalescing rule (SPEC-301 §5, grafted backpressure terms, ADR-0006 decision
1 — the classification itself comes from the #46 frozen registry, never a
local copy): an incoming event whose type is :func:`is_coalescable` MAY
overwrite an older undelivered event with the same coalesce key when the
queue is full (new value replaces the old in the old value's position). Any
other event — delivery-protected or merely not registered as coalescable —
meets a full queue with :class:`QueueFullError` (explicit rejection).

Thread posture: one producer-side lock, no condition variables — ``put`` is
non-blocking by contract (SPEC-300 §8: 不得让仿真时钟线程阻塞在慢消费者上),
``pop_batch`` drains whatever is available.
"""

from __future__ import annotations

import threading
from collections import deque
from typing import Any, Optional

#: Coalesce identity: one pending slot per (producer, session, run, type).
#: Two different runs (or producers) never overwrite each other's progress.
CoalesceKey = tuple[str, str, str, str]


class QueueFullError(Exception):
    """The bounded queue is at capacity and the event may not coalesce.

    Raised by :meth:`BoundedEventQueue.put`; the gateway converts it into a
    structured rejected result with ``OBS_QUEUE_FULL`` — callers of the
    gateway never see this raw type.
    """

    def __init__(self, capacity: int) -> None:
        super().__init__(
            f"ingestion queue is full (capacity {capacity}); the event was "
            "NOT silently dropped — retry after backoff (SPEC-300 §8)"
        )
        self.capacity = capacity


class BoundedEventQueue:
    """Capacity-bounded FIFO with in-place coalescing admission (§5/§8)."""

    def __init__(self, capacity: int) -> None:
        if capacity < 1:
            raise ValueError(f"queue capacity must be >= 1, got {capacity!r}")
        self._capacity = capacity
        self._items: deque[tuple[Optional[CoalesceKey], dict[str, Any]]] = deque()
        self._lock = threading.Lock()

    @property
    def capacity(self) -> int:
        return self._capacity

    def depth(self) -> int:
        """Undelivered event count (SPEC-300 §8: 暴露队列深度)."""
        with self._lock:
            return len(self._items)

    def put(
        self, envelope: dict[str, Any], coalesce_key: Optional[CoalesceKey]
    ) -> str:
        """Admit one event; returns ``"enqueued"`` or ``"coalesced"``.

        Raises :class:`QueueFullError` when full and no coalescable victim
        exists. Coalescing (only possible when ``coalesce_key`` is given and
        a pending event with the same key is still undelivered) overwrites
        the old value in place — the old value is never delivered.
        """
        with self._lock:
            if coalesce_key is not None:
                for index, (key, _) in enumerate(self._items):
                    if key == coalesce_key:
                        self._items[index] = (key, envelope)
                        return "coalesced"
            if len(self._items) >= self._capacity:
                raise QueueFullError(self._capacity)
            self._items.append((coalesce_key, envelope))
            return "enqueued"

    def pop_batch(self, limit: Optional[int] = None) -> list[dict[str, Any]]:
        """Pop up to ``limit`` envelopes oldest-first (journal order)."""
        with self._lock:
            count = len(self._items) if limit is None else min(limit, len(self._items))
            popped = [self._items.popleft() for _ in range(count)]
        return [envelope for _, envelope in popped]

    def pending(self, limit: Optional[int] = None) -> list[dict[str, Any]]:
        """Snapshot of undelivered envelopes oldest-first (diagnostics/tests)."""
        with self._lock:
            items = list(self._items)
        if limit is not None:
            items = items[:limit]
        return [envelope for _, envelope in items]


__all__ = ["BoundedEventQueue", "CoalesceKey", "QueueFullError"]
