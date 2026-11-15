"""SPEC-202 section 4 — State Engine graph contract (ticket #40).

Nodes carry a stable *semantic* ``node_id`` (topology-internal slug,
ADR-0006 decision 3), a type, config and **named ports**; connections are
the port-level four-tuple ``from_node/from_port -> to_node/to_port``
(ADR-0005 decision 5: node-to-node links are invalid — multi-port
components like Mux cannot be expressed unambiguously with two-tuples).

Interface freeze (SIM-E / #44 depends on this surface): the types below are
frozen dataclasses; field names follow the platform-wide snake_case
convention and mirror the shared SPEC-003 domain model (``domain.topology``)
field-for-field. The direct import edge ``simulation -> domain.topology`` is
forbidden by the import-linter contract (ADR-0005 D4-4 + M3 ruling), so the
contract is defined here; 1:1 shape/value correspondence is enforced by
``tests/unit/simulation/state/test_graph.py`` (drift guard).

Purity: data only — no IO, no wall clock, no randomness (SPEC-202 section
3). Link compatibility (direction/plane/capacity) is NOT checked here; it
is validator concern (:mod:`simulation.state.validate`, SPEC-202 section 5).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from simulation.errors import TopologyCycleError

#: A topology-stable semantic slug identifying a node (e.g. ``demux-0``).
#: Same vocabulary as ``domain.topology.NodeId`` (non-empty string).
NodeId = str

#: Identifier of a port within its node (non-empty string).
PortId = str

#: Identifier of a connection inside the topology (non-empty string).
ConnectionId = str


class PortDirection(str, Enum):
    """Port direction (SPEC-202 section 4 / SPEC-003 section 2.1).

    Values mirror ``domain.topology.PortDirection`` 1:1 (drift-guarded by
    test).
    """

    INPUT = "input"
    OUTPUT = "output"
    BIDIRECTIONAL = "bidirectional"


class SignalPlane(str, Enum):
    """Signal plane (SPEC-003 section 2.1, ADR-0005 decision 5).

    Values mirror ``domain.topology.SignalPlane`` 1:1 (drift-guarded by
    test). MVP links only enable ``MPEG_TS``; the full five-plane set is
    kept so the media-compatibility rule survives scope extension.
    """

    RF = "RF"
    SEC_CONTROL = "SEC_CONTROL"
    MPEG_TS = "MPEG_TS"
    T2MI = "T2MI"
    IP = "IP"


_VALID_DIRECTIONS = frozenset(member.value for member in PortDirection)
_VALID_PLANES = frozenset(member.value for member in SignalPlane)


def _require_non_empty_str(value: object, field_name: str) -> str:
    """Type/shape gate: identifiers must be non-empty strings."""
    if not isinstance(value, str):
        raise TypeError(
            f"{field_name} must be str, got {type(value).__name__}"
        )
    if not value:
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


@dataclass(frozen=True)
class PortSpec:
    """A named port of a node (SPEC-202 section 4).

    ``direction`` / ``plane`` are accepted as plain vocabulary strings and
    normalized to the enums above; unknown values are rejected at
    construction (programming errors, not topology violations).
    """

    port_id: PortId
    direction: PortDirection
    plane: SignalPlane
    max_connections: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "port_id", _require_non_empty_str(self.port_id, "port_id")
        )
        for name, vocabulary in (
            ("direction", _VALID_DIRECTIONS),
            ("plane", _VALID_PLANES),
        ):
            raw = getattr(self, name)
            if not isinstance(raw, str):
                raise TypeError(
                    f"{name} must be str, got {type(raw).__name__}"
                )
            if raw not in vocabulary:
                raise ValueError(
                    f"{name} must be one of {sorted(vocabulary)}, got {raw!r}"
                )
            normalized = PortDirection(raw) if name == "direction" else SignalPlane(raw)
            object.__setattr__(self, name, normalized)
        if self.max_connections is not None:
            if not isinstance(self.max_connections, int) or isinstance(
                self.max_connections, bool
            ):
                raise TypeError(
                    "max_connections must be int or None, got "
                    f"{type(self.max_connections).__name__}"
                )
            if self.max_connections < 1:
                raise ValueError(
                    "max_connections must be >= 1, got "
                    f"{self.max_connections}"
                )


@dataclass(frozen=True)
class NodeConfig:
    """A node of the state-engine graph (SPEC-202 section 4/6.1).

    ``node_type`` stays a plain string: the NodeType registry and per-type
    config schemas are module-spec scope (SPEC-003 section 6), not this
    engine's. ``config`` is an opaque mapping owned by the node semantics.
    """

    node_id: NodeId
    node_type: str
    config: dict
    ports: list

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "node_id", _require_non_empty_str(self.node_id, "node_id")
        )
        if not isinstance(self.node_type, str) or not self.node_type:
            raise ValueError("node_type must be a non-empty string")
        if not self.ports:
            raise ValueError(
                f"node {self.node_id!r} must declare at least one port"
            )
        for port in self.ports:
            if not isinstance(port, PortSpec):
                raise TypeError(
                    f"node {self.node_id!r} ports must be PortSpec, got "
                    f"{type(port).__name__}"
                )
        # NOTE: duplicate port IDs are NOT rejected here — validation
        # (SPEC-202 section 5) must stay a non-mutating, repeatable
        # operation that *reports* ``SIM_TOPO_DUPLICATE_ID`` on possibly
        # invalid graphs instead of crashing at construction.

    def port(self, port_id: PortId) -> PortSpec | None:
        """The named port with ``port_id`` (None when absent)."""
        for port in self.ports:
            if port.port_id == port_id:
                return port
        return None


@dataclass(frozen=True)
class Connection:
    """A port-level link (SPEC-202 section 4 four-tuple contract)."""

    connection_id: ConnectionId
    from_node: NodeId
    from_port: PortId
    to_node: NodeId
    to_port: PortId
    plane: SignalPlane

    def __post_init__(self) -> None:
        for name in (
            "connection_id",
            "from_node",
            "from_port",
            "to_node",
            "to_port",
        ):
            object.__setattr__(
                self, name, _require_non_empty_str(getattr(self, name), name)
            )
        if not isinstance(self.plane, str):
            raise TypeError(
                f"plane must be str, got {type(self.plane).__name__}"
            )
        if self.plane not in _VALID_PLANES:
            raise ValueError(
                f"plane must be one of {sorted(_VALID_PLANES)}, "
                f"got {self.plane!r}"
            )
        object.__setattr__(self, "plane", SignalPlane(self.plane))


@dataclass(frozen=True)
class TopologyGraph:
    """The whole graph contract (SPEC-202 section 4).

    Construction checks identity uniqueness that is structural (node IDs,
    per-node port IDs, connection IDs); the full SPEC-202 section 5 rule
    set (endpoints, directions, planes, cardinality, self-loops, cycles)
    belongs to :mod:`simulation.state.validate` and returns path-addressed
    violations instead of raising.
    """

    topology_id: str
    revision: int
    nodes: list
    connections: list

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "topology_id",
            _require_non_empty_str(self.topology_id, "topology_id"),
        )
        if not isinstance(self.revision, int) or isinstance(
            self.revision, bool
        ):
            raise TypeError(
                f"revision must be int, got {type(self.revision).__name__}"
            )
        if self.revision < 0:
            raise ValueError(f"revision must be >= 0, got {self.revision}")
        node_ids: set[str] = set()
        for node in self.nodes:
            if not isinstance(node, NodeConfig):
                raise TypeError(
                    f"nodes must be NodeConfig, got {type(node).__name__}"
                )
            node_ids.add(node.node_id)
        for connection in self.connections:
            if not isinstance(connection, Connection):
                raise TypeError(
                    "connections must be Connection, got "
                    f"{type(connection).__name__}"
                )
        # NOTE: duplicate node/connection IDs are reported by
        # ``simulation.state.validate`` (SPEC-202 section 5 path-addressed
        # violations), never raised here — see NodeConfig note above.

    def node(self, node_id: NodeId) -> NodeConfig | None:
        """The node with ``node_id`` (None when absent)."""
        for node in self.nodes:
            if node.node_id == node_id:
                return node
        return None

    def connections_from(self, node_id: NodeId) -> list:
        """Connections whose ``from_node`` is ``node_id`` (in list order)."""
        return [c for c in self.connections if c.from_node == node_id]

    def connections_to(self, node_id: NodeId) -> list:
        """Connections whose ``to_node`` is ``node_id`` (in list order)."""
        return [c for c in self.connections if c.to_node == node_id]


def _dependencies(graph: TopologyGraph) -> dict:
    """Node -> set of upstream node IDs that feed it (edge exists only
    between distinct nodes; same-node port pairs cannot form a dependency
    and are the validator's self-loop case)."""
    dependencies: dict[str, set[str]] = {node.node_id: set() for node in graph.nodes}
    for connection in graph.connections:
        if connection.from_node == connection.to_node:
            continue
        dependencies.setdefault(connection.from_node, set())
        dependencies.setdefault(connection.to_node, set())
        dependencies[connection.to_node].add(connection.from_node)
    return dependencies


def topological_order(graph: TopologyGraph) -> tuple:
    """Deterministic topological order of ``graph`` (SPEC-202 section 6.2).

    Kahn's algorithm; among the always-ready frontier the **smallest
    nodeId in lexicographic order** is emitted next, so the total order is
    unique for a given node set and edge set regardless of the input node
    list order (determinism, REQ-SIM-202-002).

    Raises :class:`TopologyCycleError` (``SIM_TOPO_CYCLE``) when the graph
    is not a DAG — a cyclic topology cannot be evaluated deterministically
    (SPEC-202 section 5: MVP rejects cycles).
    """
    dependencies = _dependencies(graph)
    emitted: list[str] = []
    remaining = dict(dependencies)
    while remaining:
        ready = sorted(
            node_id for node_id, upstreams in remaining.items() if not upstreams
        )
        if not ready:
            cyclic = sorted(remaining)
            raise TopologyCycleError(
                "topology contains a cycle among nodes "
                f"{cyclic}; a DAG is required for deterministic evaluation "
                "(SPEC-202 section 5)"
            )
        chosen = ready[0]
        emitted.append(chosen)
        del remaining[chosen]
        for upstreams in remaining.values():
            upstreams.discard(chosen)
    return tuple(emitted)


__all__ = [
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
]
