"""A1/A14 drift lock — evaluator parse vocabulary vs the domain DTOs (#161).

Ruling A1: the evaluators read ``node.config`` dicts and must NOT import
``domain.topology`` (importlinter contract 8), so the config key names and
vocabularies live as module constants in
``simulation.state.evaluators._vocab``.  Tests sit outside the linter's
root packages and import both sides — this module asserts the mirrored
faces agree, field for field, with:

1. the domain config DTOs (``domain.topology.node_types`` — the
   config-period validation authority), and
2. the #160 validator vocabulary (``simulation.state.validate``), and
3. the #162 unicable mirror constants (``simulation.state.unicable``) —
   ruling A14's third leg.

A drift here means a wire key renamed on one side only — the evaluator
would silently read a missing key and evaluate on defaults.
"""

from __future__ import annotations

import pytest

from simulation.state.evaluators import _vocab
from simulation.state.validate import (
    DISEQC_SWITCH_NODE_TYPE,
    LNB_NODE_TYPE,
    PROTOCOL_CONFIG_KEY,
    SCR_CONFIG_KEY,
    TUNER_NODE_CONFIG_KEY,
    TUNER_NODE_TYPE,
    UB_ASSIGNMENTS_CONFIG_KEY,
    UB_SLOT_CONFIG_KEY,
    UNICABLE_PROTOCOLS,
)
from simulation.state.unicable import (
    FREQUENCY_KHZ_CONFIG_KEY,
    PIN_CONFIG_KEY,
    POLARIZATION_CONFIG_KEY,
    POSITION_CONFIG_KEY,
    TUNER_CONFIG_NODE_KEY,
    UB_CENTER_FREQ_CONFIG_KEY,
    UNIVERSAL_BAND_BOUNDARY_KHZ,
)

pytestmark = pytest.mark.unit


class TestNodeTypeStrings:
    """The evaluator registry keys are the #160 validator's wire strings."""

    def test_evaluator_registry_uses_validator_node_types(self) -> None:
        from simulation.state.evaluators import DEFAULT_EVALUATORS

        assert set(DEFAULT_EVALUATORS) == {
            LNB_NODE_TYPE,
            TUNER_NODE_TYPE,
            DISEQC_SWITCH_NODE_TYPE,
        }

    def test_node_type_strings_match_phase3_registry(self) -> None:
        from domain.topology.node_types import PHASE3_NODE_TYPES

        assert {spec.node_type for spec in PHASE3_NODE_TYPES} == {
            LNB_NODE_TYPE,
            TUNER_NODE_TYPE,
            DISEQC_SWITCH_NODE_TYPE,
        }


class TestLnbConfigKeys:
    """``LnbConfigDTO`` (+ evaluation-time drive keys) field names."""

    def test_dto_field_names_match_vocab(self) -> None:
        from domain.topology.node_types import LnbConfigDTO, LoFrequenciesDTO

        assert _vocab.LNB_KIND_CONFIG_KEY in LnbConfigDTO.model_fields
        assert _vocab.LO_FREQUENCIES_CONFIG_KEY in LnbConfigDTO.model_fields
        assert SCR_CONFIG_KEY in LnbConfigDTO.model_fields
        assert _vocab.LOW_KHZ_CONFIG_KEY in LoFrequenciesDTO.model_fields
        assert _vocab.HIGH_KHZ_CONFIG_KEY in LoFrequenciesDTO.model_fields

    def test_lnb_kind_vocabulary_matches_dto_literal(self) -> None:
        from domain.topology.node_types import LnbConfigDTO

        annotation = LnbConfigDTO.model_fields[_vocab.LNB_KIND_CONFIG_KEY].annotation
        assert set(_vocab.LNB_KINDS) == set(annotation.__args__)

    def test_scr_protocol_vocabulary_matches_dto_literal(self) -> None:
        from domain.topology.node_types import ScrConfigDTO

        annotation = ScrConfigDTO.model_fields[PROTOCOL_CONFIG_KEY].annotation
        assert set(UNICABLE_PROTOCOLS) == set(annotation.__args__)
        assert set(_vocab.SCR_PROTOCOLS) == set(UNICABLE_PROTOCOLS)

    def test_drive_keys_are_evaluation_time_conventions(self) -> None:
        # The drive keys (voltage/tone/short-circuit) are pinned as
        # literals (the evaluator's parse face never renames under us).
        assert _vocab.VOLTAGE_CONFIG_KEY == "voltage"
        assert _vocab.TONE_COMMANDED_CONFIG_KEY == "tone_commanded"
        assert _vocab.TONE_ACTUAL_CONFIG_KEY == "tone_actual"
        assert _vocab.TONE_COMPOSITE_CONFIG_KEY == "tone_composite"
        assert _vocab.SHORT_CIRCUIT_STATE_CONFIG_KEY == "short_circuit_state"

    def test_drive_keys_are_first_class_optional_dto_fields(self) -> None:
        # Ruling A20 (ticket #171): the five lnb drive keys are declared
        # optional ``LnbConfigDTO`` fields — the scenario-calibration and
        # TONE_RESIDUE-transform face is part of the schema authority, no
        # longer an undeclared post-validation bypass.  ``tone_actual``
        # keeps the follow-commanded fallback (default ``None``); the
        # other four default to the evaluator's unconfigured semantics.
        from domain.topology.node_types import LnbConfigDTO

        drive_fields = (
            _vocab.VOLTAGE_CONFIG_KEY,
            _vocab.TONE_COMMANDED_CONFIG_KEY,
            _vocab.TONE_ACTUAL_CONFIG_KEY,
            _vocab.TONE_COMPOSITE_CONFIG_KEY,
            _vocab.SHORT_CIRCUIT_STATE_CONFIG_KEY,
        )
        for field_name in drive_fields:
            assert field_name in LnbConfigDTO.model_fields
        assert LnbConfigDTO.model_fields[_vocab.TONE_ACTUAL_CONFIG_KEY].default is None
        assert LnbConfigDTO.model_fields[_vocab.VOLTAGE_CONFIG_KEY].default == "off"
        assert (
            LnbConfigDTO.model_fields[_vocab.TONE_COMMANDED_CONFIG_KEY].default
            == "none"
        )
        assert (
            LnbConfigDTO.model_fields[_vocab.TONE_COMPOSITE_CONFIG_KEY].default
            == "none"
        )
        assert (
            LnbConfigDTO.model_fields[
                _vocab.SHORT_CIRCUIT_STATE_CONFIG_KEY
            ].default
            == "normal"
        )

    def test_drive_key_vocabularies_match_dto_literals(self) -> None:
        # The evaluator-side vocabulary tuples agree field-for-field with
        # the DTO Literals (the same A20 registration face).
        from domain.topology.node_types import LnbConfigDTO

        lnb_fields = LnbConfigDTO.model_fields
        assert set(_vocab.VOLTAGES) == set(
            lnb_fields[_vocab.VOLTAGE_CONFIG_KEY].annotation.__args__
        )
        assert set(_vocab.TONES) == set(
            lnb_fields[_vocab.TONE_COMMANDED_CONFIG_KEY].annotation.__args__
        )
        assert set(_vocab.TONES) == set(
            lnb_fields[_vocab.TONE_ACTUAL_CONFIG_KEY].annotation.__args__[0].__args__
        )
        assert set(_vocab.TONE_COMPOSITES) == set(
            lnb_fields[_vocab.TONE_COMPOSITE_CONFIG_KEY].annotation.__args__
        )
        assert set(_vocab.SHORT_CIRCUIT_STATES) == set(
            lnb_fields[_vocab.SHORT_CIRCUIT_STATE_CONFIG_KEY].annotation.__args__
        )

    def test_drive_vocabularies_are_spec_literals(self) -> None:
        assert _vocab.VOLTAGES == ("off", "13V", "18V")
        assert _vocab.TONES == ("none", "continuous", "tone_burst", "data_burst")
        assert _vocab.TONE_COMPOSITES == ("none", "continuous_plus_data_burst")
        assert _vocab.BANDS == ("low", "high", "none")
        assert _vocab.POLARIZATION_DELIVERED == ("vertical", "horizontal", "none")
        assert _vocab.SCR_PROTOCOLS == ("EN50494", "EN50607")


class TestTunerConfigKeys:
    """``TunerConfigDTO`` field names vs vocab + the #162 mirror."""

    def test_dto_field_names_match_vocab(self) -> None:
        from domain.topology.node_types import TunerConfigDTO, TuningRequestDTO

        assert _vocab.TUNING_REQUEST_CONFIG_KEY in TunerConfigDTO.model_fields
        assert UB_SLOT_CONFIG_KEY in TunerConfigDTO.model_fields
        assert _vocab.DISEQC_COMMANDS_CONFIG_KEY in TunerConfigDTO.model_fields
        assert FREQUENCY_KHZ_CONFIG_KEY in TuningRequestDTO.model_fields
        assert POLARIZATION_CONFIG_KEY in TuningRequestDTO.model_fields

    def test_polarization_vocabulary_matches_dto_literal(self) -> None:
        from domain.topology.node_types import TuningRequestDTO

        annotation = TuningRequestDTO.model_fields[POLARIZATION_CONFIG_KEY].annotation
        assert set(_vocab.POLARIZATIONS) == set(annotation.__args__)

    def test_tuner_effective_claim_key_is_the_unicable_mirror(self) -> None:
        # A13: the runtime UB claim goes through #162's ub_conflicts, whose
        # tuner-identity key is the #162 mirror constant.
        assert _vocab.OWN_NODE_ID_CONFIG_KEY == TUNER_CONFIG_NODE_KEY == "node_id"

    def test_universal_band_boundary_shared_with_unicable(self) -> None:
        # The band boundary is #162's constant, reused not redefined.
        assert _vocab.BAND_BOUNDARY_KHZ == UNIVERSAL_BAND_BOUNDARY_KHZ == 11_700_000


class TestSwitchConfigKeys:
    """``SwitchConfigDTO`` / command-intent field names."""

    def test_dto_field_names_match_vocab(self) -> None:
        from domain.topology.node_types import (
            DiseqcCommandsDTO,
            DiseqcTargetRegisterDTO,
            SwitchConfigDTO,
        )

        assert _vocab.POWER_PASS_CONFIG_KEY in SwitchConfigDTO.model_fields
        assert _vocab.DISEQC_COMMANDS_CONFIG_KEY not in SwitchConfigDTO.model_fields
        assert _vocab.TARGET_REGISTER_CONFIG_KEY in DiseqcCommandsDTO.model_fields
        assert _vocab.NIBBLE_WRITES_CONFIG_KEY in DiseqcCommandsDTO.model_fields
        assert _vocab.COMMITTED_CONFIG_KEY in DiseqcTargetRegisterDTO.model_fields
        assert _vocab.UNCOMMITTED_CONFIG_KEY in DiseqcTargetRegisterDTO.model_fields

    def test_nibble_write_wire_keys_match_dto_alias(self) -> None:
        from domain.topology.node_types import DiseqcNibbleWriteDTO

        register_field = DiseqcNibbleWriteDTO.model_fields["register_id"]
        assert register_field.alias == _vocab.REGISTER_CONFIG_KEY == "register"
        assert _vocab.NIBBLE_CONFIG_KEY in DiseqcNibbleWriteDTO.model_fields
        assert _vocab.VALUE_CONFIG_KEY in DiseqcNibbleWriteDTO.model_fields

    def test_register_and_nibble_vocabularies(self) -> None:
        assert _vocab.REGISTERS == ("committed", "uncommitted")
        assert _vocab.NIBBLES == ("high", "low")
        assert _vocab.POWER_PASS_VALUES == ("on", "off")

    def test_command_intent_channel_key(self) -> None:
        # The switch's intent channel key (config primary / A2-metrics
        # fallback) is the tuner DTO's field name.
        assert _vocab.DISEQC_COMMANDS_CONFIG_KEY == "diseqc_commands"


class TestUbAssignmentKeys:
    """``UbAssignmentDTO`` field names across all three mirror sites."""

    def test_validator_keys_match_dto(self) -> None:
        from domain.topology.node_types import UbAssignmentDTO

        assert TUNER_NODE_CONFIG_KEY in UbAssignmentDTO.model_fields
        assert UB_SLOT_CONFIG_KEY in UbAssignmentDTO.model_fields

    def test_unicable_mirror_keys_match_dto(self) -> None:
        # A14: the #162 mirror constants join the three-way lock.
        from domain.topology.node_types import UbAssignmentDTO

        assert UB_CENTER_FREQ_CONFIG_KEY in UbAssignmentDTO.model_fields
        assert POSITION_CONFIG_KEY in UbAssignmentDTO.model_fields
        assert PIN_CONFIG_KEY in UbAssignmentDTO.model_fields

    def test_scr_table_keys_match_dto(self) -> None:
        from domain.topology.node_types import ScrConfigDTO

        assert UB_ASSIGNMENTS_CONFIG_KEY in ScrConfigDTO.model_fields
        assert PROTOCOL_CONFIG_KEY in ScrConfigDTO.model_fields


class TestMetricKeySets:
    """The per-node metric key sets — the #164 payload-registration source
    (each set pinned as a literal; #164 registers rf./sec. payload schemas
    from exactly these)."""

    def test_lnb_metric_keys(self) -> None:
        # SPEC-621 §5 list + SPEC-303 §Phase3 lnb snapshot's
        # ub_assignments; ``sat_selected`` is the legacy additive key.
        assert _vocab.LNB_METRIC_KEYS == (
            "voltage",
            "tone_commanded",
            "tone_actual",
            "tone_composite",
            "band_selected",
            "lo_frequency_khz",
            "polarization_delivered",
            "short_circuit_state",
            "ub_assignments",
        )
        assert _vocab.LNB_SAT_SELECTED_METRIC_KEY == "sat_selected"

    def test_tuner_metric_keys(self) -> None:
        # SPEC-620 §5 list + the §8 stale flag (REPORT-frozen: present on
        # every snapshot, true iff unlocked).
        assert _vocab.TUNER_METRIC_KEYS == (
            "lock_state",
            "if_frequency_khz",
            "ber_state",
            "locked_transponder_id",
            "stale",
        )

    def test_switch_metric_keys(self) -> None:
        assert _vocab.SWITCH_METRIC_KEYS == (
            "committed_switch_state",
            "uncommitted_switch_state",
            "port_selected",
            "power_pass",
        )

    def test_signal_plumbing_keys(self) -> None:
        # The lnb → tuner A2-channel plumbing keys (REPORT-frozen): the
        # facts downstream evaluators need that the node config alone
        # cannot expose.
        assert _vocab.LNB_KIND_METRIC_KEY == "lnb_kind"
        assert _vocab.LO_PLAN_LOW_METRIC_KEY == "lo_plan_low_khz"
        assert _vocab.LO_PLAN_HIGH_METRIC_KEY == "lo_plan_high_khz"
        assert _vocab.SCR_PROTOCOL_METRIC_KEY == "scr_protocol"


class TestSlotModelConstants:
    """The IF-slot arithmetic constants (REPORT-frozen model)."""

    def test_if_window(self) -> None:
        assert _vocab.IF_SLOT_LOW_KHZ == 950_000
        assert _vocab.IF_SLOT_HIGH_KHZ == 1_950_000

    def test_high_arm_floor(self) -> None:
        assert _vocab.HIGH_ARM_IF_FLOOR_KHZ == 1_100_000

    def test_protection_band_width(self) -> None:
        assert _vocab.PROTECTION_BAND_WIDTH_KHZ == 3_000

    def test_port_select_mask(self) -> None:
        assert _vocab.PORT_SELECT_MASK == 0x03
        assert _vocab.REGISTER_NIBBLE_SHIFT == 4

    def test_lock_and_ber_vocabularies(self) -> None:
        assert _vocab.LOCK_STATES == ("unlocked", "locked")
        assert _vocab.BER_STATES == ("normal", "elevated", "severe")
