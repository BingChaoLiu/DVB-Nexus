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

from typing import Any, Optional

from pydantic import Field, model_validator

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
    """The artifact anchor (SPEC-306 §6 chain terminus) — TWO states
    (SPEC-306 §Phase2 补丁修订, ticket #138):

    - MVP: the flat triple ``{artifact_id, pid, packet_index}`` — the
      existing wire, byte-unchanged. ``pid`` is the 13-bit DVB PID space;
      ``packet_index`` follows the ADR-0007 item 4 shared frame (baseline
      and faulted share one packet order, same index = same slot).
    - Phase 2: ``{artifact_id, locator}`` — ``locator`` carries the
      evidence event's payload locator fields verbatim (no fabricated
      pid/packet_index: 无对应定位字段不虚填).

    Exactly one state must hold (validated below); a partial MVP triple
    is refused in both states.
    """

    artifact_id: str = Field(min_length=1)
    pid: Optional[int] = Field(default=None, ge=0, le=8191)
    packet_index: Optional[int] = Field(default=None, ge=0)
    locator: Optional[dict[str, Any]] = None

    @model_validator(mode="after")
    def _two_state(self) -> "EvidenceRef":
        has_pid = self.pid is not None
        has_packet_index = self.packet_index is not None
        if self.locator is not None:
            if has_pid or has_packet_index:
                raise ValueError(
                    "evidence carries either the MVP {pid, packet_index}"
                    " triple or the Phase 2 locator — never both states"
                    " (SPEC-306 §Phase2)"
                )
            if not self.locator:
                raise ValueError("Phase 2 evidence locator must be non-empty")
            return self
        if has_pid != has_packet_index:
            raise ValueError(
                "the MVP anchor triple needs pid and packet_index together"
                " (SPEC-306 §6)"
            )
        if not (has_pid and has_packet_index):
            raise ValueError(
                "evidence needs the MVP triple or a Phase 2 locator"
                " (SPEC-306 §6/§7)"
            )
        return self


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
