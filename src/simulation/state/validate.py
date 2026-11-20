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

Phase 3 UB rules (SPEC-003 §Phase3, ticket #160 — the ``SIM_TOPO_UB_*``
family; SPEC-623 §7/§8 layering: config-period violations only, the
baseline topology is always legal, misassignment is fault-plan territory):

- UB slot unmatched (tuner ``ub_slot`` hits no ``ub_assignments`` entry of
  any path-reachable SCR)
- UB slot conflict (two tuners claim the same UB slot in one SCR table)
- UB slot out of range (beyond the protocol bit width: EN 50494 > 7 /
  EN 50607 > 31)
- UB protocol mixed (one tuner's reachable SCR set mixes EN 50494 and
  EN 50607)

The UB rules read node ``config`` dicts directly and never import
``domain.topology`` (importlinter contract 8) — the mirrored node-type
strings, config key names and protocol vocabulary are module constants
below, drift-locked against the domain registry from the tests layer
(ruling A1; #162 reuses the width/protocol constants).

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
    SIM_TOPO_UB_PROTOCOL_MIXED,
    SIM_TOPO_UB_SLOT_CONFLICT,
    SIM_TOPO_UB_SLOT_OUT_OF_RANGE,
    SIM_TOPO_UB_SLOT_UNMATCHED,
    TopologyCycleError,
)
from simulation.state.graph import (
    PortDirection,
    TopologyGraph,
    topological_order,
)

__all__ = [
    "DISEQC_SWITCH_NODE_TYPE",
    "LNB_NODE_TYPE",
    "MAX_UB_SLOT_BY_PROTOCOL",
    "PROTOCOL_CONFIG_KEY",
    "SCR_CONFIG_KEY",
    "SIM_TOPO_CARDINALITY",
    "SIM_TOPO_CYCLE",
    "SIM_TOPO_DIRECTION_INVALID",
    "SIM_TOPO_DUPLICATE_ID",
    "SIM_TOPO_ENDPOINT_MISSING",
    "SIM_TOPO_MEDIA_INCOMPATIBLE",
    "SIM_TOPO_SELF_LOOP",
    "SIM_TOPO_UB_PROTOCOL_MIXED",
    "SIM_TOPO_UB_SLOT_CONFLICT",
    "SIM_TOPO_UB_SLOT_OUT_OF_RANGE",
    "SIM_TOPO_UB_SLOT_UNMATCHED",
    "TUNER_NODE_CONFIG_KEY",
    "TUNER_NODE_TYPE",
    "UB_ASSIGNMENTS_CONFIG_KEY",
    "UB_SLOT_CONFIG_KEY",
    "UNICABLE_PROTOCOL_EN50494",
    "UNICABLE_PROTOCOL_EN50607",
    "UNICABLE_PROTOCOLS",
    "TopologyViolation",
    "validate_topology",
]

#: Directions a *from*-side port may have for a link to be legal.
_FROM_CAPABLE = frozenset({PortDirection.OUTPUT, PortDirection.BIDIRECTIONAL})

#: Directions a *to*-side port may have for a link to be legal.
_TO_CAPABLE = frozenset({PortDirection.INPUT, PortDirection.BIDIRECTIONAL})


# -- Phase 3 Unicable vocabulary (SPEC-623 §2.1/§5; mirrored from
#    domain.topology.node_types PHASE3_NODE_TYPES / DTO field names —
#    simulation must not import domain.topology, ruling A1 drift lock) ----

#: RF/SEC node-type wire strings (SPEC-003 §Phase3 registry trio).
LNB_NODE_TYPE = "lnb"
TUNER_NODE_TYPE = "tuner"
DISEQC_SWITCH_NODE_TYPE = "diseqc_switch"

#: ``config`` dict key names mirrored from the domain config DTOs.
SCR_CONFIG_KEY = "scr"
UB_ASSIGNMENTS_CONFIG_KEY = "ub_assignments"
PROTOCOL_CONFIG_KEY = "protocol"
UB_SLOT_CONFIG_KEY = "ub_slot"
TUNER_NODE_CONFIG_KEY = "tuner_node"

#: The two Unicable protocol variants (SPEC-623 §2.1).
UNICABLE_PROTOCOL_EN50494 = "EN50494"
UNICABLE_PROTOCOL_EN50607 = "EN50607"
UNICABLE_PROTOCOLS: tuple[str, ...] = (
    UNICABLE_PROTOCOL_EN50494,
    UNICABLE_PROTOCOL_EN50607,
)

#: Highest legal ``ub_slot`` per protocol (EN 50494: 3-bit → 8 slots
#: 0–7; EN 50607: 5-bit → 32 slots 0–31).  #162 reuses this table.
MAX_UB_SLOT_BY_PROTOCOL: dict[str, int] = {
    UNICABLE_PROTOCOL_EN50494: 7,
    UNICABLE_PROTOCOL_EN50607: 31,
}


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
    violations.extend(_ub_violations(graph))
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


# -- Phase 3 UB rules (SPEC-003 §Phase3, ticket #160) ---------------------------


def _is_int(value: object) -> bool:
    """int but not bool (booleans sneak in through JSON wire dicts)."""
    return isinstance(value, int) and not isinstance(value, bool)


def _upstream_node_ids(graph: TopologyGraph, node_id: str) -> frozenset:
    """All nodes feeding ``node_id`` transitively (against connection
    direction).  Cycle-safe via a visited set; deterministic because the
    result is a set (order never observed)."""
    seen: set[str] = set()
    stack = [node_id]
    while stack:
        current = stack.pop()
        for connection in graph.connections:
            if connection.to_node == current:
                feeder = connection.from_node
                if feeder not in seen:
                    seen.add(feeder)
                    stack.append(feeder)
    return frozenset(seen)


def _scr_tables(graph: TopologyGraph) -> dict:
    """``lnb`` nodes carrying an ``scr`` config sub-segment, as a
    deterministic ``{lnb_id: (protocol, entries)}`` mapping.  Entries are
    the raw ``ub_assignments`` dicts; malformed shapes are skipped here
    (the config-schema layer owns type validation — these rules only
    judge well-formed keys)."""
    tables: dict[str, tuple[object, list]] = {}
    for node in sorted(graph.nodes, key=lambda item: item.node_id):
        if node.node_type != LNB_NODE_TYPE:
            continue
        scr = node.config.get(SCR_CONFIG_KEY)
        if not isinstance(scr, dict):
            continue
        protocol = scr.get(PROTOCOL_CONFIG_KEY)
        entries = scr.get(UB_ASSIGNMENTS_CONFIG_KEY)
        if protocol not in UNICABLE_PROTOCOLS or not isinstance(entries, list):
            continue
        tables[node.node_id] = (protocol, entries)
    return tables


def _ub_violations(graph: TopologyGraph) -> list:
    """The four ``SIM_TOPO_UB_*`` rules (SPEC-003 §Phase3).

    Pure dict-level traversal: no DTO imports, no I/O.  Config-period
    only — the baseline topology is always legal absent these static
    conflicts; runtime misassignment is fault-plan territory (SPEC-623
    §7 layering).
    """
    violations: list[TopologyViolation] = []
    scr_tables = _scr_tables(graph)

    tuners = [
        node
        for node in sorted(graph.nodes, key=lambda item: item.node_id)
        if node.node_type == TUNER_NODE_TYPE
    ]
    reachable_scrs = {
        tuner.node_id: {
            lnb_id: scr_tables[lnb_id]
            for lnb_id in sorted(
                _upstream_node_ids(graph, tuner.node_id) & scr_tables.keys()
            )
        }
        for tuner in tuners
    }

    # Rule 1 — tuner.ub_slot must hit a path-reachable SCR table entry.
    for tuner in tuners:
        ub_slot = tuner.config.get(UB_SLOT_CONFIG_KEY)
        if not _is_int(ub_slot):
            continue  # null / malformed: no UB participation claim here
        tables = reachable_scrs[tuner.node_id]
        matched = any(
            isinstance(entry, dict)
            and entry.get(TUNER_NODE_CONFIG_KEY) == tuner.node_id
            and entry.get(UB_SLOT_CONFIG_KEY) == ub_slot
            for _lnb_id, (_protocol, entries) in tables.items()
            for entry in entries
        )
        if not matched:
            violations.append(
                TopologyViolation(
                    code=SIM_TOPO_UB_SLOT_UNMATCHED,
                    path=f"nodes[{tuner.node_id}]",
                    message=(
                        f"tuner ub_slot {ub_slot} matches no ub_assignments "
                        "entry of any path-reachable SCR (SPEC-003 §Phase3 "
                        "rule 1)"
                    ),
                )
            )

    # Rule 2 — two tuners claiming the same UB slot in one SCR table.
    for lnb_id, (_protocol, entries) in scr_tables.items():
        claims: dict[int, set[str]] = {}
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            slot = entry.get(UB_SLOT_CONFIG_KEY)
            tuner_node = entry.get(TUNER_NODE_CONFIG_KEY)
            if _is_int(slot) and isinstance(tuner_node, str):
                claims.setdefault(slot, set()).add(tuner_node)
        for slot in sorted(claims):
            if len(claims[slot]) > 1:
                claimants = ", ".join(sorted(claims[slot]))
                violations.append(
                    TopologyViolation(
                        code=SIM_TOPO_UB_SLOT_CONFLICT,
                        path=f"nodes[{lnb_id}]",
                        message=(
                            f"ub_assignments slot {slot} claimed by tuners "
                            f"{claimants} — config-period static conflict "
                            "(SPEC-003 §Phase3 rule 2)"
                        ),
                    )
                )

    # Rule 3 — ub_slot beyond the protocol bit width (table entries and
    # tuner configs).
    for lnb_id, (protocol, entries) in scr_tables.items():
        width = MAX_UB_SLOT_BY_PROTOCOL[protocol]
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            slot = entry.get(UB_SLOT_CONFIG_KEY)
            if _is_int(slot) and slot > width:
                tuner_node = entry.get(TUNER_NODE_CONFIG_KEY)
                violations.append(
                    TopologyViolation(
                        code=SIM_TOPO_UB_SLOT_OUT_OF_RANGE,
                        path=f"nodes[{lnb_id}]",
                        message=(
                            f"ub_assignments entry for tuner "
                            f"{tuner_node!r} uses ub_slot {slot}, beyond "
                            f"the {protocol} width {width} (SPEC-003 "
                            "§Phase3 rule 3)"
                        ),
                    )
                )
    for tuner in tuners:
        ub_slot = tuner.config.get(UB_SLOT_CONFIG_KEY)
        if not _is_int(ub_slot):
            continue
        offending = sorted(
            protocol
            for protocol, _entries in reachable_scrs[tuner.node_id].values()
            if ub_slot > MAX_UB_SLOT_BY_PROTOCOL[protocol]
        )
        if offending:
            limits = ", ".join(
                f"{protocol} width {MAX_UB_SLOT_BY_PROTOCOL[protocol]}"
                for protocol in offending
            )
            violations.append(
                TopologyViolation(
                    code=SIM_TOPO_UB_SLOT_OUT_OF_RANGE,
                    path=f"nodes[{tuner.node_id}]",
                    message=(
                        f"tuner ub_slot {ub_slot} exceeds {limits} "
                        "(SPEC-003 §Phase3 rule 3)"
                    ),
                )
            )

    # Rule 4 — one tuner's reachable SCR set must not mix the two
    # protocols (ticket-authorised refinement: ``scr.protocol`` is a
    # single-valued field, so the SPEC-623 §7 "same lnb mixes two
    # protocols" prepare-reject is enforced as its structural equivalent
    # "reachable SCR protocol set inconsistent → reject"; pinned by
    # tests, declared in the #160 report).
    for tuner in tuners:
        protocols = {
            protocol
            for protocol, _entries in reachable_scrs[tuner.node_id].values()
        }
        if len(protocols) > 1:
            mixed = ", ".join(sorted(protocols))
            violations.append(
                TopologyViolation(
                    code=SIM_TOPO_UB_PROTOCOL_MIXED,
                    path=f"nodes[{tuner.node_id}]",
                    message=(
                        f"tuner reaches SCR protocols {{{mixed}}} — the "
                        "EN 50494 and EN 50607 UB spaces are independent "
                        "(SPEC-003 §Phase3 rule 4)"
                    ),
                )
            )

    return violations
