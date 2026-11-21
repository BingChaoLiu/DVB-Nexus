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

Two run forms (ticket #165, ADR-0012 decision 2 — 诚实区分): the submit
request declares ``fidelity`` — ``SIM_TS`` (default, the SPEC-203 TS
generation form; ``config`` required) or ``SIM_STATE`` (the state-domain
L0 evaluation form; **no generator config** — a state run carries no TS
artifact, no packet counts and no ``gen.*`` events, and its status face
carries the L0 evaluation products ``graph_health`` / ``node_health``
instead).  All extensions are additive: existing keys keep their names,
order and types; ``RunAcceptedDTO`` (the 202 body) is untouched.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from api.dto.faults import FaultDefinitionDTO
from api.dto.generator import GeneratorConfigDTO

__all__ = [
    "RunAcceptedDTO",
    "RunArtifactDTO",
    "RunListItemDTO",
    "RunStatusDTO",
    "RunSubmitRequest",
]

#: The run-form discriminator values (ADR-0012 decision 2's two run
#: forms; the state-domain wire value mirrors
#: ``simulation.state.run.STATE_RUN_FIDELITY``).
FIDELITY_VALUES = Literal["SIM_TS", "SIM_STATE"]


class _StrictDTO(BaseModel):
    """snake_case wire contract: extra keys are a schema violation (400)."""

    model_config = ConfigDict(extra="forbid")


class RunSubmitRequest(_StrictDTO):
    """``POST /sessions/{session_id}/runs`` request body (SPEC-500 §4.3).

    ``config`` = the SPEC-108 §4 ``TSGeneratorConfig`` wire shape (SIM_TS
    runs only); ``fault_plan`` = SPEC-204 §3 ``FaultDefinition`` list bound
    at prepare (ADR-0007 item 2). An empty list is a valid plan.

    The fidelity contract (ticket #165): ``SIM_TS`` requires ``config``;
    ``SIM_STATE`` refuses one (a state run has no generator — carrying a
    dummy config would be the dishonest form). The discriminator rides
    the same 202 job face; the plan's layer routing is enforced by the
    per-form prepare gate (``SIM_TS_PLAN_INVALID`` /
    ``SIM_STATE_PLAN_INVALID``).
    """

    config: GeneratorConfigDTO | None = None
    fault_plan: list[FaultDefinitionDTO] = Field(default_factory=list)
    fidelity: FIDELITY_VALUES = "SIM_TS"

    @model_validator(mode="after")
    def _fidelity_config_contract(self) -> "RunSubmitRequest":
        if self.fidelity == "SIM_TS" and self.config is None:
            raise ValueError(
                "fidelity SIM_TS requires the generator config (SPEC-108 "
                "§4 wire shape) — a TS generation run has no configless form"
            )
        if self.fidelity == "SIM_STATE" and self.config is not None:
            raise ValueError(
                "fidelity SIM_STATE refuses a generator config (ADR-0012 "
                "decision 2: a SIM_STATE run evaluates the L0 state domain "
                "— it generates no TS stream, so a TSGeneratorConfig has "
                "nothing to configure)"
            )
        return self


class RunAcceptedDTO(_StrictDTO):
    """The 202 acceptance answer: async job identity + bound fingerprint."""

    run_id: str
    config_hash: str
    status: Literal["running"] = "running"


class RunListItemDTO(_StrictDTO):
    """One ``GET /sessions/{id}/runs`` row (SPEC-408 §6.3, ticket #94).

    The list answers in ``submitted_at`` ASC order (the eight-step
    narrative order), no pagination. ``submitted_at_ms`` and
    ``fault_plan_present`` are recorded by the composition layer at
    submission; ``packet_count`` passes through from the completed result
    face (``None`` while running / on failure — the honest null face).

    Additive (ticket #165): ``fidelity`` declares the run form (``SIM_TS``
    default keeps every pre-#165 row shape); ``graph_health`` carries the
    L0 aggregate for SIM_STATE rows (``None`` for SIM_TS — no L0
    evaluation happens on the TS face).
    """

    run_id: str
    status: Literal["running", "completed", "cancelled", "failed"]
    submitted_at_ms: int
    fault_plan_present: bool
    packet_count: int | None = None
    fidelity: FIDELITY_VALUES = "SIM_TS"
    graph_health: str | None = None


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

    Additive (ticket #165): ``fidelity`` declares the run form; for
    SIM_STATE runs the L0 evaluation products ride ``graph_health`` /
    ``node_health`` (the canvas health-badge data source, ADR-0012
    decision 5), ``artifacts`` stays honestly empty (a state run lands no
    TS artifact) and the count/version faces stay ``None``. SIM_TS runs
    keep the exact pre-#165 body plus the default ``fidelity`` value.
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
    fidelity: FIDELITY_VALUES = "SIM_TS"
    #: The final evaluation's whole-graph aggregate (SIM_STATE only).
    graph_health: str | None = None
    #: The final evaluation's per-node health (SIM_STATE only).
    node_health: dict[str, str] | None = None
