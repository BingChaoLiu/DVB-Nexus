"""TUNER_UNLOCKED / BER_SEVERE lifecycle behaviour (ticket #166).

Seam: ``AlertEngine.evaluate`` over the shipped Phase 3 rules
(``default_rule_set().rule(...)``) with a metric-name-filtering reader double
(the ``MetricWindowReader`` structural seam, as ``MetricsWindowReader`` does
in production).

Pinned here (SPEC-304 §Phase3 + §5):

- TUNER_UNLOCKED (warning) opens on the unlocked code (1.0) and — with
  ``for_duration=0`` — fires on the NEXT tick: the untouched five-state
  machine advances at most one step per deterministic tick (ruling A6: zero
  engine changes; same posture as the ``for_duration=0`` TOPOLOGY_PATH_DOWN
  precedent);
- BER_SEVERE (error) opens on the severe code (2.0) and fires the same way;
- the elevated code (1.0) satisfies NEITHER the open condition NOR any
  close band of another rule: no migration, no firing (SPEC-304 §Phase3
  elevated 不告警) — but it IS a measured close for a firing BER_SEVERE slot;
- the non-alerting paths (locked=0.0 / normal=0.0) never migrate anything;
- fingerprint dedup: per (rule, node_id) slots — two tuners migrate
  independently, repeated ticks on a firing slot are idempotent;
- the five-state lifecycle (pending → firing → resolving → resolved, reopen
  window semantics) rides the UNCHANGED engine machine;
- a session without tuner snapshots holds (input missing, not firing, and
  — the rules being ``required=False`` — never an unhealthy verdict).

Unit layer: injected integers only, no I/O, no wall clock.
"""

from __future__ import annotations

from domain.observation import (
    AlertSeverity,
    AlertState,
    MetricProvenance,
    MetricSample,
    MetricSampleTimepoint,
    SampleSemantics,
    SeriesQuality,
)

from application.observation.alerts.engine import AlertEngine, AlertEngineConfig
from application.observation.alerts.rules import default_rule_set

SESSION_ID = "sess-tuner"
DOMAIN = f"sim:{SESSION_ID}"
NODE_A = "tuner-a"
NODE_B = "tuner-b"
#: The snapshot instant; evaluation ticks ride ≥1 ns after it so the sample
#: lands inside the rule's 10 s window (``[now - window, now)``).
SNAPSHOT_NS = 10_000_000_000
SECOND_NS = 1_000_000_000
#: The Phase 3 rules' evaluation window (the sandbox-standard 10 s).
RULE_WINDOW_NS = 10 * SECOND_NS


def tuner_sample(
    metric_name: str,
    value: float,
    *,
    node_id: str = NODE_A,
    value_ns: int = SNAPSHOT_NS,
    session_id: str = SESSION_ID,
) -> MetricSample:
    return MetricSample(
        metric_name=metric_name,
        time=MetricSampleTimepoint(
            value_ns=value_ns,
            clock_domain=DOMAIN,
            clock_epoch=0,
            semantics=SampleSemantics.SOURCE,
        ),
        value=value,
        dimensions={"session_id": session_id, "node_id": node_id},
        quality=(SeriesQuality.GOOD,),
        provenance=MetricProvenance(source_event_ids=("evt-1",)),
    )


class MetricsMapReader:
    """Structural ``MetricWindowReader`` double keyed by metric name (the
    production ``MetricsWindowReader`` filters the same way)."""

    def __init__(self) -> None:
        self._samples: dict[str, list[MetricSample]] = {}

    def add(self, sample: MetricSample) -> None:
        self._samples.setdefault(sample.metric_name, []).append(sample)

    def samples_for(self, *, metric_name, session_id, clock_domain, clock_epoch):
        return tuple(self._samples.get(metric_name, ()))


def _engine(rule_id: str) -> AlertEngine:
    rule = default_rule_set().rule(rule_id)
    alert_ids = iter(f"alert-{rule_id}-{n:02d}" for n in range(1, 100))
    return AlertEngine(
        rule,
        config=AlertEngineConfig(alert_id_factory=lambda: next(alert_ids)),
    )


def _tick(engine: AlertEngine, reader: MetricsMapReader, now_ns: int):
    return engine.evaluate(
        SESSION_ID, reader=reader, now_ns=now_ns, clock_domain=DOMAIN
    )


def _states(evaluation) -> list:
    return [t.to_state for t in evaluation.transitions]


def test_tuner_unlocked_opens_pending_then_fires_as_a_warning() -> None:
    reader = MetricsMapReader()
    reader.add(tuner_sample("tuner.lock_state", 1.0))  # unlocked
    engine = _engine("TUNER_UNLOCKED")

    first = _tick(engine, reader, SNAPSHOT_NS + 1)
    assert _states(first) == [AlertState.PENDING]
    second = _tick(engine, reader, SNAPSHOT_NS + 1 + SECOND_NS)
    assert _states(second) == [AlertState.FIRING]
    assert all(
        t.severity is AlertSeverity.WARNING
        for t in first.transitions + second.transitions
    )
    assert all(t.rule_id == "TUNER_UNLOCKED" for t in second.transitions)
    assert all(
        t.group_key == (("node_id", NODE_A),) for t in second.transitions
    )


def test_ber_severe_opens_pending_then_fires_as_an_error() -> None:
    reader = MetricsMapReader()
    reader.add(tuner_sample("tuner.ber_state", 2.0))  # severe
    engine = _engine("BER_SEVERE")

    first = _tick(engine, reader, SNAPSHOT_NS + 1)
    second = _tick(engine, reader, SNAPSHOT_NS + 1 + SECOND_NS)
    assert _states(first) == [AlertState.PENDING]
    assert _states(second) == [AlertState.FIRING]
    assert all(
        t.severity is AlertSeverity.ERROR
        for t in first.transitions + second.transitions
    )


def test_elevated_code_never_alerts() -> None:
    """The tier gap is behavioural, not just declarative: elevated (1.0)
    opens nothing (SPEC-304 §Phase3 elevated 不告警)."""
    reader = MetricsMapReader()
    reader.add(tuner_sample("tuner.ber_state", 1.0))  # elevated
    engine = _engine("BER_SEVERE")

    first = _tick(engine, reader, SNAPSHOT_NS + 1)
    second = _tick(engine, reader, SNAPSHOT_NS + 1 + SECOND_NS)
    assert first.transitions == ()
    assert second.transitions == ()
    assert all(not c.firing for c in first.contributions)
    assert all(not c.firing for c in second.contributions)
    assert all(c.input_status == "fresh" for c in first.contributions)


def test_non_alerting_codes_never_migrate() -> None:
    reader = MetricsMapReader()
    reader.add(tuner_sample("tuner.lock_state", 0.0))  # locked
    reader.add(tuner_sample("tuner.ber_state", 0.0))  # normal
    unlocked_engine = _engine("TUNER_UNLOCKED")
    ber_engine = _engine("BER_SEVERE")

    for tick_ns in (SNAPSHOT_NS + 1, SNAPSHOT_NS + 1 + SECOND_NS):
        unlocked_evaluation = _tick(unlocked_engine, reader, tick_ns)
        ber_evaluation = _tick(ber_engine, reader, tick_ns)
        assert unlocked_evaluation.transitions == ()
        assert ber_evaluation.transitions == ()
        assert all(not c.firing for c in unlocked_evaluation.contributions)
        assert all(not c.firing for c in ber_evaluation.contributions)


def test_elevated_is_a_measured_close_for_a_firing_ber_severe() -> None:
    """firing on severe → an elevated reading closes the band (close LTE 1)
    → resolving (never straight to resolved — the §5 hold applies)."""
    reader = MetricsMapReader()
    reader.add(tuner_sample("tuner.ber_state", 2.0))
    engine = _engine("BER_SEVERE")
    assert _states(_tick(engine, reader, SNAPSHOT_NS + 1)) == [AlertState.PENDING]
    assert _states(_tick(engine, reader, SNAPSHOT_NS + 1 + SECOND_NS)) == [
        AlertState.FIRING
    ]

    # Next snapshot: elevated (code 1) — measured close, no open.
    reader.add(
        tuner_sample("tuner.ber_state", 1.0, value_ns=SNAPSHOT_NS + 2 * SECOND_NS)
    )
    third = _tick(engine, reader, SNAPSHOT_NS + 2 * SECOND_NS + 1)
    assert _states(third) == [AlertState.RESOLVING]


def test_fingerprint_dedup_is_per_rule_and_per_node() -> None:
    """Two tuners migrate as two independent fingerprint slots (SPEC-304 §6
    grouping); each slot's fingerprint is stable across ticks."""
    reader = MetricsMapReader()
    reader.add(tuner_sample("tuner.lock_state", 1.0, node_id=NODE_A))
    reader.add(tuner_sample("tuner.lock_state", 1.0, node_id=NODE_B))
    engine = _engine("TUNER_UNLOCKED")

    first = _tick(engine, reader, SNAPSHOT_NS + 1)
    slots = {t.fingerprint for t in first.transitions}
    assert len(slots) == 2
    assert _states(first) == [AlertState.PENDING, AlertState.PENDING]
    # Distinct alert ids per slot (the deterministic factory pins them).
    assert {t.alert_id for t in first.transitions} == {
        "alert-TUNER_UNLOCKED-01",
        "alert-TUNER_UNLOCKED-02",
    }

    second = _tick(engine, reader, SNAPSHOT_NS + 1 + SECOND_NS)
    assert _states(second) == [AlertState.FIRING, AlertState.FIRING]
    assert {t.fingerprint for t in second.transitions} == slots

    # A repeated unlocked tick is idempotent: firing holds, no migration.
    third = _tick(engine, reader, SNAPSHOT_NS + 1 + 2 * SECOND_NS)
    assert third.transitions == ()
    assert all(c.firing for c in third.contributions)


def test_recovery_to_resolved_and_reopen_window_semantics() -> None:
    """unlocked → firing → locked: resolving → resolved; a re-open inside
    the reopen window re-arms the SAME alert id (§5); the engine machine is
    the untouched five-state lifecycle."""
    reader = MetricsMapReader()
    reader.add(tuner_sample("tuner.lock_state", 1.0))
    engine = _engine("TUNER_UNLOCKED")

    assert _states(_tick(engine, reader, SNAPSHOT_NS + 1)) == [AlertState.PENDING]
    firing_tick = _tick(engine, reader, SNAPSHOT_NS + 1 + SECOND_NS)
    assert _states(firing_tick) == [AlertState.FIRING]
    firing_id = firing_tick.transitions[0].alert_id

    # Locked again → resolving.
    reader.add(
        tuner_sample("tuner.lock_state", 0.0, value_ns=SNAPSHOT_NS + 2 * SECOND_NS)
    )
    assert _states(_tick(engine, reader, SNAPSHOT_NS + 2 * SECOND_NS + 1)) == [
        AlertState.RESOLVING
    ]

    # resolve_duration 5 s hold elapses → resolved.
    assert _states(
        _tick(engine, reader, SNAPSHOT_NS + 7 * SECOND_NS + 1)
    ) == [AlertState.RESOLVED]

    # Re-open INSIDE the 60 s reopen window → same alert instance re-arms.
    reader.add(
        tuner_sample(
            "tuner.lock_state", 1.0, value_ns=SNAPSHOT_NS + 10 * SECOND_NS
        )
    )
    reopen_tick = _tick(engine, reader, SNAPSHOT_NS + 10 * SECOND_NS + 1)
    assert _states(reopen_tick) == [AlertState.PENDING]
    assert reopen_tick.transitions[0].alert_id == firing_id


def test_session_without_tuner_snapshots_holds_without_false_firing() -> None:
    """缺数据行为 (§11): no samples → missing input → the machine holds
    inactive, the contribution is honest (missing, not firing, not required)."""
    reader = MetricsMapReader()  # no tuner samples at all
    engine = _engine("TUNER_UNLOCKED")
    evaluation = _tick(engine, reader, SNAPSHOT_NS + 1)
    assert evaluation.transitions == ()
    assert len(evaluation.contributions) == 1
    contribution = evaluation.contributions[0]
    assert contribution.input_status == "missing"
    assert contribution.firing is False
    assert contribution.required is False
    assert contribution.state is AlertState.INACTIVE


def test_unlocked_snapshot_does_not_feed_the_ber_rule() -> None:
    """The #164 snapshot face keeps no BER grade when unlocked
    (``ber_state=null``): the unlocked fact drives TUNER_UNLOCKED only —
    BER_SEVERE honestly holds on missing input (no fabricated grade)."""
    reader = MetricsMapReader()
    reader.add(tuner_sample("tuner.lock_state", 1.0))  # ber series absent
    unlocked_engine = _engine("TUNER_UNLOCKED")
    ber_engine = _engine("BER_SEVERE")

    for tick_ns in (SNAPSHOT_NS + 1, SNAPSHOT_NS + 1 + SECOND_NS):
        unlocked_evaluation = _tick(unlocked_engine, reader, tick_ns)
        ber_evaluation = _tick(ber_engine, reader, tick_ns)
        assert _states(unlocked_evaluation) == (
            [AlertState.PENDING]
            if tick_ns == SNAPSHOT_NS + 1
            else [AlertState.FIRING]
        )
        assert ber_evaluation.transitions == ()
    assert ber_evaluation.contributions[0].input_status == "missing"


def test_summary_carries_the_measured_fact_not_the_interpretation() -> None:
    """REQ-OBS-304-006: the fact sentence names the metric, the code and the
    threshold — the declared interpretation stays in rule.description."""
    reader = MetricsMapReader()
    reader.add(tuner_sample("tuner.ber_state", 2.0))
    engine = _engine("BER_SEVERE")
    _tick(engine, reader, SNAPSHOT_NS + 1)
    firing_tick = _tick(engine, reader, SNAPSHOT_NS + 1 + SECOND_NS)
    firing = firing_tick.transitions[0]
    assert firing.to_state is AlertState.FIRING
    assert firing.summary.startswith("tuner.ber_state last = 2")
    assert "satisfies open gte 2" in firing.summary
    assert "rule BER_SEVERE v1.0.0" in firing.summary
    # The evidence ref resolves through the metrics query face shape
    # (bucket start = the tick's evaluation window start).
    firing_now_ns = SNAPSHOT_NS + 1 + SECOND_NS
    assert firing.evidence_refs == (
        "metric:tuner.ber_state:bucket-%d" % (firing_now_ns - RULE_WINDOW_NS),
    )
