"""SPEC-204 §4/§6/§11 — the MVP fault-type registry and schema validation.

One registry entry per MVP fault type (§6, ADR-0007 item 5 — single
attributable symptom each), carrying:

- the versioned parameter schema (``PARAMETERS_SCHEMA_VERSION = 1``);
- the transform builder used by the semantic stream filter
  (:mod:`faults.filters.semantic`, lazily imported to keep this module
  free of the packet model).

:func:`validate_fault_definition` is the pure validation half of prepare
(SPEC-204 §11): it returns the per-fault error detail list, each detail
prefixed with its §11 diagnostic code.  The simulation prepare stage
(``simulation.fault_plan.validate_fault_plan``) raises those details inside
``SIM_TS_PLAN_INVALID`` before any session mutation (AC-204-01) — the
``faults`` package never imports ``simulation`` (import contract).

Schema evolution follows SPEC-301 §8 compatibility rules: adding an
optional parameter = minor; removing/renaming/re-semanting = major.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from faults.definition import FaultActivation, FaultDefinition
from faults.targets import FaultTarget, parse_target_id

if TYPE_CHECKING:  # pragma: no cover — typing only
    from faults.filters.base import FaultTransform

__all__ = [
    "FAULT_TYPE_CC_DISCONTINUITY",
    "FAULT_TYPE_PAT_MISSING",
    "FAULT_TYPE_PMT_INVALID_CRC",
    "FAULT_TYPE_PMT_PID_MISMATCH",
    "MVP_FAULT_TYPES",
    "PARAMETERS_SCHEMA_VERSION",
    "transform_builder_for",
    "validate_fault_definition",
]

FAULT_TYPE_PAT_MISSING = "PAT_MISSING"
FAULT_TYPE_PMT_INVALID_CRC = "PMT_INVALID_CRC"
FAULT_TYPE_CC_DISCONTINUITY = "CC_DISCONTINUITY"
FAULT_TYPE_PMT_PID_MISMATCH = "PMT_PID_MISMATCH"

#: The four MVP fault types (SPEC-204 §6; ADR-0007 item 5).
MVP_FAULT_TYPES: frozenset[str] = frozenset(
    {
        FAULT_TYPE_PAT_MISSING,
        FAULT_TYPE_PMT_INVALID_CRC,
        FAULT_TYPE_CC_DISCONTINUITY,
        FAULT_TYPE_PMT_PID_MISMATCH,
    }
)

#: Versioned parameter schema generation (SPEC-204 §4).
PARAMETERS_SCHEMA_VERSION = 1

# --- SPEC-204 §11 diagnostic codes ----------------------------------------------

SIM_FAULT_UNKNOWN_TYPE = "SIM_FAULT_UNKNOWN_TYPE"
SIM_FAULT_PARAM_INVALID = "SIM_FAULT_PARAM_INVALID"
SIM_FAULT_EXPECTED_OBS_MISSING = "SIM_FAULT_EXPECTED_OBS_MISSING"
SIM_FAULT_TARGET_INVALID = "SIM_FAULT_TARGET_INVALID"
SIM_FAULT_ACTIVATION_OUT_OF_RANGE = "SIM_FAULT_ACTIVATION_OUT_OF_RANGE"

#: CC_DISCONTINUITY relative-offset bounds (§6.3): delta ∈ 1..15, non-zero.
_CC_DELTA_MIN = 1
_CC_DELTA_MAX = 15

#: PMT_PID_MISMATCH wrong-PID bounds (§6.4): 13-bit, non-reserved, non-null
#: (the 0x0000..0x001F PSI range and null PID 0x1FFF are excluded —
#: SPEC-103 §8.6 project-reserved range, mirroring the #43 seam rules).
_WRONG_PID_MIN = 0x0020
_WRONG_PID_MAX = 0x1FFE

_ACTIVATION_KINDS = ("packet_index", "session_start")


def _detail(code: str, message: str) -> str:
    return f"{code}: {message}"


def _fault_label(fault: FaultDefinition) -> str:
    return f"fault {fault.fault_id!r}"


# --- activation (SPEC-204 §3) ---------------------------------------------------


def _validate_activation(
    fault: FaultDefinition, *, expected_packet_count: int | None
) -> list[str]:
    activation: FaultActivation = fault.activation
    label = _fault_label(fault)
    if activation.kind not in _ACTIVATION_KINDS:
        return [
            _detail(
                SIM_FAULT_PARAM_INVALID,
                f"{label}: activation kind {activation.kind!r} is outside the "
                f"MVP set {set(_ACTIVATION_KINDS)} (ADR-0007 item 3)",
            )
        ]
    if activation.kind == "session_start":
        if activation.packet_index is not None:
            return [
                _detail(
                    SIM_FAULT_PARAM_INVALID,
                    f"{label}: activation kind 'session_start' must not "
                    "carry a packet_index",
                )
            ]
        return []
    index = activation.packet_index
    if not isinstance(index, int) or isinstance(index, bool):
        return [
            _detail(
                SIM_FAULT_PARAM_INVALID,
                f"{label}: activation kind 'packet_index' requires an int "
                "packet_index (shared frame, 0-based)",
            )
        ]
    if index < 0:
        return [
            _detail(
                SIM_FAULT_PARAM_INVALID,
                f"{label}: packet_index {index} is negative (0-based "
                "shared frame)",
            )
        ]
    if expected_packet_count is not None and index >= expected_packet_count:
        return [
            _detail(
                SIM_FAULT_ACTIVATION_OUT_OF_RANGE,
                f"{label}: packet_index {index} is beyond the prepared "
                f"packet frame (0..{expected_packet_count - 1})",
            )
        ]
    return []


# --- versioned parameter schemas (SPEC-204 §4/§6) --------------------------------

#: v1 schema table: allowed keys and required keys per fault type.
_SCHEMAS: dict[str, dict[str, set[str]]] = {
    FAULT_TYPE_PAT_MISSING: {"allowed": set(), "required": set()},
    FAULT_TYPE_PMT_INVALID_CRC: {
        "allowed": {"mode", "corruption"},
        "required": set(),
    },
    FAULT_TYPE_CC_DISCONTINUITY: {"allowed": {"delta"}, "required": {"delta"}},
    FAULT_TYPE_PMT_PID_MISMATCH: {
        "allowed": {"wrong_pmt_pid"},
        "required": {"wrong_pmt_pid"},
    },
}


def _validate_parameters(
    fault: FaultDefinition, *, actual_pmt_pid: int | None
) -> list[str]:
    parameters = dict(fault.parameters)
    fault_type = fault.fault_type
    label = _fault_label(fault)
    details: list[str] = []

    def reject(message: str) -> None:
        details.append(_detail(SIM_FAULT_PARAM_INVALID, f"{label}: {message}"))

    schema = _SCHEMAS.get(fault_type)
    if schema is None:
        # Unknown type: the caller already recorded SIM_FAULT_UNKNOWN_TYPE.
        return []

    unknown = sorted(set(parameters) - schema["allowed"])
    if unknown:
        reject(
            f"unknown parameter key(s) {unknown} for {fault_type} schema v1 "
            "(SPEC-204 §4: unknown keys are rejected, never ignored)"
        )
    missing = sorted(schema["required"] - set(parameters))
    if missing:
        reject(
            f"missing required parameter key(s) {missing} for {fault_type} "
            "schema v1"
        )
        return details

    if fault_type == FAULT_TYPE_PMT_INVALID_CRC:
        mode = parameters.get("mode", "persistent")
        if mode not in ("once", "persistent"):
            reject(
                f"PMT_INVALID_CRC mode {mode!r} is not one of "
                "'once' | 'persistent' (default persistent, SPEC-204 §6.2)"
            )
        corruption = parameters.get("corruption", "invert")
        if corruption not in ("invert", "zero"):
            reject(
                f"PMT_INVALID_CRC corruption {corruption!r} is not one of "
                "'invert' | 'zero' (default invert, SPEC-204 §6.2)"
            )
    elif fault_type == FAULT_TYPE_CC_DISCONTINUITY:
        delta = parameters["delta"]
        if not isinstance(delta, int) or isinstance(delta, bool):
            reject("CC_DISCONTINUITY delta must be an int (SPEC-204 §6.3)")
        elif not _CC_DELTA_MIN <= delta <= _CC_DELTA_MAX or delta == 0:
            reject(
                f"CC_DISCONTINUITY delta {delta} outside the non-zero "
                f"{_CC_DELTA_MIN}..{_CC_DELTA_MAX} range (SPEC-204 §6.3 "
                "relative-offset semantics)"
            )
    elif fault_type == FAULT_TYPE_PMT_PID_MISMATCH:
        wrong_pid = parameters["wrong_pmt_pid"]
        if not isinstance(wrong_pid, int) or isinstance(wrong_pid, bool):
            reject(
                "PMT_PID_MISMATCH wrong_pmt_pid must be an int "
                "(SPEC-204 §6.4)"
            )
        elif not _WRONG_PID_MIN <= wrong_pid <= _WRONG_PID_MAX:
            reject(
                f"wrong_pmt_pid {wrong_pid:#06x} is outside the 13-bit "
                f"non-reserved, non-null range ({_WRONG_PID_MIN:#06x}.."
                f"{_WRONG_PID_MAX:#06x}; the 0x0000..0x001F PSI range and "
                "the null PID are project-reserved, SPEC-204 §6.4 / "
                "SPEC-103 §8.6)"
            )
        elif actual_pmt_pid is not None and wrong_pid == actual_pmt_pid:
            reject(
                f"wrong_pmt_pid {wrong_pid:#06x} equals the program's "
                f"actual pmt_pid ({actual_pmt_pid:#06x}) — the mismatch "
                "would be a no-op (SPEC-204 §6.4)"
            )
    return details


# --- the registry validator (SPEC-204 §11 prepare half) ---------------------------


def validate_fault_definition(
    fault: FaultDefinition,
    *,
    actual_pmt_pid: int | None = None,
    expected_packet_count: int | None = None,
) -> tuple[str, ...]:
    """Validate one canonical fault definition; return §11 detail strings.

    Each detail is ``"<SIM_FAULT_*_CODE>: <message>"``.  Empty tuple =
    valid.  Pure: no exceptions, no I/O, no wall clock.
    """
    label = _fault_label(fault)
    details: list[str] = []

    if fault.fault_type not in MVP_FAULT_TYPES:
        details.append(
            _detail(
                SIM_FAULT_UNKNOWN_TYPE,
                f"{label}: fault_type {fault.fault_type!r} is not in the "
                f"MVP registry {sorted(MVP_FAULT_TYPES)} (SPEC-204 §6)",
            )
        )

    target: FaultTarget | None
    try:
        target = parse_target_id(fault.target_id)
    except ValueError as error:
        target = None
        details.append(
            _detail(SIM_FAULT_TARGET_INVALID, f"{label}: {error}")
        )
    else:
        if target.pid is None:
            details.append(
                _detail(
                    SIM_FAULT_TARGET_INVALID,
                    f"{label}: the four MVP fault types are stream-level "
                    f"faults — target {fault.target_id!r} must be the "
                    "'{node_id}:pid:0x{hex}' form (node_id + pid, ADR-0006 "
                    "item 3)",
                )
            )

    if not fault.expected_observations or not all(
        isinstance(observation, str) and observation
        for observation in fault.expected_observations
    ):
        details.append(
            _detail(
                SIM_FAULT_EXPECTED_OBS_MISSING,
                f"{label}: expected_observations is required and must be "
                "non-empty event-code strings (ADR-0007 item 5; the "
                "declared observation codes are the SPEC-206 anchor)",
            )
        )

    details.extend(
        _validate_activation(fault, expected_packet_count=expected_packet_count)
    )
    details.extend(_validate_parameters(fault, actual_pmt_pid=actual_pmt_pid))
    return tuple(details)


def transform_builder_for(fault_type: str) -> Callable[[FaultDefinition], "FaultTransform"]:
    """Resolve the transform class for a registered fault type.

    Lazily imported (keeps :mod:`faults.registry` free of the packet
    model); unknown types raise ``KeyError`` — the registry validator has
    already rejected them by the time the filter builds.  The class is
    called with the canonical :class:`FaultDefinition` and receives the
    parsed stream target through it.
    """
    from faults.filters import cc_discontinuity, pat_missing
    from faults.filters import pmt_invalid_crc, pmt_pid_mismatch

    builders = {
        FAULT_TYPE_PAT_MISSING: pat_missing.PatMissingTransform,
        FAULT_TYPE_PMT_INVALID_CRC: pmt_invalid_crc.PmtInvalidCrcTransform,
        FAULT_TYPE_CC_DISCONTINUITY: cc_discontinuity.CCDiscontinuityTransform,
        FAULT_TYPE_PMT_PID_MISMATCH: pmt_pid_mismatch.PmtPidMismatchTransform,
    }
    return builders[fault_type]
