"""#163 — the state-layer pre-evaluation pure transforms (SPEC-204 §Phase3).

Seam: :mod:`simulation.state.fault_transforms` — the module-level
:data:`STATE_TRANSFORM_BY_FAULT_TYPE` registry (ruling A18: state-layer
transforms are pre-evaluation config rewrites, NOT package-level
``faults.factory`` packet filters) plus :func:`state_layer_prepare_checks`
(the SPEC-204 §Phase3 prepare extension: target node exists + layer
routing reachable, ruling A5 — independent of the rf.*/sec. event
registry).

Postures covered:

1. transform unit face — pure rewrite of ``node_configs_by_id`` (the
   input mapping and its config dicts are never mutated), target/attr
   contract enforcement;
2. symptom propagation — the rewritten configs flow through the real
   walk (``DEFAULT_EVALUATORS``) into the SPEC-620/621 symptom chains:
   A2 (tone residue → band wrong → IF offset → wrong-lock/unlocked +
   severe) and A1 (UB stacking → unlocked + CauseRef conflict pair);
3. the layering discipline (SPEC-003 §Phase3 / SPEC-623 §7): the baseline
   topology with the state fault plan merely *present* validates clean
   and evaluates clean — the misassignment is effective only after the
   transform is applied (fault plan ≠ topology mutation).
"""

from __future__ import annotations

import pytest

from faults.definition import FaultActivation, FaultDefinition
from faults.registry import (
    FAULT_TYPE_TONE_RESIDUE,
    FAULT_TYPE_UB_SLOT_CONFLICT,
    LAYER_BY_FAULT_TYPE,
)

from simulation.state.evaluate import EvalContext, Health, evaluate_topology
from simulation.state.evaluators import DEFAULT_EVALUATORS
from simulation.state.fault_transforms import (
    STATE_FAULT_LAYERS,
    STATE_TRANSFORM_BY_FAULT_TYPE,
    state_layer_prepare_checks,
)
from simulation.state.graph import Connection, NodeConfig, PortSpec, TopologyGraph
from simulation.state.validate import validate_topology

pytestmark = pytest.mark.unit

OBS_RF_STATE = "rf.state_observed"
OBS_SEC_STATE = "sec.state_observed"


# --- fault definitions (the plan face) ------------------------------------------


def tone_residue_fault(
    *, target_id: str = "lnb-0", tone_actual: str = "continuous"
) -> FaultDefinition:
    return FaultDefinition(
        fault_id="fault-tone-residue",
        fault_type=FAULT_TYPE_TONE_RESIDUE,
        target_id=target_id,
        parameters={"tone_actual": tone_actual},
        activation=FaultActivation(kind="session_start", packet_index=None),
        expected_observations=(OBS_SEC_STATE, OBS_RF_STATE),
        layer="RF",
    )


def ub_slot_conflict_fault(
    *, target_id: str = "tuner-b:ub_slot", conflicting_ub_slot: int = 0
) -> FaultDefinition:
    return FaultDefinition(
        fault_id="fault-ub-conflict",
        fault_type=FAULT_TYPE_UB_SLOT_CONFLICT,
        target_id=target_id,
        parameters={"conflicting_ub_slot": conflicting_ub_slot},
        activation=FaultActivation(kind="session_start", packet_index=None),
        expected_observations=(OBS_SEC_STATE, OBS_RF_STATE),
        layer="SEC",
    )


# --- topology construction (SC-11 / SC-10 shapes, brief §E.11) ------------------


def _sec_port(port_id: str, direction: str, max_connections: int) -> PortSpec:
    return PortSpec(
        port_id=port_id,
        direction=direction,
        plane="SEC_CONTROL",
        max_connections=max_connections,
    )


def _lnb_config(**overrides: object) -> dict:
    config = {
        "lnb_kind": "universal",
        "lo_frequencies": {"low_khz": 9_750_000, "high_khz": 10_600_000},
        "voltage": "13V",
        "tone_commanded": "none",
        "tone_actual": "none",
        "tone_composite": "none",
        "short_circuit_state": "normal",
    }
    config.update(overrides)
    return config


def _scr_lnb_config(**overrides: object) -> dict:
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
    config = {
        "lnb_kind": "universal",
        "lo_frequencies": {"low_khz": 9_750_000, "high_khz": 10_600_000},
        "voltage": "13V",
        "tone_commanded": "none",
        "tone_actual": "none",
        "tone_composite": "none",
        "short_circuit_state": "normal",
        "scr": {"protocol": "EN50494", "ub_assignments": table},
    }
    config.update(overrides)
    return config


def _tuner_config(
    frequency_khz: int,
    polarization: str,
    ub_slot: int | None = None,
) -> dict:
    return {
        "tuning_request": {
            "frequency_khz": frequency_khz,
            "polarization": polarization,
        },
        "ub_slot": ub_slot,
    }


def _direct_graph(lnb_config: dict, tuner_config: dict) -> TopologyGraph:
    """SC-11 shape: lnb-0 coax_out → tuner-low rf_in."""
    return TopologyGraph(
        topology_id="topo-sc11",
        revision=1,
        nodes=[
            NodeConfig(
                node_id="lnb-0",
                node_type="lnb",
                config=lnb_config,
                ports=[_sec_port("coax_out", "output", 2)],
            ),
            NodeConfig(
                node_id="tuner-low",
                node_type="tuner",
                config=tuner_config,
                ports=[_sec_port("rf_in", "input", 1)],
            ),
        ],
        connections=[
            Connection(
                connection_id="c1",
                from_node="lnb-0",
                from_port="coax_out",
                to_node="tuner-low",
                to_port="rf_in",
                plane="SEC_CONTROL",
            )
        ],
    )


def _scr_fanout_graph(
    tuner_a_slot: int = 0,
    tuner_b_slot: int = 1,
) -> TopologyGraph:
    """SC-10 shape: one SCR lnb fans out to two tuners (shared coax)."""
    return TopologyGraph(
        topology_id="topo-sc10",
        revision=1,
        nodes=[
            NodeConfig(
                node_id="lnb-0",
                node_type="lnb",
                config=_scr_lnb_config(),
                ports=[_sec_port("coax_out", "output", 2)],
            ),
            NodeConfig(
                node_id="tuner-a",
                node_type="tuner",
                config=_tuner_config(11_095_000, "vertical", tuner_a_slot),
                ports=[_sec_port("rf_in", "input", 1)],
            ),
            NodeConfig(
                node_id="tuner-b",
                node_type="tuner",
                config=_tuner_config(12_070_000, "horizontal", tuner_b_slot),
                ports=[_sec_port("rf_in", "input", 1)],
            ),
        ],
        connections=[
            Connection(
                connection_id="c1",
                from_node="lnb-0",
                from_port="coax_out",
                to_node="tuner-a",
                to_port="rf_in",
                plane="SEC_CONTROL",
            ),
            Connection(
                connection_id="c2",
                from_node="lnb-0",
                from_port="coax_out",
                to_node="tuner-b",
                to_port="rf_in",
                plane="SEC_CONTROL",
            ),
        ],
    )


def _apply_transform(fault: FaultDefinition, graph: TopologyGraph) -> dict:
    configs = {node.node_id: node.config for node in graph.nodes}
    transform = STATE_TRANSFORM_BY_FAULT_TYPE[fault.fault_type]
    return dict(transform(fault, configs))


def _rebuild_with_configs(
    graph: TopologyGraph, configs: dict
) -> TopologyGraph:
    return TopologyGraph(
        topology_id=graph.topology_id,
        revision=graph.revision,
        nodes=[
            NodeConfig(
                node_id=node.node_id,
                node_type=node.node_type,
                config=configs[node.node_id],
                ports=list(node.ports),
            )
            for node in graph.nodes
        ],
        connections=list(graph.connections),
    )


def _run(graph: TopologyGraph):
    return evaluate_topology(
        graph, evaluators=DEFAULT_EVALUATORS, context=EvalContext(topology_revision=1)
    )


# --- transform unit face ---------------------------------------------------------


class TestToneResidueTransform:
    def test_rewrites_tone_actual_and_keeps_tone_commanded(self) -> None:
        fault = tone_residue_fault(tone_actual="continuous")
        configs = {
            "lnb-0": _lnb_config(),
            "tuner-low": _tuner_config(11_095_000, "vertical"),
        }
        rewritten = dict(STATE_TRANSFORM_BY_FAULT_TYPE[FAULT_TYPE_TONE_RESIDUE](fault, configs))
        assert rewritten["lnb-0"]["tone_actual"] == "continuous"
        # tone_commanded stays — the mismatch IS the injected seam.
        assert rewritten["lnb-0"]["tone_commanded"] == "none"
        assert rewritten["tuner-low"] == _tuner_config(11_095_000, "vertical")

    def test_input_mapping_is_never_mutated(self) -> None:
        fault = tone_residue_fault()
        lnb_config = _lnb_config()
        configs = {"lnb-0": lnb_config}
        rewritten = dict(
            STATE_TRANSFORM_BY_FAULT_TYPE[FAULT_TYPE_TONE_RESIDUE](fault, configs)
        )
        assert lnb_config["tone_actual"] == "none"
        assert configs["lnb-0"]["tone_actual"] == "none"
        assert rewritten is not configs
        assert rewritten["lnb-0"] is not lnb_config

    def test_missing_target_node_raises_target_invalid(self) -> None:
        fault = tone_residue_fault(target_id="lnb-9")
        with pytest.raises(ValueError, match="SIM_FAULT_TARGET_INVALID"):
            STATE_TRANSFORM_BY_FAULT_TYPE[FAULT_TYPE_TONE_RESIDUE](
                fault, {"lnb-0": _lnb_config()}
            )

    def test_unparseable_target_raises_target_invalid(self) -> None:
        fault = tone_residue_fault(target_id="")
        with pytest.raises(ValueError, match="SIM_FAULT_TARGET_INVALID"):
            STATE_TRANSFORM_BY_FAULT_TYPE[FAULT_TYPE_TONE_RESIDUE](
                fault, {"lnb-0": _lnb_config()}
            )

    def test_foreign_tone_param_raises_param_invalid(self) -> None:
        fault = tone_residue_fault(tone_actual="22khz")
        with pytest.raises(ValueError, match="SIM_FAULT_PARAM_INVALID"):
            STATE_TRANSFORM_BY_FAULT_TYPE[FAULT_TYPE_TONE_RESIDUE](
                fault, {"lnb-0": _lnb_config()}
            )


class TestToneResidueSymptomChain:
    """A2: residue → band wrong → IF offset → wrong-lock + severe."""

    def test_residue_yields_wrong_lock_severe_and_cause_to_lnb(self) -> None:
        graph = _direct_graph(
            _lnb_config(), _tuner_config(11_095_000, "vertical")
        )
        rewritten = _apply_transform(tone_residue_fault(), graph)
        result = _run(_rebuild_with_configs(graph, rewritten))
        lnb = result.result_for("lnb-0")
        tuner = result.result_for("tuner-low")
        # band wrong: commanded none → low; residue continuous → high.
        assert lnb.metrics["band_selected"] == "high"
        assert lnb.metrics["lo_frequency_khz"] == 10_600_000
        # IF offset 850 MHz ≫ capture range: the tuner 错锁s the
        # high-band neighbour sharing the IF slot.
        assert tuner.metrics["lock_state"] == "locked"
        assert tuner.metrics["locked_transponder_id"] == "high@11945000"
        assert tuner.metrics["ber_state"] == "severe"
        assert tuner.health is Health.ERROR
        assert any(cause.node_id == "lnb-0" for cause in tuner.causes)
        assert result.graph_health is Health.ERROR

    def test_residue_unlocks_a_low_band_bottom_request(self) -> None:
        # The 失锁 variant: a low-band-bottom request (10700000 kHz →
        # tuned IF 950000 kHz) locks its target without the fault; the
        # residue stops the LO on the high arm whose IF floor
        # (1100000 kHz, the §3 overlap arithmetic) excludes the slot →
        # unlocked + severe.
        baseline = _run(
            _direct_graph(
                _lnb_config(), _tuner_config(10_700_000, "vertical")
            )
        )
        assert (
            baseline.result_for("tuner-low").metrics["locked_transponder_id"]
            == "low@10700000"
        )
        graph = _direct_graph(
            _lnb_config(), _tuner_config(10_700_000, "vertical")
        )
        rewritten = _apply_transform(tone_residue_fault(), graph)
        result = _run(_rebuild_with_configs(graph, rewritten))
        tuner = result.result_for("tuner-low")
        assert tuner.metrics["lock_state"] == "unlocked"
        assert tuner.metrics["ber_state"] == "severe"
        assert any(cause.node_id == "lnb-0" for cause in tuner.causes)
        assert result.graph_health is Health.ERROR


class TestUbSlotConflictTransform:
    def test_attr_form_target_rewrites_ub_slot(self) -> None:
        # The SC-10 wire face (ruling A4): target_id "tuner-b:ub_slot".
        fault = ub_slot_conflict_fault(conflicting_ub_slot=0)
        configs = {"tuner-b": _tuner_config(12_070_000, "horizontal", 1)}
        rewritten = dict(
            STATE_TRANSFORM_BY_FAULT_TYPE[FAULT_TYPE_UB_SLOT_CONFLICT](fault, configs)
        )
        assert rewritten["tuner-b"]["ub_slot"] == 0
        assert rewritten["tuner-b"]["tuning_request"] == {
            "frequency_khz": 12_070_000,
            "polarization": "horizontal",
        }

    def test_bare_node_target_rewrites_ub_slot(self) -> None:
        fault = ub_slot_conflict_fault(target_id="tuner-b")
        configs = {"tuner-b": _tuner_config(12_070_000, "horizontal", 1)}
        rewritten = dict(
            STATE_TRANSFORM_BY_FAULT_TYPE[FAULT_TYPE_UB_SLOT_CONFLICT](fault, configs)
        )
        assert rewritten["tuner-b"]["ub_slot"] == 0

    def test_input_mapping_is_never_mutated(self) -> None:
        fault = ub_slot_conflict_fault()
        tuner_config = _tuner_config(12_070_000, "horizontal", 1)
        configs = {"tuner-b": tuner_config}
        rewritten = dict(
            STATE_TRANSFORM_BY_FAULT_TYPE[FAULT_TYPE_UB_SLOT_CONFLICT](fault, configs)
        )
        assert tuner_config["ub_slot"] == 1
        assert rewritten["tuner-b"] is not tuner_config

    def test_foreign_attr_segment_raises_target_invalid(self) -> None:
        fault = ub_slot_conflict_fault(target_id="tuner-b:voltage")
        with pytest.raises(ValueError, match="SIM_FAULT_TARGET_INVALID"):
            STATE_TRANSFORM_BY_FAULT_TYPE[FAULT_TYPE_UB_SLOT_CONFLICT](
                fault, {"tuner-b": _tuner_config(12_070_000, "horizontal", 1)}
            )

    def test_missing_tuner_node_raises_target_invalid(self) -> None:
        fault = ub_slot_conflict_fault(target_id="tuner-z:ub_slot")
        with pytest.raises(ValueError, match="SIM_FAULT_TARGET_INVALID"):
            STATE_TRANSFORM_BY_FAULT_TYPE[FAULT_TYPE_UB_SLOT_CONFLICT](
                fault, {"tuner-b": _tuner_config(12_070_000, "horizontal", 1)}
            )


class TestUbSlotConflictSymptomChain:
    """A1: stacking interference → unlocked + CauseRef conflict pair."""

    def test_conflict_unlocks_one_tuner_with_cause_to_peer(self) -> None:
        graph = _scr_fanout_graph()
        rewritten = _apply_transform(ub_slot_conflict_fault(), graph)
        result = _run(_rebuild_with_configs(graph, rewritten))
        tuner_a = result.result_for("tuner-a")
        tuner_b = result.result_for("tuner-b")
        # tuner-a keeps its carrier; tuner-b misclaims slot 0.
        assert tuner_a.metrics["lock_state"] == "locked"
        assert tuner_a.metrics["locked_transponder_id"] == "ub:0:1210"
        assert tuner_b.metrics["lock_state"] == "unlocked"
        assert tuner_b.metrics["ber_state"] == "severe"
        assert any(cause.node_id == "tuner-a" for cause in tuner_b.causes)
        assert result.graph_health is Health.ERROR


class TestLayeringDiscipline:
    """SPEC-003 §Phase3 / SPEC-623 §7: 基线永远合法, 错配仅 fault plan 期生效.

    The fault plan is never a topology mutation: a baseline topology with
    the state fault plan merely attached validates clean (SIM_TOPO_UB_*
    all green) AND evaluates clean — the conflict exists only after the
    transform rewrites the config (runtime judgement via ``ub_conflicts``,
    ruling A13).
    """

    def test_baseline_topology_with_state_fault_plan_stays_valid(self) -> None:
        graph = _scr_fanout_graph(tuner_b_slot=1)
        # The plan exists but is NOT applied — validate_topology never
        # sees it (plans and topologies are separate prepare artifacts).
        assert validate_topology(graph) == ()

    def test_untransformed_evaluation_has_no_conflict(self) -> None:
        graph = _scr_fanout_graph(tuner_b_slot=1)
        result = _run(graph)
        assert result.result_for("tuner-a").metrics["locked_transponder_id"] == "ub:0:1210"
        assert result.result_for("tuner-b").metrics["locked_transponder_id"] == "ub:1:1420"
        assert result.graph_health is Health.OK

    def test_misassignment_takes_effect_only_after_the_transform(self) -> None:
        graph = _scr_fanout_graph(tuner_b_slot=1)
        rewritten = _apply_transform(ub_slot_conflict_fault(), graph)
        faulted = _run(_rebuild_with_configs(graph, rewritten))
        assert faulted.result_for("tuner-b").metrics["lock_state"] == "unlocked"
        assert faulted.graph_health is Health.ERROR


class TestStateLayerPrepareChecks:
    """SPEC-204 §Phase3 prepare extension: target node exists + layer
    routing reachable (ruling A5: no rf.*/sec.* registry dependency)."""

    def test_empty_plan_yields_no_details(self) -> None:
        graph = _scr_fanout_graph()
        assert state_layer_prepare_checks((), graph) == ()

    def test_valid_state_faults_yield_no_details(self) -> None:
        graph = _scr_fanout_graph()
        faults = (
            ub_slot_conflict_fault(),
            ub_slot_conflict_fault(target_id="tuner-a"),
            tone_residue_fault(),
        )
        assert state_layer_prepare_checks(faults, graph) == ()

    def test_package_layer_fault_is_out_of_scope(self) -> None:
        graph = _scr_fanout_graph()
        fault = FaultDefinition(
            fault_id="f-ts",
            fault_type="PAT_MISSING",
            target_id="demux-0:pid:0x0000",
            expected_observations=("ts.psi_section_observed",),
        )
        assert state_layer_prepare_checks((fault,), graph) == ()

    def test_missing_target_node_rejected(self) -> None:
        graph = _scr_fanout_graph()
        details = state_layer_prepare_checks(
            (ub_slot_conflict_fault(target_id="tuner-z:ub_slot"),), graph
        )
        codes = [detail.split(":", 1)[0] for detail in details]
        assert codes == ["SIM_FAULT_TARGET_INVALID"]

    def test_unregistered_state_layer_fault_type_rejected(self) -> None:
        # A prematurely used candidate-pool primitive (SPEC-204 §Phase3
        # 诚实标注: LNB_SHORT_CIRCUIT etc. are not first-version entries):
        # its layer routes to the state domain but no transform exists.
        fault = FaultDefinition(
            fault_id="f-candidate",
            fault_type="THERMAL_FAULT",
            target_id="lnb-0",
            parameters={"short_circuit_state": "thermal_fault"},
            expected_observations=(OBS_SEC_STATE,),
            layer="RF",
        )
        details = state_layer_prepare_checks((fault,), _direct_graph(_lnb_config(), _tuner_config(11_095_000, "vertical")))
        codes = [detail.split(":", 1)[0] for detail in details]
        assert codes == ["SIM_FAULT_STATE_TRANSFORM_UNREGISTERED"]

    def test_node_kind_mismatch_rejected(self) -> None:
        graph = _scr_fanout_graph()
        details = state_layer_prepare_checks(
            (tone_residue_fault(target_id="tuner-a"),), graph
        )
        codes = [detail.split(":", 1)[0] for detail in details]
        assert codes == ["SIM_FAULT_TARGET_INVALID"]
        details = state_layer_prepare_checks(
            (ub_slot_conflict_fault(target_id="lnb-0"),), graph
        )
        codes = [detail.split(":", 1)[0] for detail in details]
        assert codes == ["SIM_FAULT_TARGET_INVALID"]

    def test_foreign_attr_segment_rejected(self) -> None:
        graph = _scr_fanout_graph()
        details = state_layer_prepare_checks(
            (ub_slot_conflict_fault(target_id="tuner-b:voltage"),), graph
        )
        codes = [detail.split(":", 1)[0] for detail in details]
        assert codes == ["SIM_FAULT_TARGET_INVALID"]

    def test_unparseable_target_rejected(self) -> None:
        graph = _scr_fanout_graph()
        details = state_layer_prepare_checks(
            (tone_residue_fault(target_id=""),), graph
        )
        codes = [detail.split(":", 1)[0] for detail in details]
        assert codes == ["SIM_FAULT_TARGET_INVALID"]


class TestStateTransformRegistryShape:
    def test_registry_covers_exactly_the_two_state_primitives(self) -> None:
        assert set(STATE_TRANSFORM_BY_FAULT_TYPE) == {
            FAULT_TYPE_TONE_RESIDUE,
            FAULT_TYPE_UB_SLOT_CONFLICT,
        }
        for fault_type in STATE_TRANSFORM_BY_FAULT_TYPE:
            assert LAYER_BY_FAULT_TYPE[fault_type] in STATE_FAULT_LAYERS

    def test_state_layers_are_the_phase3_expansion(self) -> None:
        assert STATE_FAULT_LAYERS == ("RF", "SEC")
