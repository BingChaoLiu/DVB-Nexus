"""TSDuck adapter exception hierarchy (SPEC-308 §9).

Each class carries the SPEC-308 §9 error code and its §9-table HTTP mapping
as class data. Rendering HTTP responses is the API layer's job (SPEC-500 §6,
M3 wiring — out of this ticket's scope); the adapter guarantees the code and
the mapped status travel together so the §9 table stays lockable line by line.

The seven §9 rows are the whole mapped family. One extra member outside the
table: :class:`TSDuckNotEnabledError` for the reserved inject/generate
operations (SPEC-308 §4 "预留操作……显式拒绝（防静默半实现）"). The §9 table
has no row for that refusal, so it carries ``http_status=None`` — the API
layer decides its mapping when the endpoints land (M3); no fabricated status.
"""

from __future__ import annotations

from typing import Any


class TSDuckAdapterError(Exception):
    """Base class of every error raised by the TSDuck adapter (SPEC-308 §9).

    Subclasses own exactly one §9-table row via the ``code``/``http_status``
    class attributes.
    """

    code: str
    http_status: int | None


class TSDuckNotFoundError(TSDuckAdapterError):
    """PATH and fallback probing both failed (SPEC-308 §9 row 1).

    Raised by the client before any spawn when the #25 probe (adapters.
    tsduck.version) reports structured unavailability. API mapping: 503
    (service not ready).
    """

    code = "TSDUCK_NOT_FOUND"
    http_status = 503


class TSDuckVersionUnsupportedError(TSDuckAdapterError):
    """Detected version below the MVP minimum baseline 3.40 (SPEC-308 §9 row 2).

    The baseline is the #3-measured version floor (tsduck-env.md §3.3);
    comparison uses parsed ``(major, minor)`` components, never string
    literals of a machine's actual version. API mapping: 503.
    """

    code = "TSDUCK_VERSION_UNSUPPORTED"
    http_status = 503


class TSDuckSpawnFailedError(TSDuckAdapterError):
    """Process start failed (SPEC-308 §9 row 3).

    Strictly the OSError-at-spawn case (executable vanished between probe
    and launch, non-executable file, …). A CLI that started and then exited
    nonzero is NOT this error — ticket #3 makes the JSON content the only
    validity arbiter, so a started-but-failed run falls to the content gate.
    API mapping: 500.
    """

    code = "TSDUCK_SPAWN_FAILED"
    http_status = 500


class TSDuckTimeoutError(TSDuckAdapterError):
    """Operation exceeded its timeout and the process tree was killed
    (SPEC-308 §9 row 4). API mapping: 500.

    ``partial_result`` (set by the process runner) carries the partial
    stdout/stderr captured up to the kill — the partial-log retention the
    §9 row mandates (排查依据).
    """

    code = "TSDUCK_TIMEOUT"
    http_status = 500

    partial_result: Any | None = None


class TSDuckCancelledError(TSDuckAdapterError):
    """User/session-dispose cancellation killed the process tree
    (SPEC-308 §9 row 5). API mapping: 409.

    ``partial_result`` (set by the process runner) carries the partial
    stdout/stderr captured up to the kill.
    """

    code = "TSDUCK_CANCELLED"
    http_status = 409

    partial_result: Any | None = None


class TSDuckJsonGateError(TSDuckAdapterError):
    """JSON content gate failed (SPEC-308 §9 row 6).

    The gate (``ts.bytes > 0 && ts.services.total >= 1``, ticket #3 measured
    discipline) is the adapter's ONLY validity arbiter — exit 0 does not
    prove validity and a nonzero exit does not by itself prove invalidity.
    Every run whose stdout content does not pass the gate lands here,
    including non-JSON stdout and nonzero exits (their exit code and a
    display-only stderr excerpt travel in the message/detail). API
    mapping: 500.

    ``call_record`` (set by the client) carries the nine-field invocation
    record for the failed call — the §7 recording duty holds on failures too.
    """

    code = "TSDUCK_JSON_GATE_FAILED"
    http_status = 500

    call_record: Any | None = None


class TSDuckPluginNotAllowedError(TSDuckAdapterError):
    """argv construction named a plugin outside the MVP whitelist
    (SPEC-308 §5: 用户配置不得直通任意 CLI 插件). API mapping: 422."""

    code = "TSDUCK_PLUGIN_NOT_ALLOWED"
    http_status = 422


class TSDuckNotEnabledError(TSDuckAdapterError):
    """Reserved operation invoked (SPEC-308 §4: inject/generate MVP 预留).

    Explicit refusal, never a silent half-implementation. Outside the §9
    table (see module docstring): ``http_status=None`` defers the mapping
    to the API layer.
    """

    code = "TSDUCK_NOT_ENABLED"
    http_status = None


__all__ = [
    "TSDuckAdapterError",
    "TSDuckCancelledError",
    "TSDuckJsonGateError",
    "TSDuckNotFoundError",
    "TSDuckNotEnabledError",
    "TSDuckPluginNotAllowedError",
    "TSDuckSpawnFailedError",
    "TSDuckTimeoutError",
    "TSDuckVersionUnsupportedError",
]
