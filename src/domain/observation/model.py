"""SPEC-003 section 2.4 Observation.

A fact that was measured, parsed, simulated or inferred — never a root cause
in itself (that is ``domain.diagnosis``). Data only: the mixing bans
(``source='tsduck'`` must not be labelled ``measured``, ``SIM_STATE`` output
must not be labelled ``parsed``, hardware must not share a confidence class
with simulated values, SPEC-003 section 2.4 / CONTEXT.md 观测) are producer
disciplines enforced by engines, not model invariants.

Two axes live here and must never be conflated (ticket #13 Q3 cross-cutting
ruling):
- ``ObservationSource`` — who produced the fact (six values since
  SPEC-003 §Phase3, ticket #160: the L0 evaluation product source
  ``state_evaluator`` joins the closed set);
- ``ConfidenceKind`` — how it was produced (four values).
Diagnosis's rule-level ``low/medium/high`` confidence is a DIFFERENT axis
(SPEC-306/307 static declaration), see ``domain.diagnosis``.

Event-transport note (ticket #13 Q3-i): observation-flavoured event payloads
(``ts.*`` family, SPEC-301 section 4) must carry ``source`` and ``confidence``
from these vocabularies; the envelope itself stays untouched (loose envelope,
tight payload, ADR-0006 decision 4). This interface is the logical record; the
event payload is its transport/persistence form.
"""

from enum import Enum
from typing import Any, Optional

from domain._base import DomainModel
from domain.observation.ids import Identifier, OpaqueEntityId


class ObservationSource(str, Enum):
    """Who produced the fact (SPEC-003 section 2.4).

    ``STATE_EVALUATOR`` is the SPEC-003 §Phase3 addition (ticket #160):
    the dedicated source for L0 state-evaluation products, always paired
    with ``ConfidenceKind.SIMULATED`` — ``state_evaluator`` products must
    never be labelled ``parsed``/``measured`` (axis discipline extension).
    """

    GENERATOR = "generator"
    INTERNAL_PARSER = "internal_parser"
    TSDUCK = "tsduck"
    HARDWARE = "hardware"
    RULE_ENGINE = "rule_engine"
    STATE_EVALUATOR = "state_evaluator"


class ConfidenceKind(str, Enum):
    """How the fact was produced (SPEC-003 section 2.4).

    Not the Diagnosis confidence axis: no ``low/medium/high`` here.
    """

    SIMULATED = "simulated"
    PARSED = "parsed"
    MEASURED = "measured"
    INFERRED = "inferred"


class Observation(DomainModel):
    """SPEC-003 section 2.4 ``Observation``."""

    observation_id: Identifier
    run_id: OpaqueEntityId
    source: ObservationSource
    confidence: ConfidenceKind
    type: str
    #: Real-world UTC epoch milliseconds; logging/sorting use only
    #: (SPEC-003 section 4 time model).
    observed_at_utc_ms: int
    #: Simulation virtual time; unit and clock belong to the Simulation Clock
    #: spec — never mixed with wall clock or PCR/PTS (SPEC-003 section 4).
    simulation_time_ticks: Optional[int] = None
    pid: Optional[int] = None
    packet_index: Optional[int] = None
    value: Optional[Any] = None
    unit: Optional[str] = None
    artifact_id: Optional[OpaqueEntityId] = None
    evidence_refs: Optional[list[str]] = None


__all__ = ["ConfidenceKind", "Observation", "ObservationSource"]
