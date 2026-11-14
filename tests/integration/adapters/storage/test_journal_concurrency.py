"""Concurrent journal append (SPEC-502 §9 盖章: 并发 append 序号无洞无重).

Seam (delegator-approved): the public ``append`` return values from multiple
connections on one file-backed database. Each worker uses its OWN connection
(SQLite single-writer semantics; SPEC-502 §8) — the ``BEGIN IMMEDIATE``
stamp transaction must serialize them so the union of stamped seqs is
1..total with no hole and no duplicate, and per-session sequences stay
independent.

This is the verification test for the stamping design of REQ-PLT-502-002 on
real (WAL) files under Windows.
"""

import threading
from pathlib import Path

from adapters.storage import db
from adapters.storage.journal import SqliteEventJournal


def _envelope(session_id: str, event_id: str) -> dict:
    return {
        "schema_version": "1.0",
        "event_id": event_id,
        "event_type": "simulation.run_progress",
        "producer": {"producer_id": "sim-engine", "producer_version": "0.1.0", "instance_id": "inst-1"},
        "scope": {"tenant_id": "local", "session_id": session_id},
        "time": {
            "source": {"value_ns": 1, "clock_domain": "sim:x", "clock_epoch": 0},
            "observed": {"value_ns": 2, "clock_domain": "wall:utc", "clock_epoch": 0},
        },
        "severity": "info",
        "payload": {},
        "tags": [],
    }


def test_concurrent_appends_same_session_have_no_holes_and_no_duplicates(tmp_path: Path) -> None:
    workers = 4
    per_worker = 25
    db_path = tmp_path / "db.sqlite3"
    conn = db.connect(db_path)
    db.migrate(conn)
    conn.close()

    results: dict[int, list[int]] = {}
    errors: list[Exception] = []
    start = threading.Barrier(workers)

    def worker(index: int) -> None:
        try:
            journal_conn = db.connect(db_path)
            journal = SqliteEventJournal(journal_conn)
            seqs: list[int] = []
            start.wait()
            for i in range(per_worker):
                seq, duplicate = journal.append(_envelope("sess-1", f"w{index}-evt-{i}"))
                assert duplicate is False
                seqs.append(seq)
            journal_conn.close()
            results[index] = seqs
        except Exception as exc:  # noqa: BLE001 - collected and re-asserted below
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    stamped = sorted(s for seqs in results.values() for s in seqs)
    total = workers * per_worker
    assert stamped == list(range(1, total + 1)), "seqs must be exactly 1..N: no hole, no duplicate"


def test_concurrent_appends_keep_session_sequences_independent(tmp_path: Path) -> None:
    """Cross-session independence under concurrency: each session counts from 1."""
    db_path = tmp_path / "db.sqlite3"
    conn = db.connect(db_path)
    db.migrate(conn)
    conn.close()

    results: dict[str, list[int]] = {"sess-a": [], "sess-b": []}
    errors: list[Exception] = []
    start = threading.Barrier(2)

    def worker(session_id: str) -> None:
        try:
            journal_conn = db.connect(db_path)
            journal = SqliteEventJournal(journal_conn)
            start.wait()
            for i in range(20):
                seq, _ = journal.append(_envelope(session_id, f"{session_id}-evt-{i}"))
                results[session_id].append(seq)
            journal_conn.close()
        except Exception as exc:  # noqa: BLE001 - collected and re-asserted below
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=("sess-a",)), threading.Thread(target=worker, args=("sess-b",))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert sorted(results["sess-a"]) == list(range(1, 21))
    assert sorted(results["sess-b"]) == list(range(1, 21))
