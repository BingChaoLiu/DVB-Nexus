"""Phase 3 rules × the two state-layer injection paths (ticket #168
acceptance, SPEC-307 §Phase3 + the SPEC-303 §Phase3 journal composition).

Each rule is interlocked against the REAL injected SIM_STATE run of its
paired primitive (#163 TONE_RESIDUE / UB_SLOT_CONFLICT) through the #165
state-run orchestration — the A2 (tone residue) and A1 (UB conflict)
chains emit ``rf.state_observed`` / ``sec.state_observed`` snapshots with
the exact registered payload key sets (#164), and the paired rule's
declaration is proven to consume exactly those shapes (the
expected_evidence 互证 + the match/predicate key interlock against REAL
producer output, not fixture mirrors — the Phase 2 candidates posture).

判据互锁 posture (NOT a diagnose-face candidate assertion): the engine's
SPEC-306 §6 anchor gate has no state for the state-snapshot family (the
registered exact-key payloads carry neither the MVP triple nor the Phase
2 evidence-family locator face), so the rules stay loadable-but-unfired
under the frozen engine — asserted here on REAL run output so a silent
gate change cannot pass unnoticed (the #130 → #138 precedent face; the
anchor-path expansion is the recorded follow-up, ticket #168 REPORT).

Predicate-face honesty asserted on REAL output: the eq faces (the
SPEC-303 §Phase3 恒定配对 + the graded/unlocked discriminators) hold on
the real faulted snapshots and fail the clean/ungraded ones; the
CauseRef-array face (``causes[*].node_id`` — lnb reference / conflict
peer) and the cross-event ``sec.state_observed`` faces (tone 双字段 /
``ub_assignments`` 表, key-signature discriminated by the registry
constants) are consumed as the same-run combination facts the 互证
covers — outside the finite single-event predicate set (ticket #168
REPORT deviation).

Marked integration: drives the real SIM_STATE run orchestration (real
evaluation walk, real emitter delivery, no wall clock — asyncio.run over
the driver).
"""

from __future__ import annotations

import asyncio

import pytest

pytestmark = pytest.mark.integration

from domain.diagnosis.engine import DiagnosisEvaluator, ObservationRecord
from domain.diagnosis.rules import load_builtin_rules
from domain.observation.registry import (
    SEC_LNB_SNAPSHOT_KEYS,
    validate_payload,
)
from simulation.clock import SimulationClockConfig
from simulation.fault_plan import FaultActivation, FaultDefinition
from simulation.runtime import SimulationRuntime, SimulationSessionSpec
from simulation.state.graph import (
    Connection,
    NodeConfig,
    PortSpec,
    TopologyGraph,
)
from simulation.state.run import prepare_state_run, run_state_run
from simulation.state.validate import TUNER_NODE_TYPE

EVALUATOR = DiagnosisEvaluator()
NOW_MS = 1_700_000_000_000

RULE_TONE = "DIA-TONE-RESIDUE-SUSPECT"
RULE_UB = "DIA-UB-CONFLICT-SUSPECT"

RF_STATE = "rf.state_observed"
SEC_STATE = "sec.state_observed"


# --- graph builders (the SC-11 direct chain and the SC-10 SCR chain) --------------


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
        node_type=TUNER_NODE_TYPE,
        config=config,
        ports=[PortSpec("rf_in", "input", "SEC_CONTROL", 1)],
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
        topology_id="topo-dia-168", revision=1, nodes=graph_nodes, connections=connections
    )


def _direct_chain_graph(tuning_frequency_khz: int = 11_095_000) -> TopologyGraph:
    """lnb → tuner (the SC-11 shape, no switch)."""
    nodes = [
        _lnb(),
        _tuner("tuner-0", tuning_frequency_khz, "vertical"),
    ]
    return _connect(nodes, [("lnb-0", "coax_out", "tuner-0", "rf_in")])


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


# --- plan builders (the #163 primitives, SC-draft expected_observations) -----------


def _tone_residue(*, tone_actual: str = "continuous") -> FaultDefinition:
    return FaultDefinition(
        fault_id="fd000000-0000-4000-8000-000000000168",
        fault_type="TONE_RESIDUE",
        target_id="lnb-0",
        parameters={"tone_actual": tone_actual},
        activation=FaultActivation(kind="session_start", packet_index=None),
        expected_observations=[SEC_STATE, RF_STATE],
        layer="RF",
    )


def _ub_conflict() -> FaultDefinition:
    return FaultDefinition(
        fault_id="fd000000-0000-4000-8000-000000000169",
        fault_type="UB_SLOT_CONFLICT",
        target_id="tuner-b:ub_slot",
        parameters={"conflicting_ub_slot": 0},
        activation=FaultActivation(kind="session_start", packet_index=None),
        expected_observations=[SEC_STATE, RF_STATE],
        layer="SEC",
    )


# --- the real SIM_STATE drive (the Phase 2 _run_layered posture) -------------------


def _run_state(graph: TopologyGraph, plan: tuple) -> list[dict]:
    """One real SIM_STATE run through the full wired delivery posture: the
    emitted envelopes cross the shared emitter path (registry guard +
    payload schema + parse_envelope construction), and the delivered
    documents are what the assertions consume."""
    events: list[dict] = []

    class RecordingGateway:
        def publish(self, event) -> None:
            events.append(dict(event))

    async def main() -> None:
        runtime = SimulationRuntime(event_sink=RecordingGateway())
        session = SimulationSessionSpec(
            session_id="dia-phase3-168",
            topology=graph,
            seed=7,
            deterministic=True,
            clock_config=SimulationClockConfig(mode="deterministic", start_time_ns=0),
        )
        await runtime.create_session(session)
        await runtime.validate_session(session.session_id)
        await runtime.start(session.session_id)
        prepared = prepare_state_run(session, plan)
        result = await run_state_run(prepared, runtime)
        assert result.status == "completed", result

    asyncio.run(main())
    return events


def _collected(events: list[dict], event_type: str) -> list[dict]:
    """The run's REAL delivered payloads for one event type (emission
    order preserved) — envelopes that already cleared the full ADR-0006
    path (registry guard + payload schema)."""
    return [
        dict(event["payload"])
        for event in events
        if event["event_type"] == event_type
    ]


def _rule(rule_id: str):
    return next(rule for rule in load_builtin_rules() if rule.rule_id == rule_id)


def _faulted_rf_payload(payloads: list[dict], node_id: str) -> dict:
    """The LAST snapshot of one tuner node (trigger 2 — the faulted
    re-evaluation; trigger 1 is the baseline)."""
    faulted = [payload for payload in payloads if payload["node_id"] == node_id]
    assert faulted, f"no rf snapshot for {node_id}"
    return faulted[-1]


def _eq_predicates(rule):
    return [
        predicate for predicate in rule.match.predicates if predicate.op == "eq"
    ]


def _predicates_hold(rule, payload: dict) -> bool:
    record = ObservationRecord(
        journal_seq=1,
        event_type=rule.match.event_type,
        event_id="obs-interlock",
        payload=dict(payload),
        node_id=str(payload["node_id"]),
    )
    return all(predicate.holds(record) for predicate in rule.match.predicates)


def _interlock_asserts(rule_id: str, payloads: list[dict]) -> None:
    """The shared interlock: the rule references exactly the event symbol
    its primitive really emits, its predicates address exactly the REAL
    payload keys, and every real payload clears the engine's own
    registry gate (the payload shapes the rules pin are the producer's)."""
    rule = _rule(rule_id)
    assert rule.match.event_type == RF_STATE
    assert payloads, f"the {RF_STATE} snapshot never fired in the real run"
    for payload in payloads:
        validate_payload(rule.match.event_type, payload)
        real_keys = {f"payload.{key}" for key in payload}
        predicate_fields = {
            predicate.field for predicate in rule.match.predicates
        }
        assert predicate_fields == real_keys


def _evaluator_stays_candidate_free(payloads: list[dict]) -> None:
    """The 判据互锁 honesty face on REAL producer output: the state
    snapshots carry no SPEC-306 §6 anchor state, so the full evaluator
    produces no candidate and no warning (no anchor, no candidate; the
    payloads are registry-valid — no skip warnings either)."""
    records = tuple(
        ObservationRecord(
            journal_seq=index + 1,
            event_type=RF_STATE,
            event_id=f"obs-rf-{index}",
            payload=dict(payload),
            node_id=str(payload["node_id"]),
        )
        for index, payload in enumerate(payloads)
    )
    outcome = EVALUATOR.evaluate(
        "sess-x",
        "run-x",
        records,
        load_builtin_rules(),
        now_utc_ms=NOW_MS,
    )
    assert outcome.report.candidates == ()
    assert outcome.report.warnings == ()


class TestToneResidueCandidate:
    """「LNB tone 残留 / 供电异常」: the real A2 chain run emits the tuner
    snapshot family and DIA-TONE-RESIDUE-SUSPECT consumes exactly that
    shape."""

    def test_rule_interlocks_with_the_real_run_emission(self):
        events = _run_state(_direct_chain_graph(), (_tone_residue(),))
        payloads = _collected(events, RF_STATE)
        _interlock_asserts(RULE_TONE, payloads)
        # The expected_evidence 互证 is against REAL emission: both
        # symbols of the primitive's expected_observations set rode the
        # same run, and the journal never carries gen.* (构造事件是 TS
        # 构造域).
        event_types = {event["event_type"] for event in events}
        assert {SEC_STATE, RF_STATE} <= event_types
        assert "fault.injected" in event_types
        assert not any(event_type.startswith("gen.") for event_type in event_types)

    def test_eq_faces_hold_on_the_real_wrong_lock_face(self):
        """The 错锁 face (locked + severe, SPEC-620 §7 错锁组合事实): the
        eq pins are REAL producer facts — the 恒定配对 axes and the graded
        BER — and the CauseRef chain self-reports the feeder (the
        「CauseRef 指向 lnb」 face the finite predicate set cannot
        address).  The UB rule's unlocked discriminator does NOT hold
        here — the wrong-lock face stays single-attributable."""
        events = _run_state(_direct_chain_graph(), (_tone_residue(),))
        faulted = _faulted_rf_payload(_collected(events, RF_STATE), "tuner-0")
        assert faulted["lock_state"] == "locked"
        assert faulted["ber_state"] == "severe"
        assert faulted["locked_transponder_id"] != "low@11095000"
        assert [cause["node_id"] for cause in faulted["causes"]] == ["lnb-0"]
        for predicate in _eq_predicates(_rule(RULE_TONE)):
            key = predicate.field.partition(".")[2]
            assert faulted[key] == predicate.value
        assert _predicates_hold(_rule(RULE_TONE), faulted)
        assert not _predicates_hold(_rule(RULE_UB), faulted)

    def test_eq_faces_hold_on_the_real_unlocked_face_too(self):
        """The 失锁 face (unlocked + severe — the IF left no slot): the
        TON eq set holds here as well (SPEC-620 §7: 失锁或错锁).  The UB
        rule's eq set holds TOO — the honest overlap face: the conflict
        discrimination (whose reference the cause chain carries) is
        outside the frozen predicate set, asserted not hidden (ticket
        #168 REPORT deviation; inert today behind the anchor gate)."""
        events = _run_state(_direct_chain_graph(10_500_000), (_tone_residue(),))
        faulted = _faulted_rf_payload(_collected(events, RF_STATE), "tuner-0")
        assert faulted["lock_state"] == "unlocked"
        assert faulted["ber_state"] == "severe"
        assert faulted["locked_transponder_id"] is None
        assert [cause["node_id"] for cause in faulted["causes"]] == ["lnb-0"]
        assert _predicates_hold(_rule(RULE_TONE), faulted)
        assert _predicates_hold(_rule(RULE_UB), faulted)

    def test_cross_event_lnb_face_carries_the_tone_split(self):
        """The second 互证 symbol's REAL face: the faulted lnb snapshot
        (key-signature = the registry lnb shape) carries
        tone_actual ≠ tone_commanded — the 双字段分离缝 the rule's
        root-cause narrative names, consumed through the expected_evidence
        symbol set, not the match predicates."""
        events = _run_state(_direct_chain_graph(), (_tone_residue(),))
        lnb_payloads = _collected(events, SEC_STATE)
        assert lnb_payloads
        for payload in lnb_payloads:
            assert set(payload) == set(SEC_LNB_SNAPSHOT_KEYS)
        faulted_lnb = lnb_payloads[-1]
        assert faulted_lnb["tone_commanded"] == "none"
        assert faulted_lnb["tone_actual"] == "continuous"

    def test_baseline_face_stays_candidate_free(self):
        """The baseline evaluation (trigger 1) is the clean face: the eq
        pins (graded BER) fail it — 缺失 ≠ 候选."""
        events = _run_state(_direct_chain_graph(), (_tone_residue(),))
        payloads = _collected(events, RF_STATE)
        baseline = [
            payload for payload in payloads if payload["node_id"] == "tuner-0"
        ][0]
        assert baseline["ber_state"] == "normal"
        assert not _predicates_hold(_rule(RULE_TONE), baseline)

    def test_full_evaluator_stays_candidate_free_on_real_snapshots(self):
        events = _run_state(_direct_chain_graph(), (_tone_residue(),))
        _evaluator_stays_candidate_free(_collected(events, RF_STATE))


class TestUbConflictCandidate:
    """「UB 槽位冲突 / SCR 堆叠互扰」: the real A1 chain run emits the
    conflict tuner snapshot and DIA-UB-CONFLICT-SUSPECT consumes exactly
    that shape."""

    def test_rule_interlocks_with_the_real_run_emission(self):
        events = _run_state(_scr_chain_graph(), (_ub_conflict(),))
        payloads = _collected(events, RF_STATE)
        _interlock_asserts(RULE_UB, payloads)
        event_types = {event["event_type"] for event in events}
        assert {SEC_STATE, RF_STATE} <= event_types
        assert not any(event_type.startswith("gen.") for event_type in event_types)

    def test_eq_faces_hold_on_the_real_conflict_face(self):
        """The conflict face: tuner-b unlocked + severe with the conflict
        peer in the cause chain (the 「CauseRef 冲突对」 face); tuner-a
        stays locked-normal — the eq pins fail it (single attributable
        symptom at the payload level)."""
        events = _run_state(_scr_chain_graph(), (_ub_conflict(),))
        payloads = _collected(events, RF_STATE)
        conflict = _faulted_rf_payload(payloads, "tuner-b")
        assert conflict["lock_state"] == "unlocked"
        assert conflict["ber_state"] == "severe"
        assert [cause["node_id"] for cause in conflict["causes"]] == ["tuner-a"]
        for predicate in _eq_predicates(_rule(RULE_UB)):
            key = predicate.field.partition(".")[2]
            assert conflict[key] == predicate.value
        assert _predicates_hold(_rule(RULE_UB), conflict)
        healthy = _faulted_rf_payload(payloads, "tuner-a")
        assert healthy["lock_state"] == "locked"
        assert not _predicates_hold(_rule(RULE_UB), healthy)

    def test_cross_event_lnb_face_carries_the_ub_table(self):
        """The second 互证 symbol's REAL face: the lnb snapshot (key
        signature = the registry lnb shape) carries the ``ub_assignments``
        table — the SCR face the rule's root-cause narrative names
        (「共享介质上冲突是成对事实」), consumed through the
        expected_evidence symbol set, not the match predicates."""
        events = _run_state(_scr_chain_graph(), (_ub_conflict(),))
        lnb_payloads = _collected(events, SEC_STATE)
        assert lnb_payloads
        faulted_lnb = lnb_payloads[-1]
        assert set(faulted_lnb) == set(SEC_LNB_SNAPSHOT_KEYS)
        table = faulted_lnb["ub_assignments"]
        assert {entry["tuner_node"] for entry in table} == {"tuner-a", "tuner-b"}

    def test_full_evaluator_stays_candidate_free_on_real_snapshots(self):
        events = _run_state(_scr_chain_graph(), (_ub_conflict(),))
        _evaluator_stays_candidate_free(_collected(events, RF_STATE))
