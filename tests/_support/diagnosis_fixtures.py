"""Shared diagnosis-engine test fixtures (ticket #54, SPEC-306 §9 /
SPEC-307 §9 shared-fixture duty; consumed by ticket #55).

This module is the sanctioned shared-constructor area for the diagnosis
axis. Three kinds of material:

1. **Builtin ruleset delegate** — the four fault-mirroring rules are the
   PRODUCTION builtin set, built by the production loader
   (``domain.diagnosis.rules.load_builtin_rules``) from the shipped JSON
   declarations. The fixture tree keeps NO parallel rule model or match
   interpreter: the former ``FixtureDiagnosticRule`` stand-ins existed
   so the #54 engine was testable before the #55 rules package landed;
   since #55 they are a drift risk (M0 double-implementation lesson),
   so M4 review fix F2 collapsed them into this thin delegate and the
   interlock test pins fixture ≡ production (``tests/unit/domain/
   diagnosis/test_dia_rules_interlock.py``).

2. **Observation programs** — deterministic parsed-record programs whose
   payload keys mirror the ADR-0007 item 5 single-symptom signatures of
   the four MVP fault types. G3 note (brief §8.3): the TS analysis path
   is not eventized yet, so the ``ts.*`` payload keys BELOW are the
   diagnosis-side fixture contract: ``artifact_id`` / ``packet_index``
   (plus ``pid``) ride every observation payload so the SPEC-306 §6
   evidence chain is exercisable end to end. They join the #50 metrics
   fixture contract keys documented in
   ``application.observation.metrics.catalog`` until the analysis bridge
   lands.

3. **Fault-definition interlock** — real ``FaultDefinition`` objects
   (canonical ``faults`` package) whose ``expected_observations`` are
   exactly the paired builtin rule's ``expected_evidence`` (ADR-0007
   item 5 interlock; SPEC-307 §6).

Axis discipline: every ``ts.*`` envelope/payload built here carries the
mandatory observation axes (``source`` / ``confidence``, #13 Q3-i); the
rules' ``confidence`` is the diagnosis THREE-tier static axis
(SPEC-307 §3) and never the observation provenance axis.
"""

from __future__ import annotations

from typing import Any

from domain.diagnosis.engine import ObservationRecord
from domain.diagnosis.rules import DiagnosticRule, load_builtin_rules
from faults.definition import FaultActivation, FaultDefinition

# --- constants -----------------------------------------------------------------

#: The session/run identity the deterministic programs use.
SESSION_ID = "sess-dia-fixture"
RUN_ID = "run-dia-fixture"

#: The node every program attributes its hits to (semantic node slug,
#: ADR-0006 decision 3 — plain string because domain.diagnosis may not
#: import domain.topology).
NODE_ID = "mux-0"

#: PID the PAT/PMT-family programs address (PID 0x0000 carries PAT/PMT).
PSI_PID = 0

#: PID the CC program addresses.
CC_PID = 256

#: The artifact the evidence chain anchors to (opaque uuid4-shaped string;
#: the content-addressed store test binds a REAL artifact with this id —
#: the id is producer policy, not parsed semantics).
ARTIFACT_ID = "d1a6dd5e-4c62-4f3f-9d9a-2b6f7c8a0001"

#: Packet indexes the programs anchor evidence to (ADR-0007 item 4:
#: baseline and faulted share one packet-order frame — same index, same
#: slot). Values mirror the golden-vector landing geometry loosely; they
#: are fixture inputs, not spec pins.
PAT_WINDOW_START_INDEX = 12000
CC_LANDING_INDEX = 50
PMT_CRC_INDEX = 7000
PMT_MISMATCH_INDEX = 9000


# --- builtin ruleset (thin delegate to the production loader) ------------------


def builtin_fixture_rules() -> tuple[DiagnosticRule, ...]:
    """The four fault-mirroring rules (SPEC-307 §6: one rule per MVP fault)
    — the PRODUCTION builtin set, not a fixture copy.

    Thin delegate (M4 review fix F2): rules come from the production
    loader (``domain.diagnosis.rules.load_builtin_rules``) over the
    shipped JSON declarations, in the §5 output ordering. The fixture
    tree keeps no parallel rule model or match interpreter (the M0
    double-implementation lesson); rule semantics live in
    ``domain.diagnosis.rules`` (ticket #55, REQ-DIA-307-003).
    """
    return load_builtin_rules()


# --- observation programs (ADR-0007 item 5 single-symptom signatures) ----------


def observation_record(
    *,
    journal_seq: int,
    event_type: str,
    payload: dict[str, Any],
    node_id: str | None = NODE_ID,
    pid: int | None = None,
    event_id: str = "obs-0000-0000",
    source_ns: int = 1_000,
) -> ObservationRecord:
    """One parsed observation record for the evaluator (unit posture)."""
    return ObservationRecord(
        journal_seq=journal_seq,
        event_type=event_type,
        event_id=event_id,
        payload=payload,
        node_id=node_id,
        pid=pid,
        source_ns=source_ns,
    )


def observation_envelope(
    *,
    event_type: str,
    payload: dict[str, Any],
    session_id: str = SESSION_ID,
    run_id: str | None = RUN_ID,
    source_ns: int = 1_000,
    pid: int | None = None,
    node_id: str | None = NODE_ID,
    observed_ns: int = 1_005,
) -> dict:
    """SPEC-301-shaped ``ts.*`` envelope document, schema-validated by
    ``parse_envelope`` (construction guarantee — a non-conforming fixture
    event cannot reach the gateway/journal). Carries the mandatory
    observation axes via ``payload`` (#13 Q3-i)."""
    from domain.observation import new_event_id, parse_envelope

    document = {
        "schema_version": "1.0",
        "event_id": new_event_id(),
        "event_type": event_type,
        "producer": {
            "producer_id": "diagnosis-fixture",
            "producer_version": "0.1.0",
            "instance_id": "fixture-inst",
        },
        "scope": {
            "tenant_id": "local",
            "session_id": session_id,
            "run_id": run_id,
        },
        "time": {
            "source": {
                "value_ns": source_ns,
                "clock_domain": f"sim:{session_id}",
                "clock_epoch": 0,
            },
            "observed": {
                "value_ns": observed_ns,
                "clock_domain": "wall:utc",
                "clock_epoch": 0,
            },
        },
        "correlation": {
            "trace_id": None,
            "span_id": None,
            "parent_event_id": None,
            "fault_id": None,
            "node_id": node_id,
            "port_id": None,
            "service_id": None,
            "pid": pid,
        },
        "severity": "info",
        "payload": dict(payload),
        "tags": [],
    }
    return parse_envelope(document).model_dump(mode="json")


def _psi_payload(**extra: Any) -> dict[str, Any]:
    """PSI observation payload with the evidence triple + observation axes."""
    return {
        "source": "internal_parser",
        "confidence": "parsed",
        "pid": PSI_PID,
        "artifact_id": ARTIFACT_ID,
        **extra,
    }


def fault_observation_program(fault_type: str) -> tuple[ObservationRecord, ...]:
    """The deterministic single-symptom program for one MVP fault type.

    Payload keys per fault (diagnosis fixture contract, see module
    docstring); each hit carries the full evidence triple so the SPEC-306
    §6 chain resolves:

    - PAT_MISSING: the PAT window is missing (present=False), one hit;
    - PMT_INVALID_CRC: persistent CRC failures, two hits (stable symptom);
    - CC_DISCONTINUITY: relative CC offset, one landing hit;
    - PMT_PID_MISMATCH: PAT repointed at a wrong pid, one hit.
    """
    if fault_type == "PAT_MISSING":
        return (
            observation_record(
                journal_seq=42,
                event_type="ts.psi_section_observed",
                payload=_psi_payload(
                    section="PAT",
                    present=False,
                    packet_index=PAT_WINDOW_START_INDEX,
                ),
                pid=PSI_PID,
                event_id="obs-pat-missing-1",
            ),
        )
    if fault_type == "PMT_INVALID_CRC":
        return (
            observation_record(
                journal_seq=51,
                event_type="ts.psi_section_observed",
                payload=_psi_payload(
                    section="PMT",
                    crc_valid=False,
                    packet_index=PMT_CRC_INDEX,
                ),
                pid=PSI_PID,
                event_id="obs-pmt-crc-1",
            ),
            observation_record(
                journal_seq=52,
                event_type="ts.psi_section_observed",
                payload=_psi_payload(
                    section="PMT",
                    crc_valid=False,
                    packet_index=PMT_CRC_INDEX + 188 * 13,
                ),
                pid=PSI_PID,
                event_id="obs-pmt-crc-2",
            ),
        )
    if fault_type == "CC_DISCONTINUITY":
        return (
            observation_record(
                journal_seq=77,
                event_type="ts.continuity_error",
                payload={
                    "source": "internal_parser",
                    "confidence": "parsed",
                    "pid": CC_PID,
                    "expected_cc": 5,
                    "actual_cc": 8,  # delta 3, relative offset
                    "artifact_id": ARTIFACT_ID,
                    "packet_index": CC_LANDING_INDEX,
                },
                node_id=NODE_ID,
                pid=CC_PID,
                event_id="obs-cc-1",
            ),
        )
    if fault_type == "PMT_PID_MISMATCH":
        return (
            observation_record(
                journal_seq=88,
                event_type="ts.psi_section_observed",
                payload=_psi_payload(
                    section="PAT",
                    actual_program_map_pid=4100,
                    expected_program_map_pid=4096,
                    packet_index=PMT_MISMATCH_INDEX,
                ),
                pid=PSI_PID,
                event_id="obs-pmt-pid-mismatch-1",
            ),
        )
    raise ValueError(f"unknown fixture fault type: {fault_type!r}")


FIXTURE_FAULT_TYPES: tuple[str, ...] = (
    "PAT_MISSING",
    "PMT_INVALID_CRC",
    "CC_DISCONTINUITY",
    "PMT_PID_MISMATCH",
)


def fixture_rule_for_fault(fault_type: str) -> DiagnosticRule:
    """The SPEC-307 §6 one-rule-per-fault pairing (production rules)."""
    pairing = {
        "PAT_MISSING": "DIA-PAT-MISSING",
        "PMT_INVALID_CRC": "DIA-PMT-CRC-BAD",
        "CC_DISCONTINUITY": "DIA-CC-DISCONTINUITY",
        "PMT_PID_MISMATCH": "DIA-PMT-PID-MISMATCH",
    }
    rule_id = pairing[fault_type]
    for rule in builtin_fixture_rules():
        if rule.rule_id == rule_id:
            return rule
    raise ValueError(f"no fixture rule for fault type: {fault_type!r}")


def fixture_fault_definition(fault_type: str) -> FaultDefinition:
    """A real ``FaultDefinition`` interlocked with the paired builtin rule.

    ``expected_observations`` = the pairing rule's ``expected_evidence``
    (ADR-0007 item 5 interlock — SPEC-307 §6 table); target follows the
    canonical ``node_id:pid:0xhex`` stream-level form (SPEC-204 §6).
    """
    rule = fixture_rule_for_fault(fault_type)
    pid = CC_PID if fault_type == "CC_DISCONTINUITY" else PSI_PID
    # Minimal versioned parameters per SPEC-204 §6: CC needs the relative
    # delta, PMT_PID_MISMATCH needs the repointed pid; the other two MVP
    # types carry their mode defaults.
    parameters: dict[str, Any] = {
        "CC_DISCONTINUITY": {"delta": 3},
        "PMT_PID_MISMATCH": {"wrong_pmt_pid": 4100},
    }.get(fault_type, {})
    return FaultDefinition(
        fault_id="fd000000-0000-4000-8000-000000000001",
        fault_type=fault_type,
        target_id=f"{NODE_ID}:pid:0x{pid:04x}",
        parameters=parameters,
        activation=FaultActivation(kind="session_start", packet_index=None),
        expected_observations=rule.expected_evidence,
    )


__all__ = [
    "ARTIFACT_ID",
    "CC_LANDING_INDEX",
    "CC_PID",
    "FIXTURE_FAULT_TYPES",
    "NODE_ID",
    "PAT_WINDOW_START_INDEX",
    "PSI_PID",
    "PMT_CRC_INDEX",
    "PMT_MISMATCH_INDEX",
    "RUN_ID",
    "SESSION_ID",
    "builtin_fixture_rules",
    "fixture_fault_definition",
    "fixture_rule_for_fault",
    "fault_observation_program",
    "observation_envelope",
    "observation_record",
]
