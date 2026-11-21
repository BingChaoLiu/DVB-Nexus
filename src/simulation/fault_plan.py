"""SPEC-204 §3/§4/§11 — fault plan prepare validation (canonicalized, #44).

SIM-D (#43) owned the **prepare binding** of the fault plan (ADR-0007
item 2 / REQ-SIM-203-002): the plan is validated at prepare — "session 变
异前拒绝" (AC-204-01) — and folded into :class:`simulation.ts_runtime.
PreparedTSRun`'s deterministic fingerprint.  #43 had also declared the
``FaultDefinition`` / ``FaultActivation`` structural seam here with
field-identical dataclasses.

SIM-E (#44) performed the canonicalization: the canonical classes live in
:mod:`faults.definition` (ADR-0005 D4-4: ``faults → ts``, simulation
consumes faults) and are re-exported below, so every #43 consumer
(``simulation.ts_runtime``, tests, callers) keeps working unchanged with
the same objects.  The per-element validation rules themselves now live in
:mod:`faults.registry` (pure, returns SPEC-204 §11 detail codes); this
module stays the prepare-face that raises
:class:`simulation.errors.TSPlanInvalidError` (``SIM_TS_PLAN_INVALID``)
carrying the per-element error detail list — ``faults`` must never import
``simulation``, so the exception raising stays on this side of the edge.

Validation covers the MVP v1 parameter schemas (SPEC-204 §6, registry
owner: :mod:`faults.registry`):

- ``PAT_MISSING``        v1 parameters: ``{}``
- ``PMT_INVALID_CRC``    v1: ``mode`` ∈ {once, persistent} (default
  persistent), ``corruption`` ∈ {invert, zero} (default invert)
- ``CC_DISCONTINUITY``   v1: ``delta`` int 1..15 (required, non-zero)
- ``PMT_PID_MISMATCH``   v1: ``wrong_pmt_pid`` int 0x0020..0x1FFE, ≠ the
  program's actual ``pmt_pid`` (prepare knows the config)

plus the SPEC-204 §3 target/activation/expected_observations rules and the
§11 ``SIM_FAULT_ACTIVATION_OUT_OF_RANGE`` frame check (packet_index vs the
prepared output frame when the length is budgetable at prepare).
"""

from __future__ import annotations

from typing import Sequence

from faults.definition import FaultActivation, FaultDefinition
from faults.registry import (
    FAULT_TYPE_CC_DISCONTINUITY,
    FAULT_TYPE_PAT_MISSING,
    FAULT_TYPE_PMT_INVALID_CRC,
    FAULT_TYPE_PMT_PID_MISMATCH,
    LAYER_BY_FAULT_TYPE,
    MVP_FAULT_TYPES,
    validate_fault_definition,
)

from simulation.errors import (
    SIM_FAULT_PLAN_LAYER_MISMATCH,
    TSPlanInvalidError,
)

__all__ = [
    "FAULT_TYPE_PAT_MISSING",
    "FAULT_TYPE_PMT_INVALID_CRC",
    "FAULT_TYPE_CC_DISCONTINUITY",
    "FAULT_TYPE_PMT_PID_MISMATCH",
    "MVP_FAULT_TYPES",
    "PACKAGE_PLAN_LAYERS",
    "FaultActivation",
    "FaultDefinition",
    "validate_fault_plan",
]

#: The package-level (ADR-0007 filter-chain) layers a SIM_TS prepare
#: accepts (ticket #165's bidirectional mixed-plan gate; the state layers
#: RF/SEC route through the pre-evaluation transform path —
#: ``simulation.state.run`` — and are rejected here for the TS face).
PACKAGE_PLAN_LAYERS: tuple[str, ...] = ("TS", "BBFRAME", "T2MI", "BISS")


def validate_fault_plan(
    plan,
    *,
    actual_pmt_pid: int | None = None,
    expected_packet_count: int | None = None,
    allowed_layers: Sequence[str] | None = None,
) -> tuple[FaultDefinition, ...]:
    """Validate a fault plan for prepare binding; return it as a tuple.

    ``plan`` may be any sequence (a bare list and an empty sequence are
    both normalized to ``()``).  Every element must be a canonical
    :class:`FaultDefinition` (a non-``FaultDefinition`` element is a caller
    programming error → ``TypeError``).  Content violations raise
    :class:`simulation.errors.TSPlanInvalidError` (``SIM_TS_PLAN_INVALID``)
    with the per-element SPEC-204 §11 detail codes — prepare-stage
    rejection before any session mutation (AC-204-01).

    ``actual_pmt_pid`` is the program's real PMT PID from the prepared
    config; ``PMT_PID_MISMATCH`` requires ``wrong_pmt_pid`` to differ from
    it (SPEC-204 §6.4 prepare-time rule).  ``expected_packet_count`` is the
    prepared output frame length when budgetable at prepare; a
    ``packet_index`` activation beyond it is rejected as
    ``SIM_FAULT_ACTIVATION_OUT_OF_RANGE`` (SPEC-204 §11).

    ``allowed_layers`` (ticket #165, additive keyword-only; default
    ``None`` = the pre-#165 behavior byte-identically) is the consuming
    run form's layer allowlist — the bidirectional mixed-plan gate
    (ADR-0012 decisions 2/3): a fault whose effective layer
    (:data:`faults.registry.LAYER_BY_FAULT_TYPE` declaration, falling back
    to the definition's own ``layer`` field) is outside the allowlist gets
    a ``SIM_FAULT_PLAN_LAYER_MISMATCH`` detail.  The TS face
    (``simulation.ts_runtime.TSRuntime.prepare``) passes
    :data:`PACKAGE_PLAN_LAYERS`, so an RF/SEC fault is rejected cleanly at
    prepare instead of crashing ``LayerFaultFilter`` construction at
    run stage (#163 REPORT note).
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
        if not fault.fault_id or not isinstance(fault.fault_id, str):
            details.append(
                "SIM_FAULT_PARAM_INVALID: fault_id must be a non-empty "
                "string (uuid4 opaque identity, ADR-0006 item 3)"
            )
            continue
        details.extend(
            validate_fault_definition(
                fault,
                actual_pmt_pid=actual_pmt_pid,
                expected_packet_count=expected_packet_count,
            )
        )
        if allowed_layers is not None:
            effective_layer = LAYER_BY_FAULT_TYPE.get(
                fault.fault_type, fault.layer
            )
            if effective_layer not in allowed_layers:
                details.append(
                    f"{SIM_FAULT_PLAN_LAYER_MISMATCH}: fault "
                    f"{fault.fault_id!r}: fault_type {fault.fault_type!r} "
                    f"routes to layer {effective_layer!r}, outside this "
                    f"prepare's allowed layer set {sorted(allowed_layers)} "
                    "(ADR-0012 decisions 2/3 bidirectional mixed-plan gate"
                    " — the execution通路 is declared per run form)"
                )
    if details:
        raise TSPlanInvalidError(
            f"fault plan rejected at prepare with {len(details)} "
            "validation error(s); the session was not mutated "
            "(AC-204-01)",
            details=tuple(details),
        )
    return plan_tuple
