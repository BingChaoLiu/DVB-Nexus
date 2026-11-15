"""SIM-F (#45) file-face integration — SPEC-205 loader over real files.

Covers the IO half the unit layer may not touch (SPEC-505 §1/§8): loading
scenario documents from checked-in assets (the canonical example, issue #12
authority) and from pytest tmp files, plus the end-to-end open path
(schema gate -> new session -> VALIDATING (topology + fault-plan gate) ->
READY) against a real :class:`simulation.runtime.SimulationRuntime`.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from simulation.errors import SimulationIOError
from simulation.lifecycle import LifecycleState
from simulation.runtime import SimulationRuntime
from simulation.scenario.loader import (
    ScenarioSession,
    load_scenario_file,
    open_scenario_session,
)
from tests._support.paths import REPO_ROOT

#: The canonical example (issue #12 authority): scenario 补
#: expected_observations + initial_topology，通过 SPEC-205 §3 结构校验.
CANONICAL_EXAMPLE = (
    REPO_ROOT
    / "docs"
    / "spec"
    / "DVB-Sandbox-Spec-v0.4-Complete"
    / "examples"
    / "scenario-cc-discontinuity.json"
)


def _run(coro):
    return asyncio.run(coro)


def test_canonical_example_exists_and_loads():
    document = load_scenario_file(CANONICAL_EXAMPLE)
    assert document.scenario_id == "c2a9e0f1-7b34-4d58-9a12-6f8e5d3c2b10"
    assert document.version == "1.0.0"
    assert document.topology.topology_id == "topo-cc-lab-v1"
    fault = document.fault_plan[0]
    assert fault.fault_type == "CC_DISCONTINUITY"
    assert fault.parameters == {"delta": 3}
    assert fault.expected_observations == ("ts.continuity_error",)
    assert [criterion.kind for criterion in document.pass_criteria] == [
        "no_unexpected_cc_error",
        "fault_inactive",
    ]
    assert len(document.content_hash) == 64


def test_canonical_example_hash_is_stable_across_loads():
    first = load_scenario_file(CANONICAL_EXAMPLE)
    second = load_scenario_file(CANONICAL_EXAMPLE)
    assert first.content_hash == second.content_hash


def test_canonical_example_opens_a_ready_session_end_to_end():
    runtime = SimulationRuntime()
    binding = _run(open_scenario_session(runtime, CANONICAL_EXAMPLE))
    assert isinstance(binding, ScenarioSession)
    assert binding.snapshot.lifecycle is LifecycleState.READY
    assert binding.content_hash == load_scenario_file(
        CANONICAL_EXAMPLE
    ).content_hash


def test_load_scenario_file_from_tmp(tmp_path):
    raw = json.loads(CANONICAL_EXAMPLE.read_text(encoding="utf-8"))
    raw["version"] = "1.0.1"
    target = tmp_path / "scenario-1.0.1.json"
    target.write_text(
        json.dumps(raw, ensure_ascii=False), encoding="utf-8"
    )
    document = load_scenario_file(target)
    assert document.version == "1.0.1"
    # Content change = new scenario version identity (pinning hash).
    assert document.content_hash != load_scenario_file(
        CANONICAL_EXAMPLE
    ).content_hash


def test_missing_file_is_sim_io_error(tmp_path):
    with pytest.raises(SimulationIOError) as excinfo:
        load_scenario_file(tmp_path / "absent.json")
    assert excinfo.value.code == "SIM_IO_ERROR"


def test_non_utf8_file_is_sim_io_error(tmp_path):
    target = tmp_path / "mojibake.json"
    target.write_bytes(b'{"title": "\xff\xfe"}')
    with pytest.raises(SimulationIOError):
        load_scenario_file(target)
