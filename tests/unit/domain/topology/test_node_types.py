"""SPEC-003 §Phase2 — backend NodeType registry and config schema tests.

The registry (``domain.topology.node_types``) is the single backend
declaration point for node types.  #121 adds ``t2mi_encapsulator`` and
``t2mi_demux`` with their config schemas (SPEC-600 §5 / SPEC-601 §5 /
SPEC-602 §5); the MVP four entries are unchanged (baseline untouched,
additive).  ``MVP_ENABLED_PLANES`` expands to {MPEG_TS, T2MI} (the RF /
SEC_CONTROL / IP planes stay disabled for Phase 3/4).
"""

from __future__ import annotations

import dataclasses

import pytest
from pydantic import ValidationError

from domain.topology.model import MVP_ENABLED_PLANES, PortDirection, SignalPlane
from domain.topology.node_types import (
    ALL_NODE_TYPES,
    BBFrameBuildParamsDTO,
    MVP_NODE_TYPES,
    NODE_TYPE_T2MI_DEMUX,
    NODE_TYPE_T2MI_ENCAPSULATOR,
    NODE_TYPE_TS_GENERATOR,
    NODE_TYPE_UNKNOWN,
    NodeTypeSpec,
    PHASE2_NODE_TYPES,
    PlpAssignmentDTO,
    PlpAssignmentEntryDTO,
    PlpFilterConfigDTO,
    T2miDemuxConfigDTO,
    T2miEncapsulatorConfigDTO,
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


class TestEnabledPlanes:
    def test_phase2_enables_mpeg_ts_and_t2mi(self) -> None:
        # SPEC-003 §Phase2: {MPEG_TS} → {MPEG_TS, T2MI}; RF / SEC_CONTROL
        # / IP stay disabled (Phase 3/4).
        assert MVP_ENABLED_PLANES == frozenset(
            {SignalPlane.MPEG_TS, SignalPlane.T2MI}
        )


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

    def test_registry_is_the_additive_union(self) -> None:
        assert ALL_NODE_TYPES == MVP_NODE_TYPES + PHASE2_NODE_TYPES
        assert len(ALL_NODE_TYPES) == 6

    def test_lookup_by_wire_string(self) -> None:
        spec = get_node_type("t2mi_encapsulator")
        assert spec is not None and spec.node_type == "t2mi_encapsulator"
        assert get_node_type("tuner") is None

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

    def test_unknown_node_type_reported(self) -> None:
        details = validate_node_config("tuner", {})
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
