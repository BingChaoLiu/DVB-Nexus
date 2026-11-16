"""Scenario-dimension DTOs (SPEC-500 §4.7, ticket #80).

The detail response is the loader's export face verbatim
(``simulation.scenario.schema.export_scenario_document`` — the normalized
wire mapping with ``hidden_reference_solution`` stripped by default,
REQ-SIM-205-003: reveal 政策外不得经任何 API 泄露). Two documented wire
islands inside it, both #45 canonical-example authorities:

- ``initial_topology`` keys are **camelCase** (nodeId / nodeType /
  portId / direction / plane / maxConnections / connectionId / from / to)
  — the scenario document format authority (SPEC-205 §3), unlike the REST
  snake_case around it; the REST face re-serializes the authored mapping
  verbatim rather than translating it (consumers: ticket #67).
- ``required_engine_versions`` / ``hints`` / ``pass_criteria`` /
  ``fault_plan`` islands carry the document's own shapes (ScenarioHint /
  ScenarioCriterion / SPEC-204 FaultDefinition wire).

The list response is the summary projection only — no document payload,
no hidden solution.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "ScenarioDetailDTO",
    "ScenarioSolutionDTO",
    "ScenarioSummaryDTO",
]


class _StrictDTO(BaseModel):
    """snake_case wire contract: extra keys are a schema violation (400)."""

    model_config = ConfigDict(extra="forbid")


class ScenarioSummaryDTO(_StrictDTO):
    """One ``GET /scenarios`` row (the summary projection)."""

    scenario_id: str
    version: str
    title: str
    difficulty: str


class ScenarioDetailDTO(_StrictDTO):
    """``GET /scenarios/{id}`` — the exported document (hidden
    reference solution absent by construction; ``initial_topology`` keeps
    its authored camelCase keys, the #45 canonical-example authority).

    ``content_hash`` (SPEC-408 §6.4, ticket #94) is the loader's pinned
    SHA-256 of the scenario version — the version-pinning identity
    (SPEC-205 §5) read back so verify can cite the true binding instead
    of a declared constant string. Injected by the port from the
    document; the export face itself does not carry it.
    """

    schema_version: str
    scenario_id: str
    version: str
    title: str
    difficulty: str
    required_engine_versions: dict[str, str] = Field(default_factory=dict)
    initial_topology: dict[str, Any]
    simulation_config: dict[str, Any]
    fault_plan: list[dict[str, Any]]
    objectives: list[str]
    hints: list[dict[str, Any]]
    pass_criteria: list[dict[str, Any]]
    content_hash: str


class ScenarioSolutionDTO(_StrictDTO):
    """``GET /scenarios/{id}/solution`` answer (the gated reveal;
    ``hidden_reference_solution`` is null when the scenario declares no
    hidden field — orchestrator OQ-3)."""

    scenario_id: str
    hidden_reference_solution: str | None
