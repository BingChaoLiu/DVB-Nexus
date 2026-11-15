"""SPEC-204 §11 codes through the prepare face (REQ-SIM-204-001).

The #43 seam tests pin ``SIM_TS_PLAN_INVALID`` rejection semantics; this
slice pins the #44 additions: the SPEC-204 §11 detail codes surface in
``TSPlanInvalidError.details`` and the activation is validated against
the prepared output frame (SIM_FAULT_ACTIVATION_OUT_OF_RANGE — the frame
length is budgetable at prepare from ``output_packet_count``).
"""

from __future__ import annotations

import pytest

from faults.definition import FaultActivation, FaultDefinition
from simulation.errors import SIM_TS_PLAN_INVALID
from simulation.ts_runtime import TSRuntime

from tests.unit.faults._fault_builders import (
    GOLDEN_PACKET_COUNT,
    cc_discontinuity_fault,
    pat_missing_fault,
    pmt_pid_mismatch_fault,
)
from tests.unit.simulation._ts_runtime_builders import (
    make_generator_config,
    make_session_spec,
)

pytestmark = pytest.mark.unit


def _prepare(plan):
    runtime = TSRuntime()
    return runtime.prepare(
        make_session_spec(), make_generator_config(output_packet_count=GOLDEN_PACKET_COUNT), plan
    )


class TestActivationRangeAtPrepare:
    def test_packet_index_beyond_frame_rejected_at_prepare(self) -> None:
        fault = FaultDefinition(
            fault_id="f",
            fault_type="CC_DISCONTINUITY",
            target_id="demux-0:pid:0x0100",
            parameters={"delta": 3},
            activation=FaultActivation(kind="packet_index", packet_index=600),
            expected_observations=("ts.continuity_error",),
        )
        with pytest.raises(Exception) as excinfo:
            _prepare((fault,))
        assert excinfo.value.code == SIM_TS_PLAN_INVALID
        assert any(
            detail.startswith("SIM_FAULT_ACTIVATION_OUT_OF_RANGE")
            for detail in excinfo.value.details
        )

    def test_last_slot_of_frame_accepted(self) -> None:
        fault = FaultDefinition(
            fault_id="f",
            fault_type="CC_DISCONTINUITY",
            target_id="demux-0:pid:0x0100",
            parameters={"delta": 3},
            activation=FaultActivation(kind="packet_index", packet_index=599),
            expected_observations=("ts.continuity_error",),
        )
        prepared = _prepare((fault,))
        assert prepared.fault_plan == (fault,)

    def test_session_start_has_no_range_constraint(self) -> None:
        prepared = _prepare((pat_missing_fault(),))
        assert prepared.fault_plan[0].activation.kind == "packet_index"


class TestSpec204CodesAtPrepare:
    def test_target_invalid_code_surfaces(self) -> None:
        fault = FaultDefinition(
            fault_id="f",
            fault_type="CC_DISCONTINUITY",
            target_id="demux-0:pid:0xZZZZ",
            parameters={"delta": 3},
            expected_observations=("ts.continuity_error",),
        )
        with pytest.raises(Exception) as excinfo:
            _prepare((fault,))
        assert excinfo.value.code == SIM_TS_PLAN_INVALID
        assert any(
            detail.startswith("SIM_FAULT_TARGET_INVALID")
            for detail in excinfo.value.details
        )

    def test_node_level_target_rejected_for_mvp_faults(self) -> None:
        fault = FaultDefinition(
            fault_id="f",
            fault_type="PAT_MISSING",
            target_id="demux-0",
            expected_observations=("ts.psi_section_observed",),
        )
        with pytest.raises(Exception) as excinfo:
            _prepare((fault,))
        assert any(
            detail.startswith("SIM_FAULT_TARGET_INVALID")
            for detail in excinfo.value.details
        )

    def test_wrong_pmt_pid_vs_real_config_pid(self) -> None:
        # golden geometry pmt_pid = 0x1000 (4096)
        fault = FaultDefinition(
            fault_id="f",
            fault_type="PMT_PID_MISMATCH",
            target_id="demux-0:pid:0x0000",
            parameters={"wrong_pmt_pid": 4096},
            expected_observations=("ts.psi_section_observed",),
        )
        with pytest.raises(Exception) as excinfo:
            _prepare((fault,))
        assert any(
            detail.startswith("SIM_FAULT_PARAM_INVALID")
            for detail in excinfo.value.details
        )
        # a legal wrong pid prepares cleanly
        prepared = _prepare((pmt_pid_mismatch_fault(),))
        assert prepared.fault_plan == (pmt_pid_mismatch_fault(),)

    def test_golden_plans_prepare_cleanly(self) -> None:
        prepared = _prepare(
            (pat_missing_fault(), cc_discontinuity_fault())
        )
        assert len(prepared.fault_plan) == 2
