"""Artifact-dimension DTOs (SPEC-500 §4.6, ticket #48).

``ArtifactMetaDTO`` mirrors the SPEC-502 §5 ``ArtifactRow`` (the #42 index
half) — the metadata authority for the REST surface. Path discipline
(SPEC-003 §2.7 / SPEC-503 §6): ``relative_path`` is forwarded **verbatim**
and is layout-relative only; the API never produces or accepts absolute
paths, and no store-internal root leaks into any field.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["ArtifactMetaDTO"]


class ArtifactMetaDTO(BaseModel):
    """``GET /artifacts/{artifact_id}`` metadata (SPEC-003 §2.7)."""

    model_config = ConfigDict(extra="forbid")

    artifact_id: str
    run_id: str
    session_id: str
    kind: str
    relative_path: str
    byte_size: int = Field(ge=0)
    sha256: str
    packet_size: int | None = None
    packet_count: int | None = None
    generator_version: str | None = None
    config_hash: str | None = None
    fault_profile_ids: list[str] = Field(default_factory=list)
    created_at_utc_ms: int = Field(ge=0)
