"""SPEC-206 recovery verification (ticket #56, SIM-G).

Public face of the verification package:

- :class:`simulation.verification.engine.evaluate` — the pure three-state
  evaluation core (six-kind closed enum, §6 dual semantics, #59
  fault_inactive chain, §8 codes);
- :class:`simulation.verification.service.VerificationService` — the
  journal-backed orchestration (reads, persistence, event emission);
- :mod:`simulation.verification.events` — the authoritative
  ``recovery.verification_completed`` envelope builder.

Import-contract posture (C8): simulation → ts/faults/adapters +
``domain.observation``; nothing from ``domain.diagnosis`` (verdict
evidence references diagnosis-side facts by ID/journal_seq only).
"""

from simulation.verification.engine import (
    REASON_EVIDENCE_MISSING,
    RESULT_FAIL,
    RESULT_NOT_EVALUATED,
    RESULT_PASS,
    VERDICT_FAIL,
    VERDICT_INCONCLUSIVE,
    VERDICT_PASS,
    VERIFICATION_CRITERION_KINDS,
    CriterionResult,
    EvaluationInput,
    FaultEventRecord,
    ObservationRecord,
    VerificationOutcome,
    evaluate,
)
from simulation.verification.events import (
    PRODUCER_ID,
    PRODUCER_VERSION,
    verification_completed_envelope,
)
from simulation.verification.service import (
    JournalReader,
    VerificationResult,
    VerificationService,
    VerifierPublisher,
)

__all__ = [
    "PRODUCER_ID",
    "PRODUCER_VERSION",
    "REASON_EVIDENCE_MISSING",
    "RESULT_FAIL",
    "RESULT_NOT_EVALUATED",
    "RESULT_PASS",
    "JournalReader",
    "CriterionResult",
    "EvaluationInput",
    "FaultEventRecord",
    "ObservationRecord",
    "VERDICT_FAIL",
    "VERDICT_INCONCLUSIVE",
    "VERDICT_PASS",
    "VERIFICATION_CRITERION_KINDS",
    "VerificationOutcome",
    "VerificationResult",
    "VerificationService",
    "VerifierPublisher",
    "evaluate",
    "verification_completed_envelope",
]
