"""EventGateway idempotency — (producer_id, event_id) (SPEC-300 §4.1 duty 5,
§13, OBSERVATION-INTEGRATION-CONTRACT §5).

Seam: ``accept`` answers ``duplicate`` for a replayed event — idempotent
success at the API boundary, returning the ORIGINAL journal_seq once the
durable append has stamped it (SPEC-300 §13: 重复提交返回原 journal_seq).
"""

import pytest

from application.observation.gateway import EventGateway, IngestOutcome
from tests.unit.application.observation.test_gateway_accept import (
    _FakeJournal,
    _raw_envelope,
)


@pytest.fixture
def gateway() -> EventGateway:
    return EventGateway(journal=_FakeJournal())


def test_replayed_event_is_duplicate_with_original_seq_after_drain(gateway) -> None:
    raw = _raw_envelope(event_id="evt-dup-0001")
    assert gateway.accept(raw).outcome is IngestOutcome.ACCEPTED
    gateway.drain()
    committed_seq = gateway.metrics().accepted

    replay = gateway.accept(_raw_envelope(event_id="evt-dup-0001"))

    assert replay.outcome is IngestOutcome.DUPLICATE
    assert replay.journal_seq == committed_seq
    # No second journal row, no second fan-out: depth stays empty.
    assert gateway.metrics().queue_depth == 0


def test_replayed_event_while_pending_is_duplicate_without_queue_slot(gateway) -> None:
    """A retry racing the dispatcher is answered idempotently from the
    pending marker — it must not consume a second queue slot."""
    raw = _raw_envelope(event_id="evt-pending-01")
    assert gateway.accept(raw).outcome is IngestOutcome.ACCEPTED

    replay = gateway.accept(raw)

    assert replay.outcome is IngestOutcome.DUPLICATE
    assert replay.journal_seq is None  # not stamped yet
    assert replay.details == {"pending": True}
    assert gateway.metrics().queue_depth == 1


def test_same_event_id_from_a_different_producer_is_not_a_duplicate(gateway) -> None:
    """The idempotency key is the PAIR (producer_id, event_id) — SPEC-301 §5."""
    assert gateway.accept(
        _raw_envelope(event_id="evt-x-00001", producer_id="sim-engine")
    ).outcome is IngestOutcome.ACCEPTED

    other = gateway.accept(
        _raw_envelope(event_id="evt-x-00001", producer_id="ts-core")
    )

    assert other.outcome is IngestOutcome.ACCEPTED
    assert gateway.metrics().queue_depth == 2
