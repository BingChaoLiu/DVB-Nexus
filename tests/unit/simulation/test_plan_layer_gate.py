"""The bidirectional mixed-plan prepare gate (ticket #165, ADR-0012
decisions 2/3; the #163 REPORT note: a ``LayerFaultFilter`` construction
KeyError is unacceptable — the SIM_TS direction rejects cleanly at
prepare).

Two directions, one seam:

- SIM_TS Run receives an RF/SEC-layer fault → clean prepare rejection
  (``TSPlanInvalidError`` / ``SIM_TS_PLAN_INVALID`` carrying the
  ``SIM_FAULT_PLAN_LAYER_MISMATCH`` detail family).
- SIM_STATE Run receives a package-layer (TS/BBFRAME/T2MI/BISS) fault →
  the mirror rejection on the state face (covered in
  ``tests/unit/simulation/state/test_run.py``).
- Default behavior (no ``allowed_layers``) is byte-identical to the
  pre-#165 face — ADR-0007 package-path zero-behavior-change, the full
  TS-layer plan suite stays green.
"""

from __future__ import annotations

import pytest

from simulation.errors import TSPlanInvalidError
from simulation.fault_plan import (
    PACKAGE_PLAN_LAYERS,
    FaultActivation,
    FaultDefinition,
    validate_fault_plan,
)
from simulation.ts_runtime import TSRuntime
from tests.unit.simulation._ts_runtime_builders import (
    make_generator_config,
    make_session_spec,
)

pytestmark = pytest.mark.unit


def _tone_residue() -> FaultDefinition:
    return FaultDefinition(
        fault_id="fault-tone",
        fault_type="TONE_RESIDUE",
        target_id="lnb-0",
        parameters={"tone_actual": "continuous"},
        activation=FaultActivation(kind="session_start"),
        expected_observations=("sec.state_observed", "rf.state_observed"),
        layer="RF",
    )


def _ub_conflict() -> FaultDefinition:
    return FaultDefinition(
        fault_id="fault-ub",
        fault_type="UB_SLOT_CONFLICT",
        target_id="tuner-0:ub_slot",
        parameters={"conflicting_ub_slot": 0},
        activation=FaultActivation(kind="session_start"),
        expected_observations=("sec.state_observed", "rf.state_observed"),
        layer="SEC",
    )


def _cc_discontinuity() -> FaultDefinition:
    return FaultDefinition(
        fault_id="fault-cc",
        fault_type="CC_DISCONTINUITY",
        target_id="demux-0:pid:0x0100",
        parameters={"delta": 3},
        activation=FaultActivation(kind="packet_index", packet_index=10),
        expected_observations=("ts.continuity_error",),
        layer="TS",
    )


class TestPackageLayerAllowlist:
    """The ``allowed_layers`` prepare face (default None = unchanged)."""

    def test_default_accepts_state_layer_faults(self) -> None:
        # zero behavior change: without the kwarg the canonical registry
        # validation runs exactly as before (#163 already registered the
        # state primitives as legal definitions).
        plan = validate_fault_plan((_tone_residue(),))
        assert plan == (_tone_residue(),)

    def test_ts_run_rejects_rf_layer_fault(self) -> None:
        with pytest.raises(TSPlanInvalidError) as excinfo:
            validate_fault_plan(
                (_tone_residue(),), allowed_layers=PACKAGE_PLAN_LAYERS
            )
        assert any(
            detail.startswith("SIM_FAULT_PLAN_LAYER_MISMATCH")
            for detail in excinfo.value.details
        )

    def test_ts_run_rejects_sec_layer_fault(self) -> None:
        with pytest.raises(TSPlanInvalidError) as excinfo:
            validate_fault_plan(
                (_ub_conflict(),), allowed_layers=PACKAGE_PLAN_LAYERS
            )
        assert any(
            detail.startswith("SIM_FAULT_PLAN_LAYER_MISMATCH")
            for detail in excinfo.value.details
        )

    def test_ts_run_still_accepts_package_layer_plan(self) -> None:
        plan = validate_fault_plan(
            (_cc_discontinuity(),), allowed_layers=PACKAGE_PLAN_LAYERS
        )
        assert plan == (_cc_discontinuity(),)


class TestTSRuntimePrepareCleanRejection:
    """The #163 REPORT note: no ``LayerFaultFilter`` construction KeyError.

    A SIM_TS run whose plan routes RF/SEC must be rejected at prepare
    (422 face), never crash at run-stage filter construction.
    """

    def test_prepare_rejects_state_layer_fault(self) -> None:
        runtime = TSRuntime()
        with pytest.raises(TSPlanInvalidError) as excinfo:
            runtime.prepare(
                make_session_spec(),
                make_generator_config(),
                (_tone_residue(),),
            )
        assert any(
            detail.startswith("SIM_FAULT_PLAN_LAYER_MISMATCH")
            for detail in excinfo.value.details
        )

    def test_prepare_still_binds_package_layer_plan(self) -> None:
        runtime = TSRuntime()
        prepared = runtime.prepare(
            make_session_spec(),
            make_generator_config(),
            (_cc_discontinuity(),),
        )
        assert prepared.fault_plan == (_cc_discontinuity(),)
