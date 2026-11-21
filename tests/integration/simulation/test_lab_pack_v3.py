"""Lab Pack v3 inventory tests (ticket #171, SPEC-406 §Phase3 + ADR-0012
decision 2) — the two Phase 3 state-domain scenarios landed from the
approved draft examples (``docs/spec/.../examples/lab-pack-v3/`` →
``scenarios/``, calibrated to the implementation state per rulings
A3 / A17 / A20).

Pinned here (the SPEC-406 §12 authoring contract rides on every file,
mirroring the v1/v2 lab-pack posture assertion-for-assertion):

- the two files exist filename-ASC after every earlier scenario (the v1
  five + the v2 four) and every file passes the production loader's
  **v3 schema branch** (ruling A3: ``schema_version ∈ {3, "3"}``,
  ``simulation_config {fidelity: "SIM_STATE", seed}`` — mode/clock stay
  the v1 branch's exclusive face) AND the SPEC-204 §11 fault-plan gate
  (``validate_scenario_fault_plan`` — the #163 state-layer primitives
  through the production registry) AND the SPEC-202 §5 topology gate
  (``validate_topology`` — the #160 ``SIM_TOPO_UB_*`` rules; the
  baseline is statically legal, the UB mismatch exists at plan time
  only, SPEC-623 §7 layering);
- two distinct uuid4 scenario ids, disjoint from all nine earlier files;
- every file declares a non-empty ``hidden_reference_solution`` and the
  teaching copy (objectives/hints/solution: SCR = Satellite Channel
  Router 非 Subscriber Channel Radio; 冲突在 SCR 堆叠层与 LNB 本振无关;
  850 MHz 不对称性) rides the draft verbatim — pinned by non-regression
  assertions, never re-authored here;
- each scenario's fault plan references its Phase 3 primitive with the
  state-observation symbol set — and the paired builtin diagnostic
  rule's ``expected_evidence`` is the SAME symbol set (the 判据互锁
  posture per the v2 precedent: rule-symbol interlock, NOT a
  diagnose-face candidate assertion — the state-snapshot anchor gap
  stays recorded on #168);
- ``required_engine_versions`` = ``{fault_registry, l0_state_evaluators}
  >= 0.7.0`` — the archive-only fact (no runtime enforcement exists;
  the engine-face guarantee IS this test, brief §I R3);
- SC-10 declares the shared-coax SCR topology (``coax_out``
  maxConnections 2 fan-out, ``scr.ub_assignments`` tuner-a→UB0@1210 /
  tuner-b→UB1@1420); SC-11 declares the dual-LNB direct chain (ruling
  A17's mechanism-level calibration: a single universal LNB delivers
  one polarization and one band, so the draft's one-LNB dual-band
  baseline 双锁 is structurally impossible — lnb-0 13V/none feeds
  tuner-low, lnb-1 18V/continuous feeds tuner-high, the asymmetric
  narrative survives verbatim);
- all files open READY sessions through :func:`open_scenario_session`
  and their **baseline Run (no fault)** is deterministic across
  prepared runs (the same config_hash + terminal state — the ADR-0012
  decision 6 reproducibility contract over the #165 orchestration);
- the v1 parse path is byte-identical: all nine earlier scenarios keep
  ``schema_version "1"`` / ``fidelity None`` / wire-parsed clock (the
  A3 zero-drift lock).
"""

from __future__ import annotations

import asyncio
import json

import pytest

from domain.diagnosis.rules import load_builtin_rules
from domain.topology.node_types import ALL_NODE_TYPES

REGISTERED_NODE_TYPES = {spec.node_type for spec in ALL_NODE_TYPES}
from simulation.clock import SimulationClockConfig
from simulation.scenario.loader import (
    open_scenario_session,
    scenario_session_spec,
    validate_scenario_fault_plan,
)
from simulation.scenario.schema import (
    ScenarioSchemaInvalidError,
    parse_scenario_document,
)
from simulation.runtime import SimulationRuntime
from simulation.state.run import (
    compute_state_run_hash,
    prepare_state_run,
    run_state_run,
)
from simulation.state.validate import validate_topology

from tests._support.paths import REPO_ROOT

SCENARIO_DIR = REPO_ROOT / "scenarios"

V3_FILES = (
    "SC-10-unicable_ub_conflict.json",
    "SC-11-tone_residue.json",
)

V3_IDS = {
    "SC-10-unicable_ub_conflict.json": "5c010000-0000-4000-8000-00000000000a",
    "SC-11-tone_residue.json": "5c010000-0000-4000-8000-00000000000b",
}

#: v3 file → the paired builtin diagnostic rule (#168 finals).
PAIRED_RULES = {
    "SC-10-unicable_ub_conflict.json": "DIA-UB-CONFLICT-SUSPECT",
    "SC-11-tone_residue.json": "DIA-TONE-RESIDUE-SUSPECT",
}

#: The Phase 3 engine-face declaration (archive-only, brief §I R3).
V3_REQUIRED_ENGINE_VERSIONS = {
    "fault_registry": ">=0.7.0",
    "l0_state_evaluators": ">=0.7.0",
}

#: The two state-observation symbols every v3 primitive cites.
STATE_SYMBOLS = {"sec.state_observed", "rf.state_observed"}


def _v3_pack() -> dict[str, dict]:
    return {
        name: json.loads((SCENARIO_DIR / name).read_text(encoding="utf-8"))
        for name in V3_FILES
    }


def _document_of(name: str):
    return parse_scenario_document(_v3_pack()[name])


# --- inventory + authoring contract ----------------------------------------------


def test_v3_files_sit_after_every_earlier_scenario_in_filename_order() -> None:
    names = [path.name for path in sorted(SCENARIO_DIR.glob("*.json"))]
    assert len(names) == 11  # v1 five + v2 four + v3 two
    assert names[-2:] == list(V3_FILES)


@pytest.mark.parametrize("name", V3_FILES)
def test_every_v3_file_passes_the_v3_schema_fault_and_topology_gates(
    name: str,
) -> None:
    document = _document_of(name)  # schema gate — the v3 branch (A3)
    assert document.content_hash
    assert document.scenario_id == V3_IDS[name]
    assert validate_scenario_fault_plan(document) == ()  # SPEC-204 §11 gate
    assert validate_topology(document.topology) == ()  # SPEC-202 §5 gate


def test_v3_scenario_ids_are_distinct_uuid4s_disjoint_from_earlier() -> None:
    all_ids = [
        parse_scenario_document(
            json.loads(path.read_text(encoding="utf-8"))
        ).scenario_id
        for path in sorted(SCENARIO_DIR.glob("*.json"))
    ]
    assert len(set(all_ids)) == 11
    for scenario_id in V3_IDS.values():
        assert scenario_id[14] == "4" and scenario_id[19] in "89ab"


@pytest.mark.parametrize("name", V3_FILES)
def test_every_v3_scenario_declares_a_non_empty_hidden_reference_solution(
    name: str,
) -> None:
    solution = _v3_pack()[name].get("hidden_reference_solution")
    assert isinstance(solution, str) and solution.strip(), name


def test_v3_difficulty_ladder_does_not_descend() -> None:
    difficulties = [_v3_pack()[name]["difficulty"] for name in V3_FILES]
    rank = {"introductory": 0, "intermediate": 1, "advanced": 2}
    ranks = [rank[difficulty] for difficulty in difficulties]
    assert ranks == sorted(ranks)


@pytest.mark.parametrize("name", V3_FILES)
def test_v3_hint_ladders_are_three_deep_with_null_standard_refs(
    name: str,
) -> None:
    hints = _v3_pack()[name]["hints"]
    assert len(hints) >= 3
    for hint in hints:
        assert hint["standard_ref"] is None
        assert isinstance(hint["content"], str) and hint["content"].strip()


@pytest.mark.parametrize("name", V3_FILES)
def test_v3_pass_criteria_is_the_single_fault_inactive_criterion(
    name: str,
) -> None:
    raw = _v3_pack()[name]
    criteria = raw["pass_criteria"]
    assert len(criteria) == 1
    only = criteria[0]
    assert only["kind"] == "fault_inactive"
    assert only["mandatory"] is True
    assert only["fault_id"] in {fault["fault_id"] for fault in raw["fault_plan"]}


# --- the v3 schema face (ruling A3) ------------------------------------------------


@pytest.mark.parametrize("name", V3_FILES)
def test_v3_documents_carry_the_phase3_schema_and_config_face(name: str) -> None:
    raw = _v3_pack()[name]
    assert raw["schema_version"] == 3
    assert raw["simulation_config"] == {"fidelity": "SIM_STATE", "seed": 42}
    document = parse_scenario_document(raw)
    assert document.schema_version == "3"  # normalized, never downgraded to "1"
    assert document.fidelity == "SIM_STATE"
    assert document.seed == 42
    # SIM_STATE runs are deterministic (ADR-0012 decision 6 contract).
    assert document.deterministic is True
    # No wire clock on the v3 face: the loader synthesizes the deterministic
    # epoch-zero clock (REPORT-frozen #171 additive).
    assert document.clock_config == SimulationClockConfig(
        mode="deterministic", start_time_ns=0
    )
    assert document.raw["schema_version"] == "3"
    assert document.raw["simulation_config"]["fidelity"] == "SIM_STATE"


@pytest.mark.parametrize("name", V3_FILES)
def test_v3_required_engine_versions_are_the_archived_phase3_face(
    name: str,
) -> None:
    # Archive-only fact (no runtime enforcement exists — brief §I R3):
    # the engine-face >= 0.7.0 guarantee is exactly this pin.
    document = _document_of(name)
    assert dict(document.required_engine_versions) == V3_REQUIRED_ENGINE_VERSIONS


def test_v3_branch_rejects_fidelity_outside_the_phase3_domain() -> None:
    raw = _v3_pack()["SC-10-unicable_ub_conflict.json"]
    raw["simulation_config"]["fidelity"] = "SIM_TS"
    with pytest.raises(ScenarioSchemaInvalidError) as excinfo:
        parse_scenario_document(raw)
    assert any(
        "$.simulation_config.fidelity" in detail
        for detail in excinfo.value.details
    )


@pytest.mark.parametrize("missing_key", ["fidelity", "seed"])
def test_v3_branch_requires_fidelity_and_seed(missing_key: str) -> None:
    raw = _v3_pack()["SC-11-tone_residue.json"]
    del raw["simulation_config"][missing_key]
    with pytest.raises(ScenarioSchemaInvalidError) as excinfo:
        parse_scenario_document(raw)
    assert any(
        f"$.simulation_config.{missing_key}" in detail
        for detail in excinfo.value.details
    )


def test_the_intermediate_version_2_stays_rejected() -> None:
    # The A3 additive widens the accepted set to {1, "1", 3, "3"} only.
    raw = _v3_pack()["SC-10-unicable_ub_conflict.json"]
    raw["schema_version"] = 2
    with pytest.raises(ScenarioSchemaInvalidError) as excinfo:
        parse_scenario_document(raw)
    assert any(
        "$.schema_version" in detail for detail in excinfo.value.details
    )


def test_v3_branch_ignores_the_v1_exclusive_mode_clock_keys() -> None:
    # mode/clock are the v1 branch's face; a v3 document carrying them
    # rides the raw verbatim but the v3 semantics decide (REPORT-frozen:
    # accepted-and-ignored, no new rejection path).
    raw = _v3_pack()["SC-11-tone_residue.json"]
    raw["simulation_config"]["mode"] = "realtime"
    document = parse_scenario_document(raw)
    assert document.fidelity == "SIM_STATE"
    assert document.deterministic is True
    assert document.raw["simulation_config"]["mode"] == "realtime"


# --- the fault faces (primitive × layer × activation × symbols) --------------------


def _fault_of(name: str) -> dict:
    raw = _v3_pack()[name]
    assert len(raw["fault_plan"]) == 1
    return raw["fault_plan"][0]


def test_sc10_fault_face() -> None:
    raw_fault = _fault_of("SC-10-unicable_ub_conflict.json")
    assert raw_fault["fault_type"] == "UB_SLOT_CONFLICT"
    # The ruling-A4 third target form (node_id:attr_name), draft-verbatim.
    assert raw_fault["target_id"] == "tuner-b:ub_slot"
    assert raw_fault["parameters"] == {"conflicting_ub_slot": 0}
    assert raw_fault["activation"]["kind"] == "session_start"
    assert set(raw_fault["expected_observations"]) == STATE_SYMBOLS
    # The layer rides the #163 registry declaration (parse-derived; the
    # draft wire carries no layer key).
    document = _document_of("SC-10-unicable_ub_conflict.json")
    assert [fault.layer for fault in document.fault_plan] == ["SEC"]


def test_sc11_fault_face() -> None:
    raw_fault = _fault_of("SC-11-tone_residue.json")
    assert raw_fault["fault_type"] == "TONE_RESIDUE"
    assert raw_fault["target_id"] == "lnb-0"  # bare node_id form
    assert raw_fault["parameters"] == {"tone_actual": "continuous"}
    assert raw_fault["activation"]["kind"] == "session_start"
    assert set(raw_fault["expected_observations"]) == STATE_SYMBOLS
    document = _document_of("SC-11-tone_residue.json")
    assert [fault.layer for fault in document.fault_plan] == ["RF"]


# --- the rule-symbol interlock (the v2 §10-18 posture, #168 finals) ----------------


def test_v3_expected_observations_interlock_with_builtin_rule_evidence() -> None:
    """Each v3 scenario's ``expected_observations`` equals its paired
    builtin rule's ``expected_evidence`` — the same-construct mutual proof.
    Deliberately NOT a diagnose-face candidate assertion: the state
    snapshots carry no SPEC-306 §6 anchor state (recorded on #168)."""
    rules = {rule.rule_id: rule for rule in load_builtin_rules()}
    for name, rule_id in PAIRED_RULES.items():
        rule = rules[rule_id]  # KeyError = the rule left the builtin set
        fault = _fault_of(name)
        assert set(fault["expected_observations"]) == set(rule.expected_evidence), (
            f"{name} ↔ {rule_id}"
        )


# --- the topology faces ------------------------------------------------------------


def _ports_by_node(topology: dict) -> dict:
    return {
        node["nodeId"]: {port["portId"]: port for port in node["ports"]}
        for node in topology["nodes"]
    }


def test_sc10_declares_the_shared_coax_scr_topology() -> None:
    topology = _v3_pack()["SC-10-unicable_ub_conflict.json"]["initial_topology"]
    nodes = {node["nodeId"]: node for node in topology["nodes"]}
    assert set(nodes) == {"lnb-0", "tuner-a", "tuner-b"}
    assert all(node["nodeType"] in REGISTERED_NODE_TYPES for node in nodes.values())
    lnb = nodes["lnb-0"]
    # The SCR sub-segment rides the lnb config (SPEC-623 §5; the draft's
    # ub_assignments table verbatim).
    scr = lnb["config"]["scr"]
    assert scr["protocol"] == "EN50494"
    table = {
        entry["tuner_node"]: entry for entry in scr["ub_assignments"]
    }
    assert set(table) == {"tuner-a", "tuner-b"}
    assert table["tuner-a"]["ub_slot"] == 0
    assert table["tuner-a"]["ub_center_freq_mhz"] == 1210
    assert table["tuner-a"]["position"] == "A"
    assert table["tuner-b"]["ub_slot"] == 1
    assert table["tuner-b"]["ub_center_freq_mhz"] == 1420
    assert table["tuner-b"]["position"] == "B"
    # The #148 mechanism-zero-extension face: one coax_out fans out 1:N.
    ports = _ports_by_node(topology)
    assert ports["lnb-0"]["coax_out"]["plane"] == "SEC_CONTROL"
    assert ports["lnb-0"]["coax_out"]["maxConnections"] == 2
    # Both tuners claim their own UB slot — the baseline is statically
    # legal; the fault's conflicting slot 0 exists at plan time only.
    assert nodes["tuner-a"]["config"]["ub_slot"] == 0
    assert nodes["tuner-b"]["config"]["ub_slot"] == 1
    # The production wire form: nested from/to + plane (the draft's flat
    # fromNode/toNode shape is calibrated to the v1/v2 wire vocabulary).
    assert len(topology["connections"]) == 2
    for connection in topology["connections"]:
        assert connection["plane"] == "SEC_CONTROL"
        assert connection["from"]["nodeId"] == "lnb-0"
        assert connection["from"]["portId"] == "coax_out"
    to_nodes = {connection["to"]["nodeId"] for connection in topology["connections"]}
    assert to_nodes == {"tuner-a", "tuner-b"}


def test_sc11_declares_the_dual_lnb_direct_chain() -> None:
    """Ruling A17's mechanism-level calibration: the draft's single-LNB
    topology cannot deliver two bands at once (one voltage, one
    tone_actual ⇒ one LO), so the 双锁 baseline is structurally
    impossible there; the calibrated dual-LNB direct chain keeps the
    asymmetric narrative verbatim (lnb-0 low-band feed faulted, lnb-1
    high-band feed clean)."""
    topology = _v3_pack()["SC-11-tone_residue.json"]["initial_topology"]
    nodes = {node["nodeId"]: node for node in topology["nodes"]}
    assert set(nodes) == {"lnb-0", "lnb-1", "tuner-low", "tuner-high"}
    assert {node["nodeType"] for node in nodes.values()} == {"lnb", "tuner"}
    assert all("scr" not in node["config"] for node in nodes.values())
    assert all("diseqc_switch" != node["nodeType"] for node in nodes.values())
    # The declared drive keys (ruling A20's first-class optional fields):
    # lnb-0 feeds tuner-low on the low band; lnb-1 feeds tuner-high on the
    # high band — the baseline locks both, the TONE_RESIDUE fault on lnb-0
    # leaves tuner-high untouched (the asymmetry).
    assert nodes["lnb-0"]["config"]["voltage"] == "13V"
    assert nodes["lnb-0"]["config"]["tone_commanded"] == "none"
    assert nodes["lnb-1"]["config"]["voltage"] == "18V"
    assert nodes["lnb-1"]["config"]["tone_commanded"] == "continuous"
    assert nodes["tuner-low"]["config"]["tuning_request"] == {
        "frequency_khz": 11095000,
        "polarization": "vertical",
    }
    assert nodes["tuner-high"]["config"]["tuning_request"] == {
        "frequency_khz": 12070000,
        "polarization": "horizontal",
    }
    assert nodes["tuner-low"]["config"]["ub_slot"] is None
    assert nodes["tuner-high"]["config"]["ub_slot"] is None
    # 1:1 direct links, production wire form.
    links = {
        (connection["from"]["nodeId"], connection["to"]["nodeId"])
        for connection in topology["connections"]
    }
    assert links == {("lnb-0", "tuner-low"), ("lnb-1", "tuner-high")}
    assert all(
        connection["plane"] == "SEC_CONTROL"
        for connection in topology["connections"]
    )


# --- the composition-root faces ------------------------------------------------------


def test_all_v3_scenarios_open_ready_sessions() -> None:
    """``open_scenario_session`` (schema gate → CREATED → VALIDATING →
    READY) — the exact composition path the Lab UI's 开局 drives."""

    async def _open_all() -> list[str]:
        runtime = SimulationRuntime()
        lifecycles = []
        for name in V3_FILES:
            session = await open_scenario_session(runtime, SCENARIO_DIR / name)
            lifecycle = session.snapshot.lifecycle
            lifecycles.append(str(getattr(lifecycle, "value", lifecycle)))
        return lifecycles

    assert asyncio.run(_open_all()) == ["ready", "ready"]


def _run_baseline(name: str):
    """One scenario's baseline determinism drive: READY 开局 → a spec-built
    session → two prepared runs through the #165 orchestration (the
    fidelity="SIM_STATE" + no-config submit posture, plan empty)."""

    async def _drive():
        runtime = SimulationRuntime()
        binding = await open_scenario_session(runtime, SCENARIO_DIR / name)
        lifecycle = binding.snapshot.lifecycle
        assert str(getattr(lifecycle, "value", lifecycle)) == "ready"
        spec = scenario_session_spec(binding.document)
        await runtime.create_session(spec)
        await runtime.validate_session(spec.session_id)
        await runtime.start(spec.session_id)
        prepared_a = prepare_state_run(spec, ())
        prepared_b = prepare_state_run(spec, ())
        result_a = await run_state_run(prepared_a, runtime)
        result_b = await run_state_run(prepared_b, runtime)
        return spec, prepared_a, prepared_b, result_a, result_b

    return asyncio.run(_drive())


@pytest.mark.parametrize("name", V3_FILES)
def test_v3_baseline_run_is_deterministic_across_prepared_runs(name: str) -> None:
    """The ADR-0012 decision 6 reproducibility contract over the scenario
    baseline: two prepares and two runs of the same config + empty plan
    produce the same fingerprint and the same terminal state — and the
    基线双锁 teaching narrative (every node healthy) holds."""
    spec, prepared_a, prepared_b, result_a, result_b = _run_baseline(name)
    document = _document_of(name)
    expected_hash = compute_state_run_hash(
        graph=document.topology, fault_plan=(), seed=document.seed
    )
    assert prepared_a.config_hash == prepared_b.config_hash == expected_hash
    for result in (result_a, result_b):
        assert result.status == "completed"
        assert result.config_hash == expected_hash
        assert result.failures == ()
        assert result.error is None
    assert result_a.node_health == result_b.node_health
    assert result_a.graph_health == result_b.graph_health
    # 基线双锁: every node reports healthy on the baseline run (SC-10 both
    # tuners lock their UB slots; SC-11 both direct tuners lock).
    assert set(result_a.node_health.values()) == {"ok"}


# --- the A3 zero-drift lock (v1 path byte-identical) --------------------------------


def test_every_earlier_scenario_keeps_the_untouched_v1_parse_path() -> None:
    """Ruling A3: the v3 branch is additive — all nine earlier scenarios
    still parse through the untouched v1 gate (version "1", no fidelity,
    wire-parsed clock, both VALIDATING gates green)."""
    for path in sorted(SCENARIO_DIR.glob("*.json")):
        if path.name in V3_FILES:
            continue
        document = parse_scenario_document(
            json.loads(path.read_text(encoding="utf-8"))
        )
        assert document.schema_version == "1", path.name
        assert document.fidelity is None, path.name
        # v1 docs keep the wire-declared simulation semantics.
        assert document.clock_config.mode == "deterministic", path.name
        assert document.raw["simulation_config"]["mode"] == "deterministic"
        assert validate_scenario_fault_plan(document) == (), path.name
        assert validate_topology(document.topology) == (), path.name
