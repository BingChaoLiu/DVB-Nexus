"""Shared builders for the SPEC-206 verification-engine test slices (#56).

Unit layer: pure objects only — no I/O, no wall clock, no tmp paths. The
records mirror exactly the journal-read faces the service feeds the engine
(fault.* lifecycle records, ``ts.*`` normalized observations, run
boundaries), so the R2 replay-equivalence test (fixture verdict vs real
journal chain) compares like with like.
"""

from __future__ import annotations

from typing import Any, Mapping

from simulation.verification.engine import (
    EvaluationInput,
    FaultEventRecord,
    ObservationRecord,
)

SESSION = "sess-verif"
BASELINE = "run-baseline"
RECOVERY = "run-recovery"
SCENARIO_ID = "9c0f0000-0000-4000-8000-000000000001"
SCENARIO_VERSION = "1.0.0"
SCENARIO_HASH = "1a" * 32

FAULT_ID = "fd000000-0000-4000-8000-000000000001"
NODE = "demux-0"
PSI_PID = 0
CC_PID = 256


def criterion(
    criterion_id: str = "sc-01",
    kind: str = "fault_inactive",
    mandatory: bool = True,
    fault_id: str | None = FAULT_ID,
) -> dict[str, Any]:
    """A SPEC-205 §3 criterion declaration (mapping form — loader shape)."""
    return {
        "criterion_id": criterion_id,
        "kind": kind,
        "mandatory": mandatory,
        "fault_id": fault_id,
    }


def fault_event(
    event_type: str,
    *,
    journal_seq: int,
    fault_id: str = FAULT_ID,
    run_id: str = BASELINE,
    expected_observations: tuple[str, ...] = ("ts.continuity_error",),
    applied: tuple[int, ...] | None = None,
) -> FaultEventRecord:
    """One fault.* lifecycle record as the journal read face returns it."""
    payload: dict[str, Any] = {
        "fault_id": fault_id,
        "fault_type": "CC_DISCONTINUITY",
        "injection_index": 50,
    }
    if event_type == "fault.injected":
        payload["expected_observations"] = list(expected_observations)
    if event_type == "fault.applied":
        payload["applied_packet_indexes"] = list(applied or (50,))
        payload["mutation_log_ref"] = f"artifact-log-{journal_seq}"
    if event_type == "fault.cleared":
        payload["cleared_reason"] = "run_end"
    return FaultEventRecord(
        journal_seq=journal_seq,
        event_type=event_type,
        fault_id=fault_id,
        fault_type=payload["fault_type"],
        node_id=NODE,
        pid=CC_PID,
        run_id=run_id,
        payload=payload,
    )


def closed_baseline_lifecycle() -> list[FaultEventRecord]:
    """The #59 segment-1 anchor: injected + activated + cleared all seen."""
    return [
        fault_event("fault.injected", journal_seq=10),
        fault_event("fault.activated", journal_seq=11),
        fault_event("fault.applied", journal_seq=12),
        fault_event("fault.cleared", journal_seq=13),
    ]


def observation(
    event_type: str,
    payload: Mapping[str, Any],
    *,
    journal_seq: int,
    pid: int | None = CC_PID,
) -> ObservationRecord:
    """One normalized observation (source/confidence ride the payload)."""
    return ObservationRecord(
        journal_seq=journal_seq,
        event_type=event_type,
        payload=dict(payload),
        node_id=NODE,
        pid=pid,
        run_id=RECOVERY,
    )


def clean_psi(section: str, seq: int) -> ObservationRecord:
    return observation(
        "ts.psi_section_observed",
        {
            "source": "internal_parser",
            "confidence": "parsed",
            "section": section,
            "present": True,
            "crc_valid": True,
            "packet_index": 100 + seq,
        },
        journal_seq=seq,
        pid=PSI_PID,
    )


def clean_mapping_program() -> list[ObservationRecord]:
    """PAT declares 0x1000; a PMT is observed on 0x1000 — mapping holds."""
    return [
        observation(
            "ts.psi_section_observed",
            {
                "source": "internal_parser",
                "confidence": "parsed",
                "section": "PAT",
                "present": True,
                "crc_valid": True,
                "actual_program_map_pid": 0x1000,
                "packet_index": 100,
            },
            journal_seq=201,
            pid=PSI_PID,
        ),
        observation(
            "ts.psi_section_observed",
            {
                "source": "internal_parser",
                "confidence": "parsed",
                "section": "PMT",
                "present": True,
                "crc_valid": True,
                "packet_index": 140,
            },
            journal_seq=202,
            pid=0x1000,
        ),
    ]


def clean_coverage() -> list[ObservationRecord]:
    """The CC coverage evidence: real packets observed, zero errors."""
    return observation(
        "ts.packet_batch_observed",
        {
            "source": "internal_parser",
            "confidence": "parsed",
            "packet_count": 500,
            "continuity_error_count": 0,
        },
        journal_seq=301,
        pid=None,
    )


def cc_error(seq: int = 401) -> ObservationRecord:
    return observation(
        "ts.continuity_error",
        {
            "source": "internal_parser",
            "confidence": "parsed",
            "expected_cc": 5,
            "actual_cc": 8,
            "packet_index": 50,
        },
        journal_seq=seq,
    )


def evaluation_input(
    *,
    criteria: list[dict[str, Any]],
    baseline_fault_events: list[FaultEventRecord] | None = None,
    recovery_fault_events: list[FaultEventRecord] | None = None,
    recovery_observations: list[ObservationRecord] | None = None,
    recovery_run_completed: bool = True,
    ui_state: Mapping[str, Any] | None = None,
) -> EvaluationInput:
    return EvaluationInput(
        session_id=SESSION,
        baseline_run_id=BASELINE,
        recovery_run_id=RECOVERY,
        scenario_id=SCENARIO_ID,
        scenario_version=SCENARIO_VERSION,
        scenario_content_hash=SCENARIO_HASH,
        pass_criteria=tuple(criteria),
        baseline_fault_events=tuple(baseline_fault_events or ()),
        recovery_fault_events=tuple(recovery_fault_events or ()),
        recovery_observations=tuple(recovery_observations or ()),
        recovery_run_completed=recovery_run_completed,
        ui_state=ui_state,
    )


def baseline_verified_input(
    criteria: list[dict[str, Any]],
    **overrides: Any,
) -> EvaluationInput:
    """The 'repair worked' happy-path input: closed baseline lifecycle,
    clean recovery (no fault events), clean observations."""
    kwargs: dict[str, Any] = {
        "criteria": criteria,
        "baseline_fault_events": closed_baseline_lifecycle(),
        "recovery_observations": [clean_coverage()] + clean_mapping_program(),
    }
    kwargs.update(overrides)
    return evaluation_input(**kwargs)
