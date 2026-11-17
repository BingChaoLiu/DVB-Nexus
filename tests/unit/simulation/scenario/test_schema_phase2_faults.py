"""Scenario fault-plan Phase 2 face (ticket #131, SPEC-204 §Phase2).

The scenario schema's fault-plan parse accepts the full KNOWN fault-type
registry (MVP four + the Phase 2 four) and resolves each entry's pipeline
``layer`` the same way the run-wire face does (#128: a fault's layer is
semantics, not wire state) — the registry's declared layer map is the
default source, an explicit ``layer`` key passes through, and the
layer-vs-fault-type constraint stays owned by the faults.registry
VALIDATING gate (:func:`simulation.scenario.loader.validate_scenario_fault_plan`).

Pinned here (orchestrator ruling on #131 — see the ticket REPORT's
「orchestrator 追认项」 section):

- MVP zero-regression: an MVP-era fault entry without any ``layer`` key
  parses byte-identically to the pre-#131 face (layer "TS", every other
  field verbatim);
- the four Phase 2 fault types pass the schema gate (previously rejected
  by the MVP-only membership check — the #131 landing blocker);
- layer derivation: T2MI_PLP_MISMATCH → "T2MI", BBHEADER_SYNC_FAULT →
  "BBFRAME", BISS_KEY_MISMATCH → "BISS", PMT_PID_DRIFT → "TS";
- explicit ``layer`` pass-through (and an explicitly wrong layer still
  parses here — the mismatch is the registry gate's violation, not the
  schema's);
- unknown fault types stay rejected with the registry-membership error.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from simulation.scenario.schema import (
    ScenarioSchemaInvalidError,
    parse_scenario_document,
)

from ._scenario_builders import FAULT_ID, SCENARIO_ID, raw_scenario

PHASE2_FAULT_ID = "fd000000-0000-4000-8000-00000000f100"


def _scenario_with_fault(fault: dict[str, Any]) -> dict[str, Any]:
    """A valid scenario document whose single fault entry is ``fault``.

    The criterion references the plan fault id (reference integrity), so
    the builder's criterion pair is replaced with a single fault_inactive
    row carrying the same contract the Lab Pack v2 files use.
    """
    raw = raw_scenario()
    raw["scenario_id"] = SCENARIO_ID  # builder default; explicit for clarity
    raw["fault_plan"] = [fault]
    raw["pass_criteria"] = [
        {
            "criterion_id": "fault-cleared",
            "kind": "fault_inactive",
            "mandatory": True,
            "fault_id": fault["fault_id"],
        }
    ]
    return raw


def _phase2_fault(fault_type: str, *, layer: str | None = None) -> dict[str, Any]:
    """A registry-legal Phase 2 fault entry (parameters per SPEC-204)."""
    parameters: dict[str, Any] = {
        "T2MI_PLP_MISMATCH": {"expected_plp": 0, "actual_plp": 1},
        "BBHEADER_SYNC_FAULT": {"field": "SYNCD", "mode": "corrupt"},
        "BISS_KEY_MISMATCH": {"wrong_session_word": "0123456789ab", "pid_scope": [256]},
        "PMT_PID_DRIFT": {"new_pid_map": {"1": 4608}, "pmt_version_bump": True},
    }[fault_type]
    fault: dict[str, Any] = {
        "fault_id": PHASE2_FAULT_ID,
        "fault_type": fault_type,
        "target_id": {
            "T2MI_PLP_MISMATCH": "enc-0",
            "BBHEADER_SYNC_FAULT": "enc-0",
            "BISS_KEY_MISMATCH": "mux-0",
            "PMT_PID_DRIFT": "mux-0:pid:0x1000",
        }[fault_type],
        "parameters": parameters,
        "activation": (
            {"kind": "packet_index", "packet_index": 30}
            if fault_type in {"BBHEADER_SYNC_FAULT", "PMT_PID_DRIFT"}
            else {"kind": "session_start"}
        ),
        "expected_observations": ["ts.psi_section_observed"],
    }
    if layer is not None:
        fault["layer"] = layer
    return fault


# --- MVP zero-regression ---------------------------------------------------------


def test_mvp_fault_entry_parses_byte_identically_without_a_layer_key() -> None:
    """The pre-#131 MVP face is unchanged: no ``layer`` key, layer "TS"."""
    raw = raw_scenario()
    document = parse_scenario_document(copy.deepcopy(raw))
    (fault,) = document.fault_plan
    assert fault.fault_type == "CC_DISCONTINUITY"
    assert fault.layer == "TS"
    assert fault.target_id == "mux-0:pid:0x0100"
    assert fault.parameters == {"delta": 3}
    assert fault.activation.kind == "packet_index"
    assert fault.activation.packet_index == 120
    assert fault.expected_observations == ("ts.continuity_error",)
    # The raw document (and therefore the pinned content hash / export
    # face) carries no layer key — the layer is semantics, not wire state.
    assert "layer" not in raw["fault_plan"][0]
    assert "layer" not in document.raw["fault_plan"][0]


def test_mvp_fault_type_membership_unchanged() -> None:
    """The MVP four still parse (the KNOWN swap is a pure superset)."""
    for fault_type in (
        "PAT_MISSING",
        "PMT_INVALID_CRC",
        "CC_DISCONTINUITY",
        "PMT_PID_MISMATCH",
    ):
        raw = _scenario_with_fault(
            {
                "fault_id": FAULT_ID,
                "fault_type": fault_type,
                "target_id": "mux-0:pid:0x0100",
                "activation": {"kind": "packet_index", "packet_index": 1},
                "parameters": {},
                "expected_observations": ["ts.psi_section_observed"],
            }
        )
        document = parse_scenario_document(raw)
        assert document.fault_plan[0].fault_type == fault_type
        assert document.fault_plan[0].layer == "TS"


# --- Phase 2 membership + layer derivation ---------------------------------------


@pytest.mark.parametrize(
    ("fault_type", "expected_layer"),
    [
        ("T2MI_PLP_MISMATCH", "T2MI"),
        ("BBHEADER_SYNC_FAULT", "BBFRAME"),
        ("BISS_KEY_MISMATCH", "BISS"),
        ("PMT_PID_DRIFT", "TS"),
    ],
)
def test_phase2_fault_types_parse_with_the_declared_layer(
    fault_type: str, expected_layer: str
) -> None:
    raw = _scenario_with_fault(_phase2_fault(fault_type))
    document = parse_scenario_document(raw)
    (fault,) = document.fault_plan
    assert fault.fault_type == fault_type
    # No ``layer`` key on the wire: the declared layer map is the source
    # (the same derivation the run-wire face performs, #128).
    assert fault.layer == expected_layer
    assert "layer" not in raw["fault_plan"][0]
    assert "layer" not in document.raw["fault_plan"][0]


def test_explicit_layer_key_passes_through() -> None:
    raw = _scenario_with_fault(_phase2_fault("T2MI_PLP_MISMATCH", layer="T2MI"))
    document = parse_scenario_document(raw)
    assert document.fault_plan[0].layer == "T2MI"


def test_explicit_layer_mismatch_still_parses_at_the_schema_face() -> None:
    """A wrong explicit layer is NOT a schema error — the layer-vs-type
    constraint is owned by the faults.registry VALIDATING gate."""
    raw = _scenario_with_fault(_phase2_fault("T2MI_PLP_MISMATCH", layer="TS"))
    document = parse_scenario_document(raw)
    assert document.fault_plan[0].layer == "TS"


def test_malformed_explicit_layer_is_a_schema_error() -> None:
    # The criterion must not reference the (about-to-be-dropped) fault id:
    # the criterion-integrity check raises before the schema-error check,
    # so a referencing criterion would mask the layer error with the
    # integrity cascade.
    raw = _scenario_with_fault(_phase2_fault("T2MI_PLP_MISMATCH", layer=""))
    raw["pass_criteria"] = raw_scenario()["pass_criteria"]
    with pytest.raises(ScenarioSchemaInvalidError) as excinfo:
        parse_scenario_document(raw)
    assert any(
        detail.startswith("$.fault_plan[0].layer")
        for detail in excinfo.value.details
    )


# --- unknown types stay rejected ---------------------------------------------------


def test_unknown_fault_type_still_rejected_with_the_registry_error() -> None:
    raw = _scenario_with_fault(
        {
            "fault_id": FAULT_ID,
            "fault_type": "DEFINITELY_NOT_A_FAULT",
            "target_id": "mux-0:pid:0x0100",
            "activation": {"kind": "packet_index", "packet_index": 1},
            "parameters": {},
            "expected_observations": ["ts.psi_section_observed"],
        }
    )
    # Same precedence note as the malformed-layer test: the criterion must
    # not reference the dropped fault id, or the integrity cascade masks
    # the registry-membership error.
    raw["pass_criteria"] = raw_scenario()["pass_criteria"]
    with pytest.raises(ScenarioSchemaInvalidError) as excinfo:
        parse_scenario_document(raw)
    assert any(
        "fault-type registry" in detail for detail in excinfo.value.details
    )
