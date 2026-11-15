"""Pure programmatic builders for raw scenario documents (SIM-F #45).

Test-data discipline (tests/README.md §5): these builders are the
*programmatic construction* source for scenario JSON fixtures — plain JSON
text shapes only, no TS bytes, no hand-spliced binary literals. The shapes
mirror the canonical wire format of the shipped example
``docs/spec/DVB-Sandbox-Spec-v0.4-Complete/examples/scenario-cc-discontinuity.json``
(issue #12 authority): camelCase topology vocabulary (``nodeId`` /
``nodeType`` / ``portId`` / ``maxConnections``; nested ``from``/``to`` link
objects), ``schema_version`` as the number ``1``.

Every builder returns a *fresh* dict each call so tests can mutate one copy
without leaking state into another.
"""

from __future__ import annotations

import copy
from typing import Any

SCENARIO_ID = "c2a9e0f1-7b34-4d58-9a12-6f8e5d3c2b10"
FAULT_ID = "9d3b7c2e-51a8-4e6f-b0d4-8c7a6f5e4d31"


def raw_topology() -> dict[str, Any]:
    """The shipped example's initial_topology (SPEC-003 §2.1 wire form)."""
    return {
        "topology_id": "topo-cc-lab-v1",
        "revision": 1,
        "nodes": [
            {
                "nodeId": "mux-0",
                "nodeType": "ts_mux",
                "config": {
                    "cbr_bps": 3750000,
                    "pcr_insertion_policy": "pes_first_packet",
                },
                "ports": [
                    {
                        "portId": "in-0",
                        "direction": "input",
                        "plane": "MPEG_TS",
                        "maxConnections": 8,
                    },
                    {
                        "portId": "out",
                        "direction": "output",
                        "plane": "MPEG_TS",
                        "maxConnections": 1,
                    },
                ],
            },
            {
                "nodeId": "sink-0",
                "nodeType": "analyzer_sink",
                "config": {},
                "ports": [
                    {
                        "portId": "in",
                        "direction": "input",
                        "plane": "MPEG_TS",
                        "maxConnections": 1,
                    }
                ],
            },
        ],
        "connections": [
            {
                "connectionId": "conn-1",
                "from": {"nodeId": "mux-0", "portId": "out"},
                "to": {"nodeId": "sink-0", "portId": "in"},
                "plane": "MPEG_TS",
            }
        ],
    }


def raw_fault_plan(*, with_expected_observations: bool = True) -> list:
    """The shipped example's fault plan (single CC_DISCONTINUITY fault)."""
    fault: dict[str, Any] = {
        "fault_id": FAULT_ID,
        "fault_type": "CC_DISCONTINUITY",
        "target_id": "mux-0:pid:0x0100",
        "activation": {"kind": "packet_index", "packet_index": 120},
        "parameters": {"delta": 3},
    }
    if with_expected_observations:
        fault["expected_observations"] = ["ts.continuity_error"]
    return [fault]


def raw_scenario() -> dict[str, Any]:
    """A full valid scenario document (mirrors the shipped example)."""
    return {
        "schema_version": 1,
        "scenario_id": SCENARIO_ID,
        "version": "1.0.0",
        "title": "Locate a continuity-counter discontinuity",
        "difficulty": "beginner",
        "required_engine_versions": {"generator": "0.5.0"},
        "initial_topology": raw_topology(),
        "simulation_config": {
            "mode": "deterministic",
            "seed": 123456,
            "clock": {
                "mode": "deterministic",
                "start_time_ns": 0,
                "speed_num": 1,
                "speed_den": 1,
            },
        },
        "fault_plan": raw_fault_plan(),
        "objectives": [
            "Locate the CC discontinuity on PID 0x0100 in the faulted stream",
            "Repair CC continuity and pass verification with new evidence",
        ],
        "hints": [
            {
                "hint_id": "hint-1",
                "trigger": "two failed analyzes",
                "level": "nudge",
                "content": "Compare the CC sequence on PID 0x0100 packet by packet.",
                "requirement_ids": ["REQ-SIM-204-001"],
                "standard_ref": None,
            }
        ],
        "pass_criteria": [
            {
                "criterion_id": "PASS-1",
                "kind": "no_unexpected_cc_error",
                "mandatory": True,
            },
            {
                "criterion_id": "PASS-2",
                "kind": "fault_inactive",
                "mandatory": True,
            },
        ],
    }


def raw_scenario_clone() -> dict[str, Any]:
    """A deep clone of :func:`raw_scenario` (fresh dict identity)."""
    return copy.deepcopy(raw_scenario())


def strip_expected_observations(document: dict[str, Any]) -> dict[str, Any]:
    """Return the document with every fault's expected_observations removed.

    The acceptance-core negative: a scenario whose fault plan lacks
    ``expected_observations`` must be rejected by the SPEC-200 VALIDATING
    gate (ADR-0007 item 5).
    """
    stripped = copy.deepcopy(document)
    for fault in stripped["fault_plan"]:
        fault.pop("expected_observations", None)
    return stripped
