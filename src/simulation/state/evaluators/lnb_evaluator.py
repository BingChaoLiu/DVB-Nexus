"""SPEC-621 §6/§7 — the LNB band-selection pure functions + evaluator (#161).

Seam: ``simulation.state.evaluators.lnb_evaluator`` — registered under the
``"lnb"`` node-type wire string via :func:`evaluate_topology`'s injection
mapping (:data:`simulation.state.evaluators.DEFAULT_EVALUATORS`).

Pure-function core (each independently unit-tested, house "pure core +
dataclass shell" style):

- :func:`select_band` — the SPEC-621 §6 band-selection function
  ``(lnb_kind, voltage, tone_actual, tone_composite) → (band_selected,
  lo_frequency_khz, polarization_delivered)``, cell-for-cell the appendix
  A 14-state truth table, parametrised by the LO plan (the appendix A LO
  column is the default plan 9750000/10600000 kHz — the spec prints those
  cells in MHz shorthand against a ``*_khz`` field, REPORT-frozen as full
  kHz).  The ``legacy_cascade`` branch is the §7 simplified semantics:
  single LO (the plan's ``low_khz``), no band mechanism (``band_selected
  = "none"``, REPORT-frozen — the band label is derived tuner-side from
  the tuning frequency), 22kHz tone selects Satellite A/B via the
  additive ``sat_selected`` fact, polarization stays voltage-driven.
- :func:`lnb_health` — the short-circuit five-state health map
  (clamping/hiccup → warn; thermal_fault/fault_latched → error; normal →
  ok).  The five states are terminal; hiccup's 128 ms retry rhythm and
  the 160/140 °C hysteresis are reference-table facts that never enter
  the evaluation; ``fault_latched`` resets only via an explicit clear
  (the evaluator state is decided by its inputs, no built-in clock).

Shell semantics (REPORT-frozen):

- Drive facts (``voltage`` / ``tone_commanded`` / ``tone_actual`` /
  ``tone_composite`` / ``short_circuit_state``) come from the node's
  evaluation-time config — they are NOT ``LnbConfigDTO`` fields; they
  arrive through fault transforms (#163) or scenario calibration (#171)
  after config validation.  Defaults: voltage ``off``, tones ``none``,
  ``tone_actual`` falls back to ``tone_commanded`` when absent,
  short-circuit ``normal`` — an unconfigured LNB delivers no carrier.
- The short-circuit axis is orthogonal to the appendix A delivery table:
  a clamping/hiccup/faulted LNB still delivers per the table; the
  consequences flow through health and the downstream tuner ber rule
  (``short_circuit_state ≠ normal`` → severe).
- Out-of-vocabulary values degrade without raising: a foreign voltage is
  never treated as powered, a foreign tone never selects a band — the
  RAW input values stay visible in the metrics (no silent lying) and
  prepare rejection stays the #163/#165 face.  A foreign short-circuit
  value is the one loud case: the node reports error health rather than
  normalising it to ``normal``.
- ``ub_assignments`` is the SCR table snapshot (SPEC-303 §Phase3 lnb
  snapshot key, SPEC-623 §5); empty list without an ``scr`` segment.
- The output port (``coax_out``) carries the full signal-fact snapshot on
  its A2 ``PortState.metrics`` channel: node metrics + the plumbing keys
  (``lnb_kind`` / LO plan / ``scr_protocol``) downstream evaluators need
  and the node config alone cannot expose (importlinter contract 8 — the
  tuner cannot read this node's config).
"""

from __future__ import annotations

from dataclasses import dataclass

from simulation.state.evaluate import (
    EvalContext,
    Health,
    NodeEvalResult,
    PortState,
)
from simulation.state.evaluators._vocab import (
    LNB_KINDS,
    LNB_KIND_METRIC_KEY,
    LNB_SAT_SELECTED_METRIC_KEY,
    LO_FREQUENCIES_CONFIG_KEY,
    LO_PLAN_HIGH_METRIC_KEY,
    LO_PLAN_LOW_METRIC_KEY,
    SCR_CONFIG_KEY,
    SCR_PROTOCOL_METRIC_KEY,
    SHORT_CIRCUIT_STATE_CONFIG_KEY,
    TONE_ACTUAL_CONFIG_KEY,
    TONE_COMMANDED_CONFIG_KEY,
    TONE_COMPOSITE_CONFIG_KEY,
    VOLTAGE_CONFIG_KEY,
)
from simulation.state.graph import NodeConfig

__all__ = [
    "DEFAULT_LO_HIGH_KHZ",
    "DEFAULT_LO_LOW_KHZ",
    "BandDelivery",
    "LnbEvaluator",
    "lnb_health",
    "select_band",
]

#: Universal default LO plan, kHz (SPEC-621 §5 documented reference
#: default {9750, 10600} MHz — appendix A LO column shorthand).
DEFAULT_LO_LOW_KHZ = 9_750_000
DEFAULT_LO_HIGH_KHZ = 10_600_000


@dataclass(frozen=True)
class BandDelivery:
    """One appendix A cell: the LNB's terminal delivery facts.

    ``sat_selected`` is the legacy_cascade-only additive fact
    (``"A"``/``"B"``); ``None`` for universal and when unpowered.
    """

    band_selected: str
    lo_frequency_khz: int | None
    polarization_delivered: str
    sat_selected: str | None = None


def _high_band_requested(tone_actual: object, tone_composite: object) -> bool:
    """The continuous 22kHz carrier is present — pure or as the composite's
    continuous component (SPEC-621 §7 composite叠加 semantics)."""
    return (
        tone_actual == "continuous"
        or tone_composite == "continuous_plus_data_burst"
    )


def _polarization_for(voltage: object) -> str:
    if voltage == "13V":
        return "vertical"
    if voltage == "18V":
        return "horizontal"
    return "none"


def select_band(
    lnb_kind: str,
    voltage: object,
    tone_actual: object,
    tone_composite: object,
    lo_plan_low_khz: int = DEFAULT_LO_LOW_KHZ,
    lo_plan_high_khz: int = DEFAULT_LO_HIGH_KHZ,
) -> BandDelivery:
    """The SPEC-621 §6 band-selection function, appendix A cell by cell.

    Pure and total over the inputs: out-of-vocabulary values degrade to
    the unpowered/no-tone delivery semantics (the shell passes the raw
    values through in metrics).  The LO plan parameters carry the config's
    ``lo_frequencies``; the defaults reproduce the appendix A table's LO
    column verbatim.
    """
    if lnb_kind not in LNB_KINDS or voltage not in ("13V", "18V"):
        # 0V semantics (rows 1-4): no carrier, no band, no polarization;
        # the tone has nothing to ride on.  Foreign inputs degrade here.
        return BandDelivery("none", None, "none", None)

    polarization = _polarization_for(voltage)
    if lnb_kind == "legacy_cascade":
        # §7 simplified semantics: single LO, no band mechanism, the tone
        # selects the satellite instead.
        sat = "B" if _high_band_requested(tone_actual, tone_composite) else "A"
        return BandDelivery("none", lo_plan_low_khz, polarization, sat)

    # Universal rows 5-14: continuous carrier (pure or composite) → high
    # band; everything else stays low.
    if _high_band_requested(tone_actual, tone_composite):
        return BandDelivery("high", lo_plan_high_khz, polarization, None)
    return BandDelivery("low", lo_plan_low_khz, polarization, None)


def lnb_health(short_circuit_state: object) -> Health:
    """The short-circuit five-state health map (SPEC-621 §5).

    A foreign value is loud: error health — never silently normalised.
    """
    if short_circuit_state == "normal":
        return Health.OK
    if short_circuit_state in ("clamping", "hiccup"):
        return Health.WARN
    # thermal_fault / fault_latched and any foreign value: error.
    return Health.ERROR


class LnbEvaluator:
    """The ``lnb`` node evaluator shell (SPEC-202 §6.1 protocol shape)."""

    def evaluate(
        self,
        node: NodeConfig,
        inputs: dict,
        context: EvalContext,
    ) -> NodeEvalResult:
        config = node.config if isinstance(node.config, dict) else {}

        lnb_kind = config.get("lnb_kind")
        lo_plan = config.get(LO_FREQUENCIES_CONFIG_KEY)
        lo_plan = lo_plan if isinstance(lo_plan, dict) else {}
        lo_plan_low_khz = lo_plan.get("low_khz", DEFAULT_LO_LOW_KHZ)
        lo_plan_high_khz = lo_plan.get("high_khz", DEFAULT_LO_HIGH_KHZ)

        voltage = config.get(VOLTAGE_CONFIG_KEY, "off")
        tone_commanded = config.get(TONE_COMMANDED_CONFIG_KEY, "none")
        # tone_actual falls back to the commanded value (no fault transform
        # present → the LNB follows its command).
        tone_actual = config.get(TONE_ACTUAL_CONFIG_KEY, tone_commanded)
        tone_composite = config.get(TONE_COMPOSITE_CONFIG_KEY, "none")
        short_circuit_state = config.get(SHORT_CIRCUIT_STATE_CONFIG_KEY, "normal")

        delivery = select_band(
            lnb_kind,
            voltage,
            tone_actual,
            tone_composite,
            lo_plan_low_khz=lo_plan_low_khz,
            lo_plan_high_khz=lo_plan_high_khz,
        )

        scr = config.get(SCR_CONFIG_KEY)
        scr = scr if isinstance(scr, dict) else {}
        scr_protocol = scr.get("protocol")
        scr_table = scr.get("ub_assignments")
        scr_table = list(scr_table) if isinstance(scr_table, list) else []

        # Raw input values pass through verbatim — the delivery functions
        # degraded foreign values, the metrics never lie about the input.
        metrics = {
            "voltage": voltage,
            "tone_commanded": tone_commanded,
            "tone_actual": tone_actual,
            "tone_composite": tone_composite,
            "band_selected": delivery.band_selected,
            "lo_frequency_khz": delivery.lo_frequency_khz,
            "polarization_delivered": delivery.polarization_delivered,
            "short_circuit_state": short_circuit_state,
            "ub_assignments": scr_table,
        }
        if lnb_kind == "legacy_cascade":
            metrics[LNB_SAT_SELECTED_METRIC_KEY] = delivery.sat_selected

        port_metrics = {
            **metrics,
            LNB_KIND_METRIC_KEY: lnb_kind,
            LO_PLAN_LOW_METRIC_KEY: lo_plan_low_khz,
            LO_PLAN_HIGH_METRIC_KEY: lo_plan_high_khz,
            SCR_PROTOCOL_METRIC_KEY: scr_protocol,
        }

        return NodeEvalResult(
            node_id=node.node_id,
            health=lnb_health(short_circuit_state),
            port_states=tuple(
                PortState(
                    port_id=port.port_id,
                    health=lnb_health(short_circuit_state),
                    metrics=port_metrics,
                )
                for port in node.ports
            ),
            metrics=metrics,
            causes=(),
        )
