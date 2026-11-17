"""Phase 2 encapsulation-layer throughput profile — ticket #136 (SPEC-600
§9 / SPEC-610 §9 / SPEC-611 §9 benchmark acceptance).

The three §9 budgets, measured on the REAL production primitives:

| face        | §9 budget (budget INPUT, never an assertion pin)   | measured by |
|-------------|----------------------------------------------------|-------------|
| T2-MI chain | outer T2-MI processing throughput ≥ scenario stream bound (MVP envelope 1~100 Mbps 量级, SPEC-600 §9) | ``TestT2miChainThroughputProfile`` |
| BISS Mode 1 | SSE2 batch scramble/descramble margin posture (SPEC-610 §9; the #106 raw-API face ran ~497 Mbps — this module measures the END-TO-END primitive face incl. per-packet dataclass/ctypes marshaling, a strictly slower aperture) | ``TestBissMode1DllThroughputProfile`` |
| CISSA       | pure-Python AES-128-CBC face meets envelope-scale rates (SPEC-611 §9; #106 measured 134 Mbps on the raw payload face) | ``TestCissaThroughputProfile`` |

DISCIPLINE (ruling §10-8, tests/README §6, mirroring
``tests/integration/observation_perf/test_obs_perf_profile.py``):

- everything here is ``slow`` — the CI-green combination excludes it;
- NO assertion pins a §9 Mbps budget value: budgets are printed as
  ``PERF-RESULT`` lines with the envelope margin computed at run time;
  the asserts are order-of-magnitude COLLAPSE GUARDS set roughly an
  order below measured bench reality (best-of-runs posture,
  docs/research/python-perf.md §8) so a catastrophic regression fails
  while normal cross-machine noise passes;
- the measured-budget gap (e.g. the encapsulation-side ``t2mi_build``
  bottleneck) is REPORTED as evidence, never threshold-tuned here;
- all byte material from the deterministic generator (sanctioned source
  2, tests/README §5); key material derived from seeds (never literal);
- no sleep-based pacing: walls are measured, never waited on;
- the DLL face is ``dvbcsa_dll``-gated: DLL absence skips with a
  visible reason (SPEC-610 §8; CI NOT RUN semantics, ADR-0011 §5).
"""

from __future__ import annotations

import platform
import sys
import time

import pytest

from tests._support.deterministic import seeded_bytes

pytestmark = pytest.mark.slow

# --- budget inputs (SPEC §9 constants, printed as evidence — NOT thresholds) --
ENVELOPE_FLOOR_MBPS = 1.0
ENVELOPE_CEIL_MBPS = 100.0
#: #106 evidence points (printed alongside for margin framing only).
BISS_SSE2_RAW_API_EVIDENCE_MBPS = 497.0
CISSA_EVIDENCE_MBPS = 134.0

# Bench sizing: enough packets for a stable rate, small enough that the
# slow module stays minutes-scale (best-of-runs × facets).
T2MI_TS_BYTES = 4 * 1024 * 1024 // 188 * 188  # ~21.8k UPs → ~21.8k T2-MI pkts
BISS_PACKETS = 8_000

#: measurement repeats; the recorded rate is the best of them (best-of-runs
#: bench posture — ±10% desktop noise, docs/research/python-perf.md §8).
_REPEATS = 3


def _mbps(nbytes: int, elapsed_ns: int) -> float:
    return nbytes * 8 / (elapsed_ns / 1e9) / 1e6


def _best_of(repeats: int, probe) -> float:
    """Run ``probe()`` ``repeats`` times; return the best observed rate.

    ``probe`` returns ``BytesPerSecond-ish`` tuple ``(bytes, elapsed_ns)``.
    """
    best = 0.0
    for _ in range(repeats):
        nbytes, elapsed_ns = probe()
        best = max(best, _mbps(nbytes, elapsed_ns))
    return best


def _perf_line(item: str, **fields) -> None:
    rendered = " ".join(f"{key}={value}" for key, value in fields.items())
    print(f"PERF-RESULT item={item} {rendered}", flush=True)


def _env_line() -> None:
    print(
        "PERF-ENV "
        f"os={platform.system()}-{platform.release()} "
        f"python={sys.version.split()[0]} "
        f"cpu={platform.processor() or platform.machine()}",
        flush=True,
    )


@pytest.fixture(autouse=True)
def _print_bench_env():
    _env_line()
    yield


# ============================================================================
# SPEC-600 §9 — outer T2-MI chain (encapsulation + decapsulation)
# ============================================================================


class TestT2miChainThroughputProfile:
    """The three-level chain on production primitives: TS → BBFRAME build
    → T2-MI build → wire stream, and back (parse → Inner TS rebuild).
    Rates are expressed against the OUTER stream bytes (the §9 “外层
    T2-MI 处理吞吐” aperture)."""

    def test_encapsulation_chain_throughput(self):
        from ts.t2mi.bbframe import BBFrameBuildConfig, build as bbframe_build
        from ts.t2mi.builder import T2miBuildConfig, build as t2mi_build
        from ts.t2mi.packet import encode_packet

        up_stream = seeded_bytes(20261117, T2MI_TS_BYTES)
        bb_cfg = BBFrameBuildConfig()
        t2_cfg = T2miBuildConfig()

        def _probe() -> tuple[int, int]:
            started = time.perf_counter_ns()
            frames = bbframe_build(up_stream, bb_cfg)
            packets = t2mi_build(frames, t2_cfg)
            stream = b"".join(encode_packet(p) for p in packets)
            return len(up_stream), time.perf_counter_ns() - started

        mbps = _best_of(_REPEATS, _probe)
        _perf_line(
            "t2mi_encap_chain",
            input_ts_bytes=T2MI_TS_BYTES,
            repeats=_REPEATS,
            mbps=round(mbps, 1),
            envelope_floor_mbps=ENVELOPE_FLOOR_MBPS,
            envelope_ceil_mbps=ENVELOPE_CEIL_MBPS,
            margin_vs_floor=round(mbps / ENVELOPE_FLOOR_MBPS, 1),
        )
        # Collapse guard ~9× under measured bench reality (4-5 Mbps on the
        # reference bench; t2mi_build per-packet assembly dominates — the
        # gap vs the envelope ceiling is recorded in the ticket report,
        # never tuned here).
        assert mbps >= 0.5, f"encapsulation chain collapsed to {mbps:.2f} Mbps"

    def test_decapsulation_chain_throughput(self):
        from ts.t2mi.bbframe import BBFrameBuildConfig, build as bbframe_build
        from ts.t2mi.builder import T2miBuildConfig, build as t2mi_build
        from ts.t2mi.inner_ts import reconstruct
        from ts.t2mi.packet import encode_packet
        from ts.t2mi.parser import parse as t2mi_parse

        up_stream = seeded_bytes(20261117, T2MI_TS_BYTES)
        stream = b"".join(
            encode_packet(p)
            for p in t2mi_build(
                bbframe_build(up_stream, BBFrameBuildConfig()), T2miBuildConfig()
            )
        )

        def _probe() -> tuple[int, int]:
            started = time.perf_counter_ns()
            result = t2mi_parse(stream)
            inner = reconstruct(result.packets)
            assert inner.reconstruction_status == "ok"
            return len(stream), time.perf_counter_ns() - started

        mbps = _best_of(_REPEATS, _probe)
        _perf_line(
            "t2mi_decap_chain",
            outer_stream_bytes=len(stream),
            repeats=_REPEATS,
            mbps=round(mbps, 1),
            envelope_floor_mbps=ENVELOPE_FLOOR_MBPS,
            envelope_ceil_mbps=ENVELOPE_CEIL_MBPS,
            margin_vs_floor=round(mbps / ENVELOPE_FLOOR_MBPS, 1),
        )
        # Collapse guard ~10× under measured bench reality (~85 Mbps:
        # parse ~400 + reconstruct ~110). This is the demux-side outer
        # processing rate the §9 budget speaks to.
        assert mbps >= 5.0, f"decapsulation chain collapsed to {mbps:.2f} Mbps"


# ============================================================================
# SPEC-611 §9 — CISSA (pure Python, pycryptodome AES-128-CBC)
# ============================================================================


class TestCissaThroughputProfile:
    """The BISS2/Mode-E payload face (per-packet AES-128-CBC restart,
    fixed IV). Zero native dependencies — CI-runnable everywhere; the
    DLL face below is the contrast case."""

    def test_cissa_scramble_descramble_throughput(self):
        from ts.biss.cissa import descramble, scramble
        from ts.packet import TSPacket

        ciss_key = seeded_bytes(0xC155A, 16).hex().upper()
        pid = 0x1000
        payload = seeded_bytes(4242, 184)
        packets = tuple(
            TSPacket(pid=pid, continuity_counter=i % 16, payload=payload)
            for i in range(BISS_PACKETS)
        )
        stream_bytes = BISS_PACKETS * 188

        def _scramble_probe() -> tuple[int, int]:
            started = time.perf_counter_ns()
            out = scramble(packets, ciss_key, (pid,))
            return stream_bytes, time.perf_counter_ns() - started

        def _descramble_probe() -> tuple[int, int]:
            scrambled = scramble(packets, ciss_key, (pid,))
            started = time.perf_counter_ns()
            out, _checks = descramble(scrambled, ciss_key, (pid,))
            assert all(p.payload == payload for p in out)
            return stream_bytes, time.perf_counter_ns() - started

        scramble_mbps = _best_of(_REPEATS, _scramble_probe)
        descramble_mbps = _best_of(_REPEATS, _descramble_probe)
        _perf_line(
            "cissa_face",
            packets=BISS_PACKETS,
            repeats=_REPEATS,
            scramble_mbps=round(scramble_mbps, 1),
            descramble_mbps=round(descramble_mbps, 1),
            evidence_mbps=CISSA_EVIDENCE_MBPS,
            envelope_floor_mbps=ENVELOPE_FLOOR_MBPS,
            margin_vs_floor=round(min(scramble_mbps, descramble_mbps) / ENVELOPE_FLOOR_MBPS, 1),
        )
        # Collapse guards ~8-15× under measured bench reality (scramble
        # ~46-77 Mbps, descramble ~41-77 Mbps across runs — desktop noise
        # band; the #106 134 Mbps evidence point is printed above).
        assert scramble_mbps >= 4.0, f"CISSA scramble collapsed to {scramble_mbps:.2f} Mbps"
        assert descramble_mbps >= 4.0, (
            f"CISSA descramble collapsed to {descramble_mbps:.2f} Mbps"
        )


# ============================================================================
# SPEC-610 §9 — BISS Mode 1 SSE2 batch face (DLL-gated, honest NOT RUN)
# ============================================================================


class TestBissMode1DllThroughputProfile:
    """SSE2 bitslice batch backend end-to-end (scramble + descramble
    through the production primitive, per-packet TSPacket/ctypes
    marshaling included). DLL absence → ``dvbcsa_dll`` fixture skip with
    a visible reason (SPEC-610 §8, ADR-0011 §5): CI NOT RUN is honest,
    the local build (tools/build_dvbcsa_dll.sh) restores the face."""

    def test_sse2_batch_scramble_descramble_throughput(self, dvbcsa_dll):
        from adapters.dvbcsa._binding import DvbcsaBatchCipher
        from ts.biss.biss1 import descramble, scramble
        from ts.packet import TSPacket

        session_word = seeded_bytes(0xB155, 6).hex().upper()  # 12 hex, 48-bit
        pid = 0x1000
        payload = seeded_bytes(4242, 184)
        packets = tuple(
            TSPacket(pid=pid, continuity_counter=i % 16, payload=payload)
            for i in range(BISS_PACKETS)
        )
        stream_bytes = BISS_PACKETS * 188
        backend = DvbcsaBatchCipher(dll_path=dvbcsa_dll.path)

        def _scramble_probe() -> tuple[int, int]:
            started = time.perf_counter_ns()
            out = scramble(packets, session_word, (pid,), backend=backend)
            return stream_bytes, time.perf_counter_ns() - started

        def _descramble_probe() -> tuple[int, int]:
            scrambled = scramble(packets, session_word, (pid,), backend=backend)
            started = time.perf_counter_ns()
            out, _checks = descramble(
                scrambled, session_word, (pid,), backend=backend
            )
            assert all(p.payload == payload for p in out)
            return stream_bytes, time.perf_counter_ns() - started

        scramble_mbps = _best_of(_REPEATS, _scramble_probe)
        descramble_mbps = _best_of(_REPEATS, _descramble_probe)
        _perf_line(
            "biss_sse2_face",
            packets=BISS_PACKETS,
            repeats=_REPEATS,
            batch_size=backend.batch_size(),
            dll_path=dvbcsa_dll.path,
            scramble_mbps=round(scramble_mbps, 1),
            descramble_mbps=round(descramble_mbps, 1),
            raw_api_evidence_mbps=BISS_SSE2_RAW_API_EVIDENCE_MBPS,
            envelope_floor_mbps=ENVELOPE_FLOOR_MBPS,
            margin_vs_floor=round(min(scramble_mbps, descramble_mbps) / ENVELOPE_FLOOR_MBPS, 1),
        )
        # Collapse guards ~10× under measured bench reality (~99-107 Mbps
        # end-to-end primitive face; the #106 497 Mbps raw-API point is a
        # strictly narrower aperture and is printed for framing only).
        assert scramble_mbps >= 8.0, f"SSE2 scramble collapsed to {scramble_mbps:.2f} Mbps"
        assert descramble_mbps >= 8.0, (
            f"SSE2 descramble collapsed to {descramble_mbps:.2f} Mbps"
        )
