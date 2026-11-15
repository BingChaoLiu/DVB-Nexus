"""Backpressure coalesce/no-drop matrix — ticket #47 acceptance, authority
GitHub issues #8/#12 + SPEC-301 §5 (grafted backpressure terms, ADR-0006
decision 1) + SPEC-300 §8.

The matrix, one test per cell, all at the public ``accept`` seam with a
small queue capacity (fill by accepting without draining — fully
deterministic, no threads):

=======================  ==============  ======================================
incoming class           queue           outcome
=======================  ==============  ======================================
coalescable              has room        ACCEPTED
(run_progress)           full, same-key  ACCEPTED, coalesced — newest value
                         victim pending  overwrites the undelivered old value
                         full, no victim REJECTED OBS_QUEUE_FULL (explicit)
delivery-protected       has room        ACCEPTED
(fault.* / session_* /   full            REJECTED OBS_QUEUE_FULL — never
run_completed/failed /                   dropped, never coalesced
recovery.verification)
other registered         full            REJECTED OBS_QUEUE_FULL
duplicate (pending/      any             DUPLICATE — no rejection, no slot
committed)
malformed envelope       any             REJECTED structured code, no slot
=======================  ==============  ======================================

Classification comes ONLY from the frozen #46 registry
(``is_coalescable`` / ``is_delivery_protected``); these tests pin that the
gateway's admission honors it.
"""

import pytest

from application.observation.gateway import EventGateway, GatewayConfig, IngestOutcome
from tests.unit.application.observation.test_gateway_accept import (
    _FakeJournal,
    _raw_envelope,
)

_CAPACITY = 3


@pytest.fixture
def gateway() -> EventGateway:
    return EventGateway(journal=_FakeJournal(), config=GatewayConfig(queue_capacity=_CAPACITY))


def _fill(gateway: EventGateway, event_type: str, count: int) -> None:
    for index in range(count):
        raw = _raw_envelope(
            event_id=f"fill-{event_type}-{index:04d}", event_type=event_type
        )
        result = gateway.accept(raw)
        assert result.outcome is not IngestOutcome.REJECTED, result


# --- cell 1: coalescable, room available -------------------------------------


def test_coalescable_event_is_accepted_when_queue_has_room(gateway) -> None:
    result = gateway.accept(
        _raw_envelope(event_id="prog-000001", event_type="simulation.run_progress")
    )

    assert result.outcome is IngestOutcome.ACCEPTED
    assert result.details.get("coalesced") is None


# --- cell 2: coalescable, full queue, same-key victim ------------------------


def test_coalescable_event_overwrites_undelivered_same_key_value(gateway) -> None:
    delivered: list[dict] = []
    gateway.subscribe(delivered.append)
    # Reach the cell state: one pending progress + a full queue behind it.
    first = _raw_envelope(event_id="prog-000000", event_type="simulation.run_progress")
    first["payload"] = {"step": 0}
    assert gateway.accept(first).outcome is IngestOutcome.ACCEPTED
    _fill(gateway, "fault.injected", _CAPACITY - 1)

    for step in (1, 2, 3):
        newer = _raw_envelope(
            event_id=f"prog-{step:06d}", event_type="simulation.run_progress"
        )
        newer["payload"] = {"step": step}
        outcome = gateway.accept(newer)
        # Queue stays full, yet every newer progress is accepted by
        # coalescing over the pending same-key value.
        assert outcome.outcome is IngestOutcome.ACCEPTED
        assert outcome.details.get("coalesced") is True

    gateway.drain()

    # Only ONE run_progress per (producer, session, run) slot lands, and the
    # delivered value is the NEWEST one — the overwritten intermediates
    # never reach the journal or any subscriber.
    progress = [
        record
        for record in delivered
        if record["event_type"] == "simulation.run_progress"
    ]
    assert [record["payload"]["step"] for record in progress] == [3]
    assert gateway.metrics().coalesced == 3


# --- cell 3: coalescable, full queue, no victim ------------------------------


def test_coalescable_event_with_no_victim_is_rejected_explicitly(gateway) -> None:
    _fill(gateway, "fault.injected", _CAPACITY)

    result = gateway.accept(
        _raw_envelope(event_id="prog-late-01", event_type="simulation.run_progress")
    )

    assert result.outcome is IngestOutcome.REJECTED
    assert result.error_code == "OBS_QUEUE_FULL"
    assert result.retryable is True


def test_coalescing_is_scoped_per_run_not_per_event_type(gateway) -> None:
    """One pending run_progress of run A never absorbs run B's progress."""
    for run_id in ("run-a",):
        raw = _raw_envelope(event_id="prog-a-0001", event_type="simulation.run_progress")
        raw["scope"]["run_id"] = run_id
        gateway.accept(raw)
    _fill(gateway, "fault.injected", _CAPACITY - 1)

    other_run = _raw_envelope(event_id="prog-b-0001", event_type="simulation.run_progress")
    other_run["scope"]["run_id"] = "run-b"
    result = gateway.accept(other_run)

    assert result.outcome is IngestOutcome.REJECTED
    assert result.error_code == "OBS_QUEUE_FULL"


# --- cells 4-6: delivery-protected family ------------------------------------


def test_delivery_protected_event_is_accepted_when_queue_has_room(gateway) -> None:
    result = gateway.accept(_raw_envelope(event_id="fault-00001", event_type="fault.injected"))

    assert result.outcome is IngestOutcome.ACCEPTED


@pytest.mark.parametrize(
    "event_type",
    [
        "fault.injected",
        "fault.activated",
        "fault.applied",
        "fault.cleared",
        "simulation.session_created",
        "simulation.session_stopped",
        "simulation.run_completed",
        "simulation.run_failed",
        "recovery.verification_completed",
    ],
)
def test_delivery_protected_event_is_never_dropped_when_full(
    gateway, event_type: str
) -> None:
    _fill(gateway, "fault.injected", _CAPACITY)

    result = gateway.accept(
        _raw_envelope(event_id="prot-late-1", event_type=event_type)
    )

    assert result.outcome is IngestOutcome.REJECTED
    assert result.error_code == "OBS_QUEUE_FULL"
    assert result.retryable is True
    # Never coalesced either: the pending protected events stay intact.
    pending_types = {record["event_type"] for record in gateway.pending()}
    assert pending_types == {"fault.injected"}


def test_protected_event_is_not_absorbed_by_later_same_type_event(gateway) -> None:
    """Two fault.injected of the same producer while full: the second is
    rejected; the first stays queued — protected classes never coalesce."""
    _fill(gateway, "fault.injected", _CAPACITY)

    second = gateway.accept(
        _raw_envelope(event_id="fault-late-2", event_type="fault.injected")
    )

    assert second.outcome is IngestOutcome.REJECTED
    assert gateway.metrics().coalesced == 0
    assert len(gateway.pending()) == _CAPACITY


# --- cell 7: other registered events ------------------------------------------


def test_regular_registered_event_is_rejected_explicitly_when_full(gateway) -> None:
    _fill(gateway, "fault.injected", _CAPACITY)

    result = gateway.accept(
        _raw_envelope(
            event_id="ts-late-0001",
            event_type="ts.continuity_error",
        )
        | {"payload": {"source": "generator", "confidence": "simulated"}}
    )

    assert result.outcome is IngestOutcome.REJECTED
    assert result.error_code == "OBS_QUEUE_FULL"


# --- cell 8: duplicate under backpressure -------------------------------------


def test_duplicate_of_pending_event_is_idempotent_even_when_full(gateway) -> None:
    raw = _raw_envelope(event_id="dup-000001")
    gateway.accept(raw)
    _fill(gateway, "fault.injected", _CAPACITY - 1)

    replay = gateway.accept(raw)

    assert replay.outcome is IngestOutcome.DUPLICATE
    assert gateway.metrics().queue_depth == _CAPACITY  # no extra slot consumed


# --- cell 9: malformed under any queue state ----------------------------------


def test_malformed_event_is_rejected_without_consuming_a_slot(gateway) -> None:
    _fill(gateway, "fault.injected", _CAPACITY)
    raw = _raw_envelope(event_id="bad-000001")
    raw["severity"] = "catastrophic"

    result = gateway.accept(raw)

    assert result.outcome is IngestOutcome.REJECTED
    assert result.error_code == "OBS_INVALID_ENVELOPE"
    assert gateway.metrics().queue_depth == _CAPACITY
