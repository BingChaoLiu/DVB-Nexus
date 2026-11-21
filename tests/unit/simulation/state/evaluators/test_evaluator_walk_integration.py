"""#161 — the three evaluators through the frozen walk (integration posture).

Seam: ``simulation.state.evaluate.evaluate_topology`` with
``DEFAULT_EVALUATORS`` injected — the ADR-0012 decision-1 composition:
zero new walk machinery, the evaluators plug into the existing
deterministic traversal, severity aggregation, causal threading and
``SIM_EVAL_NODE_FAILED`` isolation.

Chains covered:

- lnb → tuner direct (the SC-11 lab-pack shape, brief §E.11): the A2
  channel must carry the lnb's signal facts to the tuner through the
  walk's ``_input_states`` — the lock arithmetic runs on them.
- lnb → switch → tuner (the legacy cascade shape): the switch merges the
  upstream signal facts onto its output port; the tuner behind it sees
  the same lnb facts plus the register state.
- lnb (SCR) → two tuners fan-out (the SC-10 lab-pack shape, shared coax
  max_connections=2): each SCR tuner locks its own UB carrier.
- Fault-transform preview (#163 seam): rewriting the lnb's
  ``tone_actual`` in the config — the exact TONE_RESIDUE transform —
  propagates through the walk into the tuner's wrong-lock + severe.
- Unregistered feeder type: idle propagation (SPEC-202 §5).
- ``changed_nodes`` diff: baseline vs faulted runs disagree exactly on
  the lnb+tuner pair (the ``topology.state_changed`` pure half).
"""

from __future__ import annotations

import pytest

from simulation.state.evaluate import (
    EvalContext,
    Health,
    changed_nodes,
    evaluate_topology,
)
from simulation.state.evaluators import DEFAULT_EVALUATORS
from simulation.state.graph import Connection, NodeConfig, PortSpec, TopologyGraph

pytestmark = pytest.mark.unit


def _lnb_node(node_id: str = "lnb-0", **config_overrides: object) -> NodeConfig:
    config = {
        "lnb_kind": "universal",
        "lo_frequencies": {"low_khz": 9_750_000, "high_khz": 10_600_000},
        "voltage": "13V",
        "tone_commanded": "none",
        "tone_actual": "none",
        "tone_composite": "none",
        "short_circuit_state": "normal",
    }
    config.update(config_overrides)
    return NodeConfig(
        node_id=node_id,
        node_type="lnb",
        config=config,
        ports=[
            PortSpec(port_id="coax_out", direction="output", plane="SEC_CONTROL", max_connections=2),
        ],
    )


def _tuner_node(
    node_id: str,
    frequency_khz: int,
    polarization: str,
    ub_slot: int | None = None,
) -> NodeConfig:
    return NodeConfig(
        node_id=node_id,
        node_type="tuner",
        config={
            "tuning_request": {"frequency_khz": frequency_khz, "polarization": polarization},
            "ub_slot": ub_slot,
            "diseqc_commands": None,
        },
        ports=[
            PortSpec(port_id="rf_in", direction="input", plane="SEC_CONTROL", max_connections=1),
        ],
    )


def _switch_node(node_id: str = "sw-0") -> NodeConfig:
    return NodeConfig(
        node_id=node_id,
        node_type="diseqc_switch",
        config={"power_pass": "on", "diseqc_commands": None},
        ports=[
            PortSpec(port_id="coax_in", direction="input", plane="SEC_CONTROL", max_connections=1),
            PortSpec(port_id="coax_out", direction="output", plane="SEC_CONTROL", max_connections=4),
        ],
    )


def _connect(connection_id: str, from_node: str, from_port: str, to_node: str, to_port: str):
    return Connection(
        connection_id=connection_id,
        from_node=from_node,
        from_port=from_port,
        to_node=to_node,
        to_port=to_port,
        plane="SEC_CONTROL",
    )


def _graph(nodes: list[NodeConfig], connections: list[Connection]) -> TopologyGraph:
    return TopologyGraph(
        topology_id="topo-l0",
        revision=1,
        nodes=nodes,
        connections=connections,
    )


def _run(graph: TopologyGraph):
    return evaluate_topology(graph, evaluators=DEFAULT_EVALUATORS, context=EvalContext(topology_revision=1))


class TestDirectLnbTunerChain:
    """SC-11 shape: lnb coax_out → tuner rf_in (the A2 channel end to end)."""

    def test_low_band_request_locks_target(self) -> None:
        graph = _graph(
            [_lnb_node(), _tuner_node("tuner-low", 11_095_000, "vertical")],
            [_connect("c1", "lnb-0", "coax_out", "tuner-low", "rf_in")],
        )
        result = _run(graph)
        lnb = result.result_for("lnb-0")
        tuner = result.result_for("tuner-low")
        assert lnb.health is Health.OK
        assert lnb.metrics["band_selected"] == "low"
        assert lnb.metrics["lo_frequency_khz"] == 9_750_000
        assert tuner.metrics["lock_state"] == "locked"
        assert tuner.metrics["locked_transponder_id"] == "low@11095000"
        assert tuner.metrics["if_frequency_khz"] == 1_345_000
        assert tuner.metrics["ber_state"] == "normal"
        assert tuner.health is Health.OK
        assert result.graph_health is Health.OK

    def test_tone_residue_transform_yields_wrong_lock_severe(self) -> None:
        # The #163 TONE_RESIDUE transform preview: rewrite the lnb config's
        # tone_actual (post-validation, pre-evaluation) — the residue stops
        # the LO at the high band, the tuner 错锁s the 850 MHz neighbour.
        graph = _graph(
            [_lnb_node(tone_actual="continuous"), _tuner_node("tuner-low", 11_095_000, "vertical")],
            [_connect("c1", "lnb-0", "coax_out", "tuner-low", "rf_in")],
        )
        result = _run(graph)
        tuner = result.result_for("tuner-low")
        assert tuner.metrics["lock_state"] == "locked"
        assert tuner.metrics["locked_transponder_id"] == "high@11945000"
        assert tuner.metrics["locked_transponder_id"] != "low@11095000"
        assert tuner.metrics["ber_state"] == "severe"
        assert tuner.health is Health.ERROR
        # The anomaly chains: the tuner's causes reach the feeding lnb port.
        assert any(cause.node_id == "lnb-0" for cause in tuner.causes)
        assert result.graph_health is Health.ERROR

    def test_residue_asymmetry_high_band_request_stays_normal(self) -> None:
        # The §11.1 asymmetry assertion: under the same residue the
        # high-band request is unaffected (the delivered continuous tone
        # is exactly what the high band needs).
        graph = _graph(
            [
                _lnb_node(tone_commanded="continuous", tone_actual="continuous", voltage="18V"),
                _tuner_node("tuner-high", 12_070_000, "horizontal"),
            ],
            [_connect("c1", "lnb-0", "coax_out", "tuner-high", "rf_in")],
        )
        result = _run(graph)
        tuner = result.result_for("tuner-high")
        assert tuner.metrics["lock_state"] == "locked"
        assert tuner.metrics["locked_transponder_id"] == "high@12070000"
        assert tuner.metrics["ber_state"] == "normal"
        assert tuner.health is Health.OK

    def test_changed_nodes_diff_between_baseline_and_faulted(self) -> None:
        baseline = _run(
            _graph(
                [_lnb_node(), _tuner_node("tuner-low", 11_095_000, "vertical")],
                [_connect("c1", "lnb-0", "coax_out", "tuner-low", "rf_in")],
            )
        )
        faulted = _run(
            _graph(
                [_lnb_node(tone_actual="continuous"), _tuner_node("tuner-low", 11_095_000, "vertical")],
                [_connect("c1", "lnb-0", "coax_out", "tuner-low", "rf_in")],
            )
        )
        assert changed_nodes(baseline, faulted) == ("lnb-0", "tuner-low")


class TestSwitchChain:
    """lnb → switch → tuner: the switch merges signal facts through."""

    def test_tuner_behind_idle_switch_still_locks(self) -> None:
        # The no-intent switch is command-domain idle but signal-
        # transparent (REPORT-frozen): the tuner behind it locks normally.
        graph = _graph(
            [
                _lnb_node(),
                _switch_node(),
                _tuner_node("tuner-low", 11_095_000, "vertical"),
            ],
            [
                _connect("c1", "lnb-0", "coax_out", "sw-0", "coax_in"),
                _connect("c2", "sw-0", "coax_out", "tuner-low", "rf_in"),
            ],
        )
        result = _run(graph)
        switch = result.result_for("sw-0")
        tuner = result.result_for("tuner-low")
        assert switch.health is Health.IDLE
        assert switch.metrics["committed_switch_state"] == 0
        assert switch.metrics["port_selected"] is None
        assert switch.metrics["power_pass"] == "on"
        assert tuner.metrics["lock_state"] == "locked"
        assert tuner.metrics["locked_transponder_id"] == "low@11095000"
        assert tuner.metrics["ber_state"] == "normal"


class TestScrFanOutChain:
    """SC-10 shape: one SCR lnb fans out to two tuners (max_connections=2)."""

    def _scr_graph(self, tuner_b_slot: int | None = 1) -> TopologyGraph:
        table = [
            {
                "tuner_node": "tuner-a",
                "ub_slot": 0,
                "ub_center_freq_mhz": 1210,
                "position": "A",
                "pin": None,
                "ub_bandwidth_mhz": 46,
            },
            {
                "tuner_node": "tuner-b",
                "ub_slot": 1,
                "ub_center_freq_mhz": 1420,
                "position": "B",
                "pin": None,
                "ub_bandwidth_mhz": 46,
            },
        ]
        lnb = _lnb_node(
            scr={"protocol": "EN50494", "ub_assignments": table},
        )
        tuner_a = _tuner_node("tuner-a", 11_095_000, "vertical", ub_slot=0)
        tuner_b = _tuner_node("tuner-b", 12_070_000, "horizontal", ub_slot=tuner_b_slot)
        return _graph(
            [lnb, tuner_a, tuner_b],
            [
                _connect("c1", "lnb-0", "coax_out", "tuner-a", "rf_in"),
                _connect("c2", "lnb-0", "coax_out", "tuner-b", "rf_in"),
            ],
        )

    def test_both_scr_tuners_lock_their_carriers(self) -> None:
        result = _run(self._scr_graph())
        assert result.result_for("tuner-a").metrics["locked_transponder_id"] == "ub:0:1210"
        assert result.result_for("tuner-b").metrics["locked_transponder_id"] == "ub:1:1420"
        assert result.graph_health is Health.OK

    def test_ub_slot_conflict_transform_breaks_one_tuner(self) -> None:
        # The A1 symptom chain: the UB_SLOT_CONFLICT transform rewrote
        # tuner-b's ub_slot to tuner-a's slot 0 → stacking interference →
        # unlocked + CauseRef to the conflict peer; tuner-a unaffected.
        result = _run(self._scr_graph(tuner_b_slot=0))
        tuner_a = result.result_for("tuner-a")
        tuner_b = result.result_for("tuner-b")
        assert tuner_a.metrics["lock_state"] == "locked"
        assert tuner_a.metrics["locked_transponder_id"] == "ub:0:1210"
        assert tuner_b.metrics["lock_state"] == "unlocked"
        assert tuner_b.metrics["ber_state"] == "severe"
        assert any(cause.node_id == "tuner-a" for cause in tuner_b.causes)
        assert result.graph_health is Health.ERROR


class TestWalkIsolationAndPropagation:
    """SPEC-202 walk semantics stay intact with the real evaluators."""

    def test_unregistered_feeder_propagates_idle(self) -> None:
        mystery = NodeConfig(
            node_id="mystery-0",
            node_type="alien_box",
            config={},
            ports=[PortSpec(port_id="out", direction="output", plane="SEC_CONTROL")],
        )
        graph = _graph(
            [mystery, _tuner_node("tuner-low", 11_095_000, "vertical")],
            [_connect("c1", "mystery-0", "out", "tuner-low", "rf_in")],
        )
        result = _run(graph)
        tuner = result.result_for("tuner-low")
        assert tuner.health is Health.IDLE
        assert tuner.metrics["lock_state"] == "unlocked"
        assert tuner.metrics["stale"] is True

    def test_thrown_evaluator_is_isolated_not_fatal(self) -> None:
        # A foreign evaluator that raises isolates to SIM_EVAL_NODE_FAILED
        # while the real evaluators around it keep working.
        class ExplodingLnb:
            def evaluate(self, node, inputs, context):
                raise RuntimeError("boom")

        graph = _graph(
            [_lnb_node(), _tuner_node("tuner-low", 11_095_000, "vertical")],
            [_connect("c1", "lnb-0", "coax_out", "tuner-low", "rf_in")],
        )
        evaluators = dict(DEFAULT_EVALUATORS)
        evaluators["lnb"] = ExplodingLnb()
        result = evaluate_topology(
            graph, evaluators=evaluators, context=EvalContext(topology_revision=1)
        )
        assert result.result_for("lnb-0").health is Health.ERROR
        assert any(failure.node_id == "lnb-0" for failure in result.failures)
        tuner = result.result_for("tuner-low")
        # The isolated lnb yields empty metrics: the tuner reports
        # unlocked + severe without fabricating an IF.
        assert tuner.metrics["lock_state"] == "unlocked"
        assert tuner.metrics["if_frequency_khz"] is None
        assert tuner.metrics["ber_state"] == "severe"


class TestDeterminismWholeWalk:
    """AC-620-06 / AC-621-05 at the walk level: same graph, same result."""

    def test_double_run_field_identical(self) -> None:
        graph = _graph(
            [
                _lnb_node(),
                _switch_node(),
                _tuner_node("tuner-low", 11_095_000, "vertical"),
            ],
            [
                _connect("c1", "lnb-0", "coax_out", "sw-0", "coax_in"),
                _connect("c2", "sw-0", "coax_out", "tuner-low", "rf_in"),
            ],
        )
        first = _run(graph)
        second = _run(graph)
        assert first == second
        assert changed_nodes(first, second) == ()
