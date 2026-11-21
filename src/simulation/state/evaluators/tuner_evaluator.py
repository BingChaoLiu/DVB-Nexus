"""SPEC-620 §6/§7/§8 — the tuner lock + ber pure functions + evaluator (#161).

Seam: ``simulation.state.evaluators.tuner_evaluator`` — registered under
the ``"tuner"`` node-type wire string via :func:`evaluate_topology`'s
injection mapping (:data:`simulation.state.evaluators.DEFAULT_EVALUATORS`).

Pure-function core (house "pure core + dataclass shell" style):

- :func:`expected_band` — the dial frequency's universal band label
  against the SPEC-621 appendix A boundary (11700000 kHz, reused from
  ``simulation.state.unicable``).
- :func:`delivered_arm` — which LO arm the upstream's ``lo_delivered``
  sits on (plan equality); ``None`` = foreign LO.
- :func:`slot_floor` — the delivered arm's IF floor: 950000 kHz (low) /
  1100000 kHz (high) — the high floor is SPEC-620 §3's overlap
  arithmetic (high band RF 11700 − LO 10600 MHz); the overlap region
  1100–1950 MHz is exactly where wrong-lock lives.
- :func:`in_protection_band` — the target slot's edge neighbourhood,
  frozen width 3000 kHz (SPEC-620 §7 rule 3 delegates the width to the
  implementation ticket; aligned with the appendix A ±3 MHz LO-drift
  reference; pinned by the tuner vectors).
- :func:`evaluate_lock` — the §6 lock pure function, the four §7 branches
  in frozen order (see the module docstring of the shell below).

The IF-slot model (REPORT-frozen, full derivation in the vector module):

- ``if_frequency_khz`` = ``|tuning_frequency − lo_delivered|`` — the §5
  formula verbatim, reported even when unlocked (``None`` only when no
  carrier is delivered at all).
- The tuner's IF-section dial: ``tuned_if = tuning_frequency −
  lo_expected`` (the LO plan entry of the dial's band).  A transponder
  slot exists on the delivered arm iff ``tuned_if`` lies in
  ``[arm_floor, 1950000]`` kHz.
- Lock at ``rf_locked = tuned_if + lo_delivered``: equal to the dial =
  target lock; different = 错锁 (the ±850 MHz neighbour sharing the IF
  slot — the AC-620-03 composite fact).  ``locked_transponder_id``:
  ``f"{band}@{rf_locked_khz}"`` on the LO path, ``f"ub:{slot}:{center}"``
  on the SCR path.

Frozen branch order (§7 four branches + §8 rows reconciled):

0. missing/malformed ``tuning_request`` → idle degrade (prepare face is
   #163/#165; no raise — walk isolation stays for evaluator faults);
1. no feeder or feeder idle → idle propagation (§8 topology-break row);
2. UB conflict (runtime judgement exclusively via #162's
   :func:`simulation.state.unicable.ub_conflicts`, ruling A13) → unlocked
   + CauseRef per conflict peer;
3. no carrier (``lo_delivered`` null/foreign-to-plan) → unlocked;
4. polarization mismatch (universal path only — the SCR tuning message
   carries the polarization bit, so the SCR path skips this gate) →
   unlocked (§8: the locked precondition fails);
5. slot determination → unlocked (no slot) / locked (target or 错锁).

ber rule table (§7, REPORT-frozen readings — full rationale in the
vector module): severe fires on any anomaly field (tone mismatch /
short-circuit non-normal / UB-conflict cause / anomalous feeder health)
regardless of slot position (rule 2's "且 IF 仍落在某槽位" qualifier
frozen as non-required so the §11.1 A2 narrative "unlocked 或错锁 +
severe" holds on the unlocked branch); elevated = the target slot's
protection band; normal = in-slot interior with a clean chain; unlocked
without anomaly → no grade (rule 4).  ``stale`` is ``true`` on every
unlocked snapshot (§8); locked snapshots carry ``false``.  The §8
"retain last decidable value" option is realised purity-safe: the severe
grade derivable from the *current* inputs survives unlocking, everything
else grades null.
"""

from __future__ import annotations

from dataclasses import dataclass

from simulation.state.evaluate import (
    CauseRef,
    EvalContext,
    Health,
    NodeEvalResult,
    PortState,
)
from simulation.state.evaluators._vocab import (
    BAND_BOUNDARY_KHZ,
    HIGH_ARM_IF_FLOOR_KHZ,
    IF_SLOT_HIGH_KHZ,
    IF_SLOT_LOW_KHZ,
    OWN_NODE_ID_CONFIG_KEY,
    POLARIZATIONS,
    PROTECTION_BAND_WIDTH_KHZ,
    SCR_PROTOCOLS,
    UB_SLOT_CONFIG_KEY,
)
from simulation.state.graph import NodeConfig
from simulation.state.unicable import (
    FREQUENCY_KHZ_CONFIG_KEY,
    POLARIZATION_CONFIG_KEY,
    UB_CENTER_FREQ_CONFIG_KEY,
    ub_conflicts,
)

__all__ = [
    "LockOutcome",
    "TunerEvaluator",
    "delivered_arm",
    "evaluate_lock",
    "expected_band",
    "in_protection_band",
    "slot_floor",
]


def expected_band(frequency_khz: int) -> str:
    """The dial frequency's universal band label (appendix A boundary)."""
    return "high" if frequency_khz >= BAND_BOUNDARY_KHZ else "low"


def delivered_arm(
    lo_delivered: int | None,
    lo_plan_low_khz: int,
    lo_plan_high_khz: int,
) -> str | None:
    """Which LO arm the delivered oscillator sits on (plan equality).

    ``None`` = foreign LO (not on any arm — defensively unlocked).  The
    legacy single-LO case collapses onto the low plan value.
    """
    if lo_delivered == lo_plan_low_khz:
        return "low"
    if lo_delivered == lo_plan_high_khz:
        return "high"
    return None


def slot_floor(arm: str) -> int:
    """The delivered arm's IF floor (kHz): SPEC-620 §3 overlap arithmetic."""
    return HIGH_ARM_IF_FLOOR_KHZ if arm == "high" else IF_SLOT_LOW_KHZ


def in_protection_band(tuned_if_khz: int, target_floor_khz: int) -> bool:
    """The tuned IF sits in the target slot's edge neighbourhood
    (frozen width :data:`PROTECTION_BAND_WIDTH_KHZ`, §7 rule 3)."""
    return (
        tuned_if_khz < target_floor_khz + PROTECTION_BAND_WIDTH_KHZ
        or tuned_if_khz > IF_SLOT_HIGH_KHZ - PROTECTION_BAND_WIDTH_KHZ
    )


@dataclass(frozen=True)
class LockOutcome:
    """The §6 lock pure-function product.

    ``causes`` carries the tuner's own causal references (UB-conflict
    peers); the walk threads upstream health chains on top.
    """

    lock_state: str
    if_frequency_khz: int | None
    locked_transponder_id: str | None
    causes: tuple = ()
    ber_state: str | None = None
    stale: bool = True
    health: Health = Health.ERROR


def _is_int(value: object) -> bool:
    """int but not bool (booleans sneak in through JSON wire dicts)."""
    return isinstance(value, int) and not isinstance(value, bool)


def _idle_outcome() -> LockOutcome:
    return LockOutcome(
        lock_state="unlocked",
        if_frequency_khz=None,
        locked_transponder_id=None,
        causes=(),
        ber_state=None,
        stale=True,
        health=Health.IDLE,
    )


def _unlocked_outcome(
    if_frequency_khz: int | None,
    anomaly: bool,
    causes: tuple = (),
) -> LockOutcome:
    return LockOutcome(
        lock_state="unlocked",
        if_frequency_khz=if_frequency_khz,
        locked_transponder_id=None,
        causes=causes,
        ber_state="severe" if anomaly else None,
        stale=True,
        health=Health.ERROR,
    )


def _locked_outcome(
    if_frequency_khz: int,
    locked_transponder_id: str,
    ber_state: str,
    causes: tuple = (),
) -> LockOutcome:
    return LockOutcome(
        lock_state="locked",
        if_frequency_khz=if_frequency_khz,
        locked_transponder_id=locked_transponder_id,
        causes=causes,
        ber_state=ber_state,
        stale=False,
        health={
            "severe": Health.ERROR,
            "elevated": Health.WARN,
            "normal": Health.OK,
        }[ber_state],
    )


def evaluate_lock(
    tuning_request: dict,
    ub_slot: object,
    upstream_metrics: dict,
    feeder_health: Health,
    own_node_id: str,
    upstream_node_id: str | None = None,
) -> LockOutcome:
    """The SPEC-620 §6 lock pure function (four §7 branches + ber table).

    ``upstream_metrics`` is the merged upstream fact dict the walk threads
    through the A2 channel — the SPEC-620 §6 signature's
    ``upstream_lnb_metrics`` / ``upstream_switch_metrics`` pair arrives
    merged (the switch passes the lnb's signal facts through onto its
    output port), so one mapping carries both.  ``feeder_health`` gates
    the idle propagation; it also counts as an anomaly field when
    anomalous (REPORT-frozen rule-2 extension).

    The runtime UB judgement goes exclusively through #162's
    :func:`ub_conflicts` (ruling A13): this tuner's effective claim (its
    config ``ub_slot`` — the value the fault transform left there) is
    checked against the upstream SCR table snapshot; pairs not involving
    this tuner are static facts (the validator's face) and are ignored.
    """
    frequency_khz = tuning_request.get(FREQUENCY_KHZ_CONFIG_KEY)
    polarization = tuning_request.get(POLARIZATION_CONFIG_KEY)
    if (
        not _is_int(frequency_khz)
        or frequency_khz < 1
        or polarization not in POLARIZATIONS
    ):
        return _idle_outcome()

    # Idle propagation first (§8 topology-break row): idle is legal and
    # non-anomalous — nothing about the signal is decidable yet.
    if feeder_health is Health.IDLE:
        return _idle_outcome()

    lo_delivered = upstream_metrics.get("lo_frequency_khz")
    lo_plan_low_khz = upstream_metrics.get("lo_plan_low_khz")
    lo_plan_high_khz = upstream_metrics.get("lo_plan_high_khz")
    lnb_kind = upstream_metrics.get("lnb_kind")
    scr_protocol = upstream_metrics.get("scr_protocol")
    table = upstream_metrics.get("ub_assignments")
    table = [entry for entry in table if isinstance(entry, dict)] if isinstance(table, list) else []

    # Anomaly fields (§7 rule 2, REPORT-frozen list + feeder-health
    # extension): graded regardless of slot position.
    tone_actual = upstream_metrics.get("tone_actual")
    tone_commanded = upstream_metrics.get("tone_commanded")
    tone_anomaly = (
        tone_actual is not None
        and tone_commanded is not None
        and tone_actual != tone_commanded
    )
    short_circuit_state = upstream_metrics.get("short_circuit_state")
    short_anomaly = short_circuit_state is not None and short_circuit_state != "normal"
    feeder_anomalous = feeder_health in (Health.WARN, Health.ERROR)

    # The healthy-but-tone-mismatched upstream (the TONE_RESIDUE chain):
    # the walk threads causes only for anomalous HEALTH, so the tuner
    # self-reports the causal reference to the feeder that carries the
    # tone anomaly (SPEC-307 §Phase3's "CauseRef 指向 lnb" evidence).  The
    # short-circuit axis needs no self-report — that LNB is warn/error and
    # the walk threads it; the feeder identity arrives via the A2
    # ``PortState.upstream_node_id`` field.
    anomaly_causes: tuple = ()
    if tone_anomaly and upstream_node_id:
        anomaly_causes = (CauseRef(node_id=upstream_node_id),)

    slot_valid = _is_int(ub_slot) and ub_slot >= 0
    scr_context = slot_valid and scr_protocol in SCR_PROTOCOLS

    # Branch 2 — runtime UB conflict (A13: exclusively via ub_conflicts).
    causes: tuple = ()
    ub_conflict = False
    slot_entry: dict | None = None
    if scr_context:
        protocol_entries = [
            {**{key: value for key, value in entry.items() if key != "protocol"},
             "protocol": scr_protocol}
            for entry in table
        ]
        own_claim = {
            OWN_NODE_ID_CONFIG_KEY: own_node_id,
            UB_SLOT_CONFIG_KEY: ub_slot,
            "protocol": scr_protocol,
        }
        conflicts = ub_conflicts(protocol_entries, [own_claim])
        own_conflicts = [
            (tuner_a, tuner_b, slot)
            for tuner_a, tuner_b, slot in conflicts
            if own_node_id in (tuner_a, tuner_b)
        ]
        if own_conflicts:
            ub_conflict = True
            causes = tuple(
                CauseRef(node_id=tuner_b if tuner_a == own_node_id else tuner_a)
                for tuner_a, tuner_b, _slot in own_conflicts
            )
            causes = causes + anomaly_causes
        else:
            slot_entry = next(
                (entry for entry in table if entry.get(UB_SLOT_CONFIG_KEY) == ub_slot),
                None,
            )

    anomaly = tone_anomaly or short_anomaly or feeder_anomalous or ub_conflict

    if ub_conflict:
        # Branch 2: unlocked + CauseRef conflict pair; the IF fact is the
        # effective slot's carrier when the claim matches a table row.
        if_metric = None
        if slot_entry is None:
            slot_entry = next(
                (entry for entry in table if entry.get(UB_SLOT_CONFIG_KEY) == ub_slot),
                None,
            )
        center_mhz = slot_entry.get(UB_CENTER_FREQ_CONFIG_KEY) if slot_entry else None
        if _is_int(center_mhz):
            if_metric = center_mhz * 1000
        return _unlocked_outcome(if_metric, anomaly=True, causes=causes)

    # Branch 3 — no carrier: unpowered LNB or no LO fact at all.
    if not _is_int(lo_delivered):
        return _unlocked_outcome(None, anomaly, causes=anomaly_causes)

    if scr_context:
        # SCR path: the UB carrier is the transponder slot (config-validated
        # widths/centres); an unmatched claim cannot establish the channel.
        if slot_entry is None:
            return _unlocked_outcome(None, anomaly, causes=anomaly_causes)
        center_mhz = slot_entry.get(UB_CENTER_FREQ_CONFIG_KEY)
        if not _is_int(center_mhz):
            return _unlocked_outcome(None, anomaly, causes=anomaly_causes)
        ber = "severe" if anomaly else "normal"  # no slot edges on the SCR path
        return _locked_outcome(
            center_mhz * 1000,
            f"ub:{ub_slot}:{center_mhz}",
            ber,
            causes=anomaly_causes,
        )

    # Polarization mismatch (§8): the locked precondition fails — the
    # SCR path above intentionally skips this gate.
    polarization_delivered = upstream_metrics.get("polarization_delivered")
    if polarization_delivered is not None and polarization_delivered != polarization:
        return _unlocked_outcome(
            abs(frequency_khz - lo_delivered), anomaly, causes=anomaly_causes
        )

    # Branches 1/3/4 — the LO-path slot determination.  The LO plan must
    # be visible to derive the expected oscillator.
    if not _is_int(lo_plan_low_khz) or not _is_int(lo_plan_high_khz):
        return _unlocked_outcome(
            abs(frequency_khz - lo_delivered), anomaly, causes=anomaly_causes
        )

    target_band = expected_band(frequency_khz)
    legacy = lnb_kind == "legacy_cascade"
    if legacy:
        # §7 legacy simplified semantics: single LO (the plan's low value);
        # the band label derives from the tuning frequency directly.
        if lo_delivered != lo_plan_low_khz:
            return _unlocked_outcome(
            abs(frequency_khz - lo_delivered), anomaly, causes=anomaly_causes
        )
        arm = "low"
        id_band = target_band
    else:
        arm = delivered_arm(lo_delivered, lo_plan_low_khz, lo_plan_high_khz)
        if arm is None:
            # Foreign LO: not on any plan arm — defensively unlocked.
            return _unlocked_outcome(
            abs(frequency_khz - lo_delivered), anomaly, causes=anomaly_causes
        )
        id_band = arm

    lo_expected = lo_plan_high_khz if (not legacy and target_band == "high") else lo_plan_low_khz
    tuned_if = frequency_khz - lo_expected
    if_metric = abs(frequency_khz - lo_delivered)

    if not slot_floor(arm) <= tuned_if <= IF_SLOT_HIGH_KHZ:
        # Branch 3 — no slot on the delivered arm (or beyond the appendix A
        # normative window).
        return _unlocked_outcome(if_metric, anomaly, causes=anomaly_causes)

    rf_locked = tuned_if + lo_delivered
    # The wrong-lock composite fact (AC-620-03) is carried by the identity
    # itself: locked_id ≠ f"{target_band}@{frequency_khz}" marks the 错锁
    # material SPEC-307 consumes (no separate state, §7).
    locked_id = f"{id_band}@{rf_locked}"

    # ber for the locked state: anomaly → severe (rule 2); else the
    # target slot's protection band → elevated (rule 3); else normal.
    if anomaly:
        ber = "severe"
    else:
        target_floor = slot_floor("high" if target_band == "high" else "low")
        ber = "elevated" if in_protection_band(tuned_if, target_floor) else "normal"
    return _locked_outcome(if_metric, locked_id, ber, causes=anomaly_causes)


class TunerEvaluator:
    """The ``tuner`` node evaluator shell (SPEC-202 §6.1 protocol shape).

    The tuner is a leaf: its port states carry health only (no output
    channel to feed).  ``causes`` on the result carry the UB-conflict
    peers; the walk threads the upstream health chain on top.
    """

    def evaluate(
        self,
        node: NodeConfig,
        inputs: dict,
        context: EvalContext,
    ) -> NodeEvalResult:
        config = node.config if isinstance(node.config, dict) else {}

        tuning_request = config.get("tuning_request")
        if not isinstance(tuning_request, dict):
            outcome = _idle_outcome()
        else:
            feeder: PortState | None = None
            for state in inputs.values():
                feeder = state
                break  # the walk's deterministic first feeder
            upstream_metrics = feeder.metrics if feeder is not None else {}
            outcome = evaluate_lock(
                tuning_request,
                config.get(UB_SLOT_CONFIG_KEY),
                upstream_metrics if isinstance(upstream_metrics, dict) else {},
                feeder.health if feeder is not None else Health.IDLE,
                node.node_id,
                upstream_node_id=(
                    feeder.upstream_node_id if feeder is not None else None
                ),
            )

        metrics = {
            "lock_state": outcome.lock_state,
            "if_frequency_khz": outcome.if_frequency_khz,
            "ber_state": outcome.ber_state,
            "locked_transponder_id": outcome.locked_transponder_id,
            "stale": outcome.stale,
        }
        return NodeEvalResult(
            node_id=node.node_id,
            health=outcome.health,
            port_states=tuple(
                PortState(port_id=port.port_id, health=outcome.health)
                for port in node.ports
            ),
            metrics=metrics,
            causes=outcome.causes,
        )
