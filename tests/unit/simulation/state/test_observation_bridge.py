"""Observation bridge pure faces (ticket #164, SPEC-303 §Phase3).

Unit half — the pure projection/archiving functions and the SIM_STATE Run
journal-composition contract. The full delivery path (real emitter →
parse_envelope → sink) and the gateway/journal read path live in the
integration half (``tests/integration/simulation/
test_observation_bridge_delivery.py``, the test_gen_events two-half
precedent).

Payload shape contract (ticket #164 REPORT, frozen): the NodeEvalResult
JSON-safe projection — #161 metric key sets verbatim + ``health`` (str) +
``causes`` (``[{node_id, port_id?}]``) + ``node_id`` + the constant
observation-axes pairing (``state_evaluator``/``simulated``).  Archiving
follows the node's PRIMARY plane: ``tuner`` → ``rf.state_observed``;
``lnb``/``diseqc_switch`` → ``sec.state_observed``.  ``tuning_message``
is not part of the face (ruling A16).
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

from domain.observation.registry import (
    FAULT_EVENT_TYPES,
    GEN_EVENT_TYPES,
    TOPOLOGY_EVENT_TYPES,
    TS_EVENT_TYPES,
    validate_payload,
)
from simulation.state.evaluate import Health, NodeEvalResult, TopologyEvalResult
from simulation.state.observation_bridge import (
    RF_STATE_OBSERVED,
    SEC_STATE_OBSERVED,
    SIM_STATE_JOURNAL_EVENT_TYPES,
    TOPOLOGY_STATE_CHANGED_CHANGED_NODES_KEY,
    TOPOLOGY_STATE_CHANGED_DEGRADED_NODE_COUNT_KEY,
    is_sim_state_journal_event_type,
    state_event_type_for,
    state_snapshot_payload,
    topology_state_changed_payload,
)

TUNER_NODE_TYPE = "tuner"
LNB_NODE_TYPE = "lnb"
SWITCH_NODE_TYPE = "diseqc_switch"


def _tuner_result(**overrides: object) -> NodeEvalResult:
    fields = {
        "node_id": "tuner-a",
        "health": Health.OK,
        "metrics": {
            "lock_state": "locked",
            "if_frequency_khz": 1_230_000,
            "ber_state": "normal",
            "locked_transponder_id": "tp-1",
            "stale": False,
        },
        "causes": (),
    }
    fields.update(overrides)
    return NodeEvalResult(**fields)


def _lnb_result(**overrides: object) -> NodeEvalResult:
    fields = {
        "node_id": "lnb-0",
        "health": Health.OK,
        "metrics": {
            "voltage": "13V",
            "tone_commanded": "none",
            "tone_actual": "none",
            "tone_composite": "none",
            "band_selected": "low",
            "lo_frequency_khz": 9_750_000,
            "polarization_delivered": "vertical",
            "short_circuit_state": "normal",
            "ub_assignments": [],
        },
        "causes": (),
    }
    fields.update(overrides)
    return NodeEvalResult(**fields)


def _switch_result(**overrides: object) -> NodeEvalResult:
    fields = {
        "node_id": "sw-0",
        "health": Health.OK,
        "metrics": {
            "committed_switch_state": 3,
            "uncommitted_switch_state": 0,
            "port_selected": 3,
            "power_pass": "on",
        },
        "causes": (),
    }
    fields.update(overrides)
    return NodeEvalResult(**fields)


class TestPrimaryPlaneArchiving:
    """node_type → state_observed namespace (按节点主平面归档)."""

    def test_tuner_archives_to_rf(self) -> None:
        assert state_event_type_for(TUNER_NODE_TYPE) == RF_STATE_OBSERVED
        assert RF_STATE_OBSERVED == "rf.state_observed"

    def test_lnb_and_switch_archive_to_sec(self) -> None:
        assert state_event_type_for(LNB_NODE_TYPE) == SEC_STATE_OBSERVED
        assert state_event_type_for(SWITCH_NODE_TYPE) == SEC_STATE_OBSERVED
        assert SEC_STATE_OBSERVED == "sec.state_observed"

    def test_non_state_node_types_have_no_snapshot_face(self) -> None:
        # MVP construction nodes (and unknown types) are not RF/SEC state
        # nodes — the bridge never fabricates a snapshot for them.
        for node_type in ("mux", "tsdump", "t2mi_encapsulator", "biss_scrambler", "gremlin"):
            assert state_event_type_for(node_type) is None


class TestSnapshotPayloadProjection:
    """The NodeEvalResult JSON-safe projection (REPORT-frozen shape)."""

    def test_tuner_projection_is_the_exact_registered_shape(self) -> None:
        payload = state_snapshot_payload(TUNER_NODE_TYPE, _tuner_result())
        assert set(payload) == {
            "node_id",
            "health",
            "causes",
            "source",
            "confidence",
            "lock_state",
            "if_frequency_khz",
            "ber_state",
            "locked_transponder_id",
            "stale",
        }
        assert payload["node_id"] == "tuner-a"
        assert payload["health"] == "ok"  # .value — never the enum object
        assert payload["source"] == "state_evaluator"
        assert payload["confidence"] == "simulated"
        assert payload["stale"] is False
        validate_payload(RF_STATE_OBSERVED, payload)  # must not raise

    def test_lnb_projection_is_the_exact_registered_shape(self) -> None:
        payload = state_snapshot_payload(LNB_NODE_TYPE, _lnb_result())
        assert "sat_selected" not in payload  # universal 无此键
        assert payload["ub_assignments"] == []
        validate_payload(SEC_STATE_OBSERVED, payload)  # must not raise

    def test_legacy_cascade_projection_adds_sat_selected(self) -> None:
        metrics = {
            **_lnb_result().metrics,
            "sat_selected": "B",
        }
        payload = state_snapshot_payload(
            LNB_NODE_TYPE, _lnb_result(metrics=metrics)
        )
        assert payload["sat_selected"] == "B"
        validate_payload(SEC_STATE_OBSERVED, payload)  # must not raise

    def test_switch_projection_is_the_exact_registered_shape(self) -> None:
        payload = state_snapshot_payload(SWITCH_NODE_TYPE, _switch_result())
        assert set(payload) == {
            "node_id",
            "health",
            "causes",
            "source",
            "confidence",
            "committed_switch_state",
            "uncommitted_switch_state",
            "port_selected",
            "power_pass",
        }
        validate_payload(SEC_STATE_OBSERVED, payload)  # must not raise

    def test_cause_refs_project_to_json_safe_objects(self) -> None:
        from simulation.state.evaluate import CauseRef

        result = _tuner_result(
            health=Health.ERROR,
            metrics={
                "lock_state": "unlocked",
                "if_frequency_khz": None,
                "ber_state": None,
                "locked_transponder_id": None,
                "stale": True,
            },
            causes=(
                CauseRef(node_id="lnb-0", port_id="coax_out"),
                CauseRef(node_id="tuner-b", port_id=None),
            ),
        )
        payload = state_snapshot_payload(TUNER_NODE_TYPE, result)
        assert payload["causes"] == [
            {"node_id": "lnb-0", "port_id": "coax_out"},
            {"node_id": "tuner-b", "port_id": None},
        ]
        # UB-conflict honesty: the combination fact rides the snapshot
        # (unlocked + CauseRef), never a separate event type.
        validate_payload(RF_STATE_OBSERVED, payload)  # must not raise

    def test_health_enum_never_leaks_as_an_enum_object(self) -> None:
        from json import dumps

        payload = state_snapshot_payload(LNB_NODE_TYPE, _lnb_result(health=Health.WARN))
        assert payload["health"] == "warn"
        assert isinstance(dumps(payload), str)  # fully JSON-safe projection

    def test_unmapped_node_type_is_a_programmer_error(self) -> None:
        with pytest.raises(ValueError):
            state_snapshot_payload(
                "mux", NodeEvalResult(node_id="m-0", health=Health.IDLE)
            )


def _eval_result(
    node_results: tuple, topology_id: str = "topo-1", revision: int = 1
) -> TopologyEvalResult:
    return TopologyEvalResult(
        topology_id=topology_id,
        revision=revision,
        order=tuple(r.node_id for r in node_results),
        node_results=node_results,
    )


class TestTopologyChangedPayload:
    """The publish half of the ``topology.state_changed`` obligation."""

    def test_diff_payload_is_changed_nodes_plus_degraded_count(self) -> None:
        previous = _eval_result((_lnb_result(), _tuner_result()))
        faulted = _eval_result(
            (
                _lnb_result(health=Health.WARN),
                _tuner_result(
                    health=Health.ERROR,
                    metrics={
                        "lock_state": "unlocked",
                        "if_frequency_khz": None,
                        "ber_state": None,
                        "locked_transponder_id": None,
                        "stale": True,
                    },
                ),
            )
        )
        payload = topology_state_changed_payload(previous, faulted)
        assert payload == {
            TOPOLOGY_STATE_CHANGED_CHANGED_NODES_KEY: ["lnb-0", "tuner-a"],
            TOPOLOGY_STATE_CHANGED_DEGRADED_NODE_COUNT_KEY: 2,
        }

    def test_no_diff_yields_no_payload(self) -> None:
        result = _eval_result((_lnb_result(), _tuner_result()))
        assert topology_state_changed_payload(result, result) is None

    def test_degraded_count_is_error_and_warn_only(self) -> None:
        previous = _eval_result((_lnb_result(),))
        current = _eval_result(
            (_lnb_result(health=Health.WARN), _switch_result(health=Health.IDLE))
        )
        payload = topology_state_changed_payload(previous, current)
        assert payload is not None
        assert payload[TOPOLOGY_STATE_CHANGED_DEGRADED_NODE_COUNT_KEY] == 1
        # The pure diff includes node-set changes (sw-0 is new).
        assert payload[TOPOLOGY_STATE_CHANGED_CHANGED_NODES_KEY] == [
            "lnb-0",
            "sw-0",
        ]


class TestSimStateJournalComposition:
    """SIM_STATE Run journal 构成 (SPEC-303 §Phase3, the #165 contract)."""

    def test_composition_is_rf_sec_plus_topology_plus_fault(self) -> None:
        assert SIM_STATE_JOURNAL_EVENT_TYPES == (
            frozenset({RF_STATE_OBSERVED, SEC_STATE_OBSERVED})
            | TOPOLOGY_EVENT_TYPES
            | FAULT_EVENT_TYPES
        )

    def test_gen_family_is_never_part_of_the_composition(self) -> None:
        # 无 gen.* — 构造流水线事件是 TS 构造域；状态域 Generate 产物即
        # state_observed 流，不冒充构造事件。
        assert not SIM_STATE_JOURNAL_EVENT_TYPES & GEN_EVENT_TYPES
        for event_type in GEN_EVENT_TYPES:
            assert not is_sim_state_journal_event_type(event_type)

    def test_predicate_admits_the_composition_and_refuses_the_rest(self) -> None:
        for event_type in (
            RF_STATE_OBSERVED,
            SEC_STATE_OBSERVED,
            "topology.state_changed",
            "fault.injected",
            "fault.activated",
            "fault.applied",
            "fault.cleared",
        ):
            assert is_sim_state_journal_event_type(event_type)
        for event_type in TS_EVENT_TYPES | {"simulation.run_started"}:
            assert not is_sim_state_journal_event_type(event_type)
