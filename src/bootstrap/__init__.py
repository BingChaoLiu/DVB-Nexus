"""Production composition root (ticket #53, 裁定 K).

``bootstrap`` is the ONLY top-level package allowed to import every other
project package downward (api/application/adapters/simulation/faults/ts/
domain) — it is the composition root; no package may import it back (the
import-linter closure guard). See ``app.build_production_app`` for the
factory and ``hints`` for the SPEC-305 §8 hub bindings.
"""

from bootstrap.app import METRIC_UPDATED_TOPIC, ProductionStack, build_production_app
from bootstrap.hints import (
    EventAppendedHintSubscriber,
    HubAlertHintEmitter,
    HubHintPublisher,
    ObservationHintPublisher,
)

__all__ = [
    "METRIC_UPDATED_TOPIC",
    "EventAppendedHintSubscriber",
    "HubAlertHintEmitter",
    "HubHintPublisher",
    "ObservationHintPublisher",
    "ProductionStack",
    "build_production_app",
]
