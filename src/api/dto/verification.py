"""Verification DTOs (SPEC-500 §4.4 verify endpoint, ticket #56).

api-owned wire shapes for ``POST /sessions/{id}/runs/{run_id}/verify``
(SPEC-206 three-state PASS/FAIL/INCONCLUSIVE). The mappers accept
duck-typed objects (attribute access only): the api layer must not import
``simulation`` (import-linter C6), so the application-facing port adapter
hands over objects whose fields carry the SPEC-206 §4 names verbatim
(the ``VerificationResult`` / ``CriterionResult`` projections).

Wire discipline (SPEC-205 §3 pass-criteria declarations ride the request
body — the scenario registry (§4.7) is a separate freeze): ``pass_criteria``
entries carry criterion_id / kind / mandatory / fault_id. ``ui_state`` is
accepted for the REQ-SIM-206-001 AC posture (the engine provably ignores
it) and is never persisted.

snake_case JSON per the SPEC-500 DTO discipline (Pydantic 权威).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ScenarioIdentityDTO(BaseModel):
    """The SPEC-205 §5 version-pinning identity (加载即钉扎)."""

    scenario_id: str
    version: str
    content_hash: str


class PassCriterionDTO(BaseModel):
    """One pass-criterion declaration (SPEC-205 §3; SPEC-206 consumes)."""

    criterion_id: str
    kind: str
    mandatory: bool = True
    fault_id: str | None = None


class VerifyRunRequest(BaseModel):
    """The verify request body (SPEC-500 §4.4; ticket #56 declaration)."""

    baseline_run_id: str
    scenario: ScenarioIdentityDTO
    pass_criteria: list[PassCriterionDTO] = Field(min_length=1)
    # Accepted and NEVER consulted: UI state is not evidence (AC-206-01).
    ui_state: dict[str, Any] | None = None


class CriterionResultDTO(BaseModel):
    """One per-criterion result (SPEC-206 §4: PASS/FAIL/NOT_EVALUATED)."""

    criterion_id: str
    kind: str
    mandatory: bool
    result: str
    reason_code: str | None = None
    reason: str | None = None


class VerificationResultDTO(BaseModel):
    """The three-state verdict answer (SPEC-206 §4 result structure)."""

    session_id: str
    recovery_run_id: str
    baseline_run_id: str
    scenario: ScenarioIdentityDTO
    verdict: str
    criteria: list[CriterionResultDTO]
    evidence_refs: list[dict[str, Any]] = Field(default_factory=list)
    summary: str
    verified_at_utc_ms: int


def verification_result_dto_from_result(result: Any) -> VerificationResultDTO:
    """Map a duck-typed ``VerificationResult`` onto the wire DTO."""
    return VerificationResultDTO(
        session_id=result.session_id,
        recovery_run_id=result.recovery_run_id,
        baseline_run_id=result.baseline_run_id,
        scenario=ScenarioIdentityDTO(
            scenario_id=result.scenario_id,
            version=result.scenario_version,
            content_hash=result.scenario_content_hash,
        ),
        verdict=result.verdict,
        criteria=[
            CriterionResultDTO(
                criterion_id=entry.criterion_id,
                kind=entry.kind,
                mandatory=entry.mandatory,
                result=entry.result,
                reason_code=entry.reason_code,
                reason=entry.reason,
            )
            for entry in result.criteria
        ],
        evidence_refs=[dict(ref) for ref in result.evidence_refs],
        summary=result.summary,
        verified_at_utc_ms=result.verified_at_utc_ms,
    )


__all__ = [
    "CriterionResultDTO",
    "PassCriterionDTO",
    "ScenarioIdentityDTO",
    "VerifyRunRequest",
    "VerificationResultDTO",
    "verification_result_dto_from_result",
]
