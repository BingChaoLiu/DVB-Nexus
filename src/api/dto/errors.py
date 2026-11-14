"""Error envelope DTOs — the platform-unified error shape (ticket #24).

SPEC-500 §3: "错误信封沿用 SPEC-305 §7 形状,推广为**全平台统一**". The
authoritative shape is SPEC-305 §7:

    {
      "error": {
        "error_code": "OBS_QUERY_RANGE_TOO_LARGE",
        "message": "Requested range exceeds configured maximum",
        "retryable": false,
        "details": {"max_range_ns": 3600000000000}
      },
      "request_id": "req-001"
    }

These Pydantic models are the DTO assembly-point pattern for SPEC-500
(ticket #24): snake_case JSON field names, Pydantic v2 as the JSON
validation authority (SPEC-108 §4 discipline), domain models stay separate.
Route/business DTOs (GeneratorConfig, fault plans, observation queries)
land in sibling modules of ``api.dto`` with M3/M4.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ErrorDetail(BaseModel):
    """The ``error`` object of the unified envelope (SPEC-305 §7)."""

    model_config = ConfigDict(extra="forbid")

    error_code: str
    message: str
    retryable: bool = False
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    """Top level of every error response body (SPEC-305 §7 shape)."""

    model_config = ConfigDict(extra="forbid")

    error: ErrorDetail
    request_id: str
