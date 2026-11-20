"""SPEC-003 §Phase2/§Phase3 — backend NodeType registry and config schema tests.

The registry (``domain.topology.node_types``) is the single backend
declaration point for node types.  #121 adds ``t2mi_encapsulator`` and
``t2mi_demux`` with their config schemas (SPEC-600 §5 / SPEC-601 §5 /
SPEC-602 §5); #160 adds the Phase 3 RF/SEC trio ``lnb`` / ``tuner`` /
``diseqc_switch`` with their config schemas (SPEC-621 §5 / SPEC-622 §5 /
SPEC-623 §5); the MVP four entries are unchanged (baseline untouched,
additive).  ``MVP_ENABLED_PLANES`` expands to
{MPEG_TS, T2MI, RF, SEC_CONTROL} (SPEC-003 §Phase3; ``IP`` stays disabled
for Phase 4).
"""

from __future__ import annotations

import dataclasses

import pytest
from pydantic import ValidationError

from domain.topology.model import MVP_ENABLED_PLANES, PortDirection, SignalPlane
from domain.topology.node_types import (
    ALL_NODE_TYPES,
    BBFrameBuildParamsDTO,
    DiseqcCommandsDTO,
    DiseqcNibbleWriteDTO,
    DiseqcTargetRegisterDTO,
    LnbConfigDTO,
    LoFrequenciesDTO,
    MVP_NODE_TYPES,
    NODE_TYPE_DISEQC_SWITCH,
    NODE_TYPE_LNB,
    NODE_TYPE_T2MI_DEMUX,
    NODE_TYPE_T2MI_ENCAPSULATOR,
    NODE_TYPE_TS_GENERATOR,
    NODE_TYPE_TUNER,
    NODE_TYPE_UNKNOWN,
    NodeTypeSpec,
    PHASE2_NODE_TYPES,
    PHASE3_NODE_TYPES,
    PlpAssignmentDTO,
    PlpAssignmentEntryDTO,
    PlpFilterConfigDTO,
    ScrConfigDTO,
    SwitchConfigDTO,
    T2miDemuxConfigDTO,
    T2miEncapsulatorConfigDTO,
    TunerConfigDTO,
    TuningRequestDTO,
    UbAssignmentDTO,
    get_node_type,
    validate_node_config,
)

pytestmark = pytest.mark.unit


def _bbframe_params(**overrides) -> dict:
    params = {
        "matype_value": 0x50,
        "upl": 1504,
        "n_ups": 1,
        "issy_mode": "none",
        "npd_enabled": False,
    }
    params.update(overrides)
    return params


def _encapsulator_config(**overrides) -> dict:
    config = {
        "plp_assignment": {
            "entries": [{"plp_id": 0, "source_tag": "business-0"}]
        },
        "bbframe_params": _bbframe_params(),
    }
    config.update(overrides)
    return config


def _demux_config(**overrides) -> dict:
    config = {
        "plp_filter": {"mode": "expected", "expected_plp": 0},
        "strict_crc": True,
    }
    config.update(overrides)
    return config


# --- Phase 3 config builders (SPEC-621/622/623 §5; SC-10 wire shapes) ---------


def _ub_assignment(**overrides) -> dict:
    fields = {
        "tuner_node": "tuner-a",
        "ub_slot": 0,
        "ub_center_freq_mhz": 1210,
        "position": "A",
        "ub_bandwidth_mhz": 46,
    }
    fields.update(overrides)
    return fields


def _scr_config(**overrides) -> dict:
    fields = {
        "protocol": "EN50494",
        "ub_assignments": [
            _ub_assignment(),
            _ub_assignment(
                tuner_node="tuner-b", ub_slot=1, ub_center_freq_mhz=1420,
                position="B",
            ),
        ],
    }
    fields.update(overrides)
    return fields


def _lnb_config(**overrides) -> dict:
    fields = {
        "lnb_kind": "universal",
        "lo_frequencies": {"low_khz": 9750, "high_khz": 10600},
    }
    fields.update(overrides)
    return fields


def _tuning_request(**overrides) -> dict:
    fields = {"frequency_khz": 11_804_000, "polarization": "vertical"}
    fields.update(overrides)
    return fields


def _tuner_config(**overrides) -> dict:
    fields = {"tuning_request": _tuning_request()}
    fields.update(overrides)
    return fields


def _diseqc_commands(**overrides) -> dict:
    fields = {
        "target_register": {"committed": True, "uncommitted": False},
        "nibble_writes": [
            {"register": "committed", "nibble": "high", "value": 0}
        ],
    }
    fields.update(overrides)
    return fields


class TestEnabledPlanes:
    def test_phase3_enables_mpeg_ts_t2mi_rf_and_sec_control(self) -> None:
        # SPEC-003 §Phase3 (ticket #160, ADR-0012): {MPEG_TS, T2MI} →
        # {MPEG_TS, T2MI, RF, SEC_CONTROL}.
        assert MVP_ENABLED_PLANES == frozenset(
            {
                SignalPlane.MPEG_TS,
                SignalPlane.T2MI,
                SignalPlane.RF,
                SignalPlane.SEC_CONTROL,
            }
        )

    def test_ip_plane_stays_disabled(self) -> None:
        # SPEC-003 §Phase3: IP stays disabled (Phase 4).
        assert SignalPlane.IP not in MVP_ENABLED_PLANES


class TestRegistryEntries:
    def test_mvp_entries_unchanged(self) -> None:
        assert [spec.node_type for spec in MVP_NODE_TYPES] == [
            "ts_generator",
            "ts_mux",
            "ts_demux",
            "ts_monitor",
        ]

    def test_phase2_entries_are_the_two_t2mi_types(self) -> None:
        assert [spec.node_type for spec in PHASE2_NODE_TYPES] == [
            "t2mi_encapsulator",
            "t2mi_demux",
        ]

    def test_phase3_entries_are_the_three_rf_sec_types(self) -> None:
        assert [spec.node_type for spec in PHASE3_NODE_TYPES] == [
            "lnb",
            "tuner",
            "diseqc_switch",
        ]

    def test_registry_is_the_three_way_additive_union(self) -> None:
        assert (
            ALL_NODE_TYPES
            == MVP_NODE_TYPES + PHASE2_NODE_TYPES + PHASE3_NODE_TYPES
        )
        assert len(ALL_NODE_TYPES) == 9

    def test_lookup_by_wire_string(self) -> None:
        spec = get_node_type("t2mi_encapsulator")
        assert spec is not None and spec.node_type == "t2mi_encapsulator"
        assert get_node_type("antenna") is None

    def test_specs_are_frozen_dataclasses(self) -> None:
        spec = get_node_type("t2mi_encapsulator")
        assert spec is not None
        assert dataclasses.is_dataclass(spec)
        with pytest.raises(dataclasses.FrozenInstanceError):
            spec.id_prefix = "x"  # type: ignore[misc]


class TestT2miEncapsulatorSpec:
    def test_port_template_matches_spec_401_phase2(self) -> None:
        spec = get_node_type(NODE_TYPE_T2MI_ENCAPSULATOR)
        assert spec is not None
        assert spec.id_prefix == "enc"
        assert spec.label == "T2-MI 封装器"
        assert [
            (port.port_id, port.direction, port.plane, port.max_connections)
            for port in spec.ports
        ] == [
            ("inner_in", PortDirection.INPUT, SignalPlane.MPEG_TS, 1),
            ("t2mi_out", PortDirection.OUTPUT, SignalPlane.T2MI, 1),
        ]

    def test_config_schema_pointer(self) -> None:
        spec = get_node_type(NODE_TYPE_T2MI_ENCAPSULATOR)
        assert spec is not None
        assert spec.config_schema_name == "T2miEncapsulatorConfigDTO"
        assert spec.config_model is T2miEncapsulatorConfigDTO


class TestT2miDemuxSpec:
    def test_port_template_matches_spec_401_phase2(self) -> None:
        spec = get_node_type(NODE_TYPE_T2MI_DEMUX)
        assert spec is not None
        assert spec.id_prefix == "dmx"
        assert spec.label == "T2-MI 解封装器"
        assert [
            (port.port_id, port.direction, port.plane, port.max_connections)
            for port in spec.ports
        ] == [
            ("t2mi_in", PortDirection.INPUT, SignalPlane.T2MI, 1),
            ("inner_out", PortDirection.OUTPUT, SignalPlane.MPEG_TS, 1),
        ]

    def test_config_schema_pointer(self) -> None:
        spec = get_node_type(NODE_TYPE_T2MI_DEMUX)
        assert spec is not None
        assert spec.config_schema_name == "T2miDemuxConfigDTO"
        assert spec.config_model is T2miDemuxConfigDTO


class TestEncapsulatorConfigSchema:
    def test_valid_config_constructs(self) -> None:
        config = T2miEncapsulatorConfigDTO.model_validate(_encapsulator_config())
        assert config.plp_assignment.entries[0].plp_id == 0
        assert config.bbframe_params.n_ups == 1

    def test_extra_keys_rejected(self) -> None:
        with pytest.raises(ValidationError):
            T2miEncapsulatorConfigDTO.model_validate(
                _encapsulator_config(surprise=1)
            )

    def test_empty_assignment_table_rejected(self) -> None:
        with pytest.raises(ValidationError):
            T2miEncapsulatorConfigDTO.model_validate(
                _encapsulator_config(plp_assignment={"entries": []})
            )

    def test_plp_id_outside_8bit_domain_rejected(self) -> None:
        with pytest.raises(ValidationError):
            PlpAssignmentEntryDTO.model_validate(
                {"plp_id": 256, "source_tag": "business-0"}
            )

    def test_empty_source_tag_rejected(self) -> None:
        with pytest.raises(ValidationError):
            PlpAssignmentEntryDTO.model_validate(
                {"plp_id": 0, "source_tag": ""}
            )

    def test_duplicate_source_tag_conflict_rejected(self) -> None:
        with pytest.raises(ValidationError):
            PlpAssignmentDTO.model_validate(
                {
                    "entries": [
                        {"plp_id": 0, "source_tag": "business-0"},
                        {"plp_id": 1, "source_tag": "business-0"},
                    ]
                }
            )

    def test_duplicate_plp_id_conflict_rejected(self) -> None:
        with pytest.raises(ValidationError):
            PlpAssignmentDTO.model_validate(
                {
                    "entries": [
                        {"plp_id": 0, "source_tag": "business-0"},
                        {"plp_id": 0, "source_tag": "business-1"},
                    ]
                }
            )

    def test_matype_field_width_rejected(self) -> None:
        with pytest.raises(ValidationError):
            BBFrameBuildParamsDTO.model_validate(_bbframe_params(matype_value=0x10000))

    def test_n_ups_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            BBFrameBuildParamsDTO.model_validate(_bbframe_params(n_ups=0))


class TestDemuxConfigSchema:
    def test_valid_config_constructs(self) -> None:
        config = T2miDemuxConfigDTO.model_validate(_demux_config())
        assert config.plp_filter.mode == "expected"
        assert config.strict_crc is True

    def test_expected_mode_requires_expected_plp(self) -> None:
        with pytest.raises(ValidationError):
            PlpFilterConfigDTO.model_validate({"mode": "expected"})

    def test_all_mode_allows_null_plp(self) -> None:
        config = PlpFilterConfigDTO.model_validate({"mode": "all"})
        assert config.expected_plp is None

    def test_unknown_mode_rejected(self) -> None:
        with pytest.raises(ValidationError):
            PlpFilterConfigDTO.model_validate({"mode": "some"})

    def test_strict_crc_defaults_true(self) -> None:
        config = T2miDemuxConfigDTO.model_validate(
            {"plp_filter": {"mode": "all"}}
        )
        assert config.strict_crc is True

    def test_extra_keys_rejected(self) -> None:
        with pytest.raises(ValidationError):
            T2miDemuxConfigDTO.model_validate(_demux_config(surprise=1))


class TestValidateNodeConfig:
    def test_valid_configs_pass(self) -> None:
        assert validate_node_config("t2mi_encapsulator", _encapsulator_config()) == ()
        assert validate_node_config("t2mi_demux", _demux_config()) == ()
        assert validate_node_config("lnb", _lnb_config()) == ()
        assert validate_node_config("lnb", _lnb_config(scr=_scr_config())) == ()
        assert validate_node_config("tuner", _tuner_config()) == ()
        assert validate_node_config("diseqc_switch", {"power_pass": "on"}) == ()

    def test_unknown_node_type_reported(self) -> None:
        details = validate_node_config("antenna", {})
        assert len(details) == 1
        assert details[0].startswith(f"{NODE_TYPE_UNKNOWN}:")

    def test_invalid_config_reports_details(self) -> None:
        details = validate_node_config(
            "t2mi_demux", {"plp_filter": {"mode": "bogus"}}
        )
        assert details
        assert all(d.startswith("NODE_CONFIG_INVALID:") for d in details)

    def test_mvp_opaque_configs_stay_valid(self) -> None:
        # MVP types with no domain-side model keep their opaque contract.
        assert validate_node_config("ts_mux", {"anything": [1]}) == ()
        assert validate_node_config("ts_monitor", {}) == ()
        assert validate_node_config("ts_generator", {}) == ()

    def test_specs_declare_the_config_schema_shape_contract(self) -> None:
        for spec in ALL_NODE_TYPES:
            assert isinstance(spec, NodeTypeSpec)
            if spec.config_model is not None:
                assert spec.config_schema_name is not None


# --- Phase 3 registry entries (SPEC-003 §Phase3 / SPEC-621/622/623) -------------


class TestLnbSpec:
    def test_port_template_carries_the_shared_coax_fanout(self) -> None:
        # SPEC-003 §Phase3 / SC-10: coax_out plane SEC_CONTROL with
        # maxConnections=2 carries the A1 dual-tuner shared coax (1:N
        # via the existing per-port cardinality — mechanism zero-extension).
        spec = get_node_type(NODE_TYPE_LNB)
        assert spec is not None
        assert spec.id_prefix == "lnb"
        assert spec.label == "LNB"
        assert [
            (port.port_id, port.direction, port.plane, port.max_connections)
            for port in spec.ports
        ] == [("coax_out", PortDirection.OUTPUT, SignalPlane.SEC_CONTROL, 2)]

    def test_config_schema_pointer(self) -> None:
        spec = get_node_type(NODE_TYPE_LNB)
        assert spec is not None
        assert spec.config_schema_name == "LnbConfigDTO"
        assert spec.config_model is LnbConfigDTO


class TestTunerSpec:
    def test_port_template_input_is_single_feed(self) -> None:
        spec = get_node_type(NODE_TYPE_TUNER)
        assert spec is not None
        assert spec.id_prefix == "tuner"
        assert spec.label == "卫星调谐器"
        assert [
            (port.port_id, port.direction, port.plane, port.max_connections)
            for port in spec.ports
        ] == [("rf_in", PortDirection.INPUT, SignalPlane.SEC_CONTROL, 1)]

    def test_config_schema_pointer(self) -> None:
        spec = get_node_type(NODE_TYPE_TUNER)
        assert spec is not None
        assert spec.config_schema_name == "TunerConfigDTO"
        assert spec.config_model is TunerConfigDTO


class TestDiseqcSwitchSpec:
    def test_port_template_pins_the_single_dc_path(self) -> None:
        # SPEC-622 §7 / SPEC-003 §Phase3: "at most one DC path" is nailed
        # in the registry — the switch's upstream (lnb-side) port takes
        # max_connections=1.
        spec = get_node_type(NODE_TYPE_DISEQC_SWITCH)
        assert spec is not None
        assert spec.id_prefix == "sw"
        assert spec.label == "DiSEqC 开关"
        assert [
            (port.port_id, port.direction, port.plane, port.max_connections)
            for port in spec.ports
        ] == [
            ("coax_in", PortDirection.INPUT, SignalPlane.SEC_CONTROL, 1),
            ("coax_out", PortDirection.OUTPUT, SignalPlane.SEC_CONTROL, 4),
        ]

    def test_config_schema_pointer(self) -> None:
        spec = get_node_type(NODE_TYPE_DISEQC_SWITCH)
        assert spec is not None
        assert spec.config_schema_name == "SwitchConfigDTO"
        assert spec.config_model is SwitchConfigDTO


# --- Phase 3 config schemas ------------------------------------------------------


class TestLnbConfigSchema:
    def test_universal_without_scr_constructs(self) -> None:
        # SC-11 shape: direct dual tuner, no SCR sub-segment.
        config = LnbConfigDTO.model_validate(_lnb_config())
        assert config.lnb_kind == "universal"
        assert config.lo_frequencies.low_khz == 9750
        assert config.lo_frequencies.high_khz == 10600
        assert config.scr is None

    def test_universal_with_scr_constructs(self) -> None:
        # SC-10 shape: built-in SCR with the UB assignment table.
        config = LnbConfigDTO.model_validate(_lnb_config(scr=_scr_config()))
        assert config.scr is not None
        assert config.scr.protocol == "EN50494"
        assert len(config.scr.ub_assignments) == 2

    def test_unknown_lnb_kind_rejected(self) -> None:
        with pytest.raises(ValidationError):
            LnbConfigDTO.model_validate(_lnb_config(lnb_kind="quasi"))

    def test_missing_lo_frequencies_rejected(self) -> None:
        with pytest.raises(ValidationError):
            LnbConfigDTO.model_validate({"lnb_kind": "universal"})

    def test_lo_frequencies_missing_low_khz_rejected(self) -> None:
        with pytest.raises(ValidationError):
            LnbConfigDTO.model_validate(
                _lnb_config(lo_frequencies={"high_khz": 10600})
            )

    def test_non_positive_lo_khz_rejected(self) -> None:
        with pytest.raises(ValidationError):
            LoFrequenciesDTO.model_validate({"low_khz": 0, "high_khz": 10600})

    def test_legacy_cascade_must_not_carry_scr(self) -> None:
        # SPEC-621 §8 prepare rejection: legacy_cascade 携 scr 子段 → 拒.
        with pytest.raises(ValidationError):
            LnbConfigDTO.model_validate(
                _lnb_config(lnb_kind="legacy_cascade", scr=_scr_config())
            )

    def test_extra_keys_rejected(self) -> None:
        with pytest.raises(ValidationError):
            LnbConfigDTO.model_validate(_lnb_config(surprise=1))


class TestScrConfigSchema:
    def test_en50494_assignments_construct(self) -> None:
        scr = ScrConfigDTO.model_validate(_scr_config())
        assert scr.protocol == "EN50494"
        entry = scr.ub_assignments[0]
        assert entry.tuner_node == "tuner-a"
        assert entry.ub_slot == 0
        assert entry.ub_center_freq_mhz == 1210
        assert entry.position == "A"
        assert entry.ub_bandwidth_mhz == 46
        assert entry.pin is None

    def test_en50607_int_positions_construct(self) -> None:
        scr = ScrConfigDTO.model_validate(
            _scr_config(
                protocol="EN50607",
                ub_assignments=[
                    _ub_assignment(position=5),
                    _ub_assignment(
                        tuner_node="tuner-b", ub_slot=1,
                        ub_center_freq_mhz=1420, position=63,
                    ),
                ],
            )
        )
        assert scr.ub_assignments[1].position == 63

    def test_unknown_protocol_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ScrConfigDTO.model_validate(_scr_config(protocol="EN50495"))

    def test_ub_slot_upper_bound_stays_with_the_validator(self) -> None:
        # The ticket splits the layers: the DTO pins ub_slot >= 0 only —
        # the protocol-dependent width (EN 50494 >7 / EN 50607 >31) is
        # SIM_TOPO_UB_SLOT_OUT_OF_RANGE territory (validator rule 3).
        entry = UbAssignmentDTO.model_validate(_ub_assignment(ub_slot=8))
        assert entry.ub_slot == 8
        with pytest.raises(ValidationError):
            UbAssignmentDTO.model_validate(_ub_assignment(ub_slot=-1))

    def test_position_vocabulary_union(self) -> None:
        # str "A"/"B" (EN 50494) or int 0..63 (EN 50607).
        with pytest.raises(ValidationError):
            UbAssignmentDTO.model_validate(_ub_assignment(position="C"))
        with pytest.raises(ValidationError):
            UbAssignmentDTO.model_validate(_ub_assignment(position=64))
        with pytest.raises(ValidationError):
            UbAssignmentDTO.model_validate(_ub_assignment(position=-1))

    def test_position_must_match_scr_protocol(self) -> None:
        with pytest.raises(ValidationError):
            ScrConfigDTO.model_validate(_scr_config(ub_assignments=[
                _ub_assignment(position=0),
            ]))
        with pytest.raises(ValidationError):
            ScrConfigDTO.model_validate(
                _scr_config(
                    protocol="EN50607",
                    ub_assignments=[_ub_assignment(position="A")],
                )
            )

    def test_duplicate_tuner_node_rejected(self) -> None:
        # One tuner holds at most one user band per SCR (SPEC-623 §5
        # tuner→assignment map semantics).
        with pytest.raises(ValidationError):
            ScrConfigDTO.model_validate(_scr_config(ub_assignments=[
                _ub_assignment(),
                _ub_assignment(ub_slot=1, ub_center_freq_mhz=1420,
                               position="B"),
            ]))

    def test_pin_value_domain(self) -> None:
        assert UbAssignmentDTO.model_validate(
            _ub_assignment(pin=255)
        ).pin == 255
        with pytest.raises(ValidationError):
            UbAssignmentDTO.model_validate(_ub_assignment(pin=256))
        with pytest.raises(ValidationError):
            UbAssignmentDTO.model_validate(_ub_assignment(pin=-1))

    def test_ub_bandwidth_defaults_to_46(self) -> None:
        entry = UbAssignmentDTO.model_validate(
            {
                "tuner_node": "tuner-a",
                "ub_slot": 0,
                "ub_center_freq_mhz": 1210,
                "position": "A",
            }
        )
        assert entry.ub_bandwidth_mhz == 46

    def test_empty_assignment_table_is_legal(self) -> None:
        # An SCR with no assignments yet: rule 1 then rejects any tuner
        # claiming a ub_slot (validator layer), the table itself is fine.
        scr = ScrConfigDTO.model_validate(
            _scr_config(ub_assignments=[])
        )
        assert scr.ub_assignments == []


class TestTunerConfigSchema:
    def test_minimal_config_constructs(self) -> None:
        config = TunerConfigDTO.model_validate(_tuner_config())
        assert config.tuning_request.frequency_khz == 11_804_000
        assert config.tuning_request.polarization == "vertical"
        assert config.ub_slot is None
        assert config.diseqc_commands is None

    def test_ub_slot_optional_int(self) -> None:
        config = TunerConfigDTO.model_validate(_tuner_config(ub_slot=1))
        assert config.ub_slot == 1
        with pytest.raises(ValidationError):
            TunerConfigDTO.model_validate(_tuner_config(ub_slot=-1))

    def test_missing_tuning_request_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TunerConfigDTO.model_validate({"ub_slot": 0})

    def test_unknown_polarization_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TunerConfigDTO.model_validate(
                _tuner_config(
                    tuning_request=_tuning_request(polarization="circular")
                )
            )

    def test_diseqc_commands_construct(self) -> None:
        config = TunerConfigDTO.model_validate(
            _tuner_config(diseqc_commands=_diseqc_commands())
        )
        assert config.diseqc_commands is not None
        assert config.diseqc_commands.target_register.committed is True
        assert config.diseqc_commands.nibble_writes[0].nibble == "high"

    def test_nibble_write_register_must_be_declared(self) -> None:
        # SPEC-622 §8: nibble_writes referencing an undeclared register
        # are rejected (prepare-reject semantics at the config layer).
        with pytest.raises(ValidationError):
            DiseqcCommandsDTO.model_validate(_diseqc_commands(
                nibble_writes=[
                    {"register": "uncommitted", "nibble": "low", "value": 1}
                ],
            ))

    def test_nibble_write_vocabulary(self) -> None:
        with pytest.raises(ValidationError):
            DiseqcNibbleWriteDTO.model_validate(
                {"register": "committed", "nibble": "middle", "value": 0}
            )
        with pytest.raises(ValidationError):
            DiseqcNibbleWriteDTO.model_validate(
                {"register": "committed", "nibble": "high", "value": 16}
            )

    def test_target_register_defaults_are_false(self) -> None:
        target = DiseqcTargetRegisterDTO.model_validate({})
        assert target.committed is False
        assert target.uncommitted is False

    def test_extra_keys_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TunerConfigDTO.model_validate(_tuner_config(surprise=1))


class TestSwitchConfigSchema:
    def test_power_pass_constructs(self) -> None:
        assert SwitchConfigDTO.model_validate(
            {"power_pass": "on"}
        ).power_pass == "on"
        assert SwitchConfigDTO.model_validate(
            {"power_pass": "off"}
        ).power_pass == "off"

    def test_unknown_power_pass_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SwitchConfigDTO.model_validate({"power_pass": "through"})

    def test_extra_keys_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SwitchConfigDTO.model_validate(
                {"power_pass": "on", "surprise": 1}
            )
