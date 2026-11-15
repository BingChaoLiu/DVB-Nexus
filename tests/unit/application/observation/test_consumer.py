"""JournalTailingConsumer — cursor reads, checkpoints, restart recovery
(SPEC-300 §7: "消费者必须对其最后完整处理的 journal_seq 做检查点；重启恢复从
该序号继续并安全容忍重复投递").

Seam: ``catch_up()`` reads the journal from the durable checkpoint cursor in
journal_seq order, delivers committed records to the handler batch-wise, and
checkpoints ONLY fully processed batches. A crash between processing and
checkpointing redelivers the batch — handlers must be idempotent, and these
tests pin that redelivery happens and that an idempotent handler yields no
double effects.

Unit layer: in-memory fake journal + fake checkpoint store (no I/O).
"""

import pytest

from application.observation.consumer import ConsumerConfig, JournalTailingConsumer
from adapters.storage.errors import StorageWriteFailure


class _FakeJournal:
    """In-memory journal: committed rows addressed by (producer, event_id)."""

    def __init__(self, rows=None, fail_on_max: bool = False) -> None:
        self.rows = list(rows or [])
        self.fail_on_max = fail_on_max

    def append(self, envelope: dict) -> tuple[int, bool]:
        raise AssertionError("fakes use rows, not append")  # pragma: no cover

    def query(self, session_id: str, *, after_seq: int = 0, limit: int = 100):
        return [
            row
            for row in self.rows
            if row.session_id == session_id and row.journal_seq > after_seq
        ][:limit]

    def max_seq(self, session_id: str) -> int:
        if self.fail_on_max:
            raise StorageWriteFailure("simulated watermark failure")
        return max(
            (row.journal_seq for row in self.rows if row.session_id == session_id),
            default=0,
        )


class _FakeCheckpoints:
    def __init__(self) -> None:
        self._values: dict[tuple[str, str], int] = {}
        self.set_calls: list[tuple[str, str, int]] = []

    def get(self, consumer_id: str, session_id: str) -> int:
        return self._values.get((consumer_id, session_id), 0)

    def set(self, consumer_id: str, session_id: str, last_seq: int) -> None:
        self.set_calls.append((consumer_id, session_id, last_seq))
        self._values[(consumer_id, session_id)] = last_seq


class _Row:
    """Structural stand-in for adapters.storage.journal.EventRow."""

    def __init__(self, session_id: str, journal_seq: int, event_id: str) -> None:
        self.session_id = session_id
        self.journal_seq = journal_seq
        self.event_id = event_id
        self.event_type = "simulation.run_started"


def _rows(count: int, session_id: str = "sess-1") -> list[_Row]:
    return [_Row(session_id, seq, f"evt-{seq:07d}") for seq in range(1, count + 1)]


class _IdempotentHandler:
    """Records each event_id once; counts redeliveries for assertions."""

    def __init__(self) -> None:
        self.effects: list[str] = []
        self.deliveries: list[str] = []
        self.fail_on: set[str] = set()

    def __call__(self, record) -> None:
        self.deliveries.append(record.event_id)
        if record.event_id in self.fail_on:
            raise RuntimeError("handler failure mid-batch")
        if record.event_id not in self.effects:
            self.effects.append(record.event_id)


@pytest.fixture
def handler() -> _IdempotentHandler:
    return _IdempotentHandler()


@pytest.fixture
def store() -> _FakeCheckpoints:
    return _FakeCheckpoints()


def _consumer(journal, store, handler, session_id="sess-1", batch_size=100):
    return JournalTailingConsumer(
        journal=journal,
        checkpoints=store,
        session_id=session_id,
        consumer_id="metrics-engine",
        handler=handler,
        config=ConsumerConfig(batch_size=batch_size),
    )


# --- catch-up: cursor order and checkpoint semantics ---------------------------


def test_catch_up_delivers_all_records_in_journal_seq_order(handler, store) -> None:
    journal = _FakeJournal(_rows(5))

    processed = _consumer(journal, store, handler).catch_up()

    assert processed == 5
    assert handler.effects == [f"evt-{seq:07d}" for seq in range(1, 6)]
    assert store.get("metrics-engine", "sess-1") == 5


def test_checkpoint_advances_only_per_fully_processed_batch(handler, store) -> None:
    journal = _FakeJournal(_rows(5))

    _consumer(journal, store, handler, batch_size=2).catch_up()

    # 2, 4, then the final partial batch of 1 — every checkpoint is a batch
    # boundary, never a mid-batch seq.
    assert store.set_calls == [
        ("metrics-engine", "sess-1", 2),
        ("metrics-engine", "sess-1", 4),
        ("metrics-engine", "sess-1", 5),
    ]


def test_catch_up_from_an_advanced_cursor_skips_committed_records(
    handler, store
) -> None:
    store._values[("metrics-engine", "sess-1")] = 3
    journal = _FakeJournal(_rows(5))

    processed = _consumer(journal, store, handler).catch_up()

    assert processed == 2
    assert handler.effects == ["evt-0000004", "evt-0000005"]


# --- restart recovery and redelivery tolerance ---------------------------------


def test_restart_resumes_from_the_durable_checkpoint(handler, store) -> None:
    journal = _FakeJournal(_rows(4))
    first = _consumer(journal, store, handler, batch_size=2)
    first.catch_up()
    # Nothing new; a restarted consumer (same store) must not reprocess.
    restarted = _consumer(journal, store, handler, batch_size=2)

    processed = restarted.catch_up()

    assert processed == 0
    assert len(handler.deliveries) == 4  # no redelivery of committed records


def test_crash_before_checkpoint_redelivers_and_idempotent_handler_yields_no_double_effects(
    handler, store
) -> None:
    journal = _FakeJournal(_rows(4))
    handler.fail_on = {"evt-0000003"}
    consumer = _consumer(journal, store, handler, batch_size=2)

    with pytest.raises(RuntimeError):
        consumer.catch_up()
    # Batch (3, 4) was NOT checkpointed — the crash left it uncommitted.
    assert store.get("metrics-engine", "sess-1") == 2

    handler.fail_on = set()
    processed = consumer.catch_up()

    # Redelivery of the incomplete batch (the crash aborted it mid-way, so
    # evt-...004 arrives only now); the idempotent handler produces no
    # duplicate effects.
    assert processed == 2
    assert handler.deliveries.count("evt-0000003") == 2
    assert handler.deliveries.count("evt-0000004") == 1
    assert handler.effects == [
        "evt-0000001",
        "evt-0000002",
        "evt-0000003",
        "evt-0000004",
    ]
    assert store.get("metrics-engine", "sess-1") == 4


def test_checkpoints_are_scoped_per_session(handler, store) -> None:
    journal = _FakeJournal(_rows(2) + _rows(3, session_id="sess-2"))

    _consumer(journal, store, handler, session_id="sess-1").catch_up()
    _consumer(journal, store, handler, session_id="sess-2").catch_up()

    assert store.get("metrics-engine", "sess-1") == 2
    assert store.get("metrics-engine", "sess-2") == 3


# --- consumer lag (SPEC-300 §8: 消费者滞后可见) ---------------------------------


def test_lag_is_watermark_minus_checkpoint(handler, store) -> None:
    journal = _FakeJournal(_rows(4))
    consumer = _consumer(journal, store, handler)
    consumer.catch_up()
    assert consumer.lag() == 0

    # New committed records arrive while the consumer is not running.
    journal.rows += [
        _Row("sess-1", 5, "evt-0000005"),
        _Row("sess-1", 6, "evt-0000006"),
    ]

    assert consumer.lag() == 2
    assert consumer.checkpoint_seq() == 4


def test_lag_is_zero_when_fully_caught_up(handler, store) -> None:
    journal = _FakeJournal(_rows(3))
    consumer = _consumer(journal, store, handler)

    consumer.catch_up()

    assert consumer.lag() == 0
