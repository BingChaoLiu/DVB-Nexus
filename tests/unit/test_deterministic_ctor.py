"""Unit-layer tests for the deterministic test-data constructors.

Sanctioned source 2 of SPEC-505 §6 test-data discipline: fixed-seed
deterministic scenario generation (same seed + same parameters ⇒ same
bytes). Pure computation — no I/O, no wall clock.
"""

from __future__ import annotations

import hashlib

import pytest

from tests._support.deterministic import (
    PACKET_SIZE,
    SEED_MIN,
    SEED_MAX,
    SYNC_BYTE,
    seeded_bytes,
    seeded_ts_stream,
    stream_sha256,
)


class TestSeededBytes:
    def test_same_seed_same_bytes(self):
        assert seeded_bytes(7, 64) == seeded_bytes(7, 64)

    def test_different_seed_different_bytes(self):
        assert seeded_bytes(7, 64) != seeded_bytes(8, 64)

    def test_length_honoured(self):
        assert len(seeded_bytes(1, 250)) == 250

    def test_zero_length_empty(self):
        assert seeded_bytes(1, 0) == b""


class TestSeededTsStream:
    def test_same_seed_same_stream(self):
        assert seeded_ts_stream(123, 16) == seeded_ts_stream(123, 16)

    def test_different_seed_different_stream(self):
        assert seeded_ts_stream(123, 16) != seeded_ts_stream(124, 16)

    def test_stream_length_is_packet_framed(self):
        stream = seeded_ts_stream(5, 7)
        assert len(stream) == 7 * PACKET_SIZE

    def test_sync_byte_at_every_packet_slot(self):
        stream = seeded_ts_stream(99, 12)
        for index in range(12):
            assert stream[index * PACKET_SIZE] == SYNC_BYTE

    def test_prefix_stability_exact(self):
        # Extending packet_count must keep the earlier bytes stable
        # (append-only construction), so expectations recorded against a
        # shorter stream survive a longer regeneration of the same seed.
        short = seeded_ts_stream(42, 4)
        long = seeded_ts_stream(42, 8)
        assert long[: len(short)] == short


class TestSeedDomain:
    @pytest.mark.parametrize("bad_seed", [-1, 2**64, 2**128])
    def test_out_of_uint64_domain_rejected(self, bad_seed):
        with pytest.raises(ValueError):
            seeded_bytes(bad_seed, 8)

    def test_uint64_boundaries_accepted(self):
        seeded_bytes(SEED_MIN, 8)
        seeded_bytes(SEED_MAX, 8)
        seeded_ts_stream(SEED_MAX, 1)


class TestStreamSha256:
    def test_matches_direct_hash_of_stream(self):
        stream = seeded_ts_stream(11, 5)
        assert stream_sha256(11, 5) == hashlib.sha256(stream).hexdigest()

    def test_stable_across_repeated_calls(self):
        assert stream_sha256(11, 5) == stream_sha256(11, 5)
