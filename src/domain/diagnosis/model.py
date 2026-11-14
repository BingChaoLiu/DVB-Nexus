"""SPEC-003 section 2.6 Diagnosis.

A root-cause candidate produced by a rule or analysis logic — never a raw fact
(CONTEXT.md 诊断). Data only: rule priority/suppression/correlation semantics
are SPEC-306/307 scope (SPEC-003 section 6).

``confidence`` is the rule's STATIC three-tier declaration (``low/medium/
high``, ticket #13 Q3-ii: the pre-revision continuous number is gone; the rule
definition declares the tier and the engine computes no score). It is a
different axis from the observation ``ConfidenceKind`` four-value provenance
vocabulary — the two must never be conflated.

Note on imports: ``domain.diagnosis`` consumes only ``domain.observation``
(ADR-0005 decision 4); the import-linter contract forbids importing
``domain.topology``, so ``affected_node_ids`` elements are plain strings even
though they carry semantic node slugs (ADR-0006 decision 3) — documented here
rather than type-shared.
"""

from enum import Enum
from typing import Optional

from domain._base import DomainModel
from domain.observation.ids import Identifier, OpaqueEntityId


class DiagnosisSeverity(str, Enum):
    """Severity of the root-cause candidate (SPEC-003 section 2.6)."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class DiagnosisConfidence(str, Enum):
    """Static three-tier rule confidence (SPEC-003 section 2.6, #13 Q3-ii).

    Not a probability and not the observation provenance axis; continuous
    scores and probability calibration are roadmap items. Semantics owner:
    SPEC-307.
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Diagnosis(DomainModel):
    """SPEC-003 section 2.6 ``Diagnosis``."""

    diagnosis_id: Identifier
    run_id: OpaqueEntityId
    rule_id: Identifier
    code: str
    severity: DiagnosisSeverity
    title: str
    summary: str
    confidence: DiagnosisConfidence
    observation_ids: list[Identifier]
    #: Semantic node slugs (ADR-0006 decision 3); plain strings because the
    #: diagnosis package must not import domain.topology (import-linter).
    affected_node_ids: Optional[list[str]] = None
    suggested_actions: Optional[list[str]] = None
    created_at_utc_ms: int


__all__ = ["Diagnosis", "DiagnosisConfidence", "DiagnosisSeverity"]
