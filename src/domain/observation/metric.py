"""SPEC-003 section 2.5 Metric.

A sampled scalar measurement within a run. Data only: sampling windows,
aggregation, valid ranges and units per metric are SPEC-302's scope; unknown
values must not be forced to 0 (caller's discipline — the model simply carries
what it is given).
"""

from enum import Enum
from typing import Optional, Union

from domain._base import DomainModel
from domain.observation.ids import Identifier, OpaqueEntityId
from domain.observation.model import ObservationSource


class MetricQuality(str, Enum):
    """Sample quality (SPEC-003 section 2.5)."""

    VALID = "valid"
    UNAVAILABLE = "unavailable"
    ESTIMATED = "estimated"
    INVALID = "invalid"


class Metric(DomainModel):
    """SPEC-003 section 2.5 ``Metric``."""

    metric_id: Identifier
    run_id: OpaqueEntityId
    name: str
    #: number | string | boolean in SPEC-003; each JSON scalar kind must stay
    #: itself (bool is never coerced into int).
    value: Union[int, float, str, bool]
    unit: Optional[str] = None
    source: ObservationSource
    quality: MetricQuality
    observed_at_utc_ms: int
    window_start_utc_ms: Optional[int] = None
    window_end_utc_ms: Optional[int] = None
    pid: Optional[int] = None


__all__ = ["Metric", "MetricQuality"]
