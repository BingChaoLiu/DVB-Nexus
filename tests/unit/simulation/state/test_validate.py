"""SPEC-202 section 5 — topology validation rule tests (ticket #40).

Seam: ``simulation.state.validate.validate_topology`` — the pure,
non-mutating, repeatable rule surface. Every SPEC-202 section 5 rule gets
at least one minimal counter-example with a path-location assertion
(REQ-SIM-202-001); expected codes are literals from SPEC-202 section 8.

#160 appends the SPEC-003 §Phase3 ``SIM_TOPO_UB_*`` family (four rules:
ub_slot table hit / config-period conflict / protocol width / protocol
mixing) plus the RF/SEC maxConnections 1:N shared-coax confirmation and
the initial validator-vocabulary drift lock (ruling A1 — the validator
reads config dicts without importing ``domain.topology``; tests may import
both sides).
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
    DISEQC_SWITCH_NODE_TYPE,
    LNB_NODE_TYPE,
    MAX_UB_SLOT_BY_PROTOCOL,
    PROTOCOL_CONFIG_KEY,
    SCR_CONFIG_KEY,
    SIM_TOPO_CARDINALITY,
    SIM_TOPO_CYCLE,
    SIM_TOPO_DIRECTION_INVALID,
    SIM_TOPO_DUPLICATE_ID,
    SIM_TOPO_ENDPOINT_MISSING,
    SIM_TOPO_MEDIA_INCOMPATIBLE,
    SIM_TOPO_SELF_LOOP,
    SIM_TOPO_UB_PROTOCOL_MIXED,
    SIM_TOPO_UB_SLOT_CONFLICT,
    SIM_TOPO_UB_SLOT_OUT_OF_RANGE,
    SIM_TOPO_UB_SLOT_UNMATCHED,
    TUNER_NODE_CONFIG_KEY,
    TUNER_NODE_TYPE,
    UB_ASSIGNMENTS_CONFIG_KEY,
    UB_SLOT_CONFIG_KEY,
    UNICABLE_PROTOCOLS,
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


# --- Phase 3 (SPEC-003 §Phase3 / SPEC-623, ticket #160) --------------------------


def _sec_port(
    port_id: str,
    direction: str,
    max_connections: int | None = None,
) -> PortSpec:
    return PortSpec(
        port_id=port_id,
        direction=direction,
        plane="SEC_CONTROL",
        max_connections=max_connections,
    )


def _lnb_node(node_id: str = "lnb-0", config: dict | None = None) -> NodeConfig:
    return NodeConfig(
        node_id=node_id,
        node_type=LNB_NODE_TYPE,
        config=config if config is not None else {},
        ports=[_sec_port("coax_out", "output", max_connections=2)],
    )


def _tuner_node(node_id: str, config: dict | None = None) -> NodeConfig:
    return NodeConfig(
        node_id=node_id,
        node_type=TUNER_NODE_TYPE,
        config=config if config is not None else {},
        ports=[_sec_port("rf_in", "input", max_connections=1)],
    )


def _switch_node(node_id: str = "sw-0") -> NodeConfig:
    return NodeConfig(
        node_id=node_id,
        node_type=DISEQC_SWITCH_NODE_TYPE,
        config={"power_pass": "on"},
        ports=[
            _sec_port("coax_in", "input", max_connections=1),
            _sec_port("coax_out", "output", max_connections=4),
        ],
    )


def _coax(
    connection_id: str,
    from_node: str,
    to_node: str,
    to_port: str = "rf_in",
) -> Connection:
    return Connection(
        connection_id=connection_id,
        from_node=from_node,
        from_port="coax_out",
        to_node=to_node,
        to_port=to_port,
        plane="SEC_CONTROL",
    )


def _ub_entry(tuner_node: str, ub_slot: int, **overrides) -> dict:
    entry = {
        "tuner_node": tuner_node,
        "ub_slot": ub_slot,
        "ub_center_freq_mhz": 1210 if ub_slot == 0 else 1420,
        "position": "A" if ub_slot == 0 else "B",
        "ub_bandwidth_mhz": 46,
    }
    entry.update(overrides)
    return entry


def _scr_lnb_config(protocol: str = "EN50494", entries: list | None = None) -> dict:
    return {
        "lnb_kind": "universal",
        "lo_frequencies": {"low_khz": 9750, "high_khz": 10600},
        "scr": {
            "protocol": protocol,
            "ub_assignments": entries
            if entries is not None
            else [_ub_entry("tuner-a", 0), _ub_entry("tuner-b", 1)],
        },
    }


def _tuner_config(ub_slot: int | None = None) -> dict:
    config: dict = {
        "tuning_request": {"frequency_khz": 11_804_000, "polarization": "vertical"}
    }
    if ub_slot is not None:
        config[UB_SLOT_CONFIG_KEY] = ub_slot
    return config


def _ub_graph(
    lnb_configs: list[dict] | None = None,
    tuner_configs: dict[str, dict] | None = None,
    switch: bool = False,
) -> TopologyGraph:
    """lnb-0 (coax_out) -> [sw-0 ->] tuner-a/tuner-b (rf_in)."""
    nodes: list[NodeConfig] = [
        _lnb_node(config=lnb_configs[0] if lnb_configs else None)
    ]
    connections: list[Connection] = []
    lnb_out_target = "sw-0" if switch else "tuner-a"
    if switch:
        nodes.append(_switch_node())
        connections.append(_coax("c-lnb", "lnb-0", "sw-0", to_port="coax_in"))
        connections.append(
            Connection(
                connection_id="c-sw-a",
                from_node="sw-0",
                from_port="coax_out",
                to_node="tuner-a",
                to_port="rf_in",
                plane="SEC_CONTROL",
            )
        )
        connections.append(
            Connection(
                connection_id="c-sw-b",
                from_node="sw-0",
                from_port="coax_out",
                to_node="tuner-b",
                to_port="rf_in",
                plane="SEC_CONTROL",
            )
        )
    else:
        connections.append(_coax("c-a", "lnb-0", "tuner-a"))
        connections.append(_coax("c-b", "lnb-0", "tuner-b"))
    tuner_configs = tuner_configs if tuner_configs is not None else {}
    nodes.append(
        _tuner_node("tuner-a", tuner_configs.get("tuner-a"))
    )
    nodes.append(
        _tuner_node("tuner-b", tuner_configs.get("tuner-b"))
    )
    return TopologyGraph(
        topology_id="topo-ub",
        revision=0,
        nodes=nodes,
        connections=connections,
    )


class TestPhase3BaselineIsAlwaysLegal:
    """SPEC-003 §Phase3 layering: the baseline topology is always legal;
    misassignment is fault-plan territory only (validator reports
    config-period conflicts, never invents runtime faults)."""

    def test_valid_scr_topology_no_violations(self) -> None:
        graph = _ub_graph(
            lnb_configs=[_scr_lnb_config()],
            tuner_configs={
                "tuner-a": _tuner_config(ub_slot=0),
                "tuner-b": _tuner_config(ub_slot=1),
            },
        )
        assert validate_topology(graph) == ()

    def test_no_scr_direct_topology_no_violations(self) -> None:
        # SC-11 shape: lnb without scr, tuners without ub_slot.
        graph = _ub_graph(
            tuner_configs={
                "tuner-a": _tuner_config(),
                "tuner-b": _tuner_config(),
            }
        )
        assert validate_topology(graph) == ()

    def test_scr_reachable_through_the_switch(self) -> None:
        graph = _ub_graph(
            lnb_configs=[_scr_lnb_config()],
            tuner_configs={
                "tuner-a": _tuner_config(ub_slot=0),
                "tuner-b": _tuner_config(ub_slot=1),
            },
            switch=True,
        )
        assert validate_topology(graph) == ()

    def test_ub_violations_are_repeatable_and_non_mutating(self) -> None:
        graph = _ub_graph(
            lnb_configs=[_scr_lnb_config(entries=[_ub_entry("tuner-a", 0)])],
            tuner_configs={"tuner-a": _tuner_config(ub_slot=1)},
        )
        nodes_before = list(graph.nodes)
        first = validate_topology(graph)
        second = validate_topology(graph)
        assert first == second
        assert list(graph.nodes) == nodes_before


class TestUbSlotMatchRule:
    """Rule 1 — tuner.ub_slot must hit a ``ub_assignments`` entry of a
    path-reachable SCR (SPEC-003 §Phase3 rule 1)."""

    def test_unmatched_slot_reported_on_the_tuner(self) -> None:
        graph = _ub_graph(
            lnb_configs=[_scr_lnb_config(entries=[_ub_entry("tuner-a", 0)])],
            tuner_configs={
                "tuner-a": _tuner_config(ub_slot=0),
                "tuner-b": _tuner_config(ub_slot=0),
            },
        )
        violations = validate_topology(graph)
        assert _codes(violations) == [SIM_TOPO_UB_SLOT_UNMATCHED]
        assert violations[0].path == "nodes[tuner-b]"

    def test_ub_slot_without_any_reachable_scr_reported(self) -> None:
        graph = _ub_graph(
            lnb_configs=[_scr_lnb_config(entries=[])],
            tuner_configs={
                "tuner-a": _tuner_config(ub_slot=0),
                "tuner-b": _tuner_config(),
            },
        )
        violations = validate_topology(graph)
        assert _codes(violations) == [SIM_TOPO_UB_SLOT_UNMATCHED]
        assert violations[0].path == "nodes[tuner-a]"

    def test_null_ub_slot_never_participates(self) -> None:
        graph = _ub_graph(
            lnb_configs=[_scr_lnb_config(entries=[_ub_entry("tuner-a", 0)])],
            tuner_configs={
                "tuner-a": _tuner_config(ub_slot=0),
                "tuner-b": _tuner_config(),
            },
        )
        assert validate_topology(graph) == ()


class TestUbConflictRule:
    """Rule 2 — two tuners claiming the same UB slot in one SCR table is
    a config-period static conflict (SPEC-623 §6 ``ub_conflicts``)."""

    def test_same_slot_two_tuners_reported_on_the_lnb(self) -> None:
        graph = _ub_graph(
            lnb_configs=[
                _scr_lnb_config(
                    entries=[_ub_entry("tuner-a", 0), _ub_entry("tuner-b", 0)]
                )
            ],
            tuner_configs={
                "tuner-a": _tuner_config(ub_slot=0),
                "tuner-b": _tuner_config(ub_slot=0),
            },
        )
        violations = validate_topology(graph)
        assert _codes(violations) == [SIM_TOPO_UB_SLOT_CONFLICT]
        assert violations[0].path == "nodes[lnb-0]"

    def test_distinct_slots_are_clean(self) -> None:
        graph = _ub_graph(
            lnb_configs=[_scr_lnb_config()],
            tuner_configs={
                "tuner-a": _tuner_config(ub_slot=0),
                "tuner-b": _tuner_config(ub_slot=1),
            },
        )
        assert validate_topology(graph) == ()


class TestUbWidthRule:
    """Rule 3 — ub_slot beyond the protocol bit width is rejected
    (EN 50494 > 7 / EN 50607 > 31, SPEC-623 §2.1/§8)."""

    def test_table_entry_beyond_en50494_width_reported(self) -> None:
        # Only the SCR table claims slot 8 (the tuner config carries no
        # ub_slot) — the violation addresses the lnb hosting the table.
        graph = _ub_graph(
            lnb_configs=[
                _scr_lnb_config(entries=[_ub_entry("tuner-a", 8)])
            ],
            tuner_configs={"tuner-a": _tuner_config()},
        )
        violations = validate_topology(graph)
        assert _codes(violations) == [SIM_TOPO_UB_SLOT_OUT_OF_RANGE]
        assert violations[0].path == "nodes[lnb-0]"

    def test_tuner_slot_beyond_reachable_protocol_reported(self) -> None:
        # A tuner config slot beyond the reachable protocol's width fires
        # the width rule on the tuner node; the empty table additionally
        # makes the slot unmatched (rule 1 co-occurrence).
        graph = _ub_graph(
            lnb_configs=[_scr_lnb_config(entries=[])],
            tuner_configs={
                "tuner-a": _tuner_config(ub_slot=8),
                "tuner-b": _tuner_config(),
            },
        )
        violations = validate_topology(graph)
        assert set(_codes(violations)) == {
            SIM_TOPO_UB_SLOT_UNMATCHED,
            SIM_TOPO_UB_SLOT_OUT_OF_RANGE,
        }
        assert (
            "nodes[tuner-a]"
            in [v.path for v in violations
                if v.code == SIM_TOPO_UB_SLOT_OUT_OF_RANGE]
        )

    def test_en50607_width_31_accepted(self) -> None:
        graph = _ub_graph(
            lnb_configs=[
                _scr_lnb_config(
                    protocol="EN50607",
                    entries=[_ub_entry("tuner-a", 31, position=0)],
                )
            ],
            tuner_configs={
                "tuner-a": _tuner_config(ub_slot=31),
                "tuner-b": _tuner_config(),
            },
        )
        assert validate_topology(graph) == ()

    def test_en50494_width_boundary_seven_accepted(self) -> None:
        graph = _ub_graph(
            lnb_configs=[
                _scr_lnb_config(entries=[_ub_entry("tuner-a", 7)])
            ],
            tuner_configs={
                "tuner-a": _tuner_config(ub_slot=7),
                "tuner-b": _tuner_config(),
            },
        )
        assert validate_topology(graph) == ()


class TestUbProtocolMixedRule:
    """Rule 4 — one tuner's reachable SCR set must not mix EN 50494 and
    EN 50607 (SPEC-623 §7: the two UB spaces are independent).

    Ticket-authorised refinement: ``scr.protocol`` is a single-valued
    field, so "same lnb mixes two protocols" is not expressible in the
    data model; the structural equivalent enforced here is "the set of
    SCRs reachable from one tuner carries inconsistent protocols →
    reject" (pinned by these tests, declared in the #160 report).
    """

    def test_two_reachable_scrs_with_mixed_protocols_reported(self) -> None:
        lnb_a = _lnb_node(
            "lnb-a",
            _scr_lnb_config(
                protocol="EN50494", entries=[_ub_entry("tuner-x", 0)]
            ),
        )
        lnb_b = _lnb_node(
            "lnb-b",
            _scr_lnb_config(
                protocol="EN50607",
                entries=[_ub_entry("tuner-x", 1, position=1)],
            ),
        )
        # The graph contract leaves max_connections open by default
        # (PortSpec.max_connections=None is unbounded); the registry
        # template pins tuner rf_in=1 for REST-facing topologies, while
        # rule 4 guards the state-engine graph face where dual SCR
        # reachability stays constructible (defense in depth).
        tuner = NodeConfig(
            node_id="tuner-x",
            node_type=TUNER_NODE_TYPE,
            config=_tuner_config(ub_slot=0),
            ports=[_sec_port("rf_in", "input")],
        )
        graph = TopologyGraph(
            topology_id="topo-mixed",
            revision=0,
            nodes=[lnb_a, lnb_b, tuner],
            connections=[
                _coax("c-a", "lnb-a", "tuner-x"),
                _coax("c-b", "lnb-b", "tuner-x"),
            ],
        )
        violations = validate_topology(graph)
        assert _codes(violations) == [SIM_TOPO_UB_PROTOCOL_MIXED]
        assert violations[0].path == "nodes[tuner-x]"

    def test_single_protocol_reachable_is_clean(self) -> None:
        graph = _ub_graph(
            lnb_configs=[_scr_lnb_config(protocol="EN50607",
                                         entries=[_ub_entry("tuner-a", 0,
                                                            position=0)])],
            tuner_configs={
                "tuner-a": _tuner_config(ub_slot=0),
                "tuner-b": _tuner_config(),
            },
        )
        assert validate_topology(graph) == ()


class TestPhase3SharedCoaxSemantics:
    """maxConnections 1:N shared-coax confirmation on the RF/SEC planes
    (SPEC-003 §Phase3: mechanism zero-extension — the existing per-port
    cardinality carries the LNB/SCR fan-out; connection wire shape
    unchanged; no new plane rule)."""

    def test_lnb_coax_out_fans_out_to_two_tuners_without_violation(self) -> None:
        graph = _ub_graph()
        assert validate_topology(graph) == ()

    def test_third_tuner_breaks_the_lnb_fanout_budget(self) -> None:
        graph = _ub_graph()
        graph.nodes.append(_tuner_node("tuner-c"))
        graph.connections.append(_coax("c-c", "lnb-0", "tuner-c"))
        violations = validate_topology(graph)
        assert _codes(violations) == [SIM_TOPO_CARDINALITY]
        assert violations[0].path == "nodes[lnb-0].ports[coax_out]"

    def test_switch_upstream_dc_path_is_single(self) -> None:
        # SPEC-622 §7 "at most one DC path": a second lnb feed into the
        # switch's upstream port breaches the registered cardinality.
        graph = _ub_graph(switch=True)
        graph.nodes.append(_lnb_node("lnb-1"))
        graph.connections.append(
            _coax("c-lnb-1", "lnb-1", "sw-0", to_port="coax_in")
        )
        violations = validate_topology(graph)
        assert _codes(violations) == [SIM_TOPO_CARDINALITY]
        assert violations[0].path == "nodes[sw-0].ports[coax_in]"

    def test_rf_plane_links_stay_media_legal(self) -> None:
        # The media rule generalises to the newly enabled planes with zero
        # new code: plane-consistency applies to SEC_CONTROL links.
        graph = _ub_graph()
        bad = Connection(
            connection_id="c-bad",
            from_node="lnb-0",
            from_port="coax_out",
            to_node="tuner-a",
            to_port="rf_in",
            plane="RF",
        )
        graph.connections.append(bad)
        violations = validate_topology(graph)
        assert SIM_TOPO_MEDIA_INCOMPATIBLE in _codes(violations)


class TestPhase3VocabularyDriftLock:
    """Initial validator-vocabulary drift lock (ruling A1).

    The validator reads node ``config`` dicts and must not import
    ``domain.topology`` (importlinter contract 8), so the node-type
    strings, config key names and protocol vocabulary live as module
    constants here.  These tests pin the mirrored faces against the
    domain registry/DTO field names — tests sit outside the linter's
    root packages and may import both sides.  #161 extends this lock to
    its evaluator-side parse tables (per A1 the DTO-side counterpart is
    #161's to add).
    """

    def test_ub_slot_width_table(self) -> None:
        assert MAX_UB_SLOT_BY_PROTOCOL == {"EN50494": 7, "EN50607": 31}
        assert set(MAX_UB_SLOT_BY_PROTOCOL) == set(UNICABLE_PROTOCOLS)

    def test_protocol_vocabulary_matches_scr_dto(self) -> None:
        from domain.topology.node_types import ScrConfigDTO

        annotation = ScrConfigDTO.model_fields[PROTOCOL_CONFIG_KEY].annotation
        assert set(UNICABLE_PROTOCOLS) == set(annotation.__args__)

    def test_config_key_names_match_dto_fields(self) -> None:
        from domain.topology.node_types import (
            LnbConfigDTO,
            ScrConfigDTO,
            TunerConfigDTO,
            UbAssignmentDTO,
        )

        assert SCR_CONFIG_KEY in LnbConfigDTO.model_fields
        assert UB_SLOT_CONFIG_KEY in TunerConfigDTO.model_fields
        assert UB_ASSIGNMENTS_CONFIG_KEY in ScrConfigDTO.model_fields
        assert TUNER_NODE_CONFIG_KEY in UbAssignmentDTO.model_fields

    def test_node_type_strings_match_phase3_registry(self) -> None:
        from domain.topology.node_types import PHASE3_NODE_TYPES

        assert {spec.node_type for spec in PHASE3_NODE_TYPES} == {
            LNB_NODE_TYPE,
            TUNER_NODE_TYPE,
            DISEQC_SWITCH_NODE_TYPE,
        }

    def test_lnb_drive_keys_are_first_class_dto_fields(self) -> None:
        # Ruling A20 (ticket #171): the five lnb evaluation-time drive keys
        # are declared optional ``LnbConfigDTO`` fields — the
        # scenario-calibration / TONE_RESIDUE-transform face joins the
        # schema authority (registration face; the evaluator-side
        # vocabulary lock lives in test_evaluator_vocab_drift_lock.py).
        from domain.topology.node_types import LnbConfigDTO

        for key in (
            "voltage",
            "tone_commanded",
            "tone_actual",
            "tone_composite",
            "short_circuit_state",
        ):
            assert key in LnbConfigDTO.model_fields
