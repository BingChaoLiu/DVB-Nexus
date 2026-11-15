"""Diagnosis orchestration package (ticket #54, SPEC-306).

The application half of the SPEC-306 §5 ``DiagnosisEngine`` face: journal
reading, lifecycle commit (``diagnoses`` table upsert + ``diagnosis.*``
publication through the SPEC-300 §12 producer face) and the run-end
trigger binding (§4). The evaluation core itself is the pure
``domain.diagnosis`` evaluator — this package never re-implements rule
semantics (SPEC-307 territory).
"""

from application.diagnosis.service import (
    JournalReader,
    TERMINAL_RUN_EVENT_TYPES,
    DiagnosisService,
    bind_run_completion_trigger,
)

__all__ = [
    "TERMINAL_RUN_EVENT_TYPES",
    "DiagnosisService",
    "JournalReader",
    "bind_run_completion_trigger",
]
