"""SPEC-202 section 6 — evaluation interface tests (ticket #40).

Seam: ``simulation.state.evaluate`` — the frozen evaluation surface SIM-E
(#44) depends on. The full L0 node-semantics evaluation is DEFERRED out of
MVP (ADR-0005 decision 2, issue #40); what is frozen and tested here is the
interface plus the deterministic skeleton walk: order, idle stub for
unregistered node types, severity precedence, causal reference threading,
SIM_EVAL_NODE_FAILED isolation and the state_changed diff helper.

Determinism discipline (tests/README section 5): every context is built
with fixed integers; no wall clock, no sleep, no randomness.
"""

from __future__ import annotations

import dataclasses
from typing import Mapping

import pytest

from simulation.errors import SIM_EVAL_NODE_FAILED
from simulation.state.evaluate import (
    SIM_EVAL_NODE_FAILED as FAILURE_CODE,
)
from simulation.state.evaluate import (
    CauseRef,
    EvalContext,
    Health,
    NodeEvalResult,
    NodeFailure,
    PortState,
    TopologyEvalResult,
    changed_nodes,
    evaluate_topology,
)
from simulation.state.graph import (
    Connection,
    NodeConfig,
    PortSpec,
    TopologyGraph,
    topological_order,
)

pytestmark = pytest.mark.unit


# -- test double: a configurable pure stub evaluator ---------------------------


class _StubEvaluator:
    """Pure evaluator returning a fixed health, echoing nothing else."""

    def __init__(self, health: str = "ok", fail: bool = False) -> None:
        self._health = health
        self._fail = fail

    def evaluate(
        self,
        node: NodeConfig,
        inputs: Mapping[str, PortState],
        context: EvalContext,
    ) -> NodeEvalResult:
        if self._fail:
            raise RuntimeError("boom: evaluator-internal failure")
        return NodeEvalResult(
            node_id=node.node_id,
            health=Health(self._health),
            port_states=tuple(
                PortState(port.port_id, Health(self._health))
                for port in node.ports
            ),
            metrics={"context_virtual_ns": context.virtual_time_ns},
            causes=(),
        )


def _port(port_id: str, direction: str = "input") -> PortSpec:
    return PortSpec(port_id=port_id, direction=direction, plane="MPEG_TS")


def _node(node_id: str, *ports: PortSpec, node_type: str = "mux") -> NodeConfig:
    return NodeConfig(
        node_id=node_id, node_type=node_type, config={}, ports=list(ports)
    )


def _chain_graph(node_order: list[str]) -> TopologyGraph:
    """src -> mid -> sink linear chain (all MPEG_TS in/out ports)."""
    by_id = {
        "src": _node("src", _port("out-0", "output"), node_type="tuner"),
        "mid": _node("mid", _port("in-0"), _port("out-0", "output")),
        "sink": _node("sink", _port("in-0"), node_type="monitor"),
    }
    return TopologyGraph(
        topology_id="topo-chain",
        revision=7,
        nodes=[by_id[name] for name in node_order],
        connections=[
            Connection(
                connection_id="c1",
                from_node="src",
                from_port="out-0",
                to_node="mid",
                to_port="in-0",
                plane="MPEG_TS",
            ),
            Connection(
                connection_id="c2",
                from_node="mid",
                from_port="out-0",
                to_node="sink",
                to_port="in-0",
                plane="MPEG_TS",
            ),
        ],
    )


class TestFrozenSurface:
    """Interface freeze: types SIM-E (#44) will import."""

    def test_result_types_are_frozen(self) -> None:
        for instance in (
            CauseRef(node_id="src", port_id="out-0"),
            PortState(port_id="out-0", health=Health.OK),
            NodeEvalResult(node_id="src", health=Health.OK),
            NodeFailure(node_id="src", code=SIM_EVAL_NODE_FAILED, detail="d"),
            EvalContext(topology_revision=1),
        ):
            attribute = dataclasses.fields(instance)[0].name
            with pytest.raises(dataclasses.FrozenInstanceError):
                setattr(instance, attribute, None)  # type: ignore[misc]

    def test_health_vocabulary_matches_spec(self) -> None:
        """SPEC-202 section 6.1: health is ok/warn/error/idle."""
        assert {item.value for item in Health} == {
            "ok",
            "warn",
            "error",
            "idle",
        }

    def test_severity_precedence_error_gt_warn_gt_idle_gt_ok(self) -> None:
        """SPEC-202 section 6.2: error > warn > idle > ok."""
        from simulation.state.evaluate import severity_rank

        assert severity_rank(Health.ERROR) > severity_rank(Health.WARN)
        assert severity_rank(Health.WARN) > severity_rank(Health.IDLE)
        assert severity_rank(Health.IDLE) > severity_rank(Health.OK)

    def test_eval_context_carries_no_wall_clock(self) -> None:
        """SPEC-202 section 6.1: EvalContext carries revision, a committed
        virtual-time reading and a node config version — never a wall
        clock. Structural check: every field is an int."""
        context = EvalContext(
            topology_revision=3,
            node_config_version=2,
            virtual_time_ns=1_000_000,
        )
        for field in dataclasses.fields(context):
            value = getattr(context, field.name)
            assert isinstance(value, int) and not isinstance(value, bool)


class TestL0DeferredStub:
    """The L0 evaluation point is an explicit stub (ADR-0005 decision 2)."""

    def test_unregistered_node_type_evaluates_idle(self) -> None:
        graph = _chain_graph(["src", "mid", "sink"])
        result = evaluate_topology(graph)
        for node_result in result.node_results:
            assert node_result.health is Health.IDLE
            assert node_result.metrics == {}
            assert node_result.causes == ()

    def test_deferred_rationale_is_recorded(self) -> None:
        """The stub records its deferred basis for review/audit."""
        from simulation.state import evaluate as evaluate_module

        rationale = evaluate_module.L0_DEFERRED_RATIONALE
        assert "ADR-0005" in rationale
        assert "decision 2" in rationale

    def test_isolated_node_reports_idle(self) -> None:
        """SPEC-202 section 5: isolated nodes are legal, report idle."""
        graph = TopologyGraph(
            topology_id="topo-island",
            revision=0,
            nodes=[_node("lonely", _port("in-0"))],
            connections=[],
        )
        result = evaluate_topology(graph)
        assert result.node_results[0].health is Health.IDLE
        assert result.graph_health is Health.IDLE


class TestDeterministicWalk:
    """REQ-SIM-202-003 skeleton: same graph + config, same result."""

    def test_repeated_evaluation_is_field_identical(self) -> None:
        graph = _chain_graph(["src", "mid", "sink"])
        evaluators = {"tuner": _StubEvaluator("ok"), "monitor": _StubEvaluator("ok")}
        first = evaluate_topology(
            graph,
            evaluators=evaluators,  # type: ignore[arg-type]
            context=EvalContext(topology_revision=7, virtual_time_ns=42),
        )
        second = evaluate_topology(
            graph,
            evaluators=evaluators,  # type: ignore[arg-type]
            context=EvalContext(topology_revision=7, virtual_time_ns=42),
        )
        assert first == second

    def test_shuffled_node_lists_yield_identical_results(self) -> None:
        evaluators = {"tuner": _StubEvaluator("ok"), "monitor": _StubEvaluator("ok")}
        expected = evaluate_topology(
            _chain_graph(["src", "mid", "sink"]),
            evaluators=evaluators,  # type: ignore[arg-type]
            context=EvalContext(topology_revision=7),
        )
        for order in (["sink", "mid", "src"], ["mid", "sink", "src"]):
            result = evaluate_topology(
                _chain_graph(order),
                evaluators=evaluators,  # type: ignore[arg-type]
                context=EvalContext(topology_revision=7),
            )
            assert result == expected

    def test_walk_follows_topological_order(self) -> None:
        graph = _chain_graph(["sink", "mid", "src"])
        result = evaluate_topology(graph)
        assert result.order == topological_order(graph)
        assert result.order == ("src", "mid", "sink")

    def test_context_virtual_time_reaches_evaluator(self) -> None:
        """Dependency injection: the committed virtual time arrives via
        EvalContext (no wall clock is read anywhere)."""
        graph = _chain_graph(["src", "mid", "sink"])
        evaluators = {"tuner": _StubEvaluator("ok"), "monitor": _StubEvaluator("ok")}
        result = evaluate_topology(
            graph,
            evaluators=evaluators,  # type: ignore[arg-type]
            context=EvalContext(topology_revision=7, virtual_time_ns=12345),
        )
        src = result.result_for("src")
        assert src is not None
        assert src.metrics == {"context_virtual_ns": 12345}

    def test_input_port_state_feeds_downstream(self) -> None:
        """Downstream evaluators receive per-input-port upstream health."""

        class InputRecorder(_StubEvaluator):
            seen: dict = {}

            def evaluate(self, node, inputs, context):
                InputRecorder.seen[node.node_id] = dict(inputs)
                return super().evaluate(node, inputs, context)

        graph = _chain_graph(["src", "mid", "sink"])
        evaluators = {
            "tuner": _StubEvaluator("warn"),
            "mux": InputRecorder("ok"),
        }
        evaluate_topology(
            graph,
            evaluators=evaluators,  # type: ignore[arg-type]
            context=EvalContext(topology_revision=1),
        )
        assert InputRecorder.seen["mid"]["in-0"].health is Health.WARN


class TestSeverityAggregation:
    """SPEC-202 section 6.2: severity precedence over the whole graph."""

    def test_graph_health_takes_maximum_severity(self) -> None:
        graph = _chain_graph(["src", "mid", "sink"])
        evaluators = {
            "tuner": _StubEvaluator("ok"),
            "monitor": _StubEvaluator("warn"),
        }
        result = evaluate_topology(
            graph,
            evaluators=evaluators,  # type: ignore[arg-type]
            context=EvalContext(topology_revision=1),
        )
        assert result.graph_health is Health.WARN

    def test_error_beats_warn(self) -> None:
        graph = _chain_graph(["src", "mid", "sink"])
        evaluators = {
            "tuner": _StubEvaluator("warn"),
            "monitor": _StubEvaluator("error"),
        }
        result = evaluate_topology(
            graph,
            evaluators=evaluators,  # type: ignore[arg-type]
            context=EvalContext(topology_revision=1),
        )
        assert result.graph_health is Health.ERROR

    def test_all_ok_graph_is_ok(self) -> None:
        graph = _chain_graph(["src", "mid", "sink"])
        evaluators = {
            "tuner": _StubEvaluator("ok"),
            "mux": _StubEvaluator("ok"),
            "monitor": _StubEvaluator("ok"),
        }
        result = evaluate_topology(
            graph,
            evaluators=evaluators,  # type: ignore[arg-type]
            context=EvalContext(topology_revision=1),
        )
        assert result.graph_health is Health.OK


class TestCausalReferences:
    """REQ-SIM-202-004: downstream anomalies carry root-cause references."""

    def test_downstream_of_error_carries_cause_ref(self) -> None:
        graph = _chain_graph(["src", "mid", "sink"])
        evaluators = {
            "tuner": _StubEvaluator("error"),
            "mux": _StubEvaluator("error"),
            "monitor": _StubEvaluator("error"),
        }
        result = evaluate_topology(
            graph,
            evaluators=evaluators,  # type: ignore[arg-type]
            context=EvalContext(topology_revision=1),
        )
        sink = result.result_for("sink")
        assert sink is not None
        assert CauseRef(node_id="src", port_id="out-0") in sink.causes
        assert CauseRef(node_id="mid", port_id="out-0") in sink.causes

    def test_chain_reaches_the_root_cause(self) -> None:
        """Transitive threading: src -> mid -> sink, src is the root."""
        graph = _chain_graph(["src", "mid", "sink"])
        evaluators = {
            "tuner": _StubEvaluator("error"),
            "mux": _StubEvaluator("error"),
            "monitor": _StubEvaluator("error"),
        }
        result = evaluate_topology(
            graph,
            evaluators=evaluators,  # type: ignore[arg-type]
            context=EvalContext(topology_revision=1),
        )
        mid = result.result_for("mid")
        sink = result.result_for("sink")
        assert mid is not None and sink is not None
        mid_cause_nodes = {cause.node_id for cause in mid.causes}
        sink_cause_nodes = {cause.node_id for cause in sink.causes}
        assert "src" in mid_cause_nodes
        # The chain from sink reaches past mid to the root src.
        assert "src" in sink_cause_nodes and "mid" in sink_cause_nodes

    def test_healthy_upstream_adds_no_causes(self) -> None:
        graph = _chain_graph(["src", "mid", "sink"])
        evaluators = {"tuner": _StubEvaluator("ok"), "monitor": _StubEvaluator("ok")}
        result = evaluate_topology(
            graph,
            evaluators=evaluators,  # type: ignore[arg-type]
            context=EvalContext(topology_revision=1),
        )
        sink = result.result_for("sink")
        assert sink is not None
        assert sink.causes == ()

    def test_idle_upstream_is_not_an_anomaly(self) -> None:
        """Idle (e.g. isolated upstream) is legal, not an abnormal state —
        no causal references are manufactured for it."""
        graph = TopologyGraph(
            topology_id="topo-idle-up",
            revision=0,
            nodes=[
                _node("idle-up", _port("in-0")),
                _node("down", _port("in-0")),
            ],
            connections=[
                Connection(
                    connection_id="c1",
                    from_node="idle-up",
                    from_port="in-0",
                    to_node="down",
                    to_port="in-0",
                    plane="MPEG_TS",
                )
            ],
        )
        result = evaluate_topology(
            graph, context=EvalContext(topology_revision=0)
        )
        down = result.result_for("down")
        assert down is not None
        assert down.causes == ()


class TestNodeFailureIsolation:
    """SPEC-202 section 8: SIM_EVAL_NODE_FAILED isolates the node."""

    def test_raising_evaluator_is_isolated_as_error(self) -> None:
        graph = _chain_graph(["src", "mid", "sink"])
        evaluators = {
            "tuner": _StubEvaluator("ok", fail=True),
            "monitor": _StubEvaluator("ok"),
        }
        result = evaluate_topology(
            graph,
            evaluators=evaluators,  # type: ignore[arg-type]
            context=EvalContext(topology_revision=1),
        )
        src = result.result_for("src")
        assert src is not None
        assert src.health is Health.ERROR
        assert len(result.failures) == 1
        failure = result.failures[0]
        assert failure.node_id == "src"
        assert failure.code == FAILURE_CODE == SIM_EVAL_NODE_FAILED
        assert result.graph_health is Health.ERROR

    def test_isolation_does_not_crash_the_rest_of_the_graph(self) -> None:
        graph = _chain_graph(["src", "mid", "sink"])
        evaluators = {
            "tuner": _StubEvaluator("ok", fail=True),
            "monitor": _StubEvaluator("ok"),
        }
        result = evaluate_topology(
            graph,
            evaluators=evaluators,  # type: ignore[arg-type]
            context=EvalContext(topology_revision=1),
        )
        assert len(result.node_results) == 3
        sink = result.result_for("sink")
        assert sink is not None
        assert sink.health is Health.OK

    def test_isolated_node_ports_do_not_read_healthy(self) -> None:
        graph = _chain_graph(["src", "mid", "sink"])
        evaluators = {"tuner": _StubEvaluator("ok", fail=True), "monitor": _StubEvaluator("ok")}
        result = evaluate_topology(
            graph,
            evaluators=evaluators,  # type: ignore[arg-type]
            context=EvalContext(topology_revision=1),
        )
        src = result.result_for("src")
        assert src is not None
        assert all(
            port.health is Health.ERROR for port in src.port_states
        )


class TestStateChangeDiff:
    """SPEC-202 section 6.3: change detection feeding the
    ``topology.state_changed`` emission obligation (envelope emission is
    the consumers' obligation — SIM-C/D; this is the pure diff half)."""

    def test_no_change_yields_empty_diff(self) -> None:
        graph = _chain_graph(["src", "mid", "sink"])
        evaluators = {"tuner": _StubEvaluator("ok"), "monitor": _StubEvaluator("ok")}
        context = EvalContext(topology_revision=1)
        first = evaluate_topology(
            graph,
            evaluators=evaluators,  # type: ignore[arg-type]
            context=context,
        )
        second = evaluate_topology(
            graph,
            evaluators=evaluators,  # type: ignore[arg-type]
            context=context,
        )
        assert changed_nodes(first, second) == ()

    def test_health_change_is_reported_sorted(self) -> None:
        graph = _chain_graph(["src", "mid", "sink"])
        before = evaluate_topology(
            graph,
            evaluators={"tuner": _StubEvaluator("ok"), "monitor": _StubEvaluator("ok")},
            context=EvalContext(topology_revision=1),
        )
        after = evaluate_topology(
            graph,
            evaluators={
                "tuner": _StubEvaluator("error"),
                "monitor": _StubEvaluator("warn"),
            },
            context=EvalContext(topology_revision=1),
        )
        assert changed_nodes(before, after) == ("mid", "sink", "src")

    def test_diff_is_symmetric_in_arguments(self) -> None:
        graph = _chain_graph(["src", "mid", "sink"])
        before = evaluate_topology(graph, context=EvalContext(topology_revision=1))
        after = evaluate_topology(
            graph,
            evaluators={"tuner": _StubEvaluator("error"), "monitor": _StubEvaluator("ok")},
            context=EvalContext(topology_revision=1),
        )
        assert changed_nodes(before, after) == changed_nodes(after, before) == (
            "mid",
            "sink",
            "src",
        )


class TestCycleInput:
    def test_cyclic_graph_is_refused(self) -> None:
        """Evaluation requires a DAG; cycles are the validator's rejection
        (SPEC-202 section 5) and are refused here too."""
        graph = TopologyGraph(
            topology_id="topo-cycle",
            revision=0,
            nodes=[
                _node("x", _port("in-0"), _port("out-0", "output")),
                _node("y", _port("in-0"), _port("out-0", "output")),
            ],
            connections=[
                Connection(
                    connection_id="c1",
                    from_node="x",
                    from_port="out-0",
                    to_node="y",
                    to_port="in-0",
                    plane="MPEG_TS",
                ),
                Connection(
                    connection_id="c2",
                    from_node="y",
                    from_port="out-0",
                    to_node="x",
                    to_port="in-0",
                    plane="MPEG_TS",
                ),
            ],
        )
        from simulation.errors import TopologyCycleError

        with pytest.raises(TopologyCycleError):
            evaluate_topology(graph, context=EvalContext(topology_revision=0))


class TestResultSurface:
    def test_result_for_unknown_node_returns_none(self) -> None:
        graph = _chain_graph(["src", "mid", "sink"])
        result = evaluate_topology(graph, context=EvalContext(topology_revision=1))
        assert result.result_for("ghost") is None

    def test_result_carries_topology_identity(self) -> None:
        graph = _chain_graph(["src", "mid", "sink"])
        result = evaluate_topology(graph, context=EvalContext(topology_revision=9))
        assert isinstance(result, TopologyEvalResult)
        assert result.topology_id == "topo-chain"
        assert result.revision == 9
