"""``recovery.verification_completed`` envelope construction (ticket #56).

The authoritative recovery event name (ADR-0006 decision 5; the #46 frozen
registry). The payload mirrors the SPEC-206 §4 verdict structure (ticket
#56 declaration — see the registry test for the shape). Construction
guarantee: every built document passes :func:`parse_envelope` before it is
returned; ``journal_seq`` is NEVER filled (the gateway stamps it).

Producer identity: ``recovery-verifier`` — the verification face is its own
producer role (the verdict is not a fault-execution fact and not a session
lifecycle fact); recorded in the ticket #56 report. Virtual ``time.source``
anchors to an injected deterministic value (the service passes the latest
observed source_ns of the recovery run — the ticket #54 posture); the wall
``time.observed`` is the operational verification timestamp (the one §4
permitted non-deterministic field).
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

from domain.observation import parse_envelope
from domain.observation.registry import is_delivery_protected, validate_payload
from simulation.verification.events import (
    PRODUCER_ID,
    PRODUCER_VERSION,
    verification_completed_envelope,
)


def _criteria_payload():
    return [
        {
            "criterion_id": "sc-01",
            "kind": "fault_inactive",
            "mandatory": True,
            "result": "PASS",
            "reason_code": None,
            "reason": None,
        }
    ]


def _payload(**overrides):
    payload = {
        "verdict": "PASS",
        "run_id": "run-recovery",
        "baseline_run_id": "run-baseline",
        "scenario_id": "9c0f0000-0000-4000-8000-000000000001",
        "scenario_version": "1.0.0",
        "scenario_content_hash": "2b" * 32,
        "criteria": _criteria_payload(),
        "summary": "1/1 mandatory criteria passed",
    }
    payload.update(overrides)
    return payload


class TestEnvelopeConformance:
    def test_built_document_passes_envelope_and_payload_schema(self):
        document = verification_completed_envelope(
            session_id="sess-verif-env",
            payload=_payload(),
            source_ns=42_000,
            observed_ns=1_700_000_000_000_000,
        )
        envelope = parse_envelope(document)
        envelope.ensure_publishable()  # producers never fill journal_seq
        assert envelope.scope.run_id == "run-recovery"
        assert envelope.producer.producer_id == PRODUCER_ID == "recovery-verifier"
        assert envelope.producer.producer_version == PRODUCER_VERSION
        validate_payload(document["event_type"], document["payload"])

    def test_event_type_is_the_registered_protected_name(self):
        document = verification_completed_envelope(
            session_id="sess-verif-env",
            payload=_payload(),
            source_ns=0,
            observed_ns=1,
        )
        assert document["event_type"] == "recovery.verification_completed"
        assert is_delivery_protected(document["event_type"])

    @pytest.mark.parametrize(
        ("verdict", "severity"),
        [("PASS", "info"), ("FAIL", "warning"), ("INCONCLUSIVE", "notice")],
    )
    def test_verdict_severity_mapping(self, verdict, severity):
        document = verification_completed_envelope(
            session_id="sess-verif-env",
            payload=_payload(verdict=verdict),
            source_ns=0,
            observed_ns=1,
        )
        assert document["severity"] == severity

    def test_dual_clock_identity(self):
        document = verification_completed_envelope(
            session_id="sess-verif-clock",
            payload=_payload(),
            source_ns=7_000,
            observed_ns=9_000,
        )
        assert document["time"]["source"] == {
            "value_ns": 7_000,
            "clock_domain": "sim:sess-verif-clock",
            "clock_epoch": 0,
        }
        assert document["time"]["observed"]["clock_domain"] == "wall:utc"
