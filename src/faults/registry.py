"""SPEC-204 §4/§6/§11 — the fault-type registry and schema validation.

One registry entry per fault type (§6, ADR-0007 item 5 — single
attributable symptom each), carrying:

- the versioned parameter schema (``PARAMETERS_SCHEMA_VERSION = 1``);
- the declared pipeline ``layer`` (Phase 2, SPEC-204 §Phase2 /
  ADR-0010 §3: {TS, BBFRAME, T2MI, BISS});
- the per-type activation set (Phase 2 pins some primitives to a single
  activation kind);
- the transform builder used by the semantic stream filter
  (:mod:`faults.filters.semantic`, lazily imported to keep this module
  free of the packet model).  Phase 2 (#121, orchestrator ruling §10-4)
  makes the builder table pluggable via
  :func:`faults.factory.register_transform` — downstream tickets
  self-register their filter builders from their own modules.

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

import re
from typing import TYPE_CHECKING, Callable

from faults.definition import FaultActivation, FaultDefinition
from faults.targets import FaultTarget, parse_target_id

if TYPE_CHECKING:  # pragma: no cover — typing only
    from faults.filters.base import FaultTransform

__all__ = [
    "FAULT_LAYERS",
    "FAULT_TYPE_BBHEADER_SYNC_FAULT",
    "FAULT_TYPE_BISS_KEY_MISMATCH",
    "FAULT_TYPE_CC_DISCONTINUITY",
    "FAULT_TYPE_PAT_MISSING",
    "FAULT_TYPE_PMT_INVALID_CRC",
    "FAULT_TYPE_PMT_PID_DRIFT",
    "FAULT_TYPE_PMT_PID_MISMATCH",
    "FAULT_TYPE_T2MI_PLP_MISMATCH",
    "KNOWN_FAULT_TYPES",
    "LAYER_BY_FAULT_TYPE",
    "MVP_FAULT_TYPES",
    "PARAMETERS_SCHEMA_VERSION",
    "PHASE2_FAULT_TYPES",
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

# --- Phase 2 primitives (SPEC-204 §Phase2, ticket #121) --------------------------

FAULT_TYPE_T2MI_PLP_MISMATCH = "T2MI_PLP_MISMATCH"
FAULT_TYPE_BBHEADER_SYNC_FAULT = "BBHEADER_SYNC_FAULT"
FAULT_TYPE_BISS_KEY_MISMATCH = "BISS_KEY_MISMATCH"
FAULT_TYPE_PMT_PID_DRIFT = "PMT_PID_DRIFT"

#: The four Phase 2 primitives (the MVP "baseline freeze" expansion port).
PHASE2_FAULT_TYPES: frozenset[str] = frozenset(
    {
        FAULT_TYPE_T2MI_PLP_MISMATCH,
        FAULT_TYPE_BBHEADER_SYNC_FAULT,
        FAULT_TYPE_BISS_KEY_MISMATCH,
        FAULT_TYPE_PMT_PID_DRIFT,
    }
)

#: The full known registry: MVP four + Phase 2 four (additive union).
KNOWN_FAULT_TYPES: frozenset[str] = MVP_FAULT_TYPES | PHASE2_FAULT_TYPES

#: The pipeline layer set (SPEC-204 §Phase2 / ADR-0010 §3).
FAULT_LAYERS: tuple[str, ...] = ("TS", "BBFRAME", "T2MI", "BISS")

#: Declared layer per fault type — the runtime routes filters by this
#: (``FaultDefinition.layer`` must equal the declared value; the MVP four
#: are TS-layer faults, so their default ``layer="TS"`` already matches).
LAYER_BY_FAULT_TYPE: dict[str, str] = {
    FAULT_TYPE_PAT_MISSING: "TS",
    FAULT_TYPE_PMT_INVALID_CRC: "TS",
    FAULT_TYPE_CC_DISCONTINUITY: "TS",
    FAULT_TYPE_PMT_PID_MISMATCH: "TS",
    FAULT_TYPE_T2MI_PLP_MISMATCH: "T2MI",
    FAULT_TYPE_BBHEADER_SYNC_FAULT: "BBFRAME",
    FAULT_TYPE_BISS_KEY_MISMATCH: "BISS",
    FAULT_TYPE_PMT_PID_DRIFT: "TS",
}

#: Per-type activation sets.  Types not listed accept both MVP kinds
#: (``T2MI_PLP_MISMATCH`` keeps session_start (default) | packet_index).
_ACTIVATION_KINDS_BY_TYPE: dict[str, frozenset[str]] = {
    FAULT_TYPE_BBHEADER_SYNC_FAULT: frozenset({"packet_index"}),
    FAULT_TYPE_BISS_KEY_MISMATCH: frozenset({"session_start"}),
    FAULT_TYPE_PMT_PID_DRIFT: frozenset({"packet_index"}),
}

#: Fault types that address a node-internal layer target (bare
#: ``node_id`` slug): BBFrame/T2-MI/BISS carry no shared-frame pid, so
#: the pid form is rejected for them.  Every other known type (the MVP
#: four, the TS-layer PMT_PID_DRIFT — and any unknown type, conservatively)
#: requires the stream-level ``node:pid:0x{hex}`` form.
_TARGET_REJECTS_PID: frozenset[str] = PHASE2_FAULT_TYPES - {
    FAULT_TYPE_PMT_PID_DRIFT,
}

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

#: PLP identifier value domain (Phase 2): DVB-T2 L1 signalling carries the
#: PLP_ID in an 8-bit field (0..255) — SPEC-602 §8 "PLP ID 越界 schema 拒绝".
_PLP_ID_MIN = 0
_PLP_ID_MAX = 0xFF

#: BISS key-material wire formats (SPEC-610 §5 / SPEC-611 §5): session
#: word = 12 hex (48-bit), encrypted session word = 16 hex, injected ID
#: = 32 hex (128-bit).  Case-insensitive.
_BISS_SW_PATTERN = re.compile(r"^[0-9A-Fa-f]{12}$")
_BISS_ESW_PATTERN = re.compile(r"^[0-9A-Fa-f]{16}$")
_BISS_INJECTED_ID_PATTERN = re.compile(r"^[0-9A-Fa-f]{32}$")

#: BBHEADER field enumeration for BBHEADER_SYNC_FAULT (EN 302 755 §5.1.7).
_BBHEADER_FIELDS = ("MATYPE", "UPL", "DFL", "SYNC", "SYNCD", "CRC-8")

#: BBHEADER_SYNC_FAULT mode enumeration (SPEC-204 §Phase2 item 2).
_BBHEADER_FAULT_MODES = ("corrupt", "shift")

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
    allowed_kinds = _ACTIVATION_KINDS_BY_TYPE.get(fault.fault_type)
    if allowed_kinds is not None and activation.kind not in allowed_kinds:
        return [
            _detail(
                SIM_FAULT_PARAM_INVALID,
                f"{label}: activation kind {activation.kind!r} is not "
                f"allowed for {fault.fault_type} (allowed: "
                f"{sorted(allowed_kinds)}, SPEC-204 §Phase2)",
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


# --- versioned parameter schemas (SPEC-204 §4/§6 + §Phase2) ----------------------

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
    FAULT_TYPE_T2MI_PLP_MISMATCH: {
        "allowed": {"expected_plp", "actual_plp", "plp_version_switch"},
        "required": {"expected_plp", "actual_plp"},
    },
    FAULT_TYPE_BBHEADER_SYNC_FAULT: {
        "allowed": {"field", "mode"},
        "required": {"field", "mode"},
    },
    FAULT_TYPE_BISS_KEY_MISMATCH: {
        "allowed": {
            "wrong_session_word",
            "wrong_esw",
            "wrong_injected_id",
            "pid_scope",
        },
        "required": {"pid_scope"},
    },
    FAULT_TYPE_PMT_PID_DRIFT: {
        "allowed": {"new_pid_map", "pmt_version_bump"},
        "required": {"new_pid_map", "pmt_version_bump"},
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
    elif fault_type == FAULT_TYPE_T2MI_PLP_MISMATCH:
        _validate_t2mi_plp_mismatch_params(parameters, reject)
    elif fault_type == FAULT_TYPE_BBHEADER_SYNC_FAULT:
        field = parameters["field"]
        if field not in _BBHEADER_FIELDS:
            reject(
                f"BBHEADER_SYNC_FAULT field {field!r} is not one of "
                f"{list(_BBHEADER_FIELDS)} (EN 302 755 §5.1.7, SPEC-204 "
                "§Phase2)"
            )
        mode = parameters["mode"]
        if mode not in _BBHEADER_FAULT_MODES:
            reject(
                f"BBHEADER_SYNC_FAULT mode {mode!r} is not one of "
                f"{list(_BBHEADER_FAULT_MODES)} (SPEC-204 §Phase2)"
            )
    elif fault_type == FAULT_TYPE_BISS_KEY_MISMATCH:
        _validate_biss_key_mismatch_params(parameters, reject)
    elif fault_type == FAULT_TYPE_PMT_PID_DRIFT:
        _validate_pmt_pid_drift_params(parameters, reject)
    return details


def _validate_t2mi_plp_mismatch_params(
    parameters: dict, reject
) -> None:
    """T2MI_PLP_MISMATCH value rules (SPEC-204 §Phase2 item 1 / SPEC-602)."""
    for key in ("expected_plp", "actual_plp"):
        plp_id = parameters[key]
        if not isinstance(plp_id, int) or isinstance(plp_id, bool):
            reject(f"T2MI_PLP_MISMATCH {key} must be an int (PLP_ID)")
        elif not _PLP_ID_MIN <= plp_id <= _PLP_ID_MAX:
            reject(
                f"T2MI_PLP_MISMATCH {key} {plp_id} outside the 8-bit PLP_ID "
                f"value domain ({_PLP_ID_MIN}..{_PLP_ID_MAX}, SPEC-602 §8)"
            )
    if parameters["expected_plp"] == parameters["actual_plp"]:
        reject(
            "T2MI_PLP_MISMATCH expected_plp equals actual_plp — the "
            "mismatch would be a no-op (SPEC-204 §Phase2 item 1)"
        )
    if "plp_version_switch" in parameters and not isinstance(
        parameters["plp_version_switch"], bool
    ):
        reject(
            "T2MI_PLP_MISMATCH plp_version_switch must be a bool "
            "(SPEC-204 §Phase2 item 1)"
        )


def _validate_biss_key_mismatch_params(
    parameters: dict, reject
) -> None:
    """BISS_KEY_MISMATCH value rules (SPEC-204 §Phase2 item 3, SPEC-610/611 §5).

    Two mutually exclusive key-mismatch variants: Mode 1 declares a
    ``wrong_session_word`` (12 hex); Mode E declares ``wrong_esw`` (16 hex)
    and/or ``wrong_injected_id`` (32 hex).  ``pid_scope`` is always
    required (non-empty list of 13-bit ints).
    """
    pid_scope = parameters["pid_scope"]
    if not isinstance(pid_scope, list) or not pid_scope:
        reject(
            "BISS_KEY_MISMATCH pid_scope must be a non-empty list of PIDs "
            "(SPEC-204 §Phase2 item 3)"
        )
    else:
        for pid in pid_scope:
            if not isinstance(pid, int) or isinstance(pid, bool):
                reject(
                    "BISS_KEY_MISMATCH pid_scope entries must be ints "
                    f"(got {pid!r})"
                )
            elif not 0x0000 <= pid <= 0x1FFF:
                reject(
                    f"BISS_KEY_MISMATCH pid_scope entry {pid} outside the "
                    "13-bit range (0x0000..0x1FFF)"
                )
    has_mode1 = "wrong_session_word" in parameters
    has_mode_e = "wrong_esw" in parameters or "wrong_injected_id" in parameters
    if has_mode1 and has_mode_e:
        reject(
            "BISS_KEY_MISMATCH variants are mutually exclusive: either "
            "wrong_session_word (Mode 1) or wrong_esw/wrong_injected_id "
            "(Mode E), never both (SPEC-204 §Phase2 item 3)"
        )
        return
    if not has_mode1 and not has_mode_e:
        reject(
            "BISS_KEY_MISMATCH requires a key-mismatch variant: "
            "wrong_session_word (Mode 1) or wrong_esw/wrong_injected_id "
            "(Mode E) (SPEC-204 §Phase2 item 3)"
        )
        return
    if has_mode1:
        session_word = parameters["wrong_session_word"]
        if not isinstance(session_word, str) or not _BISS_SW_PATTERN.match(
            session_word
        ):
            reject(
                f"BISS_KEY_MISMATCH wrong_session_word {session_word!r} is "
                "not a 12-hex-digit session word (48-bit, SPEC-610 §5)"
            )
        return
    for key, pattern, length in (
        ("wrong_esw", _BISS_ESW_PATTERN, 16),
        ("wrong_injected_id", _BISS_INJECTED_ID_PATTERN, 32),
    ):
        if key in parameters:
            value = parameters[key]
            if not isinstance(value, str) or not pattern.match(value):
                reject(
                    f"BISS_KEY_MISMATCH {key} {value!r} is not a "
                    f"{length}-hex-digit value (SPEC-611 §5)"
                )


def _validate_pmt_pid_drift_params(
    parameters: dict, reject
) -> None:
    """PMT_PID_DRIFT value rules (SPEC-204 §Phase2 item 4).

    ``new_pid_map`` maps program_number → drifted pmt_pid (the TS-layer
    equivalent of PMT_PID_MISMATCH, applied per packet_index); program
    numbers are positive ints, drifted PIDs follow the same non-reserved,
    non-null 13-bit rule as PMT_PID_MISMATCH (§6.4).
    """
    pid_map = parameters["new_pid_map"]
    if not isinstance(pid_map, dict) or not pid_map:
        reject(
            "PMT_PID_DRIFT new_pid_map must be a non-empty mapping of "
            "program_number → drifted pmt_pid (SPEC-204 §Phase2 item 4)"
        )
        return
    for program_number, drifted_pid in pid_map.items():
        if not isinstance(program_number, int) or isinstance(
            program_number, bool
        ):
            reject(
                f"PMT_PID_DRIFT program_number {program_number!r} must be "
                "an int"
            )
        elif program_number < 1:
            reject(
                f"PMT_PID_DRIFT program_number {program_number} must be "
                "positive (0 is the PAT's program_count indicator)"
            )
        if not isinstance(drifted_pid, int) or isinstance(drifted_pid, bool):
            reject(
                f"PMT_PID_DRIFT drifted pmt_pid {drifted_pid!r} must be an "
                "int"
            )
        elif not _WRONG_PID_MIN <= drifted_pid <= _WRONG_PID_MAX:
            reject(
                f"PMT_PID_DRIFT drifted pmt_pid {drifted_pid:#06x} is "
                f"outside the 13-bit non-reserved, non-null range "
                f"({_WRONG_PID_MIN:#06x}..{_WRONG_PID_MAX:#06x}, "
                "SPEC-204 §6.4 rule carried over)"
            )
    if not isinstance(parameters["pmt_version_bump"], bool):
        reject(
            "PMT_PID_DRIFT pmt_version_bump must be a bool (SPEC-204 "
            "§Phase2 item 4)"
        )


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

    if fault.fault_type not in KNOWN_FAULT_TYPES:
        details.append(
            _detail(
                SIM_FAULT_UNKNOWN_TYPE,
                f"{label}: fault_type {fault.fault_type!r} is not in the "
                f"registry {sorted(KNOWN_FAULT_TYPES)} (SPEC-204 §6 + "
                "§Phase2)",
            )
        )

    # --- layer (SPEC-204 §Phase2 / ADR-0010 §3) --------------------------
    declared_layer = LAYER_BY_FAULT_TYPE.get(fault.fault_type)
    if fault.fault_type in KNOWN_FAULT_TYPES:
        if fault.layer not in FAULT_LAYERS:
            details.append(
                _detail(
                    SIM_FAULT_PARAM_INVALID,
                    f"{label}: layer {fault.layer!r} is outside the "
                    f"pipeline layer set {list(FAULT_LAYERS)} (SPEC-204 "
                    "§Phase2)",
                )
            )
        elif declared_layer is not None and fault.layer != declared_layer:
            details.append(
                _detail(
                    SIM_FAULT_PARAM_INVALID,
                    f"{label}: layer {fault.layer!r} does not match the "
                    f"layer declared for {fault.fault_type} "
                    f"({declared_layer!r}, SPEC-204 §Phase2)",
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
        if target.pid is None and fault.fault_type not in _TARGET_REJECTS_PID:
            # MVP four + PMT_PID_DRIFT are stream-level; unknown types keep
            # the strict MVP-era stream-level requirement (never looser).
            details.append(
                _detail(
                    SIM_FAULT_TARGET_INVALID,
                    f"{label}: {fault.fault_type} is a stream-level "
                    f"fault — target {fault.target_id!r} must be the "
                    "'{node_id}:pid:0x{hex}' form (node_id + pid, ADR-0006 "
                    "item 3)",
                )
            )
        elif target.pid is not None and fault.fault_type in _TARGET_REJECTS_PID:
            details.append(
                _detail(
                    SIM_FAULT_TARGET_INVALID,
                    f"{label}: {fault.fault_type} acts on a node-internal "
                    "layer (no shared-frame pid) — target "
                    f"{fault.target_id!r} must be the bare node_id slug "
                    "(ADR-0006 item 3 node-level form)",
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

    Resolution order: the pluggable override table
    (:func:`faults.factory.register_transform` — Phase 2 self-registration,
    ticket #121 / ruling §10-4) first, then the MVP built-in table below.
    Lazily imported (keeps :mod:`faults.registry` free of the packet
    model and avoids the module-load cycle with :mod:`faults.factory`);
    unknown types raise ``KeyError`` — the registry validator has
    already rejected them by the time the filter builds.  The class is
    called with the canonical :class:`FaultDefinition` and receives the
    parsed stream target through it.
    """
    # Deferred import: factory imports the semantic filter, which imports
    # this module — resolving the override table at call time keeps the
    # graph acyclic at load time.
    from faults import factory as _factory

    override = _factory.override_builder_for(fault_type)
    if override is not None:
        return override

    from faults.filters import cc_discontinuity, pat_missing
    from faults.filters import pmt_invalid_crc, pmt_pid_mismatch

    builders = {
        FAULT_TYPE_PAT_MISSING: pat_missing.PatMissingTransform,
        FAULT_TYPE_PMT_INVALID_CRC: pmt_invalid_crc.PmtInvalidCrcTransform,
        FAULT_TYPE_CC_DISCONTINUITY: cc_discontinuity.CCDiscontinuityTransform,
        FAULT_TYPE_PMT_PID_MISMATCH: pmt_pid_mismatch.PmtPidMismatchTransform,
    }
    return builders[fault_type]
