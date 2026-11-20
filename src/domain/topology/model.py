"""SPEC-003 section 2.1 topology configuration model.

User-designed nodes, ports and connections. This is a *configuration* model,
not runtime state (SPEC-003 section 2.1). Models define data only: plane /
direction / capacity / protocol compatibility of a link is checked by the
backend validator (SPEC-202 section 5), never here.

Field naming follows the platform-wide snake_case convention (SPEC-301
envelope, SPEC-202 port-level link tuple); SPEC-003's TS illustration is
camelCase, mapped 1:1.
"""

from enum import Enum
from typing import Annotated, Any, Optional

from pydantic import StringConstraints

from domain._base import DomainModel

#: A topology-stable *semantic* slug identifying a node inside its topology
#: (e.g. ``demux-0``). The documented exception to opaque machine-entity IDs
#: (ADR-0006 decision 3); node identity is configuration identity.
NodeId = Annotated[str, StringConstraints(min_length=1)]

#: Identifier of a port within its node. SPEC-202 section 4 speaks of named
#: ports ("named ports"); the spec pins no opaque/semantic ruling beyond
#: topology-internal identity, so this is a neutral non-empty string.
PortId = Annotated[str, StringConstraints(min_length=1)]

#: Identifier of a connection inside the topology. SPEC-003 pins no ID-strategy
#: ruling for connections (ADR-0006 decision 3 lists only machine entities);
#: neutral non-empty string, no opaque/semantic claim.
ConnectionId = Annotated[str, StringConstraints(min_length=1)]


class SignalPlane(str, Enum):
    """The five signal planes (SPEC-003 section 2.1, ADR-0005 decision 5).

    Extension slots stay in the enum; the enabled set is Phase-scoped
    (see ``MVP_ENABLED_PLANES``: MPEG_TS since MVP, T2MI since Phase 2,
    RF and SEC_CONTROL since Phase 3).
    Whether two ports may be linked is a validator concern, not a model
    invariant.
    """

    RF = "RF"
    SEC_CONTROL = "SEC_CONTROL"
    MPEG_TS = "MPEG_TS"
    T2MI = "T2MI"
    IP = "IP"


class PortDirection(str, Enum):
    """Port direction (SPEC-003 section 2.1)."""

    INPUT = "input"
    OUTPUT = "output"
    BIDIRECTIONAL = "bidirectional"


#: Planes actually enabled for links (SPEC-003 §Phase3, ticket #160:
#: the enabled set expands from {MPEG_TS, T2MI} — Phase 2, ticket #121 /
#: ADR-0010 §3 — to {MPEG_TS, T2MI, RF, SEC_CONTROL} for the Phase 3
#: RF/SEC sandbox, ADR-0012; ``IP`` stays disabled for Phase 4, per
#: ADR-0002 / ADR-0005 decision 5 "links on non-enabled planes are
#: forbidden").  Data constant for the validator to consume; per ruling
#: A10 it is NOT wired into the validator as an enforcement check
#: (Phase 2 precedent).  The frontend mirror
#: (``frontend/src/features/topologies/nodeTypes.ts``) is updated by
#: ticket #169.
MVP_ENABLED_PLANES = frozenset(
    {
        SignalPlane.MPEG_TS,
        SignalPlane.T2MI,
        SignalPlane.RF,
        SignalPlane.SEC_CONTROL,
    }
)


class TopologyPort(DomainModel):
    """A named port of a node (SPEC-003 section 2.1 ``TopologyPort``)."""

    port_id: PortId
    direction: PortDirection
    plane: SignalPlane
    protocol: Optional[str] = None
    max_connections: Optional[int] = None


class TopologyNode(DomainModel):
    """A designed node (SPEC-003 section 2.1 ``TopologyNode``).

    ``node_id`` is the topology-internal semantic slug (ADR-0006 decision 3).
    ``node_type`` stays a plain string: the NodeType registry and per-type
    config schemas are module-spec scope (SPEC-003 section 6).
    """

    node_id: NodeId
    node_type: str
    config: dict[str, Any]
    ports: list[TopologyPort]


class TopologyConnection(DomainModel):
    """A port-level link (SPEC-003 section 2.1, SPEC-202 section 4).

    The approved MVP baseline flattens the link into the four-tuple
    ``from_node/from_port -> to_node/to_port`` (ADR-0005 decision 5: node-pair
    links are invalid — multi-port components like Mux cannot be expressed
    unambiguously with two-tuples).
    """

    connection_id: ConnectionId
    from_node: NodeId
    from_port: PortId
    to_node: NodeId
    to_port: PortId
    plane: SignalPlane


class Topology(DomainModel):
    """The whole topology configuration (SPEC-003 section 2.1 ``Topology``).

    ``revision`` versions the configuration; validators must reject links on
    non-enabled planes (see ``MVP_ENABLED_PLANES``) and incompatible
    plane/direction/capacity/protocol pairs — deliberately not modelled here.
    """

    topology_id: str
    revision: int
    nodes: list[TopologyNode]
    connections: list[TopologyConnection]


__all__ = [
    "ConnectionId",
    "MVP_ENABLED_PLANES",
    "NodeId",
    "PortDirection",
    "PortId",
    "SignalPlane",
    "Topology",
    "TopologyConnection",
    "TopologyNode",
    "TopologyPort",
]
