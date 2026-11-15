"""SPEC-205 loader face tests (SIM-F #45) — REQ-SIM-205-002 / 004 / 006.

Mapping:

- REQ-SIM-205-002: loading creates a NEW session and pins the scenario
  version + content hash; the document is immutable after load and never
  mutates a running session; re-running produces distinguishable records;
  applying a new version to a live session is refused
  (``SIM_SCENARIO_VERSION_CONFLICT``).
- REQ-SIM-205-004: deterministic initial Run — same scenario version
  yields identical session-spec inputs (seed / clock / topology / fault
  plan) and identical content hashes.
- REQ-SIM-205-006 (verification half): the fault plan must carry
  ``expected_observations`` — enforced at the SPEC-200 VALIDATING gate
  (acceptance core): a scenario whose fault plan lacks it is rejected
  while the session is in VALIDATING and the session ends FAILED.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json

import pytest

from simulation.errors import (
    SIM_VALIDATION_FAILED,
    SimulationValidationError,
)
from simulation.lifecycle import LifecycleState
from simulation.runtime import SimulationRuntime
from simulation.scenario.loader import (
    ScenarioSession,
    apply_scenario_update,
    install_scenario_validation_gate,
    load_scenario_text,
    open_scenario_session,
    scenario_session_spec,
    validate_scenario_fault_plan,
)
from simulation.scenario.schema import (
    SIM_SCENARIO_SCHEMA_INVALID,
    ScenarioSchemaInvalidError,
    ScenarioVersionConflictError,
    parse_scenario_document,
)

from ._scenario_builders import raw_scenario, raw_scenario_clone


def _text(**overrides_of_raw) -> str:
    raw = raw_scenario()
    seed = overrides_of_raw.pop("seed", None)
    if seed is not None:
        raw["simulation_config"]["seed"] = seed
    raw.update(overrides_of_raw)
    return json.dumps(raw, ensure_ascii=False)


# --- REQ-SIM-205-002: load = new session + version/hash pinning ---------------


def test_load_text_pins_content_hash_stably():
    document_a = load_scenario_text(_text())
    document_b = load_scenario_text(_text())
    assert document_a.content_hash == document_b.content_hash
    assert len(document_a.content_hash) == 64


def test_scenario_session_spec_is_a_new_session_per_call():
    document = load_scenario_text(_text())
    spec_a = scenario_session_spec(document)
    spec_b = scenario_session_spec(document)
    assert spec_a.session_id != spec_b.session_id
    # Same scenario version -> identical session inputs (REQ-SIM-205-004).
    assert spec_a.topology == spec_b.topology
    assert spec_a.seed == spec_b.seed
    assert spec_a.deterministic == spec_b.deterministic
    assert spec_a.clock_config == spec_b.clock_config


def test_document_immutability_after_load():
    raw = raw_scenario_clone()
    document = parse_scenario_document(raw)
    pinned_hash = document.content_hash
    pinned_seed = document.seed
    # Mutating the caller's dict after load must not touch the document.
    raw["seed"] = 999
    raw["title"] = "mutated in place"
    assert document.seed == pinned_seed
    assert document.content_hash == pinned_hash
    assert document.title != "mutated in place"
    # And the pinned session inputs are unaffected:
    spec = scenario_session_spec(document)
    assert spec.seed == pinned_seed
    with pytest.raises(dataclasses.FrozenInstanceError):
        document.version = "2.0.0"  # type: ignore[misc]


def test_modified_document_loads_as_new_version_not_mutation():
    first = load_scenario_text(_text())
    second = load_scenario_text(_text(seed=654321))
    assert first.content_hash != second.content_hash
    assert second.seed == 654321
    spec_first = scenario_session_spec(first)
    spec_second = scenario_session_spec(second)
    assert spec_first.seed == 123456
    assert spec_second.seed == 654321


def test_malformed_json_text_rejected_path_addressed():
    with pytest.raises(ScenarioSchemaInvalidError) as excinfo:
        load_scenario_text("{not json")
    assert excinfo.value.code == SIM_SCENARIO_SCHEMA_INVALID
    assert excinfo.value.details[0].startswith("$")


# --- REQ-SIM-205-006: fault plan invariants at the VALIDATING gate ------------


def test_fault_plan_gate_reports_missing_expected_observations():
    raw = raw_scenario_clone()
    for fault in raw["fault_plan"]:
        fault.pop("expected_observations", None)
    document = load_scenario_text(json.dumps(raw, ensure_ascii=False))
    violations = validate_scenario_fault_plan(document)
    assert violations, "missing expected_observations must be a violation"
    joined = " | ".join(violations)
    assert "SIM_SCENARIO_FAULT_PLAN_INVALID" in joined
    assert "SIM_FAULT_EXPECTED_OBS_MISSING" in joined
    assert "fault_plan[0].expected_observations" in joined


def test_fault_plan_gate_surfaces_spec204_details():
    raw = raw_scenario_clone()
    raw["fault_plan"][0]["parameters"] = {"delta": 0}
    document = load_scenario_text(json.dumps(raw, ensure_ascii=False))
    violations = validate_scenario_fault_plan(document)
    joined = " | ".join(violations)
    assert "SIM_FAULT_PARAM_INVALID" in joined


def test_valid_fault_plan_gate_passes_clean():
    document = load_scenario_text(_text())
    assert validate_scenario_fault_plan(document) == ()


def test_gate_install_is_idempotent():
    from simulation.runtime import VALIDATION_GATES

    before = len(VALIDATION_GATES)
    install_scenario_validation_gate()
    install_scenario_validation_gate()
    assert len(VALIDATION_GATES) == before + 1


# --- acceptance core: VALIDATING rejection (SPEC-200 lifecycle) ----------------


def _run(coro):
    return asyncio.run(coro)


def test_missing_expected_observations_rejected_in_validating():
    """验收核心：缺 expected_observations 的 scenario 被 VALIDATING 拒绝.

    The session walks CREATED -> VALIDATING and the scenario fault-plan
    gate runs *inside* the VALIDATING phase; the rejection drives
    VALIDATING -> FAILED (the #12-ruled edge) and surfaces as
    ``SIM_VALIDATION_FAILED`` carrying the path-addressed scenario
    violations.
    """
    raw = raw_scenario_clone()
    for fault in raw["fault_plan"]:
        fault.pop("expected_observations", None)
    runtime = SimulationRuntime()
    with pytest.raises(SimulationValidationError) as excinfo:
        _run(open_scenario_session(runtime, json.dumps(raw, ensure_ascii=False)))
    error = excinfo.value
    assert error.code == SIM_VALIDATION_FAILED
    report = error.report
    joined = " ".join(str(v) for v in report.violations)
    assert "SIM_SCENARIO_FAULT_PLAN_INVALID" in joined
    assert "SIM_FAULT_EXPECTED_OBS_MISSING" in joined
    snapshot = _run(runtime.get_snapshot(_session_id(runtime)))
    assert snapshot.lifecycle is LifecycleState.FAILED


def _session_id(runtime: SimulationRuntime) -> str:
    # The rejected session is the only one on this private runtime.
    (session_id,) = list(runtime._sessions)  # noqa: SLF001 - test seam
    return session_id


def test_open_scenario_session_happy_path_is_ready():
    runtime = SimulationRuntime()
    binding = _run(open_scenario_session(runtime, _text()))
    assert isinstance(binding, ScenarioSession)
    assert binding.snapshot.lifecycle is LifecycleState.READY
    assert binding.document.content_hash == binding.content_hash
    snapshot = _run(runtime.get_snapshot(binding.session_id))
    assert snapshot.lifecycle is LifecycleState.READY


def test_two_loads_produce_distinguishable_records():
    runtime = SimulationRuntime()
    first = _run(open_scenario_session(runtime, _text()))
    second = _run(open_scenario_session(runtime, _text()))
    assert first.session_id != second.session_id
    assert first.content_hash == second.content_hash
    # The first session is untouched by the second load (SPEC-205 §5:
    # 不突变运行中的 session).
    snapshot = _run(runtime.get_snapshot(first.session_id))
    assert snapshot.lifecycle is LifecycleState.READY


def test_apply_scenario_update_to_live_session_is_refused():
    runtime = SimulationRuntime()
    binding = _run(open_scenario_session(runtime, _text()))
    modified = load_scenario_text(_text(seed=1))
    with pytest.raises(ScenarioVersionConflictError) as excinfo:
        apply_scenario_update(binding, modified)
    assert excinfo.value.code == "SIM_SCENARIO_VERSION_CONFLICT"
    snapshot = _run(runtime.get_snapshot(binding.session_id))
    assert snapshot.lifecycle is LifecycleState.READY


def test_topology_invalid_scenario_rejected_in_validating_too():
    # The #41 topology gate rides the same VALIDATING phase; scenario
    # violations never mask topology ones and vice versa.
    raw = raw_scenario_clone()
    raw["initial_topology"]["connections"].append(
        {
            "connectionId": "conn-self",
            "from": {"nodeId": "mux-0", "portId": "out"},
            "to": {"nodeId": "mux-0", "portId": "out"},
            "plane": "MPEG_TS",
        }
    )
    runtime = SimulationRuntime()
    with pytest.raises(SimulationValidationError) as excinfo:
        _run(open_scenario_session(runtime, json.dumps(raw, ensure_ascii=False)))
    joined = " ".join(
        str(getattr(v, "code", "")) for v in excinfo.value.report.violations
    )
    assert "SIM_TOPO_SELF_LOOP" in joined


# --- REQ-SIM-205-004: deterministic initial Run regeneration -------------------


def test_deterministic_regeneration_same_inputs_and_hash():
    runtime = SimulationRuntime()
    first = _run(open_scenario_session(runtime, _text()))
    second = _run(open_scenario_session(runtime, _text()))
    spec_a = _run(runtime.get_snapshot(first.session_id))
    spec_b = _run(runtime.get_snapshot(second.session_id))
    # Same scenario version + same engine => identical baseline inputs;
    # the pinned scenario version (content hash) is identical.
    assert first.content_hash == second.content_hash
    assert spec_a.topology_revision == spec_b.topology_revision
    document = first.document
    assert document.seed == second.document.seed
    assert document.clock_config == second.document.clock_config
    assert document.fault_plan == second.document.fault_plan
    assert document.topology == second.document.topology
