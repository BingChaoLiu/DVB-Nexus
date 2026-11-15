"""Run-dimension DTOs: async-job submission (202) and status (SPEC-500
§4.3, ticket #48).

Async-job discipline (REQ-API-500-004): ``POST .../runs`` **never** runs a
generation synchronously — it validates (prepare), schedules, and answers
**202 + run_id** immediately; progress rides ``run_progress`` events
(SPEC-301 §5) over the SPEC-501 transport, not this REST surface. The 202
body also carries the prepare-bound ``config_hash`` fingerprint (ADR-0007
item 2) so the binding is HTTP-observable at acceptance time.

``RunStatusDTO`` mirrors the SPEC-203 §5.2 ``TSRunResult`` field set; while
the job is running the result fields are ``None`` / empty. ``RunContext``
discipline (SPEC-500 §5): ``run_id`` is server-generated; request DTOs carry
no ``journal_seq`` and no ``RunContext`` (ADR-0006 item 2 — producers never
fill it).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from api.dto.faults import FaultDefinitionDTO
from api.dto.generator import GeneratorConfigDTO

__all__ = [
    "RunAcceptedDTO",
    "RunArtifactDTO",
    "RunStatusDTO",
    "RunSubmitRequest",
]


class _StrictDTO(BaseModel):
    """snake_case wire contract: extra keys are a schema violation (400)."""

    model_config = ConfigDict(extra="forbid")


class RunSubmitRequest(_StrictDTO):
    """``POST /sessions/{session_id}/runs`` request body (SPEC-500 §4.3).

    ``config`` = the SPEC-108 §4 ``TSGeneratorConfig`` wire shape;
    ``fault_plan`` = SPEC-204 §3 ``FaultDefinition`` list bound at prepare
    (ADR-0007 item 2). An empty list is a valid plan (no tee legs).
    """

    config: GeneratorConfigDTO
    fault_plan: list[FaultDefinitionDTO] = Field(default_factory=list)


class RunAcceptedDTO(_StrictDTO):
    """The 202 acceptance answer: async job identity + bound fingerprint."""

    run_id: str
    config_hash: str
    status: Literal["running"] = "running"


class RunArtifactDTO(_StrictDTO):
    """One landed artifact reference (SPEC-203 §5.2 ``ArtifactRef``)."""

    artifact_id: str
    kind: Literal["generated_ts", "faulted_ts", "log"]
    sha256: str
    byte_size: int = Field(ge=0)
    packet_count: int | None = None
    partial: bool = False


class RunStatusDTO(_StrictDTO):
    """``GET .../runs/{run_id}`` answer (SPEC-203 §5.2 ``TSRunResult``).

    ``status`` is the async-job state: ``running`` while scheduled; the
    terminal values mirror the SPEC-203 result statuses. Result count
    fields are ``None`` while running.
    """

    run_id: str
    status: Literal["running", "completed", "cancelled", "failed"]
    config_hash: str | None = None
    generator_version: str | None = None
    packet_count: int | None = None
    byte_count: int | None = None
    virtual_duration_ns: int | None = None
    artifacts: list[RunArtifactDTO] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
