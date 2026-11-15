"""Diagnosis orchestration — the SPEC-306 §5 ``DiagnosisEngine`` face
(ticket #54).

:class:`DiagnosisService` implements the batch evaluation boundary: it
reads the SPEC-502 journal through an injected read face (structural
``JournalReader`` — the domain never touches storage), evaluates the
ruleset through the pure :class:`domain.diagnosis.DiagnosisEvaluator`,
then commits the lifecycle: upsert the ``diagnoses`` table
(REQ-DIA-306-004) and publish ``diagnosis.raised/updated/cleared``
through the SPEC-300 §12 ``EventPublisher`` producer face.

Trigger model (SPEC-306 §4): MVP = run-end batch evaluation —
:func:`bind_run_completion_trigger` subscribes to the #47 gateway commit
fan-out and calls ``evaluate`` when ``simulation.run_completed`` /
``simulation.run_failed`` commits. ``rules=None`` resolves through the
injectable ``rules_provider`` (the SPEC-307 registered ruleset — absent
until ticket #55, in which case the evaluation honestly reports the
empty ruleset instead of pretending, SPEC-306 §8 row 1).

Error mapping (SPEC-306 §8 + SPEC-500 §6):

- journal read failure → ``ServiceUnavailableError(OBS_STORAGE_UNAVAILABLE)``
  (HTTP 503 via the declarative api mapping);
- unknown session/run → ``NotFoundError`` (HTTP 404);
- rule isolation / skipped payloads / no match stay inside the domain
  evaluator as warnings and never fail the evaluation.

Clocks follow the SPEC-201 injection discipline: ``now_utc_ms`` is
injectable (tests inject exact integers; production defaults to the wall
clock). The derived events' virtual ``time.source`` anchors to the latest
observed ``value_ns`` of the run's observations (deterministic replay;
0 when the run has no observations) — recorded as a ticket #54 posture.
"""

from __future__ import annotations

import sqlite3
import time
from typing import Any, Callable, Optional, Protocol, Sequence

from adapters.storage.errors import StorageError
from adapters.storage.repositories import DiagnosisRecord, DiagnosisRepository
from application.errors import NotFoundError, ServiceUnavailableError
from application.observation.errors import OBS_STORAGE_UNAVAILABLE
from domain.diagnosis.engine import (
    DiagnosisEvaluator,
    EvaluationOutcome,
    EvaluationRule,
    GroupedCandidate,
    ObservationRecord,
    suppression_node_key,
)
from domain.diagnosis.events import (
    cleared_envelope,
    raised_envelope,
    updated_envelope,
)
from domain.diagnosis.report import DiagnosisReport
from domain.observation.registry import TS_EVENT_TYPES

__all__ = [
    "DiagnosisService",
    "JournalReader",
    "TERMINAL_RUN_EVENT_TYPES",
    "bind_run_completion_trigger",
]

#: SPEC-306 §4: the run-end trigger point (batch evaluation happens when
#: the run reaches a terminal state).
TERMINAL_RUN_EVENT_TYPES = frozenset(
    {"simulation.run_completed", "simulation.run_failed"}
)

#: Rules provider: resolves the SPEC-307 registered ruleset (ticket #55
#: owns the real registry; until then the provider is None → honest empty
#: ruleset per SPEC-306 §8).
RulesProvider = Callable[[], Optional[Sequence[EvaluationRule]]]

#: Wall clock injection (SPEC-201 discipline): epoch-ms source.
NowUtcMs = Callable[[], int]

#: Journal read page (== the SPEC-502 hard cap; pagination walks pages).
_PAGE_LIMIT = 2_000

_CLEARED_REASON_TEMPLATE = (
    "no matching observations for code {code} in the re-evaluation of run"
    " {run_id} (SPEC-306 §7 cleared)"
)


class JournalReader(Protocol):
    """Structural subset of the SPEC-502 journal read face.

    Both application read protocols satisfy it (the gateway's
    ``EventJournal`` and the consumer's ``TailableJournal``); the
    authoritative protocol lives in ``adapters.storage.journal``.
    """

    def query(
        self, session_id: str, *, after_seq: int = 0, limit: int = 100
    ) -> Sequence[Any]: ...

    def max_seq(self, session_id: str) -> int: ...


class DiagnosisPublisher(Protocol):
    """SPEC-300 §12 producer face (structural)."""

    def publish(self, event: Any) -> Any: ...


def _default_now_utc_ms() -> int:
    return int(time.time() * 1000)


class DiagnosisService:
    """Run-end batch evaluation + lifecycle commit (SPEC-306 §5)."""

    def __init__(
        self,
        journal: JournalReader,
        publisher: DiagnosisPublisher,
        repository: DiagnosisRepository,
        *,
        rules_provider: RulesProvider | None = None,
        now_utc_ms: NowUtcMs | None = None,
    ) -> None:
        self._journal = journal
        self._publisher = publisher
        self._repository = repository
        self._rules_provider = rules_provider
        self._now_utc_ms: NowUtcMs = now_utc_ms or _default_now_utc_ms

    # --- SPEC-306 §5 face -------------------------------------------------------

    def evaluate(
        self, session_id: str, run_id: str, *, rules: Sequence[EvaluationRule] | None = None
    ) -> DiagnosisReport:
        """Batch-evaluate one run and commit the diagnosis lifecycle.

        ``rules=None`` resolves the registered ruleset via the injectable
        provider; when no ruleset is registered the evaluation is an
        honest empty report (SPEC-306 §8 row 1) — no rows are touched
        (clearing requires an explicit ruleset, see ``_commit_clears``).
        """
        records = self._read_run_observations(session_id, run_id)
        ruleset = rules
        if ruleset is None and self._rules_provider is not None:
            ruleset = self._rules_provider()
        stored_rows = [
            row for row in self._query_rows(session_id) if row.run_id == run_id
        ]
        existing = {
            (row.code, suppression_node_key(row.affected_node_ids)): row.diagnosis_id
            for row in stored_rows
            if row.state == "raised"
        }
        now_ms = self._now_utc_ms()
        outcome = DiagnosisEvaluator().evaluate(
            session_id,
            run_id,
            records,
            ruleset,
            existing=existing,
            now_utc_ms=now_ms,
        )
        report = self._commit_lifecycle(
            session_id,
            outcome,
            stored_rows,
            records,
            rules_provided=ruleset is not None,
        )
        return report

    def list_diagnoses(self, session_id: str) -> list[DiagnosisRecord]:
        """The diagnoses-table view (SPEC-500 §4.4 list endpoint)."""
        rows = self._query_rows(session_id)
        if not rows and self._journal_max_seq(session_id) == 0:
            raise NotFoundError(
                "SIM_SESSION_NOT_FOUND",
                f"unknown session {session_id!r}: no stored diagnoses and"
                " no journal events (SPEC-500 §6 row 404)",
            )
        return rows

    # --- internals ----------------------------------------------------------------

    def _read_run_observations(
        self, session_id: str, run_id: str
    ) -> list[ObservationRecord]:
        """Read the run's observation-class records from the journal.

        Pagination walks the full session stream (hard-capped pages);
        records of the run outside the ``ts.*`` observation family are
        skipped (fault.*/simulation.* engine events are NOT observations,
        brief §6; the domain only sees observation records).
        """
        records: list[ObservationRecord] = []
        saw_run = False
        after_seq = 0
        while True:
            rows = self._journal_query(session_id, after_seq=after_seq, limit=_PAGE_LIMIT)
            if not rows:
                break
            for row in rows:
                after_seq = max(after_seq, int(row.journal_seq))
                envelope = row.envelope
                scope = envelope.get("scope") or {}
                if scope.get("run_id") != run_id:
                    continue
                saw_run = True
                if row.event_type not in TS_EVENT_TYPES:
                    continue
                correlation = envelope.get("correlation") or {}
                records.append(
                    ObservationRecord(
                        journal_seq=int(row.journal_seq),
                        event_type=row.event_type,
                        event_id=str(envelope.get("event_id")),
                        payload=dict(envelope.get("payload") or {}),
                        node_id=correlation.get("node_id"),
                        pid=correlation.get("pid"),
                        source_ns=int(
                            (envelope.get("time") or {})
                            .get("source", {})
                            .get("value_ns", 0)
                        ),
                    )
                )
            if len(rows) < _PAGE_LIMIT:
                break
        if not saw_run:
            raise NotFoundError(
                "SIM_RUN_NOT_FOUND",
                f"unknown run {run_id!r} in session {session_id!r}: no"
                " journal events carry this run (SPEC-500 §6 row 404)",
            )
        return records

    def _commit_lifecycle(
        self,
        session_id: str,
        outcome: EvaluationOutcome,
        stored_rows: list[DiagnosisRecord],
        records: Sequence[ObservationRecord],
        *,
        rules_provided: bool,
    ) -> DiagnosisReport:
        """Upsert rows + publish the lifecycle events (REQ-DIA-306-004).

        Emission granularity is per hit for NEW groups (SPEC-307 §5
        suppression: one raised, each further hit accumulates one updated
        with cumulative refs); re-evaluated groups emit a single updated
        only when their accumulated refs actually differ from the stored
        row (idempotent re-evaluation emits nothing).
        """
        now_ms = outcome.report.evaluated_at_utc_ms
        observed_ns = now_ms * 1_000_000
        # Deterministic virtual-time anchor: the latest observed source_ns
        # of the run's observations (0 when none — posture recorded in the
        # module docstring / ticket #54 report).
        source_ns = max((record.source_ns for record in records), default=0)
        stored_by_id = {row.diagnosis_id: row for row in stored_rows}
        publish_warnings: list[str] = []

        for group in outcome.groups:
            candidate = group.candidate
            refs = [
                {"journal_seq": ref.journal_seq, "event_type": ref.event_type}
                for ref in group.hit_refs
            ]
            stored = stored_by_id.get(candidate.diagnosis_id)
            if group.is_new:
                self._publish(
                    raised_envelope(
                        candidate,
                        session_id=session_id,
                        observation_refs=group.hit_refs[:1],
                        source_ns=source_ns,
                        observed_ns=observed_ns,
                    ),
                    publish_warnings,
                )
                for index in range(1, len(group.hit_refs)):
                    self._publish(
                        updated_envelope(
                            candidate,
                            session_id=session_id,
                            observation_refs=group.hit_refs[: index + 1],
                            source_ns=source_ns,
                            observed_ns=observed_ns,
                        ),
                        publish_warnings,
                    )
            else:
                stored_refs = stored.observation_refs if stored is not None else []
                if stored_refs == refs:
                    continue  # idempotent re-evaluation: no twin events
                self._publish(
                    updated_envelope(
                        candidate,
                        session_id=session_id,
                        observation_refs=list(group.hit_refs),
                        source_ns=source_ns,
                        observed_ns=observed_ns,
                    ),
                    publish_warnings,
                )
            self._repository.upsert(self._record_of(session_id, group, stored, now_ms))

        self._commit_clears(
            session_id,
            outcome,
            stored_rows,
            source_ns,
            observed_ns,
            publish_warnings,
            rules_provided=rules_provided,
        )

        if publish_warnings:
            return outcome.report.model_copy(
                update={
                    "warnings": outcome.report.warnings + tuple(publish_warnings)
                }
            )
        return outcome.report

    def _commit_clears(
        self,
        session_id: str,
        outcome: EvaluationOutcome,
        stored_rows: list[DiagnosisRecord],
        source_ns: int,
        observed_ns: int,
        publish_warnings: list[str],
        *,
        rules_provided: bool,
    ) -> None:
        """Clear stored raised rows whose code produced no candidate.

        Only explicit-ruleset evaluations clear: a ``rules=None``
        evaluation with no registered ruleset is a no-op (SPEC-306 §8
        empty-report row) and must not wipe prior results.
        """
        if not rules_provided:
            return
        found_codes = {group.candidate.code for group in outcome.groups}
        now_ms = outcome.report.evaluated_at_utc_ms
        for row in stored_rows:
            if row.state != "raised" or row.code in found_codes:
                continue
            self._publish(
                cleared_envelope(
                    diagnosis_id=row.diagnosis_id,
                    rule_id=row.rule_id,
                    session_id=session_id,
                    run_id=row.run_id,
                    reason=_CLEARED_REASON_TEMPLATE.format(
                        code=row.code, run_id=row.run_id
                    ),
                    source_ns=source_ns,
                    observed_ns=observed_ns,
                ),
                publish_warnings,
            )
            self._repository.clear(row.diagnosis_id, cleared_at_utc_ms=now_ms)

    def _record_of(
        self,
        session_id: str,
        group: GroupedCandidate,
        stored: Optional[DiagnosisRecord],
        now_ms: int,
    ) -> DiagnosisRecord:
        candidate = group.candidate
        # An updated candidate keeps its original raise time (R3: the
        # row's raised_at is the FIRST raise of this diagnosis identity).
        raised_at = stored.raised_at if stored is not None else now_ms
        return DiagnosisRecord(
            diagnosis_id=candidate.diagnosis_id,
            session_id=session_id,
            run_id=candidate.run_id,
            rule_id=candidate.rule_id,
            rule_version=candidate.rule_version,
            code=candidate.code,
            severity=candidate.severity.value,
            confidence=candidate.confidence.value,
            observation_refs=[
                {"journal_seq": ref.journal_seq, "event_type": ref.event_type}
                for ref in candidate.observation_refs
            ],
            affected_node_ids=list(candidate.affected_node_ids),
            suggested_actions=list(candidate.suggested_actions),
            state="raised",
            raised_at=raised_at,
            cleared_at=None,
        )

    def _publish(self, document: dict, warnings: list[str]) -> None:
        receipt = self._publisher.publish(document)
        accepted = getattr(receipt, "accepted", True)
        if not accepted:
            warnings.append(
                "diagnosis event"
                f" {document.get('event_type')!r} was not accepted by the"
                " gateway"
                f" ({getattr(receipt, 'error_code', None) or 'rejected'});"
                " the table row stays authoritative"
            )

    def _query_rows(self, session_id: str) -> list[DiagnosisRecord]:
        try:
            return list(self._repository.query(session_id))
        except (sqlite3.Error, StorageError) as exc:
            raise ServiceUnavailableError(
                OBS_STORAGE_UNAVAILABLE,
                f"diagnoses table unavailable: {exc}",
            ) from exc

    def _journal_query(self, session_id: str, *, after_seq: int, limit: int):
        try:
            return self._journal.query(session_id, after_seq=after_seq, limit=limit)
        except (sqlite3.Error, StorageError) as exc:
            raise ServiceUnavailableError(
                OBS_STORAGE_UNAVAILABLE,
                f"journal query failed: {exc} (SPEC-306 §8: storage unavailable)",
            ) from exc

    def _journal_max_seq(self, session_id: str) -> int:
        try:
            return int(self._journal.max_seq(session_id))
        except (sqlite3.Error, StorageError) as exc:
            raise ServiceUnavailableError(
                OBS_STORAGE_UNAVAILABLE,
                f"journal watermark unavailable: {exc}",
            ) from exc


def bind_run_completion_trigger(
    gateway: Any,
    engine: Callable[[str, str], DiagnosisReport],
) -> Callable[[dict[str, Any]], None]:
    """SPEC-306 §4 run-end trigger: evaluate when a terminal run event
    commits (gateway commit fan-out). Subscriber errors are counted by
    the gateway and never break ingestion (SPEC-300 §7)."""
    def _on_committed(envelope: dict[str, Any]) -> None:
        if envelope.get("event_type") not in TERMINAL_RUN_EVENT_TYPES:
            return
        scope = envelope.get("scope") or {}
        session_id = scope.get("session_id")
        run_id = scope.get("run_id")
        if not session_id or not run_id:
            return
        engine.evaluate(session_id, run_id)

    gateway.subscribe(_on_committed)
    return _on_committed
