"""Unit-layer tests for the deterministic session/run factory (SPEC-505 §4
`session_run`, serving SPEC-200/203/SPEC-201).

Pure computation: id derivation is a hash of the seed, clock config mirrors
SPEC-201 §4 ``SimulationClockConfig``. No I/O, no wall clock — the factory
must not even *look* at the wall clock (determinism per CONTEXT.md).
"""

from __future__ import annotations

import re

import pytest

from tests._support.session_factory import (
    DEFAULT_SEED,
    SessionPlan,
    SessionRunFactory,
    SimulationClockConfig,
)

_SESSION_ID_PATTERN = re.compile(r"^session-[0-9a-f]{16}$")
_RUN_ID_PATTERN = re.compile(r"^run-[0-9a-f]{16}$")


class TestDeterministicIdentity:
    def test_same_seed_same_ids(self):
        first = SessionRunFactory().create(seed=123)
        second = SessionRunFactory().create(seed=123)
        assert (first.session_id, first.run_id) == (second.session_id, second.run_id)

    def test_different_seed_different_ids(self):
        first = SessionRunFactory().create(seed=1)
        second = SessionRunFactory().create(seed=2)
        assert first.session_id != second.session_id
        assert first.run_id != second.run_id

    def test_id_shape_is_slug_hex(self):
        plan = SessionRunFactory().create(seed=7)
        assert _SESSION_ID_PATTERN.match(plan.session_id)
        assert _RUN_ID_PATTERN.match(plan.run_id)

    def test_default_seed_used_when_omitted(self):
        factory = SessionRunFactory()
        plan = factory.create()
        assert plan.seed == DEFAULT_SEED
        assert plan == factory.create()  # value-equal, same defaults


class TestPlanImmutability:
    def test_plan_is_frozen(self):
        plan = SessionRunFactory().create(seed=9)
        with pytest.raises(Exception):
            plan.seed = 10  # type: ignore[misc]

    def test_each_call_yields_a_new_object(self):
        factory = SessionRunFactory()
        first = factory.create()
        second = factory.create()
        assert first is not second
        assert first == second  # equal values, distinct instances


class TestClockConfigValidation:
    def test_defaults_match_spec201(self):
        config = SimulationClockConfig()
        assert config.mode == "deterministic"
        assert config.start_time_ns == 0
        assert config.speed_num == 1 and config.speed_den == 1
        assert config.tick_quantum_ns == 1_000_000

    @pytest.mark.parametrize(
        "bad_kwargs",
        [
            {"start_time_ns": -1},
            {"tick_quantum_ns": 0},
            {"speed_num": 0},
            {"speed_den": 0},
            {"mode": "wallclock"},
        ],
    )
    def test_invalid_fields_rejected(self, bad_kwargs: dict):
        with pytest.raises(ValueError):
            bad_config = SimulationClockConfig(**bad_kwargs)
            SessionRunFactory().create(clock_config=bad_config)

    def test_realtime_speed_rational_accepted(self):
        factory = SessionRunFactory()
        plan = factory.create(
            clock_config=SimulationClockConfig(mode="realtime", speed_num=3, speed_den=2)
        )
        assert plan.clock_config.speed_num == 3
        assert plan.clock_config.speed_den == 2

    def test_out_of_domain_seed_rejected(self):
        with pytest.raises(ValueError):
            SessionRunFactory().create(seed=-1)
        with pytest.raises(ValueError):
            SessionRunFactory().create(seed=2**64)


class TestCustomClockInPlan:
    def test_plan_carries_clock_config(self):
        config = SimulationClockConfig(mode="deterministic", tick_quantum_ns=500_000)
        plan = SessionRunFactory().create(seed=5, clock_config=config)
        assert isinstance(plan, SessionPlan)
        assert plan.clock_config.tick_quantum_ns == 500_000
        assert plan.clock_config.mode == "deterministic"
