"""SPEC-302 metrics engine (ticket #50) — application/observation/metrics.

The observation plane's metrics face (SPEC-300 §7 step 6: 指标/时间轴/告警
组件幂等更新): catalog registry, aggregation operators, the in-memory
derived-series store, the journal-tailing ingestion engine and the
``MetricsService.query`` contract (SPEC-300 §12 required interface,
SPEC-302 §8). The SQLite journal and durable retention stay in
:mod:`adapters.storage` — this package never touches storage I/O.
"""

from application.observation.metrics.aggregator import (
    aggregate_scalar,
    bucket_bounds,
    bucket_count,
    bucket_index_for,
    counter_increase,
    counter_rate,
    histogram_counts,
    histogram_quantile,
    pair_increase,
)
from application.observation.metrics.catalog import CATALOG_METRIC_NAMES, default_catalog
from application.observation.metrics.engine import (
    MetricsEngine,
    MetricsEngineConfig,
    build_metrics_consumer,
)
from application.observation.metrics.errors import (
    OBS_METRIC_CARDINALITY_EXCEEDED,
    OBS_METRIC_DIMENSION_REJECTED,
    OBS_METRIC_NOT_FOUND,
    OBS_QUERY_RANGE_TOO_LARGE,
    MetricError,
)
from application.observation.metrics.registry import MetricRegistry
from application.observation.metrics.service import MetricsService

__all__ = [
    "CATALOG_METRIC_NAMES",
    "MetricError",
    "MetricRegistry",
    "MetricsEngine",
    "MetricsEngineConfig",
    "MetricsService",
    "OBS_METRIC_CARDINALITY_EXCEEDED",
    "OBS_METRIC_DIMENSION_REJECTED",
    "OBS_METRIC_NOT_FOUND",
    "OBS_QUERY_RANGE_TOO_LARGE",
    "aggregate_scalar",
    "bucket_bounds",
    "bucket_count",
    "bucket_index_for",
    "build_metrics_consumer",
    "counter_increase",
    "counter_rate",
    "default_catalog",
    "histogram_counts",
    "histogram_quantile",
    "pair_increase",
]
