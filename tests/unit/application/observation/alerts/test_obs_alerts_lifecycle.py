"""Alert lifecycle state machine (SPEC-304 §5, ticket #52).

Virtual-time deterministic evaluation: every test drives the machine with
INJECTED integer nanoseconds (SPEC-201 discipline — no wall clock, no
sleeping). The lifecycle is

    inactive → pending → firing → resolving → resolved
                        \\-> inactive  (condition cleared before the pending
                                       for_duration threshold)

with the open/close hysteresis band (§4), the reopen window for resolved
instances (§5), and the missing-data behaviour (§11: 缺数据入 unknown，不误
报 — lost input never fabricates a recovery).

REQ-OBS-304-002: every migration persists timestamp (explicit clock domain),
rule version and evidence references — the transition object carries all of
them.

REQ-OBS-304-006 (fact vs interpretation): the persisted summary is the
MEASURED FACT (observed aggregation, threshold, unit, window); the declared
rule description stays the interpretation and never leaks into the fact
sentence.
"""

from __future__ import annotations

import pytest

from application.observation.alerts.engine import AlertEngine, AlertEngineConfig
from application.observation.alerts.rules import MissingDataPolicy
from domain.observation import (
    AlertState,
    EnvelopeError,
    EnvelopeErrorCode,
)

from tests.unit.application.observation.alerts._alerts_fixtures import (
    CannedReader,
    DOMAIN,
    METRIC,
    deterministic_alert_id,
    make_rule,
    sample_at,
)


def make_engine(reader: CannedReader, **rule_overrides) -> AlertEngine:
    config = AlertEngineConfig(alert_id_factory=deterministic_alert_id())
    return AlertEngine(make_rule(**rule_overrides), config=config)


class TestFullMigrationChain:
    """inactive → pending → firing → resolving → resolved (§5)."""

    def test_no_input_yields_no_records_and_a_missing_contribution(self) -> None:
        reader = CannedReader()
        engine = make_engine(reader)
        evaluation = engine.evaluate("sess-1", reader=reader, now_ns=1_000, clock_domain=DOMAIN)
        assert evaluation.transitions == ()
        contribution = evaluation.contributions[0]
        assert contribution.input_status == "missing"
        assert contribution.state is AlertState.INACTIVE

    def test_condition_open_moves_inactive_to_pending(self) -> None:
        reader = CannedReader((sample_at(900, 200.0),))
        engine = make_engine(reader)
        evaluation = engine.evaluate("sess-1", reader=reader, now_ns=1_000, clock_domain=DOMAIN)
        assert [(t.from_state, t.to_state) for t in evaluation.transitions] == [
            (AlertState.INACTIVE, AlertState.PENDING)
        ]
        transition = evaluation.transitions[0]
        # REQ-OBS-304-002: timestamp + rule version ride the migration.
        assert transition.at_ns == 1_000
        assert transition.rule_version == "1.2.0"
        assert transition.clock_domain == DOMAIN
        assert transition.evidence_refs  # evidence captured on migration
        contribution = evaluation.contributions[0]
        assert contribution.state is AlertState.PENDING
        assert contribution.input_status == "fresh"

    def test_pending_holds_until_for_duration_elapses(self) -> None:
        reader = CannedReader((sample_at(900, 200.0),))
        engine = make_engine(reader)
        engine.evaluate("sess-1", reader=reader, now_ns=1_000, clock_domain=DOMAIN)
        evaluation = engine.evaluate("sess-1", reader=reader, now_ns=1_500, clock_domain=DOMAIN)
        assert evaluation.transitions == ()  # 500 ns < for_duration 1000 ns

    def test_pending_fires_at_for_duration_boundary(self) -> None:
        reader = CannedReader((sample_at(900, 200.0),))
        engine = make_engine(reader)
        engine.evaluate("sess-1", reader=reader, now_ns=1_000, clock_domain=DOMAIN)
        evaluation = engine.evaluate("sess-1", reader=reader, now_ns=2_000, clock_domain=DOMAIN)
        assert [(t.from_state, t.to_state) for t in evaluation.transitions] == [
            (AlertState.PENDING, AlertState.FIRING)
        ]

    def test_firing_is_idempotent_while_condition_holds(self) -> None:
        reader = CannedReader((sample_at(900, 200.0), sample_at(2_100, 150.0)))
        engine = make_engine(reader)
        engine.evaluate("sess-1", reader=reader, now_ns=1_000, clock_domain=DOMAIN)
        engine.evaluate("sess-1", reader=reader, now_ns=2_000, clock_domain=DOMAIN)
        evaluation = engine.evaluate("sess-1", reader=reader, now_ns=3_000, clock_domain=DOMAIN)
        assert evaluation.transitions == ()  # firing + open: no new migration


class TestCloseAndResolve:
    """firing → resolving → resolved + resolving re-arm."""

    def _firing_engine(self) -> tuple[AlertEngine, CannedReader]:
        reader = CannedReader((sample_at(900, 200.0),))
        engine = make_engine(reader)
        engine.evaluate("sess-1", reader=reader, now_ns=1_000, clock_domain=DOMAIN)
        engine.evaluate("sess-1", reader=reader, now_ns=2_000, clock_domain=DOMAIN)
        return engine, reader

    def test_close_condition_moves_firing_to_resolving(self) -> None:
        engine, reader = self._firing_engine()
        reader.add(sample_at(3_000, 10.0))
        evaluation = engine.evaluate("sess-1", reader=reader, now_ns=3_100, clock_domain=DOMAIN)
        assert [(t.from_state, t.to_state) for t in evaluation.transitions] == [
            (AlertState.FIRING, AlertState.RESOLVING)
        ]

    def test_reopened_condition_re_arms_firing_from_resolving(self) -> None:
        engine, reader = self._firing_engine()
        reader.add(sample_at(3_000, 10.0))
        engine.evaluate("sess-1", reader=reader, now_ns=3_100, clock_domain=DOMAIN)
        reader.add(sample_at(4_000, 300.0))
        evaluation = engine.evaluate("sess-1", reader=reader, now_ns=4_100, clock_domain=DOMAIN)
        assert [(t.from_state, t.to_state) for t in evaluation.transitions] == [
            (AlertState.RESOLVING, AlertState.FIRING)
        ]

    def test_resolving_settles_to_resolved_after_hold(self) -> None:
        engine, reader = self._firing_engine()
        reader.add(sample_at(3_000, 10.0))
        engine.evaluate("sess-1", reader=reader, now_ns=3_100, clock_domain=DOMAIN)
        reader.add(sample_at(3_400, 10.0))
        evaluation = engine.evaluate("sess-1", reader=reader, now_ns=3_700, clock_domain=DOMAIN)
        # resolve_since = 3_100; hold 500 ns → resolved at 3_600.
        assert [(t.from_state, t.to_state) for t in evaluation.transitions] == [
            (AlertState.RESOLVING, AlertState.RESOLVED)
        ]

    def test_resolved_is_stable_while_input_stays_clear(self) -> None:
        engine, reader = self._firing_engine()
        reader.add(sample_at(3_000, 10.0))
        engine.evaluate("sess-1", reader=reader, now_ns=3_100, clock_domain=DOMAIN)
        reader.add(sample_at(3_400, 10.0))
        engine.evaluate("sess-1", reader=reader, now_ns=3_700, clock_domain=DOMAIN)
        reader.add(sample_at(4_500, 10.0))
        evaluation = engine.evaluate("sess-1", reader=reader, now_ns=5_000, clock_domain=DOMAIN)
        assert evaluation.transitions == ()


class TestInactiveBranch:
    """pending 阈值前清除回 inactive (§5 分支)."""

    def test_condition_cleared_before_for_duration_returns_to_inactive(self) -> None:
        reader = CannedReader((sample_at(900, 200.0),))
        engine = make_engine(reader)
        engine.evaluate("sess-1", reader=reader, now_ns=1_000, clock_domain=DOMAIN)
        reader.add(sample_at(1_100, 10.0))  # cleared at 1_100 < 2_000 threshold
        evaluation = engine.evaluate("sess-1", reader=reader, now_ns=1_200, clock_domain=DOMAIN)
        assert [(t.from_state, t.to_state) for t in evaluation.transitions] == [
            (AlertState.PENDING, AlertState.INACTIVE)
        ]
        contribution = evaluation.contributions[0]
        assert contribution.state is AlertState.INACTIVE


class TestHysteresisBand:
    """开/合迟滞 (§4): the neutral band holds the current state."""

    def test_band_value_holds_firing_without_transition(self) -> None:
        reader = CannedReader((sample_at(900, 200.0),))
        engine = make_engine(reader)
        engine.evaluate("sess-1", reader=reader, now_ns=1_000, clock_domain=DOMAIN)
        engine.evaluate("sess-1", reader=reader, now_ns=2_000, clock_domain=DOMAIN)
        # 75 sits between the close (50) and open (100) thresholds: neither.
        reader.add(sample_at(2_500, 75.0))
        evaluation = engine.evaluate("sess-1", reader=reader, now_ns=2_600, clock_domain=DOMAIN)
        assert evaluation.transitions == ()

    def test_band_value_holds_pending_without_firing_or_clearing(self) -> None:
        reader = CannedReader((sample_at(900, 200.0),))
        engine = make_engine(reader)
        engine.evaluate("sess-1", reader=reader, now_ns=1_000, clock_domain=DOMAIN)
        # Pending holds when the value left the open zone into the band —
        # the pending clock keeps running (the breach was never retracted by
        # a measured close; only a measured close returns it to inactive).
        reader.add(sample_at(1_100, 75.0))
        evaluation = engine.evaluate("sess-1", reader=reader, now_ns=1_200, clock_domain=DOMAIN)
        assert evaluation.transitions == ()
        # The pending dwell started at 1_000 → firing at 2_000 still.
        reader.add(sample_at(2_100, 75.0))
        evaluation = engine.evaluate("sess-1", reader=reader, now_ns=2_200, clock_domain=DOMAIN)
        assert [(t.from_state, t.to_state) for t in evaluation.transitions] == [
            (AlertState.PENDING, AlertState.FIRING)
        ]


class TestReopenPolicy:
    """resolved 后再触发：reopen in window or a NEW instance (§5)."""

    def _resolved_engine(self) -> tuple[AlertEngine, CannedReader]:
        reader = CannedReader((sample_at(900, 200.0),))
        engine = make_engine(reader)
        engine.evaluate("sess-1", reader=reader, now_ns=1_000, clock_domain=DOMAIN)
        engine.evaluate("sess-1", reader=reader, now_ns=2_000, clock_domain=DOMAIN)
        reader.add(sample_at(3_000, 10.0))
        engine.evaluate("sess-1", reader=reader, now_ns=3_100, clock_domain=DOMAIN)
        reader.add(sample_at(3_400, 10.0))
        engine.evaluate("sess-1", reader=reader, now_ns=3_700, clock_domain=DOMAIN)
        return engine, reader

    def test_reopen_within_window_keeps_the_instance(self) -> None:
        engine, reader = self._resolved_engine()
        # resolved at 3_700; reopen window 2_000 ns → reopen until 5_700.
        reader.add(sample_at(4_000, 200.0))
        evaluation = engine.evaluate("sess-1", reader=reader, now_ns=4_100, clock_domain=DOMAIN)
        assert [(t.from_state, t.to_state) for t in evaluation.transitions] == [
            (AlertState.RESOLVED, AlertState.PENDING)
        ]
        assert evaluation.transitions[0].alert_id == "alert-0001"  # same instance

    def test_reopen_after_window_creates_a_new_instance(self) -> None:
        engine, reader = self._resolved_engine()
        # resolved at 3_700; the next breach lands at 7_000 > 5_700.
        reader.add(sample_at(7_000, 200.0))
        evaluation = engine.evaluate("sess-1", reader=reader, now_ns=7_100, clock_domain=DOMAIN)
        assert [(t.from_state, t.to_state) for t in evaluation.transitions] == [
            (AlertState.RESOLVED, AlertState.PENDING)
        ]
        assert evaluation.transitions[0].alert_id == "alert-0002"  # NEW instance


class TestMissingDataBehaviour:
    """缺数据行为 (§11): unknown, never a false firing/recovery."""

    def test_stale_input_holds_firing_without_false_recovery(self) -> None:
        reader = CannedReader((sample_at(900, 200.0),))
        engine = make_engine(reader)
        engine.evaluate("sess-1", reader=reader, now_ns=1_000, clock_domain=DOMAIN)
        engine.evaluate("sess-1", reader=reader, now_ns=2_000, clock_domain=DOMAIN)
        # Last sample at 900; freshness 1_000_000 — still fresh. Advance far
        # past freshness with NO new sample.
        evaluation = engine.evaluate("sess-1", reader=reader, now_ns=1_100_000, clock_domain=DOMAIN)
        assert evaluation.transitions == ()  # held firing, no fabricated resolve
        contribution = evaluation.contributions[0]
        assert contribution.input_status == "stale"

    def test_missing_input_reports_missing_and_holds_state(self) -> None:
        reader = CannedReader((sample_at(900, 200.0),))
        engine = make_engine(reader)
        engine.evaluate("sess-1", reader=reader, now_ns=1_000, clock_domain=DOMAIN)
        reader.samples.clear()  # input vanished entirely
        evaluation = engine.evaluate("sess-1", reader=reader, now_ns=2_000, clock_domain=DOMAIN)
        assert evaluation.transitions == ()
        contribution = evaluation.contributions[0]
        assert contribution.input_status == "missing"

    def test_null_quality_samples_do_not_count_as_input(self) -> None:
        # 缺失 ≠ 零: a missing-quality sample is not a measurement.
        reader = CannedReader((sample_at(900, None),))
        engine = make_engine(reader)
        evaluation = engine.evaluate("sess-1", reader=reader, now_ns=1_000, clock_domain=DOMAIN)
        assert evaluation.transitions == ()
        assert evaluation.contributions[0].input_status == "missing"

    def test_insufficient_samples_below_min_samples_do_not_fire(self) -> None:
        reader = CannedReader((sample_at(900, 200.0),))
        engine = make_engine(reader, min_samples=2)
        evaluation = engine.evaluate("sess-1", reader=reader, now_ns=1_000, clock_domain=DOMAIN)
        assert evaluation.transitions == ()
        assert evaluation.contributions[0].input_status == "missing"

    def test_missing_data_ignore_policy_skips_the_rule(self) -> None:
        reader = CannedReader()
        engine = make_engine(reader, missing_data=MissingDataPolicy.IGNORE)
        evaluation = engine.evaluate("sess-1", reader=reader, now_ns=1_000, clock_domain=DOMAIN)
        assert evaluation.contributions == ()  # skipped, not unknown


class TestTimeDomainGuard:
    """SPEC-300 §6 via the OBS_INVALID_TIME_DOMAIN guard (§1.5 seam)."""

    def test_epoch_change_is_refused(self) -> None:
        reader = CannedReader((sample_at(900, 200.0),))
        engine = make_engine(reader)
        engine.evaluate("sess-1", reader=reader, now_ns=1_000, clock_domain=DOMAIN)
        with pytest.raises(EnvelopeError) as excinfo:
            engine.evaluate(
                "sess-1", reader=reader, now_ns=2_000, clock_domain=DOMAIN, clock_epoch=1
            )
        assert excinfo.value.code is EnvelopeErrorCode.OBS_INVALID_TIME_DOMAIN

    def test_domain_change_is_refused(self) -> None:
        reader = CannedReader((sample_at(900, 200.0),))
        engine = make_engine(reader)
        engine.evaluate("sess-1", reader=reader, now_ns=1_000, clock_domain=DOMAIN)
        with pytest.raises(EnvelopeError):
            engine.evaluate(
                "sess-1", reader=reader, now_ns=2_000, clock_domain="sim:other"
            )


class TestDeterminism:
    """重放下的确定性评估 (§11): same input sequence ⇒ same transitions."""

    def test_two_engines_replay_identically(self) -> None:
        def run() -> list[tuple]:
            reader = CannedReader(
                (
                    sample_at(900, 200.0),
                    sample_at(2_100, 150.0, pid=1),
                    sample_at(3_000, 10.0),
                    sample_at(3_400, 10.0),
                    sample_at(4_000, 200.0),
                )
            )
            engine = make_engine(reader)
            history = []
            for now in (1_000, 2_000, 3_100, 3_700, 4_100):
                evaluation = engine.evaluate(
                    "sess-1", reader=reader, now_ns=now, clock_domain=DOMAIN
                )
                history.extend(
                    (t.alert_id, t.from_state, t.to_state, t.at_ns)
                    for t in evaluation.transitions
                )
            return history

        assert run() == run()

    def test_summary_is_measured_fact_without_interpretation(self) -> None:
        reader = CannedReader((sample_at(900, 200.0),))
        engine = make_engine(reader)
        evaluation = engine.evaluate("sess-1", reader=reader, now_ns=1_000, clock_domain=DOMAIN)
        summary = evaluation.transitions[0].summary
        # The measured fact: aggregation reading, operator, threshold, unit.
        assert "200" in summary
        assert "100" in summary and "u" in summary
        # The declared interpretation text never leaks into the fact.
        assert "interpretation" not in summary.lower()
        assert "too high" not in summary.lower()
