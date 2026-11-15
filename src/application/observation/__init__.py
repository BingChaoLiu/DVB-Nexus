"""Application observation package — Event Gateway / Event Journal service
face (SPEC-300 §4.1/§4.2, ticket #47).

Owns the gateway admission path (validation → idempotency → bounded queue
with the SPEC-301 §5 coalescing/delivery policy), the producer-facing
publisher receipt (§12) and the checkpointed journal-tailing consumer (§7).
The SQLite journal itself stays in :mod:`adapters.storage` (the unique
``journal_seq`` stamp point, ADR-0006 decision 2).
"""

from application.observation.consumer import ConsumerConfig, JournalTailingConsumer
from application.observation.errors import OBS_QUEUE_FULL, OBS_STORAGE_UNAVAILABLE
from application.observation.gateway import (
    EventGateway,
    EventJournal,
    EventPublisher,
    GatewayConfig,
    GatewayMetrics,
    IngestFailure,
    IngestOutcome,
    IngestResult,
    PublishReceipt,
    PublishableEvent,
)
from application.observation.queue import BoundedEventQueue, QueueFullError

__all__ = [
    "BoundedEventQueue",
    "ConsumerConfig",
    "EventGateway",
    "EventJournal",
    "EventPublisher",
    "GatewayConfig",
    "GatewayMetrics",
    "IngestFailure",
    "IngestOutcome",
    "IngestResult",
    "JournalTailingConsumer",
    "OBS_QUEUE_FULL",
    "OBS_STORAGE_UNAVAILABLE",
    "PublishReceipt",
    "PublishableEvent",
    "QueueFullError",
]
