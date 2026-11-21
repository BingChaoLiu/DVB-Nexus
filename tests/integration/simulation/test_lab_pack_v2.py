"""Lab Pack v2 inventory tests (ticket #131, SPEC-406 §Phase2) — the four
Phase 2 training-range scenarios landed from the approved draft examples
(``docs/spec/.../examples/lab-pack-v2/`` → ``scenarios/``, calibrated to
the implementation state).

Pinned here (the SPEC-406 §12 authoring contract rides on every file):

- the four files exist filename-ASC after the v1 five and every file
  passes the production loader (schema gate) AND the SPEC-204 §11
  fault-plan gate (``validate_scenario_fault_plan``) AND the SPEC-202 §5
  topology gate — the session-READY preconditions of the Lab 开局;
- four distinct uuid4 scenario ids, disjoint from the v1 five;
- every file declares a non-empty ``hidden_reference_solution``;
- the v2 difficulty ladder ascends (SC-06..08 intermediate, SC-09 advanced);
- each scenario's fault plan references its Phase 2 primitive with the
  #130-final ``expected_observations`` symbol set — and the paired builtin
  diagnostic rule's ``expected_evidence`` is the SAME symbol set (the
  判据互锁 posture per orchestrator ruling §10-18: journal evidence events
  + rule-symbol interlock, NOT a diagnose-face candidate assertion — the
  SPEC-306 §6 anchor gap stays recorded on #130/#136);
- SC-06/07 declare the #110 three-level topology (t2mi_encapsulator /
  t2mi_demux over the T2MI plane link); SC-08 declares the scenario
  ``biss`` construction face (mode/session-word shape/pid scope/ca_pid —
  key MATERIAL is never pinned: shape only, SPEC-610 §9 discipline);
- SC-09's PMT_PID_DRIFT map rides the JSON digit-string-key face (the
  #131 orchestrator ruling on the registry wire form);
- all four open READY sessions through :func:`open_scenario_session`
  (the composition root face the Lab UI's 开局 drives).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from simulation.scenario.loader import (
    open_scenario_session,
    validate_scenario_fault_plan,
)
from simulation.scenario.schema import parse_scenario_document
from simulation.runtime import SimulationRuntime
from simulation.state.validate import validate_topology
from domain.diagnosis.rules import load_builtin_rules

from tests._support.paths import REPO_ROOT

SCENARIO_DIR = REPO_ROOT / "scenarios"

V2_FILES = (
    "SC-06-t2mi_plp_mismatch.json",
    "SC-07-bbheader_sync_fault.json",
    "SC-08-biss_key_mismatch.json",
    "SC-09-pmt_pid_drift.json",
)

V2_IDS = {
    "SC-06-t2mi_plp_mismatch.json": "5c010000-0000-4000-8000-000000000006",
    "SC-07-bbheader_sync_fault.json": "5c010000-0000-4000-8000-000000000007",
    "SC-08-biss_key_mismatch.json": "5c010000-0000-4000-8000-000000000008",
    "SC-09-pmt_pid_drift.json": "5c010000-0000-4000-8000-000000000009",
}

#: v2 file → the paired builtin diagnostic rule (the #130 finals).
PAIRED_RULES = {
    "SC-06-t2mi_plp_mismatch.json": "DIA-T2MI-PLP-MISMATCH",
    "SC-07-bbheader_sync_fault.json": "DIA-BBHEADER-SYNC-FAULT",
    "SC-08-biss_key_mismatch.json": "DIA-BISS-KEY-MISMATCH",
    "SC-09-pmt_pid_drift.json": "DIA-PMT-PID-DRIFT",
}


def _v2_pack() -> dict[str, dict]:
    return {
        name: json.loads((SCENARIO_DIR / name).read_text(encoding="utf-8"))
        for name in V2_FILES
    }


# --- inventory + authoring contract ----------------------------------------------


def test_v2_files_sit_after_the_v1_five_in_filename_order() -> None:
    names = [path.name for path in sorted(SCENARIO_DIR.glob("*.json"))]
    # Registration face (#171): the v2 four follow the v1 five; the v3
    # two ride after them (SC-10/SC-11, pinned in test_lab_pack_v3.py).
    assert names[5:9] == list(V2_FILES)


@pytest.mark.parametrize("name", V2_FILES)
def test_every_v2_file_passes_loader_fault_gate_and_topology_gate(name: str) -> None:
    document = parse_scenario_document(_v2_pack()[name])  # schema gate
    assert document.content_hash
    assert document.scenario_id == V2_IDS[name]
    assert validate_scenario_fault_plan(document) == ()  # SPEC-204 §11 gate
    assert validate_topology(document.topology) == ()  # SPEC-202 §5 gate


def test_v2_scenario_ids_are_distinct_uuid4s_disjoint_from_v1() -> None:
    all_ids = [
        parse_scenario_document(json.loads(path.read_text(encoding="utf-8"))).scenario_id
        for path in sorted(SCENARIO_DIR.glob("*.json"))
    ]
    assert len(set(all_ids)) == 11  # v1 five + v2 four + v3 two (#171)
    for scenario_id in V2_IDS.values():
        assert scenario_id[14] == "4" and scenario_id[19] in "89ab"


@pytest.mark.parametrize("name", V2_FILES)
def test_every_v2_scenario_declares_a_non_empty_hidden_reference_solution(
    name: str,
) -> None:
    solution = _v2_pack()[name].get("hidden_reference_solution")
    assert isinstance(solution, str) and solution.strip(), name


def test_v2_difficulty_ladder_ascends() -> None:
    difficulties = [_v2_pack()[name]["difficulty"] for name in V2_FILES]
    rank = {"introductory": 0, "intermediate": 1, "advanced": 2}
    ranks = [rank[difficulty] for difficulty in difficulties]
    assert ranks == sorted(ranks)
    assert ranks[-1] > ranks[0]  # SC-09 advanced > SC-06 intermediate


@pytest.mark.parametrize("name", V2_FILES)
def test_v2_hint_ladders_are_three_deep_with_null_standard_refs(name: str) -> None:
    hints = _v2_pack()[name]["hints"]
    assert len(hints) >= 3
    for hint in hints:
        assert hint["standard_ref"] is None
        assert isinstance(hint["content"], str) and hint["content"].strip()


@pytest.mark.parametrize("name", V2_FILES)
def test_v2_pass_criteria_is_the_single_fault_inactive_criterion(name: str) -> None:
    raw = _v2_pack()[name]
    criteria = raw["pass_criteria"]
    assert len(criteria) == 1
    only = criteria[0]
    assert only["kind"] == "fault_inactive"
    assert only["mandatory"] is True
    assert only["fault_id"] in {fault["fault_id"] for fault in raw["fault_plan"]}


# --- the fault faces (primitive × layer × activation × symbols) --------------------


def _fault_of(name: str) -> dict:
    raw = _v2_pack()[name]
    assert len(raw["fault_plan"]) == 1
    return raw["fault_plan"][0]


def test_sc06_fault_face() -> None:
    fault = _fault_of("SC-06-t2mi_plp_mismatch.json")
    assert fault["fault_type"] == "T2MI_PLP_MISMATCH"
    assert fault["target_id"] == "enc-0"  # node-level form (no shared pid)
    assert fault["parameters"] == {"expected_plp": 0, "actual_plp": 1}
    assert fault["activation"] == {"kind": "session_start"}
    assert set(fault["expected_observations"]) == {"t2mi.plp_mismatch"}


def test_sc07_fault_face() -> None:
    fault = _fault_of("SC-07-bbheader_sync_fault.json")
    assert fault["fault_type"] == "BBHEADER_SYNC_FAULT"
    assert fault["target_id"] == "enc-0"  # node-level form
    assert fault["parameters"] == {"field": "SYNCD", "mode": "corrupt"}
    assert fault["activation"]["kind"] == "packet_index"
    assert isinstance(fault["activation"]["packet_index"], int)
    assert set(fault["expected_observations"]) == {"bbframe.recovery_failed"}


def test_sc08_fault_face_and_biss_construction_section() -> None:
    raw = _v2_pack()["SC-08-biss_key_mismatch.json"]
    fault = raw["fault_plan"][0]
    assert fault["fault_type"] == "BISS_KEY_MISMATCH"
    assert fault["target_id"] == "mux-0"  # node-level form
    # pid_scope present + exactly one mismatch variant (Mode 1 here).
    assert isinstance(fault["parameters"]["pid_scope"], list)
    assert fault["parameters"]["pid_scope"] == [256]
    assert "wrong_session_word" in fault["parameters"]
    assert "wrong_esw" not in fault["parameters"]
    assert "wrong_injected_id" not in fault["parameters"]
    assert fault["activation"] == {"kind": "session_start"}
    assert set(fault["expected_observations"]) == {"biss.descramble_failed"}
    # The declared construction face (SPEC-610 §5): mode 1, CA_PID 0x1FFF.
    # Key MATERIAL is asserted as SHAPE only — never pinned as a literal
    # (SPEC-610 §9 密钥本体永不落; the discipline covers test assertions).
    biss = raw["biss"]
    assert biss["mode"] == "1"
    assert isinstance(biss["session_word"], str)
    assert len(biss["session_word"]) == 12  # 48-bit session word
    int(biss["session_word"], 16)  # hex-decodable
    assert biss["pid_scope"] == [256]
    assert biss["ca_pid"] == 8191


def test_sc09_fault_face() -> None:
    fault = _fault_of("SC-09-pmt_pid_drift.json")
    assert fault["fault_type"] == "PMT_PID_DRIFT"
    assert fault["target_id"] == "mux-0:pid:0x1000"  # stream-level form
    pid_map = fault["parameters"]["new_pid_map"]
    # JSON digit-string keys (the #131 ruling face): program_number → pid.
    assert isinstance(pid_map, dict) and pid_map
    for program_number, drifted_pid in pid_map.items():
        assert isinstance(program_number, str) and program_number.isascii()
        assert program_number.isdigit() and int(program_number) >= 1
        assert 0x0020 <= drifted_pid <= 0x1FFE
    assert fault["parameters"]["pmt_version_bump"] is True
    assert fault["activation"]["kind"] == "packet_index"
    # The #130/#129 symbol final (ruling §10-16-③): ts.* observation family
    # + fault.applied — NOT the withdrawn observation.* and NOT an
    # unregistered diagnosis.* symbol.
    assert set(fault["expected_observations"]) == {
        "ts.psi_section_observed",
        "fault.applied",
    }


# --- the rule-symbol interlock (ruling §10-18 posture) ------------------------------


def test_v2_expected_observations_interlock_with_builtin_rule_evidence() -> None:
    """Each v2 scenario's ``expected_observations`` equals its paired
    builtin rule's ``expected_evidence`` — the same-construct mutual proof.
    Deliberately NOT a diagnose-face candidate assertion: the Phase 2
    evidence anchoring is a recorded gap (ruling §10-18, #136 收口评估)."""
    rules = {rule.rule_id: rule for rule in load_builtin_rules()}
    for name, rule_id in PAIRED_RULES.items():
        rule = rules[rule_id]  # KeyError = the rule left the builtin set
        fault = _fault_of(name)
        assert set(fault["expected_observations"]) == set(rule.expected_evidence), (
            f"{name} ↔ {rule_id}"
        )


# --- the composition-root 开局 face -------------------------------------------------


def test_all_four_v2_scenarios_open_ready_sessions() -> None:
    """``open_scenario_session`` (schema gate → CREATED → VALIDATING →
    READY) — the exact composition path the Lab UI's 开局 drives."""

    async def _open_all() -> list[str]:
        runtime = SimulationRuntime()
        lifecycles = []
        for name in V2_FILES:
            session = await open_scenario_session(runtime, SCENARIO_DIR / name)
            lifecycle = session.snapshot.lifecycle
            lifecycles.append(str(getattr(lifecycle, "value", lifecycle)))
        return lifecycles

    assert asyncio.run(_open_all()) == ["ready", "ready", "ready", "ready"]


# --- the three-level topology face (SC-06/07) ---------------------------------------


@pytest.mark.parametrize("name", ["SC-06-t2mi_plp_mismatch.json", "SC-07-bbheader_sync_fault.json"])
def test_sc06_sc07_declare_the_three_level_chain(name: str) -> None:
    topology = _v2_pack()[name]["initial_topology"]
    node_types = {node["nodeType"] for node in topology["nodes"]}
    assert {"t2mi_encapsulator", "t2mi_demux"} <= node_types
    ports_by_node = {
        node["nodeId"]: {port["portId"]: port["plane"] for port in node["ports"]}
        for node in topology["nodes"]
    }
    # The #110 port templates: encapsulator bridges MPEG_TS → T2MI, the
    # demux bridges T2MI → MPEG_TS (the BBFrame level lives INSIDE the
    # nodes — it is never a plane; CONTEXT.md 词汇纪律).
    assert ports_by_node["enc-0"]["inner_in"] == "MPEG_TS"
    assert ports_by_node["enc-0"]["t2mi_out"] == "T2MI"
    assert ports_by_node["demux-0"]["t2mi_in"] == "T2MI"
    assert ports_by_node["demux-0"]["inner_out"] == "MPEG_TS"
    # Exactly one T2MI-plane connection: encapsulator → demux.
    t2mi_links = [c for c in topology["connections"] if c["plane"] == "T2MI"]
    assert len(t2mi_links) == 1
    assert t2mi_links[0]["from"]["nodeId"] == "enc-0"
    assert t2mi_links[0]["to"]["nodeId"] == "demux-0"
