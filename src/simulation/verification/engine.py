"""SPEC-206 — the three-state recovery verification engine (ticket #56).

The PURE evaluation core (§1: 修复后的新 Run 证据判定；§4 verdict
semantics; §6 观测语义区分; §7 six-kind closed enum + the #59 fault_inactive
three-segment chain). The engine consumes journal-shaped records — fault.*
lifecycle facts and normalized ``ts.*`` observations — handed in by the
caller (the :mod:`simulation.verification.service` journal reader, or a
test); it never reads a wall clock, never uses randomness and never
re-parses the bitstream (§7: 判据评估复用 Observation/诊断输出).

Import-contract note (C8): this package imports ``simulation.scenario``
(the pass_criteria closed enum — same package edge) and NOTHING from
``domain.diagnosis``. Verdict evidence references diagnosis-side facts by
ID/journal_seq only (the injection read face), per the ticket #56 裁定.

Three-state aggregation (§4): PASS requires every mandatory criterion to
PASS; any mandatory FAIL ⇒ FAIL; any mandatory NOT_EVALUATED (with the rest
PASSing) ⇒ INCONCLUSIVE. Non-mandatory criteria are reported but never
gate the verdict. FAIL takes precedence over INCONCLUSIVE.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from simulation.errors import (
    SIM_VERIF_BASELINE_REUSED,
    SIM_VERIF_EVIDENCE_MISSING,
    VerificationCriterionInvalidError,
)
from simulation.scenario.schema import SCENARIO_CRITERION_KINDS

__all__ = [
    "CRITERION_RESULT_FAIL",
    "CRITERION_RESULT_NOT_EVALUATED",
    "CRITERION_RESULT_PASS",
    "CriterionResult",
    "EvaluationInput",
    "FaultEventRecord",
    "ObservationRecord",
    "REASON_EVIDENCE_MISSING",
    "RESULT_FAIL",
    "RESULT_NOT_EVALUATED",
    "RESULT_PASS",
    "VERDICT_FAIL",
    "VERDICT_INCONCLUSIVE",
    "VERDICT_PASS",
    "VERIFICATION_CRITERION_KINDS",
    "VerificationOutcome",
    "evaluate",
]

#: §4 three-state verdict.
VERDICT_PASS = "PASS"
VERDICT_FAIL = "FAIL"
VERDICT_INCONCLUSIVE = "INCONCLUSIVE"

#: §4 per-criterion results.
CRITERION_RESULT_PASS = "PASS"
CRITERION_RESULT_FAIL = "FAIL"
CRITERION_RESULT_NOT_EVALUATED = "NOT_EVALUATED"

#: Aliases kept next to the verdict vocabulary for import symmetry.
RESULT_PASS = CRITERION_RESULT_PASS
RESULT_FAIL = CRITERION_RESULT_FAIL
RESULT_NOT_EVALUATED = CRITERION_RESULT_NOT_EVALUATED

#: The NOT_EVALUATED reason code (SPEC-206 §8: mandatory evidence missing).
#: The fault_inactive applicability boundary (#59): baseline side only.
REASON_EVIDENCE_MISSING = SIM_VERIF_EVIDENCE_MISSING

#: The §7 MVP criterion kind closed enum (single source: the SPEC-205 §4
#: loader declaration the scenario engine already enforces at load time).
VERIFICATION_CRITERION_KINDS = SCENARIO_CRITERION_KINDS

_INJECTED = "fault.injected"
_ACTIVATED = "fault.activated"
_APPLIED = "fault.applied"
_CLEARED = "fault.cleared"

#: The #59 baseline anchor states (``fault.applied`` is L1-only and may be
#: omitted in state-level scenarios — SPEC-204 §8.1).
_ANCHOR_STATES = (_INJECTED, _ACTIVATED, _CLEARED)

_RECURRENCE_STATES = (_ACTIVATED, _APPLIED)

_CC_ERROR_EVENT = "ts.continuity_error"
_PSI_EVENT = "ts.psi_section_observed"
_BATCH_EVENT = "ts.packet_batch_observed"


# --- journal-read record shapes ---------------------------------------------------


@dataclass(frozen=True)
class FaultEventRecord:
    """One ``fault.*`` lifecycle fact (structural evidence, §6 指针句).

    The service reads these from the journal with ``scope.run_id``
    attribution; ``payload`` carries the SPEC-204 §9 registered shape.
    """

    journal_seq: int
    event_type: str
    fault_id: str
    fault_type: str
    node_id: str | None
    pid: int | None
    run_id: str
    payload: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ObservationRecord:
    """One normalized ``ts.*`` observation (the G3 fixture contract; the
    #58 analysis bridge supplies the same shape end to end — the engine is
    unchanged by that swap, SPEC-206 §11 解耦条款)."""

    journal_seq: int
    event_type: str
    payload: Mapping[str, Any]
    node_id: str | None
    pid: int | None
    run_id: str


@dataclass(frozen=True)
class EvaluationInput:
    """§3 判定输入, projected onto journal-read faces.

    ``pass_criteria`` entries are SPEC-205 §3 declarations (attribute or
    mapping form: criterion_id / kind / mandatory / fault_id). ``ui_state``
    is accepted and deliberately NEVER consulted — UI state is not evidence
    (REQ-SIM-206-001 / AC-206-01); the field exists so callers can hand the
    engine whatever they like and the verdict provably cannot move.
    """

    session_id: str
    baseline_run_id: str
    recovery_run_id: str
    scenario_id: str
    scenario_version: str
    scenario_content_hash: str
    pass_criteria: Sequence[Any]
    baseline_fault_events: Sequence[FaultEventRecord] = ()
    recovery_fault_events: Sequence[FaultEventRecord] = ()
    recovery_observations: Sequence[ObservationRecord] = ()
    recovery_run_completed: bool = False
    ui_state: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class CriterionResult:
    """§4 per-criterion result (PASS/FAIL/NOT_EVALUATED + reason)."""

    criterion_id: str
    kind: str
    mandatory: bool
    result: str
    reason_code: str | None = None
    reason: str | None = None
    evidence_refs: tuple[Mapping[str, Any], ...] = ()


@dataclass(frozen=True)
class VerificationOutcome:
    """§4 判定结果 (the deterministic projection; the operational
    verification timestamp is injected by the service, never sourced here —
    REQ-SIM-206-005)."""

    verdict: str
    criteria: tuple[CriterionResult, ...]
    evidence_refs: tuple[Mapping[str, Any], ...]
    summary: str


# --- public entry -------------------------------------------------------------------


def evaluate(spec: EvaluationInput) -> VerificationOutcome:
    """Evaluate one recovery attempt against the scenario pass criteria.

    Pure and deterministic: identical ``spec`` ⇒ identical outcome (the
    only non-deterministic field of the full pipeline, ``verified_at``,
    lives upstream). Unknown criterion kinds / malformed ``fault_inactive``
    declarations raise :class:`VerificationCriterionInvalidError`
    (SIM_VERIF_CRITERION_INVALID, §8 row 1 — 拒绝判定).
    """
    criteria = [_criterion_fields(entry) for entry in spec.pass_criteria]

    if spec.recovery_run_id == spec.baseline_run_id:
        # §5 item 4 / §8 row 4: the candidate IS the baseline — a run
        # cannot prove its own repair. INCONCLUSIVE with the explicit
        # reason (REQ-SIM-206-004 distinguishability check).
        return VerificationOutcome(
            verdict=VERDICT_INCONCLUSIVE,
            criteria=tuple(
                CriterionResult(
                    criterion_id=criterion_id,
                    kind=kind,
                    mandatory=mandatory,
                    result=CRITERION_RESULT_NOT_EVALUATED,
                    reason_code=SIM_VERIF_BASELINE_REUSED,
                    reason=(
                        f"candidate run {spec.recovery_run_id} is the"
                        " baseline run itself (SPEC-206 §8:"
                        " SIM_VERIF_BASELINE_REUSED)"
                    ),
                )
                for criterion_id, kind, mandatory, _fault_id in criteria
            ),
            evidence_refs=(),
            summary=(
                "candidate run equals the baseline run — verification is"
                " INCONCLUSIVE by definition (SPEC-206 §5 item 4)"
            ),
        )

    baseline_by_fault = _group_baseline(spec.baseline_fault_events)
    recovery_injected = {
        event.fault_id
        for event in spec.recovery_fault_events
        if event.event_type == _INJECTED
    }
    expected_cc_declared = any(
        _CC_ERROR_EVENT in (event.payload or {}).get("expected_observations", ())
        for event in spec.baseline_fault_events
        if event.event_type == _INJECTED
    )

    results = []
    if not spec.recovery_run_completed:
        # §8 (via #59): 候选恢复 Run 未完成走 §4 mandatory 证据缺失既有规则 —
        # every criterion is honestly NOT_EVALUATED; the verdict is
        # INCONCLUSIVE, never a fabricated PASS/FAIL.
        for criterion_id, kind, mandatory, _fault_id in criteria:
            results.append(
                CriterionResult(
                    criterion_id=criterion_id,
                    kind=kind,
                    mandatory=mandatory,
                    result=CRITERION_RESULT_NOT_EVALUATED,
                    reason_code=REASON_EVIDENCE_MISSING,
                    reason=(
                        f"recovery run {spec.recovery_run_id} has not"
                        " completed (criterion evaluation depends on the"
                        " run's terminal evidence; SPEC-206 §8)"
                    ),
                )
            )
    else:
        for criterion_id, kind, mandatory, fault_id in criteria:
            results.append(
                _evaluate_criterion(
                    spec,
                    criterion_id,
                    kind,
                    mandatory,
                    fault_id,
                    baseline_by_fault,
                    recovery_injected,
                    expected_cc_declared,
                )
            )

    return VerificationOutcome(
        verdict=_aggregate(results),
        criteria=tuple(results),
        evidence_refs=tuple(
            ref for result in results for ref in result.evidence_refs
        ),
        summary=_summary(results),
    )


# --- criterion dispatch -----------------------------------------------------------


def _criterion_fields(entry: Any) -> tuple[str, str, bool, str | None]:
    """Normalize a SPEC-205 §3 criterion declaration (mapping or attribute).

    Unknown kinds and a ``fault_inactive`` without its ``fault_id`` are
    rejected outright (SIM_VERIF_CRITERION_INVALID — the §7 closed enum).
    """
    if isinstance(entry, Mapping):
        getter = entry.get
    else:
        getter = lambda name, default=None: getattr(entry, name, default)  # noqa: E731
    criterion_id = getter("criterion_id")
    kind = getter("kind")
    mandatory = getter("mandatory", True)
    fault_id = getter("fault_id")
    if not isinstance(criterion_id, str) or not criterion_id:
        raise VerificationCriterionInvalidError(
            "pass criterion is missing a non-empty criterion_id"
        )
    if kind not in VERIFICATION_CRITERION_KINDS:
        raise VerificationCriterionInvalidError(
            f"pass criterion {criterion_id!r} references unknown criterion"
            f" kind {kind!r} (SPEC-206 §7 MVP closed enum: "
            f"{sorted(VERIFICATION_CRITERION_KINDS)})"
        )
    if not isinstance(mandatory, bool):
        raise VerificationCriterionInvalidError(
            f"pass criterion {criterion_id!r} carries a non-boolean"
            f" mandatory flag ({mandatory!r})"
        )
    if kind == "fault_inactive" and (
        not isinstance(fault_id, str) or not fault_id
    ):
        raise VerificationCriterionInvalidError(
            f"pass criterion {criterion_id!r} declares kind"
            " 'fault_inactive' without a fault_id (SPEC-206 §7: the"
            " criterion references the scenario fault plan declaration)"
        )
    return criterion_id, kind, mandatory, fault_id


def _evaluate_criterion(
    spec: EvaluationInput,
    criterion_id: str,
    kind: str,
    mandatory: bool,
    fault_id: str | None,
    baseline_by_fault: Mapping[str, Mapping[str, FaultEventRecord]],
    recovery_injected: frozenset[str],
    expected_cc_declared: bool,
) -> CriterionResult:
    if kind == "fault_inactive":
        result, reason_code, reason, refs = _evaluate_fault_inactive(
            spec, fault_id or "", baseline_by_fault, recovery_injected
        )
    elif kind == "psi_pat_valid":
        result, reason_code, reason, refs = _evaluate_psi_valid(
            spec.recovery_observations, "PAT"
        )
    elif kind == "psi_pmt_valid":
        result, reason_code, reason, refs = _evaluate_psi_valid(
            spec.recovery_observations, "PMT"
        )
    elif kind == "pat_pmt_mapping_valid":
        result, reason_code, reason, refs = _evaluate_mapping(
            spec.recovery_observations
        )
    elif kind == "cc_continuous":
        result, reason_code, reason, refs = _evaluate_cc_continuous(
            spec.recovery_observations
        )
    else:  # no_unexpected_cc_error
        result, reason_code, reason, refs = _evaluate_no_unexpected_cc(
            spec.recovery_observations, expected_cc_declared
        )
    return CriterionResult(
        criterion_id=criterion_id,
        kind=kind,
        mandatory=mandatory,
        result=result,
        reason_code=reason_code,
        reason=reason,
        evidence_refs=refs,
    )


# --- fault_inactive (#59 three-segment chain) ---------------------------------------


def _evaluate_fault_inactive(
    spec: EvaluationInput,
    fault_id: str,
    baseline_by_fault: Mapping[str, Mapping[str, FaultEventRecord]],
    recovery_injected: frozenset[str],
) -> tuple[str, str | None, str | None, tuple[Mapping[str, Any], ...]]:
    anchor = baseline_by_fault.get(fault_id, {})
    anchor_refs = _journal_refs(
        [anchor[state] for state in _ANCHOR_STATES if state in anchor]
    )
    missing = [state for state in _ANCHOR_STATES if state not in anchor]
    if missing:
        # SIM_VERIF_EVIDENCE_MISSING applicability boundary (#59): for this
        # criterion evidence can ONLY be missing on the baseline side.
        return (
            CRITERION_RESULT_NOT_EVALUATED,
            REASON_EVIDENCE_MISSING,
            f"baseline lifecycle incomplete for fault {fault_id}: missing"
            f" {', '.join(missing)} (the fault was never proven planted on"
            f" run {spec.baseline_run_id}; SPEC-206 §7 segment 1)",
            anchor_refs,
        )
    declared = next(
        (event for event in spec.recovery_fault_events if event.fault_id == fault_id and event.event_type == _INJECTED),
        None,
    )
    if declared is not None:
        return (
            CRITERION_RESULT_FAIL,
            None,
            f"recovery prepared plan still declares fault {fault_id}"
            f" (fault.injected present on run {spec.recovery_run_id};"
            " SPEC-206 §7 segment 2)",
            (declared_ref(declared),),
        )
    recurrence = sorted(
        (
            event
            for event in spec.recovery_fault_events
            if event.fault_id == fault_id and event.event_type in _RECURRENCE_STATES
        ),
        key=lambda event: event.journal_seq,
    )
    if recurrence:
        return (
            CRITERION_RESULT_FAIL,
            None,
            f"undeclared recurrence of fault {fault_id} on the recovery run"
            " (fault.activated/fault.applied present without a prepared"
            " plan declaration — engine violation; SPEC-206 §7 segment 3)",
            _journal_refs(recurrence),
        )
    # Constructive absence (NOT observation absence — §6 指针句 / #59): the
    # prepare-validated plan binding emits one fault.injected per planned
    # fault at run open, so the absence of any fault.* event for this
    # fault_id IS the plan-exclusion declaration.
    absence = {
        "kind": "journal_absence",
        "run_id": spec.recovery_run_id,
        "checked_event_types": [_INJECTED, _ACTIVATED, _APPLIED],
        "detail": (
            "recovery prepared plan excludes the fault (no fault.injected)"
            " and the journal carries no recurrence — constructive segment"
            " 2+3 evidence"
        ),
    }
    return (
        CRITERION_RESULT_PASS,
        None,
        None,
        anchor_refs + (absence,),
    )


def declared_ref(event: FaultEventRecord) -> Mapping[str, Any]:
    return {
        "kind": "journal",
        "journal_seq": event.journal_seq,
        "event_type": event.event_type,
        "run_id": event.run_id,
    }


def _group_baseline(
    events: Sequence[FaultEventRecord],
) -> dict[str, dict[str, FaultEventRecord]]:
    grouped: dict[str, dict[str, FaultEventRecord]] = {}
    for event in events:
        by_state = grouped.setdefault(event.fault_id, {})
        # First fact per state wins (journal order = the caller's page walk).
        by_state.setdefault(event.event_type, event)
    return grouped


def _journal_refs(
    events: Sequence[FaultEventRecord],
) -> tuple[Mapping[str, Any], ...]:
    return tuple(declared_ref(event) for event in events)


# --- observation-side criteria -----------------------------------------------------


def _psi_records(
    observations: Sequence[ObservationRecord], section: str
) -> list[ObservationRecord]:
    return [
        record
        for record in observations
        if record.event_type == _PSI_EVENT
        and (record.payload or {}).get("section") == section
    ]


def _ref(record: ObservationRecord, note: str | None = None) -> Mapping[str, Any]:
    ref: dict[str, Any] = {
        "kind": "journal",
        "journal_seq": record.journal_seq,
        "event_type": record.event_type,
        "run_id": record.run_id,
    }
    if note:
        ref["detail"] = note
    return ref


def _not_evaluated(
    reason: str, refs: tuple[Mapping[str, Any], ...] = ()
) -> tuple[str, str | None, str | None, tuple[Mapping[str, Any], ...]]:
    return CRITERION_RESULT_NOT_EVALUATED, REASON_EVIDENCE_MISSING, reason, refs


def _evaluate_psi_valid(
    observations: Sequence[ObservationRecord], section: str
) -> tuple[str, str | None, str | None, tuple[Mapping[str, Any], ...]]:
    """``psi_pat_valid`` / ``psi_pmt_valid``.

    Dual 1: zero records ⇒ NOT_EVALUATED (无观测 ≠ 干净). Dual 2: records
    without the ``present`` capability field are unusable (analyzer
    unsupported), never a violation; an explicit ``present=False`` or
    ``crc_valid=False`` IS the protocol violation fact.
    """
    records = _psi_records(observations, section)
    if not records:
        return _not_evaluated(
            f"no {section} observations on the recovery run (无观测 ≠ 干净"
            " — absence cannot confirm validity; SPEC-206 §6)"
        )
    usable = [
        record
        for record in records
        if isinstance((record.payload or {}).get("present"), bool)
    ]
    if not usable:
        return _not_evaluated(
            f"{len(records)} {section} observation(s) carry neither the"
            " 'present' nor 'crc_valid' capability field (analyzer"
            " unsupported — NOT a protocol violation; SPEC-206 §6)",
            tuple(_ref(record) for record in records),
        )
    violations = [
        record
        for record in usable
        if (record.payload or {}).get("present") is False
        or (record.payload or {}).get("crc_valid") is False
    ]
    if violations:
        return (
            CRITERION_RESULT_FAIL,
            None,
            f"{section} protocol violation observed (present/crc_valid"
            f" explicitly false on {len(violations)} of {len(usable)}"
            f" usable observations)",
            tuple(_ref(record, "explicit violation fact") for record in violations),
        )
    return (
        CRITERION_RESULT_PASS,
        None,
        None,
        tuple(_ref(record) for record in usable),
    )


def _evaluate_mapping(
    observations: Sequence[ObservationRecord],
) -> tuple[str, str | None, str | None, tuple[Mapping[str, Any], ...]]:
    """``pat_pmt_mapping_valid``: PAT declarations ↔ observed PMT placement.

    Dual 3: a PAT without ``actual_program_map_pid`` is unknown; an
    explicit ``0`` is a fact (PAT cannot declare itself → invalid). The
    declared PMT being entirely unobserved is NOT_EVALUATED (无观测 ≠ 干净);
    PMT observations contradicting the declaration are the violation.
    """
    pat = _psi_records(observations, "PAT")
    usable_pat = [
        record
        for record in pat
        if isinstance((record.payload or {}).get("actual_program_map_pid"), int)
    ]
    if not usable_pat:
        return _not_evaluated(
            "no PAT observations carrying a declared program_map_pid"
            " (mapping cannot be evaluated without the declaration fact)"
        )
    refs_declared = tuple(_ref(record) for record in usable_pat)
    declared = sorted(
        {record.payload["actual_program_map_pid"] for record in usable_pat}
    )
    # Declaration-internal facts first (they hold regardless of what PMT
    # observations exist): an explicit zero is a FACT — PAT cannot declare
    # itself (缺失值 vs 零值 dual, SPEC-206 §6); a repoint is the mismatch
    # symptom recorded in the observation itself.
    if 0 in declared:
        return (
            CRITERION_RESULT_FAIL,
            None,
            "PAT declares program_map_pid 0 — an explicitly invalid mapping"
            " (PAT cannot declare itself; 零值 is a fact, SPEC-206 §6)",
            refs_declared,
        )
    for record in usable_pat:
        expected = (record.payload or {}).get("expected_program_map_pid")
        actual = record.payload["actual_program_map_pid"]
        if isinstance(expected, int) and expected != actual:
            return (
                CRITERION_RESULT_FAIL,
                None,
                "PAT repointed at program_map_pid "
                f"{actual} while the stream declares {expected}"
                " (repoint detection)",
                refs_declared,
            )
    pmt = _psi_records(observations, "PMT")
    if not pmt:
        return _not_evaluated(
            "PAT declarations observed but no PMT observations at all"
            " (无观测 ≠ 干净 — the mapping is unconfirmed, not violated)",
            refs_declared,
        )
    refs = tuple(_ref(record) for record in usable_pat + pmt)
    observed_pids = sorted(
        {
            record.pid if record.pid is not None else (record.payload or {}).get("pid")
            for record in pmt
        }
    )
    missing = [pid for pid in declared if pid not in observed_pids]
    if missing:
        return (
            CRITERION_RESULT_FAIL,
            None,
            f"declared PMT pid(s) {missing} not observed while PMT"
            f" sections sit on {observed_pids} (observed mapping"
            " contradicts the declaration)",
            refs,
        )
    orphans = [pid for pid in observed_pids if pid not in declared]
    if orphans:
        return (
            CRITERION_RESULT_FAIL,
            None,
            f"PMT observed on undeclared pid(s) {orphans} (orphan PMT)",
            refs,
        )
    return CRITERION_RESULT_PASS, None, None, refs


def _cc_facts(
    observations: Sequence[ObservationRecord],
) -> tuple[list[ObservationRecord], list[ObservationRecord], list[ObservationRecord]]:
    """(error records, counted batches, coverage batches)."""
    errors = [
        record for record in observations if record.event_type == _CC_ERROR_EVENT
    ]
    counted = [
        record
        for record in observations
        if record.event_type == _BATCH_EVENT
        and isinstance((record.payload or {}).get("continuity_error_count"), int)
        and record.payload["continuity_error_count"] > 0
    ]
    coverage = [
        record
        for record in observations
        if record.event_type == _BATCH_EVENT
        and isinstance((record.payload or {}).get("packet_count"), int)
        and record.payload["packet_count"] > 0
    ]
    return errors, counted, coverage


def _evaluate_cc_continuous(
    observations: Sequence[ObservationRecord],
) -> tuple[str, str | None, str | None, tuple[Mapping[str, Any], ...]]:
    """``cc_continuous``: any discontinuity fact breaks continuity.

    Dual 1: no stream coverage ⇒ NOT_EVALUATED. A violation fact (a
    per-error record, or a batch explicitly counting > 0) is FAIL even
    without coverage facts. 修复后从恢复点重算期望 CC（§7）: the engine does
    NOT re-derive expected CC values — the normalized continuity_error
    record IS the discontinuity fact.
    """
    errors, counted, coverage = _cc_facts(observations)
    violations = errors + counted
    if violations:
        return (
            CRITERION_RESULT_FAIL,
            None,
            f"{len(violations)} CC discontinuity fact(s) on the recovery"
            " stream",
            tuple(_ref(record, "CC discontinuity fact") for record in violations),
        )
    if not coverage:
        return _not_evaluated(
            "no TS stream coverage observed (无观测 ≠ 干净 — without"
            " observed packets continuity cannot be confirmed)"
        )
    return (
        CRITERION_RESULT_PASS,
        None,
        None,
        tuple(_ref(record, "observed stream coverage") for record in coverage),
    )


def _evaluate_no_unexpected_cc(
    observations: Sequence[ObservationRecord],
    expected_declared: bool,
) -> tuple[str, str | None, str | None, tuple[Mapping[str, Any], ...]]:
    """``no_unexpected_cc_error``: declared expectations vs uncovered facts.

    Dual 4: a CC error covered by the baseline plan's declared
    ``expected_observations`` vocabulary does not violate THIS criterion
    (it still fails ``cc_continuous``); an uncovered error fails both.
    """
    errors, counted, coverage = _cc_facts(observations)
    violations = errors + counted
    if not violations:
        if not coverage:
            return _not_evaluated(
                "no TS stream coverage observed (无观测 ≠ 干净)"
            )
        return (
            CRITERION_RESULT_PASS,
            None,
            None,
            tuple(_ref(record, "observed stream coverage") for record in coverage),
        )
    if not expected_declared:
        return (
            CRITERION_RESULT_FAIL,
            None,
            "unexpected CC error(s) on the recovery stream — no declared"
            " expected_observations cover ts.continuity_error"
            " (SPEC-206 §6 预期/意外对偶)",
            tuple(_ref(record, "unexpected CC error") for record in violations),
        )
    return (
        CRITERION_RESULT_PASS,
        None,
        None,
        tuple(
            _ref(record, "CC error covered by the declared expectations")
            for record in violations
        ),
    )


# --- aggregation -------------------------------------------------------------------


def _aggregate(results: Sequence[CriterionResult]) -> str:
    """§4: mandatory FAIL ⇒ FAIL; mandatory missing ⇒ INCONCLUSIVE; else
    PASS (non-mandatory criteria never gate)."""
    mandatory = [result for result in results if result.mandatory]
    if any(result.result == CRITERION_RESULT_FAIL for result in mandatory):
        return VERDICT_FAIL
    if any(
        result.result == CRITERION_RESULT_NOT_EVALUATED for result in mandatory
    ):
        return VERDICT_INCONCLUSIVE
    return VERDICT_PASS


def _summary(results: Sequence[CriterionResult]) -> str:
    mandatory = [result for result in results if result.mandatory]
    total = len(mandatory)
    passed = sum(1 for result in mandatory if result.result == CRITERION_RESULT_PASS)
    failed = [
        result.criterion_id
        for result in mandatory
        if result.result == CRITERION_RESULT_FAIL
    ]
    unevaluated = [
        result.criterion_id
        for result in mandatory
        if result.result == CRITERION_RESULT_NOT_EVALUATED
    ]
    if failed:
        return (
            f"{passed}/{total} mandatory criteria passed; FAILED: "
            f"{', '.join(failed)}"
        )
    if unevaluated:
        return (
            f"{passed}/{total} mandatory criteria passed; evidence missing"
            f" (INCONCLUSIVE): {', '.join(unevaluated)}"
        )
    return f"{total}/{total} mandatory criteria passed"
