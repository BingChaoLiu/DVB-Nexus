"""Per-client backpressure — SPEC-501 §6 matrix (ticket #49, REQ-WS-501-004).

One bounded queue per connected WS client sits between the gateway's
commit fan-out (which runs on the journal drain thread,
:meth:`application.observation.gateway.EventGateway.subscribe`) and the
event-loop pump that serializes frames onto the socket. The §6 matrix:

- **coalescable** class (frozen face :func:`is_coalescable`, consumed
  through the application seam — the #46 registry object itself, never a
  transport-local copy): a new value overwrites an undelivered old value
  with the same coalesce identity in place; a full queue drops the new
  value — both sanctioned, the client tolerates seq jumps for the class.
- **no-drop** class (everything else — ``fault.*`` / ``session_*`` /
  terminal run / ``recovery.verification_completed`` are exactly the frozen
  ``DELIVERY_PROTECTED`` set, and unclassified types follow the same
  complement rule the application face's queue canonized): never silently
  dropped. It either enqueues — evicting at most one pending coalescable
  victim — or the client **saturates**: the loud slow-consumer disconnect
  (close 1013 + continuation cursor, SPEC-501 §6) whose journal replay
  recovers every event, so the drop ledger stays empty.
- **hints** are the "重复提示" class: droppable when full, never a
  saturation trigger (SPEC-501 §6: 丢的只是重复提示).

Thread posture mirrors the application face's bounded queue
(``application.observation.queue.BoundedEventQueue``): one lock,
non-blocking ``put_*`` (a simulation clock thread must never block on a
slow WS consumer), batch ``pop`` for the pump.

Classifier wiring: the coalescable/no-drop decision is NOT re-decided
here — the frozen #46 registry face (:func:`domain.observation.is_coalescable`)
is bound by the **composition root** (``create_ws_app`` callers / tests)
and injected as the ``coalescable_of`` predicate. The api layer may not
import domain even transitively (ADR-0005 decision 4 import contract:
application.observation.gateway itself imports domain), so a default
binding inside api would either copy the registry (forbidden) or break
the layering (forbidden) — injection is the only contract-clean seam,
and it consumes the registry's own function object.
"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable, Optional

#: Transport-side coalesce identity — same shape as the application face's
#: ``CoalesceKey``: one pending slot per (producer, session, run, type).
CoalesceKey = tuple[str, str, str, str]

CoalescableOf = Callable[[str], bool]

_PUT_QUEUED = "queued"
_PUT_COALESCED = "coalesced"
_PUT_DROPPED_COALESCABLE = "dropped_coalescable"
_PUT_SATURATED = "saturated"
_HINT_QUEUED = "queued"
_HINT_DROPPED = "dropped_hint"


@dataclass(frozen=True)
class PendingItem:
    """One undelivered transport item waiting for the pump.

    Exactly one of the payload slots is set: journal items carry the
    stamped envelope, hint items carry ``(topic, data)``.
    """

    kind: str  # "journal" | "hint"
    envelope: Optional[dict[str, Any]] = None
    topic: Optional[str] = None
    data: Optional[dict[str, Any]] = None

    @property
    def seq(self) -> Optional[int]:
        """The item's ``journal_seq`` (journal items only)."""
        if self.envelope is None:
            return None
        return self.envelope.get("journal_seq")


class ClientQueue:
    """Bounded per-client queue implementing the SPEC-501 §6 matrix."""

    def __init__(
        self,
        capacity: int,
        *,
        coalescable_of: CoalescableOf,
    ) -> None:
        if capacity < 1:
            raise ValueError(f"client queue capacity must be >= 1, got {capacity!r}")
        self._capacity = capacity
        self._coalescable_of = coalescable_of
        self._items: deque[tuple[Optional[CoalesceKey], PendingItem]] = deque()
        self._lock = threading.Lock()
        self._saturated = False
        self._coalesced = 0
        self._dropped_coalescable = 0
        self._dropped_hints = 0

    # --- fan-out side (drain thread) ------------------------------------------

    def put_envelope(self, envelope: dict[str, Any]) -> str:
        """Admit one committed envelope; returns the §6 matrix outcome.

        ``"queued"`` / ``"coalesced"`` / ``"dropped_coalescable"`` /
        ``"saturated"``. A saturated queue accepts nothing further — the
        pump closes the connection with the continuation cursor and the
        journal replay recovers the events (nothing is silently lost).
        """
        event_type = envelope.get("event_type", "")
        with self._lock:
            if self._saturated:
                return _PUT_SATURATED
            if self._coalescable_of(event_type):
                key = _coalesce_key(envelope)
                for index, (pending_key, item) in enumerate(self._items):
                    if pending_key == key:
                        self._items[index] = (
                            key,
                            PendingItem(kind="journal", envelope=envelope),
                        )
                        self._coalesced += 1
                        return _PUT_COALESCED
                if len(self._items) >= self._capacity:
                    # Sanctioned drop: the class tolerates seq jumps; the
                    # newest progress value still lives in the journal for
                    # snapshot/REST pulls.
                    self._dropped_coalescable += 1
                    return _PUT_DROPPED_COALESCABLE
            elif len(self._items) >= self._capacity:
                # No-drop class meets a full queue: try to evict ONE pending
                # coalescable victim (the only sanctioned silent drop stays
                # inside the coalescable class); otherwise saturate loudly.
                if not self._evict_one_coalescable_locked():
                    self._saturated = True
                    return _PUT_SATURATED
            self._items.append(
                (
                    _coalesce_key(envelope) if self._coalescable_of(event_type) else None,
                    PendingItem(kind="journal", envelope=envelope),
                )
            )
            return _PUT_QUEUED

    def put_hint(self, topic: str, data: dict[str, Any]) -> str:
        """Admit one record-state pointer; hints drop when full (never a
        saturation trigger — SPEC-501 §6)."""
        with self._lock:
            if self._saturated:
                self._dropped_hints += 1
                return _HINT_DROPPED
            if len(self._items) >= self._capacity:
                self._dropped_hints += 1
                return _HINT_DROPPED
            self._items.append(
                (None, PendingItem(kind="hint", topic=topic, data=data))
            )
            return _HINT_QUEUED

    # --- pump side (event loop) -----------------------------------------------

    def pop_batch(self, limit: int | None = None) -> list[PendingItem]:
        """Pop up to ``limit`` pending items oldest-first."""
        with self._lock:
            count = len(self._items) if limit is None else min(limit, len(self._items))
            popped = [self._items.popleft() for _ in range(count)]
        return [item for _, item in popped]

    def pending(self, limit: int | None = None) -> list[PendingItem]:
        """Snapshot of undelivered items oldest-first (diagnostics/tests)."""
        with self._lock:
            items = list(self._items)
        if limit is not None:
            items = items[:limit]
        return [item for _, item in items]

    # --- observability ----------------------------------------------------------

    @property
    def saturated(self) -> bool:
        with self._lock:
            return self._saturated

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def coalesced(self) -> int:
        with self._lock:
            return self._coalesced

    @property
    def dropped_coalescable(self) -> int:
        with self._lock:
            return self._dropped_coalescable

    @property
    def dropped_hints(self) -> int:
        with self._lock:
            return self._dropped_hints

    # --- internals ----------------------------------------------------------------

    def _evict_one_coalescable_locked(self) -> bool:
        """Drop the oldest pending coalescable entry to make room.

        Caller holds the lock. Returns False when no victim exists.
        """
        for index, (key, _) in enumerate(self._items):
            if key is not None:
                del self._items[index]
                self._dropped_coalescable += 1
                return True
        return False


def _coalesce_key(envelope: dict[str, Any]) -> CoalesceKey:
    """Derive the coalesce identity from a committed envelope dict.

    Same identity as the application face's ``_coalesce_key``: one pending
    slot per (producer, session, run, type) — progress of two different
    runs (or producers) never overwrites each other. The dict-shape
    derivation is transport mechanics; the *policy* (which types may
    coalesce) is the frozen face, never decided here.
    """
    producer = envelope.get("producer") or {}
    scope = envelope.get("scope") or {}
    return (
        str(producer.get("producer_id", "")),
        str(scope.get("session_id") or ""),
        str(scope.get("run_id") or ""),
        str(envelope.get("event_type", "")),
    )


__all__ = ["ClientQueue", "CoalesceKey", "PendingItem"]
