"""TSDuck call-record DTO (SPEC-500 §4.8, ticket #80 / REQ-API-500-008).

The nine SPEC-308 §7 fields + the optional ``run_id`` association, in
snake_case. Field-value discipline mirrors the adapter's
``TSDuckCallRecord`` no-fabrication rule verbatim: failure-path fields
carry explicit ``null`` — never fabricated values. ``stderr_text`` is the
display-only decode (GBK rendered verbatim, UTF-8 errors="replace") —
consumers render it as-is and never parse it (SPEC-308 §7; ticket #66).

Timestamps are epoch-ms INTEGER (R8 house convention) — the adapter's
epoch-second ``started_at``/``finished_at`` floats convert at the store's
write seam (the mapper below handles the converter). Exit 0 ≠ valid
content (the SPEC-308 §9 JSON gate) — ``exit_code`` carries no validity
claim.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["TSDuckCallDTO"]


class _StrictDTO(BaseModel):
    """snake_case wire contract: extra keys are a schema violation (400)."""

    model_config = ConfigDict(extra="forbid")


class TSDuckCallDTO(_StrictDTO):
    """One TSDuck invocation record (SPEC-308 §7, SPEC-001 §7)."""

    version: Optional[str] = None
    executable_path: Optional[str] = None
    argv: list[str] = Field(default_factory=list)
    started_at_utc_ms: int
    finished_at_utc_ms: int
    exit_code: Optional[int] = None
    stdout_text: Optional[str] = None
    stderr_text: Optional[str] = None
    input_artifact_sha256: Optional[str] = None
    run_id: Optional[str] = None


def tsduck_call_dto(record: object) -> TSDuckCallDTO:
    """Storage row → wire DTO (duck-typed; the api layer never imports
    ``adapters`` — import-linter C6). Accepts the epoch-second
    ``started_at``/``finished_at`` floats of the adapter dataclass shape
    OR epoch-ms integers (the storage row shape) — whichever the caller
    carries; the wire contract is epoch-ms either way."""
    def _to_ms(value: object) -> int:
        # Adapter records use epoch seconds (floats); storage rows use
        # epoch-ms integers. Integers pass through, seconds scale ×1000.
        if isinstance(value, int):
            return value
        return int(round(float(value) * 1000))

    return TSDuckCallDTO(
        version=getattr(record, "version", None),
        executable_path=getattr(record, "executable_path", None),
        argv=list(getattr(record, "argv", ()) or ()),
        started_at_utc_ms=_to_ms(getattr(record, "started_at_utc_ms", getattr(record, "started_at", 0.0))),
        finished_at_utc_ms=_to_ms(getattr(record, "finished_at_utc_ms", getattr(record, "finished_at", 0.0))),
        exit_code=getattr(record, "exit_code", None),
        stdout_text=getattr(record, "stdout_text", None),
        stderr_text=getattr(record, "stderr_text", None),
        input_artifact_sha256=getattr(record, "input_artifact_sha256", None),
        run_id=getattr(record, "run_id", None),
    )
