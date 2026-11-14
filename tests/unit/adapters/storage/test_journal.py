"""Journal stamp/dedup/query protocol (SPEC-502 sections 5-7, SPEC-301 §5).

Seams (delegator-approved, public API only):
- append -> stamped seq observable via the returned value AND the stored row;
- dedup replay -> original seq + duplicate=True, no duplicate row;
- query -> ordered rows, cursor, default/hard limit;
- invalid envelopes rejected before commit.

Unit slices run against an in-memory database (no file I/O); the file-backed
behaviors (WAL, concurrency across connections, migrations) live under
tests/integration/adapters/storage/.
"""

import pytest

from adapters.storage import db
from adapters.storage.errors import InvalidEnvelopeError, StorageWriteFailure
from adapters.storage.journal import EventRow, SqliteEventJournal


def _envelope(
    session_id: str = "sess-1",
    event_id: str = "evt-1",
    event_type: str = "simulation.run_started",
    severity: str = "info",
    producer_id: str = "sim-engine",
) -> dict:
    """Minimal SPEC-301 §2-shaped envelope (required fields only)."""
    return {
        "schema_version": "1.0",
        "event_id": event_id,
        "event_type": event_type,
        "producer": {
            "producer_id": producer_id,
            "producer_version": "0.1.0",
            "instance_id": "inst-1",
        },
        "scope": {"tenant_id": "local", "session_id": session_id},
        "time": {
            "source": {"value_ns": 1, "clock_domain": "sim:sess-1", "clock_epoch": 0},
            "observed": {"value_ns": 2, "clock_domain": "wall:utc", "clock_epoch": 0},
        },
        "severity": severity,
        "payload": {},
        "tags": [],
    }


def _journal() -> SqliteEventJournal:
    conn = db.connect(":memory:")
    db.migrate(conn)
    return SqliteEventJournal(conn)


# --- append: stamping (REQ-PLT-502-002) -------------------------------------


def test_append_stamps_first_seq_and_stores_row() -> None:
    journal = _journal()
    envelope = _envelope()

    stamped_seq, duplicate = journal.append(envelope)

    assert (stamped_seq, duplicate) == (1, False)
    rows = journal.query("sess-1")
    assert len(rows) == 1
    row = rows[0]
    assert isinstance(row, EventRow)
    assert (row.session_id, row.journal_seq) == ("sess-1", 1)
    assert row.event_type == "simulation.run_started"
    assert row.severity == "info"
    assert row.producer_id == "sim-engine"
    assert row.event_id == "evt-1"
    # The authoritative stored envelope carries the stamp.
    assert row.envelope["journal_seq"] == 1


def test_append_is_monotonic_per_session() -> None:
    journal = _journal()
    seqs = [journal.append(_envelope(event_id=f"evt-{i}"))[0] for i in range(3)]
    assert seqs == [1, 2, 3]


def test_journal_seq_independent_across_sessions() -> None:
    journal = _journal()
    assert journal.append(_envelope(session_id="sess-a", event_id="a1"))[0] == 1
    assert journal.append(_envelope(session_id="sess-b", event_id="b1"))[0] == 1
    assert journal.append(_envelope(session_id="sess-a", event_id="a2"))[0] == 2


def test_append_does_not_mutate_caller_envelope() -> None:
    journal = _journal()
    envelope = _envelope()
    journal.append(envelope)
    assert "journal_seq" not in envelope


def test_append_overwrites_producer_supplied_journal_seq() -> None:
    """ADR-0006 decision 2: producers never fill journal_seq; the stamp point
    is unique, so any incoming value is replaced by the authoritative one."""
    journal = _journal()
    envelope = _envelope()
    envelope["journal_seq"] = 999_999

    seq, duplicate = journal.append(envelope)

    assert (seq, duplicate) == (1, False)
    assert journal.query("sess-1")[0].envelope["journal_seq"] == 1


# --- dedup: (producer_id, event_id) replay (REQ-PLT-502-003) -----------------


def test_dedup_replay_returns_original_seq_and_stores_no_row() -> None:
    """SPEC-301 §5: at-least-once delivery — the replayed append returns the
    ORIGINAL journal_seq with duplicate=True and creates no new row."""
    journal = _journal()
    envelope = _envelope(event_id="evt-dup")

    first_seq, first_dup = journal.append(envelope)
    replay_seq, replay_dup = journal.append(envelope)

    assert (first_seq, first_dup) == (1, False)
    assert (replay_seq, replay_dup) == (1, True)
    rows = journal.query("sess-1")
    assert len(rows) == 1
    # The stored envelope stays the FIRST stamped one, not a re-stamp.
    assert rows[0].envelope["journal_seq"] == 1


def test_same_event_id_from_different_producer_is_not_dedup() -> None:
    journal = _journal()
    first = journal.append(_envelope(event_id="evt-x", producer_id="producer-a"))
    second = journal.append(_envelope(event_id="evt-x", producer_id="producer-b"))
    assert first == (1, False)
    assert second == (2, False)
    assert len(journal.query("sess-1")) == 2


def test_dedup_replay_after_other_events_returns_original_seq() -> None:
    """The original seq survives later appends on the same session."""
    journal = _journal()
    journal.append(_envelope(event_id="evt-dup"))
    journal.append(_envelope(event_id="evt-2"))
    journal.append(_envelope(event_id="evt-3"))
    replay_seq, replay_dup = journal.append(_envelope(event_id="evt-dup"))
    assert (replay_seq, replay_dup) == (1, True)


# --- query: ordering, cursor, limits (SPEC-502 §5/§8 via SPEC-305 §5) -------


def test_query_returns_rows_in_seq_order_after_cursor() -> None:
    journal = _journal()
    for i in range(1, 4):
        journal.append(_envelope(event_id=f"evt-{i}"))

    full = journal.query("sess-1")
    assert [row.journal_seq for row in full] == [1, 2, 3]
    assert [row.event_id for row in full] == ["evt-1", "evt-2", "evt-3"]
    assert [row.envelope["event_id"] for row in full] == ["evt-1", "evt-2", "evt-3"]

    after_first = journal.query("sess-1", after_seq=1)
    assert [row.journal_seq for row in after_first] == [2, 3]

    assert journal.query("no-such-session") == []


def test_query_default_limit_is_100() -> None:
    journal = _journal()
    for i in range(150):
        journal.append(_envelope(event_id=f"evt-{i}"))

    assert len(journal.query("sess-1")) == 100
    assert [row.journal_seq for row in journal.query("sess-1")] == list(range(1, 101))
    assert len(journal.query("sess-1", limit=150)) == 150


def test_query_enforces_hard_cap_2000() -> None:
    journal = _journal()
    journal.append(_envelope())

    assert len(journal.query("sess-1", limit=2000)) == 1
    with pytest.raises(ValueError):
        journal.query("sess-1", limit=2001)
    with pytest.raises(ValueError):
        journal.query("sess-1", limit=0)


# --- invalid envelopes rejected before commit (SPEC-301 §9) -----------------


def test_append_rejects_malformed_envelopes_without_storing() -> None:
    journal = _journal()

    cases: list[dict] = []
    missing_event_id = _envelope()
    del missing_event_id["event_id"]
    cases.append(missing_event_id)
    missing_event_type = _envelope()
    del missing_event_type["event_type"]
    cases.append(missing_event_type)
    missing_severity = _envelope()
    del missing_severity["severity"]
    cases.append(missing_severity)
    missing_producer = _envelope()
    del missing_producer["producer"]
    cases.append(missing_producer)
    empty_producer_id = _envelope()
    empty_producer_id["producer"]["producer_id"] = ""
    cases.append(empty_producer_id)
    missing_scope = _envelope()
    del missing_scope["scope"]
    cases.append(missing_scope)
    null_session = _envelope()
    null_session["scope"]["session_id"] = None  # R4: journal stamps per session
    cases.append(null_session)
    wrong_type = _envelope()
    wrong_type["event_id"] = 12345
    cases.append(wrong_type)

    for envelope in cases:
        with pytest.raises(InvalidEnvelopeError):
            journal.append(envelope)

    assert journal.query("sess-1") == []


def test_append_rejects_non_object_and_unserializable_envelopes() -> None:
    journal = _journal()
    with pytest.raises(InvalidEnvelopeError):
        journal.append(["not", "a", "dict"])
    unserializable = _envelope()
    unserializable["payload"] = {"x": {1, 2}}  # sets are not JSON-representable
    with pytest.raises(InvalidEnvelopeError):
        journal.append(unserializable)
    assert journal.query("sess-1") == []


def test_append_failure_maps_to_storage_write_failure() -> None:
    """SPEC-502 §7 row 2: journal append failure -> OBS_STORAGE_WRITE_FAILURE.
    Triggered on a test-owned connection whose events table was dropped (the
    OperationalError path a real disk/lock failure would take)."""
    conn = db.connect(":memory:")
    db.migrate(conn)
    journal = SqliteEventJournal(conn)
    conn.execute("DROP TABLE events")

    with pytest.raises(StorageWriteFailure) as excinfo:
        journal.append(_envelope())

    assert excinfo.value.code == "OBS_STORAGE_WRITE_FAILURE"
