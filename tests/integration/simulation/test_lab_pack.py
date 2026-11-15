"""Lab Pack v1 inventory tests (ticket #67, SPEC-406 §4.9) — the five
repo-top-level ``scenarios/*.json`` files every implementation obligation
rides on.

The registry (``bootstrap.scenarios.ScenarioRegistry``, 裁定 F) scans the
repo-top-level ``scenarios/`` directory CWD-relative at composition time
and **fails fast on malformed files** — so every shipped file must pass
the production loader. These tests pin that obligation plus the SPEC-406
§4.9 authoring contract:

- five files, filename-ASC = SC-01..05 library order;
- every file parses through ``parse_scenario_document`` (the schema gate)
  and passes the SPEC-204 §11 fault-plan gate;
- five distinct uuid4 scenario ids, all declaring a non-empty
  ``hidden_reference_solution`` (the reveal-face content carrier);
- SC-01's pass criteria = the single ``fault_inactive`` mandatory
  criterion (the pure-REST PASS-reachable chain, M4 裁定 B posture);
- SC-02..05 additionally carry mandatory observation-class criteria (the
  SPEC-206 §7 symptom-guard intent; honest INCONCLUSIVE today);
- hints ladders ≥ 3 with ``standard_ref`` null (禁编造条款号, SPEC-205 §6).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from simulation.scenario.loader import validate_scenario_fault_plan
from simulation.scenario.schema import parse_scenario_document

from tests._support.paths import REPO_ROOT

SCENARIO_DIR = REPO_ROOT / "scenarios"

EXPECTED_FILES = (
    "SC-01-pat-missing.json",
    "SC-02-pmt-invalid-crc.json",
    "SC-03-pmt-pid-mismatch.json",
    "SC-04-cc-discontinuity.json",
    "SC-05-double-fault.json",
)

#: SPEC-206 §7 MVP criterion closed enum (verbatim wire slugs).
KINDS = {
    "fault_inactive",
    "psi_pat_valid",
    "psi_pmt_valid",
    "pat_pmt_mapping_valid",
    "cc_continuous",
    "no_unexpected_cc_error",
}

OBSERVATION_KINDS = KINDS - {"fault_inactive"}


def _lab_pack() -> list[tuple[str, dict]]:
    paths = sorted(SCENARIO_DIR.glob("*.json"))
    return [(path.name, json.loads(path.read_text(encoding="utf-8"))) for path in paths]


def test_lab_pack_directory_holds_exactly_the_five_pack_files() -> None:
    names = tuple(path.name for path in sorted(SCENARIO_DIR.glob("*.json")))
    assert names == EXPECTED_FILES


def test_every_lab_pack_file_passes_the_production_loader_and_fault_gate() -> None:
    pack = _lab_pack()
    assert len(pack) == 5
    for name, raw in pack:
        document = parse_scenario_document(raw)  # schema gate (raises on malformed)
        assert document.content_hash, name
        assert validate_scenario_fault_plan(document) == (), name


def test_lab_pack_scenario_ids_are_five_distinct_uuid4s() -> None:
    ids = [parse_scenario_document(raw).scenario_id for _name, raw in _lab_pack()]
    assert len(set(ids)) == 5
    for scenario_id in ids:
        # uuid4 shape: version nibble 4, variant nibble 8/9/a/b.
        assert scenario_id[14] == "4" and scenario_id[19] in "89ab"


def test_every_scenario_declares_a_non_empty_hidden_reference_solution() -> None:
    for name, raw in _lab_pack():
        solution = raw.get("hidden_reference_solution")
        assert isinstance(solution, str) and solution.strip(), name


def test_sc01_pass_criteria_is_the_single_fault_inactive_criterion() -> None:
    _name, raw = _lab_pack()[0]
    assert raw["scenario_id"] == "5c010000-0000-4000-8000-000000000001"
    criteria = raw["pass_criteria"]
    assert len(criteria) == 1
    only = criteria[0]
    assert only["kind"] == "fault_inactive"
    assert only["mandatory"] is True
    assert only["fault_id"] in {fault["fault_id"] for fault in raw["fault_plan"]}


@pytest.mark.parametrize("index", [1, 2, 3, 4])
def test_sc02_to_sc05_carry_mandatory_observation_class_criteria(index: int) -> None:
    _name, raw = _lab_pack()[index]
    kinds = {
        criterion["kind"]: criterion["mandatory"] for criterion in raw["pass_criteria"]
    }
    assert set(kinds) <= KINDS  # closed enum only
    mandatory_kinds = {kind for kind, mandatory in kinds.items() if mandatory}
    assert "fault_inactive" in mandatory_kinds
    assert mandatory_kinds & OBSERVATION_KINDS
    # SPEC-206 §7: every fault_inactive criterion references this plan.
    plan_ids = {fault["fault_id"] for fault in raw["fault_plan"]}
    for criterion in raw["pass_criteria"]:
        if criterion["kind"] == "fault_inactive":
            assert criterion["fault_id"] in plan_ids


def test_hint_ladders_are_three_deep_with_null_standard_refs() -> None:
    for name, raw in _lab_pack():
        hints = raw["hints"]
        assert len(hints) >= 3, name
        for hint in hints:
            assert hint["standard_ref"] is None, name
            assert isinstance(hint["content"], str) and hint["content"].strip(), name


def test_difficulty_ladder_ascends_across_the_pack() -> None:
    difficulties = [raw["difficulty"] for _name, raw in _lab_pack()]
    rank = {"introductory": 0, "intermediate": 1, "advanced": 2}
    assert [rank[difficulty] for difficulty in difficulties] == sorted(
        rank[difficulty] for difficulty in difficulties
    )


def test_topologies_use_the_frozen_mvp_node_type_strings() -> None:
    frozen = {"ts_generator", "ts_mux", "ts_demux", "ts_monitor"}
    for name, raw in _lab_pack():
        topology = raw["initial_topology"]
        for node in topology["nodes"]:
            assert node["nodeType"] in frozen, name
            for port in node["ports"]:
                assert port["plane"] == "MPEG_TS", name
                assert port["maxConnections"] == 1, name
