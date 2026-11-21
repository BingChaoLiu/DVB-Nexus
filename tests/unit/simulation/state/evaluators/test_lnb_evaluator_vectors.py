"""SPEC-621 appendix A — the 14-state LNB truth table, cell by cell (#161).

Seam: ``simulation.state.evaluators.lnb_evaluator`` — the band-selection
pure function plus the :class:`LnbEvaluator` shell.

Vector-first discipline (SPEC-621 §11.2): the 14-state table below is the
normative appendix A truth table transcribed **verbatim, cell by cell**,
before the implementation was written (brief §E.2).  The implementation
must reproduce these literals; a mismatch is an implementation bug, never
a test bug.

Unit reconciliations frozen by ticket #161 (REPORT-declared):

- The appendix A ``lo_frequency_khz`` column prints ``9750`` / ``10600``
  — MHz-denominated shorthand against a ``*_khz`` field.  Frozen as the
  full kHz values ``9750000`` / ``10600000``, consistent with
  ``LoFrequenciesDTO.low_khz/high_khz`` and the IF-window arithmetic
  (950000..1950000 kHz).
- The composite state (rows 13/14) is encoded as ``tone_actual =
  "data_burst"`` (the addressing burst) + ``tone_composite =
  "continuous_plus_data_burst"`` (the continuous carrier component);
  the band follows the continuous component.
- Rows 1-4 (voltage off) are the 0V semantics: band ``none`` / LO
  ``null`` / polarization ``none`` — the tone has no carrier.
"""

from __future__ import annotations

import pytest

from simulation.state.evaluate import EvalContext, Health
from simulation.state.graph import NodeConfig, PortSpec
from simulation.state.evaluators import LnbEvaluator
from simulation.state.evaluators.lnb_evaluator import (
    DEFAULT_LO_HIGH_KHZ,
    DEFAULT_LO_LOW_KHZ,
    lnb_health,
    select_band,
)

pytestmark = pytest.mark.unit

# -- vector table: SPEC-621 appendix A, 14 states verbatim ---------------------
#
# (voltage, tone_actual, tone_composite) -> (band_selected, lo_frequency_khz,
# polarization_delivered).  The default universal LO plan makes the table's
# LO column literal (9750/10600 MHz -> 9750000/10600000 kHz).

#: 0V semantics: unpowered — band none, LO null, polarization none, the
#: tone has no carrier (rows 1-4; the tone value is irrelevant).
APPENDIX_A_ROWS_1_TO_4 = [
    ("off", "none", "none", "none", None, "none"),
    ("off", "continuous", "none", "none", None, "none"),
    ("off", "tone_burst", "none", "none", None, "none"),
    ("off", "data_burst", "none", "none", None, "none"),
]

#: Powered universal rows (5-12): tone continuous drives the high band,
#: everything else (none / tone_burst / data_burst) stays low; 13V ->
#: vertical, 18V -> horizontal.
APPENDIX_A_ROWS_5_TO_12 = [
    ("13V", "none", "none", "low", 9750000, "vertical"),
    ("13V", "continuous", "none", "high", 10600000, "vertical"),
    ("13V", "tone_burst", "none", "low", 9750000, "vertical"),
    ("13V", "data_burst", "none", "low", 9750000, "vertical"),
    ("18V", "none", "none", "low", 9750000, "horizontal"),
    ("18V", "continuous", "none", "high", 10600000, "horizontal"),
    ("18V", "tone_burst", "none", "low", 9750000, "horizontal"),
    ("18V", "data_burst", "none", "low", 9750000, "horizontal"),
]

#: Composite rows (13/14): continuous + data_burst — band semantics of the
#: continuous component叠加 on the data_burst addressing.  Frozen encoding:
#: ``tone_actual="data_burst"`` + ``tone_composite=
#: "continuous_plus_data_burst"``.
APPENDIX_A_ROWS_13_14 = [
    ("13V", "data_burst", "continuous_plus_data_burst", "high", 10600000, "vertical"),
    ("18V", "data_burst", "continuous_plus_data_burst", "high", 10600000, "horizontal"),
]

ALL_14_ROWS = APPENDIX_A_ROWS_1_TO_4 + APPENDIX_A_ROWS_5_TO_12 + APPENDIX_A_ROWS_13_14


class TestAppendixATruthTable:
    """AC-621-01 — 14 states asserted cell by cell (band / LO / polarization)."""

    @pytest.mark.parametrize(
        "voltage,tone_actual,tone_composite,band,lo_khz,polarization",
        APPENDIX_A_ROWS_1_TO_4,
        ids=["row1-off-none", "row2-off-cont", "row3-off-tburst", "row4-off-dburst"],
    )
    def test_rows_1_to_4_zero_volt(
        self, voltage, tone_actual, tone_composite, band, lo_khz, polarization
    ) -> None:
        delivery = select_band(
            "universal", voltage, tone_actual, tone_composite
        )
        assert delivery.band_selected == band
        assert delivery.lo_frequency_khz == lo_khz
        assert delivery.polarization_delivered == polarization

    @pytest.mark.parametrize(
        "voltage,tone_actual,tone_composite,band,lo_khz,polarization",
        APPENDIX_A_ROWS_5_TO_12,
        ids=[
            "row5-13V-none", "row6-13V-cont", "row7-13V-tburst", "row8-13V-dburst",
            "row9-18V-none", "row10-18V-cont", "row11-18V-tburst", "row12-18V-dburst",
        ],
    )
    def test_rows_5_to_12_powered(
        self, voltage, tone_actual, tone_composite, band, lo_khz, polarization
    ) -> None:
        delivery = select_band(
            "universal", voltage, tone_actual, tone_composite
        )
        assert delivery.band_selected == band
        assert delivery.lo_frequency_khz == lo_khz
        assert delivery.polarization_delivered == polarization

    @pytest.mark.parametrize(
        "voltage,tone_actual,tone_composite,band,lo_khz,polarization",
        APPENDIX_A_ROWS_13_14,
        ids=["row13-13V-composite", "row14-18V-composite"],
    )
    def test_rows_13_14_composite(
        self, voltage, tone_actual, tone_composite, band, lo_khz, polarization
    ) -> None:
        delivery = select_band(
            "universal", voltage, tone_actual, tone_composite
        )
        assert delivery.band_selected == band
        assert delivery.lo_frequency_khz == lo_khz
        assert delivery.polarization_delivered == polarization

    def test_composite_alt_encoding_continuous_actual_still_high(self) -> None:
        # The composite marker alone carries the continuous component: even
        # with tone_actual="none" the composite state drives the high band
        # (the continuous carrier is present in the composite).
        delivery = select_band(
            "universal", "13V", "none", "continuous_plus_data_burst"
        )
        assert delivery.band_selected == "high"
        assert delivery.lo_frequency_khz == 10600000

    def test_full_table_row_count(self) -> None:
        # The appendix A table has exactly 14 normative rows.
        assert len(ALL_14_ROWS) == 14


class TestCustomLoPlan:
    """The band pure function is plan-parametrised: a custom ``lo_frequencies``
    plan replaces the appendix A default LO column value-for-value."""

    def test_custom_plan_low_band_uses_plan_low_khz(self) -> None:
        delivery = select_band(
            "universal", "13V", "none", "none",
            lo_plan_low_khz=9750000, lo_plan_high_khz=11300000,
        )
        assert delivery.band_selected == "low"
        assert delivery.lo_frequency_khz == 9750000

    def test_custom_plan_high_band_uses_plan_high_khz(self) -> None:
        delivery = select_band(
            "universal", "18V", "continuous", "none",
            lo_plan_low_khz=9750000, lo_plan_high_khz=11300000,
        )
        assert delivery.band_selected == "high"
        assert delivery.lo_frequency_khz == 11300000

    def test_default_plan_constants(self) -> None:
        # The universal default plan (SPEC-621 §5 documented reference
        # default {9750, 10600} MHz).
        assert DEFAULT_LO_LOW_KHZ == 9750000
        assert DEFAULT_LO_HIGH_KHZ == 10600000


class TestLegacyCascade:
    """SPEC-621 §7 legacy_cascade simplified semantics (AC-621-06).

    Frozen by ticket #161 (REPORT-declared): the legacy LNB has a single
    LO (the plan's ``low_khz``) — no band-selection mechanism exists, so
    ``band_selected`` stays ``none`` while powered (the band label is
    derived tuner-side from the tuning frequency per §7); the 22kHz tone
    selects Satellite A/B instead (``sat_selected``: continuous present —
    pure or composite — selects B, otherwise A).  Polarization stays
    voltage-driven.
    """

    def test_legacy_tone_none_selects_sat_a_low_lo(self) -> None:
        delivery = select_band("legacy_cascade", "13V", "none", "none")
        assert delivery.band_selected == "none"
        assert delivery.lo_frequency_khz == 9750000
        assert delivery.polarization_delivered == "vertical"
        assert delivery.sat_selected == "A"

    def test_legacy_tone_continuous_selects_sat_b(self) -> None:
        delivery = select_band("legacy_cascade", "18V", "continuous", "none")
        assert delivery.sat_selected == "B"
        assert delivery.lo_frequency_khz == 9750000
        assert delivery.polarization_delivered == "horizontal"
        assert delivery.band_selected == "none"

    def test_legacy_bursts_select_sat_a(self) -> None:
        assert select_band("legacy_cascade", "13V", "tone_burst", "none").sat_selected == "A"
        assert select_band("legacy_cascade", "13V", "data_burst", "none").sat_selected == "A"

    def test_legacy_composite_selects_sat_b(self) -> None:
        delivery = select_band(
            "legacy_cascade", "13V", "data_burst", "continuous_plus_data_burst"
        )
        assert delivery.sat_selected == "B"

    def test_legacy_unpowered_delivers_nothing(self) -> None:
        delivery = select_band("legacy_cascade", "off", "none", "none")
        assert delivery.band_selected == "none"
        assert delivery.lo_frequency_khz is None
        assert delivery.polarization_delivered == "none"
        assert delivery.sat_selected is None


class TestShortCircuitHealth:
    """AC-621-03 — the five-state short-circuit vocabulary and health map.

    ``hiccup`` 128ms retry / 160°C-140°C hysteresis are reference-table
    facts that never enter the evaluation (SPEC-621 §7); the five states
    are terminal; ``fault_latched`` resets only via explicit clear (no
    built-in clock advance — the evaluator state is decided by its inputs).
    """

    def test_normal_maps_ok(self) -> None:
        assert lnb_health("normal") is Health.OK

    def test_clamping_and_hiccup_map_warn(self) -> None:
        assert lnb_health("clamping") is Health.WARN
        assert lnb_health("hiccup") is Health.WARN

    def test_thermal_and_latched_map_error(self) -> None:
        assert lnb_health("thermal_fault") is Health.ERROR
        assert lnb_health("fault_latched") is Health.ERROR

    def test_five_state_vocabulary_is_closed(self) -> None:
        from simulation.state.evaluators._vocab import SHORT_CIRCUIT_STATES

        assert SHORT_CIRCUIT_STATES == (
            "normal", "clamping", "hiccup", "thermal_fault", "fault_latched",
        )


# -- evaluator shell helpers ----------------------------------------------------


def _lnb_node(config: dict) -> NodeConfig:
    return NodeConfig(
        node_id="lnb-0",
        node_type="lnb",
        config=config,
        ports=[
            PortSpec(port_id="coax_out", direction="output", plane="SEC_CONTROL", max_connections=2),
        ],
    )


def _evaluate(evaluator: LnbEvaluator, config: dict):
    return evaluator.evaluate(_lnb_node(config), {}, EvalContext(topology_revision=1))


def _full_config(**overrides: object) -> dict:
    base = {
        "lnb_kind": "universal",
        "lo_frequencies": {"low_khz": 9750000, "high_khz": 10600000},
        "voltage": "13V",
        "tone_commanded": "none",
        "tone_actual": "none",
        "tone_composite": "none",
        "short_circuit_state": "normal",
    }
    base.update(overrides)
    return base


class TestLnbEvaluatorShell:
    """The dataclass-style shell: config dict in -> NodeEvalResult out."""

    def test_metrics_key_set_is_frozen(self) -> None:
        # The #164 payload-registration source: the lnb node metrics carry
        # exactly these keys (SPEC-621 §5 list + SPEC-303 §Phase3 lnb
        # snapshot's ``ub_assignments``; legacy adds ``sat_selected``).
        result = _evaluate(LnbEvaluator(), _full_config())
        assert set(result.metrics) == {
            "voltage",
            "tone_commanded",
            "tone_actual",
            "tone_composite",
            "band_selected",
            "lo_frequency_khz",
            "polarization_delivered",
            "short_circuit_state",
            "ub_assignments",
        }

    def test_metrics_values_json_safe(self) -> None:
        result = _evaluate(LnbEvaluator(), _full_config())
        for value in result.metrics.values():
            assert value is None or isinstance(value, (bool, int, str, list))

    def test_powered_delivery_metrics(self) -> None:
        result = _evaluate(
            LnbEvaluator(),
            _full_config(
                voltage="18V",
                tone_commanded="continuous",
                tone_actual="continuous",
            ),
        )
        assert result.metrics["voltage"] == "18V"
        assert result.metrics["tone_commanded"] == "continuous"
        assert result.metrics["band_selected"] == "high"
        assert result.metrics["lo_frequency_khz"] == 10600000
        assert result.metrics["polarization_delivered"] == "horizontal"
        assert result.metrics["short_circuit_state"] == "normal"
        assert result.metrics["ub_assignments"] == []

    def test_unpowered_metrics(self) -> None:
        result = _evaluate(LnbEvaluator(), _full_config(voltage="off"))
        assert result.metrics["band_selected"] == "none"
        assert result.metrics["lo_frequency_khz"] is None
        assert result.metrics["polarization_delivered"] == "none"

    def test_tone_commanded_and_actual_independent_injection(self) -> None:
        # AC-621-02: the dual-field seam — the TONE_RESIDUE transform
        # rewrites tone_actual only; commanded stays authoritative.
        result = _evaluate(
            LnbEvaluator(),
            _full_config(tone_commanded="none", tone_actual="continuous"),
        )
        assert result.metrics["tone_commanded"] == "none"
        assert result.metrics["tone_actual"] == "continuous"
        # Delivery follows the ACTUAL tone (high band, 10600).
        assert result.metrics["band_selected"] == "high"
        assert result.metrics["lo_frequency_khz"] == 10600000
        # Health is the short-circuit axis only: a tone mismatch is not an
        # LNB-health fault (the tuner grades it severe downstream).
        assert result.health is Health.OK

    def test_short_circuit_states_drive_health(self) -> None:
        assert _evaluate(LnbEvaluator(), _full_config(short_circuit_state="clamping")).health is Health.WARN
        assert _evaluate(LnbEvaluator(), _full_config(short_circuit_state="hiccup")).health is Health.WARN
        assert _evaluate(
            LnbEvaluator(), _full_config(short_circuit_state="thermal_fault")
        ).health is Health.ERROR
        assert _evaluate(
            LnbEvaluator(), _full_config(short_circuit_state="fault_latched")
        ).health is Health.ERROR

    def test_short_circuit_does_not_alter_delivery(self) -> None:
        # The short-circuit axis is orthogonal to the appendix A delivery
        # table (REPORT-frozen): clamping LNB still delivers per the table;
        # consequences flow through health + the downstream ber rule.
        result = _evaluate(
            LnbEvaluator(), _full_config(short_circuit_state="clamping")
        )
        assert result.metrics["band_selected"] == "low"
        assert result.metrics["lo_frequency_khz"] == 9750000
        assert result.metrics["polarization_delivered"] == "vertical"

    def test_out_of_vocabulary_short_circuit_is_loud_not_silent(self) -> None:
        # A foreign short-circuit value is never normalised to normal: the
        # raw value passes through and the node reports error health
        # (prepare rejection is the #163/#165 face; the evaluator refuses
        # to call it healthy).
        result = _evaluate(LnbEvaluator(), _full_config(short_circuit_state="sparks"))
        assert result.metrics["short_circuit_state"] == "sparks"
        assert result.health is Health.ERROR

    def test_legacy_metrics_carry_sat_selected(self) -> None:
        result = _evaluate(
            LnbEvaluator(),
            _full_config(
                lnb_kind="legacy_cascade",
                tone_commanded="continuous",
                tone_actual="continuous",
            ),
        )
        assert result.metrics["sat_selected"] == "B"
        assert result.metrics["band_selected"] == "none"
        assert result.metrics["lo_frequency_khz"] == 9750000

    def test_universal_metrics_have_no_sat_selected(self) -> None:
        result = _evaluate(LnbEvaluator(), _full_config())
        assert "sat_selected" not in result.metrics

    def test_scr_snapshot_in_metrics(self) -> None:
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
        config = _full_config(scr={"protocol": "EN50494", "ub_assignments": table})
        result = _evaluate(LnbEvaluator(), config)
        assert result.metrics["ub_assignments"] == table

    def test_missing_drive_keys_default_to_unpowered(self) -> None:
        # SC-10/SC-11 drafts carry no drive keys; the frozen defaults are
        # voltage=off / tone none (honest: an unconfigured LNB delivers no
        # carrier).  Scenario calibration (#171) authors explicit keys.
        config = {
            "lnb_kind": "universal",
            "lo_frequencies": {"low_khz": 9750000, "high_khz": 10600000},
        }
        result = _evaluate(LnbEvaluator(), config)
        assert result.metrics["voltage"] == "off"
        assert result.metrics["tone_commanded"] == "none"
        assert result.metrics["tone_actual"] == "none"
        assert result.metrics["band_selected"] == "none"
        assert result.metrics["lo_frequency_khz"] is None
        assert result.health is Health.OK

    def test_output_port_state_carries_signal_facts(self) -> None:
        # The A2 channel: the walk threads the feeding port's metrics to
        # downstream inputs, so coax_out carries the full lnb fact set plus
        # the plumbing keys (lnb_kind / lo plan / scr protocol) the tuner
        # needs and the node config alone cannot expose.
        result = _evaluate(LnbEvaluator(), _full_config())
        (coax_out,) = result.port_states
        assert coax_out.port_id == "coax_out"
        assert coax_out.health is Health.OK
        assert coax_out.metrics["lnb_kind"] == "universal"
        assert coax_out.metrics["lo_plan_low_khz"] == 9750000
        assert coax_out.metrics["lo_plan_high_khz"] == 10600000
        assert coax_out.metrics["scr_protocol"] is None
        assert coax_out.metrics["lo_frequency_khz"] == 9750000

    def test_scr_protocol_in_port_metrics(self) -> None:
        config = _full_config(
            scr={"protocol": "EN50607", "ub_assignments": []}
        )
        result = _evaluate(LnbEvaluator(), config)
        assert result.port_states[0].metrics["scr_protocol"] == "EN50607"

    def test_out_of_vocabulary_voltage_degrades_to_off_passthrough(self) -> None:
        # REPORT-frozen degrade-don't-throw posture: a foreign voltage is
        # never treated as powered; the raw value stays visible in metrics.
        result = _evaluate(LnbEvaluator(), _full_config(voltage="27V"))
        assert result.metrics["voltage"] == "27V"
        assert result.metrics["band_selected"] == "none"
        assert result.metrics["lo_frequency_khz"] is None

    def test_determinism_same_input_same_output(self) -> None:
        # AC-621-05: same config, double run, field-identical results.
        config = _full_config(voltage="18V", tone_actual="continuous")
        first = _evaluate(LnbEvaluator(), config)
        second = _evaluate(LnbEvaluator(), config)
        assert first == second
        assert first.metrics == second.metrics
        assert first.port_states == second.port_states

    def test_port_states_carry_all_ports(self) -> None:
        result = _evaluate(LnbEvaluator(), _full_config())
        assert [state.port_id for state in result.port_states] == ["coax_out"]
