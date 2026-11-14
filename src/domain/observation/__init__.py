"""Observation domain: the unified event exchange interface.

Facts, metrics and evidence models plus the event publishing contract
(SPEC-001 section 4). Producers must declare source and confidence; observed
facts are never mixed with structured evidence.

Also hosts the run-scoped shared vocabulary every consumer may import
(ADR-0005 decision 4 hub): RunContext, the ID strategy types (ADR-0006
decision 3) and the SPEC-003 section 3 status vocabulary.
"""

from domain.observation.ids import Identifier, OpaqueEntityId
from domain.observation.model import ConfidenceKind, Observation, ObservationSource
from domain.observation.run_context import Fidelity, RunContext, RunMode

__all__ = [
    "ConfidenceKind",
    "Fidelity",
    "Identifier",
    "Observation",
    "ObservationSource",
    "OpaqueEntityId",
    "RunContext",
    "RunMode",
]
