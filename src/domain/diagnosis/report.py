"""SPEC-306 evaluation value objects (ticket #54).

``DiagnosisCandidate`` is the engine's root-cause-candidate view: the
existing ``Diagnosis`` (``model.py``, fields frozen) plus the evaluation
surface the engine needs — ``rule_version`` traceability (SPEC-307 §7),
the declarative ``priority`` (SPEC-307 §5 ordering key) and the evidence
anchor (SPEC-306 §6). The SPEC-502 §4/§5 ``diagnoses``-row type is
storage-owned (``DiagnosisRecord`` in ``adapters.storage.repositories``,
same posture as ``ArtifactRow``/``EventRow``) — deliberately NOT here:
a domain import edge from adapters would create indirect
simulation/faults → domain.diagnosis chains and break the frozen
import-linter contracts C7/C8.

Confidence stays the rule's static three-tier declaration — the engine
computes no score (SPEC-003 §2.6, brief §6 axis discipline).
"""

from pydantic import Field

from domain._base import DomainModel
from domain.diagnosis.model import DiagnosisConfidence, DiagnosisSeverity
from domain.observation.ids import Identifier, OpaqueEntityId

__all__ = [
    "DiagnosisCandidate",
    "DiagnosisReport",
    "EvidenceRef",
    "ObservationRef",
    "sort_candidates",
]


class ObservationRef(DomainModel):
    """One evidence hop: the committed journal record a rule matched on."""

    journal_seq: int = Field(ge=1)
    event_type: str = Field(min_length=1)


class EvidenceRef(DomainModel):
    """The artifact anchor (SPEC-306 §6 chain terminus).

    ``pid`` is the 13-bit DVB PID space; ``packet_index`` follows the
    ADR-0007 item 4 shared frame (baseline and faulted share one packet
    order, same index = same slot).
    """

    artifact_id: str = Field(min_length=1)
    pid: int = Field(ge=0, le=8191)
    packet_index: int = Field(ge=0)


class DiagnosisCandidate(DomainModel):
    """One root-cause candidate produced by one rule (SPEC-306 §5/§7)."""

    diagnosis_id: str = Field(min_length=1)
    run_id: OpaqueEntityId
    rule_id: Identifier
    rule_version: str = Field(min_length=1)
    code: str = Field(min_length=1)
    #: SPEC-307 §5 ordering key (smaller first) — orthogonal to severity.
    priority: int
    severity: DiagnosisSeverity
    confidence: DiagnosisConfidence
    title: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    #: Ordered hits (SPEC-306 §6: refs store the per-session journal_seq).
    observation_refs: list[ObservationRef] = Field(min_length=1)
    affected_node_ids: list[str] = Field(default_factory=list)
    suggested_actions: list[str] = Field(default_factory=list)
    evidence: EvidenceRef


class DiagnosisReport(DomainModel):
    """The batch evaluation answer (SPEC-306 §5 ``DiagnosisReport``)."""

    session_id: OpaqueEntityId
    run_id: OpaqueEntityId
    #: Sorted by priority asc → severity desc → code lexicographic.
    candidates: tuple[DiagnosisCandidate, ...] = ()
    #: Rule-isolation / skipped-record warnings (SPEC-306 §8) — warnings
    #: never fail the evaluation, they are reported.
    warnings: tuple[str, ...] = ()
    #: Injected evaluation wall-clock stamp (SPEC-201 injection discipline;
    #: never read from the wall inside the domain).
    evaluated_at_utc_ms: int


_SEVERITY_ORDER_DESC = {
    DiagnosisSeverity.CRITICAL: 0,
    DiagnosisSeverity.ERROR: 1,
    DiagnosisSeverity.WARNING: 2,
    DiagnosisSeverity.INFO: 3,
}


def sort_candidates(
    candidates: list[DiagnosisCandidate],
) -> list[DiagnosisCandidate]:
    """SPEC-307 §5 output ordering (SPEC-306 §5 references it).

    priority ascending → severity descending (critical first) → code
    lexicographic ascending. No priority preemption: every candidate is
    returned, only the order is pinned.
    """
    return sorted(
        candidates,
        key=lambda candidate: (
            candidate.priority,
            _SEVERITY_ORDER_DESC[candidate.severity],
            candidate.code,
        ),
    )
