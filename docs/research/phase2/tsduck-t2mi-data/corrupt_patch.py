# -*- coding: utf-8 -*-
"""Corrupt bytes inside T2-MI packet 0 of an outer stream, then repack with
recomputed T2-MI CRC-32 (isolating non-CRC32-layer integrity checks)."""
import os
import struct
import sys
from pathlib import Path

DATA = Path(os.environ["DATA_DIR"])
T2MI_PID = 0x0015
SYNC = 0x47


def crc32_mpeg(data):
    crc = 0xFFFFFFFF
    for b in data:
        crc ^= b << 24
        for _ in range(8):
            crc = ((crc << 1) ^ 0x04C11DB7) & 0xFFFFFFFF if crc & 0x80000000 else (crc << 1) & 0xFFFFFFFF
    return crc


def extract_t2mi_stream(ts):
    pkts = [ts[i:i + 188] for i in range(0, len(ts), 188)]
    out = bytearray()
    for p in pkts:
        pid = ((p[1] & 0x1F) << 8) | p[2]
        if pid != T2MI_PID:
            continue
        body = p[4:188]
        if p[1] & 0x40:  # PUSI
            body = body[1 + body[0]:]
        out += body
    return bytes(out), len(out)


def repack(pat_bin, pmt_bin, t2mi_bytes, trailing_nulls=50):
    out = []
    cc = {T2MI_PID: 0, 0: 0, 0x1000: 0}

    def add_pkt(pid, payload, pusi):
        h = bytes([SYNC, (0x40 if pusi else 0) | ((pid >> 8) & 0x1F), pid & 0xFF, 0x10 | (cc[pid] & 0x0F)])
        out.append(h + payload[:184].ljust(184, b"\xff"))
        cc[pid] = (cc[pid] + 1) & 0x0F

    def add_section(pid, sec):
        add_pkt(pid, b"\x00" + sec, True)

    add_section(0, pat_bin)
    add_section(0x1000, pmt_bin)
    pos = 0
    first = True
    while pos < len(t2mi_bytes):
        if first:
            add_pkt(T2MI_PID, b"\x00" + t2mi_bytes[pos:pos + 183], True)
            pos += 183
            first = False
        else:
            add_pkt(T2MI_PID, t2mi_bytes[pos:pos + 184], False)
            pos += 184
    ncc = 0
    for _ in range(trailing_nulls):
        out.append(bytes([SYNC, 0x1F, 0xFF, 0x10 | ncc]) + bytes(184))
        ncc = (ncc + 1) & 0x0F
    return b"".join(out)


def main():
    ts = (DATA / "outer_hem.ts").read_bytes()
    t2mi, total = extract_t2mi_stream(ts)
    pkt0_size = struct.unpack(">H", t2mi[4:6])[0]
    pkt0_size = 6 + (pkt0_size + 7) // 8 + 4
    print("t2mi stream: %d bytes, pkt0 size %d" % (total, pkt0_size))

    variants = {
        # name: (byte offset in pkt0 to flip, description)
        "crc8bb": (6 + 3 + 9, "BBHEADER CRC-8 byte"),
        "rot": (6 + 3 + 10 + 100, "BBFRAME datafield byte (post-CRC bit rot)"),
        "tspayload": (6 + 3 + 10 + 20, "byte inside first encapsulated TS packet"),
    }
    for name, (off, desc) in variants.items():
        buf = bytearray(t2mi)
        buf[off] ^= 0x01
        # recompute T2-MI pkt0 CRC-32
        buf[pkt0_size - 4:pkt0_size] = struct.pack(">I", crc32_mpeg(buf[0:pkt0_size - 4]))
        new = repack((DATA / "outer_pat.bin").read_bytes(), (DATA / "outer_pmt.bin").read_bytes(), bytes(buf))
        (DATA / ("corrupt_%s.ts" % name)).write_bytes(new)
        print("corrupt_%s.ts written (%s)" % (name, desc))


if __name__ == "__main__":
    main()
