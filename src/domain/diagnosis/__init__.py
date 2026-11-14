"""Diagnosis domain: maps Observations to root-cause candidates and suggestions.

Consumes only ``domain.observation`` (plus static reference data from
``knowledge``); never touches TSDuck processes, never parses raw TS and never
starts processes (ADR-0005 decision 4).

Public API: SPEC-003 section 2.6 diagnosis models. Rule priority, suppression,
correlation and confidence semantics are SPEC-307 scope — models carry data
only.
"""

from domain.diagnosis.model import Diagnosis, DiagnosisConfidence, DiagnosisSeverity

__all__ = ["Diagnosis", "DiagnosisConfidence", "DiagnosisSeverity"]
