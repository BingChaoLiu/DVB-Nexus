"""Topology domain: node/port/link model and validation.

MVP scope is model + validation; the causal evaluator is deferred (ADR-0005
decision 4). Links are port-level: ``from_node/from_port`` to
``to_node/to_port`` (SPEC-202).

Public API: SPEC-003 section 2.1 topology configuration models. Data only —
link compatibility validation belongs to the topology validator (SPEC-202
section 5).
"""

from domain.topology.model import (
    ConnectionId,
    MVP_ENABLED_PLANES,
    NodeId,
    PortDirection,
    PortId,
    SignalPlane,
    Topology,
    TopologyConnection,
    TopologyNode,
    TopologyPort,
)

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
