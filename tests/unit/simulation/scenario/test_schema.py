"""SPEC-205 schema face tests (SIM-F #45) — REQ-SIM-205-001 / 003 / 006.

Mapping:

- REQ-SIM-205-001: schema validation is mandatory; malformed documents are
  rejected with path-addressed errors (``SIM_SCENARIO_SCHEMA_INVALID`` /
  ``SIM_SCENARIO_CRITERION_INVALID``) — the negative matrix below.
- REQ-SIM-205-003: the hidden reference solution is protected before the
  reveal policy grants it (``SIM_SCENARIO_SOLUTION_LEAK``) and never leaks
  through error messages (path-addressed errors never echo values).
- REQ-SIM-205-006 (import half): imported scenario content is statically
  scanned for executable bodies (scripts / macros / dynamic expressions).
"""

from __future__ import annotations

import dataclasses
import json

import pytest

from simulation.errors import SimulationError
from simulation.scenario.schema import (
    SCENARIO_CRITERION_KINDS,
    SIM_SCENARIO_CRITERION_INVALID,
    SIM_SCENARIO_SCHEMA_INVALID,
    SIM_SCENARIO_SOLUTION_LEAK,
    ScenarioCriterionInvalidError,
    ScenarioDocument,
    ScenarioSchemaInvalidError,
    ScenarioSolutionLeakError,
    export_scenario_document,
    parse_scenario_document,
    reveal_hidden_solution,
)

from ._scenario_builders import (
    FAULT_ID,
    SCENARIO_ID,
    raw_scenario,
    raw_scenario_clone,
)


# --- REQ-SIM-205-001: happy path ---------------------------------------------


def test_valid_scenario_parses_into_frozen_document():
    document = parse_scenario_document(raw_scenario())
    assert isinstance(document, ScenarioDocument)
    assert document.scenario_id == SCENARIO_ID
    assert document.version == "1.0.0"
    assert document.title == "Locate a continuity-counter discontinuity"
    assert document.difficulty == "beginner"
    assert document.required_engine_versions["generator"] == "0.5.0"
    # initial_topology -> the SPEC-202 graph contract (snake_case mirror)
    assert document.topology.topology_id == "topo-cc-lab-v1"
    assert document.topology.revision == 1
    assert [node.node_id for node in document.topology.nodes] == [
        "mux-0",
        "sink-0",
    ]
    connection = document.topology.connections[0]
    assert (
        connection.from_node,
        connection.from_port,
        connection.to_node,
        connection.to_port,
        connection.plane.value,
    ) == ("mux-0", "out", "sink-0", "in", "MPEG_TS")
    # simulation_config -> clock contract (SPEC-201)
    assert document.seed == 123456
    assert document.deterministic is True
    assert document.clock_config.mode == "deterministic"
    assert document.clock_config.start_time_ns == 0
    # fault_plan -> canonical FaultDefinition objects (faults package owner)
    fault = document.fault_plan[0]
    assert fault.fault_id == FAULT_ID
    assert fault.fault_type == "CC_DISCONTINUITY"
    assert fault.target_id == "mux-0:pid:0x0100"
    assert fault.parameters == {"delta": 3}
    assert fault.activation.kind == "packet_index"
    assert fault.activation.packet_index == 120
    assert fault.expected_observations == ("ts.continuity_error",)
    # hints + criteria
    hint = document.hints[0]
    assert hint.hint_id == "hint-1"
    assert hint.requirement_ids == ("REQ-SIM-204-001",)
    assert hint.standard_ref is None
    assert [c.kind for c in document.pass_criteria] == [
        "no_unexpected_cc_error",
        "fault_inactive",
    ]
    assert document.hidden_reference_solution is None


def test_document_is_frozen():
    document = parse_scenario_document(raw_scenario())
    with pytest.raises(dataclasses.FrozenInstanceError):
        document.title = "mutated"  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        document.fault_plan[0].fault_type = "PAT_MISSING"  # type: ignore[misc]


def test_schema_version_accepts_number_one_and_string_one():
    for variant in (1, "1"):
        raw = raw_scenario()
        raw["schema_version"] = variant
        assert parse_scenario_document(raw).schema_version == "1"


def test_content_hash_is_sha256_of_canonical_form_and_stable():
    document_a = parse_scenario_document(raw_scenario())
    document_b = parse_scenario_document(raw_scenario_clone())
    # Same content, different dict identity/key order -> same pinning hash.
    reordered = json.loads(
        json.dumps(raw_scenario(), ensure_ascii=False)
    )
    reordered["title"], reordered["version"] = (
        reordered["version"],
        reordered["title"],
    )
    swapped = parse_scenario_document(reordered)
    assert document_a.content_hash == document_b.content_hash
    assert len(document_a.content_hash) == 64  # sha256 hex
    mutated = raw_scenario_clone()
    mutated["seed"] = 654321
    assert parse_scenario_document(mutated).content_hash != (
        document_a.content_hash
    )
    assert swapped.content_hash != document_a.content_hash


# --- REQ-SIM-205-001: negative matrix (all rejected, path-addressed) ---------


_SCHEMA_NEGATIVES: list[tuple[str, object]] = [
    ("missing schema_version", ("schema_version", ...)),
    ("missing scenario_id", ("scenario_id", ...)),
    ("missing version", ("version", ...)),
    ("missing title", ("title", ...)),
    ("missing difficulty", ("difficulty", ...)),
    ("missing initial_topology", ("initial_topology", ...)),
    ("missing simulation_config", ("simulation_config", ...)),
    ("missing fault_plan", ("fault_plan", ...)),
    ("missing objectives", ("objectives", ...)),
    ("missing pass_criteria", ("pass_criteria", ...)),
    ("schema_version bool", ("schema_version", True)),
    ("schema_version unsupported", ("schema_version", "2")),
    ("scenario_id not uuid4", ("scenario_id", "not-a-uuid")),
    ("seed not int", ("simulation_config.seed", "123456")),
    ("fault_plan not a list", ("fault_plan", {})),
    ("objectives not a list", ("objectives", "locate")),
    ("clock mode invalid", ("simulation_config.clock.mode", "warp")),
]


@pytest.mark.parametrize(
    "label,mutation", _SCHEMA_NEGATIVES, ids=[label for label, _ in _SCHEMA_NEGATIVES]
)
def test_schema_negatives_rejected_path_addressed(label, mutation):
    path, value = mutation
    raw = raw_scenario_clone()
    if value is ...:
        _remove_path(raw, path)
    else:
        _set_path(raw, path, value)
    with pytest.raises(ScenarioSchemaInvalidError) as excinfo:
        parse_scenario_document(raw)
    error = excinfo.value
    assert error.code == SIM_SCENARIO_SCHEMA_INVALID
    assert error.details, "schema rejection must carry path-addressed details"
    assert all(detail.startswith("$.") for detail in error.details)
    assert path.split(".")[-1] in error.details[0]


def _split_path(path: str) -> list:
    """Split ``a.b[0].c`` into ``["a", "b", 0, "c"]`` segments."""
    import re

    segments: list = []
    for token in path.split("."):
        match = re.fullmatch(r"([^\[\]]+)(?:\[(\d+)\])?", token)
        if match:
            segments.append(match.group(1))
            if match.group(2) is not None:
                segments.append(int(match.group(2)))
        elif token:
            segments.append(token)
    return segments


def _set_path(raw: dict, path: str, value: object) -> None:
    segments = _split_path(path)
    target = raw
    for segment in segments[:-1]:
        target = target[segment]
    target[segments[-1]] = value


def _remove_path(raw: dict, path: str) -> None:
    segments = _split_path(path)
    target = raw
    for segment in segments[:-1]:
        target = target[segment]
    del target[segments[-1]]


def test_unknown_fault_type_is_schema_rejected():
    raw = raw_scenario_clone()
    raw["fault_plan"][0]["fault_type"] = "TELEPORT_PACKETS"
    with pytest.raises(ScenarioSchemaInvalidError) as excinfo:
        parse_scenario_document(raw)
    assert excinfo.value.code == SIM_SCENARIO_SCHEMA_INVALID
    assert "$.fault_plan[0].fault_type" in excinfo.value.details[0]


def test_fault_plan_entry_missing_required_field_rejected():
    raw = raw_scenario_clone()
    del raw["fault_plan"][0]["target_id"]
    with pytest.raises(ScenarioSchemaInvalidError) as excinfo:
        parse_scenario_document(raw)
    assert "$.fault_plan[0].target_id" in excinfo.value.details[0]


def test_duplicate_fault_id_and_criterion_id_rejected():
    raw = raw_scenario_clone()
    raw["fault_plan"].append(dict(raw["fault_plan"][0]))
    with pytest.raises(ScenarioSchemaInvalidError) as excinfo:
        parse_scenario_document(raw)
    assert "$.fault_plan[1].fault_id" in excinfo.value.details[0]

    raw = raw_scenario_clone()
    raw["pass_criteria"][1]["criterion_id"] = "PASS-1"
    with pytest.raises(ScenarioSchemaInvalidError) as excinfo:
        parse_scenario_document(raw)
    assert "$.pass_criteria[1].criterion_id" in excinfo.value.details[0]


def test_malformed_activation_rejected_path_addressed():
    raw = raw_scenario_clone()
    raw["fault_plan"][0]["activation"] = {"kind": "packet_index"}
    with pytest.raises(ScenarioSchemaInvalidError) as excinfo:
        parse_scenario_document(raw)
    assert "$.fault_plan[0].activation.packet_index" in (
        excinfo.value.details[0]
    )

    raw = raw_scenario_clone()
    raw["fault_plan"][0]["activation"] = {"kind": "virtual_time"}
    with pytest.raises(ScenarioSchemaInvalidError):
        parse_scenario_document(raw)


def test_top_level_must_be_object():
    with pytest.raises(ScenarioSchemaInvalidError) as excinfo:
        parse_scenario_document([1, 2, 3])
    assert excinfo.value.details[0].startswith("$")


# --- criterion integrity (SIM_SCENARIO_CRITERION_INVALID) ---------------------


def test_criterion_kind_out_of_closed_enum_rejected():
    raw = raw_scenario_clone()
    raw["pass_criteria"][0]["kind"] = "ui_looks_green"
    with pytest.raises(ScenarioCriterionInvalidError) as excinfo:
        parse_scenario_document(raw)
    assert excinfo.value.code == SIM_SCENARIO_CRITERION_INVALID
    assert "$.pass_criteria[0].kind" in excinfo.value.details[0]


def test_criterion_kinds_match_spec206_closed_enum():
    assert SCENARIO_CRITERION_KINDS == frozenset(
        {
            "fault_inactive",
            "psi_pat_valid",
            "psi_pmt_valid",
            "pat_pmt_mapping_valid",
            "cc_continuous",
            "no_unexpected_cc_error",
        }
    )


def test_fault_inactive_referencing_unknown_fault_id_rejected():
    raw = raw_scenario_clone()
    raw["pass_criteria"][1]["fault_id"] = (
        "0b0e8e10-1111-4222-8333-444455556666"
    )
    with pytest.raises(ScenarioCriterionInvalidError) as excinfo:
        parse_scenario_document(raw)
    assert "$.pass_criteria[1].fault_id" in excinfo.value.details[0]


def test_fault_inactive_referencing_declared_fault_id_accepted():
    raw = raw_scenario_clone()
    raw["pass_criteria"][1]["fault_id"] = FAULT_ID
    document = parse_scenario_document(raw)
    assert document.pass_criteria[1].fault_id == FAULT_ID


def test_fault_inactive_without_fault_id_is_accepted_at_load():
    # Documented load-time ruling: SPEC-205 §4 rejects a *broken reference*
    # (fault_id declared but absent from the plan); a fault_inactive with no
    # fault_id makes no reference, so the integrity rule has nothing to
    # violate — criterion evaluation (SPEC-206) owns that case. This keeps
    # the shipped example loadable.
    document = parse_scenario_document(raw_scenario())
    assert document.pass_criteria[1].fault_id is None


# --- REQ-SIM-205-006 (import half): executable-content static scan ------------


_EXECUTABLE_MARKERS = (
    "<script>alert(1)</script>",
    "javascript:void(0)",
    "eval('1+1')",
    "exec('import os')",
    "__import__('os')",
    "${process.env.SECRET}",
    "{{7*7}}",
    "#!/bin/sh",
    "os.system('rm -rf /')",
    "subprocess.Popen('cmd')",
    "Function('return 1')()",
    "`backtick expression`",
)


@pytest.mark.parametrize("marker", _EXECUTABLE_MARKERS)
def test_executable_content_in_any_string_field_is_rejected(marker):
    for path in ("title", "objectives[0]", "hints[0].content"):
        raw = raw_scenario_clone()
        _set_path(raw, path, f"innocent text {marker} trailing")
        with pytest.raises(ScenarioSchemaInvalidError) as excinfo:
            parse_scenario_document(raw)
        assert "$." in excinfo.value.details[0]


def test_executable_content_scan_is_deterministic():
    raw = raw_scenario_clone()
    raw["title"] = "eval(1)"
    with pytest.raises(ScenarioSchemaInvalidError) as first:
        parse_scenario_document(raw)
    with pytest.raises(ScenarioSchemaInvalidError) as second:
        parse_scenario_document(raw)
    assert first.value.details == second.value.details


# --- REQ-SIM-205-003: hidden reference solution protection --------------------


def test_hidden_reference_solution_roundtrip():
    raw = raw_scenario_clone()
    raw["hidden_reference_solution"] = "Set delta back to 0 on mux-0."
    document = parse_scenario_document(raw)
    assert (
        document.hidden_reference_solution == "Set delta back to 0 on mux-0."
    )


def test_reveal_without_policy_grant_is_refused():
    raw = raw_scenario_clone()
    secret = "Set delta back to 0 on mux-0."
    raw["hidden_reference_solution"] = secret
    document = parse_scenario_document(raw)
    with pytest.raises(ScenarioSolutionLeakError) as excinfo:
        reveal_hidden_solution(document, reveal_granted=False)
    assert excinfo.value.code == SIM_SCENARIO_SOLUTION_LEAK
    assert secret not in str(excinfo.value)


def test_reveal_with_policy_grant_returns_solution():
    raw = raw_scenario_clone()
    secret = "Set delta back to 0 on mux-0."
    raw["hidden_reference_solution"] = secret
    document = parse_scenario_document(raw)
    assert reveal_hidden_solution(document, reveal_granted=True) == secret


def test_export_drops_hidden_solution_without_reveal_grant():
    raw = raw_scenario_clone()
    secret = "Set delta back to 0 on mux-0."
    raw["hidden_reference_solution"] = secret
    document = parse_scenario_document(raw)
    exported = export_scenario_document(document)
    blob = json.dumps(exported, ensure_ascii=False)
    assert secret not in blob
    assert "hidden_reference_solution" not in exported


def test_export_without_hidden_solution_round_trips():
    document = parse_scenario_document(raw_scenario())
    exported = export_scenario_document(document)
    reparsed = parse_scenario_document(exported)
    assert reparsed.content_hash == document.content_hash


def test_validation_errors_never_echo_document_values():
    # REQ-SIM-205-003: no read path (errors included) may leak document
    # content — here the "secret" is an ordinary field value that must not
    # surface in the path-addressed error text.
    raw = raw_scenario_clone()
    raw["title"] = "top-secret-title"
    del raw["difficulty"]
    with pytest.raises(ScenarioSchemaInvalidError) as excinfo:
        parse_scenario_document(raw)
    error = excinfo.value
    assert isinstance(error, SimulationError)
    assert "top-secret-title" not in str(error)
    assert all("top-secret-title" not in detail for detail in error.details)
