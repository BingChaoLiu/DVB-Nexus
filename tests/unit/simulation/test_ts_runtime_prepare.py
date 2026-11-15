"""SPEC-203 TS Runtime — prepare binding + deterministic fingerprint
(ticket #43, REQ-SIM-203-002, ADR-0007 item 2).

Traceability:

- REQ-SIM-203-002  prepare binds the fault plan into the fingerprint; the
  plan is validated and rejected BEFORE any session mutation
  (AC-204-01 alignment); ``run()`` takes no plan argument.
- SPEC-203 §5.1    fingerprint inputs: generator version + effective
  config, seed + initial virtual clock, canonical plan serialization;
  wall clock / session_id / run_id never enter the hash.
- SPEC-203 §8      ``SIM_TS_PLAN_INVALID`` / ``SIM_TS_CONFIG_INVALID``.

All tests are pure (unit layer): no IO, no wall clock, no threads.
"""

from __future__ import annotations

import pytest

from simulation.errors import SimulationError
from simulation.fault_plan import FaultActivation, FaultDefinition
from simulation.ts_runtime import (
    SIM_TS_CONFIG_INVALID,
    SIM_TS_PLAN_INVALID,
    PreparedTSRun,
    TSRuntime,
)
from tests.unit.simulation._ts_runtime_builders import (
    make_generator_config,
    make_session_spec,
)

pytestmark = pytest.mark.unit


def _cc_discontinuity(
    *, delta: int = 3, index: int | None = 10
) -> FaultDefinition:
    return FaultDefinition(
        fault_id="fault-1",
        fault_type="CC_DISCONTINUITY",
        target_id="demux-0:pid:0x0100",
        parameters={"delta": delta},
        activation=FaultActivation(
            kind="packet_index" if index is not None else "session_start",
            packet_index=index,
        ),
        expected_observations=("ts.continuity_error",),
    )


class TestPrepareBinding:
    """ADR-0007 item 2: the plan binds at prepare; run() has no plan."""

    def test_prepare_returns_frozen_prepared_run_with_plan(self) -> None:
        runtime = TSRuntime()
        prepared = runtime.prepare(
            make_session_spec(), make_generator_config(), (_cc_discontinuity(),)
        )
        assert isinstance(prepared, PreparedTSRun)
        assert prepared.fault_plan == (_cc_discontinuity(),)
        assert prepared.session_id == "session-ts-runtime"

    def test_run_signature_takes_no_plan(self) -> None:
        # The plan travels only inside PreparedTSRun (ADR-0007 item 2):
        # run() is invoked as run(prepared, sink) — a plan kwarg is a
        # programming error, not a silent re-binding.
        runtime = TSRuntime()
        assert "fault_plan" not in TSRuntime.run.__code__.co_varnames

    def test_empty_plan_defaults_to_baseline_only(self) -> None:
        runtime = TSRuntime()
        prepared = runtime.prepare(make_session_spec(), make_generator_config())
        assert prepared.fault_plan == ()


class TestPreparePlanValidation:
    """AC-204-01 alignment: the plan is rejected at prepare, before any
    session mutation (SIM_TS_PLAN_INVALID with SPEC-204 detail)."""

    def _prepare(self, plan, config=None):
        runtime = TSRuntime()
        return runtime.prepare(
            make_session_spec(), config or make_generator_config(), plan
        )

    def test_unknown_fault_type_rejected(self) -> None:
        bad = FaultDefinition(
            fault_id="f",
            fault_type="SOMETHING_ELSE",
            target_id="demux-0:pid:0x0100",
            parameters={},
            activation=FaultActivation(kind="session_start", packet_index=None),
            expected_observations=("ts.something",),
        )
        with pytest.raises(SimulationError) as excinfo:
            self._prepare((bad,))
        assert excinfo.value.code == SIM_TS_PLAN_INVALID

    def test_missing_expected_observations_rejected(self) -> None:
        bad = FaultDefinition(
            fault_id="f",
            fault_type="PAT_MISSING",
            target_id="demux-0:pid:0x0000",
            parameters={},
            activation=FaultActivation(kind="session_start", packet_index=None),
            expected_observations=(),
        )
        with pytest.raises(SimulationError) as excinfo:
            self._prepare((bad,))
        assert excinfo.value.code == SIM_TS_PLAN_INVALID

    def test_unknown_parameter_key_rejected(self) -> None:
        bad = FaultDefinition(
            fault_id="f",
            fault_type="CC_DISCONTINUITY",
            target_id="demux-0:pid:0x0100",
            parameters={"delta": 3, "bogus_key": 1},
            activation=FaultActivation(kind="packet_index", packet_index=0),
            expected_observations=("ts.continuity_error",),
        )
        with pytest.raises(SimulationError) as excinfo:
            self._prepare((bad,))
        assert excinfo.value.code == SIM_TS_PLAN_INVALID

    def test_delta_out_of_range_rejected(self) -> None:
        for bad_delta in (0, 16, -1):
            with pytest.raises(SimulationError) as excinfo:
                self._prepare((_cc_discontinuity(delta=bad_delta),))
            assert excinfo.value.code == SIM_TS_PLAN_INVALID

    def test_packet_index_activation_requires_index(self) -> None:
        bad = FaultDefinition(
            fault_id="f",
            fault_type="PAT_MISSING",
            target_id="demux-0:pid:0x0000",
            parameters={},
            activation=FaultActivation(kind="packet_index", packet_index=None),
            expected_observations=("ts.psi_section_observed",),
        )
        with pytest.raises(SimulationError) as excinfo:
            self._prepare((bad,))
        assert excinfo.value.code == SIM_TS_PLAN_INVALID

    def test_negative_packet_index_rejected(self) -> None:
        with pytest.raises(SimulationError) as excinfo:
            self._prepare((_cc_discontinuity(index=-1),))
        assert excinfo.value.code == SIM_TS_PLAN_INVALID

    def test_wrong_pmt_pid_must_differ_from_actual(self) -> None:
        bad = FaultDefinition(
            fault_id="f",
            fault_type="PMT_PID_MISMATCH",
            target_id="demux-0:pid:0x0000",
            # config pmt_pid is 0x1000; reusing it is a no-op, rejected.
            parameters={"wrong_pmt_pid": 0x1000},
            activation=FaultActivation(kind="session_start", packet_index=None),
            expected_observations=("ts.psi_section_observed",),
        )
        with pytest.raises(SimulationError) as excinfo:
            self._prepare((bad,))
        assert excinfo.value.code == SIM_TS_PLAN_INVALID

    def test_wrong_pmt_pid_reserved_or_zero_rejected(self) -> None:
        for bad_pid in (0, 0x0005, 0x1FFF):
            bad = FaultDefinition(
                fault_id="f",
                fault_type="PMT_PID_MISMATCH",
                target_id="demux-0:pid:0x0000",
                parameters={"wrong_pmt_pid": bad_pid},
                activation=FaultActivation(
                    kind="session_start", packet_index=None
                ),
                expected_observations=("ts.psi_section_observed",),
            )
            with pytest.raises(SimulationError) as excinfo:
                self._prepare((bad,))
            assert excinfo.value.code == SIM_TS_PLAN_INVALID

    def test_valid_four_types_accepted(self) -> None:
        plan = (
            FaultDefinition(
                fault_id="f1",
                fault_type="PAT_MISSING",
                target_id="demux-0:pid:0x0000",
                parameters={},
                activation=FaultActivation(kind="session_start", packet_index=None),
                expected_observations=("ts.psi_section_observed",),
            ),
            FaultDefinition(
                fault_id="f2",
                fault_type="PMT_INVALID_CRC",
                target_id="demux-0:pid:0x1000",
                parameters={"mode": "persistent", "corruption": "invert"},
                activation=FaultActivation(kind="packet_index", packet_index=5),
                expected_observations=("ts.psi_section_observed",),
            ),
            _cc_discontinuity(),
            FaultDefinition(
                fault_id="f4",
                fault_type="PMT_PID_MISMATCH",
                target_id="demux-0:pid:0x0000",
                parameters={"wrong_pmt_pid": 0x0300},
                activation=FaultActivation(kind="session_start", packet_index=None),
                expected_observations=("ts.psi_section_observed",),
            ),
        )
        prepared = self._prepare(plan)
        assert len(prepared.fault_plan) == 4


class TestPrepareConfigValidation:
    """SIM_TS_CONFIG_INVALID: the TSGeneratorConfig is validated at prepare
    through the SPEC-108 public validator (no re-implementation)."""

    def test_invalid_config_rejected_with_code(self) -> None:
        config = make_generator_config(deterministic=False)
        runtime = TSRuntime()
        with pytest.raises(SimulationError) as excinfo:
            runtime.prepare(make_session_spec(), config)
        assert excinfo.value.code == SIM_TS_CONFIG_INVALID

    def test_non_generator_config_is_type_error(self) -> None:
        runtime = TSRuntime()
        with pytest.raises(TypeError):
            runtime.prepare(make_session_spec(), {"not": "a config"})


class TestFingerprint:
    """SPEC-203 §5.1: deterministic fingerprint over explicit inputs."""

    def test_same_inputs_same_hash(self) -> None:
        runtime = TSRuntime()
        a = runtime.prepare(
            make_session_spec(), make_generator_config(), (_cc_discontinuity(),)
        )
        b = runtime.prepare(
            make_session_spec(), make_generator_config(), (_cc_discontinuity(),)
        )
        assert a.config_hash == b.config_hash

    def test_different_plan_different_hash(self) -> None:
        runtime = TSRuntime()
        a = runtime.prepare(
            make_session_spec(), make_generator_config(), (_cc_discontinuity(delta=3),)
        )
        b = runtime.prepare(
            make_session_spec(), make_generator_config(), (_cc_discontinuity(delta=5),)
        )
        assert a.config_hash != b.config_hash

    def test_empty_tuple_and_empty_list_plans_hash_equal(self) -> None:
        runtime = TSRuntime()
        a = runtime.prepare(make_session_spec(), make_generator_config(), ())
        b = runtime.prepare(make_session_spec(), make_generator_config(), [])
        assert a.config_hash == b.config_hash

    def test_plan_change_from_empty_changes_hash(self) -> None:
        runtime = TSRuntime()
        empty = runtime.prepare(make_session_spec(), make_generator_config())
        planned = runtime.prepare(
            make_session_spec(), make_generator_config(), (_cc_discontinuity(),)
        )
        assert empty.config_hash != planned.config_hash

    def test_config_change_changes_hash(self) -> None:
        runtime = TSRuntime()
        a = runtime.prepare(make_session_spec(), make_generator_config(seed=1))
        b = runtime.prepare(make_session_spec(), make_generator_config(seed=2))
        assert a.config_hash != b.config_hash

    def test_initial_virtual_clock_changes_hash(self) -> None:
        from simulation.clock import SimulationClockConfig

        runtime = TSRuntime()
        a = runtime.prepare(
            make_session_spec(
                clock_config=SimulationClockConfig(mode="deterministic", start_time_ns=0)
            ),
            make_generator_config(),
        )
        b = runtime.prepare(
            make_session_spec(
                clock_config=SimulationClockConfig(mode="deterministic", start_time_ns=500)
            ),
            make_generator_config(),
        )
        assert a.config_hash != b.config_hash

    def test_session_id_and_wall_clock_never_enter_hash(self) -> None:
        runtime = TSRuntime()
        a = runtime.prepare(
            make_session_spec(session_id="session-a"), make_generator_config()
        )
        b = runtime.prepare(
            make_session_spec(session_id="session-b"), make_generator_config()
        )
        assert a.config_hash == b.config_hash
        assert a.generator_version == b.generator_version

    def test_fault_id_identity_does_not_change_hash(self) -> None:
        # fault_id is uuid4-opaque identity (ADR-0006 item 3): the same
        # semantic plan re-generated with new ids keeps the fingerprint.
        runtime = TSRuntime()
        a = runtime.prepare(
            make_session_spec(),
            make_generator_config(),
            (_cc_discontinuity(),),
        )
        other = FaultDefinition(
            fault_id="fault-other-uuid",
            fault_type="CC_DISCONTINUITY",
            target_id="demux-0:pid:0x0100",
            parameters={"delta": 3},
            activation=FaultActivation(kind="packet_index", packet_index=10),
            expected_observations=("ts.continuity_error",),
        )
        b = runtime.prepare(make_session_spec(), make_generator_config(), (other,))
        assert a.config_hash == b.config_hash

    def test_different_target_same_type_changes_hash(self) -> None:
        runtime = TSRuntime()
        a = runtime.prepare(
            make_session_spec(),
            make_generator_config(),
            (_cc_discontinuity(),),
        )
        moved = FaultDefinition(
            fault_id="fault-1",
            fault_type="CC_DISCONTINUITY",
            target_id="demux-0:pid:0x0200",
            parameters={"delta": 3},
            activation=FaultActivation(kind="packet_index", packet_index=10),
            expected_observations=("ts.continuity_error",),
        )
        b = runtime.prepare(make_session_spec(), make_generator_config(), (moved,))
        assert a.config_hash != b.config_hash
