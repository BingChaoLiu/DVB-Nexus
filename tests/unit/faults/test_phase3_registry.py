"""SPEC-204 §Phase3 — the two state-layer fault primitives (ticket #163).

Registry additive expansion (SPEC-204 0.7.0 §Phase3 revision; ADR-0012
decision 3): ``TONE_RESIDUE`` (RF layer) and ``UB_SLOT_CONFLICT`` (SEC
layer) — the first-version state-layer primitives.  Their execution path
is the pre-evaluation pure transform (``simulation.state.fault_transforms``,
orchestrator ruling A18) — NOT the package-level
``faults.factory.register_transform`` filter mechanism.

Pinned here:

- registry structure — ``PHASE3_FAULT_TYPES``, the additive
  ``KNOWN_FAULT_TYPES`` union, the six-value ``FAULT_LAYERS`` set and the
  declared layers RF/SEC;
- versioned parameter schemas (v1 stays, additive per SPEC-301 §8):
  TONE_RESIDUE ``{tone_actual}``, UB_SLOT_CONFLICT ``{conflicting_ub_slot}``;
- activation: both primitives are session_start only (state-layer faults
  have no packet frame to index);
- targets: node-level forms only — bare node_id, plus the
  ``node_id:attr_name`` third form for UB_SLOT_CONFLICT (ruling A4, the
  SC-10 wire ``tuner-b:ub_slot`` stays verbatim); the pid form is
  rejected;
- expected_observations: the state observation symbols
  (``rf.state_observed`` / ``sec.state_observed``) ride the existing
  non-empty-string contract — the rf.*/sec.* event-registry expansion is
  #164's face (ruling A5);
- the candidate pool (LNB_SHORT_CIRCUIT / SWITCH_MISCONFIG /
  THERMAL_FAULT) stays OUT of the first version — honest non-entry.
"""

from __future__ import annotations

import pytest

from faults.definition import FaultActivation, FaultDefinition
from faults.registry import (
    FAULT_TYPE_UB_SLOT_CONFLICT,
    FAULT_TYPE_TONE_RESIDUE,
    FAULT_LAYERS,
    KNOWN_FAULT_TYPES,
    LAYER_BY_FAULT_TYPE,
    MVP_FAULT_TYPES,
    PHASE2_FAULT_TYPES,
    PHASE3_FAULT_TYPES,
    PARAMETERS_SCHEMA_VERSION,
    validate_fault_definition,
)

pytestmark = pytest.mark.unit

#: The state observation symbols (SPEC-303 §Phase3 namespaces; the event
#: registry expansion itself is #164's face — ruling A5).
OBS_RF_STATE = "rf.state_observed"
OBS_SEC_STATE = "sec.state_observed"

#: The candidate pool (SPEC-204 §Phase3 诚实标注: not in the first version).
CANDIDATE_POOL_TYPES = (
    "LNB_SHORT_CIRCUIT",
    "SWITCH_MISCONFIG",
    "THERMAL_FAULT",
)


def _codes(details: tuple[str, ...]) -> list[str]:
    return [detail.split(":", 1)[0] for detail in details]


def _fault(
    fault_type: str,
    parameters: dict,
    *,
    target_id: str,
    activation: FaultActivation | None = None,
    layer: str | None = None,
    expected_observations: tuple[str, ...] = (),
    fault_id: str = "f-phase3",
) -> FaultDefinition:
    # Default: the declared layer for the type (the dataclass default "TS"
    # only matches the TS-layer primitives); an explicit override keeps the
    # layer-validation tests honest.
    if layer is None:
        layer = LAYER_BY_FAULT_TYPE.get(fault_type, "TS")
    return FaultDefinition(
        fault_id=fault_id,
        fault_type=fault_type,
        target_id=target_id,
        parameters=parameters,
        activation=activation
        or FaultActivation(kind="session_start", packet_index=None),
        expected_observations=expected_observations,
        layer=layer,
    )


def _tone_residue_fault(
    *, target_id: str = "lnb-0", tone_actual: str = "continuous", **kwargs
) -> FaultDefinition:
    return _fault(
        FAULT_TYPE_TONE_RESIDUE,
        {"tone_actual": tone_actual},
        target_id=target_id,
        expected_observations=(OBS_SEC_STATE, OBS_RF_STATE),
        **kwargs,
    )


def _ub_slot_conflict_fault(
    *,
    target_id: str = "tuner-b:ub_slot",
    conflicting_ub_slot: int = 0,
    **kwargs,
) -> FaultDefinition:
    return _fault(
        FAULT_TYPE_UB_SLOT_CONFLICT,
        {"conflicting_ub_slot": conflicting_ub_slot},
        target_id=target_id,
        expected_observations=(OBS_SEC_STATE, OBS_RF_STATE),
        **kwargs,
    )


class TestPhase3RegistryExpansion:
    def test_phase3_fault_types_are_the_two_new_primitives(self) -> None:
        assert PHASE3_FAULT_TYPES == frozenset(
            {FAULT_TYPE_TONE_RESIDUE, FAULT_TYPE_UB_SLOT_CONFLICT}
        )

    def test_known_registry_is_the_three_way_additive_union(self) -> None:
        assert (
            KNOWN_FAULT_TYPES
            == MVP_FAULT_TYPES | PHASE2_FAULT_TYPES | PHASE3_FAULT_TYPES
        )
        assert len(KNOWN_FAULT_TYPES) == 10

    def test_fault_layers_are_the_six_value_phase3_set(self) -> None:
        assert FAULT_LAYERS == (
            "TS",
            "BBFRAME",
            "T2MI",
            "BISS",
            "RF",
            "SEC",
        )

    def test_phase2_layer_prefix_is_untouched(self) -> None:
        assert FAULT_LAYERS[:4] == ("TS", "BBFRAME", "T2MI", "BISS")

    def test_layer_declared_per_fault_type(self) -> None:
        assert LAYER_BY_FAULT_TYPE[FAULT_TYPE_TONE_RESIDUE] == "RF"
        assert LAYER_BY_FAULT_TYPE[FAULT_TYPE_UB_SLOT_CONFLICT] == "SEC"

    def test_schema_version_stays_v1(self) -> None:
        # Additive expansion follows the Phase 2 precedent: new schemas on
        # the same v1 generation (SPEC-301 §8 compatibility rules).
        assert PARAMETERS_SCHEMA_VERSION == 1

    def test_candidate_pool_stays_out_of_the_first_version(self) -> None:
        # SPEC-204 §Phase3 诚实标注: LNB_SHORT_CIRCUIT / SWITCH_MISCONFIG /
        # THERMAL_FAULT are declared candidates, not first-version entries.
        assert set(CANDIDATE_POOL_TYPES).isdisjoint(KNOWN_FAULT_TYPES)


class TestToneResidueSchema:
    """TONE_RESIDUE (RF layer, A2): params = {tone_actual} on the lnb."""

    def test_valid_definition_accepted(self) -> None:
        assert validate_fault_definition(_tone_residue_fault()) == ()

    def test_every_tone_vocabulary_value_accepted(self) -> None:
        for tone in ("none", "continuous", "tone_burst", "data_burst"):
            assert validate_fault_definition(
                _tone_residue_fault(tone_actual=tone)
            ) == ()

    def test_missing_tone_actual_rejected(self) -> None:
        fault = _fault(
            FAULT_TYPE_TONE_RESIDUE,
            {},
            target_id="lnb-0",
            expected_observations=(OBS_RF_STATE,),
        )
        assert _codes(validate_fault_definition(fault)) == [
            "SIM_FAULT_PARAM_INVALID"
        ]

    def test_unknown_parameter_key_rejected(self) -> None:
        fault = _fault(
            FAULT_TYPE_TONE_RESIDUE,
            {"tone_actual": "none", "mode": "x"},
            target_id="lnb-0",
            expected_observations=(OBS_RF_STATE,),
        )
        assert _codes(validate_fault_definition(fault)) == [
            "SIM_FAULT_PARAM_INVALID"
        ]

    @pytest.mark.parametrize("bad_tone", ["22khz", "CONTINUOUS", "", 1, None])
    def test_foreign_tone_value_rejected(self, bad_tone) -> None:
        fault = _tone_residue_fault(tone_actual=bad_tone)
        assert _codes(validate_fault_definition(fault)) == [
            "SIM_FAULT_PARAM_INVALID"
        ]

    def test_packet_index_activation_rejected(self) -> None:
        fault = _tone_residue_fault(
            activation=FaultActivation(kind="packet_index", packet_index=0)
        )
        assert _codes(validate_fault_definition(fault)) == [
            "SIM_FAULT_PARAM_INVALID"
        ]


class TestUbSlotConflictSchema:
    """UB_SLOT_CONFLICT (SEC layer, A1): params = {conflicting_ub_slot}."""

    def test_valid_definition_with_attr_form_target_accepted(self) -> None:
        # The SC-10 wire face: target_id "tuner-b:ub_slot" verbatim (A4).
        assert validate_fault_definition(_ub_slot_conflict_fault()) == ()

    def test_valid_definition_with_bare_node_target_accepted(self) -> None:
        fault = _ub_slot_conflict_fault(target_id="tuner-b")
        assert validate_fault_definition(fault) == ()

    def test_missing_conflicting_ub_slot_rejected(self) -> None:
        fault = _fault(
            FAULT_TYPE_UB_SLOT_CONFLICT,
            {},
            target_id="tuner-b:ub_slot",
            expected_observations=(OBS_RF_STATE,),
        )
        assert _codes(validate_fault_definition(fault)) == [
            "SIM_FAULT_PARAM_INVALID"
        ]

    def test_unknown_parameter_key_rejected(self) -> None:
        fault = _fault(
            FAULT_TYPE_UB_SLOT_CONFLICT,
            {"conflicting_ub_slot": 0, "ub_slot": 1},
            target_id="tuner-b:ub_slot",
            expected_observations=(OBS_RF_STATE,),
        )
        assert _codes(validate_fault_definition(fault)) == [
            "SIM_FAULT_PARAM_INVALID"
        ]

    @pytest.mark.parametrize("bad_slot", [-1, True, False, "0", 1.5, None])
    def test_non_natural_int_slot_rejected(self, bad_slot) -> None:
        fault = _ub_slot_conflict_fault(conflicting_ub_slot=bad_slot)
        assert _codes(validate_fault_definition(fault)) == [
            "SIM_FAULT_PARAM_INVALID"
        ]

    def test_slot_zero_accepted(self) -> None:
        assert validate_fault_definition(
            _ub_slot_conflict_fault(conflicting_ub_slot=0)
        ) == ()

    def test_packet_index_activation_rejected(self) -> None:
        fault = _ub_slot_conflict_fault(
            activation=FaultActivation(kind="packet_index", packet_index=3)
        )
        assert _codes(validate_fault_definition(fault)) == [
            "SIM_FAULT_PARAM_INVALID"
        ]


class TestPhase3LayerValidation:
    def test_wrong_declared_layer_rejected(self) -> None:
        assert _codes(
            validate_fault_definition(_tone_residue_fault(layer="SEC"))
        ) == ["SIM_FAULT_PARAM_INVALID"]
        assert _codes(
            validate_fault_definition(_ub_slot_conflict_fault(layer="RF"))
        ) == ["SIM_FAULT_PARAM_INVALID"]
        assert _codes(
            validate_fault_definition(_tone_residue_fault(layer="TS"))
        ) == ["SIM_FAULT_PARAM_INVALID"]

    def test_mvp_fault_with_new_state_layer_token_rejected(self) -> None:
        # "RF" is now a legal layer token, but PAT_MISSING declares TS —
        # the declared-layer match still binds.
        fault = _fault(
            "PAT_MISSING",
            {},
            target_id="demux-0:pid:0x0000",
            layer="RF",
            expected_observations=("ts.psi_section_observed",),
        )
        assert _codes(validate_fault_definition(fault)) == [
            "SIM_FAULT_PARAM_INVALID"
        ]

    def test_rf_sec_tokens_in_the_layer_set(self) -> None:
        assert "RF" in FAULT_LAYERS
        assert "SEC" in FAULT_LAYERS


class TestPhase3Targets:
    def test_tone_residue_pid_form_target_rejected(self) -> None:
        fault = _tone_residue_fault(target_id="lnb-0:pid:0x0100")
        assert _codes(validate_fault_definition(fault)) == [
            "SIM_FAULT_TARGET_INVALID"
        ]

    def test_ub_slot_conflict_pid_form_target_rejected(self) -> None:
        fault = _ub_slot_conflict_fault(target_id="tuner-b:pid:0x0100")
        assert _codes(validate_fault_definition(fault)) == [
            "SIM_FAULT_TARGET_INVALID"
        ]

    def test_tone_residue_attr_form_target_rejected(self) -> None:
        # TONE_RESIDUE addresses the whole lnb node; attribute addressing
        # stays reserved for UB_SLOT_CONFLICT (dispatch OWN face).
        fault = _tone_residue_fault(target_id="lnb-0:tone_actual")
        assert _codes(validate_fault_definition(fault)) == [
            "SIM_FAULT_TARGET_INVALID"
        ]

    def test_state_layer_types_keep_the_wide_observation_contract(self) -> None:
        # The rf.*/sec.* symbols ride the existing non-empty-string rule;
        # no temporary allowlist (ruling A5 — the event registry is #164).
        assert validate_fault_definition(_tone_residue_fault()) == ()
        assert validate_fault_definition(_ub_slot_conflict_fault()) == ()

    def test_empty_observations_still_rejected(self) -> None:
        fault = _fault(
            FAULT_TYPE_TONE_RESIDUE,
            {"tone_actual": "continuous"},
            target_id="lnb-0",
            expected_observations=(),
        )
        assert _codes(validate_fault_definition(fault)) == [
            "SIM_FAULT_EXPECTED_OBS_MISSING"
        ]


class TestToneVocabularyDriftLock:
    """The faults package mirrors the SPEC-621 tone vocabulary (import
    contract: faults never imports simulation — the lock lives in tests)."""

    def test_registry_tone_values_match_the_evaluator_vocabulary(self) -> None:
        from faults.registry import _TONE_VALUES

        from simulation.state.evaluators._vocab import TONES

        assert _TONE_VALUES == TONES
