"""Topology domain model tests (SPEC-003 section 2.1 + ADR-0005 decision 5).

Seam: public construction/validation surface of ``domain.topology`` (valid
round-trip; invalid value -> ValidationError at the expected field location)
and enum closed-set membership. Expected values are literals copied from
SPEC-003 / SPEC-202 text, an independent source of truth.
"""

import pytest
from pydantic import ValidationError

from domain.topology import (
    MVP_ENABLED_PLANES,
    PortDirection,
    SignalPlane,
    Topology,
    TopologyConnection,
    TopologyNode,
    TopologyPort,
)


def _port(port_id: str, direction: str, plane: str, **extra) -> TopologyPort:
    return TopologyPort(port_id=port_id, direction=direction, plane=plane, **extra)


def _node(node_id: str, ports: list, node_type: str = "mux", **extra) -> TopologyNode:
    return TopologyNode(node_id=node_id, node_type=node_type, config={}, ports=ports, **extra)


def _connection(connection_id: str = "conn-1") -> TopologyConnection:
    return TopologyConnection(
        connection_id=connection_id,
        from_node="tuner-0",
        from_port="out-0",
        to_node="demux-0",
        to_port="in-0",
        plane=SignalPlane.MPEG_TS,
    )


class TestEnumClosedSets:
    def test_signal_plane_has_exactly_the_five_spec_planes(self):
        assert {member.value for member in SignalPlane} == {
            "RF",
            "SEC_CONTROL",
            "MPEG_TS",
            "T2MI",
            "IP",
        }

    def test_port_direction_has_exactly_the_three_spec_directions(self):
        assert {member.value for member in PortDirection} == {
            "input",
            "output",
            "bidirectional",
        }

    def test_phase3_enables_mpeg_ts_t2mi_rf_and_sec_control_planes(self):
        # SPEC-003 §Phase3 (ticket #160): the enabled set expands
        # {MPEG_TS, T2MI} → {MPEG_TS, T2MI, RF, SEC_CONTROL}; IP stays
        # disabled (Phase 4).  ADR-0005 decision 5 remains the
        # validator-side rule (non-enabled planes are forbidden); per
        # ruling A10 the enabled set is a data constant, not wired into
        # the validator.
        assert MVP_ENABLED_PLANES == frozenset(
            {
                SignalPlane.MPEG_TS,
                SignalPlane.T2MI,
                SignalPlane.RF,
                SignalPlane.SEC_CONTROL,
            }
        )


class TestTopologyPort:
    def test_valid_port_with_optionals_omitted(self):
        port = _port("out-0", "output", "MPEG_TS")
        assert port.port_id == "out-0"
        assert port.direction is PortDirection.OUTPUT
        assert port.plane is SignalPlane.MPEG_TS
        assert port.protocol is None
        assert port.max_connections is None

    def test_valid_port_round_trip(self):
        port = _port("in-0", "bidirectional", "IP", protocol="udp", max_connections=4)
        dumped = port.model_dump()
        assert dumped == {
            "port_id": "in-0",
            "direction": "bidirectional",
            "plane": "IP",
            "protocol": "udp",
            "max_connections": 4,
        }
        assert TopologyPort.model_validate(dumped) == port

    def test_unknown_plane_rejected_at_plane_field(self):
        with pytest.raises(ValidationError) as excinfo:
            _port("out-0", "output", "WIFI")
        assert excinfo.value.errors()[0]["loc"] == ("plane",)

    def test_unknown_direction_rejected_at_direction_field(self):
        with pytest.raises(ValidationError) as excinfo:
            _port("out-0", "sideways", "MPEG_TS")
        assert excinfo.value.errors()[0]["loc"] == ("direction",)

    def test_empty_port_id_rejected(self):
        with pytest.raises(ValidationError) as excinfo:
            _port("", "output", "MPEG_TS")
        assert excinfo.value.errors()[0]["loc"] == ("port_id",)

    def test_extra_field_rejected(self):
        with pytest.raises(ValidationError) as excinfo:
            _port("out-0", "output", "MPEG_TS", bandwidth="8MHz")
        assert excinfo.value.errors()[0]["loc"] == ("bandwidth",)

    def test_frozen_model_rejects_assignment(self):
        port = _port("out-0", "output", "MPEG_TS")
        with pytest.raises(ValidationError):
            port.plane = SignalPlane.RF


class TestTopologyNode:
    def test_valid_node_with_semantic_slug_node_id(self):
        node = _node("demux-0", [_port("in-0", "input", "MPEG_TS")])
        assert node.node_id == "demux-0"
        assert node.node_type == "mux"
        assert node.config == {}
        assert len(node.ports) == 1

    def test_node_round_trip(self):
        node = _node(
            "demux-0",
            [_port("in-0", "input", "MPEG_TS"), _port("out-0", "output", "MPEG_TS")],
            node_type="demux",
        )
        assert TopologyNode.model_validate(node.model_dump()) == node

    def test_missing_required_field_reports_location(self):
        with pytest.raises(ValidationError) as excinfo:
            TopologyNode(node_id="demux-0", node_type="demux", config={})
        error_types = {error["loc"]: error["type"] for error in excinfo.value.errors()}
        assert error_types[("ports",)] == "missing"

    def test_unknown_node_type_string_accepted_registry_is_module_spec_scope(self):
        # SPEC-003 section 6: the NodeType registry is deferred to module specs;
        # the domain model only carries the string.
        node = _node("frobnicator-7", [], node_type="not_yet_registered")
        assert node.node_type == "not_yet_registered"


class TestTopologyConnection:
    def test_connection_is_the_port_level_four_tuple(self):
        connection = _connection()
        # SPEC-202 section 4 / ADR-0005 decision 5: a link must identify
        # from_node/from_port -> to_node/to_port; node-to-node links are invalid.
        dumped = connection.model_dump()
        assert set(dumped) == {
            "connection_id",
            "from_node",
            "from_port",
            "to_node",
            "to_port",
            "plane",
        }
        assert dumped["from_node"] == "tuner-0"
        assert dumped["from_port"] == "out-0"
        assert dumped["to_node"] == "demux-0"
        assert dumped["to_port"] == "in-0"

    def test_connection_round_trip(self):
        connection = _connection("conn-9")
        assert TopologyConnection.model_validate(connection.model_dump()) == connection

    def test_missing_from_port_reports_location(self):
        with pytest.raises(ValidationError) as excinfo:
            TopologyConnection(
                connection_id="conn-1",
                from_node="tuner-0",
                to_node="demux-0",
                to_port="in-0",
                plane="MPEG_TS",
            )
        error_locs = {error["loc"] for error in excinfo.value.errors()}
        assert ("from_port",) in error_locs


class TestTopologyAggregate:
    def test_valid_empty_topology_constructs(self):
        topology = Topology(topology_id="topo-1", revision=1, nodes=[], connections=[])
        assert topology.nodes == []
        assert topology.connections == []

    def test_valid_topology_round_trip(self):
        topology = Topology(
            topology_id="topo-1",
            revision=3,
            nodes=[
                _node("tuner-0", [_port("out-0", "output", "MPEG_TS")], node_type="tuner"),
                _node("demux-0", [_port("in-0", "input", "MPEG_TS")], node_type="demux"),
            ],
            connections=[_connection()],
        )
        assert Topology.model_validate(topology.model_dump()) == topology

    def test_topology_is_frozen(self):
        topology = Topology(topology_id="topo-1", revision=1, nodes=[], connections=[])
        with pytest.raises(ValidationError):
            topology.revision = 2

    def test_missing_connections_reports_location(self):
        with pytest.raises(ValidationError) as excinfo:
            Topology(topology_id="topo-1", revision=1, nodes=[])
        error_locs = {error["loc"] for error in excinfo.value.errors()}
        assert ("connections",) in error_locs

    def test_extra_field_rejected(self):
        with pytest.raises(ValidationError) as excinfo:
            Topology(topology_id="topo-1", revision=1, nodes=[], connections=[], name="x")
        assert excinfo.value.errors()[0]["loc"] == ("name",)
