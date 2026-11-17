"""SPEC-204 §Phase2 — the four Phase 2 fault primitives and their schemas.

Registry additive expansion (ticket #121): ``T2MI_PLP_MISMATCH`` /
``BBHEADER_SYNC_FAULT`` / ``BISS_KEY_MISMATCH`` / ``PMT_PID_DRIFT``, each
with a versioned parameter schema, a declared pipeline ``layer`` (the
SPEC-204 §Phase2 / ADR-0010 §3 set {TS, BBFRAME, T2MI, BISS}) and the
per-type activation set pinned by the revision:

- ``T2MI_PLP_MISMATCH`` (T2MI layer): expected_plp/actual_plp + optional
  plp_version_switch; activation session_start (default) | packet_index;
- ``BBHEADER_SYNC_FAULT`` (BBFRAME layer): field (six BBHEADER fields) +
  mode (corrupt|shift); activation packet_index only;
- ``BISS_KEY_MISMATCH`` (BISS layer): wrong_session_word | wrong_esw /
  wrong_injected_id variants + pid_scope; activation session_start only;
- ``PMT_PID_DRIFT`` (TS layer): new_pid_map + pmt_version_bump; activation
  packet_index only.

The MVP four primitives stay untouched (baseline-frozen discipline; the
Phase 2 expansion is the revision's explicit expansion port).  The
``expected_observations`` symbol names referenced below are PLACEHOLDERS
until #129 lands the four observation namespaces — the validator only
enforces the existing "non-empty string" contract (declared placeholder
convention, see the #121 report).
"""

from __future__ import annotations

import pytest

from faults.definition import FaultActivation, FaultDefinition
from faults.registry import (
    FAULT_TYPE_BBHEADER_SYNC_FAULT,
    FAULT_TYPE_BISS_KEY_MISMATCH,
    FAULT_TYPE_CC_DISCONTINUITY,
    FAULT_TYPE_PAT_MISSING,
    FAULT_TYPE_PMT_INVALID_CRC,
    FAULT_TYPE_PMT_PID_DRIFT,
    FAULT_TYPE_PMT_PID_MISMATCH,
    FAULT_TYPE_T2MI_PLP_MISMATCH,
    FAULT_LAYERS,
    KNOWN_FAULT_TYPES,
    LAYER_BY_FAULT_TYPE,
    MVP_FAULT_TYPES,
    PHASE2_FAULT_TYPES,
    validate_fault_definition,
)


pytestmark = pytest.mark.unit

# Placeholders until #129 registers the four namespaces (see module docstring).
OBS_T2MI = "t2mi.plp_mismatch"
OBS_BBFRAME = "bbframe.recovery_failed"
OBS_BISS = "biss.descramble_failed"
OBS_PMT_DRIFT = "ts.pmt_pid_drift"


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
    fault_id: str = "f-phase2",
) -> FaultDefinition:
    # Default: the declared layer for the type (the default "TS" only
    # matches MVP primitives); explicit override keeps layer-validation
    # tests honest.
    if layer is None:
        layer = LAYER_BY_FAULT_TYPE.get(fault_type, "TS")
    kwargs: dict = {"layer": layer}
    return FaultDefinition(
        fault_id=fault_id,
        fault_type=fault_type,
        target_id=target_id,
        parameters=parameters,
        activation=activation
        or FaultActivation(kind="session_start", packet_index=None),
        expected_observations=expected_observations,
        **kwargs,
    )


class TestRegistryExpansion:
    def test_phase2_fault_types_are_the_four_new_primitives(self) -> None:
        assert PHASE2_FAULT_TYPES == frozenset(
            {
                FAULT_TYPE_T2MI_PLP_MISMATCH,
                FAULT_TYPE_BBHEADER_SYNC_FAULT,
                FAULT_TYPE_BISS_KEY_MISMATCH,
                FAULT_TYPE_PMT_PID_DRIFT,
            }
        )

    def test_mvp_registry_stays_the_four_mvp_primitives(self) -> None:
        assert MVP_FAULT_TYPES == frozenset(
            {
                FAULT_TYPE_PAT_MISSING,
                FAULT_TYPE_PMT_INVALID_CRC,
                FAULT_TYPE_CC_DISCONTINUITY,
                FAULT_TYPE_PMT_PID_MISMATCH,
            }
        )

    def test_known_registry_is_the_additive_union(self) -> None:
        assert KNOWN_FAULT_TYPES == MVP_FAULT_TYPES | PHASE2_FAULT_TYPES
        assert len(KNOWN_FAULT_TYPES) == 8

    def test_fault_layers_are_the_phase2_layer_set(self) -> None:
        assert FAULT_LAYERS == ("TS", "BBFRAME", "T2MI", "BISS")

    def test_layer_declared_per_fault_type(self) -> None:
        assert LAYER_BY_FAULT_TYPE[FAULT_TYPE_T2MI_PLP_MISMATCH] == "T2MI"
        assert LAYER_BY_FAULT_TYPE[FAULT_TYPE_BBHEADER_SYNC_FAULT] == "BBFRAME"
        assert LAYER_BY_FAULT_TYPE[FAULT_TYPE_BISS_KEY_MISMATCH] == "BISS"
        assert LAYER_BY_FAULT_TYPE[FAULT_TYPE_PMT_PID_DRIFT] == "TS"
        for mvp_type in MVP_FAULT_TYPES:
            assert LAYER_BY_FAULT_TYPE[mvp_type] == "TS"


class TestT2miPlpMismatchSchema:
    def _fault(self, parameters: dict, **kwargs) -> FaultDefinition:
        kwargs.setdefault("target_id", "t2mi-demux-0")
        kwargs.setdefault(
            "expected_observations", (OBS_T2MI,)
        )
        return _fault(FAULT_TYPE_T2MI_PLP_MISMATCH, parameters, **kwargs)

    def test_valid_definition_accepted(self) -> None:
        assert validate_fault_definition(
            self._fault({"expected_plp": 0, "actual_plp": 1})
        ) == ()

    def test_packet_index_activation_allowed(self) -> None:
        details = validate_fault_definition(
            self._fault(
                {"expected_plp": 0, "actual_plp": 1},
                activation=FaultActivation(kind="packet_index", packet_index=10),
            )
        )
        assert details == ()

    def test_missing_required_plp_keys_rejected(self) -> None:
        details = validate_fault_definition(self._fault({"expected_plp": 0}))
        assert _codes(details) == ["SIM_FAULT_PARAM_INVALID"]

    def test_unknown_parameter_key_rejected(self) -> None:
        details = validate_fault_definition(
            self._fault({"expected_plp": 0, "actual_plp": 1, "surprise": 1})
        )
        assert _codes(details) == ["SIM_FAULT_PARAM_INVALID"]

    @pytest.mark.parametrize("bad_plp", [-1, 256, "0", True])
    def test_plp_id_outside_8bit_value_domain_rejected(self, bad_plp) -> None:
        details = validate_fault_definition(
            self._fault({"expected_plp": bad_plp, "actual_plp": 1})
        )
        # True also trips the ==1 no-op guard; every detail is param-level.
        assert set(_codes(details)) == {"SIM_FAULT_PARAM_INVALID"}

    def test_identical_plp_pair_is_a_no_op_rejection(self) -> None:
        details = validate_fault_definition(
            self._fault({"expected_plp": 3, "actual_plp": 3})
        )
        assert _codes(details) == ["SIM_FAULT_PARAM_INVALID"]

    def test_plp_version_switch_must_be_bool(self) -> None:
        details = validate_fault_definition(
            self._fault(
                {"expected_plp": 0, "actual_plp": 1, "plp_version_switch": "yes"}
            )
        )
        assert _codes(details) == ["SIM_FAULT_PARAM_INVALID"]

    def test_plp_version_switch_true_accepted(self) -> None:
        details = validate_fault_definition(
            self._fault(
                {"expected_plp": 0, "actual_plp": 1, "plp_version_switch": True}
            )
        )
        assert details == ()


class TestBBHeaderSyncFaultSchema:
    def _fault(self, parameters: dict, **kwargs) -> FaultDefinition:
        kwargs.setdefault("target_id", "t2mi-enc-0")
        kwargs.setdefault("expected_observations", (OBS_BBFRAME,))
        return _fault(FAULT_TYPE_BBHEADER_SYNC_FAULT, parameters, **kwargs)

    def test_valid_definition_accepted(self) -> None:
        details = validate_fault_definition(
            self._fault(
                {"field": "SYNCD", "mode": "corrupt"},
                activation=FaultActivation(kind="packet_index", packet_index=5),
            )
        )
        assert details == ()

    @pytest.mark.parametrize(
        "field",
        ["MATYPE", "UPL", "DFL", "SYNC", "SYNCD", "CRC-8"],
    )
    def test_every_bbheader_field_accepted(self, field: str) -> None:
        details = validate_fault_definition(
            self._fault(
                {"field": field, "mode": "shift"},
                activation=FaultActivation(kind="packet_index", packet_index=0),
            )
        )
        assert details == ()

    def test_unknown_field_rejected(self) -> None:
        details = validate_fault_definition(
            self._fault(
                {"field": "SYNCD2", "mode": "corrupt"},
                activation=FaultActivation(kind="packet_index", packet_index=0),
            )
        )
        assert _codes(details) == ["SIM_FAULT_PARAM_INVALID"]

    def test_unknown_mode_rejected(self) -> None:
        details = validate_fault_definition(
            self._fault(
                {"field": "MATYPE", "mode": "flip"},
                activation=FaultActivation(kind="packet_index", packet_index=0),
            )
        )
        assert _codes(details) == ["SIM_FAULT_PARAM_INVALID"]

    def test_missing_mode_rejected(self) -> None:
        details = validate_fault_definition(
            self._fault(
                {"field": "MATYPE"},
                activation=FaultActivation(kind="packet_index", packet_index=0),
            )
        )
        assert _codes(details) == ["SIM_FAULT_PARAM_INVALID"]

    def test_session_start_activation_rejected(self) -> None:
        # The revision pins BBHEADER_SYNC_FAULT to packet_index activation.
        details = validate_fault_definition(
            self._fault(
                {"field": "MATYPE", "mode": "corrupt"},
                activation=FaultActivation(kind="session_start"),
            )
        )
        assert _codes(details) == ["SIM_FAULT_PARAM_INVALID"]

    def test_stream_level_target_rejected(self) -> None:
        # BBFrame is a node-internal layer: no pid on the shared frame.
        details = validate_fault_definition(
            self._fault(
                {"field": "MATYPE", "mode": "corrupt"},
                target_id="t2mi-enc-0:pid:0x0100",
                activation=FaultActivation(kind="packet_index", packet_index=0),
            )
        )
        assert _codes(details) == ["SIM_FAULT_TARGET_INVALID"]


class TestBissKeyMismatchSchema:
    def _fault(self, parameters: dict, **kwargs) -> FaultDefinition:
        kwargs.setdefault("target_id", "biss-scrambler-0")
        kwargs.setdefault("expected_observations", (OBS_BISS,))
        return _fault(FAULT_TYPE_BISS_KEY_MISMATCH, parameters, **kwargs)

    def test_mode1_variant_accepted(self) -> None:
        details = validate_fault_definition(
            self._fault(
                {"wrong_session_word": "A13DBC42908F", "pid_scope": [0x0100]}
            )
        )
        assert details == ()

    def test_mode_e_esw_variant_accepted(self) -> None:
        details = validate_fault_definition(
            self._fault(
                {
                    "wrong_esw": "0123456789ABCDEF",
                    "wrong_injected_id": "00112233445566778899AABBCCDDEEFF",
                    "pid_scope": [0x0100, 0x0101],
                }
            )
        )
        assert details == ()

    def test_lowercase_hex_accepted(self) -> None:
        details = validate_fault_definition(
            self._fault(
                {"wrong_session_word": "a13dbc42908f", "pid_scope": [256]}
            )
        )
        assert details == ()

    def test_missing_pid_scope_rejected(self) -> None:
        details = validate_fault_definition(
            self._fault({"wrong_session_word": "A13DBC42908F"})
        )
        assert _codes(details) == ["SIM_FAULT_PARAM_INVALID"]

    def test_empty_pid_scope_rejected(self) -> None:
        details = validate_fault_definition(
            self._fault({"wrong_session_word": "A13DBC42908F", "pid_scope": []})
        )
        assert _codes(details) == ["SIM_FAULT_PARAM_INVALID"]

    def test_session_word_must_be_12_hex(self) -> None:
        details = validate_fault_definition(
            self._fault({"wrong_session_word": "A13DBC42908", "pid_scope": [0x100]})
        )
        assert _codes(details) == ["SIM_FAULT_PARAM_INVALID"]

    def test_esw_must_be_16_hex(self) -> None:
        details = validate_fault_definition(
            self._fault({"wrong_esw": "0123456789ABCDEF0", "pid_scope": [0x100]})
        )
        assert _codes(details) == ["SIM_FAULT_PARAM_INVALID"]

    def test_injected_id_must_be_32_hex(self) -> None:
        details = validate_fault_definition(
            self._fault(
                {
                    "wrong_esw": "0123456789ABCDEF",
                    "wrong_injected_id": "00112233",
                    "pid_scope": [0x100],
                }
            )
        )
        assert _codes(details) == ["SIM_FAULT_PARAM_INVALID"]

    def test_mode1_and_mode_e_variants_are_mutually_exclusive(self) -> None:
        details = validate_fault_definition(
            self._fault(
                {
                    "wrong_session_word": "A13DBC42908F",
                    "wrong_esw": "0123456789ABCDEF",
                    "pid_scope": [0x100],
                }
            )
        )
        assert _codes(details) == ["SIM_FAULT_PARAM_INVALID"]

    def test_no_key_variant_rejected(self) -> None:
        details = validate_fault_definition(self._fault({"pid_scope": [0x100]}))
        assert _codes(details) == ["SIM_FAULT_PARAM_INVALID"]

    def test_packet_index_activation_rejected(self) -> None:
        details = validate_fault_definition(
            self._fault(
                {"wrong_session_word": "A13DBC42908F", "pid_scope": [0x100]},
                activation=FaultActivation(kind="packet_index", packet_index=0),
            )
        )
        assert _codes(details) == ["SIM_FAULT_PARAM_INVALID"]

    def test_pid_scope_entries_must_be_13bit_ints(self) -> None:
        details = validate_fault_definition(
            self._fault(
                {"wrong_session_word": "A13DBC42908F", "pid_scope": [0x2000]}
            )
        )
        assert _codes(details) == ["SIM_FAULT_PARAM_INVALID"]
        details = validate_fault_definition(
            self._fault(
                {"wrong_session_word": "A13DBC42908F", "pid_scope": [1.5]}
            )
        )
        assert _codes(details) == ["SIM_FAULT_PARAM_INVALID"]


class TestPmtPidDriftSchema:
    def _fault(self, parameters: dict, **kwargs) -> FaultDefinition:
        kwargs.setdefault("target_id", "demux-0:pid:0x1000")
        kwargs.setdefault("expected_observations", (OBS_PMT_DRIFT,))
        kwargs.setdefault(
            "activation", FaultActivation(kind="packet_index", packet_index=20)
        )
        return _fault(FAULT_TYPE_PMT_PID_DRIFT, parameters, **kwargs)

    def test_valid_definition_accepted(self) -> None:
        details = validate_fault_definition(
            self._fault(
                {"new_pid_map": {1: 0x0900}, "pmt_version_bump": True}
            )
        )
        assert details == ()

    def test_missing_new_pid_map_rejected(self) -> None:
        details = validate_fault_definition(
            self._fault({"pmt_version_bump": True})
        )
        assert _codes(details) == ["SIM_FAULT_PARAM_INVALID"]

    def test_missing_pmt_version_bump_rejected(self) -> None:
        details = validate_fault_definition(
            self._fault({"new_pid_map": {1: 0x0900}})
        )
        assert _codes(details) == ["SIM_FAULT_PARAM_INVALID"]

    def test_empty_pid_map_rejected(self) -> None:
        details = validate_fault_definition(
            self._fault({"new_pid_map": {}, "pmt_version_bump": False})
        )
        assert _codes(details) == ["SIM_FAULT_PARAM_INVALID"]

    def test_program_number_must_be_positive_int(self) -> None:
        details = validate_fault_definition(
            self._fault(
                {"new_pid_map": {0: 0x0900}, "pmt_version_bump": False}
            )
        )
        assert _codes(details) == ["SIM_FAULT_PARAM_INVALID"]

    def test_drifted_pid_must_be_non_reserved_13bit(self) -> None:
        details = validate_fault_definition(
            self._fault(
                {"new_pid_map": {1: 0x0000}, "pmt_version_bump": False}
            )
        )
        assert _codes(details) == ["SIM_FAULT_PARAM_INVALID"]
        details = validate_fault_definition(
            self._fault(
                {"new_pid_map": {1: 0x1FFF}, "pmt_version_bump": False}
            )
        )
        assert _codes(details) == ["SIM_FAULT_PARAM_INVALID"]

    def test_pmt_version_bump_must_be_bool(self) -> None:
        details = validate_fault_definition(
            self._fault(
                {"new_pid_map": {1: 0x0900}, "pmt_version_bump": 1}
            )
        )
        assert _codes(details) == ["SIM_FAULT_PARAM_INVALID"]

    # --- JSON-wire digit-string keys (ticket #131 orchestrator ruling) ---
    # JSON object keys are always strings; an all-digit ASCII string key
    # coerces to its int program number so the scenario wire can carry the
    # mapping.  The Python int-key path above is unchanged.

    def test_digit_string_program_keys_accepted(self) -> None:
        details = validate_fault_definition(
            self._fault(
                {"new_pid_map": {"1": 0x0900}, "pmt_version_bump": True}
            )
        )
        assert details == ()

    def test_multi_digit_string_keys_accepted(self) -> None:
        details = validate_fault_definition(
            self._fault(
                {"new_pid_map": {"1": 0x0900, "2": 0x0901},
                 "pmt_version_bump": False}
            )
        )
        assert details == ()

    def test_non_digit_string_program_keys_rejected(self) -> None:
        details = validate_fault_definition(
            self._fault(
                {"new_pid_map": {"program-1": 0x0900},
                 "pmt_version_bump": False}
            )
        )
        assert _codes(details) == ["SIM_FAULT_PARAM_INVALID"]

    def test_zero_as_digit_string_key_rejected(self) -> None:
        details = validate_fault_definition(
            self._fault(
                {"new_pid_map": {"0": 0x0900}, "pmt_version_bump": False}
            )
        )
        assert _codes(details) == ["SIM_FAULT_PARAM_INVALID"]

    def test_negative_digit_string_key_rejected(self) -> None:
        details = validate_fault_definition(
            self._fault(
                {"new_pid_map": {"-1": 0x0900}, "pmt_version_bump": False}
            )
        )
        assert _codes(details) == ["SIM_FAULT_PARAM_INVALID"]

    def test_bool_program_key_rejected(self) -> None:
        details = validate_fault_definition(
            self._fault(
                {"new_pid_map": {True: 0x0900}, "pmt_version_bump": False}
            )
        )
        assert _codes(details) == ["SIM_FAULT_PARAM_INVALID"]

    def test_session_start_activation_rejected(self) -> None:
        details = validate_fault_definition(
            self._fault(
                {"new_pid_map": {1: 0x0900}, "pmt_version_bump": False},
                activation=FaultActivation(kind="session_start"),
            )
        )
        assert _codes(details) == ["SIM_FAULT_PARAM_INVALID"]


class TestLayerValidation:
    def test_phase2_faults_require_their_declared_layer(self) -> None:
        # The dataclass default ("TS") does not match the T2MI-layer
        # primitive — an explicit layer="TS" shows the mismatch honestly.
        definition = _fault(
            FAULT_TYPE_T2MI_PLP_MISMATCH,
            {"expected_plp": 0, "actual_plp": 1},
            target_id="t2mi-demux-0",
            expected_observations=(OBS_T2MI,),
            layer="TS",
        )
        details = validate_fault_definition(definition)
        assert _codes(details) == ["SIM_FAULT_PARAM_INVALID"]

    def test_matching_explicit_layer_accepted(self) -> None:
        definition = _fault(
            FAULT_TYPE_BISS_KEY_MISMATCH,
            {"wrong_session_word": "A13DBC42908F", "pid_scope": [0x0100]},
            target_id="biss-scrambler-0",
            expected_observations=(OBS_BISS,),
            layer="BISS",
        )
        assert validate_fault_definition(definition) == ()

    def test_unknown_layer_token_rejected(self) -> None:
        definition = _fault(
            FAULT_TYPE_PMT_PID_DRIFT,
            {"new_pid_map": {1: 0x0900}, "pmt_version_bump": False},
            target_id="demux-0:pid:0x1000",
            expected_observations=(OBS_PMT_DRIFT,),
            layer="IP",
            activation=FaultActivation(kind="packet_index", packet_index=0),
        )
        assert _codes(validate_fault_definition(definition)) == [
            "SIM_FAULT_PARAM_INVALID"
        ]

    def test_mvp_fault_with_non_ts_layer_rejected(self) -> None:
        definition = _fault(
            FAULT_TYPE_PAT_MISSING,
            {},
            target_id="demux-0:pid:0x0000",
            expected_observations=("ts.psi_section_observed",),
            layer="T2MI",
        )
        assert _codes(validate_fault_definition(definition)) == [
            "SIM_FAULT_PARAM_INVALID"
        ]

    def test_mvp_faults_with_default_layer_stay_valid(self) -> None:
        # Backward compatibility: MVP plans constructed without a layer
        # (default "TS") validate exactly as before.
        definition = _fault(
            FAULT_TYPE_CC_DISCONTINUITY,
            {"delta": 2},
            target_id="demux-0:pid:0x0100",
            expected_observations=("ts.continuity_error",),
        )
        assert validate_fault_definition(definition) == ()


class TestPhase2Targets:
    def test_ts_layer_drift_requires_stream_level_target(self) -> None:
        details = validate_fault_definition(
            _fault(
                FAULT_TYPE_PMT_PID_DRIFT,
                {"new_pid_map": {1: 0x0900}, "pmt_version_bump": False},
                target_id="demux-0",
                expected_observations=(OBS_PMT_DRIFT,),
                activation=FaultActivation(kind="packet_index", packet_index=0),
            )
        )
        assert _codes(details) == ["SIM_FAULT_TARGET_INVALID"]

    def test_t2mi_layer_accepts_node_level_target(self) -> None:
        details = validate_fault_definition(
            _fault(
                FAULT_TYPE_T2MI_PLP_MISMATCH,
                {"expected_plp": 0, "actual_plp": 1},
                target_id="t2mi-demux-0",
                expected_observations=(OBS_T2MI,),
            )
        )
        assert details == ()


class TestPlaceholderObservations:
    def test_placeholder_symbol_names_pass_the_wide_contract(self) -> None:
        # expected_observations stays a non-empty-string contract until
        # #129 registers the four namespaces; placeholders are accepted.
        cases = (
            (
                FAULT_TYPE_T2MI_PLP_MISMATCH,
                {"expected_plp": 0, "actual_plp": 1},
                "t2mi-demux-0",
                (OBS_T2MI,),
                None,
                FaultActivation(kind="session_start"),
            ),
            (
                FAULT_TYPE_BBHEADER_SYNC_FAULT,
                {"field": "SYNCD", "mode": "corrupt"},
                "t2mi-enc-0",
                (OBS_BBFRAME,),
                None,
                FaultActivation(kind="packet_index", packet_index=1),
            ),
            (
                FAULT_TYPE_BISS_KEY_MISMATCH,
                {"wrong_session_word": "A13DBC42908F", "pid_scope": [0x100]},
                "biss-scrambler-0",
                (OBS_BISS,),
                "BISS",
                FaultActivation(kind="session_start"),
            ),
            (
                FAULT_TYPE_PMT_PID_DRIFT,
                {"new_pid_map": {1: 0x0900}, "pmt_version_bump": True},
                "demux-0:pid:0x1000",
                (OBS_PMT_DRIFT,),
                None,
                FaultActivation(kind="packet_index", packet_index=2),
            ),
        )
        for fault_type, params, target, obs, layer, activation in cases:
            definition = _fault(
                fault_type,
                params,
                target_id=target,
                expected_observations=obs,
                layer=layer,
                activation=activation,
            )
            assert validate_fault_definition(definition) == ()
