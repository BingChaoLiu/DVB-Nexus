"""EventGateway.accept — validation and structured rejection (SPEC-300 §4.1/§8).

Seam (delegator-approved): ``EventGateway.accept(event) -> IngestResult`` —
the three-outcome structured result of OBSERVATION-INTEGRATION-CONTRACT §6
(accepted / duplicate / rejected). Malformed events are refused BEFORE any
queueing with a SPEC-300 §13 code; nothing is silently repaired except the
one §4.1-mandated backfill (``time.observed`` when the producer omitted it).

Unit layer: pure in-memory, no I/O, no threads — the journal is a fake and
draining is driven manually by the tests.
"""

import pytest

from application.observation.gateway import EventGateway, EventPublisher, IngestOutcome
from domain.observation import EventEnvelope, new_event_id


def _raw_envelope(
    event_id: str | None = None,
    event_type: str = "simulation.run_started",
    producer_id: str = "sim-engine",
    session_id: str = "sess-1",
    payload: dict | None = None,
) -> dict:
    """Minimal SPEC-301 §2-shaped raw envelope (required fields only).

    fault.* events carry their registered SPEC-204 §9 payload shape
    (ticket #56) — the backpressure/dedup cells exercise delivery policy,
    not payload laxity, so the default keeps those envelopes spec-valid.
    """
    if payload is None:
        if event_type == "fault.injected":
            payload = {
                "fault_id": "fd000000-0000-4000-8000-000000000001",
                "fault_type": "PAT_MISSING",
                "injection_index": 0,
                "expected_observations": ["ts.psi_section_observed"],
            }
        elif event_type == "fault.applied":
            payload = {
                "fault_id": "fd000000-0000-4000-8000-000000000001",
                "fault_type": "PAT_MISSING",
                "injection_index": 0,
                "applied_packet_indexes": [12],
            }
        elif event_type.startswith("fault."):
            payload = {
                "fault_id": "fd000000-0000-4000-8000-000000000001",
                "fault_type": "PAT_MISSING",
                "injection_index": 0,
            }
        elif event_type == "recovery.verification_completed":
            payload = {
                "verdict": "PASS",
                "run_id": "run-r",
                "baseline_run_id": "run-b",
                "scenario_id": "scn-1",
                "scenario_version": "1.0.0",
                "scenario_content_hash": "a" * 64,
                "criteria": [
                    {
                        "criterion_id": "sc-01",
                        "kind": "fault_inactive",
                        "mandatory": True,
                        "result": "PASS",
                        "reason_code": None,
                        "reason": None,
                    }
                ],
                "summary": "all mandatory criteria passed",
            }
        else:
            payload = {}
    return {
        "schema_version": "1.0",
        "event_id": event_id or new_event_id(),
        "event_type": event_type,
        "producer": {
            "producer_id": producer_id,
            "producer_version": "0.1.0",
            "instance_id": "inst-1",
        },
        "scope": {"tenant_id": "local", "session_id": session_id},
        "time": {
            "source": {
                "value_ns": 1,
                "clock_domain": "sim:sess-1",
                "clock_epoch": 0,
            },
            "observed": {
                "value_ns": 2,
                "clock_domain": "wall:utc",
                "clock_epoch": 0,
            },
        },
        "severity": "info",
        "payload": payload,
        "tags": [],
    }


@pytest.fixture
def gateway() -> EventGateway:
    return EventGateway(journal=_FakeJournal())


class _FakeJournal:
    """In-memory EventJournal stand-in (append/query/max_seq protocol)."""

    def __init__(self) -> None:
        self.appended: list[dict] = []

    def append(self, envelope: dict) -> tuple[int, bool]:
        self.appended.append(envelope)
        return (len(self.appended), False)

    def query(self, session_id: str, *, after_seq: int = 0, limit: int = 100):
        return []

    def max_seq(self, session_id: str) -> int:
        return len(self.appended)


# --- accept: valid event is accepted (SPEC-300 §4.1 duty 6) ------------------


def test_accept_returns_accepted_for_valid_raw_envelope(gateway) -> None:
    result = gateway.accept(_raw_envelope())

    assert result.outcome is IngestOutcome.ACCEPTED
    assert result.error_code is None
    assert result.journal_seq is None  # stamped only at durable append


def test_accept_accepts_a_prebuilt_event_envelope(gateway) -> None:
    envelope = EventEnvelope.model_validate(_raw_envelope())

    result = gateway.accept(envelope)

    assert result.outcome is IngestOutcome.ACCEPTED


def test_accept_requires_empty_publish_view_journal_seq(gateway) -> None:
    """ADR-0006 decision 2: producers never fill journal_seq; the gateway
    refuses the event instead of silently dropping the forged order."""
    raw = _raw_envelope()
    raw["journal_seq"] = 42

    result = gateway.accept(raw)

    assert result.outcome is IngestOutcome.REJECTED
    assert result.error_code == "OBS_INVALID_ENVELOPE"
    assert "journal_seq" in result.message


# --- accept: structured rejection before queueing (§4.1 duty 1/§13) ---------


def test_accept_rejects_malformed_envelope_with_structured_code(gateway) -> None:
    raw = _raw_envelope()
    del raw["producer"]

    result = gateway.accept(raw)

    assert result.outcome is IngestOutcome.REJECTED
    assert result.error_code == "OBS_INVALID_ENVELOPE"
    assert result.message
    assert result.retryable is False


def test_accept_rejects_unregistered_event_type(gateway) -> None:
    raw = _raw_envelope(event_type="simulation.packet_visualized")

    result = gateway.accept(raw)

    assert result.outcome is IngestOutcome.REJECTED
    assert result.error_code == "OBS_INVALID_ENVELOPE"


def test_accept_rejects_withdrawn_namespace(gateway) -> None:
    raw = _raw_envelope(event_type="observation.alert_changed")

    result = gateway.accept(raw)

    assert result.outcome is IngestOutcome.REJECTED
    assert result.error_code == "OBS_INVALID_ENVELOPE"


def test_accept_rejects_unsupported_schema_version(gateway) -> None:
    raw = _raw_envelope()
    raw["schema_version"] = "2.0"

    result = gateway.accept(raw)

    assert result.outcome is IngestOutcome.REJECTED
    assert result.error_code == "OBS_UNSUPPORTED_SCHEMA"


def test_accept_rejects_oversized_payload(gateway) -> None:
    raw = _raw_envelope()
    raw["payload"] = {"blob": "x" * (256 * 1024 + 1)}

    result = gateway.accept(raw)

    assert result.outcome is IngestOutcome.REJECTED
    assert result.error_code == "OBS_PAYLOAD_TOO_LARGE"


# --- accept: the one sanctioned repair — time.observed backfill (§4.1) ------


def test_accept_backfills_missing_observed_timepoint_as_wall_utc(gateway) -> None:
    """§4.1: when the producer omits ``time.observed`` the gateway fills it
    (wall:utc). This is the only sanctioned repair — everything else that is
    semantically illegal stays rejected (无隐式修复)."""
    raw = _raw_envelope()
    del raw["time"]["observed"]

    result = gateway.accept(raw)

    assert result.outcome is IngestOutcome.ACCEPTED
    pending = gateway.pending()[0]
    observed = pending["time"]["observed"]
    assert observed["clock_domain"] == "wall:utc"
    assert isinstance(observed["value_ns"], int)
    assert observed["clock_epoch"] >= 0
    # The producer's source timepoint is preserved untouched (§4.1 duty 4).
    assert pending["time"]["source"]["clock_domain"] == "sim:sess-1"


# --- EventPublisher: the §12 producer-facing receipt interface ----------------


def test_publisher_returns_accepted_receipt_before_stamp(gateway) -> None:
    publisher = EventPublisher(gateway)

    receipt = publisher.publish(_raw_envelope(event_id="pub-000001"))

    assert receipt.accepted is True
    assert receipt.outcome is IngestOutcome.ACCEPTED
    assert receipt.journal_seq is None  # stamped only at durable append
    assert receipt.error_code is None


def test_publisher_returns_duplicate_receipt_with_original_seq(gateway) -> None:
    publisher = EventPublisher(gateway)
    publisher.publish(_raw_envelope(event_id="pub-000002"))
    gateway.drain()

    receipt = publisher.publish(_raw_envelope(event_id="pub-000002"))

    assert receipt.accepted is False
    assert receipt.outcome is IngestOutcome.DUPLICATE
    assert receipt.journal_seq == 1


def test_publisher_returns_rejection_receipt_with_code(gateway) -> None:
    publisher = EventPublisher(gateway)
    raw = _raw_envelope(event_id="pub-000003")
    raw["schema_version"] = "9.9"

    receipt = publisher.publish(raw)

    assert receipt.accepted is False
    assert receipt.outcome is IngestOutcome.REJECTED
    assert receipt.error_code == "OBS_UNSUPPORTED_SCHEMA"
    assert receipt.retryable is False
