"""SIM_STATE Run orchestration (ticket #165, ADR-0012 decisions 2/5/6).

Unit half — the pure orchestration faces over the frozen upstream seams:

- :func:`simulation.state.run.prepare_state_run` — the prepare gate chain
  (topology gate → bidirectional plan-layer gate → state-layer prepare
  checks) + the A15 intent bridge + the L0 baseline evaluation trigger
  (decision 6: 求值触发点 = Run prepare) + the state-domain fingerprint.
- :func:`simulation.state.run.run_state_run` — the run half: journal
  composition (the #164 bridge emit/publish at both evaluation trigger
  points; no ``gen.*``, honesty discipline SPEC-303 §Phase3), the
  pre-evaluation transform application point (#163's
  ``STATE_TRANSFORM_BY_FAULT_TYPE``), the re-evaluation and the terminal
  state.
- :func:`simulation.state.run.compute_state_run_hash` — the §D.8-derived
  fingerprint (canonical config + plan projection + evaluator/registry
  version + seed; wall clock / session_id / run_id / paths never enter).

All tests are pure (unit layer): no IO, no wall clock (the emitter wall
source is an injected fixed integer), no subprocess.  The fake run host
delegates envelope construction to the REAL :class:`SimulationEventEmitter`
with a collecting sink — the envelopes are parse_envelope-validated, so a
payload-shape violation fails here and not only at the REST face.
"""

from __future__ import annotations

import asyncio

import pytest

from domain.observation.registry import is_registered
from simulation.clock import SimulationClockConfig
from simulation.errors import (
    SIM_STATE_PLAN_INVALID,
    StatePlanInvalidError,
    SimulationValidationError,
)
from simulation.events import SimulationEventEmitter
from simulation.fault_plan import FaultActivation, FaultDefinition
from simulation.runtime import SimulationSessionSpec
from simulation.state.evaluate import Health
from simulation.state.evaluators import DEFAULT_EVALUATORS
from simulation.state.graph import (
    Connection,
    NodeConfig,
    PortSpec,
    TopologyGraph,
)
from simulation.state.observation_bridge import (
    RF_STATE_OBSERVED,
    SEC_STATE_OBSERVED,
    SIM_STATE_JOURNAL_EVENT_TYPES,
    is_sim_state_journal_event_type,
)
from simulation.state.run import (
    PreparedStateRun,
    STATE_RUN_FIDELITY,
    bridge_tuner_diseqc_commands,
    compute_state_run_hash,
    prepare_state_run,
    run_state_run,
)
from simulation.ts_runtime import _canonical_plan

pytestmark = pytest.mark.unit


# --- graph builders (SC-10/SC-11-shaped minimal fixtures) ------------------------


def _lnb(node_id: str = "lnb-0", **overrides) -> NodeConfig:
    config = {
        "lnb_kind": "universal",
        "lo_frequencies": {"low_khz": 9_750_000, "high_khz": 10_600_000},
        "voltage": "13V",
        "tone_commanded": "none",
    }
    config.update(overrides)
    return NodeConfig(
        node_id=node_id,
        node_type="lnb",
        config=config,
        ports=[PortSpec("coax_out", "output", "SEC_CONTROL", 2)],
    )


def _tuner(node_id: str, frequency_khz: int, polarization: str, **overrides) -> NodeConfig:
    config = {
        "tuning_request": {
            "frequency_khz": frequency_khz,
            "polarization": polarization,
        }
    }
    config.update(overrides)
    return NodeConfig(
        node_id=node_id,
        node_type="tuner",
        config=config,
        ports=[PortSpec("rf_in", "input", "SEC_CONTROL", 1)],
    )


def _switch(node_id: str = "sw-0", **overrides) -> NodeConfig:
    config = {"power_pass": "on"}
    config.update(overrides)
    return NodeConfig(
        node_id=node_id,
        node_type="diseqc_switch",
        config=config,
        ports=[
            PortSpec("coax_in", "input", "SEC_CONTROL", 1),
            PortSpec("coax_out", "output", "SEC_CONTROL", 4),
        ],
    )


def _connect(graph_nodes: list[NodeConfig], links: list[tuple[str, str, str, str]]) -> TopologyGraph:
    connections = [
        Connection(
            connection_id=f"conn-{index}",
            from_node=from_node,
            from_port=from_port,
            to_node=to_node,
            to_port=to_port,
            plane="SEC_CONTROL",
        )
        for index, (from_node, from_port, to_node, to_port) in enumerate(links)
    ]
    return TopologyGraph(
        topology_id="topo-state", revision=1, nodes=graph_nodes, connections=connections
    )


def _direct_chain_graph(**lnb_overrides) -> TopologyGraph:
    """lnb → tuner (the SC-11 shape, no switch)."""
    nodes = [_lnb(**lnb_overrides), _tuner("tuner-0", 11_095_000, "vertical")]
    return _connect(nodes, [("lnb-0", "coax_out", "tuner-0", "rf_in")])


def _switch_chain_graph() -> TopologyGraph:
    """lnb → switch → tuner (the A15 bridge shape: intent on the tuner,
    walk evaluates the switch first — 方向不可达)."""
    nodes = [
        _lnb(),
        _switch(),
        _tuner(
            "tuner-0",
            11_095_000,
            "vertical",
            diseqc_commands={
                "target_register": {"committed": True, "uncommitted": False},
                "nibble_writes": [{"register": "committed", "nibble": "low", "value": 1}],
            },
        ),
    ]
    return _connect(
        nodes,
        [
            ("lnb-0", "coax_out", "sw-0", "coax_in"),
            ("sw-0", "coax_out", "tuner-0", "rf_in"),
        ],
    )


def _scr_chain_graph() -> TopologyGraph:
    """SCR shared coax (the SC-10 shape): lnb.scr → two tuners."""
    nodes = [
        _lnb(
            scr={
                "protocol": "EN50494",
                "ub_assignments": [
                    {
                        "tuner_node": "tuner-a",
                        "ub_slot": 0,
                        "ub_center_freq_mhz": 1210,
                        "position": "A",
                    },
                    {
                        "tuner_node": "tuner-b",
                        "ub_slot": 1,
                        "ub_center_freq_mhz": 1420,
                        "position": "B",
                    },
                ],
            }
        ),
        _tuner("tuner-a", 11_095_000, "vertical", ub_slot=0),
        _tuner("tuner-b", 12_070_000, "horizontal", ub_slot=1),
    ]
    return _connect(
        nodes,
        [
            ("lnb-0", "coax_out", "tuner-a", "rf_in"),
            ("lnb-0", "coax_out", "tuner-b", "rf_in"),
        ],
    )


# --- session/plan/fault builders --------------------------------------------------


def _session(graph: TopologyGraph, *, seed: int = 7, session_id: str = "sess-state") -> SimulationSessionSpec:
    return SimulationSessionSpec(
        session_id=session_id,
        topology=graph,
        seed=seed,
        deterministic=True,
        clock_config=SimulationClockConfig(mode="deterministic", start_time_ns=0),
    )


def _tone_residue(*, target_id: str = "lnb-0", tone_actual: str = "continuous") -> FaultDefinition:
    return FaultDefinition(
        fault_id="fault-tone",
        fault_type="TONE_RESIDUE",
        target_id=target_id,
        parameters={"tone_actual": tone_actual},
        activation=FaultActivation(kind="session_start"),
        expected_observations=("sec.state_observed", "rf.state_observed"),
        layer="RF",
    )


def _ub_conflict(*, target_id: str = "tuner-b:ub_slot", slot: int = 0) -> FaultDefinition:
    return FaultDefinition(
        fault_id="fault-ub",
        fault_type="UB_SLOT_CONFLICT",
        target_id=target_id,
        parameters={"conflicting_ub_slot": slot},
        activation=FaultActivation(kind="session_start"),
        expected_observations=("sec.state_observed", "rf.state_observed"),
        layer="SEC",
    )


def _pat_missing() -> FaultDefinition:
    return FaultDefinition(
        fault_id="fault-ts",
        fault_type="PAT_MISSING",
        target_id="demux-0",
        parameters={},
        activation=FaultActivation(kind="session_start"),
        expected_observations=("ts.psi_integrity",),
        layer="TS",
    )


# --- the fake run host -------------------------------------------------------------


class _CollectingSink:
    """Collects delivered envelope documents (unit-layer sink seam)."""

    def __init__(self) -> None:
        self.documents: list[dict] = []

    def publish(self, event: dict) -> None:
        self.documents.append(event)


class FakeStateRunHost:
    """The :class:`simulation.state.run.StateRunHost` structural face over
    the REAL emitter — run records are plain stand-ins."""

    def __init__(self, *, now_ns: int = 500) -> None:
        self.sink = _CollectingSink()
        self.emitter = SimulationEventEmitter(
            self.sink, wall_ns_source=lambda: 1_000_000
        )
        self.now_ns_value = now_ns
        self.completed: list[tuple[str, str]] = []
        self.failed: list[tuple[str, str, str]] = []

    def now_ns(self, session_id: str) -> int:
        return self.now_ns_value

    async def start_run(self, session_id: str):
        self.emitter.run_event(
            "simulation.run_started",
            session_id,
            "run-stub",
            virtual_time_ns=self.now_ns(session_id),
        )
        return _RunViewStub("run-stub")

    async def complete_run(self, session_id: str, run_id: str):
        self.completed.append((session_id, run_id))
        self.emitter.run_event(
            "simulation.run_completed",
            session_id,
            run_id,
            virtual_time_ns=self.now_ns(session_id),
        )
        return _RunViewStub(run_id)

    async def fail_run(self, session_id: str, run_id: str, *, reason: str):
        self.failed.append((session_id, run_id, reason))
        self.emitter.run_event(
            "simulation.run_failed",
            session_id,
            run_id,
            virtual_time_ns=self.now_ns(session_id),
            payload={"run_id": run_id, "reason": reason},
            severity="error",
        )
        return _RunViewStub(run_id)

    def emit_fault_event(
        self,
        session_id: str,
        run_id: str,
        event_type: str,
        *,
        fault_id: str,
        fault_type: str,
        target_node_id,
        target_pid,
        payload=None,
        severity: str = "info",
    ):
        self.emitter.fault_event(
            event_type,
            session_id,
            run_id,
            virtual_time_ns=self.now_ns(session_id),
            fault_id=fault_id,
            fault_type=fault_type,
            target_node_id=target_node_id,
            target_pid=target_pid,
            payload=payload,
            severity=severity,
        )


class _RunViewStub:
    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self.state = "running"


def _driven_run(prepared: PreparedStateRun, host: FakeStateRunHost):
    return asyncio.run(run_state_run(prepared, host))


def _event_types(host: FakeStateRunHost) -> list[str]:
    return [document["event_type"] for document in host.sink.documents]


# --- prepare: the gate chain -------------------------------------------------------


class TestPrepareGates:
    def test_valid_state_plan_prepares_with_baseline_evaluation(self) -> None:
        prepared = prepare_state_run(_session(_direct_chain_graph()), (_tone_residue(),))
        assert isinstance(prepared, PreparedStateRun)
        assert prepared.fault_plan == (_tone_residue(),)
        # ADR-0012 decision 6: prepare triggers the L0 baseline evaluation.
        assert prepared.baseline.graph_health is Health.OK
        lnb_result = prepared.baseline.result_for("lnb-0")
        assert lnb_result is not None
        assert lnb_result.metrics["band_selected"] == "low"

    def test_topology_gate_rejects_invalid_graph(self) -> None:
        # a tuner with no feeder at all is legal; use a plane-mismatched
        # connection instead (SIM_TOPO_MEDIA_INCOMPATIBLE).
        nodes = [_lnb(), _tuner("tuner-0", 11_095_000, "vertical")]
        graph = _connect(nodes, [("lnb-0", "coax_out", "tuner-0", "rf_in")])
        broken = TopologyGraph(
            topology_id=graph.topology_id,
            revision=graph.revision,
            nodes=list(graph.nodes),
            connections=[
                Connection(
                    connection_id="conn-broken",
                    from_node="lnb-0",
                    from_port="coax_out",
                    to_node="tuner-0",
                    to_port="rf_in",
                    plane="RF",  # endpoint planes are SEC_CONTROL
                )
            ],
        )
        with pytest.raises(SimulationValidationError) as excinfo:
            prepare_state_run(_session(broken), ())
        violations = excinfo.value.report.violations
        assert any(v.code == "SIM_TOPO_MEDIA_INCOMPATIBLE" for v in violations)

    def test_package_layer_fault_rejected_on_state_run(self) -> None:
        # the bidirectional gate direction 1: a SIM_STATE run receives a
        # package-layer (TS) fault → SIM_FAULT_*-family rejection.
        with pytest.raises(StatePlanInvalidError) as excinfo:
            prepare_state_run(_session(_direct_chain_graph()), (_pat_missing(),))
        assert excinfo.value.code == SIM_STATE_PLAN_INVALID
        assert any(
            detail.startswith("SIM_FAULT_PLAN_LAYER_MISMATCH")
            for detail in excinfo.value.details
        )

    def test_mixed_plan_rejected_on_state_run(self) -> None:
        with pytest.raises(StatePlanInvalidError):
            prepare_state_run(
                _session(_direct_chain_graph()), (_tone_residue(), _pat_missing())
            )

    def test_unknown_target_node_rejected(self) -> None:
        with pytest.raises(StatePlanInvalidError) as excinfo:
            prepare_state_run(
                _session(_direct_chain_graph()), (_tone_residue(target_id="lnb-x"),)
            )
        assert any(
            detail.startswith("SIM_FAULT_TARGET_INVALID")
            for detail in excinfo.value.details
        )

    def test_non_fault_definition_element_is_type_error(self) -> None:
        with pytest.raises(TypeError):
            prepare_state_run(_session(_direct_chain_graph()), ({"fault_type": "TONE_RESIDUE"},))


# --- prepare: the fingerprint contract ---------------------------------------------


class TestStateFingerprint:
    def test_same_inputs_same_hash(self) -> None:
        session = _session(_direct_chain_graph())
        a = prepare_state_run(session, (_tone_residue(),))
        b = prepare_state_run(session, (_tone_residue(),))
        assert a.config_hash == b.config_hash

    def test_double_run_same_terminal_state(self) -> None:
        # 确定性复现契约（ADR-0012 decision 6）：同 config + plan + 版本
        # + seed → 同终态。
        session = _session(_scr_chain_graph())
        a = _driven_run(
            prepare_state_run(session, (_ub_conflict(),)), FakeStateRunHost()
        )
        b = _driven_run(
            prepare_state_run(session, (_ub_conflict(),)), FakeStateRunHost()
        )
        assert a.node_health == b.node_health
        assert a.graph_health == b.graph_health
        assert a.config_hash == b.config_hash

    def test_fault_id_identity_does_not_change_hash(self) -> None:
        session = _session(_direct_chain_graph())
        a = prepare_state_run(session, (_tone_residue(),))
        other = FaultDefinition(
            fault_id="fault-other-uuid",
            fault_type="TONE_RESIDUE",
            target_id="lnb-0",
            parameters={"tone_actual": "continuous"},
            activation=FaultActivation(kind="session_start"),
            expected_observations=("sec.state_observed", "rf.state_observed"),
            layer="RF",
        )
        b = prepare_state_run(session, (other,))
        assert a.config_hash == b.config_hash

    def test_different_plan_changes_hash(self) -> None:
        session = _session(_direct_chain_graph())
        a = prepare_state_run(session, (_tone_residue(tone_actual="continuous"),))
        b = prepare_state_run(session, (_tone_residue(tone_actual="tone_burst"),))
        assert a.config_hash != b.config_hash

    def test_different_seed_changes_hash(self) -> None:
        graph = _direct_chain_graph()
        a = prepare_state_run(_session(graph, seed=7), ())
        b = prepare_state_run(_session(graph, seed=8), ())
        assert a.config_hash != b.config_hash

    def test_different_config_changes_hash(self) -> None:
        a = prepare_state_run(_session(_direct_chain_graph()), ())
        b = prepare_state_run(_session(_direct_chain_graph(voltage="18V")), ())
        assert a.config_hash != b.config_hash

    def test_session_id_never_enters_hash(self) -> None:
        graph = _direct_chain_graph()
        a = prepare_state_run(_session(graph, session_id="sess-a"), ())
        b = prepare_state_run(_session(graph, session_id="sess-b"), ())
        assert a.config_hash == b.config_hash

    def test_plan_projection_matches_ts_face_document(self) -> None:
        # §D.8: the state-domain plan projection mirrors the TS face
        # field-for-field (drift lock against ts_runtime._canonical_plan).
        plan = (_tone_residue(), _ub_conflict())
        assert compute_state_run_hash  # module face exists
        from simulation.state.run import canonical_state_plan_projection

        assert canonical_state_plan_projection(plan) == _canonical_plan(plan)


# --- A15: the tuner→switch intent bridge -------------------------------------------


class TestTunerIntentBridge:
    def test_tuner_intent_bridges_into_target_switch(self) -> None:
        graph = _switch_chain_graph()
        bridged = bridge_tuner_diseqc_commands(graph)
        switch = bridged.node("sw-0")
        assert switch is not None
        intent = switch.config.get("diseqc_commands")
        assert isinstance(intent, dict)
        assert intent["nibble_writes"] == [
            {"register": "committed", "nibble": "low", "value": 1}
        ]
        # the input graph is never mutated (pure assembly).
        assert "diseqc_commands" not in graph.node("sw-0").config
        assert graph.node("tuner-0").config.get("diseqc_commands") is not None

    def test_switch_own_intent_is_kept(self) -> None:
        own = {
            "target_register": {"committed": True, "uncommitted": False},
            "nibble_writes": [{"register": "committed", "nibble": "high", "value": 2}],
        }
        nodes = [
            _lnb(),
            _switch(**{"diseqc_commands": own}),
            _tuner(
                "tuner-0",
                11_095_000,
                "vertical",
                diseqc_commands={
                    "target_register": {"committed": True, "uncommitted": False},
                    "nibble_writes": [
                        {"register": "committed", "nibble": "low", "value": 1}
                    ],
                },
            ),
        ]
        graph = _connect(
            nodes,
            [
                ("lnb-0", "coax_out", "sw-0", "coax_in"),
                ("sw-0", "coax_out", "tuner-0", "rf_in"),
            ],
        )
        bridged = bridge_tuner_diseqc_commands(graph)
        assert bridged.node("sw-0").config["diseqc_commands"] == own

    def test_no_tuner_intent_leaves_graph_unchanged(self) -> None:
        graph = _switch_chain_graph()
        bare = TopologyGraph(
            topology_id=graph.topology_id,
            revision=graph.revision,
            nodes=[_lnb(), _switch(), _tuner("tuner-0", 11_095_000, "vertical")],
            connections=list(graph.connections),
        )
        bridged = bridge_tuner_diseqc_commands(bare)
        assert bridged.node("sw-0").config == bare.node("sw-0").config

    def test_no_switch_upstream_is_a_no_op(self) -> None:
        graph = _direct_chain_graph(
            diseqc_commands={
                "target_register": {"committed": True, "uncommitted": False},
                "nibble_writes": [{"register": "committed", "nibble": "low", "value": 1}],
            }
        )
        bridged = bridge_tuner_diseqc_commands(graph)
        assert bridged.node("lnb-0").config == graph.node("lnb-0").config

    def test_two_tuners_one_switch_deterministic_last_wins(self) -> None:
        def _intent(value: int) -> dict:
            return {
                "target_register": {"committed": True, "uncommitted": False},
                "nibble_writes": [
                    {"register": "committed", "nibble": "low", "value": value}
                ],
            }

        nodes = [
            _lnb(),
            _switch(),
            _tuner("tuner-a", 11_095_000, "vertical", diseqc_commands=_intent(1)),
            _tuner("tuner-b", 12_070_000, "horizontal", diseqc_commands=_intent(2)),
        ]
        graph = _connect(
            nodes,
            [
                ("lnb-0", "coax_out", "sw-0", "coax_in"),
                ("sw-0", "coax_out", "tuner-a", "rf_in"),
                ("sw-0", "coax_out", "tuner-b", "rf_in"),
            ],
        )
        bridged = bridge_tuner_diseqc_commands(graph)
        # lexicographic tuner application order; the last writer wins.
        assert bridged.node("sw-0").config["diseqc_commands"] == _intent(2)


# --- run: journal composition + transform application point -------------------------


class TestStateRunJournalComposition:
    def test_faulted_run_journal_shape(self) -> None:
        host = FakeStateRunHost()
        prepared = prepare_state_run(_session(_direct_chain_graph()), (_tone_residue(),))
        result = _driven_run(prepared, host)
        assert result.status == "completed"
        types = _event_types(host)
        # honesty discipline: no gen.* construction events, no ts.* faces.
        assert not any(event_type.startswith("gen.") for event_type in types)
        assert not any(event_type.startswith("ts.") for event_type in types)
        # the state-domain events sit inside the frozen composition set.
        state_domain = [
            event_type
            for event_type in types
            if not event_type.startswith("simulation.")
        ]
        assert state_domain, "the run must produce state-domain journal events"
        assert all(is_sim_state_journal_event_type(t) for t in state_domain)
        assert RF_STATE_OBSERVED in types  # the tuner snapshot stream
        assert SEC_STATE_OBSERVED in types  # the lnb snapshot stream
        assert "fault.injected" in types
        assert "topology.state_changed" in types
        assert "simulation.run_started" in types
        assert "simulation.run_completed" in types
        # APPLIED is L1-only (the registry's own comment): the state domain
        # honestly skips it — application evidence rides the snapshots.
        assert "fault.applied" not in types

    def test_baseline_then_faulted_snapshots_differ(self) -> None:
        host = FakeStateRunHost()
        prepared = prepare_state_run(_session(_direct_chain_graph()), (_tone_residue(),))
        _driven_run(prepared, host)
        tuner_snapshots = [
            document
            for document in host.sink.documents
            if document["event_type"] == RF_STATE_OBSERVED
        ]
        assert len(tuner_snapshots) == 2  # baseline emit + re-evaluation emit
        baseline, faulted = tuner_snapshots
        # the L0 baseline: normal lock on the low band.
        assert baseline["payload"]["lock_state"] == "locked"
        assert baseline["payload"]["ber_state"] == "normal"
        assert baseline["payload"]["locked_transponder_id"] == "low@11095000"
        # the faulted re-evaluation: 残留 tone → LO 停在高臂 → 低频段请求
        # IF 偏移 → 错锁同槽高频段转发器 + severe（the A2 symptom chain,
        # SPEC-620 §11.1 — 失锁或错锁 here lands on the 错锁 composite
        # fact, AC-620-03).
        assert faulted["payload"]["lock_state"] == "locked"
        assert faulted["payload"]["ber_state"] == "severe"
        assert faulted["payload"]["locked_transponder_id"] != "low@11095000"
        assert faulted["payload"]["locked_transponder_id"].startswith("high@")
        lnb_snapshots = [
            document
            for document in host.sink.documents
            if document["event_type"] == SEC_STATE_OBSERVED
            and document["payload"]["node_id"] == "lnb-0"
        ]
        assert lnb_snapshots[0]["payload"]["tone_actual"] == "none"
        assert lnb_snapshots[1]["payload"]["tone_actual"] == "continuous"
        # honesty axes: state_evaluator products are simulated, never parsed.
        for snapshot in tuner_snapshots + lnb_snapshots:
            assert snapshot["payload"]["source"] == "state_evaluator"
            assert snapshot["payload"]["confidence"] == "simulated"

    def test_ub_conflict_terminal_state_carries_cause_pair(self) -> None:
        host = FakeStateRunHost()
        prepared = prepare_state_run(_session(_scr_chain_graph()), (_ub_conflict(),))
        result = _driven_run(prepared, host)
        assert result.status == "completed"
        assert result.graph_health is Health.ERROR
        assert result.node_health["tuner-b"] == "error"
        faulted_snapshots = [
            document
            for document in host.sink.documents
            if document["event_type"] == RF_STATE_OBSERVED
            and document["payload"]["node_id"] == "tuner-b"
        ]
        conflict_snapshot = faulted_snapshots[-1]
        assert conflict_snapshot["payload"]["lock_state"] == "unlocked"
        cause_nodes = [
            cause["node_id"] for cause in conflict_snapshot["payload"]["causes"]
        ]
        assert "tuner-a" in cause_nodes

    def test_empty_plan_single_evaluation_and_no_fault_events(self) -> None:
        host = FakeStateRunHost()
        prepared = prepare_state_run(_session(_direct_chain_graph()), ())
        result = _driven_run(prepared, host)
        assert result.status == "completed"
        types = _event_types(host)
        assert not any(t.startswith("fault.") for t in types)
        assert "topology.state_changed" not in types  # no diff → no publish
        # the baseline snapshot stream is the Generate product (decision 2).
        assert RF_STATE_OBSERVED in types
        assert SEC_STATE_OBSERVED in types
        assert host.completed == [("sess-state", result.run_id)]

    def test_state_result_carries_l0_products_and_no_ts_face(self) -> None:
        host = FakeStateRunHost()
        prepared = prepare_state_run(_session(_direct_chain_graph()), (_tone_residue(),))
        result = _driven_run(prepared, host)
        assert result.topology_id == "topo-state"
        assert result.graph_health is Health.ERROR
        assert result.node_health["tuner-0"] == "error"
        assert result.node_health["lnb-0"] == "ok"
        assert result.snapshot_event_count > 0
        assert result.config_hash == prepared.config_hash

    def test_registered_event_types_only(self) -> None:
        host = FakeStateRunHost()
        prepared = prepare_state_run(_session(_direct_chain_graph()), (_tone_residue(),))
        _driven_run(prepared, host)
        for event_type in _event_types(host):
            assert is_registered(event_type), event_type


# --- the health-display data-source switch (ADR-0012 decision 5, backend half) ------


class TestHealthDisplayDataSource:
    def test_session_initial_eval_uses_l0_evaluators_and_bridge(self) -> None:
        # the snapshot node_states health now derives from the L0 products
        # over the A15-bridged assembly — the degraded idle path is retired.
        from simulation.runtime import SimulationRuntime

        runtime = SimulationRuntime()
        session = asyncio.run(
            runtime.create_session(_session(_switch_chain_graph()))
        )
        switch_state = session.node_states["sw-0"]
        # the bridged intent selects port 1 (committed low nibble = 1) — the
        # degraded path would have reported idle here.
        assert switch_state.health is Health.OK


# --- STATE_RUN_FIDELITY constant -----------------------------------------------------


def test_state_run_fidelity_wire_value() -> None:
    assert STATE_RUN_FIDELITY == "SIM_STATE"
