"""SPEC-108 §7 step 4 — deterministic synthetic PES payload sources (#34).

One :class:`SyntheticPESSource` per elementary stream produces the PES items
the mux consumes through :class:`ts.mux.sources.PESPacketSource`.  Payloads
are deterministic synthetic test data (SPEC-108 §2: the ``analysis_only``
profile never claims decodable real audio/video) built exclusively from
frozen upstream components:

- PES packets come from :func:`ts.pes.make_analysis_only_pes` (#30) — the
  analysis-only construction mark is set, the payload is a fixed-literal
  profile, and :func:`ts.pes.serialize_pes` owns every PES wire byte.
- PTS values come from :class:`ts.clock.MediaClock` (#27) — the 27 MHz →
  90 kHz conversion exists exactly once upstream and is never duplicated
  here (contract §2.3).  A PES item's PTS is the media time its first byte
  would be consumed at the stream's configured bitrate: a smooth, seed-
  independent schedule (seed changes never move protocol fields — §8).

Determinism (SPEC-108 §8): the payload PRNG is a version-pinned 32-bit
xorshift with an explicit integer seed derived from ``seed``,
``payload_seed_offset``, the ES PID and the stream_id — no ``random``
module, no ``hash()``, no wall clock, no dict-iteration order anywhere.
``PAYLOAD_PRNG_ALGORITHM`` names the pinned algorithm; changing it is a
generator-version bump (it changes output bytes).

Sizing: :func:`synthetic_pes_byte_budget` computes the serialized-byte
budget the whole run can possibly pull from one ES
(``floor(N*R/B) + slack`` packets at 184 payload bytes each, exact integer
arithmetic); the source emits just enough fixed-size PES items to cover it,
so an ES never dries up mid-run — a dry source would silently null-fill its
slots and break the CBR share the config promised (per-source exhaustion is
mux-normal, so the Generator prevents it by construction).
"""

from __future__ import annotations

from collections.abc import Iterator

from ts.clock import MediaClock
from ts.generator.config import ElementaryStreamConfig
from ts.packet import TS_PACKET_SIZE
from ts.pes import PESPacket, make_analysis_only_pes, serialize_pes

#: Version-pinned payload PRNG algorithm (SPEC-108 §8: explicit, version-
#: fixed, explicitly seeded).  This constant is part of the generation
#: fingerprint: changing the algorithm changes output bytes and therefore
#: must bump the generator version.
PAYLOAD_PRNG_ALGORITHM = "xorshift32-v1"

#: Fixed synthetic payload size per PES item (bytes).  512 keeps every item
#: a multi-packet PES (526 serialized bytes ≈ 3 TS packets at 184 payload
#: bytes), giving frequent PES starts so payload-first PCR attachment finds
#: PES boundaries inside its target window.
SYNTHETIC_PES_PAYLOAD_BYTES = 512

#: Serialized PES item size with the MVP PTS-only header: 6-byte prefix +
#: 3 control bytes + 5-byte PTS + payload (SPEC-104 §3/§5, auto length).
_SYNTHETIC_PES_SERIALIZED_BYTES = 14 + SYNTHETIC_PES_PAYLOAD_BYTES

#: Slack packets added to the per-run pull estimate (boundary rounding of
#: the floor formulas plus the mux's one-item PES lookahead).
_BUDGET_SLACK_PACKETS = 4

#: PRNG seed-mixing constants (fixed, version-pinned integers — never
#: process-dependent; the nonzero fallback keeps xorshift32 off the
#: all-zero fixed point).
_SEED_MIX_PID = 0x85EBCA6B
_SEED_MIX_OFFSET = 0x27D4EB2F
_SEED_MIX_BASE = 0xC2B2AE3D
_SEED_FALLBACK = 0x9E3779B9

#: PES packets per serialized item at 184 payload bytes per packet, for the
#: budget derivation: ceil(526 / 184) == 3.
_PACKETS_PER_PES_ITEM_ESTIMATE = 3


def synthetic_pes_byte_budget(
    output_packet_count: int, target_bitrate_bps: int, es_bitrate_bps: int
) -> int:
    """Serialized PES bytes one ES can at most consume over the run.

    Exact integer derivation of the SPEC-107 §5.1 release accumulator: a
    source at ``es_bitrate_bps`` can emit at most ``floor(N*R/B) + 1``
    packets in ``N`` slots, each carrying 184 payload bytes; the +slack
    covers boundary rounding and the one-item lookahead so the source never
    starves (a starved ES silently null-fills and breaks the CBR promise).
    """
    pull_bound = (output_packet_count * es_bitrate_bps) // target_bitrate_bps
    return (pull_bound + _BUDGET_SLACK_PACKETS) * (
        TS_PACKET_SIZE - 4
    )


def _mix_seed(seed: int, config: ElementaryStreamConfig) -> int:
    """Explicit integer PRNG seed for one ES (SPEC-108 §8, version-pinned)."""
    state = (
        seed
        + config.payload_seed_offset * _SEED_MIX_OFFSET
        + config.pid * _SEED_MIX_PID
        + config.stream_id * _SEED_MIX_BASE
    ) & 0xFFFFFFFF
    if state == 0:
        state = _SEED_FALLBACK
    return state


def _xorshift32(state: int) -> int:
    """One pinned xorshift32 step (Marsaglia triple {13, 17, 5})."""
    state ^= (state << 13) & 0xFFFFFFFF
    state ^= state >> 17
    state ^= (state << 5) & 0xFFFFFFFF
    return state & 0xFFFFFFFF


class SyntheticPESSource:
    """Deterministic analysis-only PES item source for one ES (§7 step 4).

    Yields exactly ``item_count`` fixed-size PES packets covering
    ``byte_budget`` serialized bytes.  Replaying the same constructor
    arguments reproduces byte-identical items (the determinism test pins
    this); the items are consumed lazily by the mux's
    :class:`ts.mux.sources.PESPacketSource`.
    """

    def __init__(
        self,
        *,
        stream_config: ElementaryStreamConfig,
        seed: int,
        initial_media_clock_27mhz: int,
        byte_budget: int,
    ) -> None:
        if not isinstance(stream_config, ElementaryStreamConfig):
            raise TypeError(
                "stream_config must be ElementaryStreamConfig, got "
                f"{type(stream_config).__name__}"
            )
        if not isinstance(seed, int) or isinstance(seed, bool):
            raise TypeError(f"seed must be int, got {type(seed).__name__}")
        if not isinstance(initial_media_clock_27mhz, int) or isinstance(
            initial_media_clock_27mhz, bool
        ):
            raise TypeError(
                "initial_media_clock_27mhz must be int, got "
                f"{type(initial_media_clock_27mhz).__name__}"
            )
        if initial_media_clock_27mhz < 0:
            raise ValueError(
                f"initial_media_clock_27mhz must be non-negative, got "
                f"{initial_media_clock_27mhz}"
            )
        if not isinstance(byte_budget, int) or isinstance(byte_budget, bool):
            raise TypeError(
                f"byte_budget must be int, got {type(byte_budget).__name__}"
            )
        if byte_budget < 1:
            raise ValueError(f"byte_budget must be >= 1, got {byte_budget}")
        self._config = stream_config
        self._seed = seed
        self._initial = initial_media_clock_27mhz
        self._item_count = max(
            1, -(-byte_budget // _SYNTHETIC_PES_SERIALIZED_BYTES)
        )

    @property
    def item_count(self) -> int:
        """Number of PES items the source yields."""
        return self._item_count

    @property
    def serialized_item_bytes(self) -> int:
        """Serialized size of every yielded item (fixed-size schedule)."""
        return _SYNTHETIC_PES_SERIALIZED_BYTES

    def iter_pes(self) -> Iterator[PESPacket]:
        """Yield the deterministic PES items in stable order (§7 step 4)."""
        state = _mix_seed(self._seed, self._config)
        # Media-time schedule: one item occupies serialized_bytes*8 bits at
        # the ES bitrate; the PTS is the 90 kHz time of the item's first
        # byte (seed-independent, SPEC-105 owns the conversion).
        ticks_per_item = (
            _SYNTHETIC_PES_SERIALIZED_BYTES * 8 * 27_000_000
        ) // self._config.bitrate_bps
        for index in range(self._item_count):
            payload = bytearray()
            for _ in range(SYNTHETIC_PES_PAYLOAD_BYTES):
                state = _xorshift32(state)
                payload.append(state & 0xFF)
            clock = MediaClock(self._initial + index * ticks_per_item)
            yield make_analysis_only_pes(
                stream_id=self._config.stream_id,
                payload=bytes(payload),
                pts=clock.pts90k(),
            )

    def serialized_items(self) -> list[bytes]:
        """Eagerly serialize every item (test/diagnostic convenience)."""
        return [serialize_pes(item) for item in self.iter_pes()]
