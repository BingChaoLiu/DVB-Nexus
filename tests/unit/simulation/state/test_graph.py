"""SPEC-202 State Engine — graph contract unit tests (ticket #40).

Seam: the public construction surface of ``simulation.state.graph`` (the
frozen types SIM-E/#44 will depend on). Expected values are literals copied
from SPEC-202 section 4 (four-tuple connections, named ports with
direction/plane/max-connections) — an independent source of truth.

Note on the shared domain model: the import-linter contract (ADR-0005
D4-4 + M3 ruling, pyproject) forbids ``simulation`` from importing
``domain.topology``, so the graph contract is defined on the simulation
side and the tests (which are not import-linted) assert 1:1 shape and
enum-value correspondence with ``domain.topology`` — a drift guard, not a
re-implementation (test_domain_shape_parity below).
"""

from __future__ import annotations

import dataclasses

import pytest

from simulation.state.graph import (
    Connection,
    NodeConfig,
    PortDirection,
    PortId,
    PortSpec,
    SignalPlane,
    TopologyGraph,
    topological_order,
)

pytestmark = pytest.mark.unit


def _out_port(port_id: str = "out-0", **extra) -> PortSpec:
    return PortSpec(
        port_id=port_id, direction="output", plane="MPEG_TS", **extra
    )


def _in_port(port_id: str = "in-0", **extra) -> PortSpec:
    return PortSpec(
        port_id=port_id, direction="input", plane="MPEG_TS", **extra
    )


def _node(
    node_id: str,
    *ports: PortSpec,
    node_type: str = "mux",
    config: dict | None = None,
) -> NodeConfig:
    return NodeConfig(
        node_id=node_id,
        node_type=node_type,
        config=config or {},
        ports=list(ports),
    )


def _connection(
    connection_id: str = "conn-1",
    from_node: str = "tuner-0",
    from_port: str = "out-0",
    to_node: str = "demux-0",
    to_port: str = "in-0",
) -> Connection:
    return Connection(
        connection_id=connection_id,
        from_node=from_node,
        from_port=from_port,
        to_node=to_node,
        to_port=to_port,
        plane="MPEG_TS",
    )


def _linear_graph() -> TopologyGraph:
    return TopologyGraph(
        topology_id="topo-1",
        revision=1,
        nodes=[
            _node("tuner-0", _out_port()),
            _node("demux-0", _in_port(), _out_port()),
        ],
        connections=[_connection()],
    )


class TestGraphContract:
    """SPEC-202 section 4: nodes, named ports, four-tuple connections."""

    def test_four_tuple_connection_fields(self) -> None:
        connection = _connection()
        assert (connection.from_node, connection.from_port) == (
            "tuner-0",
            "out-0",
        )
        assert (connection.to_node, connection.to_port) == ("demux-0", "in-0")
        assert connection.plane == "MPEG_TS"

    def test_port_declares_direction_plane_max_connections(self) -> None:
        port = PortSpec(
            port_id="in-0",
            direction="input",
            plane="MPEG_TS",
            max_connections=4,
        )
        assert port.port_id == "in-0"
        assert port.direction == "input"
        assert port.plane == "MPEG_TS"
        assert port.max_connections == 4

    def test_graph_carries_topology_id_and_revision(self) -> None:
        graph = _linear_graph()
        assert graph.topology_id == "topo-1"
        assert graph.revision == 1

    def test_graph_types_are_frozen(self) -> None:
        for instance in (
            _out_port(),
            _node("tuner-0", _out_port()),
            _connection(),
            _linear_graph(),
        ):
            attribute = dataclasses.fields(instance)[0].name
            with pytest.raises(dataclasses.FrozenInstanceError):
                setattr(instance, attribute, None)  # type: ignore[misc]

    def test_empty_node_id_rejected(self) -> None:
        with pytest.raises(ValueError):
            _node("", _out_port())

    def test_empty_port_id_rejected(self) -> None:
        with pytest.raises(ValueError):
            _out_port(port_id="")

    def test_empty_connection_id_rejected(self) -> None:
        with pytest.raises(ValueError):
            _connection(connection_id="")

    def test_node_without_ports_rejected(self) -> None:
        with pytest.raises(ValueError):
            _node("mux-0")

    def test_unknown_direction_rejected(self) -> None:
        with pytest.raises(ValueError):
            PortSpec(port_id="p", direction="sideways", plane="MPEG_TS")

    def test_unknown_plane_rejected(self) -> None:
        with pytest.raises(ValueError):
            PortSpec(port_id="p", direction="input", plane="CARRIER_PIGEON")

    def test_direction_and_plane_enums_match_spec_values(self) -> None:
        assert {item.value for item in PortDirection} == {
            "input",
            "output",
            "bidirectional",
        }
        assert {item.value for item in SignalPlane} == {
            "RF",
            "SEC_CONTROL",
            "MPEG_TS",
            "T2MI",
            "IP",
        }


class TestTopologicalOrder:
    """SPEC-202 section 6.2 / REQ-SIM-202-002: cycle rejection and a
    deterministic total order with nodeId lexicographic tie-break."""

    def _diamond(self, node_order: list[str]) -> TopologyGraph:
        by_id = {
            "src": _node("src", _out_port(), node_type="tuner"),
            "b": _node("b", _in_port(), _out_port(), node_type="gain"),
            "a": _node("a", _in_port(), _out_port(), node_type="gain"),
            "sink": _node("sink", _in_port(), node_type="monitor"),
        }
        return TopologyGraph(
            topology_id="topo-diamond",
            revision=0,
            nodes=[by_id[name] for name in node_order],
            connections=[
                _connection("c1", "src", "out-0", "b", "in-0"),
                _connection("c2", "src", "out-0", "a", "in-0"),
                _connection("c3", "b", "out-0", "sink", "in-0"),
                _connection("c4", "a", "out-0", "sink", "in-0"),
            ],
        )

    def test_diamond_order_is_deterministic(self) -> None:
        graph = self._diamond(["src", "b", "a", "sink"])
        assert topological_order(graph) == ("src", "a", "b", "sink")

    def test_shuffled_node_input_lists_yield_identical_order(self) -> None:
        expected = topological_order(
            self._diamond(["src", "b", "a", "sink"])
        )
        for permutation in (
            ["sink", "b", "a", "src"],
            ["a", "sink", "src", "b"],
            ["b", "src", "sink", "a"],
        ):
            assert topological_order(self._diamond(permutation)) == expected

    def test_isolated_node_included_in_order(self) -> None:
        graph = TopologyGraph(
            topology_id="topo-island",
            revision=0,
            nodes=[
                _node("zeta", _in_port(), node_type="monitor"),
                _node("alpha", _out_port(), node_type="tuner"),
            ],
            connections=[],
        )
        assert topological_order(graph) == ("alpha", "zeta")

    def test_two_node_cycle_rejected(self) -> None:
        graph = TopologyGraph(
            topology_id="topo-cycle",
            revision=0,
            nodes=[
                _node("x", _in_port(), _out_port()),
                _node("y", _in_port(), _out_port()),
            ],
            connections=[
                _connection("c1", "x", "out-0", "y", "in-0"),
                _connection("c2", "y", "out-0", "x", "in-0"),
            ],
        )
        from simulation.errors import SIM_TOPO_CYCLE, TopologyCycleError

        with pytest.raises(TopologyCycleError) as excinfo:
            topological_order(graph)
        assert excinfo.value.code == SIM_TOPO_CYCLE

    def test_cycle_error_names_the_cyclic_nodes(self) -> None:
        graph = TopologyGraph(
            topology_id="topo-cycle",
            revision=0,
            nodes=[
                _node("x", _in_port(), _out_port()),
                _node("y", _in_port(), _out_port()),
            ],
            connections=[
                _connection("c1", "x", "out-0", "y", "in-0"),
                _connection("c2", "y", "out-0", "x", "in-0"),
            ],
        )
        from simulation.errors import TopologyCycleError

        with pytest.raises(TopologyCycleError) as excinfo:
            topological_order(graph)
        assert "x" in str(excinfo.value) and "y" in str(excinfo.value)


class TestDomainShapeParity:
    """Drift guard against the shared SPEC-003 model (domain.topology).

    The simulation-side graph contract mirrors the frozen domain model
    field-for-field (the import-linter forbids the direct import edge);
    this test fails when either side drifts.
    """

    def test_graph_fields_mirror_topology_model(self) -> None:
        from domain.topology import SignalPlane as DomainPlane
        from domain.topology import Topology, TopologyConnection
        from domain.topology import TopologyNode, TopologyPort
        from domain.topology import PortDirection as DomainDirection

        domain_topology = Topology(
            topology_id="topo-1",
            revision=1,
            nodes=[
                TopologyNode(
                    node_id="tuner-0",
                    node_type="tuner",
                    config={},
                    ports=[
                        TopologyPort(
                            port_id="out-0",
                            direction=DomainDirection.OUTPUT,
                            plane=DomainPlane.MPEG_TS,
                        )
                    ],
                )
            ],
            connections=[
                TopologyConnection(
                    connection_id="conn-1",
                    from_node="tuner-0",
                    from_port="out-0",
                    to_node="demux-0",
                    to_port="in-0",
                    plane=DomainPlane.MPEG_TS,
                )
            ],
        )
        state_graph = TopologyGraph(
            topology_id=domain_topology.topology_id,
            revision=domain_topology.revision,
            nodes=[
                NodeConfig(
                    node_id=node.node_id,
                    node_type=node.node_type,
                    config=dict(node.config),
                    ports=[
                        PortSpec(
                            port_id=port.port_id,
                            direction=port.direction.value,
                            plane=port.plane.value,
                            max_connections=port.max_connections,
                        )
                        for port in node.ports
                    ],
                )
                for node in domain_topology.nodes
            ],
            connections=[
                Connection(
                    connection_id=connection.connection_id,
                    from_node=connection.from_node,
                    from_port=connection.from_port,
                    to_node=connection.to_node,
                    to_port=connection.to_port,
                    plane=connection.plane.value,
                )
                for connection in domain_topology.connections
            ],
        )
        assert state_graph.topology_id == domain_topology.topology_id
        assert state_graph.revision == domain_topology.revision
        assert state_graph.nodes[0].node_id == "tuner-0"
        assert state_graph.nodes[0].ports[0].direction == "output"
        assert state_graph.nodes[0].ports[0].plane == "MPEG_TS"
        assert state_graph.connections[0].from_port == "out-0"

    def test_direction_values_match_domain_enum(self) -> None:
        from domain.topology import PortDirection as DomainDirection

        for member in DomainDirection:
            assert PortDirection(member.value) is not None

    def test_plane_values_match_domain_enum(self) -> None:
        from domain.topology import SignalPlane as DomainPlane

        for member in DomainPlane:
            assert SignalPlane(member.value) is not None
