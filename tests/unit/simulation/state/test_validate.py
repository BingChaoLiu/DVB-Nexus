"""SPEC-202 section 5 — topology validation rule tests (ticket #40).

Seam: ``simulation.state.validate.validate_topology`` — the pure,
non-mutating, repeatable rule surface. Every SPEC-202 section 5 rule gets
at least one minimal counter-example with a path-location assertion
(REQ-SIM-202-001); expected codes are literals from SPEC-202 section 8.
"""

from __future__ import annotations

import pytest

from simulation.errors import TopologyCycleError
from simulation.state.graph import (
    Connection,
    NodeConfig,
    PortSpec,
    TopologyGraph,
    topological_order,
)
from simulation.state.validate import (
    SIM_TOPO_CARDINALITY,
    SIM_TOPO_CYCLE,
    SIM_TOPO_DIRECTION_INVALID,
    SIM_TOPO_DUPLICATE_ID,
    SIM_TOPO_ENDPOINT_MISSING,
    SIM_TOPO_MEDIA_INCOMPATIBLE,
    SIM_TOPO_SELF_LOOP,
    TopologyViolation,
    validate_topology,
)

pytestmark = pytest.mark.unit


def _port(
    port_id: str,
    direction: str = "input",
    plane: str = "MPEG_TS",
    **extra,
) -> PortSpec:
    return PortSpec(port_id=port_id, direction=direction, plane=plane, **extra)


def _node(
    node_id: str,
    *ports: PortSpec,
    node_type: str = "mux",
) -> NodeConfig:
    return NodeConfig(
        node_id=node_id, node_type=node_type, config={}, ports=list(ports)
    )


def _connection(
    connection_id: str = "conn-1",
    from_node: str = "tuner-0",
    from_port: str = "out-0",
    to_node: str = "demux-0",
    to_port: str = "in-0",
    plane: str = "MPEG_TS",
) -> Connection:
    return Connection(
        connection_id=connection_id,
        from_node=from_node,
        from_port=from_port,
        to_node=to_node,
        to_port=to_port,
        plane=plane,
    )


def _linear_graph() -> TopologyGraph:
    return TopologyGraph(
        topology_id="topo-1",
        revision=1,
        nodes=[
            _node("tuner-0", _port("out-0", "output")),
            _node("demux-0", _port("in-0"), _port("out-0", "output")),
        ],
        connections=[_connection()],
    )


def _codes(violations) -> list[str]:
    return [violation.code for violation in violations]


class TestValidTopologies:
    """SPEC-202 section 5: isolated nodes are legal (idle reporting later)."""

    def test_linear_chain_has_no_violations(self) -> None:
        assert validate_topology(_linear_graph()) == ()

    def test_isolated_nodes_are_legal(self) -> None:
        graph = TopologyGraph(
            topology_id="topo-island",
            revision=0,
            nodes=[
                _node("lonely", _port("in-0")),
                _node("tuner-0", _port("out-0", "output")),
            ],
            connections=[],
        )
        assert validate_topology(graph) == ()

    def test_bidirectional_pair_is_legal(self) -> None:
        graph = TopologyGraph(
            topology_id="topo-bidi",
            revision=0,
            nodes=[
                _node("a", _port("p", "bidirectional")),
                _node("b", _port("p", "bidirectional")),
            ],
            connections=[_connection("c1", "a", "p", "b", "p")],
        )
        assert validate_topology(graph) == ()


class TestDuplicateIdRule:
    def test_duplicate_node_id_reported(self) -> None:
        graph = TopologyGraph(
            topology_id="topo-1",
            revision=0,
            nodes=[_node("mux-0", _port("in-0")), _node("mux-0", _port("in-0"))],
            connections=[],
        )
        violations = validate_topology(graph)
        assert _codes(violations) == [SIM_TOPO_DUPLICATE_ID]
        assert violations[0].path == "nodes[mux-0]"

    def test_duplicate_port_id_within_node_reported(self) -> None:
        graph = TopologyGraph(
            topology_id="topo-1",
            revision=0,
            nodes=[_node("mux-0", _port("in-0"), _port("in-0"))],
            connections=[],
        )
        violations = validate_topology(graph)
        assert _codes(violations) == [SIM_TOPO_DUPLICATE_ID]
        assert violations[0].path == "nodes[mux-0].ports[in-0]"

    def test_duplicate_connection_id_reported(self) -> None:
        graph = TopologyGraph(
            topology_id="topo-1",
            revision=0,
            nodes=[
                _node("tuner-0", _port("out-0", "output")),
                _node("demux-0", _port("in-0")),
            ],
            connections=[
                _connection("conn-1"),
                _connection("conn-1"),
            ],
        )
        violations = validate_topology(graph)
        assert _codes(violations) == [SIM_TOPO_DUPLICATE_ID]
        assert violations[0].path == "connections[conn-1]"


class TestEndpointMissingRule:
    def test_missing_to_node_reported(self) -> None:
        graph = TopologyGraph(
            topology_id="topo-1",
            revision=0,
            nodes=[_node("tuner-0", _port("out-0", "output"))],
            connections=[_connection("conn-1")],
        )
        violations = validate_topology(graph)
        assert _codes(violations) == [SIM_TOPO_ENDPOINT_MISSING]
        assert violations[0].path == "connections[conn-1]"

    def test_missing_from_port_reported(self) -> None:
        graph = TopologyGraph(
            topology_id="topo-1",
            revision=0,
            nodes=[
                _node("tuner-0", _port("out-9", "output")),
                _node("demux-0", _port("in-0")),
            ],
            connections=[_connection("conn-1", from_port="out-0")],
        )
        violations = validate_topology(graph)
        assert _codes(violations) == [SIM_TOPO_ENDPOINT_MISSING]
        assert "connections[conn-1]" in violations[0].path


class TestDirectionRule:
    def test_output_to_output_rejected(self) -> None:
        graph = TopologyGraph(
            topology_id="topo-1",
            revision=0,
            nodes=[
                _node("a", _port("out-0", "output")),
                _node("b", _port("out-0", "output")),
            ],
            connections=[_connection("c1", "a", "out-0", "b", "out-0")],
        )
        violations = validate_topology(graph)
        assert _codes(violations) == [SIM_TOPO_DIRECTION_INVALID]

    def test_input_to_input_rejected(self) -> None:
        graph = TopologyGraph(
            topology_id="topo-1",
            revision=0,
            nodes=[
                _node("a", _port("in-0")),
                _node("b", _port("in-0")),
            ],
            connections=[_connection("c1", "a", "in-0", "b", "in-0")],
        )
        violations = validate_topology(graph)
        assert _codes(violations) == [SIM_TOPO_DIRECTION_INVALID]

    def test_reversed_input_to_output_rejected(self) -> None:
        graph = TopologyGraph(
            topology_id="topo-1",
            revision=0,
            nodes=[
                _node("a", _port("in-0")),
                _node("b", _port("out-0", "output")),
            ],
            connections=[_connection("c1", "a", "in-0", "b", "out-0")],
        )
        violations = validate_topology(graph)
        assert _codes(violations) == [SIM_TOPO_DIRECTION_INVALID]


class TestMediaRule:
    def test_plane_mismatch_rejected(self) -> None:
        graph = TopologyGraph(
            topology_id="topo-1",
            revision=0,
            nodes=[
                _node("a", _port("out-0", "output", plane="RF")),
                _node("b", _port("in-0", plane="MPEG_TS")),
            ],
            connections=[_connection("c1", "a", "out-0", "b", "in-0", plane="RF")],
        )
        violations = validate_topology(graph)
        assert _codes(violations) == [SIM_TOPO_MEDIA_INCOMPATIBLE]
        assert violations[0].path == "connections[c1]"


class TestCardinalityRule:
    def test_max_connections_exceeded_reported_on_port(self) -> None:
        graph = TopologyGraph(
            topology_id="topo-1",
            revision=0,
            nodes=[
                _node("tuner-0", _port("out-0", "output")),
                _node(
                    "monitor-0",
                    _port("in-0", max_connections=1),
                ),
            ],
            connections=[
                _connection("c1", "tuner-0", "out-0", "monitor-0", "in-0"),
                _connection("c2", "tuner-0", "out-0", "monitor-0", "in-0"),
            ],
        )
        violations = validate_topology(graph)
        assert _codes(violations) == [SIM_TOPO_CARDINALITY]
        assert violations[0].path == "nodes[monitor-0].ports[in-0]"

    def test_unbounded_port_accepts_multiple(self) -> None:
        graph = TopologyGraph(
            topology_id="topo-1",
            revision=0,
            nodes=[
                _node("tuner-0", _port("out-0", "output")),
                _node("mux-0", _port("in-0")),
            ],
            connections=[
                _connection("c1", "tuner-0", "out-0", "mux-0", "in-0"),
                _connection("c2", "tuner-0", "out-0", "mux-0", "in-0"),
            ],
        )
        assert validate_topology(graph) == ()


class TestSelfLoopRule:
    def test_same_node_same_port_rejected(self) -> None:
        graph = TopologyGraph(
            topology_id="topo-1",
            revision=0,
            nodes=[_node("loop-0", _port("p", "bidirectional"))],
            connections=[_connection("c1", "loop-0", "p", "loop-0", "p")],
        )
        violations = validate_topology(graph)
        assert _codes(violations) == [SIM_TOPO_SELF_LOOP]
        assert violations[0].path == "connections[c1]"

    def test_same_node_different_ports_is_not_self_loop(self) -> None:
        graph = TopologyGraph(
            topology_id="topo-1",
            revision=0,
            nodes=[
                _node("loop-0", _port("in-0"), _port("out-0", "output")),
            ],
            connections=[_connection("c1", "loop-0", "out-0", "loop-0", "in-0")],
        )
        assert validate_topology(graph) == ()


class TestCycleRule:
    def test_cycle_reported_as_violation(self) -> None:
        graph = TopologyGraph(
            topology_id="topo-1",
            revision=0,
            nodes=[
                _node("x", _port("in-0"), _port("out-0", "output")),
                _node("y", _port("in-0"), _port("out-0", "output")),
            ],
            connections=[
                _connection("c1", "x", "out-0", "y", "in-0"),
                _connection("c2", "y", "out-0", "x", "in-0"),
            ],
        )
        violations = validate_topology(graph)
        assert [SIM_TOPO_CYCLE] == [v.code for v in violations]

    def test_cycle_not_reported_on_valid_dag(self) -> None:
        assert all(
            v.code != SIM_TOPO_CYCLE
            for v in validate_topology(_linear_graph())
        )


class TestValidationDiscipline:
    """SPEC-202 section 5: non-mutating, repeatable, deterministic."""

    def test_repeatable_and_non_mutating(self) -> None:
        graph = _linear_graph()
        nodes_before = list(graph.nodes)
        connections_before = list(graph.connections)
        first = validate_topology(graph)
        second = validate_topology(graph)
        assert first == second
        assert list(graph.nodes) == nodes_before
        assert list(graph.connections) == connections_before

    def test_violation_order_is_independent_of_input_list_order(self) -> None:
        def build(order: list[str]) -> TopologyGraph:
            by_id = {
                "b": _node("b", _port("in-0")),
                "a": _node("a", _port("in-0")),
            }
            return TopologyGraph(
                topology_id="topo-1",
                revision=0,
                nodes=[by_id[name] for name in order],
                connections=[
                    _connection("c1", "ghost-1", "out-0", "a", "in-0"),
                    _connection("c2", "ghost-2", "out-0", "b", "in-0"),
                ],
            )

        result_one = validate_topology(build(["a", "b"]))
        result_two = validate_topology(build(["b", "a"]))
        assert result_one == result_two
        assert len(result_one) == 2

    def test_topological_order_still_rejects_cycles(self) -> None:
        graph = TopologyGraph(
            topology_id="topo-1",
            revision=0,
            nodes=[
                _node("x", _port("in-0"), _port("out-0", "output")),
                _node("y", _port("in-0"), _port("out-0", "output")),
            ],
            connections=[
                _connection("c1", "x", "out-0", "y", "in-0"),
                _connection("c2", "y", "out-0", "x", "in-0"),
            ],
        )
        with pytest.raises(TopologyCycleError):
            topological_order(graph)


class TestViolationType:
    def test_violation_is_frozen_dataclass(self) -> None:
        import dataclasses

        violation = TopologyViolation(
            code=SIM_TOPO_SELF_LOOP, path="connections[c1]", message="m"
        )
        assert dataclasses.is_dataclass(violation)
        with pytest.raises(dataclasses.FrozenInstanceError):
            violation.code = "other"  # type: ignore[misc]
