"""Mirrored config-key and state vocabulary for the L0 evaluators (#161).

The evaluators read ``node.config`` dicts and must NOT import
``domain.topology`` (importlinter contract 8; orchestrator ruling A1) —
the config key names and state vocabularies live here as module constants.
Keys already mirrored by the #160 validator (``simulation.state.validate``)
and the #162 unicable module (``simulation.state.unicable``) are **reused
via import, never redefined**; this module owns only the keys neither
upstream site needed.  The tests layer three-way drift lock
(``tests/unit/simulation/state/evaluators/test_evaluator_vocab_drift_lock.py``)
pins every face against the domain config DTOs (rulings A1/A14).

The evaluation-time drive keys (``voltage`` / ``tone_commanded`` /
``tone_actual`` / ``tone_composite`` / ``short_circuit_state`` on the lnb)
are FIRST-CLASS optional config-DTO fields since ticket #171 (ruling A20 —
the「验证后进入」path is honest: the keys are part of the declared surface
the DTO gate validates), so the pre-A20 docstring paragraph claiming they
bypass the DTO gate is RETIRED (ticket #172); ``diseqc_commands`` was
always a DTO field.  Fault transforms (#163) still rewrite them at run
time — on the faulted path the rewrite is the SPEC-204 §Phase3 declared
mechanism, not a schema bypass.
"""

from __future__ import annotations

from simulation.state.validate import (
    DISEQC_SWITCH_NODE_TYPE,
    LNB_NODE_TYPE,
    SCR_CONFIG_KEY,
    TUNER_NODE_TYPE,
    UB_SLOT_CONFIG_KEY,
)

__all__ = [
    "BANDS",
    "BAND_BOUNDARY_KHZ",
    "BER_STATES",
    "COMMITTED_CONFIG_KEY",
    "DISEQC_COMMANDS_CONFIG_KEY",
    "HIGH_ARM_IF_FLOOR_KHZ",
    "HIGH_KHZ_CONFIG_KEY",
    "IF_SLOT_HIGH_KHZ",
    "IF_SLOT_LOW_KHZ",
    "LNB_KINDS",
    "LNB_KIND_CONFIG_KEY",
    "LNB_KIND_METRIC_KEY",
    "LNB_METRIC_KEYS",
    "LNB_NODE_TYPE",
    "LNB_SAT_SELECTED_METRIC_KEY",
    "LO_FREQUENCIES_CONFIG_KEY",
    "LO_PLAN_HIGH_METRIC_KEY",
    "LO_PLAN_LOW_METRIC_KEY",
    "LOCK_STATES",
    "LOW_KHZ_CONFIG_KEY",
    "NIBBLES",
    "NIBBLE_CONFIG_KEY",
    "NIBBLE_WRITES_CONFIG_KEY",
    "OWN_NODE_ID_CONFIG_KEY",
    "POLARIZATIONS",
    "POLARIZATION_DELIVERED",
    "PORT_SELECT_MASK",
    "POWER_PASS_CONFIG_KEY",
    "POWER_PASS_VALUES",
    "PROTECTION_BAND_WIDTH_KHZ",
    "REGISTER_CONFIG_KEY",
    "REGISTER_NIBBLE_SHIFT",
    "REGISTERS",
    "SCR_CONFIG_KEY",
    "SCR_PROTOCOLS",
    "SCR_PROTOCOL_METRIC_KEY",
    "SHORT_CIRCUIT_STATES",
    "SHORT_CIRCUIT_STATE_CONFIG_KEY",
    "TARGET_REGISTER_CONFIG_KEY",
    "TONE_ACTUAL_CONFIG_KEY",
    "TONE_COMMANDED_CONFIG_KEY",
    "TONE_COMPOSITE_CONFIG_KEY",
    "TONE_COMPOSITES",
    "TONES",
    "TUNER_METRIC_KEYS",
    "TUNER_NODE_TYPE",
    "TUNING_REQUEST_CONFIG_KEY",
    "UB_SLOT_CONFIG_KEY",
    "VALUE_CONFIG_KEY",
    "VOLTAGES",
    "VOLTAGE_CONFIG_KEY",
    "SWITCH_METRIC_KEYS",
]

# -- node-type wire strings (reused from the #160 validator) --------------------
#
# LNB_NODE_TYPE / TUNER_NODE_TYPE / DISEQC_SWITCH_NODE_TYPE are imported
# above (the #160 validator owns the wire strings; never redefined).

# -- config-dict key names (mirrored; imported sites noted per key) -------------

#: ``LnbConfigDTO`` fields.
LNB_KIND_CONFIG_KEY = "lnb_kind"
LO_FREQUENCIES_CONFIG_KEY = "lo_frequencies"
#: Reused from the #160 validator (``validate.py`` owns it).
SCR_CONFIG_KEY = SCR_CONFIG_KEY
LOW_KHZ_CONFIG_KEY = "low_khz"
HIGH_KHZ_CONFIG_KEY = "high_khz"

#: ``TunerConfigDTO`` fields.
TUNING_REQUEST_CONFIG_KEY = "tuning_request"
#: Reused from the #160 validator.
UB_SLOT_CONFIG_KEY = UB_SLOT_CONFIG_KEY
DISEQC_COMMANDS_CONFIG_KEY = "diseqc_commands"

#: ``TuningRequestDTO`` fields (frequency/polarization mirror lives in
#: ``simulation.state.unicable`` — imported there by the tuner).
#: ``DiseqcCommandsDTO`` / ``DiseqcTargetRegisterDTO`` /
#: ``DiseqcNibbleWriteDTO`` wire keys.
TARGET_REGISTER_CONFIG_KEY = "target_register"
NIBBLE_WRITES_CONFIG_KEY = "nibble_writes"
REGISTER_CONFIG_KEY = "register"
NIBBLE_CONFIG_KEY = "nibble"
VALUE_CONFIG_KEY = "value"
COMMITTED_CONFIG_KEY = "committed"
UNCOMMITTED_CONFIG_KEY = "uncommitted"

#: ``SwitchConfigDTO`` fields.
POWER_PASS_CONFIG_KEY = "power_pass"

#: Evaluation-time drive keys (lnb) — fault-transform / calibration face.
VOLTAGE_CONFIG_KEY = "voltage"
TONE_COMMANDED_CONFIG_KEY = "tone_commanded"
TONE_ACTUAL_CONFIG_KEY = "tone_actual"
TONE_COMPOSITE_CONFIG_KEY = "tone_composite"
SHORT_CIRCUIT_STATE_CONFIG_KEY = "short_circuit_state"

#: The tuner's own node identity inside :func:`ub_conflicts` claims
#: (reuses the #162 mirror value; pinned by the drift lock).
OWN_NODE_ID_CONFIG_KEY = "node_id"

# -- state vocabularies (SPEC-620/621/622 §5 normative value sets) --------------

#: ``LnbConfigDTO.lnb_kind`` (SPEC-621 §5).
LNB_KINDS: tuple[str, ...] = ("universal", "legacy_cascade")

#: LNB voltage vocabulary (SPEC-621 §5): 13V → vertical, 18V → horizontal.
VOLTAGES: tuple[str, ...] = ("off", "13V", "18V")

#: 22kHz tone vocabulary (SPEC-621 §5).
TONES: tuple[str, ...] = ("none", "continuous", "tone_burst", "data_burst")

#: Composite tone marker (SPEC-621 §5): continuous + data_burst.
TONE_COMPOSITES: tuple[str, ...] = ("none", "continuous_plus_data_burst")

#: Delivered band vocabulary; ``none`` = unpowered (universal) / no
#: band mechanism (legacy, REPORT-frozen).
BANDS: tuple[str, ...] = ("low", "high", "none")

#: Delivered polarization vocabulary.
POLARIZATION_DELIVERED: tuple[str, ...] = ("vertical", "horizontal", "none")

#: Short-circuit protection terminal states (SPEC-621 §5/§7); hiccup
#: 128 ms retry and the 160/140 °C hysteresis are reference-table facts
#: that never enter the evaluation.
SHORT_CIRCUIT_STATES: tuple[str, ...] = (
    "normal",
    "clamping",
    "hiccup",
    "thermal_fault",
    "fault_latched",
)

#: SCR protocol vocabulary (reuses the #160 validator set's values).
SCR_PROTOCOLS: tuple[str, ...] = ("EN50494", "EN50607")

#: Tuning-request polarization values (``TuningRequestDTO`` mirror; the
#: full mirror constants live in ``simulation.state.unicable``).
POLARIZATIONS: tuple[str, ...] = ("vertical", "horizontal")

#: DiSEqC register names (SPEC-622 §2.1: 0x38 = committed N0, 0x39 =
#: uncommitted N1) and nibble selectors (§5/§6).
REGISTERS: tuple[str, ...] = ("committed", "uncommitted")
NIBBLES: tuple[str, ...] = ("high", "low")

#: ``SwitchConfigDTO.power_pass`` vocabulary.
POWER_PASS_VALUES: tuple[str, ...] = ("on", "off")

#: Tuner lock / ber vocabularies (SPEC-620 §5).
LOCK_STATES: tuple[str, ...] = ("unlocked", "locked")
BER_STATES: tuple[str, ...] = ("normal", "elevated", "severe")

# -- metric-key sets (the #164 payload-registration source) ----------------------

#: lnb node metrics — SPEC-621 §5 list + SPEC-303 §Phase3 lnb snapshot's
#: ``ub_assignments``.  ``sat_selected`` joins additively for
#: ``legacy_cascade`` only.
LNB_METRIC_KEYS: tuple[str, ...] = (
    "voltage",
    "tone_commanded",
    "tone_actual",
    "tone_composite",
    "band_selected",
    "lo_frequency_khz",
    "polarization_delivered",
    "short_circuit_state",
    "ub_assignments",
)
LNB_SAT_SELECTED_METRIC_KEY = "sat_selected"

#: tuner node metrics — SPEC-620 §5 list + the §8 ``stale`` flag
#: (REPORT-frozen: present on every snapshot, ``true`` iff unlocked).
TUNER_METRIC_KEYS: tuple[str, ...] = (
    "lock_state",
    "if_frequency_khz",
    "ber_state",
    "locked_transponder_id",
    "stale",
)

#: switch node metrics — SPEC-622 §5 list.
SWITCH_METRIC_KEYS: tuple[str, ...] = (
    "committed_switch_state",
    "uncommitted_switch_state",
    "port_selected",
    "power_pass",
)

#: lnb → tuner signal-fact plumbing keys (REPORT-frozen): facts the
#: downstream evaluators need that the node metrics key sets above do not
#: carry (the tuner cannot read the lnb's config dict — the facts travel
#: on the output port's A2 ``PortState.metrics`` channel).
LNB_KIND_METRIC_KEY = "lnb_kind"
LO_PLAN_LOW_METRIC_KEY = "lo_plan_low_khz"
LO_PLAN_HIGH_METRIC_KEY = "lo_plan_high_khz"
SCR_PROTOCOL_METRIC_KEY = "scr_protocol"

# -- IF-slot model constants (REPORT-frozen; SPEC-620 §3 / SPEC-621
#    appendix A band plan, kHz) -----------------------------------------------

#: Universal band boundary (reused from #162 — never redefined here).
BAND_BOUNDARY_KHZ = 11_700_000

#: The universal-LNB IF output window (appendix A: both band arms map to
#: IF 950–1950 MHz).
IF_SLOT_LOW_KHZ = 950_000
IF_SLOT_HIGH_KHZ = 1_950_000

#: High-arm IF floor: the high band (RF ≥ 11700000 kHz) starts at
#: IF 1100000 kHz — SPEC-620 §3's "低/高频段 IF 区间重叠 1100–1950 MHz".
#: Below the floor only the low arm carries transponders.
HIGH_ARM_IF_FLOOR_KHZ = 1_100_000

#: Target-slot protection band width (SPEC-620 §7 rule 3 leaves the width
#: to the implementation ticket; frozen 3 MHz, aligned with the appendix A
#: ±3 MHz LO-drift reference; pinned by the tuner vectors).
PROTECTION_BAND_WIDTH_KHZ = 3_000

#: Port-select bit mask inside the committed register (2 bits → the 4-way
#: committed port face, SPEC-622 §5 template budget 4) and the nibble
#: shift for high-nibble writes.
PORT_SELECT_MASK = 0x03
REGISTER_NIBBLE_SHIFT = 4
