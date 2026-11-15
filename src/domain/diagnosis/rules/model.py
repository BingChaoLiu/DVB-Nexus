"""SPEC-307 §3/§4 diagnostic rule model + the declarative interpreter
(ticket #55).

``DiagnosticRule`` is the SPEC-307 §3 frozen model; ``match: MatchSpec``
is the FINITE declarative predicate set (§4): an ``event_type`` selector,
``eq/gt/lt/exists`` field predicates over payload and correlation fields,
``count/rate`` window aggregates, ``pid``/``node_id`` grouping keys. The
red line: NO user-defined Python or expression strings — every field is
structured data, unknown keys are refused (``extra="forbid"``), and
template placeholders are plain payload keys (no attribute/index access).

``DiagnosticRule.matches(records)`` is the model→engine adapter: the
:class:`domain.diagnosis.engine.EvaluationRule` face the #54 evaluator
consumes structurally. The verdict method is deliberately NOT named
``match`` — that name is the declarative FIELD (§3). The interpreter is
pure and deterministic; a rule that raises is isolated by the engine
(SPEC-306 §8), and a rule declaring ``enabled=False`` is skipped there
(non-error, §8 row 3).

Interpreter contract (mirrors the sanctioned shared-fixture interpreter,
``tests._support.diagnosis_fixtures``, so the fixture rules and the real
rules agree):

- a hit needs the full evidence triple in the payload —
  ``artifact_id``/``pid``/``packet_index`` (the diagnosis-side payload key
  contract registered by ticket #54; SPEC-306 §6: no anchor, no
  candidate);
- correlation predicates resolve the ADR-0006 decision-3 addressing dual
  form (``node_id``/``pid``) — the hops ``ObservationRecord`` carries;
- window aggregates compute per declared grouping-key group within the
  per-run scope (MVP fixed); ``rate`` denominators are the group's records
  of the rule's event type;
- match attribution is the record's ``node_id`` (the MVP suppression key
  component, SPEC-307 §5 — the engine groups per ``(code, node_id)``);
- summaries render through a plain-key-only formatter; an unresolvable
  key falls back to the raw template (deterministic, never raises).

Axis discipline: ``confidence`` is the rule's static THREE-tier
declaration, transmitted verbatim — the engine computes no score
(SPEC-003 §2.6, brief §6).
"""

from __future__ import annotations

import re
from string import Formatter
from typing import Any, Literal, Mapping, Optional, Sequence

from pydantic import Field, model_validator

from domain._base import DomainModel
from domain.diagnosis.engine import ObservationRecord, RuleMatch
from domain.diagnosis.model import DiagnosisConfidence, DiagnosisSeverity
from domain.diagnosis.report import EvidenceRef
from domain.diagnosis.rules.errors import RuleDefinitionError
from domain.observation.registry import validate_event_type

__all__ = [
    "DiagnosticRule",
    "FieldPredicate",
    "GroupKey",
    "MatchSpec",
    "PredicateOp",
    "SuppressionSpec",
    "WindowAggregate",
]

#: Predicate operators (SPEC-307 §4 finite set; extensions are additive
#: review items, never user-supplied code).
PredicateOp = Literal["eq", "gt", "lt", "exists"]

#: Grouping keys (SPEC-307 §4: correlation addressing, ADR-0006 decision 3).
GroupKey = Literal["pid", "node_id"]

#: Correlation fields a predicate may address: the addressing dual form
#: carried by ``ObservationRecord`` (the wider envelope correlation block
#: stays out until the engine records grow those hops).
_CORRELATION_PREDICATE_KEYS = ("node_id", "pid")

_FIELD_PATH_PATTERN = re.compile(r"^(payload|correlation)\.[A-Za-z_][A-Za-z0-9_]*$")
_TEMPLATE_FIELD_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


class FieldPredicate(DomainModel):
    """One declarative field predicate (SPEC-307 §4)."""

    field: str
    op: PredicateOp
    #: Comparison value for ``eq/gt/lt`` (JSON scalar); ``exists`` carries
    #: none. ``None`` is a legal ``eq`` target (JSON null equality).
    value: Any = None

    @model_validator(mode="after")
    def _contract(self) -> "FieldPredicate":
        if not _FIELD_PATH_PATTERN.match(self.field):
            raise RuleDefinitionError(
                f"predicate field {self.field!r} must be 'payload.<key>' or"
                " 'correlation.<key>' (SPEC-307 §4)"
            )
        target, _, key = self.field.partition(".")
        if target == "correlation" and key not in _CORRELATION_PREDICATE_KEYS:
            raise RuleDefinitionError(
                f"correlation predicate {self.field!r} addresses a field the"
                " evaluation records do not carry; MVP predicates resolve the"
                f" addressing dual form {_CORRELATION_PREDICATE_KEYS}"
                " (ADR-0006 decision 3)"
            )
        if self.op == "exists":
            if self.value is not None:
                raise RuleDefinitionError(
                    f"predicate {self.field!r} op 'exists' carries no value"
                )
            return self
        if "value" not in self.model_fields_set:
            raise RuleDefinitionError(
                f"predicate {self.field!r} op {self.op!r} requires a value"
            )
        if self.op in ("gt", "lt") and not _is_number(self.value):
            raise RuleDefinitionError(
                f"predicate {self.field!r} op {self.op!r} requires a numeric"
                f" value, got {self.value!r}"
            )
        if self.op == "eq" and (isinstance(self.value, (dict, list))):
            raise RuleDefinitionError(
                f"predicate {self.field!r} op 'eq' compares JSON scalars,"
                f" got {type(self.value).__name__}"
            )
        return self

    def holds(self, record: ObservationRecord) -> bool:
        """Evaluate this predicate against one record (pure)."""
        target, _, key = self.field.partition(".")
        if target == "payload":
            present = key in record.payload
            value = record.payload.get(key)
        else:  # correlation dual form
            present = True
            value = record.node_id if key == "node_id" else record.pid
        if self.op == "exists":
            return present
        if self.op == "eq":
            return present and value == self.value
        # gt / lt: a non-numeric record value simply does not hold
        # (declarative hygiene — no runtime surprise, no rule isolation).
        if not (_is_number(value) and _is_number(self.value)):
            return False
        return value > self.value if self.op == "gt" else value < self.value


class WindowAggregate(DomainModel):
    """A per-run window aggregate qualifier (SPEC-307 §4 count/rate).

    MVP scope is fixed to ``"run"`` (the evaluation batch is the window);
    virtual-time intervals are a future additive extension.
    """

    aggregation: Literal["count", "rate"]
    scope: Literal["run"] = "run"
    min_count: Optional[int] = Field(default=None, ge=1)
    min_rate: Optional[float] = None

    @model_validator(mode="after")
    def _contract(self) -> "WindowAggregate":
        if self.aggregation == "count":
            if self.min_rate is not None:
                raise RuleDefinitionError(
                    "window aggregation 'count' takes min_count, not min_rate"
                )
            if self.min_count is None:
                raise RuleDefinitionError(
                    "window aggregation 'count' requires min_count >= 1"
                )
        else:  # rate
            if self.min_count is not None:
                raise RuleDefinitionError(
                    "window aggregation 'rate' takes min_rate, not min_count"
                )
            if self.min_rate is None or not 0.0 < self.min_rate <= 1.0:
                raise RuleDefinitionError(
                    f"window aggregation 'rate' requires min_rate in (0, 1],"
                    f" got {self.min_rate!r}"
                )
        return self


class MatchSpec(DomainModel):
    """The declarative match of one rule (SPEC-307 §3 ``match`` field)."""

    event_type: str = Field(min_length=1)
    predicates: tuple[FieldPredicate, ...] = ()
    group_by: tuple[GroupKey, ...] = ("node_id",)
    window: Optional[WindowAggregate] = None

    @model_validator(mode="after")
    def _contract(self) -> "MatchSpec":
        try:
            validate_event_type(self.event_type)
        except Exception as exc:
            raise RuleDefinitionError(
                f"match references unregistered event type {self.event_type!r}"
                " — startup fails fast (SPEC-307 §8 row 2; SPEC-301 §4"
                " registry)"
            ) from exc
        if not self.group_by or len(set(self.group_by)) != len(self.group_by):
            raise RuleDefinitionError(
                f"group_by must be non-empty unique pid/node_id keys,"
                f" got {self.group_by!r}"
            )
        return self


class SuppressionSpec(DomainModel):
    """MVP-fixed suppression declaration (SPEC-307 §5)."""

    key: tuple[Literal["code", "node_id"], ...] = ("code", "node_id")
    window: Literal["per_run"] = "per_run"

    @model_validator(mode="after")
    def _contract(self) -> "SuppressionSpec":
        if self.key != ("code", "node_id") or self.window != "per_run":
            raise RuleDefinitionError(
                "SuppressionSpec MVP fixes key=('code', 'node_id') and"
                " window='per_run' (SPEC-307 §5); other dimensions/windows"
                " are future extensions"
            )
        return self


class DiagnosticRule(DomainModel):
    """SPEC-307 §3 rule model — the declarative half of a diagnostic
    rule; ``matches()`` is its evaluation verdict (the engine face)."""

    rule_id: str = Field(pattern=r"^[A-Z][A-Z0-9_]*(-[A-Z0-9_]+)*$")
    rule_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$")
    #: Ordering key, smaller first — orthogonal to severity (§5).
    priority: int
    severity: DiagnosisSeverity
    #: Static THREE-tier declaration; never a computed score (Q3-ii).
    confidence: DiagnosisConfidence
    title: str = Field(min_length=1)
    #: Explanation template; placeholders are plain payload keys.
    summary_template: str = Field(min_length=1)
    match: MatchSpec
    suppression: SuppressionSpec = SuppressionSpec()
    suggested_actions: tuple[str, ...] = ()
    #: Observation event codes this rule's evidence must come from —
    #: interlocked with ``FaultDefinition.expected_observations`` (§6,
    #: ADR-0007 item 5).
    expected_evidence: tuple[str, ...] = ()
    #: Runtime disable switch (§7): disabled rules are skipped at
    #: evaluation — a non-error (§8 row 3).
    enabled: bool = True

    @model_validator(mode="after")
    def _contract(self) -> "DiagnosticRule":
        for event_type in self.expected_evidence:
            try:
                validate_event_type(event_type)
            except Exception as exc:
                raise RuleDefinitionError(
                    f"expected_evidence entry {event_type!r} of"
                    f" {self.rule_id!r} is not a registered event type"
                    " (SPEC-301 §4)"
                ) from exc
        _validate_summary_template(self.summary_template)
        return self

    # --- evaluation verdict (EvaluationRule face) ---------------------------

    def matches(
        self, records: Sequence[ObservationRecord]
    ) -> tuple[RuleMatch, ...]:
        """Hits of this rule over the given records (pure, ordered by
        journal_seq). Deterministic; see the module docstring for the
        hit/evidence/grouping contract."""
        spec = self.match
        qualifying: list[tuple[tuple, ObservationRecord]] = []
        group_totals: dict[tuple, int] = {}
        for record in records:
            if record.event_type != spec.event_type:
                continue
            key = _group_key(spec.group_by, record)
            group_totals[key] = group_totals.get(key, 0) + 1
            if _evidence_of(record) is None:
                continue
            if not all(
                predicate.holds(record) for predicate in spec.predicates
            ):
                continue
            qualifying.append((key, record))
        if not qualifying:
            return ()

        selected = _window_selected(spec, qualifying, group_totals)
        hits = []
        for _, record in sorted(selected, key=lambda pair: pair[1].journal_seq):
            evidence = _evidence_of(record)
            assert evidence is not None  # qualifying implies the triple
            hits.append(
                RuleMatch(
                    journal_seq=record.journal_seq,
                    event_type=record.event_type,
                    evidence=evidence,
                    affected_node_ids=[record.node_id] if record.node_id else [],
                    summary=_render_summary(self.summary_template, record.payload),
                )
            )
        return tuple(hits)


# --- interpreter internals -----------------------------------------------------


def _group_key(group_by: Sequence[str], record: ObservationRecord) -> tuple:
    return tuple(
        record.node_id if dimension == "node_id" else record.pid
        for dimension in group_by
    )


def _window_selected(
    spec: MatchSpec,
    qualifying: list[tuple[tuple, ObservationRecord]],
    group_totals: Mapping[tuple, int],
) -> list[tuple[tuple, ObservationRecord]]:
    """Apply the window aggregate per declared group (None window = any
    single qualifying hit)."""
    if spec.window is None:
        return qualifying
    window = spec.window
    counts: dict[tuple, int] = {}
    for key, _ in qualifying:
        counts[key] = counts.get(key, 0) + 1
    if window.aggregation == "count":
        return [
            pair for pair in qualifying if counts[pair[0]] >= window.min_count
        ]
    # rate: qualifying share among the group's records of the event type
    return [
        pair
        for pair in qualifying
        if counts[pair[0]] / group_totals[pair[0]] >= window.min_rate
    ]


def _evidence_of(record: ObservationRecord) -> Optional[EvidenceRef]:
    """The artifact anchor from the diagnosis payload key contract
    (ticket #54): ``artifact_id``/``pid``/``packet_index``. Records
    without the full triple produce no hit — a candidate cannot exist
    without an evidence anchor (SPEC-306 §6)."""
    payload = record.payload
    artifact_id = payload.get("artifact_id")
    pid = payload.get("pid")
    packet_index = payload.get("packet_index")
    if not (
        isinstance(artifact_id, str)
        and artifact_id
        and _is_int(pid)
        and 0 <= pid <= 8191
        and _is_int(packet_index)
        and packet_index >= 0
    ):
        return None
    return EvidenceRef(artifact_id=artifact_id, pid=pid, packet_index=packet_index)


def _validate_summary_template(template: str) -> None:
    """The template is DATA: plain payload-key placeholders only —
    attribute/index access and unbalanced braces fail the load (§8 row 1,
    declarative red line)."""
    try:
        parsed = list(Formatter().parse(template))
    except ValueError as exc:
        raise RuleDefinitionError(
            f"summary_template {template!r} does not parse: {exc}"
        ) from exc
    for _, field_name, _, _ in parsed:
        if field_name is None:
            continue
        if not _TEMPLATE_FIELD_PATTERN.match(field_name):
            raise RuleDefinitionError(
                f"summary_template placeholder {field_name!r} must be a"
                " plain payload key (no attribute/index access)"
            )


def _render_summary(template: str, payload: Mapping[str, Any]) -> str:
    """Render the template over the payload; an unresolvable key falls
    back to the raw template (deterministic, never raises)."""
    try:
        return Formatter().vformat(template, (), dict(payload))
    except (KeyError, IndexError, ValueError):
        return template
