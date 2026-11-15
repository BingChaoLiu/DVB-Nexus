"""Local builders for ticket #41 runtime tests.

Test-package-local helpers (NOT ``tests/_support`` — that surface belongs to
the SPEC-505 ticket and is not this ticket's to touch). Deterministic by
construction: fixed slugs, no wall clock, no randomness.
"""

from __future__ import annotations

from simulation.clock import SimulationClockConfig
from simulation.state import (
    Connection,
    NodeConfig,
    PortSpec,
    SignalPlane,
    TopologyGraph,
)


def single_node_graph(topology_id: str = "topo-1", revision: int = 0):
    """A minimal valid graph: one node with an input and an output port."""
    node = NodeConfig(
        node_id="gen-0",
        node_type="generator",
        config={"bitrate_bps": 1_000_000},
        ports=[
            PortSpec(port_id="out", direction="output", plane="MPEG_TS"),
            PortSpec(port_id="ctl", direction="input", plane="SEC_CONTROL"),
        ],
    )
    return TopologyGraph(
        topology_id=topology_id, revision=revision, nodes=[node], connections=[]
    )


def cyclic_graph(topology_id: str = "topo-cycle", revision: int = 0):
    """A graph with a cycle — validate_topology reports SIM_TOPO_CYCLE."""
    node_a = NodeConfig(
        node_id="a",
        node_type="generator",
        config={},
        ports=[
            PortSpec(port_id="out", direction="output", plane="MPEG_TS"),
            PortSpec(port_id="in", direction="input", plane="MPEG_TS"),
        ],
    )
    node_b = NodeConfig(
        node_id="b",
        node_type="mux",
        config={},
        ports=[
            PortSpec(port_id="out", direction="output", plane="MPEG_TS"),
            PortSpec(port_id="in", direction="input", plane="MPEG_TS"),
        ],
    )
    links = [
        Connection(
            connection_id="c1",
            from_node="a",
            from_port="out",
            to_node="b",
            to_port="in",
            plane=SignalPlane.MPEG_TS,
        ),
        Connection(
            connection_id="c2",
            from_node="b",
            from_port="out",
            to_node="a",
            to_port="in",
            plane=SignalPlane.MPEG_TS,
        ),
    ]
    return TopologyGraph(
        topology_id=topology_id,
        revision=revision,
        nodes=[node_a, node_b],
        connections=links,
    )


def session_spec(
    topology=None,
    *,
    session_id="session-1",
    seed=7,
    deterministic=True,
    clock_config=None,
):
    """A SimulationSessionSpec with deterministic defaults."""
    from simulation.runtime import SimulationSessionSpec

    if clock_config is None:
        clock_config = SimulationClockConfig(
            mode="deterministic" if deterministic else "realtime"
        )
    return SimulationSessionSpec(
        session_id=session_id,
        topology=topology if topology is not None else single_node_graph(),
        seed=seed,
        deterministic=deterministic,
        clock_config=clock_config,
    )
