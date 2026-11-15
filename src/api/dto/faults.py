"""SPEC-204 §3 fault-plan request DTOs (SPEC-500 §4.3, ticket #48).

ADR-0007 item 2 (prepare binding): the fault plan rides **in the run
request body** and is validated at run-submission time by the prepare stage
(AC-204-01) — the chatgpt §9 ``POST /sessions/{id}/faults`` runtime-injection
shape is deprecated and has no route. The DTO mirrors the SPEC-204 §3
``FaultDefinition``/``FaultActivation`` shapes (field sets identical to the
``simulation.fault_plan`` seam classes).

DTO posture: structural shape only. Semantic validation (fault_type
registry, parameter schemas v1, activation/parameter consistency,
expected_observations obligation) belongs to the prepare stage and surfaces
as 422 ``SIM_TS_PLAN_INVALID`` with the per-element detail list (SPEC-500
§4.3/§6) — the DTO must not duplicate the §6 v1 schemas.

``fault_id`` is optional: uuid4-opaque identity, not semantics (ADR-0006
item 3) — absent ids are server-generated at the composition boundary and
never enter the prepare fingerprint (SPEC-203 §5.1).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "FaultActivationDTO",
    "FaultDefinitionDTO",
]


class _StrictDTO(BaseModel):
    """snake_case wire contract: extra keys are a schema violation (400)."""

    model_config = ConfigDict(extra="forbid")


class FaultActivationDTO(_StrictDTO):
    """SPEC-204 §3 ``FaultActivation`` (MVP: packet_index + session_start).

    ADR-0007 item 3 narrows activation to ``packet_index`` (shared packet
    frame) and ``session_start`` (whole run); virtual-time and manual
    triggers are deferred and rejected at prepare.
    """

    kind: Literal["packet_index", "session_start"] = "session_start"
    packet_index: int | None = Field(default=None, ge=0)


class FaultDefinitionDTO(_StrictDTO):
    """SPEC-204 §3 ``FaultDefinition`` (wire shape, plan element)."""

    fault_id: str | None = None
    fault_type: str
    target_id: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    activation: FaultActivationDTO = Field(default_factory=FaultActivationDTO)
    expected_observations: list[str] = Field(default_factory=list)
