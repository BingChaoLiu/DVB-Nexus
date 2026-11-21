"""SPEC-620 §7 — tuner lock four-branch + ber rule-table vectors (#161).

Seam: ``simulation.state.evaluators.tuner_evaluator`` — the lock/ber pure
functions plus the :class:`TunerEvaluator` shell.

Vector-first discipline (SPEC-620 §11.2): every expected value below was
hand-derived from the SPEC-620 §7 normative rule table + the SPEC-621
appendix A band plan **before** the implementation was written.

The IF-slot model frozen by ticket #161 (REPORT-declared, all four §7
branches expressible):

- ``if_frequency_khz`` (the §5 metric) = |tuning_frequency − lo_delivered|
  — the spec formula verbatim, reported even when unlocked.
- The tuner's IF-section dial: ``tuned_if = tuning_frequency −
  lo_expected`` where ``lo_expected`` is the LO plan entry of the band the
  dial frequency belongs to (boundary 11700000 kHz, SPEC-621 appendix A).
- A transponder slot exists on the delivered LO arm iff ``tuned_if`` lies
  in that arm's IF range: low arm [950000, 1950000] kHz, high arm
  [1100000, 1950000] kHz — the high-arm floor 1100000 is the SPEC-620 §3
  term-table overlap arithmetic (high band RF 11700 − LO 10600 MHz), and
  the overlap region 1100–1950 MHz is exactly where wrong-lock lives.
- Lock at ``rf_locked = tuned_if + lo_delivered``: ``rf_locked`` equal to
  the dialed frequency = target lock; different = 错锁 (wrong-lock, the
  ±850 MHz neighbour transponder sharing the IF slot) — the composite
  fact SPEC-307 consumes (AC-620-03).
- ``locked_transponder_id`` format: ``f"{band}@{rf_locked_khz}"`` for the
  universal/legacy LO path, ``f"ub:{slot}:{center_mhz}"`` for the SCR path.

ber rule-table freezing (SPEC-620 §7, REPORT-declared):

- severe fires on any anomaly field (tone_actual ≠ tone_commanded /
  short_circuit_state ≠ normal / UB-conflict cause / anomalous feeder
  health) **regardless of slot position** — rule 2's "且 IF 仍落在某槽位"
  qualifier is frozen as non-required so the §11.1 A2 golden narrative
  ("unlocked 或错锁 + severe") holds on the unlocked branch too and the
  TONE_RESIDUE_SUSPECT diagnostic rule can fire on the 失锁 variant.
- elevated = in the target slot's protection band, frozen width 3000 kHz
  (3 MHz, aligned with the appendix A ±3 MHz LO-drift reference); the
  width is pinned by these vectors, never by a spec literal.
- unlocked without any anomaly → no grade (``ber_state = null``) — rule 4.
- ``stale: true`` marks every unlocked snapshot (SPEC-620 §8); locked
  snapshots carry ``stale: false``.  The "retain last decidable value"
  option of §8 is realised purity-safe: the severe grade derivable from
  the *current* inputs survives unlocking, everything else grades null.
"""

from __future__ import annotations

import pytest

from simulation.state.evaluate import (
    CauseRef,
    EvalContext,
    Health,
    PortState,
)
from simulation.state.graph import NodeConfig, PortSpec
from simulation.state.evaluators import TunerEvaluator
from simulation.state.evaluators.tuner_evaluator import (
    HIGH_ARM_IF_FLOOR_KHZ,
    IF_SLOT_HIGH_KHZ,
    IF_SLOT_LOW_KHZ,
    PROTECTION_BAND_WIDTH_KHZ,
    expected_band,
)

pytestmark = pytest.mark.unit

BOUNDARY_KHZ = 11_700_000


# -- frozen model constants (vectors pin them) ---------------------------------


class TestFrozenSlotModelConstants:
    """The appendix A band plan + §3 overlap arithmetic, pinned as vectors."""

    def test_if_window_is_the_appendix_a_plan(self) -> None:
        # 低 10.70–11.70 GHz → LO 9750 → IF 950–1950 MHz; 高 11.70–12.75
        # GHz → LO 10600 → IF 950–1950 MHz (appendix A, kHz).
        assert IF_SLOT_LOW_KHZ == 950_000
        assert IF_SLOT_HIGH_KHZ == 1_950_000

    def test_high_arm_floor_is_the_overlap_start(self) -> None:
        # SPEC-620 §3 term table: the low/high IF-overlap region is
        # 1100–1950 MHz — below 1100000 kHz only the low arm has
        # transponders (high band RF starts at 11700000).
        assert HIGH_ARM_IF_FLOOR_KHZ == 1_100_000

    def test_protection_band_width_pinned_by_vector(self) -> None:
        # SPEC-620 §7 rule 3 leaves the width to the implementation ticket;
        # frozen 3000 kHz (3 MHz, appendix A ±3 MHz LO-drift reference).
        assert PROTECTION_BAND_WIDTH_KHZ == 3_000

    def test_band_boundary_is_the_universal_plan(self) -> None:
        assert expected_band(11_699_999) == "low"
        assert expected_band(11_700_000) == "high"
        assert expected_band(BOUNDARY_KHZ) == "high"


# -- upstream fact fixtures (the merged A2 channel shape) -----------------------


def _upstream_metrics(**overrides: object) -> dict:
    """The lnb fact set a tuner sees through the walk's A2 channel."""
    metrics = {
        "voltage": "13V",
        "tone_commanded": "none",
        "tone_actual": "none",
        "tone_composite": "none",
        "band_selected": "low",
        "lo_frequency_khz": 9_750_000,
        "polarization_delivered": "vertical",
        "short_circuit_state": "normal",
        "ub_assignments": [],
        "lnb_kind": "universal",
        "lo_plan_low_khz": 9_750_000,
        "lo_plan_high_khz": 10_600_000,
        "scr_protocol": None,
    }
    metrics.update(overrides)
    return metrics


def _feeder(metrics: dict, health: Health = Health.OK) -> PortState:
    return PortState(port_id="rf_in", health=health, metrics=metrics)


def _tuner_node(config: dict, node_id: str = "tuner-a") -> NodeConfig:
    return NodeConfig(
        node_id=node_id,
        node_type="tuner",
        config=config,
        ports=[
            PortSpec(port_id="rf_in", direction="input", plane="SEC_CONTROL", max_connections=1),
        ],
    )


def _evaluate(evaluator: TunerEvaluator, config: dict, feeder, node_id: str = "tuner-a"):
    node = _tuner_node(config, node_id)
    inputs = {"rf_in": feeder} if feeder is not None else {}
    return evaluator.evaluate(node, inputs, EvalContext(topology_revision=1))


def _config(frequency_khz: int, polarization: str, **overrides: object) -> dict:
    config = {
        "tuning_request": {"frequency_khz": frequency_khz, "polarization": polarization},
        "ub_slot": None,
        "diseqc_commands": None,
    }
    config.update(overrides)
    return config


SCR_TABLE = [
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


def _scr_upstream(**overrides: object) -> dict:
    return _upstream_metrics(
        scr_protocol="EN50494",
        ub_assignments=[dict(entry) for entry in SCR_TABLE],
        **overrides,
    )


# -- branch 1: target lock -------------------------------------------------------


class TestBranch1TargetLock:
    """IF 落入目标转发器槽位且上游链路正常 → locked（locked_transponder_id = 目标）."""

    def test_high_band_target_lock(self) -> None:
        # F=12070000 (high band), lnb 18V/continuous delivers LO 10600000:
        # tuned_if = 1470000 in the high-arm slots; lo_expected == delivered.
        result = _evaluate(
            TunerEvaluator(),
            _config(12_070_000, "horizontal"),
            _feeder(_upstream_metrics(
                voltage="18V", tone_commanded="continuous",
                tone_actual="continuous", band_selected="high",
                lo_frequency_khz=10_600_000, polarization_delivered="horizontal",
            )),
        )
        assert result.metrics["lock_state"] == "locked"
        assert result.metrics["locked_transponder_id"] == "high@12070000"
        assert result.metrics["if_frequency_khz"] == 1_470_000
        assert result.metrics["ber_state"] == "normal"
        assert result.metrics["stale"] is False
        assert result.health is Health.OK

    def test_low_band_target_lock(self) -> None:
        # F=11095000 (low band), lnb 13V/none delivers LO 9750000:
        # tuned_if = 1345000 in the low-arm slots.
        result = _evaluate(
            TunerEvaluator(),
            _config(11_095_000, "vertical"),
            _feeder(_upstream_metrics()),
        )
        assert result.metrics["lock_state"] == "locked"
        assert result.metrics["locked_transponder_id"] == "low@11095000"
        assert result.metrics["if_frequency_khz"] == 1_345_000
        assert result.metrics["ber_state"] == "normal"
        assert result.health is Health.OK

    def test_legacy_single_lo_always_locks_target(self) -> None:
        # legacy_cascade: single LO — the delivered LO always equals the
        # expected one, so any in-window dial locks the target (band label
        # derived from the tuning frequency, SPEC-621 §7).
        result = _evaluate(
            TunerEvaluator(),
            _config(11_095_000, "vertical"),
            _feeder(_upstream_metrics(lnb_kind="legacy_cascade")),
        )
        assert result.metrics["lock_state"] == "locked"
        assert result.metrics["locked_transponder_id"] == "low@11095000"
        assert result.metrics["ber_state"] == "normal"


# -- branch 2: UB conflict -------------------------------------------------------


class TestBranch2UbConflict:
    """UB 冲突 → unlocked + CauseRef 冲突对（运行期判定只走 ub_conflicts，裁定 A13）."""

    def test_conflicting_claim_unlocks_with_cause(self) -> None:
        # The UB_SLOT_CONFLICT transform (SPEC-204) rewrote tuner-b's
        # ub_slot to 0 — already claimed by tuner-a in the SCR table.
        upstream = _scr_upstream()
        result = _evaluate(
            TunerEvaluator(),
            _config(11_095_000, "vertical", ub_slot=0),
            _feeder(upstream),
            node_id="tuner-b",
        )
        assert result.metrics["lock_state"] == "unlocked"
        assert result.metrics["locked_transponder_id"] is None
        assert result.metrics["ber_state"] == "severe"
        assert result.metrics["stale"] is True
        assert result.health is Health.ERROR
        assert CauseRef(node_id="tuner-a") in result.causes

    def test_conflict_free_entrant_locks_its_ub(self) -> None:
        # tuner-a holds UB0 legitimately: no conflict → locked at its UB
        # carrier; the SCR path skips the LO-arm/polarisation machinery
        # (the tuning message carries band/polarisation bits, SPEC-623 §6).
        result = _evaluate(
            TunerEvaluator(),
            _config(11_095_000, "vertical", ub_slot=0),
            _feeder(_scr_upstream()),
            node_id="tuner-a",
        )
        assert result.metrics["lock_state"] == "locked"
        assert result.metrics["locked_transponder_id"] == "ub:0:1210"
        assert result.metrics["if_frequency_khz"] == 1_210_000
        assert result.metrics["ber_state"] == "normal"
        assert result.metrics["stale"] is False
        assert result.health is Health.OK

    def test_second_ub_entrant_locks_its_carrier(self) -> None:
        result = _evaluate(
            TunerEvaluator(),
            _config(12_070_000, "horizontal", ub_slot=1),
            _feeder(_scr_upstream()),
            node_id="tuner-b",
        )
        assert result.metrics["lock_state"] == "locked"
        assert result.metrics["locked_transponder_id"] == "ub:1:1420"
        assert result.metrics["if_frequency_khz"] == 1_420_000

    def test_conflict_pair_dedup_keeps_own_conflicts_only(self) -> None:
        # Two peers on the same slot: the tuner reports exactly the pairs
        # it participates in, in deterministic pair order.
        table = [
            dict(SCR_TABLE[0]),  # tuner-a -> slot 0
            {
                "tuner_node": "tuner-c",
                "ub_slot": 0,
                "ub_center_freq_mhz": 1210,
                "position": "A",
                "pin": None,
                "ub_bandwidth_mhz": 46,
            },
            dict(SCR_TABLE[1]),  # tuner-b -> slot 1
        ]
        result = _evaluate(
            TunerEvaluator(),
            _config(11_095_000, "vertical", ub_slot=0),
            _feeder(_upstream_metrics(
                scr_protocol="EN50494", ub_assignments=table
            )),
            node_id="tuner-b",
        )
        peers = [cause.node_id for cause in result.causes]
        assert peers == ["tuner-a", "tuner-c"]

    def test_unmatched_slot_claim_unlocks(self) -> None:
        # ub_slot dialled to a slot no table entry covers: the UB claim is
        # unmatchable → unlocked, no causes (the validator owns the static
        # SIM_TOPO_UB_SLOT_UNMATCHED face).
        result = _evaluate(
            TunerEvaluator(),
            _config(11_095_000, "vertical", ub_slot=5),
            _feeder(_scr_upstream()),
            node_id="tuner-b",
        )
        assert result.metrics["lock_state"] == "unlocked"
        assert result.metrics["if_frequency_khz"] is None
        assert result.metrics["ber_state"] is None
        assert result.metrics["stale"] is True
        assert result.causes == ()

    def test_ub_slot_without_scr_context_takes_the_lo_path(self) -> None:
        # ub_slot set but no upstream SCR: no UB participation (dangling
        # claim is the validator's face) — the universal LO machinery
        # decides the lock.
        result = _evaluate(
            TunerEvaluator(),
            _config(11_095_000, "vertical", ub_slot=0),
            _feeder(_upstream_metrics()),
        )
        assert result.metrics["lock_state"] == "locked"
        assert result.metrics["locked_transponder_id"] == "low@11095000"


# -- branch 3: no slot → unlocked -------------------------------------------------


class TestBranch3NoSlotUnlocked:
    """IF 未落任何槽位 → unlocked（A2 症状链的失锁支路）."""

    def test_residue_pushes_low_band_dial_below_high_arm_floor(self) -> None:
        # F=10800000 (low band) with the residue's delivered high-arm LO:
        # tuned_if = 1050000 < the high-arm floor 1100000 — the delivered
        # high arm has no transponder there.
        result = _evaluate(
            TunerEvaluator(),
            _config(10_800_000, "vertical"),
            _feeder(_upstream_metrics(
                tone_actual="continuous",
                band_selected="high",
                lo_frequency_khz=10_600_000,
            )),
        )
        assert result.metrics["lock_state"] == "unlocked"
        assert result.metrics["locked_transponder_id"] is None
        assert result.metrics["if_frequency_khz"] == 200_000
        assert result.metrics["ber_state"] == "severe"
        assert result.metrics["stale"] is True
        assert result.health is Health.ERROR

    def test_dial_beyond_the_normative_if_window_unlocks(self) -> None:
        # F=12700000 near the Ku top: tuned_if = 12700000 - 10600000 =
        # 2100000 kHz — beyond the appendix A normative IF window
        # (950000..1950000, REPORT-frozen as spec-literal even though the
        # raw RF arithmetic reaches 2150000) → no slot, unlocked, and
        # without an anomaly field no grade.
        result = _evaluate(
            TunerEvaluator(),
            _config(12_700_000, "horizontal"),
            _feeder(_upstream_metrics(
                voltage="18V", tone_commanded="continuous",
                tone_actual="continuous", band_selected="high",
                lo_frequency_khz=10_600_000, polarization_delivered="horizontal",
            )),
        )
        assert result.metrics["lock_state"] == "unlocked"
        assert result.metrics["if_frequency_khz"] == 2_100_000
        assert result.metrics["ber_state"] is None
        assert result.metrics["stale"] is True
        assert result.health is Health.ERROR


# -- wrong-lock composite fact -----------------------------------------------------


class TestWrongLock:
    """错锁：IF 落入另一转发器槽位（低/高频段 IF 重叠区）→ locked 且
    locked_transponder_id ≠ 目标——组合事实，供 SPEC-307 规则消费（AC-620-03）."""

    def test_a2_residue_wrong_locks_the_850mhz_neighbour(self) -> None:
        # F=11095000 (low band, commanded none) with TONE_RESIDUE
        # (actual=continuous → LO stops at 10600000): tuned_if = 1345000
        # sits in the high-arm overlap slots → the tuner locks the
        # high-band transponder 850 MHz above the dial (appendix A
        # arithmetic) — locked, wrong identity, severe.
        result = _evaluate(
            TunerEvaluator(),
            _config(11_095_000, "vertical"),
            _feeder(_upstream_metrics(
                tone_actual="continuous",
                band_selected="high",
                lo_frequency_khz=10_600_000,
            )),
        )
        assert result.metrics["lock_state"] == "locked"
        assert result.metrics["locked_transponder_id"] == "high@11945000"
        assert result.metrics["locked_transponder_id"] != "low@11095000"
        assert result.metrics["if_frequency_khz"] == 495_000
        assert result.metrics["ber_state"] == "severe"
        assert result.metrics["stale"] is False
        assert result.health is Health.ERROR

    def test_reverse_residue_wrong_locks_the_850mhz_neighbour_below(self) -> None:
        # Reverse direction: high-band dial (commanded continuous) with
        # tone_actual none (low arm delivered): tuned_if = 1470000 sits in
        # the low-arm slots → locks the low-band transponder 850 MHz below.
        result = _evaluate(
            TunerEvaluator(),
            _config(12_070_000, "horizontal"),
            _feeder(_upstream_metrics(
                voltage="18V", tone_commanded="continuous", tone_actual="none",
                lo_frequency_khz=9_750_000, polarization_delivered="horizontal",
                band_selected="low",
            )),
        )
        assert result.metrics["lock_state"] == "locked"
        assert result.metrics["locked_transponder_id"] == "low@11220000"
        assert result.metrics["locked_transponder_id"] != "high@12070000"
        assert result.metrics["if_frequency_khz"] == 2_320_000
        assert result.metrics["ber_state"] == "severe"


# -- ber rule table ----------------------------------------------------------------


class TestBerRuleTable:
    """AC-620-02 — ber_state 三档逐条；无任何连续 BER 数值进产物."""

    def test_rule1_normal_requires_chain_normal_and_slot_interior(self) -> None:
        result = _evaluate(
            TunerEvaluator(),
            _config(12_070_000, "horizontal"),
            _feeder(_upstream_metrics(
                voltage="18V", tone_commanded="continuous",
                tone_actual="continuous", band_selected="high",
                lo_frequency_khz=10_600_000, polarization_delivered="horizontal",
            )),
        )
        assert result.metrics["ber_state"] == "normal"
        # No continuous BER number anywhere in the metrics (No fake
        # evidence): every metric value is a closed-vocabulary string,
        # int frequency, bool or null.
        assert all(
            value is None or isinstance(value, (bool, int, str))
            for value in result.metrics.values()
        )

    def test_rule2_severe_on_tone_anomaly(self) -> None:
        result = _evaluate(
            TunerEvaluator(),
            _config(11_095_000, "vertical"),
            _feeder(_upstream_metrics(tone_actual="continuous")),
        )
        assert result.metrics["ber_state"] == "severe"

    def test_rule2_severe_on_short_circuit_even_when_locked(self) -> None:
        # short_circuit_state ≠ normal is an anomaly field: the lock
        # arithmetic still proceeds (delivery is orthogonal, REPORT-frozen)
        # but the grade is severe.
        result = _evaluate(
            TunerEvaluator(),
            _config(11_095_000, "vertical"),
            _feeder(_upstream_metrics(short_circuit_state="clamping")),
        )
        assert result.metrics["lock_state"] == "locked"
        assert result.metrics["locked_transponder_id"] == "low@11095000"
        assert result.metrics["ber_state"] == "severe"
        assert result.health is Health.ERROR

    def test_rule2_severe_on_anomalous_feeder_health(self) -> None:
        # REPORT-frozen rule-2 extension: an anomalous feeder health
        # (error/warn) is an upstream anomaly field.
        result = _evaluate(
            TunerEvaluator(),
            _config(11_095_000, "vertical"),
            _feeder(_upstream_metrics(), health=Health.WARN),
        )
        assert result.metrics["lock_state"] == "locked"
        assert result.metrics["ber_state"] == "severe"

    def test_rule3_elevated_in_high_arm_protection_band(self) -> None:
        # F=12549000: tuned_if = 1949000, within 3000 kHz of the window top
        # (1950000 − 3000 = 1947000 < 1949000) → elevated, health warn.
        result = _evaluate(
            TunerEvaluator(),
            _config(12_549_000, "horizontal"),
            _feeder(_upstream_metrics(
                voltage="18V", tone_commanded="continuous",
                tone_actual="continuous", band_selected="high",
                lo_frequency_khz=10_600_000, polarization_delivered="horizontal",
            )),
        )
        assert result.metrics["lock_state"] == "locked"
        assert result.metrics["locked_transponder_id"] == "high@12549000"
        assert result.metrics["ber_state"] == "elevated"
        assert result.metrics["stale"] is False
        assert result.health is Health.WARN

    def test_rule3_elevated_in_low_arm_protection_band(self) -> None:
        # F=10701000: tuned_if = 951000, within 3000 kHz above the window
        # floor 950000 → elevated.
        result = _evaluate(
            TunerEvaluator(),
            _config(10_701_000, "vertical"),
            _feeder(_upstream_metrics()),
        )
        assert result.metrics["ber_state"] == "elevated"
        assert result.health is Health.WARN

    def test_interior_of_the_slot_is_normal_not_elevated(self) -> None:
        # 953000..1947000 interior: F=10704000 → tuned_if = 954000 just
        # past the protection band → normal again.
        result = _evaluate(
            TunerEvaluator(),
            _config(10_704_000, "vertical"),
            _feeder(_upstream_metrics()),
        )
        assert result.metrics["ber_state"] == "normal"
        assert result.health is Health.OK

    def test_rule4_unlocked_without_anomaly_produces_no_grade(self) -> None:
        # Polarisation mismatch unlocks without any rule-2 anomaly field:
        # no grade (null) + stale.
        result = _evaluate(
            TunerEvaluator(),
            _config(11_095_000, "vertical"),
            _feeder(_upstream_metrics(
                voltage="18V", polarization_delivered="horizontal",
                band_selected="low",
            )),
        )
        assert result.metrics["lock_state"] == "unlocked"
        assert result.metrics["ber_state"] is None
        assert result.metrics["stale"] is True
        assert result.health is Health.ERROR


# -- §8 error-handling rows ----------------------------------------------------------


class TestErrorHandlingRows:
    """SPEC-620 §8 rows as vectors."""

    def test_polarization_mismatch_unlocks(self) -> None:
        result = _evaluate(
            TunerEvaluator(),
            _config(11_095_000, "vertical"),
            _feeder(_upstream_metrics(
                voltage="18V", polarization_delivered="horizontal",
                band_selected="low",
            )),
        )
        assert result.metrics["lock_state"] == "unlocked"
        assert result.metrics["if_frequency_khz"] == 1_345_000
        assert result.metrics["locked_transponder_id"] is None
        assert result.metrics["stale"] is True

    def test_unpowered_lnb_unlocks_without_carrier(self) -> None:
        result = _evaluate(
            TunerEvaluator(),
            _config(11_095_000, "vertical"),
            _feeder(_upstream_metrics(
                voltage="off", band_selected="none",
                lo_frequency_khz=None, polarization_delivered="none",
            )),
        )
        assert result.metrics["lock_state"] == "unlocked"
        assert result.metrics["if_frequency_khz"] is None
        assert result.metrics["ber_state"] is None
        assert result.metrics["stale"] is True
        assert result.health is Health.ERROR

    def test_topological_break_idle_propagates(self) -> None:
        # 上游 metrics 缺失（拓扑断裂）→ 输入态 idle 传播 → unlocked.
        result = _evaluate(
            TunerEvaluator(),
            _config(11_095_000, "vertical"),
            PortState(port_id="rf_in", health=Health.IDLE),
        )
        assert result.health is Health.IDLE
        assert result.metrics["lock_state"] == "unlocked"
        assert result.metrics["if_frequency_khz"] is None
        assert result.metrics["ber_state"] is None
        assert result.metrics["locked_transponder_id"] is None
        assert result.metrics["stale"] is True

    def test_no_feeder_at_all_is_idle(self) -> None:
        result = _evaluate(TunerEvaluator(), _config(11_095_000, "vertical"), None)
        assert result.health is Health.IDLE
        assert result.metrics["lock_state"] == "unlocked"

    def test_missing_tuning_request_is_idle_not_raised(self) -> None:
        # Ticket-frozen posture: a missing tuning_request is the #163/#165
        # prepare face; the evaluator degrades to idle without raising
        # (walk isolation stays reserved for evaluator-internal faults).
        result = _evaluate(TunerEvaluator(), {}, _feeder(_upstream_metrics()))
        assert result.health is Health.IDLE
        assert result.metrics["lock_state"] == "unlocked"
        assert result.metrics["stale"] is True

    def test_isolated_lnb_failure_unlocks_with_severe(self) -> None:
        # The walk isolates a thrown evaluator into an error node with
        # EMPTY metrics: the tuner sees an anomalous feeder without facts
        # → unlocked + severe (no fabricating an IF).
        result = _evaluate(
            TunerEvaluator(),
            _config(11_095_000, "vertical"),
            _feeder({}, health=Health.ERROR),
        )
        assert result.metrics["lock_state"] == "unlocked"
        assert result.metrics["if_frequency_khz"] is None
        assert result.metrics["ber_state"] == "severe"
        assert result.metrics["stale"] is True
        assert result.health is Health.ERROR

    def test_foreign_lo_value_defensively_unlocks(self) -> None:
        # A delivered LO outside the plan is not on any arm: unlocked, the
        # IF fact still computes (spec formula), no grade without anomaly.
        result = _evaluate(
            TunerEvaluator(),
            _config(11_095_000, "vertical"),
            _feeder(_upstream_metrics(lo_frequency_khz=8_000_000)),
        )
        assert result.metrics["lock_state"] == "unlocked"
        assert result.metrics["if_frequency_khz"] == 3_095_000
        assert result.metrics["ber_state"] is None


class TestTunerMetricsShape:
    """The tuner metrics key set is the #164 payload-registration source."""

    def test_metrics_key_set_is_frozen(self) -> None:
        result = _evaluate(
            TunerEvaluator(),
            _config(11_095_000, "vertical"),
            _feeder(_upstream_metrics()),
        )
        assert set(result.metrics) == {
            "lock_state",
            "if_frequency_khz",
            "ber_state",
            "locked_transponder_id",
            "stale",
        }

    def test_locked_snapshots_are_never_stale(self) -> None:
        result = _evaluate(
            TunerEvaluator(),
            _config(11_095_000, "vertical"),
            _feeder(_upstream_metrics()),
        )
        assert result.metrics["stale"] is False

    def test_determinism_same_input_same_output(self) -> None:
        # AC-620-06: same config + same inputs, double run, field-identical.
        feeder = _feeder(_upstream_metrics(tone_actual="continuous"))
        config = _config(11_095_000, "vertical")
        first = _evaluate(TunerEvaluator(), config, feeder)
        second = _evaluate(TunerEvaluator(), config, feeder)
        assert first == second

    def test_tuner_emits_no_output_port_metrics(self) -> None:
        # The tuner is a leaf: its port states carry health only.
        result = _evaluate(
            TunerEvaluator(),
            _config(11_095_000, "vertical"),
            _feeder(_upstream_metrics()),
        )
        (rf_in,) = result.port_states
        assert rf_in.port_id == "rf_in"
        assert rf_in.metrics == {}
