"""SPEC-302 §6.1 aggregation operators (pure functions, ticket #50).

All functions are total and deterministic: same inputs → same outputs, no
clock, no state. Counter ``increase``/``rate`` implement reset detection
(§7: counter resets must be detected — a decrease between consecutive
cumulative samples is a reset and the post-reset value counts as fresh
increase). Histogram quantiles interpolate linearly over the configured
bucket edges (Prometheus-style histogram_quantile semantics). Window
arithmetic is half-open ``[start, end)`` (§6.1).
"""

from typing import Optional, Union

from domain.observation import AggregationOperation, HistogramSpec

Number = Union[int, float]

_NS_PER_SECOND = 1_000_000_000


def aggregate_scalar(
    op: AggregationOperation, values: list[Number]
) -> Optional[Number]:
    """sum/min/max/avg/last over a non-empty window; ``None`` when empty."""
    if not values:
        return None
    if op is AggregationOperation.SUM:
        total: Number = 0
        for value in values:
            total += value
        return total
    if op is AggregationOperation.MIN:
        return min(values)
    if op is AggregationOperation.MAX:
        return max(values)
    if op is AggregationOperation.AVG:
        total = 0
        for value in values:
            total += value
        return total / len(values)
    if op is AggregationOperation.LAST:
        return values[-1]
    raise ValueError(
        f"{op.value!r} is not a scalar aggregation op (SPEC-302 §6.1)"
    )


def pair_increase(previous: Number, current: Number) -> Number:
    """Delta between consecutive cumulative samples, reset-detecting (§7).

    ``current < previous`` means the counter restarted: the reset point is
    not subtracted — the post-reset value itself is the fresh increase.
    """
    if current >= previous:
        return current - previous
    return current


def counter_increase(
    anchor: Optional[Number], bucket_values: list[Number]
) -> Optional[Number]:
    """Reset-detecting increase over one bucket (§6.1 counter ops).

    ``anchor`` is the last cumulative value before the bucket (``None`` when
    the series has no history); the first unanchored sample is the baseline,
    not an increase. No samples → ``None`` (the bucket is missing, §6.3).
    """
    if not bucket_values:
        return None
    total: Number = 0
    previous = anchor
    for value in bucket_values:
        if previous is not None:
            total += pair_increase(previous, value)
        previous = value
    return total


def counter_rate(increase: Number, window_ns: int) -> float:
    """Increase per second over the window (rate = Δ/t, §6.1)."""
    if window_ns <= 0:
        raise ValueError("window_ns must be positive for a rate")
    return (increase * _NS_PER_SECOND) / window_ns


def histogram_counts(spec: HistogramSpec, values: list[Number]) -> list[int]:
    """Per-edge-bucket counts (edges are lower bounds).

    Bucket i holds ``edges[i] <= value < edges[i+1]``; the top bucket
    absorbs ``>=`` the last edge, and values below the first edge clamp into
    bucket 0 so the count stays conserved (count = number of observations).
    """
    edges = spec.bucket_edges
    counts = [0] * len(edges)
    for value in values:
        for index in range(len(edges) - 1, -1, -1):
            if value >= edges[index]:
                counts[index] += 1
                break
        else:
            counts[0] += 1  # below the first edge: clamped, never dropped
    return counts


def histogram_quantile(
    spec: HistogramSpec, counts: list[int], quantile: float
) -> Optional[float]:
    """Linear interpolation over cumulative bucket counts (§6.1 quantiles).

    Returns ``None`` when the histogram holds no observations. Ranks beyond
    the last populated bucket clamp to the top edge.
    """
    if not 0.0 < quantile <= 1.0:
        raise ValueError("quantile must be in (0, 1]")
    edges = spec.bucket_edges
    total = sum(counts)
    if total == 0:
        return None
    rank = quantile * total
    cumulative = 0
    for index, count in enumerate(counts):
        if cumulative + count >= rank and count > 0:
            # Bucket i spans [edges[i], edges[i+1]) — the edges are lower
            # bounds (see histogram_counts); the top bucket clamps.
            lower_edge = edges[index]
            upper_edge = (
                edges[index + 1] if index + 1 < len(edges) else edges[index]
            )
            fraction = (rank - cumulative) / count
            return lower_edge + fraction * (upper_edge - lower_edge)
        cumulative += count
    return float(edges[-1])


def bucket_bounds(start_ns: int, step_ns: int, index: int) -> tuple[int, int]:
    """Half-open bucket ``[start + index*step, start + (index+1)*step)``."""
    if step_ns < 1:
        raise ValueError("step_ns must be >= 1")
    base = start_ns + index * step_ns
    return (base, base + step_ns)


def bucket_count(start_ns: int, end_ns: int, step_ns: int) -> int:
    """Number of ``[start, end)`` buckets, including a partial tail."""
    if end_ns <= start_ns:
        raise ValueError("end_ns must be greater than start_ns")
    if step_ns < 1:
        raise ValueError("step_ns must be >= 1")
    span = end_ns - start_ns
    return (span + step_ns - 1) // step_ns


def bucket_index_for(
    value_ns: int,
    start_ns: int,
    step_ns: int,
    *,
    bucket_total: Optional[int] = None,
) -> int:
    """Bucket index of a sample, refusing samples outside ``[start, end)``.

    The half-open discipline (§6.1): a sample at ``t == end`` belongs to a
    bucket beyond the query range and is refused, never folded back.
    ``bucket_total`` bounds the check when the query range is known.
    """
    index = (value_ns - start_ns) // step_ns
    if index < 0 or (bucket_total is not None and index >= bucket_total):
        raise ValueError(
            f"sample time {value_ns} lies outside the query buckets "
            f"(start={start_ns}, step={step_ns}, total={bucket_total})"
        )
    return index


__all__ = [
    "aggregate_scalar",
    "bucket_bounds",
    "bucket_count",
    "bucket_index_for",
    "counter_increase",
    "counter_rate",
    "histogram_counts",
    "histogram_quantile",
    "pair_increase",
]
