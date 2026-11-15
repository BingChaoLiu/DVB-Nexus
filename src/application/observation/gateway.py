"""Event Gateway — SPEC-300 §4.1 ingestion admission (application layer).

The gateway is the observation plane's front door (SPEC-300 §4.1 duties):

1. validate the SPEC-301 envelope (schema version, registry, payload policy)
   via the #46 frozen surface — :func:`domain.observation.parse_envelope`;
   producers never fill ``journal_seq`` (:meth:`EventEnvelope.ensure_publishable`).
2. perform exactly one sanctioned repair: backfill ``time.observed``
   (wall:utc) when the producer omitted it. Everything else that is
   semantically illegal is rejected with a structured code — 无隐式修复.
3. check the ``(producer_id, event_id)`` idempotency key before queueing.
4. admit into a bounded queue with the SPEC-301 §5 coalescing/delivery
   policy (classification imported from the frozen registry —
   :func:`domain.observation.is_coalescable` — never a local copy); a full
   queue is an explicit ``OBS_QUEUE_FULL`` rejection, never a silent drop.

The journal (SPEC-502 adapter) remains the unique stamp point and the
authoritative dedup backstop: :meth:`EventGateway.drain` appends queued
events, fans committed envelopes out to subscribers and records append
failures in a separate diagnostic stream (§4.2 — never re-published as
domain events). Producers are decoupled from the journal writer: ``accept``
does no disk I/O, so a simulation clock thread never blocks on storage
(SPEC-300 §8, OBSERVATION-INTEGRATION-CONTRACT §6).

Layer note (ADR-0005 decision 4): ``application`` may depend on every
package; the SQLite-touching code stays in ``adapters.storage`` behind the
``EventJournal`` protocol.
"""

from __future__ import annotations

import threading
import time as _time
from collections import OrderedDict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional, Protocol, Union

from adapters.storage.errors import StorageError
from application.observation.errors import OBS_QUEUE_FULL
from application.observation.queue import (
    BoundedEventQueue,
    CoalesceKey,
    QueueFullError,
)
from domain.observation import EventEnvelope, is_coalescable, parse_envelope
from domain.observation.errors import EnvelopeError

#: The one §4.1-sanctioned repair target: producers may omit ``time.observed``.
_BACKFILL_CLOCK_DOMAIN = "wall:utc"

CommitCallback = Callable[[dict[str, Any]], None]

#: What producers may hand to :meth:`EventGateway.accept` / ``publish``.
PublishableEvent = Union[EventEnvelope, dict[str, Any]]


class EventJournal(Protocol):
    """Structural subset of the SPEC-502 journal protocol the gateway needs.

    The authoritative protocol lives in ``adapters.storage.journal``; this
    structural duplicate documents the gateway's dependency without
    re-exporting the adapter type.
    """

    def append(self, envelope: dict) -> tuple[int, bool]: ...

    def query(self, session_id: str, *, after_seq: int = 0, limit: int = 100): ...

    def max_seq(self, session_id: str) -> int: ...


class IngestOutcome(str, Enum):
    """OBSERVATION-INTEGRATION-CONTRACT §6 three-outcome result."""

    ACCEPTED = "accepted"
    DUPLICATE = "duplicate"
    REJECTED = "rejected"


@dataclass(frozen=True)
class IngestResult:
    """Structured ingest answer (SPEC-300 §8; §13 error shape).

    ``journal_seq`` is set only when it is already known: duplicates return
    the ORIGINAL seq (SPEC-300 §13), first-time accepts answer ``None``
    because the stamp happens at durable append (ADR-0006 decision 2).
    """

    outcome: IngestOutcome
    journal_seq: Optional[int] = None
    error_code: Optional[str] = None
    message: str = ""
    retryable: bool = False
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class IngestFailure:
    """One diagnostic-stream entry (SPEC-300 §4.2: 摄入失败记入独立诊断流)."""

    envelope: dict[str, Any]
    error_code: str
    message: str


@dataclass(frozen=True)
class GatewayMetrics:
    """SPEC-300 §8 duty: 队列深度、拒绝数、重复数与存储失败可见."""

    queue_depth: int
    accepted: int
    duplicate: int
    rejected: int
    coalesced: int
    journal_duplicates: int
    subscriber_errors: int
    storage_failures: int
    unhealthy: bool


@dataclass(frozen=True)
class GatewayConfig:
    """SPEC-300 §11 ``ingestion`` block (defaults = the §11 values)."""

    queue_capacity: int = 10_000
    duplicate_cache_size: int = 100_000


@dataclass(frozen=True)
class PublishReceipt:
    """SPEC-300 §12 ``EventPublisher.publish`` receipt (producer view)."""

    accepted: bool
    outcome: IngestOutcome
    journal_seq: Optional[int] = None
    error_code: Optional[str] = None
    retryable: bool = False


class EventPublisher:
    """SPEC-300 §12 required producer-facing interface.

    A thin facade over one :class:`EventGateway` — publishers get a receipt,
    never internal gateway types.
    """

    def __init__(self, gateway: "EventGateway") -> None:
        self._gateway = gateway

    def publish(self, event: PublishableEvent) -> PublishReceipt:
        result = self._gateway.accept(event)
        return PublishReceipt(
            accepted=result.outcome is IngestOutcome.ACCEPTED,
            outcome=result.outcome,
            journal_seq=result.journal_seq,
            error_code=result.error_code,
            retryable=result.retryable,
        )


class EventGateway:
    """SPEC-300 §4.1 Event Gateway (application-layer orchestration)."""

    def __init__(
        self,
        journal: EventJournal,
        config: GatewayConfig | None = None,
    ) -> None:
        config = config or GatewayConfig()
        self._journal = journal
        self._config = config
        self._queue = BoundedEventQueue(config.queue_capacity)
        self._subscribers: list[CommitCallback] = []
        # (producer_id, event_id) -> stamped seq; None = queued, not yet
        # appended. OrderedDict = LRU bounded by duplicate_cache_size (§11).
        self._duplicates: OrderedDict[tuple[str, str], Optional[int]] = OrderedDict()
        self._lock = threading.Lock()
        self._accepted = 0
        self._duplicate = 0
        self._rejected = 0
        self._coalesced = 0
        self._journal_duplicates = 0
        self._subscriber_errors = 0
        self._storage_failures = 0
        self._unhealthy = False
        self._failures: list[IngestFailure] = []

    # --- producer side -------------------------------------------------------

    def accept(self, event: PublishableEvent) -> IngestResult:
        """Validate, dedup-check and admit one event (SPEC-300 §4.1/§7).

        Never raises for a per-event contract violation — every rejection is
        a structured :class:`IngestResult` (IC §6). Rejections happen before
        queueing: a malformed event consumes no queue capacity.
        """
        try:
            data, envelope = self._normalize(event)
        except EnvelopeError as exc:
            return self._reject(exc.code.value, str(exc))

        key = envelope.dedup_key
        with self._lock:
            if key in self._duplicates:
                # Idempotent success at the API boundary (SPEC-300 §13); the
                # seq rides along once the durable append has stamped it.
                self._duplicate += 1
                self._duplicates.move_to_end(key)
                seq = self._duplicates[key]
                details = {} if seq is not None else {"pending": True}
                return IngestResult(
                    IngestOutcome.DUPLICATE,
                    journal_seq=seq,
                    details=details,
                )
            if self._unhealthy:
                # Journal commit failures are explicit backpressure (§8):
                # new ingests are refused with the retryable code while the
                # failure stands — queued events are retained, not lost.
                self._rejected += 1
                return IngestResult(
                    IngestOutcome.REJECTED,
                    error_code="OBS_STORAGE_UNAVAILABLE",
                    message=(
                        "journal commit is failing; event refused until the "
                        "storage recovers (retryable, SPEC-300 §8)"
                    ),
                    retryable=True,
                )

        coalesce_key = (
            _coalesce_key(envelope) if is_coalescable(envelope.event_type) else None
        )
        try:
            outcome = self._queue.put(data, coalesce_key)
        except QueueFullError as exc:
            with self._lock:
                self._rejected += 1
            return IngestResult(
                IngestOutcome.REJECTED,
                error_code=OBS_QUEUE_FULL,
                message=str(exc),
                retryable=True,
                details={"queue_capacity": exc.capacity},
            )

        with self._lock:
            if outcome == "coalesced":
                # The overwritten old value never reaches the journal — the
                # sanctioned SPEC-301 §5 drop for high-fanout progress events.
                self._coalesced += 1
                return IngestResult(
                    IngestOutcome.ACCEPTED, details={"coalesced": True}
                )
            self._duplicates[key] = None
            self._duplicates.move_to_end(key)
            self._evict_overflow()
            self._accepted += 1
            return IngestResult(IngestOutcome.ACCEPTED)

    def publish(self, event: PublishableEvent) -> PublishReceipt:
        """Producer-facing alias (SPEC-300 §12 ``EventPublisher.publish``)."""
        return EventPublisher(self).publish(event)

    # --- dispatcher side ------------------------------------------------------

    def drain(self, limit: int | None = None) -> int:
        """Append queued events to the journal; returns the committed count.

        One append attempt per event (retry policy is producer-side,
        OBSERVATION-INTEGRATION-CONTRACT §5). A storage failure moves the
        failing event into the diagnostic failure stream (§4.2), marks the
        gateway unhealthy and stops the drain — queued events behind it stay
        queued and are retried on the next drain after recovery.
        """
        committed = 0
        while limit is None or committed < limit:
            batch = self._queue.pop_batch(1)
            if not batch:
                break
            data = batch[0]
            envelope = parse_envelope(data)
            key = envelope.dedup_key
            try:
                seq, duplicate = self._journal.append(data)
            except StorageError as exc:
                self._record_failure(data, exc)
                # The event never landed: it is explicitly recorded in the
                # diagnostic stream (§4.2) and removed from the dedup cache
                # so a producer retry is not mislabeled a duplicate. Events
                # behind it STAY queued — stopping here keeps every accepted
                # event in exactly one of {journal, queue, diagnostic stream}.
                with self._lock:
                    self._duplicates.pop(key, None)
                return committed
            with self._lock:
                self._unhealthy = False
                self._duplicates[key] = seq
                self._duplicates.move_to_end(key)
                if duplicate:
                    self._journal_duplicates += 1
                else:
                    committed += 1
            if not duplicate:
                stamped = dict(data)
                stamped["journal_seq"] = seq
                self._fan_out(stamped)
        return committed

    def subscribe(self, callback: CommitCallback) -> None:
        """Register a committed-event callback (SPEC-300 §7 step 5).

        Subscribers run on the drain caller's thread; a raising subscriber
        never breaks ingestion — it is counted and skipped.
        """
        self._subscribers.append(callback)

    # --- observability --------------------------------------------------------

    def metrics(self) -> GatewayMetrics:
        with self._lock:
            return GatewayMetrics(
                queue_depth=self._queue.depth(),
                accepted=self._accepted,
                duplicate=self._duplicate,
                rejected=self._rejected,
                coalesced=self._coalesced,
                journal_duplicates=self._journal_duplicates,
                subscriber_errors=self._subscriber_errors,
                storage_failures=self._storage_failures,
                unhealthy=self._unhealthy,
            )

    def pending(self, limit: int | None = None) -> list[dict[str, Any]]:
        """Undelivered queued envelopes, oldest-first (diagnostics/tests)."""
        return self._queue.pending(limit)

    def failures(self) -> tuple[IngestFailure, ...]:
        """Diagnostic failure stream snapshot (§4.2; never domain events)."""
        with self._lock:
            return tuple(self._failures)

    # --- internals -------------------------------------------------------------

    def _normalize(
        self, event: PublishableEvent
    ) -> tuple[dict[str, Any], EventEnvelope]:
        """Return (stored form, validated model); raises EnvelopeError.

        The stored form preserves producer extras (SPEC-301 §8: consumers
        ignore unknown optional fields — the journal still records them);
        the model re-validates through the frozen #46 surface either way.
        """
        if isinstance(event, EventEnvelope):
            event.ensure_publishable()
            return event.model_dump(mode="json"), event
        data = _backfill_observed_timepoint(event)
        envelope = parse_envelope(data)
        envelope.ensure_publishable()
        return data, envelope

    def _reject(self, code: str, message: str) -> IngestResult:
        with self._lock:
            self._rejected += 1
        return IngestResult(IngestOutcome.REJECTED, error_code=code, message=message)

    def _record_failure(self, data: dict[str, Any], exc: StorageError) -> None:
        with self._lock:
            self._unhealthy = True
            self._storage_failures += 1
            self._failures.append(
                IngestFailure(
                    envelope=data,
                    error_code="OBS_STORAGE_UNAVAILABLE",
                    message=str(exc),
                )
            )

    def _fan_out(self, stamped: dict[str, Any]) -> None:
        for callback in tuple(self._subscribers):
            try:
                callback(stamped)
            except Exception:  # noqa: BLE001 — subscriber faults never kill ingest
                with self._lock:
                    self._subscriber_errors += 1

    def _evict_overflow(self) -> None:
        while len(self._duplicates) > self._config.duplicate_cache_size:
            self._duplicates.popitem(last=False)


def _coalesce_key(envelope: EventEnvelope) -> CoalesceKey:
    """One pending slot per (producer, session, run, type) — SPEC-301 §5.

    Progress of two different runs (or producers) never overwrites each
    other; session-level events coalesce only within the same session.
    """
    return (
        envelope.producer.producer_id,
        envelope.scope.session_id or "",
        envelope.scope.run_id or "",
        envelope.event_type,
    )


def _backfill_observed_timepoint(data: dict[str, Any]) -> dict[str, Any]:
    """§4.1: fill ``time.observed`` (wall:utc) when the producer omitted it.

    The single sanctioned repair. The caller's dict is copied; the source
    timepoint is preserved untouched (§4.1 duty 4). Anything still missing
    afterwards is left for :func:`parse_envelope` to reject structurally.
    """
    if not isinstance(data, dict):
        return data
    time_block = data.get("time")
    if not isinstance(time_block, dict) or "observed" in time_block:
        return data
    filled = dict(data)
    observed = {
        "value_ns": _time.time_ns(),
        "clock_domain": _BACKFILL_CLOCK_DOMAIN,
        "clock_epoch": 0,
    }
    filled["time"] = {**time_block, "observed": observed}
    return filled
