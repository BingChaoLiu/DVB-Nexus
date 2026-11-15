"""Evidence discipline (SPEC-304 §6/§9, REQ-OBS-304-006, ticket #52).

Evidence refs must be RESOLVABLE to immutable source records, contain NO
secret/key material and NO volatile payload text; the persisted summary is
the measured fact and stays free of scope text and interpretation. The ref
grammar is pinned here (``metric:<name>:bucket-<window_start_ns>`` for the
MVP engine; ``journal:<seq>`` is accepted from producers) and the
resolvability itself is exercised end-to-end in the integration chain
(``tests/integration/application/observation/test_obs_alerts_journal_chain.py``).
"""

import re

from application.observation.alerts.engine import AlertEngine, AlertEngineConfig, metric_bucket_ref
from application.observation.alerts.rules import EvidencePolicy
from domain.observation import AlertState

from tests.unit.application.observation.alerts._alerts_fixtures import (
    CannedReader,
    DOMAIN,
    deterministic_alert_id,
    make_rule,
    sample_at,
)

#: The MVP metric-bucket ref grammar (resolvable via the metrics query face;
#: the window start may precede epoch zero for early-window evaluations).
METRIC_REF_PATTERN = re.compile(
    r"^metric:[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*:bucket--?\d+$"
)
JOURNAL_REF_PATTERN = re.compile(r"^journal:\d+$")


def _engine(**overrides) -> AlertEngine:
    return AlertEngine(
        make_rule(**overrides),
        config=AlertEngineConfig(alert_id_factory=deterministic_alert_id()),
    )


def _refs_for(values, now_ns=1_000):
    reader = CannedReader(
        tuple(sample_at(now_ns - 100, value) for value in values)
    )
    engine = _engine()
    evaluation = engine.evaluate(
        "sess-1", reader=reader, now_ns=now_ns, clock_domain=DOMAIN
    )
    return evaluation.transitions


class TestRefGrammar:
    def test_transitions_carry_bucket_format_refs(self) -> None:
        transitions = _refs_for([200.0])
        assert transitions
        for transition in transitions:
            for ref in transition.evidence_refs:
                assert METRIC_REF_PATTERN.match(ref), ref

    def test_refs_vary_with_window_not_with_readings(self) -> None:
        # The ref anchors the immutable window; the reading itself is
        # volatile and must not leak into the token (REQ-304-004 spirit on
        # evidence).
        first = _refs_for([200.0], now_ns=1_000)
        second = _refs_for([987_654.0], now_ns=1_000)
        assert first[-1].evidence_refs == second[-1].evidence_refs

    def test_journal_refs_are_accepted_grammar(self) -> None:
        assert JOURNAL_REF_PATTERN.match("journal:1002")

    def test_none_policy_captures_no_refs(self) -> None:
        rule = make_rule(evidence=EvidencePolicy.NONE)
        reader = CannedReader((sample_at(900, 200.0),))
        engine = AlertEngine(
            rule, config=AlertEngineConfig(alert_id_factory=deterministic_alert_id())
        )
        evaluation = engine.evaluate(
            "sess-1", reader=reader, now_ns=1_000, clock_domain=DOMAIN
        )
        assert evaluation.transitions
        assert all(t.evidence_refs == () for t in evaluation.transitions)


class TestNoSecretsNoScopeLeak:
    """SPEC-304 §9: 告警证据永不暴露密钥；summary 只带测得事实."""

    def test_refs_carry_no_free_text_or_key_material(self) -> None:
        transitions = _refs_for([200.0])
        for transition in transitions:
            for ref in transition.evidence_refs:
                # Grammar-only: metric names, bucket integers — no key=value
                # pairs, no payload text, no separators beyond the grammar.
                assert "=" not in ref and " " not in ref and ";" not in ref

    def test_summary_is_fact_only_without_scope_text(self) -> None:
        transitions = _refs_for([200.0])
        summary = transitions[0].summary
        assert "sess-1" not in summary  # scope text never rides the fact
        assert "pid" not in summary
        assert "key" not in summary.lower()
        assert "secret" not in summary.lower()
        # The declared interpretation text is absent (facts vs inference).
        assert "interpretation" not in summary.lower()

    def test_resolved_states_carry_the_close_measurement_fact(self) -> None:
        reader = CannedReader((sample_at(900, 200.0),))
        engine = _engine()
        engine.evaluate("sess-1", reader=reader, now_ns=1_000, clock_domain=DOMAIN)
        engine.evaluate("sess-1", reader=reader, now_ns=2_000, clock_domain=DOMAIN)
        # The close reading lands AFTER firing (LAST aggregation takes the
        # newest window sample).
        reader.add(sample_at(2_100, 10.0))
        evaluation = engine.evaluate(
            "sess-1", reader=reader, now_ns=3_000, clock_domain=DOMAIN
        )
        resolving = [
            t for t in evaluation.transitions if t.to_state is AlertState.RESOLVING
        ]
        assert resolving
        assert "10" in resolving[0].summary  # the measured close reading
        assert "50" in resolving[0].summary  # the close threshold


def test_metric_bucket_ref_helper_shape() -> None:
    assert (
        metric_bucket_ref("ts.pcr_jitter_ns", 2_000_000_000)
        == "metric:ts.pcr_jitter_ns:bucket-2000000000"
    )
    assert METRIC_REF_PATTERN.match(metric_bucket_ref("ts.pcr_jitter_ns", 1))
