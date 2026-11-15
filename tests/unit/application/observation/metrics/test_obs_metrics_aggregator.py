"""SPEC-302 §6.1 aggregation operators — table-driven vectors (ticket #50).

REQ-OBS-302-002: aggregation operations (sum/min/max/avg/last; histogram
count/sum/quantiles; counter rate/increase + reset detection) and the
half-open ``[start, end)`` window semantics, as pure-function vectors.

Expected values are independent hand-computed literals (worked examples),
not recomputations. Counter reset detection follows the standard semantics:
a decrease between consecutive cumulative samples is a reset — the post-reset
value counts as fresh increase (it is NOT subtracted).
"""

import pytest

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
from domain.observation import AggregationOperation, HistogramSpec

_EDGES = (0.0, 100.0, 200.0)


# --- scalar ops (sum/min/max/avg/last) ------------------------------------------


@pytest.mark.parametrize(
    "op,values,expected",
    [
        (AggregationOperation.SUM, [1, 2, 3], 6),
        (AggregationOperation.MIN, [1, 2, 3], 1),
        (AggregationOperation.MAX, [1, 2, 3], 3),
        (AggregationOperation.AVG, [1, 2, 3], 2.0),
        (AggregationOperation.LAST, [1, 2, 3], 3),
        (AggregationOperation.SUM, [2.5, 0.5], 3.0),
        (AggregationOperation.LAST, [7], 7),
    ],
)
def test_scalar_op_vectors(
    op: AggregationOperation, values, expected
) -> None:
    assert aggregate_scalar(op, values) == expected


def test_scalar_ops_on_an_empty_window_are_none() -> None:
    for op in (
        AggregationOperation.SUM,
        AggregationOperation.MIN,
        AggregationOperation.MAX,
        AggregationOperation.AVG,
        AggregationOperation.LAST,
    ):
        assert aggregate_scalar(op, []) is None


def test_avg_is_float_even_over_ints() -> None:
    assert isinstance(aggregate_scalar(AggregationOperation.AVG, [1, 2]), float)


# --- counter increase with reset detection (SPEC-302 §6.1/§7) -------------------


@pytest.mark.parametrize(
    "previous,current,expected",
    [
        (5, 9, 4),  # monotone: plain difference
        (10, 3, 3),  # reset (10 -> 3): post-reset value is fresh increase
        (7, 7, 0),  # flat
    ],
)
def test_pair_increase_detects_resets(
    previous: float, current: float, expected: float
) -> None:
    assert pair_increase(previous, current) == expected


def test_counter_increase_chains_samples_with_an_anchor() -> None:
    assert counter_increase(5, [7, 9]) == 4
    assert counter_increase(None, [7, 9]) == 2  # first sample is the baseline
    assert counter_increase(None, [7]) == 0  # single unanchored sample: no delta


def test_counter_increase_survives_a_reset_mid_bucket() -> None:
    # anchor 10 -> reset to 3 (increase 3) -> 4 (increase 1): total 4.
    assert counter_increase(10, [3, 4]) == 4


def test_counter_increase_without_samples_is_none() -> None:
    assert counter_increase(5, []) is None


@pytest.mark.parametrize(
    "increase,window_ns,expected",
    [
        (6, 1_000_000_000, 6.0),  # per second
        (1, 500_000_000, 2.0),  # half-second window doubles the rate
        (0, 1_000_000_000, 0.0),
    ],
)
def test_counter_rate_is_increase_per_second(
    increase: float, window_ns: int, expected: float
) -> None:
    assert counter_rate(increase, window_ns) == pytest.approx(expected)


# --- histogram count/sum/quantiles (SPEC-302 §6.1) ------------------------------


def test_histogram_counts_place_values_into_le_edges() -> None:
    spec = HistogramSpec(bucket_edges=_EDGES)
    assert histogram_counts(spec, [10, 50, 150, 250]) == [2, 1, 1]


def test_histogram_count_and_sum_are_exact() -> None:
    spec = HistogramSpec(bucket_edges=_EDGES)
    values = [10, 50, 150, 250]
    counts = histogram_counts(spec, values)
    assert sum(counts) == 4
    assert aggregate_scalar(AggregationOperation.SUM, values) == 460


def test_histogram_quantile_interpolates_within_buckets() -> None:
    spec = HistogramSpec(bucket_edges=_EDGES)
    counts = [2, 1, 1]
    # q=0.25: rank 1 in bucket [0,100) → 0 + (1/2)*100 = 50
    assert histogram_quantile(spec, counts, 0.25) == pytest.approx(50.0)
    # q=0.5: rank 2 at the bucket boundary → 100
    assert histogram_quantile(spec, counts, 0.5) == pytest.approx(100.0)
    # q=1.0: rank 4 in bucket [100,200) with count 1 → clamped to the edge 200
    assert histogram_quantile(spec, counts, 1.0) == pytest.approx(200.0)


def test_histogram_quantile_without_observations_is_none() -> None:
    spec = HistogramSpec(bucket_edges=_EDGES)
    assert histogram_quantile(spec, [0, 0, 0], 0.5) is None


# --- half-open bucket arithmetic ([start, end), SPEC-302 §6.1) ------------------


def test_bucket_bounds_are_half_open() -> None:
    assert bucket_bounds(0, 1_000, 0) == (0, 1_000)
    assert bucket_bounds(1_000, 1_000, 3) == (4_000, 5_000)


def test_bucket_count_covers_the_partial_tail_bucket() -> None:
    assert bucket_count(0, 10_000, 1_000) == 10
    assert bucket_count(0, 10_001, 1_000) == 11  # 1 ns spill → one more bucket


def test_bucket_index_places_the_end_boundary_sample_in_the_next_bucket() -> None:
    # A sample at t = end belongs to the NEXT bucket — [start, end) is
    # half-open on both ends of the query range.
    assert bucket_index_for(0, 0, 1_000) == 0
    assert bucket_index_for(999, 0, 1_000) == 0
    assert bucket_index_for(1_000, 0, 1_000) == 1


def test_bucket_index_rejects_samples_outside_the_query_range() -> None:
    with pytest.raises(ValueError):
        bucket_index_for(2_000, 0, 1_000, bucket_total=2)  # t == end → outside
    with pytest.raises(ValueError):
        bucket_index_for(-1, 0, 1_000, bucket_total=2)  # before start
