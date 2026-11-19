"""SPEC-306 §5/§8 batch evaluation core (ticket #54).

The evaluator is the PURE half of the diagnosis engine: it receives
already-parsed observation records (the application orchestration reads
the journal — the domain never touches SQLite/adapters, brief §2.7) and a
ruleset, and produces the sorted :class:`DiagnosisReport`. Side effects
(upsert + ``diagnosis.*`` publication) live in the application service
implementing the SPEC-306 §5 ``DiagnosisEngine`` face.

Discipline pins:

- confidence is the rule's static declaration, passed through verbatim;
  the engine computes no score (brief §6, SPEC-003 §2.6).
- rule isolation (§8): a rule that raises is skipped with a warning; the
  remaining rules evaluate normally.
- payload discipline (§8): a record whose payload violates the registered
  schema is skipped with a warning and produces no candidate.
- no rules / no match = empty report, not an error (§8).
- ordering (SPEC-307 §5): priority ascending → severity descending →
  code lexicographic; no preemption.
- suppression (SPEC-307 §5 MVP fixed semantics): one candidate per
  ``(code, node)`` per run; repeated hits accumulate evidence under the
  same ``diagnosis_id``. Cross-evaluation identity comes from the
  ``existing`` map (the caller reads it from the diagnoses table), so a
  re-evaluation extends the SAME candidate instead of raising a twin.
- single attributable symptom (ADR-0007 item 5): rules are evaluated
  independently; candidates never derive from each other.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional, Protocol, Sequence

from pydantic import Field

from domain._base import DomainModel
from domain.diagnosis.model import DiagnosisConfidence, DiagnosisSeverity
from domain.diagnosis.report import (
    DiagnosisCandidate,
    DiagnosisReport,
    ObservationRef,
    EvidenceRef,
    sort_candidates,
)
from domain.observation.envelope import new_event_id
from domain.observation.registry import validate_payload

__all__ = [
    "DiagnosisEvaluator",
    "EvaluationRule",
    "EvaluationOutcome",
    "GroupedCandidate",
    "ObservationRecord",
    "RuleMatch",
    "suppression_node_key",
]


class ObservationRecord(DomainModel):
    """One parsed observation-class journal record handed to the engine.

    The application orchestration builds these from committed
    ``EventRow`` envelopes; ``node_id``/``pid`` are the correlation hops
    rules address (ADR-0006 decision 3 dual addressing).
    ``source_ns`` is the record's ``time.source.value_ns`` — the
    orchestration anchors derived ``diagnosis.*`` events to the latest
    observed virtual time of the run (deterministic; no wall clock).

    ``evidence_artifact_id`` is the Phase 2 evidence anchor the
    APPLICATION resolves before handing the record over (SPEC-306
    §Phase2 补丁修订, ticket #138): the mutation-log artifact via the
    journal reference chain for ``biss.*``, the run's received-leg Inner
    TS artifact for ``t2mi.*``/``bbframe.*``. MVP ``ts.*`` records keep
    ``None`` — their anchor rides the payload triple (SPEC-306 §6 MVP
    state), and an unstamped evidence record produces no candidate (no
    anchor, no candidate).
    """

    journal_seq: int = Field(ge=1)
    event_type: str = Field(min_length=1)
    event_id: str = Field(min_length=1)
    payload: dict[str, Any]
    node_id: Optional[str] = None
    pid: Optional[int] = Field(default=None, ge=0, le=8191)
    source_ns: int = Field(default=0, ge=0)
    evidence_artifact_id: Optional[str] = None


class RuleMatch(DomainModel):
    """One rule hit on one record (the rule's own match verdict)."""

    journal_seq: int = Field(ge=1)
    event_type: str = Field(min_length=1)
    #: The artifact anchor for this hit (SPEC-306 §6 chain terminus).
    evidence: EvidenceRef
    #: Nodes the hit is attributed to (empty = run-level hit).
    affected_node_ids: list[str] = Field(default_factory=list)
    #: Rendered hit summary (the rule renders its SPEC-307 template).
    summary: str = Field(min_length=1)


class EvaluationRule(Protocol):
    """The rule face the engine consumes (SPEC-307 §3 shape, structural).

    #55 owns the real declarative model (``rules/`` subpackage); the
    engine only requires the static declaration attributes below plus the
    ``match`` verdict callable, so any conforming rule plugs in without
    the engine importing the rules package (SPEC-306 §2.2 out-of-scope
    rule: rule definitions are SPEC-307).
    """

    rule_id: str
    rule_version: str
    code: str
    priority: int
    severity: DiagnosisSeverity | str
    confidence: DiagnosisConfidence | str
    title: str
    suggested_actions: Sequence[str]
    expected_evidence: Sequence[str]

    def matches(
        self, records: Sequence[ObservationRecord]
    ) -> Sequence[RuleMatch]:
        """Return the hits of this rule over the given records.

        The verdict method is deliberately NOT named ``match``: the
        SPEC-307 §3 rule model carries a declarative ``match: MatchSpec``
        FIELD, so the evaluation face needs its own name. Implementations
        must be pure and deterministic; a raising rule is isolated
        (SPEC-306 §8) — never fails the evaluation.
        """
        ...


def _rule_enabled(rule: EvaluationRule) -> bool:
    """Rules MAY declare ``enabled``; disabled rules are skipped (non-error,
    SPEC-307 §8 row 3)."""
    return bool(getattr(rule, "enabled", True))


def suppression_node_key(affected_node_ids: Sequence[str]) -> str:
    """The MVP suppression-key node component (SPEC-307 §5 fixed
    ``key=("code", "node_id")``): the first attributed node, or the
    run-level group when the hit has no node attribution."""
    return affected_node_ids[0] if affected_node_ids else ""


@dataclass(frozen=True)
class GroupedCandidate:
    """One ``(code, node)`` suppression group's final view plus the
    emission facts the application service needs (event granularity is
    per hit: SPEC-307 §5 — one raised, subsequent hits accumulate as
    updated)."""

    candidate: DiagnosisCandidate
    node_key: str
    #: True when no stored candidate exists for the group yet (a raised
    #: event is due); False → the caller diffs against the stored row.
    is_new: bool
    #: Ordered per-hit refs: hit 0 anchors the raised payload, each
    #: further hit accumulates one updated payload (cumulative refs).
    hit_refs: tuple[ObservationRef, ...]


@dataclass(frozen=True)
class EvaluationOutcome:
    """Report plus the grouped emission facts (application service view).

    ``groups`` follows the same SPEC-307 §5 ordering as
    ``report.candidates``.
    """

    report: DiagnosisReport
    groups: tuple[GroupedCandidate, ...]


class DiagnosisEvaluator:
    """Pure batch evaluator (SPEC-306 §8 semantics)."""

    def evaluate(
        self,
        session_id: str,
        run_id: str,
        records: Sequence[ObservationRecord],
        rules: Sequence[EvaluationRule] | None,
        *,
        existing: Mapping[tuple[str, str], str] | None = None,
        now_utc_ms: int,
    ) -> EvaluationOutcome:
        """Evaluate ``rules`` over ``records`` for one run.

        ``existing`` maps ``(code, node_key)`` → the stored raised
        ``diagnosis_id``; groups present there keep that identity
        (updated/extended) instead of minting a twin candidate.
        """
        existing = existing or {}
        warnings: list[str] = []
        usable = self._usable_records(records, warnings)

        # Deterministic rule processing order: evaluate in the output
        # ordering so candidate ids and emission sequences do not depend
        # on ruleset input order (no priority preemption — every rule
        # still evaluates).
        ordered = sorted(
            (rule for rule in rules or () if _rule_enabled(rule)),
            key=_rule_sort_key,
        )
        groups: dict[tuple[str, str], _Group] = {}
        for rule in ordered:
            try:
                matches = list(rule.matches(usable))
            except Exception as exc:  # rule isolation, SPEC-306 §8
                warnings.append(
                    f"rule {rule.rule_id!r} raised {type(exc).__name__} "
                    "during match; rule isolated and skipped (SPEC-306 §8)"
                )
                continue
            self._absorb(groups, rule, matches)

        candidates: list[DiagnosisCandidate] = []
        grouped: list[GroupedCandidate] = []
        for key, group in groups.items():
            diagnosis_id = existing.get(key) or new_event_id()
            is_new = key not in existing
            candidate = DiagnosisCandidate(
                diagnosis_id=diagnosis_id,
                run_id=run_id,
                rule_id=group.rule_id,
                rule_version=group.rule_version,
                code=key[0],
                priority=group.priority,
                severity=group.severity,
                confidence=group.confidence,
                title=group.title,
                summary=group.summary,
                observation_refs=list(group.refs),
                affected_node_ids=group.node_ids,
                suggested_actions=group.suggested_actions,
                evidence=group.evidence,
            )
            candidates.append(candidate)
            grouped.append(
                GroupedCandidate(
                    candidate=candidate,
                    node_key=key[1],
                    is_new=is_new,
                    hit_refs=tuple(group.refs),
                )
            )

        report = DiagnosisReport(
            session_id=session_id,
            run_id=run_id,
            candidates=tuple(sort_candidates(candidates)),
            warnings=tuple(warnings),
            evaluated_at_utc_ms=now_utc_ms,
        )
        return EvaluationOutcome(report=report, groups=tuple(grouped))

    # --- internals ------------------------------------------------------------

    def _usable_records(
        self,
        records: Sequence[ObservationRecord],
        warnings: list[str],
    ) -> list[ObservationRecord]:
        """Skip records violating the registered payload schema (§8 row 4:
        skip with a warning, never a candidate)."""
        usable: list[ObservationRecord] = []
        for record in records:
            try:
                validate_payload(record.event_type, record.payload)
            except Exception as exc:
                warnings.append(
                    f"journal_seq {record.journal_seq} event "
                    f"{record.event_type!r} skipped: payload does not "
                    f"satisfy the registered schema "
                    f"({getattr(exc, 'code', type(exc).__name__)})"
                )
                continue
            usable.append(record)
        return usable

    def _absorb(
        self,
        groups: dict[tuple[str, str], "_Group"],
        rule: EvaluationRule,
        matches: Sequence[RuleMatch],
    ) -> None:
        severity = DiagnosisSeverity(rule.severity)
        confidence = DiagnosisConfidence(rule.confidence)
        for match in matches:
            key = (rule.code, suppression_node_key(match.affected_node_ids))
            group = groups.get(key)
            if group is None:
                groups[key] = _Group(
                    rule_id=rule.rule_id,
                    rule_version=rule.rule_version,
                    priority=rule.priority,
                    severity=severity,
                    confidence=confidence,
                    title=rule.title,
                    summary=match.summary,
                    suggested_actions=list(rule.suggested_actions),
                    node_ids=list(match.affected_node_ids),
                    evidence=match.evidence,
                    refs=[
                        ObservationRef(
                            journal_seq=match.journal_seq,
                            event_type=match.event_type,
                        )
                    ],
                )
                continue
            # Same (code, node) group: accumulate (SPEC-307 §5 suppression).
            group.refs.append(
                ObservationRef(
                    journal_seq=match.journal_seq,
                    event_type=match.event_type,
                )
            )
            if match.affected_node_ids and not group.node_ids:
                group.node_ids = list(match.affected_node_ids)


def _rule_sort_key(rule: EvaluationRule) -> tuple[int, int, str]:
    severity = DiagnosisSeverity(rule.severity)
    rank = {DiagnosisSeverity.CRITICAL: 0, DiagnosisSeverity.ERROR: 1,
            DiagnosisSeverity.WARNING: 2, DiagnosisSeverity.INFO: 3}[severity]
    return (rule.priority, rank, rule.code)


class _Group:
    """Mutable accumulation buffer for one suppression group."""

    __slots__ = (
        "rule_id",
        "rule_version",
        "priority",
        "severity",
        "confidence",
        "title",
        "summary",
        "suggested_actions",
        "node_ids",
        "evidence",
        "refs",
    )

    def __init__(
        self,
        *,
        rule_id: str,
        rule_version: str,
        priority: int,
        severity: DiagnosisSeverity,
        confidence: DiagnosisConfidence,
        title: str,
        summary: str,
        suggested_actions: list[str],
        node_ids: list[str],
        evidence: EvidenceRef,
        refs: list[ObservationRef],
    ) -> None:
        self.rule_id = rule_id
        self.rule_version = rule_version
        self.priority = priority
        self.severity = severity
        self.confidence = confidence
        self.title = title
        self.summary = summary
        self.suggested_actions = suggested_actions
        self.node_ids = node_ids
        self.evidence = evidence
        self.refs = refs
