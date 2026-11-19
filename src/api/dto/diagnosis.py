"""Diagnosis DTOs (SPEC-500 §4.4, ticket #54).

api-owned wire shapes for the two diagnosis endpoints — the §4.4 freeze
(``GET /sessions/{id}/diagnoses`` list + ``POST /sessions/{id}/runs/
{run_id}/diagnose`` idempotent re-evaluation). The mappers accept
duck-typed domain records (attribute access only): the api layer must not
import ``domain`` (import-linter C6), so the application port adapter
hands over objects whose fields carry the SPEC-502 §4 / SPEC-306 §5
names verbatim.

snake_case JSON per the SPEC-500 DTO discipline (Pydantic 权威).
"""

from __future__ import annotations

from typing import Any, Iterable, Sequence

from pydantic import BaseModel, Field


class DiagnosisObservationRefDTO(BaseModel):
    """One evidence hop (SPEC-306 §6 chain: the committed record)."""

    journal_seq: int = Field(ge=1)
    event_type: str


class DiagnosisEvidenceDTO(BaseModel):
    """The artifact anchor — TWO states (SPEC-306 §6 MVP + §Phase2 补丁
    修订, ticket #138): the MVP flat triple ``{artifact_id, pid,
    packet_index}`` (ADR-0007 item 4 shared packet-order frame), or the
    Phase 2 ``{artifact_id, locator}`` — the payload locator fields
    verbatim (never both states; constructed accordingly by the mapper)."""

    artifact_id: str
    pid: int | None = Field(default=None, ge=0, le=8191)
    packet_index: int | None = Field(default=None, ge=0)
    locator: dict[str, Any] | None = None


class DiagnosisDTO(BaseModel):
    """One diagnoses-table row (SPEC-502 §4; state raised/cleared)."""

    diagnosis_id: str
    session_id: str
    run_id: str
    rule_id: str
    rule_version: str
    code: str
    severity: str
    confidence: str
    observation_refs: list[DiagnosisObservationRefDTO]
    affected_node_ids: list[str]
    suggested_actions: list[str]
    state: str
    raised_at: int
    cleared_at: int | None = None


class DiagnosisCandidateDTO(BaseModel):
    """One root-cause candidate (SPEC-306 §5/§7 candidate view)."""

    diagnosis_id: str
    run_id: str
    rule_id: str
    rule_version: str
    code: str
    priority: int
    severity: str
    confidence: str
    title: str
    summary: str
    observation_refs: list[DiagnosisObservationRefDTO]
    affected_node_ids: list[str]
    suggested_actions: list[str]
    evidence: DiagnosisEvidenceDTO


class DiagnosisReportDTO(BaseModel):
    """The batch evaluation answer (SPEC-306 §5 ``DiagnosisReport``)."""

    session_id: str
    run_id: str
    evaluated_at_utc_ms: int
    candidates: list[DiagnosisCandidateDTO]
    warnings: list[str] = Field(default_factory=list)


def _evidence_dto_of(evidence: Any) -> "DiagnosisEvidenceDTO":
    """Map a duck-typed domain ``EvidenceRef`` — TWO states (ticket #138):
    the Phase 2 ``locator`` state and the MVP flat triple state each keep
    their own key set (the MVP wire stays byte-identical; Phase 2 never
    fabricates pid/packet_index)."""
    locator = getattr(evidence, "locator", None)
    if locator is not None:
        return DiagnosisEvidenceDTO(
            artifact_id=evidence.artifact_id, locator=dict(locator)
        )
    return DiagnosisEvidenceDTO(
        artifact_id=evidence.artifact_id,
        pid=evidence.pid,
        packet_index=evidence.packet_index,
    )


def diagnosis_dto_from_record(record: Any) -> DiagnosisDTO:
    """Map a duck-typed ``DiagnosisRecord`` onto the wire DTO."""
    return DiagnosisDTO(
        diagnosis_id=record.diagnosis_id,
        session_id=record.session_id,
        run_id=record.run_id,
        rule_id=record.rule_id,
        rule_version=record.rule_version,
        code=record.code,
        severity=record.severity,
        confidence=record.confidence,
        observation_refs=[
            DiagnosisObservationRefDTO(**ref) for ref in record.observation_refs
        ],
        affected_node_ids=list(record.affected_node_ids),
        suggested_actions=list(record.suggested_actions),
        state=record.state,
        raised_at=record.raised_at,
        cleared_at=record.cleared_at,
    )


def diagnosis_report_dto_from_report(report: Any) -> DiagnosisReportDTO:
    """Map a duck-typed ``DiagnosisReport`` onto the wire DTO."""
    return DiagnosisReportDTO(
        session_id=report.session_id,
        run_id=report.run_id,
        evaluated_at_utc_ms=report.evaluated_at_utc_ms,
        candidates=[
            DiagnosisCandidateDTO(
                diagnosis_id=candidate.diagnosis_id,
                run_id=candidate.run_id,
                rule_id=candidate.rule_id,
                rule_version=candidate.rule_version,
                code=candidate.code,
                priority=candidate.priority,
                severity=str(getattr(candidate.severity, "value", candidate.severity)),
                confidence=str(
                    getattr(candidate.confidence, "value", candidate.confidence)
                ),
                title=candidate.title,
                summary=candidate.summary,
                observation_refs=[
                    DiagnosisObservationRefDTO(
                        journal_seq=ref.journal_seq, event_type=ref.event_type
                    )
                    for ref in candidate.observation_refs
                ],
                affected_node_ids=list(candidate.affected_node_ids),
                suggested_actions=list(candidate.suggested_actions),
                evidence=_evidence_dto_of(candidate.evidence),
            )
            for candidate in report.candidates
        ],
        warnings=list(report.warnings),
    )


__all__ = [
    "DiagnosisCandidateDTO",
    "DiagnosisDTO",
    "DiagnosisEvidenceDTO",
    "DiagnosisObservationRefDTO",
    "DiagnosisReportDTO",
    "diagnosis_dto_from_record",
    "diagnosis_report_dto_from_report",
]
