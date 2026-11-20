"""Interface-freeze guard for the SPEC-202 State Engine skeleton (#40).

SIM-E (#44) imports the ``simulation.state`` surface; these tests fail on
any accidental drift of the public export sets (additions must be a
deliberate, ticket-visible act, never a silent side effect of a refactor).
The expected sets below are the frozen literals agreed for ticket #40.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

#: The frozen public surface of the ``simulation.state`` package.
FROZEN_STATE_EXPORTS = frozenset(
    {
        # graph contract (SPEC-202 section 4)
        "Connection",
        "ConnectionId",
        "NodeConfig",
        "NodeId",
        "PortDirection",
        "PortId",
        "PortSpec",
        "SignalPlane",
        "TopologyGraph",
        "topological_order",
        # validation rules (SPEC-202 section 5)
        "SIM_TOPO_CARDINALITY",
        "SIM_TOPO_CYCLE",
        "SIM_TOPO_DIRECTION_INVALID",
        "SIM_TOPO_DUPLICATE_ID",
        "SIM_TOPO_ENDPOINT_MISSING",
        "SIM_TOPO_MEDIA_INCOMPATIBLE",
        "SIM_TOPO_SELF_LOOP",
        # Unicable UB validator codes (SPEC-003 §Phase3, ticket #160)
        "SIM_TOPO_UB_PROTOCOL_MIXED",
        "SIM_TOPO_UB_SLOT_CONFLICT",
        "SIM_TOPO_UB_SLOT_OUT_OF_RANGE",
        "SIM_TOPO_UB_SLOT_UNMATCHED",
        "TopologyViolation",
        "validate_topology",
        # evaluation interface + skeleton walk (SPEC-202 section 6)
        "SIM_EVAL_NODE_FAILED",
        "CauseRef",
        "EvalContext",
        "Health",
        "L0_DEFERRED_RATIONALE",
        "NodeEvalResult",
        "NodeEvaluator",
        "NodeFailure",
        "PortState",
        "TopologyEvalResult",
        "changed_nodes",
        "evaluate_topology",
        "severity_rank",
    }
)

#: SPEC-202 section 8 codes appended to the package-level error module,
#: plus the SPEC-003 §Phase3 SIM_TOPO_UB_* family (ticket #160).
FROZEN_ERROR_CODES = frozenset(
    {
        "SIM_TOPO_DUPLICATE_ID",
        "SIM_TOPO_ENDPOINT_MISSING",
        "SIM_TOPO_DIRECTION_INVALID",
        "SIM_TOPO_MEDIA_INCOMPATIBLE",
        "SIM_TOPO_CARDINALITY",
        "SIM_TOPO_SELF_LOOP",
        "SIM_TOPO_CYCLE",
        "SIM_EVAL_NODE_FAILED",
        "SIM_TOPO_UB_SLOT_UNMATCHED",
        "SIM_TOPO_UB_SLOT_CONFLICT",
        "SIM_TOPO_UB_SLOT_OUT_OF_RANGE",
        "SIM_TOPO_UB_PROTOCOL_MIXED",
    }
)


def test_simulation_state_export_set_is_frozen() -> None:
    import simulation.state

    assert frozenset(simulation.state.__all__) == FROZEN_STATE_EXPORTS


def test_state_exports_resolve() -> None:
    import simulation.state

    for name in simulation.state.__all__:
        assert getattr(simulation.state, name, None) is not None, name


def test_spec202_error_codes_exist_on_simulation_errors() -> None:
    import simulation.errors

    for code in FROZEN_ERROR_CODES:
        assert getattr(simulation.errors, code) == code


def test_spec202_error_codes_are_reexported_from_simulation() -> None:
    """The package root re-exports the SPEC-202 codes (append-only surface
    shared with the SPEC-201 codes)."""
    import simulation

    for code in FROZEN_ERROR_CODES:
        assert getattr(simulation, code, None) == code


def test_deferred_marker_documented_in_module_docstrings() -> None:
    """The L0 deferral must stay visible where the stub lives."""
    import simulation.state.evaluate as evaluate_module

    assert "ADR-0005 decision 2" in evaluate_module.__doc__
    assert "ADR-0005" in evaluate_module.L0_DEFERRED_RATIONALE


class TestNodeEvaluatorProtocol:
    """The evaluator seam is structurally satisfiable (dependency
    injection discipline, SPEC-202 section 9)."""

    def test_stub_evaluator_satisfies_protocol(self) -> None:
        from simulation.state import NodeEvaluator
        from simulation.state.evaluate import (
            EvalContext,
            Health,
            NodeEvalResult,
        )
        from simulation.state.graph import NodeConfig, PortSpec

        class Evaluator:
            def evaluate(self, node, inputs, context):
                return NodeEvalResult(
                    node_id=node.node_id, health=Health.IDLE
                )

        evaluator: NodeEvaluator = Evaluator()
        node = NodeConfig(
            node_id="n",
            node_type="t",
            config={},
            ports=[
                PortSpec(port_id="p", direction="input", plane="MPEG_TS")
            ],
        )
        result = evaluator.evaluate(
            node, {}, EvalContext(topology_revision=0)
        )
        assert result.health is Health.IDLE
