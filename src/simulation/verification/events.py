"""``recovery.verification_completed`` envelope construction (ticket #56).

The authoritative recovery event name (ADR-0006 decision 5; DELIVERY_
PROTECTED in the #46 frozen registry). The payload mirrors the SPEC-206
§4 verdict structure — the shape this ticket proposes and registers in the
payload schema registry (see the module docstring of
``simulation.verification.service`` for the identity fields).

Construction guarantee (the #54 posture): every built document passes
:func:`domain.observation.parse_envelope` before it is returned, so a
non-conforming verdict event can never leave the module; ``journal_seq``
is NEVER filled (the gateway stamps the total order at durable append).

Clocks (SPEC-201 injection discipline): ``source`` is the session's
virtual domain, anchored by the service to the latest observed
``value_ns`` of the recovery run's events (deterministic replay; 0 when
the run carried no events — the recorded ticket #54 posture); ``observed``
is the wall:utc operational verification timestamp (the one §4-permitted
non-deterministic field, REQ-SIM-206-005).
"""

from __future__ import annotations

from typing import Any, Mapping

from domain.observation import new_event_id, parse_envelope

__all__ = [
    "PRODUCER_ID",
    "PRODUCER_VERSION",
    "WALL_CLOCK_DOMAIN",
    "session_clock_domain",
    "verification_completed_envelope",
]

#: Producer identity for the recovery verification face (ticket #56
#: report-recorded: the verdict is its own producer role — not a
#: fault-execution fact and not a session lifecycle fact).
PRODUCER_ID = "recovery-verifier"

#: Bumped with the verification package's spec baseline (SPEC-206 0.5.0).
PRODUCER_VERSION = "0.5.0"

#: Ingestion observation domain (SPEC-300 §6 vocabulary).
WALL_CLOCK_DOMAIN = "wall:utc"

#: Verdict → envelope severity (info ladder; a FAIL verdict is a warning
#: condition, an INCONCLUSIVE verdict is a notice — nothing raised).
_SEVERITY_BY_VERDICT = {
    "PASS": "info",
    "FAIL": "warning",
    "INCONCLUSIVE": "notice",
}

_SESSION_CLOCK_PREFIX = "sim:"


def session_clock_domain(session_id: str) -> str:
    """The session-scoped virtual clock domain name (SPEC-300 §6)."""
    return f"{_SESSION_CLOCK_PREFIX}{session_id}"


def verification_completed_envelope(
    *,
    session_id: str,
    payload: Mapping[str, Any],
    source_ns: int,
    observed_ns: int,
    instance_id: str = PRODUCER_ID,
) -> dict[str, Any]:
    """Build one ``recovery.verification_completed`` document (§4)."""
    verdict = payload.get("verdict")
    severity = _SEVERITY_BY_VERDICT.get(verdict, "notice")
    document = {
        "schema_version": "1.0",
        "event_id": str(new_event_id()),
        "event_type": "recovery.verification_completed",
        "producer": {
            "producer_id": PRODUCER_ID,
            "producer_version": PRODUCER_VERSION,
            "instance_id": instance_id,
        },
        "scope": {
            "tenant_id": "local",
            "session_id": session_id,
            # §4 attribution: the verdict event belongs to the recovery run.
            "run_id": payload.get("run_id"),
        },
        "time": {
            "source": {
                "value_ns": source_ns,
                "clock_domain": session_clock_domain(session_id),
                "clock_epoch": 0,
            },
            "observed": {
                "value_ns": observed_ns,
                "clock_domain": WALL_CLOCK_DOMAIN,
                "clock_epoch": 0,
            },
        },
        "correlation": None,
        "severity": severity,
        "payload": dict(payload),
        "tags": ["simulation", "recovery"],
    }
    # Construction guarantee: refuse to hand out a non-conforming document.
    envelope = parse_envelope(document)
    envelope.ensure_publishable()
    return envelope.model_dump(mode="json")
