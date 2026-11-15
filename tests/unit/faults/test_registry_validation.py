"""SPEC-204 §4/§11 — versioned parameter schema validation, per-code tests.

The registry validator is pure: it returns the per-fault error detail list,
each detail prefixed with its SPEC-204 §11 diagnostic code.  The prepare
stage (``simulation.fault_plan.validate_fault_plan``, #43 face) turns those
details into ``SIM_TS_PLAN_INVALID`` rejections before any session mutation
(AC-204-01) — covered in ``tests/unit/simulation/test_fault_plan_spec204``.
"""

from __future__ import annotations

import pytest

from faults.definition import FaultActivation, FaultDefinition
from faults.registry import (
    FAULT_TYPE_CC_DISCONTINUITY,
    FAULT_TYPE_PAT_MISSING,
    FAULT_TYPE_PMT_INVALID_CRC,
    FAULT_TYPE_PMT_PID_MISMATCH,
    MVP_FAULT_TYPES,
    PARAMETERS_SCHEMA_VERSION,
    validate_fault_definition,
)

pytestmark = pytest.mark.unit


def _fault(
    fault_type: str = FAULT_TYPE_PAT_MISSING,
    *,
    target_id: str = "demux-0:pid:0x0000",
    parameters: dict | None = None,
    activation: FaultActivation | None = None,
    expected_observations: tuple[str, ...] = ("ts.psi_section_observed",),
    fault_id: str = "f-1",
) -> FaultDefinition:
    return FaultDefinition(
        fault_id=fault_id,
        fault_type=fault_type,
        target_id=target_id,
        parameters=parameters or {},
        activation=activation
        or FaultActivation(kind="session_start", packet_index=None),
        expected_observations=expected_observations,
    )


def _codes(details: tuple[str, ...]) -> list[str]:
    return [detail.split(":", 1)[0] for detail in details]


class TestRegistryConstants:
    def test_mvp_registry_is_the_four_types(self) -> None:
        assert MVP_FAULT_TYPES == {
            FAULT_TYPE_PAT_MISSING,
            FAULT_TYPE_PMT_INVALID_CRC,
            FAULT_TYPE_CC_DISCONTINUITY,
            FAULT_TYPE_PMT_PID_MISMATCH,
        }

    def test_schema_version_is_v1(self) -> None:
        assert PARAMETERS_SCHEMA_VERSION == 1


class TestUnknownType:
    def test_unknown_fault_type_rejected(self) -> None:
        details = validate_fault_definition(_fault("SOMETHING_ELSE"))
        assert _codes(details) == ["SIM_FAULT_UNKNOWN_TYPE"]


class TestTargetInvalid:
    @pytest.mark.parametrize(
        "bad_target", ["", "demux-0:pid:", "demux-0:pid:0xZZ", "demux-0:pid:0x20000"]
    )
    def test_unparseable_target_rejected(self, bad_target: str) -> None:
        details = validate_fault_definition(_fault(target_id=bad_target))
        assert _codes(details) == ["SIM_FAULT_TARGET_INVALID"]

    def test_mvp_faults_require_stream_level_targets(self) -> None:
        # All four MVP faults are stream-level (node_id + pid) faults.
        details = validate_fault_definition(_fault(target_id="demux-0"))
        assert _codes(details) == ["SIM_FAULT_TARGET_INVALID"]

    def test_empty_node_segment_rejected(self) -> None:
        details = validate_fault_definition(_fault(target_id=":pid:0x0000"))
        assert _codes(details) == ["SIM_FAULT_TARGET_INVALID"]


class TestExpectedObservations:
    def test_missing_expected_observations_rejected(self) -> None:
        details = validate_fault_definition(_fault(expected_observations=()))
        assert _codes(details) == ["SIM_FAULT_EXPECTED_OBS_MISSING"]

    def test_non_string_or_empty_entries_rejected(self) -> None:
        details = validate_fault_definition(
            _fault(expected_observations=("ts.continuity_error", ""))
        )
        assert _codes(details) == ["SIM_FAULT_EXPECTED_OBS_MISSING"]
        details = validate_fault_definition(
            _fault(expected_observations=("ts.continuity_error", 3))  # type: ignore[list-item]
        )
        assert _codes(details) == ["SIM_FAULT_EXPECTED_OBS_MISSING"]


class TestActivationValidation:
    def test_unknown_activation_kind_rejected(self) -> None:
        details = validate_fault_definition(
            _fault(activation=FaultActivation(kind="virtual_time", packet_index=1))
        )
        assert _codes(details) == ["SIM_FAULT_PARAM_INVALID"]

    def test_packet_index_kind_requires_index(self) -> None:
        details = validate_fault_definition(
            _fault(activation=FaultActivation(kind="packet_index", packet_index=None))
        )
        assert _codes(details) == ["SIM_FAULT_PARAM_INVALID"]

    def test_negative_packet_index_rejected(self) -> None:
        details = validate_fault_definition(
            _fault(activation=FaultActivation(kind="packet_index", packet_index=-1))
        )
        assert _codes(details) == ["SIM_FAULT_PARAM_INVALID"]

    def test_session_start_must_not_carry_index(self) -> None:
        details = validate_fault_definition(
            _fault(activation=FaultActivation(kind="session_start", packet_index=5))
        )
        assert _codes(details) == ["SIM_FAULT_PARAM_INVALID"]

    def test_packet_index_beyond_frame_rejected(self) -> None:
        details = validate_fault_definition(
            _fault(
                activation=FaultActivation(kind="packet_index", packet_index=600),
            ),
            expected_packet_count=600,
        )
        assert _codes(details) == ["SIM_FAULT_ACTIVATION_OUT_OF_RANGE"]

    def test_packet_index_at_last_slot_of_frame_accepted(self) -> None:
        details = validate_fault_definition(
            _fault(
                activation=FaultActivation(kind="packet_index", packet_index=599),
            ),
            expected_packet_count=600,
        )
        assert details == ()

    def test_range_check_skipped_without_expected_count(self) -> None:
        details = validate_fault_definition(
            _fault(
                activation=FaultActivation(kind="packet_index", packet_index=999_999),
            ),
        )
        assert details == ()


class TestParameterSchemas:
    def test_pat_missing_schema_v1_is_empty(self) -> None:
        assert validate_fault_definition(_fault()) == ()
        details = validate_fault_definition(_fault(parameters={"bogus": 1}))
        assert _codes(details) == ["SIM_FAULT_PARAM_INVALID"]
        assert "bogus" in details[0]

    def test_pmt_invalid_crc_defaults_and_modes(self) -> None:
        # defaults are implicit: empty parameters validate
        assert validate_fault_definition(_fault(FAULT_TYPE_PMT_INVALID_CRC,
                                               target_id="demux-0:pid:0x1000")) == ()
        assert validate_fault_definition(
            _fault(FAULT_TYPE_PMT_INVALID_CRC,
                   target_id="demux-0:pid:0x1000",
                   parameters={"mode": "once", "corruption": "zero"})
        ) == ()
        for bad in ({"mode": "twice"}, {"corruption": "shuffle"}):
            details = validate_fault_definition(
                _fault(FAULT_TYPE_PMT_INVALID_CRC,
                       target_id="demux-0:pid:0x1000",
                       parameters=bad)
            )
            assert _codes(details) == ["SIM_FAULT_PARAM_INVALID"]

    def test_cc_delta_bounds(self) -> None:
        for delta in (1, 15):
            assert validate_fault_definition(
                _fault(FAULT_TYPE_CC_DISCONTINUITY,
                       target_id="demux-0:pid:0x0100",
                       parameters={"delta": delta})
            ) == ()
        for delta in (0, 16, -3, True, "3", 3.0):
            details = validate_fault_definition(
                _fault(FAULT_TYPE_CC_DISCONTINUITY,
                       target_id="demux-0:pid:0x0100",
                       parameters={"delta": delta})
            )
            assert _codes(details) == ["SIM_FAULT_PARAM_INVALID"]

    def test_cc_delta_required(self) -> None:
        details = validate_fault_definition(
            _fault(FAULT_TYPE_CC_DISCONTINUITY,
                   target_id="demux-0:pid:0x0100")
        )
        assert _codes(details) == ["SIM_FAULT_PARAM_INVALID"]

    def test_wrong_pmt_pid_bounds_and_reserved(self) -> None:
        good = {"wrong_pmt_pid": 0x0300}
        assert validate_fault_definition(
            _fault(FAULT_TYPE_PMT_PID_MISMATCH, parameters=dict(good))
        ) == ()
        for bad_pid in (0, 0x0005, 0x1FFF, 0x10000, -1, "4100", True):
            details = validate_fault_definition(
                _fault(FAULT_TYPE_PMT_PID_MISMATCH,
                       parameters={"wrong_pmt_pid": bad_pid})
            )
            assert _codes(details) == ["SIM_FAULT_PARAM_INVALID"]

    def test_wrong_pmt_pid_must_differ_from_actual(self) -> None:
        details = validate_fault_definition(
            _fault(FAULT_TYPE_PMT_PID_MISMATCH,
                   parameters={"wrong_pmt_pid": 0x1000}),
            actual_pmt_pid=0x1000,
        )
        assert _codes(details) == ["SIM_FAULT_PARAM_INVALID"]
        assert validate_fault_definition(
            _fault(FAULT_TYPE_PMT_PID_MISMATCH,
                   parameters={"wrong_pmt_pid": 0x1000}),
        ) == ()

    def test_multiple_errors_collected_in_order(self) -> None:
        details = validate_fault_definition(
            FaultDefinition(
                fault_id="",
                fault_type="SOMETHING_ELSE",
                target_id="bogus",
                parameters={"x": 1},
                activation=FaultActivation(kind="nope", packet_index=None),
                expected_observations=(),
            )
        )
        codes = _codes(details)
        assert "SIM_FAULT_UNKNOWN_TYPE" in codes
        assert "SIM_FAULT_TARGET_INVALID" in codes
        assert "SIM_FAULT_EXPECTED_OBS_MISSING" in codes
        assert "SIM_FAULT_PARAM_INVALID" in codes
