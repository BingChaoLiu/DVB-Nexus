"""Shared diagnosis-engine test fixtures (ticket #54, SPEC-306 §9 /
SPEC-307 §9 shared-fixture duty; consumed by ticket #55).

This module is the sanctioned shared-constructor area for the diagnosis
axis. Three kinds of material:

1. **Fixture rules** — in-memory rules whose DECLARATIVE SHAPE mirrors
   SPEC-307 §3 ``DiagnosticRule`` (rule_id/rule_version/code/priority/
   severity/confidence/title/summary_template/match/suppression/
   suggested_actions/expected_evidence) plus a ``match`` verdict the
   SPEC-306 evaluator consumes structurally. Ticket #55 owns the REAL
   declarative model + loader (``domain.diagnosis.rules``); these
   stand-ins exist so the #54 engine is testable before the rules
   package lands, and #55 reuses the same observation programs and
   cross-validation material (SPEC-307 §9) instead of inventing
   parallel fixtures.

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
   exactly the fixture rules' ``expected_evidence`` (ADR-0007 item 5
   interlock; SPEC-307 §6).

Axis discipline: every ``ts.*`` envelope/payload built here carries the
mandatory observation axes (``source`` / ``confidence``, #13 Q3-i); the
rules' ``confidence`` is the diagnosis THREE-tier static axis
(SPEC-307 §3) and never the observation provenance axis.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from domain.diagnosis.engine import ObservationRecord, RuleMatch
from domain.diagnosis.report import EvidenceRef
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


# --- fixture rule model (SPEC-307 §3 declarative shape) ------------------------


@dataclass(frozen=True)
class FixtureSuppressionSpec:
    """SPEC-307 §5 MVP-fixed suppression declaration."""

    key: tuple[str, ...] = ("code", "node_id")
    window: str = "per_run"


@dataclass(frozen=True)
class FixtureMatchSpec:
    """SPEC-307 §4 declarative primitives (fixture subset).

    ``event_type`` selector + ``eq`` field predicates on payload keys +
    ``exists`` predicates + a minimal ``count`` window aggregate (a match
    needs at least ``min_count`` qualifying records per run).
    """

    event_type: str
    payload_equals: tuple[tuple[str, Any], ...] = ()
    payload_exists: tuple[str, ...] = ()
    min_count: int = 1


@dataclass(frozen=True)
class FixtureDiagnosticRule:
    """SPEC-307 §3 ``DiagnosticRule`` shape (fixture stand-in for #55).

    The ``match`` verdict interprets the declarative
    :class:`FixtureMatchSpec`; production rules are #55's declarative
    model compiled by its loader — this fixture never defines rule
    semantics for production use.
    """

    rule_id: str
    rule_version: str
    code: str
    priority: int
    severity: str
    confidence: str
    title: str
    summary_template: str
    match: FixtureMatchSpec
    suppression: FixtureSuppressionSpec = field(default_factory=FixtureSuppressionSpec)
    suggested_actions: tuple[str, ...] = ()
    expected_evidence: tuple[str, ...] = ()

    def matches(
        self, records: Sequence[ObservationRecord]
    ) -> tuple[RuleMatch, ...]:
        """Evaluation verdict (SPEC-306 EvaluationRule face). Named
        ``matches`` because ``match`` is the declarative SPEC-307 §3
        field."""
        qualifying = [
            record
            for record in records
            if record.event_type == self.match.event_type
            and self._predicates_hold(record)
            and _evidence_of(record) is not None
        ]
        if len(qualifying) < self.match.min_count:
            return ()
        return tuple(_match_of(self, record) for record in qualifying)

    # -- predicate interpreter (SPEC-307 §4: eq / exists on payload) ----

    def _predicates_hold(self, record: ObservationRecord) -> bool:
        for key, expected in self.match.payload_equals:
            if record.payload.get(key) != expected:
                return False
        for key in self.match.payload_exists:
            if key not in record.payload:
                return False
        return True


def _evidence_of(record: ObservationRecord) -> EvidenceRef | None:
    """Extract the artifact anchor from the fixture payload keys.

    Records lacking the full evidence triple produce no match (the
    SPEC-306 §6 chain requires every candidate to anchor to an artifact).
    """
    artifact_id = record.payload.get("artifact_id")
    pid = record.payload.get("pid")
    packet_index = record.payload.get("packet_index")
    if not (
        isinstance(artifact_id, str)
        and artifact_id
        and isinstance(pid, int)
        and 0 <= pid <= 8191
        and isinstance(packet_index, int)
        and packet_index >= 0
    ):
        return None
    return EvidenceRef(artifact_id=artifact_id, pid=pid, packet_index=packet_index)


def _match_of(rule: FixtureDiagnosticRule, record: ObservationRecord) -> RuleMatch:
    evidence = _evidence_of(record)
    assert evidence is not None  # match() pre-filtered on the triple
    try:
        summary = rule.summary_template.format(**record.payload)
    except (KeyError, IndexError):
        summary = rule.summary_template
    return RuleMatch(
        journal_seq=record.journal_seq,
        event_type=record.event_type,
        evidence=evidence,
        affected_node_ids=[record.node_id] if record.node_id else [],
        summary=summary,
    )


# --- builtin fixture rule set (SPEC-307 §6 table mirror) -----------------------


def builtin_fixture_rules() -> tuple[FixtureDiagnosticRule, ...]:
    """The four fault-mirroring rules (SPEC-307 §6: one rule per MVP fault).

    Field values follow the SPEC-307 §6 table (priority/severity/
    confidence); the declarative predicates pin the single-symptom
    signatures of ADR-0007 item 5 at fixture level — the REAL rules and
    the four-fault cross-validation are ticket #55's REQ-DIA-307-003.
    """
    return (
        FixtureDiagnosticRule(
            rule_id="DIA-PAT-MISSING",
            rule_version="1.0.0",
            code="DIAG_PAT_MISSING",
            priority=10,
            severity="error",
            confidence="high",
            title="PAT missing in window",
            summary_template=(
                "No PAT observed on PID {pid} (null substitution at packet"
                " {packet_index}); window artefact {artifact_id}"
            ),
            match=FixtureMatchSpec(
                event_type="ts.psi_section_observed",
                payload_equals=(("section", "PAT"), ("present", False)),
            ),
            suggested_actions=("Restore PAT emission on PID 0",),
            expected_evidence=("ts.psi_section_observed",),
        ),
        FixtureDiagnosticRule(
            rule_id="DIA-PMT-CRC-BAD",
            rule_version="1.0.0",
            code="DIAG_PMT_CRC_BAD",
            priority=20,
            severity="error",
            confidence="high",
            title="PMT CRC verification failed",
            summary_template=(
                "PMT CRC check failed (persistent symptom) at packet"
                " {packet_index}; window artefact {artifact_id}"
            ),
            match=FixtureMatchSpec(
                event_type="ts.psi_section_observed",
                payload_equals=(("section", "PMT"), ("crc_valid", False)),
                min_count=2,  # persistent mode: the symptom is stable
            ),
            suggested_actions=("Re-mux the PMT with correct CRC",),
            expected_evidence=("ts.psi_section_observed",),
        ),
        FixtureDiagnosticRule(
            rule_id="DIA-CC-DISCONTINUITY",
            rule_version="1.0.0",
            code="DIAG_CC_DISCONTINUITY",
            priority=30,
            severity="warning",
            confidence="high",
            title="Continuity counter discontinuity",
            summary_template=(
                "CC discontinuity on PID {pid}: expected {expected_cc},"
                " got {actual_cc} at packet {packet_index} (relative"
                " offset persists); artefact {artifact_id}"
            ),
            match=FixtureMatchSpec(
                event_type="ts.continuity_error",
                payload_exists=("expected_cc", "actual_cc"),
            ),
            suggested_actions=("Inspect the upstream multiplex for packet loss",),
            expected_evidence=("ts.continuity_error",),
        ),
        FixtureDiagnosticRule(
            rule_id="DIA-PMT-PID-MISMATCH",
            rule_version="1.0.0",
            code="DIAG_PMT_PID_MISMATCH",
            priority=40,
            severity="error",
            confidence="medium",
            title="PAT points at a PMT PID with no PMT",
            summary_template=(
                "PAT declares program_map_pid {actual_program_map_pid} but"
                " the PMT sits on {expected_program_map_pid} (orphan PMT)"
                " at packet {packet_index}; artefact {artifact_id}"
            ),
            match=FixtureMatchSpec(
                event_type="ts.psi_section_observed",
                payload_equals=(("section", "PAT"),),
                payload_exists=("expected_program_map_pid",),
            ),
            suggested_actions=("Correct the PAT program_map_pid entry",),
            expected_evidence=("ts.psi_section_observed",),
        ),
    )


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


def fixture_rule_for_fault(fault_type: str) -> FixtureDiagnosticRule:
    """The SPEC-307 §6 one-rule-per-fault pairing."""
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
    """A real ``FaultDefinition`` interlocked with the fixture rule.

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
    "FixtureDiagnosticRule",
    "FixtureMatchSpec",
    "FixtureSuppressionSpec",
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
