"""Timeline recorder — the six-kind record store fed by gateway fan-out
(SPEC-303 §3; SPEC-300 §7 step 5 "指标/时间轴/告警组件幂等更新").

Write faces:

- ``attach_gateway`` / ``record_event_document`` — ``event`` records come
  from the gateway commit fan-out: every committed envelope (already
  stamped with ``journal_seq``) projects to a timeline record keeping the
  ORIGINAL ``event_id`` + ``journal_seq`` (REQ-OBS-303-001: 证据链不断).
  The projection re-parses the envelope through the frozen #46 surface —
  an invalid document never enters the store.
- ``record_checkpoint`` — ``checkpoint`` records from consumer journal_seq
  advancement. A checkpoint is an OBSERVATION behavior (SPEC-303 §5):
  this face touches no simulation object, pauses nothing, mutates nothing
  (Must-not OBS-D; authoritative simulation snapshots stay SPEC-200).
- ``add_snapshot`` / ``add_annotation`` / ``add_bookmark`` — MVP write
  faces with explicit timepoints (no automated producer yet; scope
  declared in the ticket report).
- ``delete_records`` — §8 deletion: records are replaced IN PLACE by
  explicit tombstones (no dangling seemingly-valid references, no
  sequence shift). Note the journal itself is NOT touched: timeline
  deletion is a projection-layer operation (SPEC-502 owns journal
  retention).

Record identity is content-derived (SHA-256 over the canonical record
document): identical content yields identical ids, so exports of the same
journal interval reproduce byte-for-byte across recorder restarts
(SPEC-303 §7 reproducibility).

Thread posture: a single lock guards the per-session store, mirroring the
gateway's fan-out contract (subscribers run on the drain caller's thread).
"""

from __future__ import annotations

import hashlib
import json
import threading
from typing import Any, Iterable, Optional

from domain.observation import (
    CheckpointRecord,
    EventEnvelope,
    TimelineRecord,
    TimelineRecordKind,
    TimelineTimepoint,
    TimepointSemantics,
    parse_envelope,
)

#: Source id stamped on records the recorder itself originates.
RECORDER_SOURCE_ID = "timeline-recorder"

_TOMBSTONE_KEY = "tombstone"


class TimelineRecorder:
    """In-memory append-only per-session timeline store (MVP).

    The journal remains the durable event authority; the recorder holds the
    projected timeline records (events from fan-out + operator/checkpoint
    writes). Querying runs through
    :class:`application.observation.timeline.service.TimelineService`.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._records: dict[str, list[TimelineRecord]] = {}
        self._event_keys: set[tuple[str, int]] = set()

    # --- event projection (gateway fan-out) ----------------------------------

    def attach_gateway(self, gateway: Any) -> None:
        """Subscribe to the gateway commit fan-out (SPEC-300 §7 step 5).

        The gateway counts subscriber exceptions without breaking ingestion,
        so a projection failure degrades the timeline, never the journal.
        """
        gateway.subscribe(self._on_commit)

    def _on_commit(self, stamped: dict) -> None:
        self.record_event_document(stamped)

    def record_event_document(self, stamped: dict) -> TimelineRecord:
        """Project one gateway-committed envelope document to an event record.

        ``stamped`` must be a SPEC-301 envelope dict carrying the gateway
        journal_seq stamp. Duplicate commits (same session + journal_seq)
        return the existing record — fan-out redelivery is idempotent.
        Raises ValueError for a missing stamp and re-raises
        :class:`EnvelopeError` for malformed documents (nothing is stored).
        """
        journal_seq = stamped.get("journal_seq") if isinstance(stamped, dict) else None
        if (
            not isinstance(journal_seq, int)
            or isinstance(journal_seq, bool)
            or journal_seq < 0
        ):
            raise ValueError(
                "event projection requires the gateway journal_seq stamp "
                "(REQ-OBS-303-001); producers never self-assign it"
            )
        envelope = parse_envelope(stamped)  # raises EnvelopeError on violation
        session_id = envelope.scope.session_id
        if not session_id:
            # Same boundary as the SPEC-502 journal stamp key (ticket #23 R4):
            # the MVP registry has no system-level sessionless events.
            raise ValueError("event projection requires a session-scoped envelope")
        key = (session_id, journal_seq)
        record = self._with_content_id(
            self._project_event_record(envelope, stamped)
        )
        with self._lock:
            if key in self._event_keys:
                for existing in self._records.get(session_id, []):
                    if (
                        existing.record_kind is TimelineRecordKind.EVENT
                        and existing.journal_seq == journal_seq
                    ):
                        return existing
            self._event_keys.add(key)
            self._records.setdefault(session_id, []).append(record)
        return record

    # --- checkpoint / operator write faces -----------------------------------

    def add_record(self, record: TimelineRecord) -> TimelineRecord:
        """Generic cross-source write face: append a fully-formed record.

        Snapshot/annotation/bookmark-style records built by callers (tests,
        replay tools) enter the store here; identity is re-derived from
        content so equal content keeps one stable id.
        """
        return self._append(record)

    def record_checkpoint(
        self,
        checkpoint: CheckpointRecord,
        *,
        source_id: str = RECORDER_SOURCE_ID,
        timepoint: Optional[TimelineTimepoint] = None,
    ) -> TimelineRecord:
        """Record a consumer-progress checkpoint (SPEC-303 §5).

        Default record timepoint: the checkpoint's virtual time (source
        semantics, its clock domain) when present, else ``created_at``
        (observed wall reading) — field names carry the semantics, §5.
        """
        if timepoint is None:
            if checkpoint.virtual_time_ns is not None:
                timepoint = TimelineTimepoint(
                    value_ns=checkpoint.virtual_time_ns,
                    clock_domain=checkpoint.clock_domain,
                    clock_epoch=0,
                    semantics=TimepointSemantics.SOURCE,
                )
            else:
                timepoint = checkpoint.created_at
        record = TimelineRecord(
            record_kind=TimelineRecordKind.CHECKPOINT,
            record_id="pending",
            session_id=checkpoint.session_id,
            source_id=source_id,
            source_seq=checkpoint.journal_seq,
            journal_seq=None,
            timepoint=timepoint,
            tags=(),
            payload=checkpoint.model_dump(mode="json"),
        )
        return self._append(record)

    def add_annotation(
        self,
        *,
        session_id: str,
        source_id: str,
        timepoint: TimelineTimepoint,
        payload: Optional[dict[str, Any]] = None,
        tags: tuple[str, ...] = (),
        scenario_id: Optional[str] = None,
        run_id: Optional[str] = None,
    ) -> TimelineRecord:
        """Operator/system annotation (SPEC-303 §3; explicit timepoint)."""
        return self._append(
            TimelineRecord(
                record_kind=TimelineRecordKind.ANNOTATION,
                record_id="pending",
                session_id=session_id,
                scenario_id=scenario_id,
                run_id=run_id,
                source_id=source_id,
                timepoint=timepoint,
                tags=tuple(tags),
                payload=dict(payload or {}),
            )
        )

    def add_bookmark(
        self,
        *,
        session_id: str,
        source_id: str,
        name: str,
        timepoint: TimelineTimepoint,
        payload: Optional[dict[str, Any]] = None,
        tags: tuple[str, ...] = (),
        scenario_id: Optional[str] = None,
        run_id: Optional[str] = None,
    ) -> TimelineRecord:
        """Named position for training/diagnosis use (SPEC-303 §3)."""
        body = dict(payload or {})
        body["name"] = name
        return self._append(
            TimelineRecord(
                record_kind=TimelineRecordKind.BOOKMARK,
                record_id="pending",
                session_id=session_id,
                scenario_id=scenario_id,
                run_id=run_id,
                source_id=source_id,
                timepoint=timepoint,
                tags=tuple(tags),
                payload=body,
            )
        )

    def add_snapshot(
        self,
        *,
        session_id: str,
        source_id: str,
        snapshot_version: str,
        timepoint: TimelineTimepoint,
        payload: Optional[dict[str, Any]] = None,
        tags: tuple[str, ...] = (),
        scenario_id: Optional[str] = None,
        run_id: Optional[str] = None,
    ) -> TimelineRecord:
        """Source-attributed, versioned state snapshot (SPEC-303 §3).

        The authoritative simulation snapshot stays SPEC-200's; this face
        records a timeline projection of one (with source + version).
        """
        body = dict(payload or {})
        body["snapshot_version"] = snapshot_version
        return self._append(
            TimelineRecord(
                record_kind=TimelineRecordKind.SNAPSHOT,
                record_id="pending",
                session_id=session_id,
                scenario_id=scenario_id,
                run_id=run_id,
                source_id=source_id,
                timepoint=timepoint,
                tags=tuple(tags),
                payload=body,
            )
        )

    # --- read / delete ---------------------------------------------------------

    def records(self, session_id: str) -> tuple[TimelineRecord, ...]:
        """Arrival-order snapshot of one session's records."""
        with self._lock:
            return tuple(self._records.get(session_id, ()))

    def delete_records(
        self, record_ids: Iterable[str], *, reason: str
    ) -> tuple[TimelineRecord, ...]:
        """Replace records with in-place tombstones (SPEC-303 §8).

        No dangling seemingly-valid references: the tombstone keeps only
        lane-stability metadata (kind/session/time base/source), drops the
        payload and the ``event_id`` evidence pointer, and names the record
        it replaces plus the deletion reason. Sequence positions are
        preserved (the tombstone occupies the original slot). The journal
        itself is untouched — SPEC-502 owns journal retention.
        """
        wanted = set(record_ids)
        tombstones: list[TimelineRecord] = []
        with self._lock:
            for session_id, records in self._records.items():
                for index, record in enumerate(records):
                    if record.record_id not in wanted:
                        continue
                    tombstone = self._with_content_id(
                        TimelineRecord(
                            record_kind=record.record_kind,
                            record_id="pending",
                            session_id=record.session_id,
                            scenario_id=record.scenario_id,
                            run_id=record.run_id,
                            source_id=record.source_id,
                            source_seq=record.source_seq,
                            journal_seq=record.journal_seq,
                            event_id=None,
                            timepoint=record.timepoint,
                            tags=(),
                            payload={
                                _TOMBSTONE_KEY: True,
                                "replaces_record_id": record.record_id,
                                "reason": reason,
                            },
                        )
                    )
                    records[index] = tombstone
                    tombstones.append(tombstone)
        return tuple(tombstones)

    # --- internals -------------------------------------------------------------

    def _append(self, record: TimelineRecord) -> TimelineRecord:
        stamped = self._with_content_id(record)
        with self._lock:
            self._records.setdefault(stamped.session_id, []).append(stamped)
        return stamped

    def _project_event_record(
        self, envelope: EventEnvelope, stamped: dict
    ) -> TimelineRecord:
        journal_seq = envelope.journal_seq
        assert journal_seq is not None  # validated by the caller
        correlation = envelope.correlation
        return TimelineRecord(
            record_kind=TimelineRecordKind.EVENT,
            record_id="pending",
            session_id=envelope.scope.session_id or "",
            scenario_id=envelope.scope.scenario_id,
            run_id=envelope.scope.run_id,
            source_id=envelope.producer.producer_id,
            source_seq=journal_seq,
            journal_seq=journal_seq,
            event_id=envelope.event_id,
            event_type=envelope.event_type,
            severity=envelope.severity,
            producer_id=envelope.producer.producer_id,
            node_id=correlation.node_id if correlation else None,
            service_id=correlation.service_id if correlation else None,
            pid=correlation.pid if correlation else None,
            fault_id=correlation.fault_id if correlation else None,
            timepoint=TimelineTimepoint(
                value_ns=envelope.time.source.value_ns,
                clock_domain=envelope.time.source.clock_domain,
                clock_epoch=envelope.time.source.clock_epoch,
                semantics=TimepointSemantics.SOURCE,
            ),
            tags=tuple(envelope.tags),
            payload={"envelope": dict(stamped)},
        )

    @staticmethod
    def _with_content_id(record: TimelineRecord) -> TimelineRecord:
        """Assign the content-derived record id (deterministic identity)."""
        document = record.model_dump(mode="json")
        document.pop("record_id", None)
        canonical = json.dumps(
            document, ensure_ascii=True, sort_keys=True, separators=(",", ":")
        )
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        content_id = f"tl-{digest[:32]}"
        if record.record_id == content_id:
            return record
        return record.model_copy(update={"record_id": content_id})


__all__ = ["RECORDER_SOURCE_ID", "TimelineRecorder"]
