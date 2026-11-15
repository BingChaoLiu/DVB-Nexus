"""Journal-tailing consumer — SPEC-300 §7 checkpoint protocol (application).

Consumes committed journal records from a durable checkpoint cursor:

- reads in journal_seq order via the SPEC-502 ``query`` cursor
  (``after_seq`` = last FULLY processed seq, per session);
- delivers batch-wise to the handler and checkpoints only fully processed
  batches — a crash between processing and checkpointing redelivers the
  incomplete batch, so handlers must be idempotent (SPEC-300 §7: 安全容忍
  重复投递);
- restart recovery is deterministic: a fresh consumer over the same
  checkpoint store resumes exactly after the durable cursor;
- exposes consumer lag (watermark − checkpoint, SPEC-300 §8 消费者滞后).

This consumer never mutates upstream state (observer boundary discipline,
OBSERVATION-INTEGRATION-CONTRACT §9); it only reads the journal and writes
its own checkpoints.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional, Protocol

RecordHandler = Callable[[Any], None]


class Checkpoints(Protocol):
    """Structural subset of ``adapters.storage.checkpoints.CheckpointStore``."""

    def get(self, consumer_id: str, session_id: str) -> int: ...

    def set(self, consumer_id: str, session_id: str, last_seq: int) -> None: ...


class TailableJournal(Protocol):
    """Structural subset of the SPEC-502 journal protocol the consumer needs."""

    def query(self, session_id: str, *, after_seq: int = 0, limit: int = 100): ...

    def max_seq(self, session_id: str) -> int: ...


@dataclass(frozen=True)
class ConsumerConfig:
    """Batch size for one read/checkpoint round (bounded, SPEC-502 §8 cap)."""

    batch_size: int = 100


class JournalTailingConsumer:
    """Checkpointed journal consumer (SPEC-300 §7)."""

    def __init__(
        self,
        journal: TailableJournal,
        checkpoints: Checkpoints,
        session_id: str,
        consumer_id: str,
        handler: RecordHandler,
        config: ConsumerConfig | None = None,
    ) -> None:
        config = config or ConsumerConfig()
        if config.batch_size < 1:
            raise ValueError(
                f"consumer batch_size must be >= 1, got {config.batch_size!r}"
            )
        self._journal = journal
        self._checkpoints = checkpoints
        self._session_id = session_id
        self._consumer_id = consumer_id
        self._handler = handler
        self._batch_size = config.batch_size

    def catch_up(self) -> int:
        """Process committed records until the journal is exhausted.

        Returns the number of records delivered to the handler (including
        redeliveries of an incomplete batch after a crash). Raises when the
        handler or the journal fails — the failing batch stays uncheckpointed
        and is redelivered on the next ``catch_up``.
        """
        processed = 0
        while True:
            cursor = self.checkpoint_seq()
            records = self._journal.query(
                self._session_id, after_seq=cursor, limit=self._batch_size
            )
            if not records:
                return processed
            for record in records:
                self._handler(record)
            # Only a fully processed batch advances the durable cursor
            # (SPEC-300 §7: the checkpoint is the last COMPLETELY processed
            # journal_seq).
            self._checkpoints.set(
                self._consumer_id, self._session_id, records[-1].journal_seq
            )
            processed += len(records)
            if len(records) < self._batch_size:
                return processed

    def checkpoint_seq(self) -> int:
        """The durable cursor: last fully processed journal_seq."""
        return self._checkpoints.get(self._consumer_id, self._session_id)

    def lag(self) -> int:
        """Committed-but-unprocessed depth (SPEC-300 §8 消费者滞后)."""
        watermark = self._journal.max_seq(self._session_id)
        return max(0, watermark - self.checkpoint_seq())


__all__ = ["ConsumerConfig", "JournalTailingConsumer"]
