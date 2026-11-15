"""SPEC-202 section 5 — topology validation rules (ticket #40).

``validate_topology`` is a **non-mutating, repeatable, pure** operation: it
never modifies the graph and reports every violation as a path-addressed
:class:`TopologyViolation` (located to node / port / connection), instead of
raising. All rejection codes carry the stable ``SIM_TOPO_*`` prefix
(SPEC-202 section 8); the code literals themselves live in
:mod:`simulation.errors` next to the SPEC-201 codes (module-owned
convention).

Rule set (SPEC-202 section 5, REQ-SIM-202-001):

- duplicate IDs (nodeId / portId / connectionId)
- endpoint missing (connection references nonexistent node/port)
- illegal direction (output->output, input->input — precisely: a from-side
  port without output capability or a to-side port without input capability)
- media incompatible (plane mismatch between the link and its endpoints)
- cardinality (maxConnections exceeded on a port)
- self loop (from == to, same node and same port)
- cycle (MVP rejects — a DAG is required for deterministic evaluation)

Isolated nodes (no connections) are legal and produce no violation; they
report as idle at evaluation time (SPEC-202 section 5).

Output discipline: the violation tuple is deterministically ordered by
``(path, code)`` so the same graph always yields the same report regardless
of the input list order (determinism, REQ-SIM-202-003 discipline).
"""

from __future__ import annotations

from dataclasses import dataclass

from simulation.errors import (
    SIM_TOPO_CARDINALITY,
    SIM_TOPO_DIRECTION_INVALID,
    SIM_TOPO_DUPLICATE_ID,
    SIM_TOPO_ENDPOINT_MISSING,
    SIM_TOPO_MEDIA_INCOMPATIBLE,
    SIM_TOPO_CYCLE,
    SIM_TOPO_SELF_LOOP,
    TopologyCycleError,
)
from simulation.state.graph import (
    PortDirection,
    TopologyGraph,
    topological_order,
)

__all__ = [
    "SIM_TOPO_CARDINALITY",
    "SIM_TOPO_CYCLE",
    "SIM_TOPO_DIRECTION_INVALID",
    "SIM_TOPO_DUPLICATE_ID",
    "SIM_TOPO_ENDPOINT_MISSING",
    "SIM_TOPO_MEDIA_INCOMPATIBLE",
    "SIM_TOPO_SELF_LOOP",
    "TopologyViolation",
    "validate_topology",
]

#: Directions a *from*-side port may have for a link to be legal.
_FROM_CAPABLE = frozenset({PortDirection.OUTPUT, PortDirection.BIDIRECTIONAL})

#: Directions a *to*-side port may have for a link to be legal.
_TO_CAPABLE = frozenset({PortDirection.INPUT, PortDirection.BIDIRECTIONAL})


@dataclass(frozen=True)
class TopologyViolation:
    """One path-addressed rejection (SPEC-202 section 5).

    ``path`` addresses the offending element, e.g. ``nodes[demux-0]``,
    ``nodes[mux-0].ports[in-0]``, ``connections[conn-1]`` or the whole
    graph (``topology``, cycle rule).
    """

    code: str
    path: str
    message: str


def validate_topology(graph: TopologyGraph) -> tuple:
    """Validate ``graph`` against every SPEC-202 section 5 rule.

    Returns a deterministically ordered tuple of
    :class:`TopologyViolation` (empty when the topology is legal). Never
    raises on rule violations — including cycles — so callers can present
    the full report; use :func:`simulation.state.graph.topological_order`
    when an exception-shaped cycle signal is preferred.
    """
    violations: list[TopologyViolation] = []
    violations.extend(_duplicate_id_violations(graph))
    violations.extend(_connection_violations(graph))
    violations.extend(_cardinality_violations(graph))
    violations.extend(_cycle_violations(graph))
    return tuple(sorted(violations, key=lambda item: (item.path, item.code)))


# -- rule implementations -----------------------------------------------------


def _duplicate_id_violations(graph: TopologyGraph) -> list:
    violations = []
    node_id_counts: dict[str, int] = {}
    for node in graph.nodes:
        node_id_counts[node.node_id] = node_id_counts.get(node.node_id, 0) + 1
    for node_id, count in sorted(node_id_counts.items()):
        if count > 1:
            violations.append(
                TopologyViolation(
                    code=SIM_TOPO_DUPLICATE_ID,
                    path=f"nodes[{node_id}]",
                    message=f"node_id {node_id!r} declared {count} times",
                )
            )
        seen_ports: set[str] = set()
        node = graph.node(node_id)
        if node is None:
            continue  # duplicated id: port check runs on first occurrence
        for port in node.ports:
            if port.port_id in seen_ports:
                violations.append(
                    TopologyViolation(
                        code=SIM_TOPO_DUPLICATE_ID,
                        path=f"nodes[{node_id}].ports[{port.port_id}]",
                        message=(
                            f"port_id {port.port_id!r} declared more than "
                            f"once on node {node_id!r}"
                        ),
                    )
                )
            seen_ports.add(port.port_id)
    connection_id_counts: dict[str, int] = {}
    for connection in graph.connections:
        connection_id_counts[connection.connection_id] = (
            connection_id_counts.get(connection.connection_id, 0) + 1
        )
    for connection_id, count in sorted(connection_id_counts.items()):
        if count > 1:
            violations.append(
                TopologyViolation(
                    code=SIM_TOPO_DUPLICATE_ID,
                    path=f"connections[{connection_id}]",
                    message=(
                        f"connection_id {connection_id!r} declared {count} "
                        "times"
                    ),
                )
            )
    return violations


def _connection_violations(graph: TopologyGraph) -> list:
    """Endpoint / direction / media / self-loop rules per connection."""
    violations: list[TopologyViolation] = []
    reported_connection_ids: set[str] = set()
    for connection in graph.connections:
        if connection.connection_id in reported_connection_ids:
            continue  # duplicate-id rule already covers this connection
        reported_connection_ids.add(connection.connection_id)
        path = f"connections[{connection.connection_id}]"
        from_port = _endpoint_port(graph, connection.from_node, connection.from_port)
        to_port = _endpoint_port(graph, connection.to_node, connection.to_port)
        for endpoint_node, _endpoint_port_id in (
            (connection.from_node, connection.from_port),
            (connection.to_node, connection.to_port),
        ):
            if graph.node(endpoint_node) is None:
                violations.append(
                    TopologyViolation(
                        code=SIM_TOPO_ENDPOINT_MISSING,
                        path=path,
                        message=f"node {endpoint_node!r} does not exist",
                    )
                )
        for owner_id, port_id, port_spec in (
            (connection.from_node, connection.from_port, from_port),
            (connection.to_node, connection.to_port, to_port),
        ):
            if graph.node(owner_id) is not None and port_spec is None:
                violations.append(
                    TopologyViolation(
                        code=SIM_TOPO_ENDPOINT_MISSING,
                        path=path,
                        message=(
                            f"port {port_id!r} does not exist on node "
                            f"{owner_id!r}"
                        ),
                    )
                )
        if (
            connection.from_node == connection.to_node
            and connection.from_port == connection.to_port
        ):
            violations.append(
                TopologyViolation(
                    code=SIM_TOPO_SELF_LOOP,
                    path=path,
                    message=(
                        f"self loop on node {connection.from_node!r} port "
                        f"{connection.from_port!r}"
                    ),
                )
            )
        if from_port is not None and to_port is not None:
            if (
                from_port.direction not in _FROM_CAPABLE
                or to_port.direction not in _TO_CAPABLE
            ):
                violations.append(
                    TopologyViolation(
                        code=SIM_TOPO_DIRECTION_INVALID,
                        path=path,
                        message=(
                            f"illegal direction pairing "
                            f"{from_port.direction.value} -> "
                            f"{to_port.direction.value}"
                        ),
                    )
                )
            if (
                connection.plane != from_port.plane
                or connection.plane != to_port.plane
            ):
                violations.append(
                    TopologyViolation(
                        code=SIM_TOPO_MEDIA_INCOMPATIBLE,
                        path=path,
                        message=(
                            f"plane {connection.plane.value} does not match "
                            f"endpoint planes {from_port.plane.value}/"
                            f"{to_port.plane.value}"
                        ),
                    )
                )
    return violations


def _endpoint_port(graph: TopologyGraph, node_id: str, port_id: str):
    node = graph.node(node_id)
    if node is None:
        return None
    return node.port(port_id)


def _cardinality_violations(graph: TopologyGraph) -> list:
    violations: list[TopologyViolation] = []
    endpoint_counts: dict[tuple[str, str], int] = {}
    seen_connection_ids: set[str] = set()
    for connection in graph.connections:
        if connection.connection_id in seen_connection_ids:
            continue  # do not double-count duplicated connections
        seen_connection_ids.add(connection.connection_id)
        for node_id, port_id in (
            (connection.from_node, connection.from_port),
            (connection.to_node, connection.to_port),
        ):
            key = (node_id, port_id)
            endpoint_counts[key] = endpoint_counts.get(key, 0) + 1
    for (node_id, port_id), count in sorted(endpoint_counts.items()):
        node = graph.node(node_id)
        if node is None:
            continue
        port = node.port(port_id)
        if port is None or port.max_connections is None:
            continue
        if count > port.max_connections:
            violations.append(
                TopologyViolation(
                    code=SIM_TOPO_CARDINALITY,
                    path=f"nodes[{node_id}].ports[{port_id}]",
                    message=(
                        f"port carries {count} connections, above "
                        f"max_connections={port.max_connections}"
                    ),
                )
            )
    return violations


def _cycle_violations(graph: TopologyGraph) -> list:
    try:
        topological_order(graph)
    except TopologyCycleError as exc:
        return [
            TopologyViolation(
                code=SIM_TOPO_CYCLE,
                path="topology",
                message=str(exc).split(": ", 1)[-1],
            )
        ]
    return []
