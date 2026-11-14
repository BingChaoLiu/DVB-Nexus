#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OPEN-006: pure-Python MPEG-TS CBR generation micro-benchmarks.

Scratch research script -- discardable, NOT for the repo. Stdlib only.
Python >= 3.10.  Run:  python -I bench.py [--quick]

Benchmarks:
  a) dataclass construction rate (1M TS packet objects, SPEC-100-like model)
  b) bytes-level serialization rate (struct.pack / bytearray variants)
  c) sequential file write rate (188-byte packet stream, ~188 MB)
  d) simplified packet-slot scheduler end-to-end rate
     (integer phase accumulator per PID + table periods + null fill + file IO)
"""
from __future__ import annotations

import argparse
import gc
import json
import os
import platform
import struct
import sys
import time
import tracemalloc
from dataclasses import dataclass
from typing import Optional

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, "benchdata")

# ------------------------------------------------------------------ TS constants
PKT_SIZE = 188
SYNC = 0x47

NULL_PAYLOAD = b"\xFF" * 184
VIDEO_PAYLOAD = b"\x5A" * 184
AUDIO_PAYLOAD = b"\xA5" * 184

# Null packet: PID 0x1FFF, AFC=payload-only(01), CC=0 (SPEC-107 5.1)
NULL_PKT = bytes((SYNC, 0x1F, 0xFF, 0x10)) + NULL_PAYLOAD


def _pad(section: bytes) -> bytes:
    return section + b"\xFF" * (184 - len(section))


_PAT_SECTION = bytes.fromhex("00 00 B0 0D 00 01 C1 00 00 00 01 E1 00 DE AD BE EF")
_PMT_SECTION = bytes.fromhex(
    "00 02 B0 1D 00 01 C1 00 00 E1 00 00 00 1B E1 00 F0 00 0F AC 15 40 DE AD BE EF"
)
PAT_PAYLOAD = _pad(_PAT_SECTION)
PMT_PAYLOAD = _pad(_PMT_SECTION)
# af_len=7 -> flags(1)+PCR(6); AFC=11 -> payload 176 bytes
VIDEO_PCR_BODY = bytes.fromhex("07 10 00 00 00 01 00 00") + b"\x5A" * 176

PIDS = (0x100, 0x101, 0x1FFF, 0x100)

assert len(NULL_PKT) == PKT_SIZE and NULL_PKT[0] == SYNC
assert len(PAT_PAYLOAD) == 184 and len(PMT_PAYLOAD) == 184
assert len(VIDEO_PCR_BODY) == 184

# ------------------------------------------------------------------ data models


@dataclass(frozen=True)
class TSPacketFrozen:
    pid: int
    continuity_counter: int
    payload: Optional[bytes]
    adaptation_field: Optional[bytes] = None  # simplified: raw AF bytes or None
    transport_error_indicator: bool = False
    payload_unit_start_indicator: bool = False
    transport_priority: bool = False
    transport_scrambling_control: int = 0


@dataclass
class TSPacketPlain:
    pid: int
    continuity_counter: int
    payload: Optional[bytes]
    adaptation_field: Optional[bytes] = None
    transport_error_indicator: bool = False
    payload_unit_start_indicator: bool = False
    transport_priority: bool = False
    transport_scrambling_control: int = 0


@dataclass(frozen=True, slots=True)
class TSPacketSlots:
    pid: int
    continuity_counter: int
    payload: Optional[bytes]
    adaptation_field: Optional[bytes] = None
    transport_error_indicator: bool = False
    payload_unit_start_indicator: bool = False
    transport_priority: bool = False
    transport_scrambling_control: int = 0


# ------------------------------------------------------------------ helpers


def timeit(fn, repeats=3):
    ts = []
    ret = None
    for _ in range(repeats):
        gc.collect()
        t0 = time.perf_counter()
        ret = fn()
        ts.append(time.perf_counter() - t0)
    ts.sort()
    return ts, ret


def entry(n, ts, unit="pkts"):
    best, median = ts[0], ts[len(ts) // 2]
    return {
        "n": n,
        "times_s": [round(t, 4) for t in ts],
        "best_s": round(best, 4),
        "median_s": round(median, 4),
        "per_op_ns_best": round(best / n * 1e9, 1),
        "ops_per_s_best": round(n / best, 0),
    }


def mem_per_obj(make, n=100_000):
    """Rough per-instance traced bytes (minus ~8 B list pointer)."""
    gc.collect()
    tracemalloc.start()
    before = tracemalloc.get_traced_memory()[0]
    objs = make(n)
    cur = tracemalloc.get_traced_memory()[0]
    tracemalloc.stop()
    del objs
    return round((cur - before - 8 * n) / n, 1)


# ------------------------------------------------------------------ (a) dataclass


def build_frozen_pos(n, keep=True):
    out = [] if keep else None
    append = out.append if keep else (lambda o: None)
    cc = 0
    for i in range(n):
        cc = (cc + 1) & 0xF
        append(TSPacketFrozen(PIDS[i & 3], cc, VIDEO_PAYLOAD, None,
                              False, i % 1000 == 0, False, 0))
    return out


def build_frozen_kwargs(n, keep=True):
    out = [] if keep else None
    append = out.append if keep else (lambda o: None)
    cc = 0
    for i in range(n):
        cc = (cc + 1) & 0xF
        append(TSPacketFrozen(pid=PIDS[i & 3], continuity_counter=cc,
                              payload=VIDEO_PAYLOAD, adaptation_field=None,
                              transport_error_indicator=False,
                              payload_unit_start_indicator=i % 1000 == 0,
                              transport_priority=False,
                              transport_scrambling_control=0))
    return out


def build_plain_pos(n, keep=True):
    out = [] if keep else None
    append = out.append if keep else (lambda o: None)
    cc = 0
    for i in range(n):
        cc = (cc + 1) & 0xF
        append(TSPacketPlain(PIDS[i & 3], cc, VIDEO_PAYLOAD, None,
                             False, i % 1000 == 0, False, 0))
    return out


def build_slots_pos(n, keep=True):
    out = [] if keep else None
    append = out.append if keep else (lambda o: None)
    cc = 0
    for i in range(n):
        cc = (cc + 1) & 0xF
        append(TSPacketSlots(PIDS[i & 3], cc, VIDEO_PAYLOAD, None,
                             False, i % 1000 == 0, False, 0))
    return out


def build_tuple(n, keep=True):
    out = [] if keep else None
    append = out.append if keep else (lambda o: None)
    cc = 0
    for i in range(n):
        cc = (cc + 1) & 0xF
        append((PIDS[i & 3], cc, VIDEO_PAYLOAD, None,
                False, i % 1000 == 0, False, 0))
    return out


def build_frozen_pos_gc_off(n, keep=True):
    gc.disable()
    try:
        return build_frozen_pos(n, keep=keep)
    finally:
        gc.enable()


# ------------------------------------------------------------------ (b) serialize


def ser_struct(n):
    pack = struct.pack
    last = b""
    for i in range(n):
        pid = PIDS[i & 3]
        last = (pack(">BBBB", SYNC, (0x40 if i % 1000 == 0 else 0) | (pid >> 8),
                     pid & 0xFF, 0x10 | (i & 0xF)) + VIDEO_PAYLOAD)
    return last


def ser_bytes_tuple(n):
    last = b""
    for i in range(n):
        pid = PIDS[i & 3]
        last = (bytes((SYNC, (0x40 if i % 1000 == 0 else 0) | (pid >> 8),
                       pid & 0xFF, 0x10 | (i & 0xF))) + VIDEO_PAYLOAD)
    return last


_TMPL_VIDEO = bytearray(bytes((SYNC, 0x01, 0x00, 0x10)) + VIDEO_PAYLOAD)


def ser_tmpl_copy(n):
    tmpl = _TMPL_VIDEO
    last = b""
    for i in range(n):
        buf = bytearray(tmpl)
        buf[3] = 0x10 | (i & 0xF)
        last = bytes(buf)
    return last


def ser_reuse_nocopy(n):
    buf = bytearray(_TMPL_VIDEO)
    for i in range(n):
        buf[3] = 0x10 | (i & 0xF)
    return bytes(buf)


# ------------------------------------------------------------------ (c) file write


def write_per_packet(path, n):
    pkt = NULL_PKT
    with open(path, "wb") as f:  # default BufferedWriter (8 KB)
        w = f.write
        for _ in range(n):
            w(pkt)


def write_chunked(path, n, chunk_packets=512):
    pkt = NULL_PKT
    chunk = pkt * chunk_packets  # 96,256 bytes
    with open(path, "wb", buffering=1 << 20) as f:
        full, rem = divmod(n, chunk_packets)
        for _ in range(full):
            f.write(chunk)
        if rem:
            f.write(pkt * rem)


# ------------------------------------------------------------------ (d) scheduler

B_TOTAL = 16_000_000
R_VIDEO = 12_000_000
R_AUDIO = 1_500_000


def sched_only(n_slots, B=B_TOTAL, rv=R_VIDEO, ra=R_AUDIO):
    """Decision-only: integer Bresenham phase per PID + periodic tables/PCR."""
    slot_rate = B / 1504.0
    pat_every = max(1, round(slot_rate * 0.1))
    pmt_every = max(1, round(slot_rate * 0.1))
    pcr_every = max(1, round(slot_rate * 0.04))
    pat_next = 0
    pmt_next = pmt_every  # offset PMT so it does not always collide with PAT
    pcr_next = pcr_every
    accv = acca = 0
    ccv = cca = ccp = ccm = 0
    vcount = chk = 0
    for n in range(n_slots):
        if n >= pat_next:
            ccp = (ccp + 1) & 0xF
            pat_next += pat_every
            chk += 1
            continue
        if n >= pmt_next:
            ccm = (ccm + 1) & 0xF
            pmt_next += pmt_every
            chk += 2
            continue
        if n >= pcr_next:
            ccv = (ccv + 1) & 0xF  # PCR rides on a video AF packet (payload)
            pcr_next += pcr_every
            accv -= B              # consume one video credit
            chk += 3
            continue
        accv += rv
        acca += ra
        if accv >= B:
            accv -= B
            vcount += 1
            ccv = (ccv + 1) & 0xF
            chk += 4
        elif acca >= B:
            acca -= B
            cca = (cca + 1) & 0xF
            chk += 5
        else:
            chk += 6  # null slot
    return chk, vcount


def sched_e2e(path, n_slots, B=B_TOTAL, rv=R_VIDEO, ra=R_AUDIO):
    """End-to-end: decision + header encode + 188B serialize + sink.write()."""
    slot_rate = B / 1504.0
    pat_every = max(1, round(slot_rate * 0.1))
    pmt_every = max(1, round(slot_rate * 0.1))
    pcr_every = max(1, round(slot_rate * 0.04))
    pat_next = 0
    pmt_next = pmt_every
    pcr_next = pcr_every
    accv = acca = 0
    ccv = cca = ccp = ccm = 0
    vcount = nulls = 0
    fout = open(path, "wb")
    w = fout.write
    for n in range(n_slots):
        if n >= pat_next:
            pkt = bytes((SYNC, 0x40, 0x00, ccp)) + PAT_PAYLOAD
            ccp = (ccp + 1) & 0xF
            pat_next += pat_every
            w(pkt)
            continue
        if n >= pmt_next:
            pkt = bytes((SYNC, 0x50, 0x00, ccm)) + PMT_PAYLOAD
            ccm = (ccm + 1) & 0xF
            pmt_next += pmt_every
            w(pkt)
            continue
        if n >= pcr_next:
            pkt = bytes((SYNC, 0x01, 0x00, 0x30 | ccv)) + VIDEO_PCR_BODY
            ccv = (ccv + 1) & 0xF
            pcr_next += pcr_every
            accv -= B
            w(pkt)
            continue
        accv += rv
        acca += ra
        if accv >= B:
            accv -= B
            vcount += 1
            pusi = 0x40 if vcount % 1000 == 0 else 0x00
            pkt = bytes((SYNC, pusi | 0x01, 0x00, 0x10 | ccv)) + VIDEO_PAYLOAD
            ccv = (ccv + 1) & 0xF
            w(pkt)
        elif acca >= B:
            acca -= B
            pkt = bytes((SYNC, 0x01, 0x01, 0x10 | cca)) + AUDIO_PAYLOAD
            cca = (cca + 1) & 0xF
            w(pkt)
        else:
            w(NULL_PKT)
            nulls += 1
    fout.close()
    return nulls, vcount


# ------------------------------------------------------------------ main


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--json", default="results.json")
    ap.add_argument("--repeats", type=int, default=3)
    args = ap.parse_args()

    n_obj = 100_000 if args.quick else 1_000_000
    n_ser = 200_000 if args.quick else 1_000_000
    n_wr = 100_000 if args.quick else 1_000_000
    n_slots = 50_000 if args.quick else 500_000
    rep = args.repeats

    os.makedirs(DATA_DIR, exist_ok=True)

    env = {
        "python": sys.version.replace("\n", " "),
        "executable": sys.executable,
        "machine": platform.machine(),
        "win32_ver": " ".join(platform.win32_ver()),
        "cpu_count": os.cpu_count() or 0,
        "processor_id": os.environ.get("PROCESSOR_IDENTIFIER", ""),
        "quick": args.quick,
    }
    print("== environment ==")
    for k, v in env.items():
        print(f"  {k}: {v}")

    R = {"env": env}

    # ---- (a) dataclass construction -------------------------------------
    print("\n== (a) dataclass construction ==")
    variants_a = [
        ("frozen_pos (SPEC-100 style)", build_frozen_pos),
        ("frozen_kwargs", build_frozen_kwargs),
        ("plain_pos", build_plain_pos),
        ("slots_pos", build_slots_pos),
        ("tuple", build_tuple),
        ("frozen_pos_gc_off", build_frozen_pos_gc_off),
    ]
    res_a = {}
    for name, fn in variants_a:
        ts, _ = timeit(lambda: fn(n_obj), rep)
        e = entry(n_obj, ts)
        res_a[name] = e
        print(f"  {name:28s} best {e['best_s']:7.3f}s  "
              f"{e['ops_per_s_best'] / 1e6:6.2f} M pkt/s  "
              f"{e['per_op_ns_best']:7.1f} ns/pkt")
    res_a["_mem_bytes_per_obj"] = {
        "frozen": mem_per_obj(build_frozen_pos),
        "plain": mem_per_obj(build_plain_pos),
        "slots": mem_per_obj(build_slots_pos),
        "tuple": mem_per_obj(build_tuple),
    }
    print("  mem/obj(bytes):", res_a["_mem_bytes_per_obj"])
    R["a_dataclass"] = res_a

    # ---- (b) serialization ----------------------------------------------
    print("\n== (b) serialization (header+184B payload -> 188B bytes) ==")
    variants_b = [
        ("struct_pack+concat", ser_struct),
        ("bytes_tuple+concat", ser_bytes_tuple),
        ("bytearray_tmpl_copy", ser_tmpl_copy),
        ("bytearray_reuse_nocopy", ser_reuse_nocopy),
    ]
    res_b = {}
    for name, fn in variants_b:
        ts, out = timeit(lambda: fn(n_ser), rep)
        assert len(out) == PKT_SIZE and out[0] == SYNC
        e = entry(n_ser, ts)
        res_b[name] = e
        print(f"  {name:28s} best {e['best_s']:7.3f}s  "
              f"{e['ops_per_s_best'] / 1e6:6.2f} M pkt/s  "
              f"{e['per_op_ns_best']:7.1f} ns/pkt  "
              f"({e['ops_per_s_best'] * 188 / 1e9:5.2f} GB/s)")
    R["b_serialize"] = res_b

    # ---- (c) file write --------------------------------------------------
    print("\n== (c) sequential file write ==")
    p1 = os.path.join(DATA_DIR, "write188.bin")
    p2 = os.path.join(DATA_DIR, "chunked.bin")
    res_c = {}
    ts, _ = timeit(lambda: write_per_packet(p1, n_wr), rep)
    e = entry(n_wr, ts)
    res_c["per_packet_188B_defaultbuf"] = e
    print(f"  per-packet f.write(188B)    best {e['best_s']:7.3f}s  "
          f"{e['ops_per_s_best'] / 1e6:6.2f} M pkt/s  "
          f"({n_wr * 188 / e['best_s'] / 1e6:7.1f} MB/s)")
    ts, _ = timeit(lambda: write_chunked(p2, n_wr), rep)
    e = entry(n_wr, ts)
    res_c["chunked_96KB_1MBbuf"] = e
    print(f"  chunked 96KB writes (1MBbf) best {e['best_s']:7.3f}s  "
          f"{e['ops_per_s_best'] / 1e6:6.2f} M pkt/s  "
          f"({n_wr * 188 / e['best_s'] / 1e6:7.1f} MB/s)")
    R["c_write"] = res_c

    # ---- (d) scheduler end-to-end ----------------------------------------
    print("\n== (d) packet-slot scheduler (16 Mbps: video 12M + audio 1.5M"
          " + PAT/PMT/PCR + null) ==")
    p3 = os.path.join(DATA_DIR, "sched.bin")
    res_d = {}
    ts, ret = timeit(lambda: sched_only(n_slots), rep)
    e = entry(n_slots, ts)
    res_d["decision_only"] = e
    print(f"  decision-only               best {e['best_s']:7.3f}s  "
          f"{e['ops_per_s_best'] / 1e6:6.2f} M slots/s")
    ts, (nulls, vcount) = timeit(lambda: sched_e2e(p3, n_slots), rep)
    size = os.path.getsize(p3)
    assert size == n_slots * PKT_SIZE, size
    e = entry(n_slots, ts)
    e["null_packets"] = nulls
    e["video_packets"] = vcount
    e["file_bytes"] = size
    res_d["end_to_end_io"] = e
    print(f"  end-to-end (serialize+IO)   best {e['best_s']:7.3f}s  "
          f"{e['ops_per_s_best'] / 1e6:6.2f} M slots/s  "
          f"({n_slots * 188 / e['best_s'] / 1e6:7.1f} MB/s)  "
          f"null={nulls} video={vcount}")
    R["d_scheduler"] = res_d

    # ---- cleanup ----------------------------------------------------------
    for p in (p1, p2, p3):
        try:
            os.remove(p)
        except OSError:
            pass

    out_path = os.path.join(SCRIPT_DIR, args.json)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(R, f, indent=1, ensure_ascii=False)
    print(f"\nresults -> {out_path}")
    print(f"total wall time: n/a (see per-bench times)")


if __name__ == "__main__":
    main()
