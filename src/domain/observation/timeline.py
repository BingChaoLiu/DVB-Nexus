"""SPEC-303 — timeline record models and the §4 ordering discipline.

The timeline is the evidence-navigation skeleton (SPEC-303 §1): a unified,
auditable trail of session events, snapshots, annotations, checkpoints,
bookmarks and export manifests. This module is the DOMAIN face (models +
pure ordering helpers); the recorder/query/export orchestration lives in
``application.observation.timeline`` (application layer — I/O and store
duties stay out of the domain, import contract C3).

Record-level timepoints (ticket #12 ruling, SPEC-300 §6): every
:class:`TimelineTimepoint` carries ``value_ns`` + ``clock_domain`` +
``clock_epoch`` PLUS an explicit ``semantics`` (source/observed/derived) —
unlike the ENVELOPE timepoint whose field name carries the meaning
(SPEC-301 §6; ``domain.observation.envelope.Timepoint`` is untouched by
design). Record-level timepoints elsewhere must never guess a meaning.

Ordering discipline (SPEC-303 §4, REQ-OBS-303-002), implemented by
:func:`timeline_record_sort_key`:

1. journal-sourced records (``journal_seq`` present) order by
   ``journal_seq`` — the gateway-stamped per-session total order
   (ADR-0006 decision 2) is the authoritative ingestion order;
2. cross-source records without a ``journal_seq`` (snapshots, annotations,
   bookmarks, ...) order by ``(clock_domain, timestamp, source_id,
   source_seq)`` — explicitly labeled via the ``*_SORT`` constants;
3. records of incompatible clock domains are NEVER merged into one claimed
   time order: within the source segment they group by the
   ``(clock_domain, clock_epoch)`` key (a deterministic key order, not a
   time claim), and the query service partitions lanes or refuses mixed
   requests (virtual time and wall time never mix, SPEC-300 §6).

Evidence chain (REQ-OBS-303-001): a record derived from an event MUST keep
the original ``event_id`` and ``journal_seq`` — enforced by a model
validator for ``record_kind == EVENT``.
"""

from enum import Enum
from typing import Annotated, Any, Optional, Tuple

from pydantic import Field, StringConstraints, model_validator

from domain._base import DomainModel
from domain.observation.envelope import Severity


class TimelineRecordKind(str, Enum):
    """SPEC-303 §3 record kinds (closed set)."""

    EVENT = "event"
    SNAPSHOT = "snapshot"
    ANNOTATION = "annotation"
    CHECKPOINT = "checkpoint"
    BOOKMARK = "bookmark"
    EXPORT_MANIFEST = "export_manifest"


class TimepointSemantics(str, Enum):
    """SPEC-300 §6 record-level timepoint semantics (explicit, never guessed)."""

    SOURCE = "source"
    OBSERVED = "observed"
    DERIVED = "derived"


class TimelineTimepoint(DomainModel):
    """Record-level timepoint: value + domain + epoch + EXPLICIT semantics.

    The ``semantics`` field is the ticket-#12/#51 addition over the envelope
    timepoint (SPEC-300 §6): record-level timepoints must say what their
    ``value_ns`` means instead of relying on the enclosing field name.
    """

    value_ns: int
    clock_domain: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    clock_epoch: int = Field(ge=0)
    semantics: TimepointSemantics


class ProducerStateVersion(DomainModel):
    """One producer's state version captured at checkpoint time (SPEC-303 §5)."""

    producer_id: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    state_version: Annotated[str, StringConstraints(min_length=1, max_length=128)]


class CheckpointRecord(DomainModel):
    """SPEC-303 §5 checkpoint contract.

    A checkpoint is an OBSERVATION behavior (§5): it never pauses or mutates
    the simulation; the authoritative simulation snapshot stays SPEC-200's.
    Field names carry time semantics per §5 (``virtual_time_ns`` is the
    source clock, ``created_at`` is an observed wall reading — both are
    :class:`TimelineTimepoint`-disciplined via the explicit semantics).
    """

    checkpoint_id: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    session_id: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    journal_seq: int = Field(ge=0)
    clock_domain: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    virtual_time_ns: Optional[int] = None
    schema_version: str = "1.0"
    producer_state_versions: Tuple[ProducerStateVersion, ...] = ()
    created_at: TimelineTimepoint
    integrity_digest: Optional[str] = None


class TimelineRecord(DomainModel):
    """One timeline record (SPEC-303 §3).

    Filterable fields are materialized flat (session/scenario/event type/
    severity/producer/node/service/PID/fault ID — SPEC-303 §6 whitelist);
    the kind-specific body rides in ``payload``. ``record_id`` is the
    timeline-local identity (opaque, content-derived at the recorder).
    """

    schema_version: str = "1.0"
    record_kind: TimelineRecordKind
    record_id: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    session_id: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    scenario_id: Optional[Annotated[str, StringConstraints(max_length=128)]] = None
    run_id: Optional[Annotated[str, StringConstraints(max_length=128)]] = None
    source_id: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    source_seq: Optional[int] = Field(default=None, ge=0)
    journal_seq: Optional[int] = Field(default=None, ge=0)
    event_id: Optional[Annotated[str, StringConstraints(min_length=8, max_length=128)]] = (
        None
    )
    event_type: Optional[str] = None
    severity: Optional[Severity] = None
    producer_id: Optional[Annotated[str, StringConstraints(max_length=64)]] = None
    node_id: Optional[str] = None
    service_id: Optional[str] = None
    pid: Optional[int] = Field(default=None, ge=0, le=8191)
    fault_id: Optional[str] = None
    timepoint: TimelineTimepoint
    tags: Tuple[
        Annotated[str, StringConstraints(max_length=64)],
        ...,
    ] = Field(default=(), max_length=32)
    payload: dict[str, Any]

    @model_validator(mode="after")
    def _validate_evidence_chain(self) -> "TimelineRecord":
        # REQ-OBS-303-001: a record derived from an event keeps the original
        # event_id AND journal_seq — the evidence chain must not break.
        # EXCEPTION (SPEC-303 §8): an explicit tombstone carries NO evidence
        # pointer (a seemingly-valid event_id on a deleted record is exactly
        # the dangling reference §8 bans); it keeps journal_seq for segment
        # stability and names the replaced record instead.
        if self.record_kind is TimelineRecordKind.EVENT:
            if self.journal_seq is None:
                raise ValueError(
                    "event records must carry the original journal_seq "
                    "(SPEC-303 §3, REQ-OBS-303-001: 证据链不断)"
                )
            is_tombstone = self.payload.get("tombstone") is True
            if not is_tombstone and not self.event_id:
                raise ValueError(
                    "event records must carry the original event_id "
                    "(SPEC-303 §3, REQ-OBS-303-001: 证据链不断; explicit "
                    "§8 tombstones are the only event_id-free form)"
                )
        return self


# --- §4 ordering discipline ---------------------------------------------------

#: Sort label for the journal-sourced segment (SPEC-303 §4 line 1).
JOURNAL_SEQ_SORT = "journal_seq"

#: Sort label for the cross-source segment (SPEC-303 §4 line 2): ordered by
#: (clock_domain, timestamp, source_id, source_seq), explicitly labeled.
SOURCE_ORDER_SORT = "source_order(clock_domain,timestamp,source_id,source_seq)"

#: Combined default descriptor: journal segment first (journal_seq), then the
#: cross-source segment (the §4 line-2 key). The descriptor states that the
#: two segments are NOT merged into one time order.
DEFAULT_SORT_DESCRIPTOR = f"{JOURNAL_SEQ_SORT}+{SOURCE_ORDER_SORT}"


def timeline_record_sort_key(record: TimelineRecord) -> tuple:
    """Deterministic §4 order key (two labeled segments, never time-merged).

    Segment 0 — journal-sourced records, keyed ``(0, journal_seq)``.
    Segment 1 — cross-source records, keyed
    ``(1, clock_domain, clock_epoch, value_ns, source_id, source_seq)``;
    the ``(domain, epoch)`` prefix groups incompatible clock bases by KEY
    (deterministic, not a cross-domain time claim — §4 line 3).
    """
    if record.journal_seq is not None:
        return (0, record.journal_seq, 0, 0, "", 0)
    timepoint = record.timepoint
    return (
        1,
        0,
        timepoint.clock_domain,
        timepoint.clock_epoch,
        timepoint.value_ns,
        record.source_id,
        record.source_seq if record.source_seq is not None else 0,
    )


def record_time_domain_key(record: TimelineRecord) -> Tuple[str, int]:
    """The record's ``(clock_domain, clock_epoch)`` lane key (SPEC-300 §6)."""
    return (record.timepoint.clock_domain, record.timepoint.clock_epoch)


__all__ = [
    "DEFAULT_SORT_DESCRIPTOR",
    "JOURNAL_SEQ_SORT",
    "SOURCE_ORDER_SORT",
    "CheckpointRecord",
    "ProducerStateVersion",
    "TimelineRecord",
    "TimelineRecordKind",
    "TimelineTimepoint",
    "TimepointSemantics",
    "record_time_domain_key",
    "timeline_record_sort_key",
]
