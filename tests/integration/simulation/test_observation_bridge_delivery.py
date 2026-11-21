"""Observation bridge delivery (ticket #164, SPEC-303 §Phase3) — the
integration half.

Proves the FULL path end to end, the test_gen_events two-half posture:

1. walk → :func:`emit_state_snapshots` through the REAL emitter with the
   REAL registry (registered by this ticket — the ``is_registered`` guard
   passes through untouched) → ``parse_envelope`` construction guarantee
   → sink; per-node plane archiving, correlation addressing, the constant
   observation-axes pairing and the payload-projection equality.
2. baseline vs faulted re-evaluation → :func:`publish_topology_changes`
   → the ``topology.state_changed`` envelope (the SPEC-202 §6.3 publish
   half wired to the pure-diff half).
3. SIM_STATE Run journal composition over the real gateway → SQLite
   journal read path (SPEC-303 §Phase3): rf.*/sec.* + topology.state_
   changed + fault.* — and never gen.*.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration

from adapters.storage.db import connect
from adapters.storage.journal import SqliteEventJournal
from application.observation.gateway import EventGateway
from domain.observation import parse_envelope
from domain.observation.registry import GEN_EVENT_TYPES, validate_payload
from simulation.events import SimulationEventEmitter
from simulation.state.evaluate import (
    EvalContext,
    Health,
    NodeEvaluator,
    evaluate_topology,
)
from simulation.state.evaluators import DEFAULT_EVALUATORS
from simulation.state.graph import Connection, NodeConfig, PortSpec, TopologyGraph
from simulation.state.observation_bridge import (
    RF_STATE_OBSERVED,
    SEC_STATE_OBSERVED,
    SIM_STATE_JOURNAL_EVENT_TYPES,
    TOPOLOGY_STATE_CHANGED_CHANGED_NODES_KEY,
    TOPOLOGY_STATE_CHANGED_DEGRADED_NODE_COUNT_KEY,
    emit_state_snapshots,
    publish_topology_changes,
)

from tests.unit.simulation.runtime.test_events import RecordingSink

SESSION_ID = "sess-obs-164"
RUN_ID = "run-obs-164"
VIRTUAL_TIME_NS = 42


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
            PortSpec(
                port_id="coax_out",
                direction="output",
                plane="SEC_CONTROL",
                max_connections=2,
            ),
        ],
    )


def _tuner_node(
    node_id: str, frequency_khz: int, polarization: str
) -> NodeConfig:
    return NodeConfig(
        node_id=node_id,
        node_type="tuner",
        config={
            "tuning_request": {
                "frequency_khz": frequency_khz,
                "polarization": polarization,
            },
            "ub_slot": None,
            "diseqc_commands": None,
        },
        ports=[
            PortSpec(
                port_id="rf_in",
                direction="input",
                plane="SEC_CONTROL",
                max_connections=1,
            ),
        ],
    )


def _switch_node(node_id: str = "sw-0") -> NodeConfig:
    return NodeConfig(
        node_id=node_id,
        node_type="diseqc_switch",
        config={"power_pass": "on", "diseqc_commands": None},
        ports=[
            PortSpec(
                port_id="coax_in",
                direction="input",
                plane="SEC_CONTROL",
                max_connections=1,
            ),
            PortSpec(
                port_id="coax_out",
                direction="output",
                plane="SEC_CONTROL",
                max_connections=4,
            ),
        ],
    )


def _connect(
    connection_id: str, from_node: str, from_port: str, to_node: str, to_port: str
) -> Connection:
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
        topology_id="topo-obs-164",
        revision=1,
        nodes=nodes,
        connections=connections,
    )


def _run(graph: TopologyGraph):
    return evaluate_topology(
        graph, evaluators=DEFAULT_EVALUATORS, context=EvalContext(topology_revision=1)
    )


def _baseline_graph() -> TopologyGraph:
    return _graph(
        [_lnb_node(), _tuner_node("tuner-low", 11_095_000, "vertical")],
        [_connect("c1", "lnb-0", "coax_out", "tuner-low", "rf_in")],
    )


def _faulted_graph() -> TopologyGraph:
    # The #163 TONE_RESIDUE transform preview: rewrite the lnb config's
    # tone_actual (post-validation, pre-evaluation) — the tuner 错锁s the
    # 850 MHz neighbour and turns severe/error (the #161 vectors).
    return _graph(
        [_lnb_node(tone_actual="continuous"), _tuner_node("tuner-low", 11_095_000, "vertical")],
        [_connect("c1", "lnb-0", "coax_out", "tuner-low", "rf_in")],
    )


class TestEmitStateSnapshotsDelivery:
    """walk → snapshots through the real emitter + registry + envelope."""

    def test_per_node_snapshots_archive_by_primary_plane(self) -> None:
        sink = RecordingSink()
        emitter = SimulationEventEmitter(sink, wall_ns_source=lambda: 1)
        result = _run(_baseline_graph())
        documents = emit_state_snapshots(
            emitter,
            result,
            graph=_baseline_graph(),
            session_id=SESSION_ID,
            run_id=RUN_ID,
            virtual_time_ns=VIRTUAL_TIME_NS,
        )
        assert [d["event_type"] for d in documents] == [
            SEC_STATE_OBSERVED,  # lnb-0 — walk order first
            RF_STATE_OBSERVED,  # tuner-low
        ]
        for document, node_id in zip(documents, ("lnb-0", "tuner-low")):
            assert document["severity"] == "info"
            assert document["tags"] == ["simulation", "state"]
            assert document["scope"]["session_id"] == SESSION_ID
            assert document["scope"]["run_id"] == RUN_ID
            correlation = document["correlation"]
            assert correlation["node_id"] == node_id
            assert correlation["fault_id"] is None
            assert correlation["pid"] is None
            assert document["time"]["source"]["value_ns"] == VIRTUAL_TIME_NS
            # parse_envelope conformance is the construction guarantee.
            assert parse_envelope(document).event_type == document["event_type"]
            # The payload rides the registry's strict face (F.3 posture).
            validate_payload(document["event_type"], document["payload"])

    def test_snapshot_payload_equals_the_projection(self) -> None:
        sink = RecordingSink()
        emitter = SimulationEventEmitter(sink, wall_ns_source=lambda: 1)
        graph = _baseline_graph()
        result = _run(graph)
        documents = emit_state_snapshots(
            emitter,
            result,
            graph=graph,
            session_id=SESSION_ID,
            run_id=RUN_ID,
            virtual_time_ns=VIRTUAL_TIME_NS,
        )
        lnb_result = result.result_for("lnb-0")
        tuner_result = result.result_for("tuner-low")
        assert documents[0]["payload"] == {
            **lnb_result.metrics,
            "node_id": "lnb-0",
            "health": "ok",
            "causes": [],
            "source": "state_evaluator",
            "confidence": "simulated",
        }
        assert documents[1]["payload"]["lock_state"] == "locked"
        assert documents[1]["payload"]["stale"] is False
        assert documents[1]["payload"]["ber_state"] == "normal"
        assert documents[1]["payload"]["health"] == "ok"

    def test_cause_ref_chain_rides_the_tuner_snapshot(self) -> None:
        # UB-conflict honesty (SPEC-303 §Phase3): the TONE_RESIDUE chain's
        # combination fact is the snapshot's unlocked/locked + CauseRef —
        # no separate event type, no per-metric stream.
        sink = RecordingSink()
        emitter = SimulationEventEmitter(sink, wall_ns_source=lambda: 1)
        graph = _faulted_graph()
        result = _run(graph)
        documents = emit_state_snapshots(
            emitter,
            result,
            graph=graph,
            session_id=SESSION_ID,
            run_id=RUN_ID,
            virtual_time_ns=VIRTUAL_TIME_NS,
        )
        tuner_document = documents[1]
        assert tuner_document["payload"]["lock_state"] == "locked"
        assert tuner_document["payload"]["locked_transponder_id"] == "high@11945000"
        assert tuner_document["payload"]["ber_state"] == "severe"
        assert tuner_document["payload"]["health"] == "error"
        assert any(
            cause["node_id"] == "lnb-0"
            for cause in tuner_document["payload"]["causes"]
        )
        validate_payload(RF_STATE_OBSERVED, tuner_document["payload"])

    def test_legacy_cascade_snapshot_carries_sat_selected(self) -> None:
        graph = _graph(
            [_lnb_node(lnb_kind="legacy_cascade")],
            [],
        )
        sink = RecordingSink()
        emitter = SimulationEventEmitter(sink, wall_ns_source=lambda: 1)
        documents = emit_state_snapshots(
            emitter,
            _run(graph),
            graph=graph,
            session_id=SESSION_ID,
            run_id=RUN_ID,
            virtual_time_ns=VIRTUAL_TIME_NS,
        )
        assert len(documents) == 1
        assert documents[0]["event_type"] == SEC_STATE_OBSERVED
        assert documents[0]["payload"]["sat_selected"] == "A"

    def test_switch_snapshot_is_a_sec_event(self) -> None:
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
        sink = RecordingSink()
        emitter = SimulationEventEmitter(sink, wall_ns_source=lambda: 1)
        documents = emit_state_snapshots(
            emitter,
            _run(graph),
            graph=graph,
            session_id=SESSION_ID,
            run_id=RUN_ID,
            virtual_time_ns=VIRTUAL_TIME_NS,
        )
        assert [d["event_type"] for d in documents] == [
            SEC_STATE_OBSERVED,  # lnb-0
            SEC_STATE_OBSERVED,  # sw-0
            RF_STATE_OBSERVED,  # tuner-low
        ]
        switch_payload = documents[1]["payload"]
        assert switch_payload["power_pass"] == "on"
        assert switch_payload["port_selected"] is None
        assert switch_payload["health"] == "idle"

    def test_factless_evaluations_produce_no_snapshots(self) -> None:
        # Idle fallback (no evaluator registered) and SIM_EVAL_NODE_FAILED
        # isolation both leave ``metrics == {}`` — no fabricated
        # observations; the failure travels with the eval result.
        class _ExplodingLnb(NodeEvaluator):
            def evaluate(self, node, inputs, context):
                raise RuntimeError("isolation preview")

        graph = _graph(
            [_lnb_node(), _tuner_node("tuner-low", 11_095_000, "vertical")],
            [_connect("c1", "lnb-0", "coax_out", "tuner-low", "rf_in")],
        )
        sink = RecordingSink()
        emitter = SimulationEventEmitter(sink, wall_ns_source=lambda: 1)
        documents = emit_state_snapshots(
            emitter,
            evaluate_topology(
                graph,
                evaluators={"lnb": _ExplodingLnb()},
                context=EvalContext(topology_revision=1),
            ),
            graph=graph,
            session_id=SESSION_ID,
            run_id=RUN_ID,
            virtual_time_ns=VIRTUAL_TIME_NS,
        )
        assert documents == ()
        assert sink.events == []


class TestPublishTopologyChangesDelivery:
    """The topology.state_changed publish half over the real envelope."""

    def test_faulted_reevaluation_publishes_the_diff(self) -> None:
        sink = RecordingSink()
        emitter = SimulationEventEmitter(sink, wall_ns_source=lambda: 1)
        baseline = _run(_baseline_graph())
        faulted = _run(_faulted_graph())
        document = publish_topology_changes(
            emitter,
            baseline,
            faulted,
            session_id=SESSION_ID,
            run_id=RUN_ID,
            virtual_time_ns=VIRTUAL_TIME_NS,
        )
        assert document is not None
        assert document["event_type"] == "topology.state_changed"
        assert document["scope"]["run_id"] == RUN_ID
        assert document["payload"] == {
            TOPOLOGY_STATE_CHANGED_CHANGED_NODES_KEY: ["lnb-0", "tuner-low"],
            TOPOLOGY_STATE_CHANGED_DEGRADED_NODE_COUNT_KEY: 1,
        }
        assert parse_envelope(document).event_type == "topology.state_changed"

    def test_identical_results_publish_nothing(self) -> None:
        sink = RecordingSink()
        emitter = SimulationEventEmitter(sink, wall_ns_source=lambda: 1)
        result = _run(_baseline_graph())
        document = publish_topology_changes(
            emitter,
            result,
            result,
            session_id=SESSION_ID,
            run_id=RUN_ID,
            virtual_time_ns=VIRTUAL_TIME_NS,
        )
        assert document is None
        assert sink.events == []


class TestSimStateJournalComposition:
    """SIM_STATE Run journal 构成 over the gateway → SQLite read path."""

    def test_journal_carries_exactly_the_composition(self, journal) -> None:
        connection = connect(journal.db_path, check_same_thread=False)
        journal_adapter = SqliteEventJournal(connection)
        gateway = EventGateway(journal_adapter)
        emitter = SimulationEventEmitter(gateway, wall_ns_source=lambda: 1)

        baseline = _run(_baseline_graph())
        faulted = _run(_faulted_graph())

        snapshots = emit_state_snapshots(
            emitter,
            baseline,
            graph=_baseline_graph(),
            session_id=SESSION_ID,
            run_id=RUN_ID,
            virtual_time_ns=1,
        )
        assert len(snapshots) == 2
        topology_event = publish_topology_changes(
            emitter,
            baseline,
            faulted,
            session_id=SESSION_ID,
            run_id=RUN_ID,
            virtual_time_ns=2,
        )
        assert topology_event is not None
        fault_document = emitter.fault_event(
            "fault.injected",
            SESSION_ID,
            RUN_ID,
            virtual_time_ns=3,
            fault_id="fd000000-0000-4000-8000-000000000164",
            fault_type="TONE_RESIDUE",
            target_node_id="lnb-0",
            target_pid=None,
            payload={
                "fault_id": "fd000000-0000-4000-8000-000000000164",
                "fault_type": "TONE_RESIDUE",
                "injection_index": 0,
                "expected_observations": ["rf.state_observed", "sec.state_observed"],
            },
        )
        assert fault_document is not None
        gateway.drain()

        rows = journal_adapter.query(SESSION_ID, limit=50)
        event_types = [row.event_type for row in rows]
        # The composition face: rf.*/sec.* + topology.state_changed + fault.*.
        assert set(event_types) == {
            RF_STATE_OBSERVED,
            SEC_STATE_OBSERVED,
            "topology.state_changed",
            "fault.injected",
        }
        # …admitted by the bridge's composition predicate…
        assert all(
            event_type in SIM_STATE_JOURNAL_EVENT_TYPES
            for event_type in event_types
        )
        # …and never gen.* (构造事件是 TS 构造域).
        assert not set(event_types) & GEN_EVENT_TYPES
        for row in rows:
            # journal_seq is gateway-stamped (producers never fill it).
            assert row.journal_seq > 0
            assert row.envelope["producer"]["producer_id"] == "simulation-runtime"
            validate_payload(
                row.envelope["event_type"], row.envelope["payload"]
            )
