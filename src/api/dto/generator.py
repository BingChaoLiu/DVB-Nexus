"""SPEC-108 §4 JSON↔DTO mapping — the Pydantic DTO authority for the TS
generator configuration (SPEC-500 §2.1/§5, ticket #48).

Field-by-field authority is the SPEC-108 §4 mapping table: JSON field
names are snake_case and mirror the frozen ``ts.generator.config`` dataclass
shapes exactly; ``bytes`` fields (``program.program_descriptors``) are hex
encoded (SPEC-500 §5 DTO discipline). Enum strings are identical to the
domain vocabulary (``profile``, ``pcr_insertion_policy``, ``payload_profile``).

Validation posture (SPEC-108 §5): the DTO layer validates *structure*
(types, required fields, JSON shape). Semantic generation-config validation
(rate fit, deadline window, PID ranges) stays with the SPEC-108 public
validator inside the simulation backend — a structurally valid DTO that
fails the §5 validator surfaces as a 422 ``SIM_TS_CONFIG_INVALID`` (SPEC-500
§6), never as a 400. The DTO therefore stays permissive and does not
duplicate semantic rules.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "ElementaryStreamDTO",
    "GeneratorConfigDTO",
    "ProgramDTO",
]


class _StrictDTO(BaseModel):
    """snake_case wire contract: extra keys are a schema violation (400)."""

    model_config = ConfigDict(extra="forbid")


class ElementaryStreamDTO(_StrictDTO):
    """SPEC-108 §4 ``ElementaryStreamConfig`` (exact field set)."""

    pid: int = Field(ge=0)
    stream_type: int = Field(ge=0)
    stream_id: int = Field(ge=0)
    bitrate_bps: int = Field(gt=0)
    payload_profile: str = "synthetic_test_data"
    payload_seed_offset: int = 0


class ProgramDTO(_StrictDTO):
    """SPEC-108 §4 ``ProgramConfig`` (exact field set).

    ``program_descriptors`` arrives hex encoded (SPEC-500 §5: bytes → hex);
    the empty string is the default (no descriptors).
    """

    transport_stream_id: int = Field(ge=0)
    program_number: int = Field(ge=1)
    pmt_pid: int = Field(ge=0)
    pcr_pid: int = Field(ge=0)
    version_number: int = Field(ge=0)
    streams: list[ElementaryStreamDTO]
    program_descriptors: str = ""


class GeneratorConfigDTO(_StrictDTO):
    """SPEC-108 §4 ``GeneratorConfig`` (exact field set, wire shape).

    Defaults are the ruling-#72 out-of-phase periods — identical to the
    domain dataclass defaults so the JSON default and the code default can
    never drift.
    """

    schema_version: int = Field(ge=1)
    profile: str = "analysis_only"
    deterministic: bool = True
    seed: int = Field(ge=0)
    initial_media_clock_27mhz: int = Field(ge=0)
    target_bitrate_bps: int = Field(gt=0)
    output_packet_count: int = Field(gt=0)
    program: ProgramDTO
    pat_period_ms: int = Field(default=101, gt=0)
    pmt_period_ms: int = Field(default=103, gt=0)
    pcr_interval_ms: int = Field(default=40, gt=0)
    pcr_insertion_policy: str = "payload_packet_first"
