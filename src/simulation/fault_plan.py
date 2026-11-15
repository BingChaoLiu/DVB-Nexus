"""SPEC-204 §3/§6 — fault plan seam: prepare-stage validation (#43).

SIM-D (#43) owns the **prepare binding** of the fault plan (ADR-0007 item
2 / REQ-SIM-203-002): the plan is validated at prepare — "session 变异前拒
绝" (AC-204-01 alignment) — and folded into :class:`simulation.ts_runtime.
PreparedTSRun`'s deterministic fingerprint. The fault *transformation*
semantics (the semantic stream filter) belong to SIM-E (#44) in the
``faults`` package; this module never transforms packets.

The two frozen dataclasses mirror SPEC-204 §3's ``FaultDefinition`` /
``FaultActivation`` shapes exactly. They are the declared seam until #44
lands the canonical ``faults`` models: the field sets are identical, so
#44's canonical classes substitute structurally (same duck surface); any
drift is a Change Request, not a silent reshape.

Validation covers the MVP v1 parameter schemas (SPEC-204 §6):

- ``PAT_MISSING``        v1 parameters: ``{}``
- ``PMT_INVALID_CRC``    v1: ``mode`` ∈ {once, persistent} (default
  persistent), ``corruption`` ∈ {invert, zero} (default invert)
- ``CC_DISCONTINUITY``   v1: ``delta`` int 1..15 (required, non-zero)
- ``PMT_PID_MISMATCH``   v1: ``wrong_pmt_pid`` int 0x0001..0x1FFE, ≠ 0,
  ≠ the program's actual ``pmt_pid`` (prepare knows the config), ≠ 0x1FFF

Every violation raises :class:`simulation.errors.TSPlanInvalidError`
(``SIM_TS_PLAN_INVALID``) carrying the per-element error detail list.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from simulation.errors import TSPlanInvalidError

__all__ = [
    "FAULT_TYPE_PAT_MISSING",
    "FAULT_TYPE_PMT_INVALID_CRC",
    "FAULT_TYPE_CC_DISCONTINUITY",
    "FAULT_TYPE_PMT_PID_MISMATCH",
    "MVP_FAULT_TYPES",
    "FaultActivation",
    "FaultDefinition",
    "validate_fault_plan",
]


FAULT_TYPE_PAT_MISSING = "PAT_MISSING"
FAULT_TYPE_PMT_INVALID_CRC = "PMT_INVALID_CRC"
FAULT_TYPE_CC_DISCONTINUITY = "CC_DISCONTINUITY"
FAULT_TYPE_PMT_PID_MISMATCH = "PMT_PID_MISMATCH"

#: The four MVP fault types (SPEC-204 §6; ADR-0007 item 5 — single
#: attributable symptom each).
MVP_FAULT_TYPES: frozenset[str] = frozenset(
    {
        FAULT_TYPE_PAT_MISSING,
        FAULT_TYPE_PMT_INVALID_CRC,
        FAULT_TYPE_CC_DISCONTINUITY,
        FAULT_TYPE_PMT_PID_MISMATCH,
    }
)

#: CC_DISCONTINUITY relative-offset bounds (SPEC-204 §6.3): delta ∈ 1..15.
_CC_DELTA_MIN = 1
_CC_DELTA_MAX = 15

#: PMT_PID_MISMATCH wrong-PID bounds (SPEC-204 §6.4): 13-bit, non-reserved
#: (PSI range 0x0000..0x001F and null PID 0x1FFF excluded — SPEC-103 §8.6).
_WRONG_PID_MIN = 0x0020
_WRONG_PID_MAX = 0x1FFE


@dataclass(frozen=True)
class FaultActivation:
    """SPEC-204 §3 ``FaultActivation`` (MVP: packet_index + session_start).

    ADR-0007 item 3 narrows activation to ``packet_index`` (shared packet
    frame, slot-preserving) and ``session_start`` (whole run). Virtual-time
    and manual-trigger activations are deferred; a wall-clock sleep may
    never schedule a fault (SPEC-204 §3).
    """

    kind: str  # "packet_index" | "session_start"
    packet_index: int | None = None


@dataclass(frozen=True)
class FaultDefinition:
    """SPEC-204 §3 ``FaultDefinition`` (seam shape; canonical home #44).

    ``fault_id`` is uuid4-opaque identity (ADR-0006 item 3) — it takes part
    in neither validation nor the plan fingerprint (identity is not
    semantics; the same plan re-issued with regenerated ids keeps the
    fingerprint stable).
    """

    fault_id: str
    fault_type: str
    target_id: str
    parameters: Mapping[str, Any] = field(default_factory=dict)
    activation: FaultActivation = field(
        default_factory=lambda: FaultActivation(
            kind="session_start", packet_index=None
        )
    )
    expected_observations: tuple[str, ...] = ()


def _plan_error(detail: str) -> TSPlanInvalidError:
    return TSPlanInvalidError(
        f"fault plan rejected at prepare ({detail}); the session was not "
        "mutated (AC-204-01)",
        details=(detail,),
    )


def _validate_activation(fault: FaultDefinition) -> None:
    activation = fault.activation
    if activation.kind == "session_start":
        if activation.packet_index is not None:
            raise _plan_error(
                f"fault {fault.fault_id!r}: activation kind "
                f"'session_start' must not carry a packet_index"
            )
        return
    if activation.kind == "packet_index":
        index = activation.packet_index
        if not isinstance(index, int) or isinstance(index, bool):
            raise _plan_error(
                f"fault {fault.fault_id!r}: activation kind "
                f"'packet_index' requires an int packet_index (shared "
                "frame, 0-based)"
            )
        if index < 0:
            raise _plan_error(
                f"fault {fault.fault_id!r}: packet_index {index} is "
                "negative (0-based shared frame)"
            )
        return
    raise _plan_error(
        f"fault {fault.fault_id!r}: activation kind {activation.kind!r} "
        "is outside the MVP set {'packet_index', 'session_start'} "
        "(ADR-0007 item 3)"
    )


def _validate_parameters(
    fault: FaultDefinition, *, actual_pmt_pid: int | None
) -> None:
    parameters = dict(fault.parameters)
    fault_type = fault.fault_type

    if fault_type == FAULT_TYPE_PAT_MISSING:
        allowed: set[str] = set()
        required: set[str] = set()
    elif fault_type == FAULT_TYPE_PMT_INVALID_CRC:
        allowed = {"mode", "corruption"}
        required = set()
        mode = parameters.get("mode", "persistent")
        if mode not in ("once", "persistent"):
            raise _plan_error(
                f"fault {fault.fault_id!r}: PMT_INVALID_CRC mode "
                f"{mode!r} is not one of 'once' | 'persistent' "
                "(default persistent, SPEC-204 §6.2)"
            )
        corruption = parameters.get("corruption", "invert")
        if corruption not in ("invert", "zero"):
            raise _plan_error(
                f"fault {fault.fault_id!r}: PMT_INVALID_CRC corruption "
                f"{corruption!r} is not one of 'invert' | 'zero' "
                "(default invert, SPEC-204 §6.2)"
            )
    elif fault_type == FAULT_TYPE_CC_DISCONTINUITY:
        allowed = {"delta"}
        required = {"delta"}
        delta = parameters.get("delta")
        if not isinstance(delta, int) or isinstance(delta, bool):
            raise _plan_error(
                f"fault {fault.fault_id!r}: CC_DISCONTINUITY delta must "
                "be an int (SPEC-204 §6.3)"
            )
        if not _CC_DELTA_MIN <= delta <= _CC_DELTA_MAX or delta == 0:
            raise _plan_error(
                f"fault {fault.fault_id!r}: CC_DISCONTINUITY delta "
                f"{delta} outside the non-zero 1..15 range "
                "(SPEC-204 §6.3 relative-offset semantics)"
            )
    elif fault_type == FAULT_TYPE_PMT_PID_MISMATCH:
        allowed = {"wrong_pmt_pid"}
        required = {"wrong_pmt_pid"}
        wrong_pid = parameters.get("wrong_pmt_pid")
        if not isinstance(wrong_pid, int) or isinstance(wrong_pid, bool):
            raise _plan_error(
                f"fault {fault.fault_id!r}: PMT_PID_MISMATCH "
                "wrong_pmt_pid must be an int (SPEC-204 §6.4)"
            )
        if not _WRONG_PID_MIN <= wrong_pid <= _WRONG_PID_MAX or wrong_pid <= 0x001F:
            raise _plan_error(
                f"fault {fault.fault_id!r}: wrong_pmt_pid {wrong_pid:#06x} "
                "is outside the 13-bit non-reserved, non-null range "
                f"(0x0020..{_WRONG_PID_MAX:#06x}; the 0x0000..0x001F PSI "
                "range and the null PID are project-reserved, "
                "SPEC-204 §6.4 / SPEC-103 §8.6)"
            )
        if actual_pmt_pid is not None and wrong_pid == actual_pmt_pid:
            raise _plan_error(
                f"fault {fault.fault_id!r}: wrong_pmt_pid "
                f"{wrong_pid:#06x} equals the program's actual pmt_pid "
                f"({actual_pmt_pid:#06x}) — the mismatch would be a "
                "no-op (SPEC-204 §6.4)"
            )
    else:  # pragma: no cover — unknown types are rejected by the caller
        raise _plan_error(f"fault {fault.fault_id!r}: unknown fault_type")

    unknown = sorted(set(parameters) - allowed)
    if unknown:
        raise _plan_error(
            f"fault {fault.fault_id!r}: unknown parameter key(s) "
            f"{unknown} for {fault_type} schema v1 (SPEC-204 §4: unknown "
            "keys are rejected, never ignored)"
        )
    missing = sorted(required - set(parameters))
    if missing:
        raise _plan_error(
            f"fault {fault.fault_id!r}: missing required parameter key(s) "
            f"{missing} for {fault_type} schema v1"
        )


def validate_fault_plan(
    plan,
    *,
    actual_pmt_pid: int | None = None,
) -> tuple[FaultDefinition, ...]:
    """Validate a fault plan for prepare binding; return it as a tuple.

    ``plan`` may be any sequence (a bare list and an empty sequence are
    both normalized to ``()``). Every element must be a
    :class:`FaultDefinition` (a non-``FaultDefinition`` element is a caller
    programming error → ``TypeError``). Content violations raise
    :class:`simulation.errors.TSPlanInvalidError` (``SIM_TS_PLAN_INVALID``)
    — prepare-stage rejection before any session mutation (AC-204-01).

    ``actual_pmt_pid`` is the program's real PMT PID from the prepared
    config; ``PMT_PID_MISMATCH`` requires ``wrong_pmt_pid`` to differ from
    it (SPEC-204 §6.4 prepare-time rule).
    """
    if plan is None:
        return ()
    plan_tuple = tuple(plan)
    details: list[str] = []
    for fault in plan_tuple:
        if not isinstance(fault, FaultDefinition):
            raise TypeError(
                f"fault plan elements must be FaultDefinition, got "
                f"{type(fault).__name__}"
            )
        try:
            _validate_one(fault, actual_pmt_pid=actual_pmt_pid)
        except TSPlanInvalidError as exc:
            details.extend(exc.details)
    if details:
        raise TSPlanInvalidError(
            f"fault plan rejected at prepare with {len(details)} "
            "validation error(s); the session was not mutated "
            "(AC-204-01)",
            details=tuple(details),
        )
    return plan_tuple


def _validate_one(fault: FaultDefinition, *, actual_pmt_pid: int | None) -> None:
    if not fault.fault_id or not isinstance(fault.fault_id, str):
        raise _plan_error("fault_id must be a non-empty string")
    if fault.fault_type not in MVP_FAULT_TYPES:
        raise _plan_error(
            f"fault {fault.fault_id!r}: fault_type {fault.fault_type!r} "
            "is not in the MVP registry "
            f"{sorted(MVP_FAULT_TYPES)} (SPEC-204 §6)"
        )
    if not fault.target_id or not isinstance(fault.target_id, str):
        raise _plan_error(
            f"fault {fault.fault_id!r}: target_id must be a non-empty "
            "semantic slug (node_id + pid stream addressing, ADR-0006 "
            "item 3)"
        )
    if not fault.expected_observations:
        raise _plan_error(
            f"fault {fault.fault_id!r}: expected_observations is required "
            "and must be non-empty (ADR-0007 item 5; the declared "
            "observation event codes are the SPEC-206 verification anchor)"
        )
    for observation in fault.expected_observations:
        if not isinstance(observation, str) or not observation:
            raise _plan_error(
                f"fault {fault.fault_id!r}: expected_observations entries "
                "must be non-empty strings"
            )
    _validate_activation(fault)
    _validate_parameters(fault, actual_pmt_pid=actual_pmt_pid)
