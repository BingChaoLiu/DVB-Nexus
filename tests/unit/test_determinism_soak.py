"""Determinism soak (``slow``): same seed twice ⇒ all green, at scale.

SPEC-505 §8 "确定性：同 seed 两次全绿（无墙钟依赖断言）" — the unit layer
has the small-scale determinism tests; this soak scales the same property
across many seeds and stream lengths. Pure computation (no I/O, no wall
clock waits); marked ``slow`` so the CI PR gate excludes it and the nightly
workflow runs it (SPEC-505 §5), while bare local ``pytest`` still runs it.
"""

from __future__ import annotations

import pytest

from tests._support.deterministic import seeded_ts_stream, stream_sha256

pytestmark = [pytest.mark.slow]

#: Sized for a meaningful soak (~seconds): nightly CI reruns it on every
#: schedule tick; local bare runs pay the same cost by design (SPEC-505 §5
#: "slow 默认本地跑").
SEEDS: range = range(1024)
PACKET_COUNT: int = 4096


def test_same_seed_two_constructions_identical_at_scale():
    for seed in SEEDS:
        first = stream_sha256(seed, PACKET_COUNT)
        second = stream_sha256(seed, PACKET_COUNT)
        assert first == second, f"seed {seed}: same-seed constructions diverged"


def test_distinct_seeds_produce_distinct_streams():
    digests = {stream_sha256(seed, PACKET_COUNT) for seed in SEEDS}
    assert len(digests) == len(SEEDS)


def test_stream_identity_is_prefix_stable_across_lengths():
    short = seeded_ts_stream(20260101, 256)
    long = seeded_ts_stream(20260101, PACKET_COUNT)
    assert long[: len(short)] == short
