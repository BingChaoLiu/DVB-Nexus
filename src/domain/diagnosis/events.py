"""``diagnosis.raised/updated/cleared`` envelope construction (ticket #54).

SPEC-306 §7 pins the shared payload shape; SPEC-306 §5 pins ``scope.run_id``
attribution. This module is the single construction point for diagnosis
events — every envelope passes :func:`parse_envelope` before it is returned,
so a non-conforming document can never leave the module (the same
construction-guarantee discipline the #41 emitter uses).

Producer identity: ``diagnosis-engine`` (report-recorded recommendation,
ticket #54). ``journal_seq`` is NEVER filled here — the journal stamps it
at durable append (ADR-0006 decision 2).

Clocks: ``source`` is the session's virtual domain (``sim:<session_id>``,
values injected by the caller — the domain never reads a wall clock);
``observed`` is the wall:utc injection point (application orchestration
passes its injected wall source).
"""

from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence

from domain.diagnosis.model import DiagnosisSeverity
from domain.diagnosis.report import DiagnosisCandidate, ObservationRef
from domain.observation.envelope import parse_envelope, new_event_id

__all__ = [
    "PRODUCER_ID",
    "PRODUCER_VERSION",
    "WALL_CLOCK_DOMAIN",
    "cleared_envelope",
    "session_clock_domain",
    "updated_envelope",
    "raised_envelope",
]

#: Producer identity (reported in ticket #54; SPEC-300 §12 duty).
PRODUCER_ID = "diagnosis-engine"

#: Bumped with the diagnosis package's spec baseline (SPEC-306 0.5.0).
PRODUCER_VERSION = "0.5.0"

#: Ingestion observation domain (SPEC-300 §6 vocabulary).
WALL_CLOCK_DOMAIN = "wall:utc"

_SESSION_CLOCK_PREFIX = "sim:"

#: DiagnosisSeverity values are a subset of the envelope Severity family
#: (info/warning/error/critical) — identity mapping, no translation.
_SEVERITY_TO_ENVELOPE = {member.value: member.value for member in DiagnosisSeverity}

_CORRELATION_KEYS = (
    "trace_id",
    "span_id",
    "parent_event_id",
    "fault_id",
    "node_id",
    "port_id",
    "service_id",
    "pid",
)


def session_clock_domain(session_id: str) -> str:
    """The session-scoped virtual clock domain name (SPEC-300 §6)."""
    return f"{_SESSION_CLOCK_PREFIX}{session_id}"


def raised_envelope(
    candidate: DiagnosisCandidate,
    *,
    session_id: str,
    observation_refs: Optional[Sequence[ObservationRef]] = None,
    source_ns: int,
    observed_ns: int,
    instance_id: str = "diagnosis-engine",
) -> Mapping[str, Any]:
    """``diagnosis.raised``: a new root-cause candidate (SPEC-306 §7)."""
    refs = list(observation_refs) if observation_refs is not None else list(
        candidate.observation_refs
    )
    return _diagnosis_envelope(
        "diagnosis.raised",
        candidate=candidate,
        session_id=session_id,
        refs=refs,
        source_ns=source_ns,
        observed_ns=observed_ns,
        instance_id=instance_id,
    )


def updated_envelope(
    candidate: DiagnosisCandidate,
    *,
    session_id: str,
    observation_refs: Optional[Sequence[ObservationRef]] = None,
    source_ns: int,
    observed_ns: int,
    instance_id: str = "diagnosis-engine",
) -> Mapping[str, Any]:
    """``diagnosis.updated``: same ``diagnosis_id``, evidence accumulates."""
    refs = list(observation_refs) if observation_refs is not None else list(
        candidate.observation_refs
    )
    return _diagnosis_envelope(
        "diagnosis.updated",
        candidate=candidate,
        session_id=session_id,
        refs=refs,
        source_ns=source_ns,
        observed_ns=observed_ns,
        instance_id=instance_id,
    )


def cleared_envelope(
    *,
    diagnosis_id: str,
    rule_id: str,
    session_id: str,
    run_id: str,
    reason: str,
    source_ns: int,
    observed_ns: int,
    instance_id: str = "diagnosis-engine",
) -> Mapping[str, Any]:
    """``diagnosis.cleared``: symptom gone — payload needs only
    ``diagnosis_id`` + ``rule_id`` + the clear reason (SPEC-306 §7)."""
    document = {
        "schema_version": "1.0",
        "event_id": new_event_id(),
        "event_type": "diagnosis.cleared",
        "producer": {
            "producer_id": PRODUCER_ID,
            "producer_version": PRODUCER_VERSION,
            "instance_id": instance_id,
        },
        "scope": {
            "tenant_id": "local",
            "session_id": session_id,
            "run_id": run_id,
        },
        "time": _time_block(session_id, source_ns, observed_ns),
        "correlation": None,
        "severity": "info",
        "payload": {
            "diagnosis_id": diagnosis_id,
            "rule_id": rule_id,
            "reason": reason,
        },
        "tags": ["diagnosis"],
    }
    return parse_envelope(document).model_dump(mode="json")


# --- internals ----------------------------------------------------------------


def _diagnosis_envelope(
    event_type: str,
    *,
    candidate: DiagnosisCandidate,
    session_id: str,
    refs: list[ObservationRef],
    source_ns: int,
    observed_ns: int,
    instance_id: str,
) -> Mapping[str, Any]:
    payload = {
        "diagnosis_id": candidate.diagnosis_id,
        "rule_id": candidate.rule_id,
        "rule_version": candidate.rule_version,
        "code": candidate.code,
        "severity": candidate.severity.value,
        "confidence": candidate.confidence.value,
        "title": candidate.title,
        "summary": candidate.summary,
        "observation_refs": [
            {"journal_seq": ref.journal_seq, "event_type": ref.event_type}
            for ref in refs
        ],
        "affected_node_ids": list(candidate.affected_node_ids),
        "suggested_actions": list(candidate.suggested_actions),
        "evidence": {
            "artifact_id": candidate.evidence.artifact_id,
            "pid": candidate.evidence.pid,
            "packet_index": candidate.evidence.packet_index,
        },
    }
    correlation = {key: None for key in _CORRELATION_KEYS}
    correlation["pid"] = candidate.evidence.pid
    if candidate.affected_node_ids:
        correlation["node_id"] = candidate.affected_node_ids[0]
    document = {
        "schema_version": "1.0",
        "event_id": new_event_id(),
        "event_type": event_type,
        "producer": {
            "producer_id": PRODUCER_ID,
            "producer_version": PRODUCER_VERSION,
            "instance_id": instance_id,
        },
        "scope": {
            "tenant_id": "local",
            "session_id": session_id,
            "run_id": candidate.run_id,
        },
        "time": _time_block(session_id, source_ns, observed_ns),
        "correlation": correlation,
        "severity": _SEVERITY_TO_ENVELOPE[candidate.severity.value],
        "payload": payload,
        "tags": ["diagnosis"],
    }
    # Construction guarantee: refuse to hand out a non-conforming document.
    return parse_envelope(document).model_dump(mode="json")


def _time_block(session_id: str, source_ns: int, observed_ns: int) -> dict:
    return {
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
    }
