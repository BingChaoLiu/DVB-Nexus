"""State-layer pre-evaluation fault transforms (SPEC-204 §Phase3, #163).

ADR-0012 decision 3: state-layer (RF/SEC) faults enter evaluation as a
*pre-evaluation pure transform* — the fault plan deterministically rewrites
node configs before the walk, and the evaluators stay fault-blind.  This
is a different signature domain from the package-level
``FaultTransform.apply(index, packet)`` filter contract (ADR-0007), so per
orchestrator ruling A18 these transforms do NOT register through
``faults.factory.register_transform``; they live in the module-level
:data:`STATE_TRANSFORM_BY_FAULT_TYPE` table, consumed by the SIM_STATE Run
orchestration (#165).

REPORT-frozen surface (ruling A18):

- ``StateTransform`` — ``(fault: FaultDefinition, node_configs_by_id:
  Mapping[str, dict]) -> Mapping[str, dict]``.  The input carries every
  node's config dict keyed by node_id; the output is the rewritten copy.
  Pure: the input mapping and its config dicts are never mutated; only the
  targeted node's config is copied and rewritten.
- Target/attr contract violations and missing target nodes raise
  ``ValueError`` carrying the ``SIM_FAULT_*`` detail string (the prepare
  face :func:`state_layer_prepare_checks` reports the same codes without
  raising — #165 owns the raise/report split).

Primitives (SPEC-204 §Phase3 first version; the candidate pool
LNB_SHORT_CIRCUIT / SWITCH_MISCONFIG / THERMAL_FAULT stays out — 诚实标注):

- ``TONE_RESIDUE`` (RF layer, A2): rewrite the target lnb's ``tone_actual``
  drive key to ``parameters["tone_actual"]``; ``tone_commanded`` stays —
  the mismatch IS the injected seam (the SPEC-621 dual-field split), the
  band/LO/lock symptoms propagate through the evaluators on their own.
- ``UB_SLOT_CONFLICT`` (SEC layer, A1): rewrite the target tuner's
  ``ub_slot`` to ``parameters["conflicting_ub_slot"]`` — the runtime
  stacking-interference judgement goes exclusively through
  ``simulation.state.unicable.ub_conflicts`` (ruling A13); the transform
  only rewrites config (the static SIM_TOPO_UB_* gate never sees runtime
  faults — the baseline topology is always legal, SPEC-003 §Phase3).  The
  ``node_id:attr_name`` third target form (ruling A4) must address
  ``ub_slot``.

Prepare gate (SPEC-204 §Phase3): :func:`state_layer_prepare_checks`
extends prepare with "fault target node exists + layer routing reachable
(the state transform is registered)" — deliberately independent of the
rf.*/sec.* event registry (ruling A5: registration order with #164 does
not gate fault-plan prepare).
"""

from __future__ import annotations

from typing import Callable, Iterable, Mapping

from faults.definition import FaultDefinition
from faults.registry import (
    FAULT_TYPE_TONE_RESIDUE,
    FAULT_TYPE_UB_SLOT_CONFLICT,
    LAYER_BY_FAULT_TYPE,
    SIM_FAULT_PARAM_INVALID,
    SIM_FAULT_TARGET_INVALID,
)
from faults.targets import FaultTarget, parse_target_id

from simulation.errors import SIM_FAULT_STATE_TRANSFORM_UNREGISTERED
from simulation.state.evaluators._vocab import TONES, TONE_ACTUAL_CONFIG_KEY
from simulation.state.graph import TopologyGraph
from simulation.state.validate import (
    LNB_NODE_TYPE,
    TUNER_NODE_TYPE,
    UB_SLOT_CONFIG_KEY,
)

__all__ = [
    "STATE_FAULT_LAYERS",
    "STATE_TRANSFORM_BY_FAULT_TYPE",
    "StateTransform",
    "state_layer_prepare_checks",
]

#: The state layers (the SPEC-204 §Phase3 FAULT_LAYERS expansion entries).
STATE_FAULT_LAYERS: tuple[str, ...] = ("RF", "SEC")

#: The frozen transform signature (ruling A18): fault + every node's config
#: dict → rewritten copy.  Pure — no mutation, no I/O, no wall clock.
StateTransform = Callable[
    [FaultDefinition, Mapping[str, dict]], Mapping[str, dict]
]


def _fault_label(fault: FaultDefinition) -> str:
    return f"fault {fault.fault_id!r}"


def _resolve_target(fault: FaultDefinition) -> FaultTarget:
    """Parse the target slug, wrapping failures in the SIM_FAULT detail."""
    try:
        return parse_target_id(fault.target_id)
    except ValueError as error:
        raise ValueError(
            f"{SIM_FAULT_TARGET_INVALID}: {_fault_label(fault)}: {error}"
        ) from error


def _require_target_config(
    fault: FaultDefinition,
    target: FaultTarget,
    node_configs_by_id: Mapping[str, dict],
) -> dict:
    """The target node's config dict; unknown nodes are a target fault."""
    config = node_configs_by_id.get(target.node_id)
    if config is None:
        raise ValueError(
            f"{SIM_FAULT_TARGET_INVALID}: {_fault_label(fault)}: target "
            f"node {target.node_id!r} is not in the node config set"
        )
    return config


def _tone_residue_transform(
    fault: FaultDefinition, node_configs_by_id: Mapping[str, dict]
) -> Mapping[str, dict]:
    """Rewrite the target lnb's ``tone_actual``; ``tone_commanded`` stays."""
    target = _resolve_target(fault)
    if target.attr is not None:
        # TONE_RESIDUE addresses the whole lnb node (the registry rejects
        # the attr form; this guard keeps the transform self-contained).
        raise ValueError(
            f"{SIM_FAULT_TARGET_INVALID}: {_fault_label(fault)}: "
            "TONE_RESIDUE addresses the whole lnb node — the bare node_id "
            f"form, not {fault.target_id!r}"
        )
    config = _require_target_config(fault, target, node_configs_by_id)
    tone_actual = fault.parameters.get("tone_actual")
    if not isinstance(tone_actual, str) or tone_actual not in TONES:
        raise ValueError(
            f"{SIM_FAULT_PARAM_INVALID}: {_fault_label(fault)}: tone_actual "
            f"{tone_actual!r} is outside the SPEC-621 §5 tone vocabulary "
            f"{list(TONES)}"
        )
    return {
        **node_configs_by_id,
        target.node_id: {**config, TONE_ACTUAL_CONFIG_KEY: tone_actual},
    }


def _ub_slot_conflict_transform(
    fault: FaultDefinition, node_configs_by_id: Mapping[str, dict]
) -> Mapping[str, dict]:
    """Rewrite the target tuner's ``ub_slot`` to the conflicting slot."""
    target = _resolve_target(fault)
    if target.attr is not None and target.attr != UB_SLOT_CONFIG_KEY:
        raise ValueError(
            f"{SIM_FAULT_TARGET_INVALID}: {_fault_label(fault)}: attr "
            f"segment {target.attr!r} does not address this primitive — "
            f"the node-attribute form must use {UB_SLOT_CONFIG_KEY!r} "
            "(ruling A4)"
        )
    config = _require_target_config(fault, target, node_configs_by_id)
    slot = fault.parameters.get("conflicting_ub_slot")
    if not isinstance(slot, int) or isinstance(slot, bool) or slot < 0:
        raise ValueError(
            f"{SIM_FAULT_PARAM_INVALID}: {_fault_label(fault)}: "
            f"conflicting_ub_slot {slot!r} must be an int >= 0 (0-based UB "
            "slot indexing)"
        )
    return {
        **node_configs_by_id,
        target.node_id: {**config, UB_SLOT_CONFIG_KEY: slot},
    }


#: The module-level state-transform registry (ruling A18): keyed by fault
#: type, consumed by the SIM_STATE Run orchestration (#165).  Registration
#: is by dict literal here — a new state-layer primitive adds one entry.
STATE_TRANSFORM_BY_FAULT_TYPE: dict[str, StateTransform] = {
    FAULT_TYPE_TONE_RESIDUE: _tone_residue_transform,
    FAULT_TYPE_UB_SLOT_CONFLICT: _ub_slot_conflict_transform,
}

#: The addressable node kind per primitive (the prepare gate's node-kind
#: contract; the transforms themselves are config-dict-only per A18).
_TARGET_NODE_TYPE_BY_FAULT_TYPE: dict[str, str] = {
    FAULT_TYPE_TONE_RESIDUE: LNB_NODE_TYPE,
    FAULT_TYPE_UB_SLOT_CONFLICT: TUNER_NODE_TYPE,
}

#: The single addressable config attribute per primitive's attr form
#: (``node_id:attr_name``, ruling A4).  ``None`` = the attr form does not
#: address this primitive (TONE_RESIDUE targets the whole node).
_TARGET_ATTR_BY_FAULT_TYPE: dict[str, str | None] = {
    FAULT_TYPE_TONE_RESIDUE: None,
    FAULT_TYPE_UB_SLOT_CONFLICT: UB_SLOT_CONFIG_KEY,
}


def state_layer_prepare_checks(
    faults: Iterable[FaultDefinition],
    graph: TopologyGraph,
) -> tuple[str, ...]:
    """The SPEC-204 §Phase3 prepare extension — pure, detail-returning.

    For every fault whose declared layer routes to the state domain
    (``LAYER_BY_FAULT_TYPE`` ∈ :data:`STATE_FAULT_LAYERS`; an unregistered
    type falls back to the definition's own ``layer`` field, so a
    prematurely used candidate-pool primitive is rejected here too):

    - layer routing reachable — the fault type has a registered transform
      in :data:`STATE_TRANSFORM_BY_FAULT_TYPE`, else
      ``SIM_FAULT_STATE_TRANSFORM_UNREGISTERED``;
    - the target slug parses and the target node exists in the topology,
      else ``SIM_FAULT_TARGET_INVALID``;
    - the node kind matches the primitive's addressable node type and the
      attr form (ruling A4) addresses the primitive's single attribute.

    Package-layer faults (TS/BBFRAME/T2MI/BISS) are out of scope — they
    route through the ADR-0007 filter chain and are validated by
    ``faults.registry.validate_fault_definition``.  Deliberately
    independent of the rf.*/sec.* event registry (ruling A5).  Returns the
    ``"CODE: message"`` detail tuple in plan order; empty = all routable.
    """
    node_types = {node.node_id: node.node_type for node in graph.nodes}
    details: list[str] = []
    for fault in faults:
        declared = LAYER_BY_FAULT_TYPE.get(fault.fault_type)
        layer = declared if declared is not None else fault.layer
        if layer not in STATE_FAULT_LAYERS:
            continue
        label = _fault_label(fault)
        if fault.fault_type not in STATE_TRANSFORM_BY_FAULT_TYPE:
            details.append(
                f"{SIM_FAULT_STATE_TRANSFORM_UNREGISTERED}: {label}: "
                f"fault_type {fault.fault_type!r} routes to state layer "
                f"{layer!r} but no pre-evaluation state transform is "
                "registered (SPEC-204 §Phase3 layer-routable prepare gate)"
            )
            continue
        try:
            target = parse_target_id(fault.target_id)
        except ValueError as error:
            details.append(f"{SIM_FAULT_TARGET_INVALID}: {label}: {error}")
            continue
        node_type = node_types.get(target.node_id)
        if node_type is None:
            details.append(
                f"{SIM_FAULT_TARGET_INVALID}: {label}: target node "
                f"{target.node_id!r} does not exist in the topology "
                "(SPEC-204 §Phase3 prepare gate)"
            )
            continue
        expected_node_type = _TARGET_NODE_TYPE_BY_FAULT_TYPE.get(
            fault.fault_type
        )
        if node_type != expected_node_type:
            details.append(
                f"{SIM_FAULT_TARGET_INVALID}: {label}: {fault.fault_type} "
                f"addresses {expected_node_type!r} nodes — target "
                f"{fault.target_id!r} sits on a {node_type!r} node"
            )
            continue
        allowed_attr = _TARGET_ATTR_BY_FAULT_TYPE.get(fault.fault_type)
        if target.attr is not None and target.attr != allowed_attr:
            details.append(
                f"{SIM_FAULT_TARGET_INVALID}: {label}: attr segment "
                f"{target.attr!r} does not address this primitive — the "
                f"node-attribute form must use {allowed_attr!r} (ruling A4)"
            )
    return tuple(details)
