"""Shared fixtures for the SPEC-302 metrics-engine unit tests (ticket #50).

Envelope documents are built to the SPEC-301 §2 shape and passed through
``parse_envelope`` so a non-conforming fixture cannot reach the engine —
the same construction-guarantee discipline the #41 emitter uses. ``ts.*``
payloads carry the mandatory source/confidence axes (#13 Q3-i) plus the
G3 derivation-contract keys documented in
``application.observation.metrics.catalog``.
"""

from typing import Any

from domain.observation import new_event_id, parse_envelope


def raw_envelope(
    *,
    event_type: str,
    session_id: str | None = "sess-1",
    source_ns: int = 1_000,
    clock_domain: str | None = None,
    clock_epoch: int = 0,
    payload: dict[str, Any] | None = None,
    run_id: str | None = None,
    pid: int | None = None,
    service_id: str | None = None,
    validate: bool = True,
) -> dict:
    """SPEC-301 §2-shaped envelope, schema-validated by default."""
    document = {
        "schema_version": "1.0",
        "event_id": new_event_id(),
        "event_type": event_type,
        "producer": {
            "producer_id": "fixture-producer",
            "producer_version": "0.1.0",
            "instance_id": "inst-1",
        },
        "scope": {
            "tenant_id": "local",
            "session_id": session_id,
            "run_id": run_id,
        },
        "time": {
            "source": {
                "value_ns": source_ns,
                "clock_domain": clock_domain or f"sim:{session_id}",
                "clock_epoch": clock_epoch,
            },
            "observed": {
                "value_ns": source_ns + 5,
                "clock_domain": "wall:utc",
                "clock_epoch": 0,
            },
        },
        "severity": "info",
        "payload": dict(payload or {}),
        "tags": [],
    }
    if pid is not None or service_id is not None:
        document["correlation"] = {
            "trace_id": None,
            "span_id": None,
            "parent_event_id": None,
            "fault_id": None,
            "node_id": None,
            "port_id": None,
            "service_id": service_id,
            "pid": pid,
        }
    if validate:
        return parse_envelope(document).model_dump(mode="json")
    return document


def ts_payload(**extra: Any) -> dict:
    """``ts.*`` payload with the mandatory observation axes (#13 Q3-i)."""
    return {"source": "internal_parser", "confidence": "parsed", **extra}


class RecordRow:
    """Structural stand-in for ``adapters.storage.journal.EventRow``."""

    def __init__(self, envelope: dict, journal_seq: int) -> None:
        self.envelope = envelope
        self.journal_seq = journal_seq
        self.event_type = envelope["event_type"]
        self.session_id = envelope["scope"]["session_id"]


def record(envelope: dict, journal_seq: int = 1) -> RecordRow:
    return RecordRow(envelope, journal_seq)
