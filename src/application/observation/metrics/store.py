"""In-memory derived-series store (SPEC-302 §6/§7, ticket #50).

Series are keyed by ``(metric_name, clock_domain, clock_epoch, dimensions)``
— the time-domain key is part of the identity, so wall-clock operational
series and virtual-time series are physically separate universes (SPEC-302
§9). The store carries raw samples in arrival order (= journal order) plus
the per-bucket materialization ledgers that give late-sample rewrites their
``revision``/``is_final`` semantics (SPEC-302 §6.2).

MVP scoping: this store is in-process memory; durable retention and the
raw/1m/1h deletion tiers are storage-backend territory (SPEC-502) — the
downsampling layers are query-time aggregations over the same raw samples
with identical operator semantics.
"""

from dataclasses import dataclass
from typing import Optional, Union

from domain.observation import MetricSample, SeriesQuality

Number = Union[int, float]

#: Series key: (metric_name, clock_domain, clock_epoch, canonical dims).
SeriesKey = tuple[str, str, int, tuple]


@dataclass
class BucketLedger:
    """Materialization state of one ``(step, bucket_start)`` (§6.2).

    ``revision`` starts at 1; it increments only when a backfill rewrite
    applies to an already-finalized bucket. ``is_final`` freezes the
    published aggregate — with backfill disabled a frozen value is returned
    unchanged no matter which late samples arrive afterwards (无静默改写).
    """

    revision: int = 1
    is_final: bool = False
    sample_positions: tuple[int, ...] = ()
    frozen_value: Optional[Number] = None
    frozen_quality: tuple[SeriesQuality, ...] = ()


class SeriesState:
    """One dimension-set's samples and materialization ledgers."""

    __slots__ = ("key", "samples", "high_ns", "ledgers")

    def __init__(self, key: SeriesKey) -> None:
        self.key = key
        self.samples: list[MetricSample] = []
        #: Max sample ``value_ns`` seen so far — the series' watermark for
        #: lateness decisions (journal-order arrival, so replay-stable).
        self.high_ns: Optional[int] = None
        self.ledgers: dict[tuple[int, int], BucketLedger] = {}

    def append(self, sample: MetricSample) -> None:
        self.samples.append(sample)
        t = sample.time.value_ns
        if self.high_ns is None or t > self.high_ns:
            self.high_ns = t


@dataclass(frozen=True)
class QuarantinedSample:
    """A sample isolated under the §7 quarantine policy (observable)."""

    code: str
    message: str
    sample: MetricSample


@dataclass(frozen=True)
class RejectionEntry:
    """A recorded ingestion refusal (§7 reject policy / defensive paths).

    Visible in the engine's rejection stream — rejections are never silent
    (SPEC-300 §4.2 discipline: failures are observable, not dropped).
    """

    code: str
    message: str
    journal_seq: Optional[int] = None
    detail: str = ""


class MetricSeriesStore:
    """Series registry + cardinality accounting (SPEC-302 §7)."""

    def __init__(self) -> None:
        self._series: dict[SeriesKey, SeriesState] = {}
        self._active_counts: dict[str, int] = {}
        self._quarantine: list[QuarantinedSample] = []

    def is_new_series(self, key: SeriesKey) -> bool:
        return key not in self._series

    def active_series_count(self, metric_name: str) -> int:
        return self._active_counts.get(metric_name, 0)

    def create(self, key: SeriesKey) -> SeriesState:
        state = SeriesState(key)
        self._series[key] = state
        self._active_counts[key[0]] = self._active_counts.get(key[0], 0) + 1
        return state

    def get(self, key: SeriesKey) -> Optional[SeriesState]:
        return self._series.get(key)

    def series_matching(
        self,
        metric_name: str,
        clock_domain: str,
        dimensions: Optional[dict] = None,
    ) -> list[SeriesState]:
        """Series of one metric+domain narrowed by the filter values.

        Filters narrow (every filter dim must match the series' value);
        an empty filter matches every series of the metric+domain. Series
        may carry dimensions the filter does not mention.
        """
        wanted = dimensions or {}
        matched = []
        for key, state in sorted(self._series.items()):
            if key[0] != metric_name or key[1] != clock_domain:
                continue
            series_dims = dict(key[3])
            if all(value == series_dims.get(dim) for dim, value in wanted.items()):
                matched.append(state)
        return matched

    def quarantine(self, entry: QuarantinedSample) -> None:
        self._quarantine.append(entry)

    def quarantined(self) -> tuple[QuarantinedSample, ...]:
        return tuple(self._quarantine)


def canonical_series_key(sample: MetricSample) -> SeriesKey:
    """The series identity of a sample (dimensions canonically ordered)."""
    return (
        sample.metric_name,
        sample.time.clock_domain,
        sample.time.clock_epoch,
        _canonical_dimensions(sample.dimensions),
    )


def _canonical_dimensions(dimensions: dict) -> tuple:
    return tuple(sorted((dim, value) for dim, value in dimensions.items()))


__all__ = [
    "BucketLedger",
    "MetricSeriesStore",
    "QuarantinedSample",
    "RejectionEntry",
    "SeriesKey",
    "SeriesState",
    "canonical_series_key",
]
