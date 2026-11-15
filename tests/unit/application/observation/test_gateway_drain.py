"""EventGateway.drain — journal commit, fan-out, storage-failure diagnostics.

Seam: ``drain`` moves queued events through the SPEC-502 journal (the unique
``journal_seq`` stamp point) and fans committed envelopes out to subscribers
(SPEC-300 §7 steps 4-5). Storage failures go to the separate diagnostic
stream (§4.2 — 摄入失败记入独立诊断流，不得递归发布为普通领域事件) and surface
as explicit retryable ``OBS_STORAGE_UNAVAILABLE`` backpressure (§8).
"""

import pytest

from adapters.storage.errors import StorageWriteFailure
from application.observation.gateway import (
    EventGateway,
    GatewayConfig,
    IngestOutcome,
)
from tests.unit.application.observation.test_gateway_accept import _raw_envelope


class _FakeJournal:
    """In-memory journal with an injectable failure mode (no I/O)."""

    def __init__(self, fail: bool = False, dedup: bool = True) -> None:
        self.appended: list[dict] = []
        self._fail = fail
        self._dedup = dedup
        self._seen: set[tuple[str, str]] = set()

    def append(self, envelope: dict) -> tuple[int, bool]:
        if self._fail:
            raise StorageWriteFailure("simulated journal commit failure")
        key = (envelope["producer"]["producer_id"], envelope["event_id"])
        if self._dedup and key in self._seen:
            original = next(
                index + 1
                for index, seen in enumerate(self.appended)
                if (seen["producer"]["producer_id"], seen["event_id"]) == key
            )
            return (original, True)
        self._seen.add(key)
        self.appended.append(envelope)
        return (len(self.appended), False)

    def query(self, session_id: str, *, after_seq: int = 0, limit: int = 100):
        return []

    def max_seq(self, session_id: str) -> int:
        return len(self.appended)


@pytest.fixture
def journal() -> _FakeJournal:
    return _FakeJournal()


@pytest.fixture
def gateway(journal) -> EventGateway:
    return EventGateway(
        journal=journal, config=GatewayConfig(queue_capacity=10, duplicate_cache_size=8)
    )


def _accept(gateway: EventGateway, event_id: str, **kwargs) -> None:
    raw = _raw_envelope(event_id=event_id, **kwargs)
    result = gateway.accept(raw)
    assert result.outcome is IngestOutcome.ACCEPTED, result


# --- drain: stamp and fan out in admission order ------------------------------


def test_drain_commits_queued_events_and_fans_out_stamped_envelopes(gateway) -> None:
    delivered: list[dict] = []
    gateway.subscribe(delivered.append)
    for index in range(3):
        _accept(gateway, f"evt-{index:07d}")

    committed = gateway.drain()

    assert committed == 3
    assert [record["journal_seq"] for record in delivered] == [1, 2, 3]
    assert delivered[0]["event_id"] == "evt-0000000"
    assert gateway.metrics().queue_depth == 0


def test_drain_without_subscribers_still_commits(gateway, journal) -> None:
    _accept(gateway, "evt-0000009")
    assert gateway.drain() == 1
    assert len(journal.appended) == 1


def test_drain_respects_limit_and_keeps_the_rest_queued(gateway) -> None:
    for index in range(3):
        _accept(gateway, f"evt-{index:07d}")

    committed = gateway.drain(limit=2)

    assert committed == 2
    assert gateway.metrics().queue_depth == 1


def test_raising_subscriber_never_breaks_ingestion(gateway) -> None:
    gateway.subscribe(lambda record: (_ for _ in ()).throw(RuntimeError("slow UI")))
    delivered: list[dict] = []
    gateway.subscribe(delivered.append)
    _accept(gateway, "evt-0000007")

    committed = gateway.drain()

    assert committed == 1
    assert len(delivered) == 1
    assert gateway.metrics().subscriber_errors == 1


# --- journal-side dedup backstop (cache miss path) -----------------------------


def test_journal_dedup_backstop_suppresses_second_fan_out() -> None:
    """After a cache eviction/restart the journal's (producer_id, event_id)
    unique index is the authority: the replay commits no second row and no
    second fan-out happens (at-least-once + idempotent, SPEC-301 §5)."""
    journal = _FakeJournal(dedup=True)
    gateway = EventGateway(
        journal=journal, config=GatewayConfig(duplicate_cache_size=4)
    )
    delivered: list[dict] = []
    gateway.subscribe(delivered.append)

    for index in range(5):
        _accept(gateway, f"evt-{index:07d}")
    gateway.drain()
    assert len(delivered) == 5

    # Cache bookkeeping after the drain re-caches every stamped event; one
    # new accept pushes the oldest entry (evt-...001) out of the LRU.
    _accept(gateway, "evt-0000005")
    # Re-accept the evicted event: cache MISS -> queued -> the journal
    # answers duplicate=True with the ORIGINAL seq.
    _accept(gateway, "evt-0000001")
    committed = gateway.drain()

    # evt-...005 is genuinely new (committed + fanned out); the replay of
    # evt-...001 lands on the journal's unique index: no second row, no
    # second fan-out.
    assert committed == 1
    assert len(delivered) == 6
    assert len(journal.appended) == 6  # evt-...005 is the only new row
    assert (
        sum(
            1
            for record in journal.appended
            if record["event_id"] == "evt-0000001"
        )
        == 1
    )
    assert gateway.metrics().journal_duplicates == 1


# --- storage failure: explicit diagnostic stream, never a silent drop ---------


def test_storage_failure_records_diagnostic_and_marks_unhealthy() -> None:
    journal = _FakeJournal(fail=True)
    gateway = EventGateway(journal=journal)
    _accept(gateway, "evt-0000001")
    _accept(gateway, "evt-0000002")

    committed = gateway.drain()

    assert committed == 0
    metrics = gateway.metrics()
    assert metrics.unhealthy is True
    assert metrics.storage_failures == 1
    failures = gateway.failures()
    assert len(failures) == 1
    assert failures[0].error_code == "OBS_STORAGE_UNAVAILABLE"
    assert failures[0].envelope["event_id"] == "evt-0000001"
    # The failing event is explicitly recorded (§4.2), NOT silently dropped,
    # and NOT re-published as a domain event (no subscriber fan-out).

    # New ingests are refused explicitly while the failure stands (§8).
    rejected = gateway.accept(_raw_envelope(event_id="evt-0000003"))
    assert rejected.outcome is IngestOutcome.REJECTED
    assert rejected.error_code == "OBS_STORAGE_UNAVAILABLE"
    assert rejected.retryable is True


def test_gateway_recovers_after_storage_comes_back() -> None:
    journal = _FakeJournal(fail=True)
    gateway = EventGateway(journal=journal)
    _accept(gateway, "evt-0000001")  # will fail at append -> diagnostics
    _accept(gateway, "evt-0000002")  # stays queued behind the failure
    gateway.drain()
    assert gateway.metrics().unhealthy is True
    assert gateway.metrics().queue_depth == 1  # queued events are retained

    journal._fail = False
    # Recovery is drain-driven: the retained queued events commit on the
    # next drain and the gateway turns healthy again.
    committed = gateway.drain()

    assert committed == 1
    metrics = gateway.metrics()
    assert metrics.unhealthy is False
    assert metrics.storage_failures == 1
    # The recorded failure's event is retried by the producer (IC §5) as a
    # fresh accept once the gateway answers healthy again.
    _accept(gateway, "evt-0000001")
    assert gateway.drain() == 1
    assert gateway.metrics().accepted == 3
