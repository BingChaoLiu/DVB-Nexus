"""Verification orchestration — journal in, verdict out (ticket #56).

:class:`VerificationService` closes the SPEC-206 loop over the REAL chain:
it reads the SPEC-502 journal through an injected read face (structural
``JournalReader`` — the domain never touches storage), partitions the run
evidence (``fault.*`` lifecycle facts per run, normalized ``ts.*``
observations, run boundaries), evaluates through the pure
:mod:`simulation.verification.engine`, then commits the verdict: persist
the §4 result structure (``verification_verdicts``, migration 003) and
publish ``recovery.verification_completed`` through the SPEC-300 §12
``EventPublisher`` producer face.

Identity and error mapping (SPEC-206 §8 → HTTP rows live in the api port
adapter; the service raises the simulation error family):

- unknown session (no journal events at all) → ``SessionNotFoundError``
  (404 semantics, same as the SPEC-200 face);
- candidate run with no journal events in the session →
  ``VerificationRunMismatchError`` (SIM_VERIF_RUN_MISMATCH, §8: 拒绝 —
  the run cannot be attributed to this session's scenario context; the
  MVP form is recorded in the ticket #56 report, the scenario registry
  (SPEC-500 §4.7) lands separately);
- journal/verdict-table failures → ``SimulationIOError`` (SIM_IO_ERROR);
  the api port adapter maps that code onto the storage-unavailable HTTP
  row (503), the same posture the diagnosis service's adapter takes.

Clocks follow the SPEC-201 injection discipline: ``now_utc_ms`` injectable
(operational verification timestamp). The derived event's virtual
``time.source`` anchors to the latest observed ``value_ns`` of the
recovery run's events (deterministic replay; 0 when none) — the recorded
ticket #54 posture.
"""

from __future__ import annotations

import sqlite3
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol, Sequence

from adapters.storage.errors import StorageError
from adapters.storage.repositories import (
    SqliteVerificationRepository,
    VerdictRecord,
)
from domain.observation.registry import FAULT_EVENT_TYPES, TS_EVENT_TYPES
from simulation.errors import (
    SessionNotFoundError,
    SimulationIOError,
    VerificationRunMismatchError,
)
from simulation.verification.engine import (
    CriterionResult,
    EvaluationInput,
    FaultEventRecord,
    ObservationRecord,
    VerificationOutcome,
    evaluate,
)
from simulation.verification.events import verification_completed_envelope

__all__ = [
    "JournalReader",
    "VerificationResult",
    "VerificationService",
    "VerifierPublisher",
]

#: Journal read page (== the SPEC-502 hard cap; pagination walks pages).
_PAGE_LIMIT = 2_000

_RUN_COMPLETED = "simulation.run_completed"
_RUN_OPEN = "simulation.run_started"

#: Wall clock injection (SPEC-201 discipline): epoch-ms source.
NowUtcMs = Callable[[], int]


class JournalReader(Protocol):
    """Structural subset of the SPEC-502 journal read face (the gateway's
    ``EventJournal`` protocol; the authoritative protocol lives in
    ``adapters.storage.journal``)."""

    def query(
        self, session_id: str, *, after_seq: int = 0, limit: int = 100
    ) -> Sequence[Any]: ...

    def max_seq(self, session_id: str) -> int: ...


class VerifierPublisher(Protocol):
    """SPEC-300 §12 producer face (structural; production impl: the #47
    gateway/publisher)."""

    def publish(self, event: Any) -> Any: ...


def _default_now_utc_ms() -> int:
    return int(time.time() * 1000)


@dataclass(frozen=True)
class VerificationResult:
    """The §4 verdict + the identity fields the API DTO mirrors.

    ``criteria``/``evidence_refs`` are the engine's projections verbatim;
    ``verified_at_utc_ms`` is the operational timestamp (the only field
    exempt from replay equality).
    """

    session_id: str
    recovery_run_id: str
    baseline_run_id: str
    scenario_id: str
    scenario_version: str
    scenario_content_hash: str
    outcome: VerificationOutcome
    verified_at_utc_ms: int

    @property
    def verdict(self) -> str:
        return self.outcome.verdict

    @property
    def criteria(self) -> tuple[CriterionResult, ...]:
        return self.outcome.criteria

    @property
    def evidence_refs(self) -> tuple[Mapping[str, Any], ...]:
        return self.outcome.evidence_refs

    @property
    def summary(self) -> str:
        return self.outcome.summary


class VerificationService:
    """Journal reads + engine evaluation + verdict persistence + event."""

    def __init__(
        self,
        journal: JournalReader,
        publisher: VerifierPublisher,
        repository: SqliteVerificationRepository,
        *,
        now_utc_ms: NowUtcMs | None = None,
    ) -> None:
        self._journal = journal
        self._publisher = publisher
        self._repository = repository
        self._now_utc_ms: NowUtcMs = now_utc_ms or _default_now_utc_ms

    # --- SPEC-206 face -------------------------------------------------------

    def verify(
        self,
        session_id: str,
        recovery_run_id: str,
        *,
        baseline_run_id: str,
        scenario_id: str,
        scenario_version: str,
        scenario_content_hash: str,
        pass_criteria: Sequence[Any],
        ui_state: Any = None,
    ) -> VerificationResult:
        """Evaluate the candidate recovery run and commit the verdict."""
        facts = _read_session_facts(self._journal_query, self._journal_max_seq, session_id)
        if recovery_run_id not in facts.run_started:
            raise VerificationRunMismatchError(
                f"candidate run {recovery_run_id!r} has no journal events in"
                f" session {session_id!r}: the run cannot be attributed to"
                " this scenario context (SPEC-206 §8 SIM_VERIF_RUN_MISMATCH)"
            )
        input = EvaluationInput(
            session_id=session_id,
            baseline_run_id=baseline_run_id,
            recovery_run_id=recovery_run_id,
            scenario_id=scenario_id,
            scenario_version=scenario_version,
            scenario_content_hash=scenario_content_hash,
            pass_criteria=pass_criteria,
            baseline_fault_events=tuple(
                event
                for event in facts.fault_events
                if event.run_id == baseline_run_id
            ),
            recovery_fault_events=tuple(
                event
                for event in facts.fault_events
                if event.run_id == recovery_run_id
            ),
            recovery_observations=tuple(
                record
                for record in facts.observations
                if record.run_id == recovery_run_id
            ),
            recovery_run_completed=recovery_run_id in facts.run_completed,
            ui_state=ui_state,
        )
        outcome = evaluate(input)
        now_ms = self._now_utc_ms()
        record = VerdictRecord(
            verdict_id=str(uuid.uuid4()),
            session_id=session_id,
            run_id=recovery_run_id,
            baseline_run_id=baseline_run_id,
            scenario_id=scenario_id,
            scenario_version=scenario_version,
            scenario_content_hash=scenario_content_hash,
            verdict=outcome.verdict,
            criteria=[
                _criterion_projection(entry) for entry in outcome.criteria
            ],
            evidence_refs=[dict(ref) for ref in outcome.evidence_refs],
            summary=outcome.summary,
            verified_at_utc_ms=now_ms,
        )
        # Persistence first (the row is the audit authority), then the
        # delivery-protected event (SPEC-206 §4: 判定结果经信封发射并持久化).
        try:
            self._repository.save(record)
        except (sqlite3.Error, StorageError) as exc:
            raise SimulationIOError(
                f"verdict persistence failed: {exc} (SPEC-206 storage row)"
            ) from exc
        self._publish(
            outcome,
            session_id=session_id,
            recovery_run_id=recovery_run_id,
            baseline_run_id=baseline_run_id,
            scenario_id=scenario_id,
            scenario_version=scenario_version,
            scenario_content_hash=scenario_content_hash,
            latest_source_ns=facts.latest_source_ns,
        )
        return VerificationResult(
            session_id=session_id,
            recovery_run_id=recovery_run_id,
            baseline_run_id=baseline_run_id,
            scenario_id=scenario_id,
            scenario_version=scenario_version,
            scenario_content_hash=scenario_content_hash,
            outcome=outcome,
            verified_at_utc_ms=now_ms,
        )

    def list_verdicts(self, session_id: str) -> list[VerdictRecord]:
        """The verdicts-table view (audit face; the SPEC-500 §4 freeze
        carries only POST verify — no additional route)."""
        try:
            return self._repository.query(session_id)
        except (sqlite3.Error, StorageError) as exc:
            raise SimulationIOError(
                f"verdicts table unavailable: {exc}"
            ) from exc

    # --- internals -------------------------------------------------------------

    def _publish(
        self,
        outcome: VerificationOutcome,
        *,
        session_id: str,
        recovery_run_id: str,
        baseline_run_id: str,
        scenario_id: str,
        scenario_version: str,
        scenario_content_hash: str,
        latest_source_ns: int,
    ) -> None:
        payload = {
            "verdict": outcome.verdict,
            "run_id": recovery_run_id,
            "baseline_run_id": baseline_run_id,
            "scenario_id": scenario_id,
            "scenario_version": scenario_version,
            "scenario_content_hash": scenario_content_hash,
            "criteria": [
                _criterion_projection(entry) for entry in outcome.criteria
            ],
            "summary": outcome.summary,
        }
        document = verification_completed_envelope(
            session_id=session_id,
            payload=payload,
            source_ns=latest_source_ns,
            observed_ns=self._now_utc_ms() * 1_000_000,
        )
        self._publisher.publish(document)

    def _journal_query(self, session_id: str, *, after_seq: int):
        try:
            return self._journal.query(
                session_id, after_seq=after_seq, limit=_PAGE_LIMIT
            )
        except (sqlite3.Error, StorageError) as exc:
            raise SimulationIOError(
                f"journal query failed: {exc} (verification evidence read)"
            ) from exc

    def _journal_max_seq(self, session_id: str) -> int:
        try:
            return int(self._journal.max_seq(session_id))
        except (sqlite3.Error, StorageError) as exc:
            raise SimulationIOError(
                f"journal watermark unavailable: {exc}"
            ) from exc


def _read_session_facts(query, max_seq, session_id: str) -> "_SessionFacts":
    """Walk the session journal once and partition the evidence."""
    if int(max_seq(session_id)) == 0:
        raise SessionNotFoundError(
            f"session_id {session_id!r} has no journal events on this"
            " deployment (unknown session; SPEC-500 §6 row 404)"
        )
    facts = _SessionFacts()
    after_seq = 0
    while True:
        rows = query(session_id, after_seq=after_seq)
        if not rows:
            break
        for row in rows:
            after_seq = max(after_seq, int(row.journal_seq))
            facts.absorb(row)
        if len(rows) < _PAGE_LIMIT:
            break
    return facts


def _criterion_projection(entry: CriterionResult) -> dict[str, Any]:
    return {
        "criterion_id": entry.criterion_id,
        "kind": entry.kind,
        "mandatory": entry.mandatory,
        "result": entry.result,
        "reason_code": entry.reason_code,
        "reason": entry.reason,
    }


class _SessionFacts:
    """One journal walk's partitioned evidence (per run)."""

    __slots__ = (
        "fault_events",
        "observations",
        "run_started",
        "run_completed",
        "latest_source_ns",
    )

    def __init__(self) -> None:
        self.fault_events: list[FaultEventRecord] = []
        self.observations: list[ObservationRecord] = []
        self.run_started: set[str] = set()
        self.run_completed: set[str] = set()
        self.latest_source_ns = 0

    def absorb(self, row: Any) -> None:
        envelope = row.envelope
        scope = envelope.get("scope") or {}
        run_id = scope.get("run_id")
        source_ns = int(
            (envelope.get("time") or {}).get("source", {}).get("value_ns", 0)
        )
        self.latest_source_ns = max(self.latest_source_ns, source_ns)
        event_type = row.event_type
        if event_type == _RUN_OPEN and run_id:
            self.run_started.add(run_id)
            return
        if event_type == _RUN_COMPLETED and run_id:
            self.run_completed.add(run_id)
            return
        correlation = envelope.get("correlation") or {}
        payload = envelope.get("payload") or {}
        if event_type in FAULT_EVENT_TYPES and run_id:
            self.fault_events.append(
                FaultEventRecord(
                    journal_seq=int(row.journal_seq),
                    event_type=event_type,
                    fault_id=str(
                        payload.get("fault_id")
                        or correlation.get("fault_id")
                        or ""
                    ),
                    fault_type=str(payload.get("fault_type") or ""),
                    node_id=correlation.get("node_id"),
                    pid=correlation.get("pid"),
                    run_id=run_id,
                    payload=dict(payload),
                )
            )
            return
        if event_type in TS_EVENT_TYPES and run_id:
            self.observations.append(
                ObservationRecord(
                    journal_seq=int(row.journal_seq),
                    event_type=event_type,
                    payload=dict(payload),
                    node_id=correlation.get("node_id"),
                    pid=correlation.get("pid"),
                    run_id=run_id,
                )
            )
