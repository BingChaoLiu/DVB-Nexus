# -*- coding: utf-8 -*-
"""Generate a minimal T2-MI encapsulated transport stream for TSDuck t2mi plugin testing.

Layout references:
- T2-MI packet: ETSI TS 102 773 V1.4.1 section 5.1 (6-byte header + payload + CRC-32)
  cross-checked against TSDuck source tsT2MI.h / tsT2MIPacket.cpp (HEADER_SIZE=6,
  payload length in BITS at bytes 4-5, CRC-32 trailer, type 0x00 = BASEBAND_FRAME).
- Baseband frame payload prefix: TSDuck tsT2MIPacket.cpp: payload[0]=frame_idx,
  payload[1]=PLP_id, payload[2] bit 0x80 = interleaving_frame_start, BBFRAME from
  payload offset 3 (byte-aligned assumption of TSDuck).
- BBHEADER (10 bytes): EN 302 755 section 5.1.7, cross-checked against TSDuck
  tsT2MIDemux.cpp: MATYPE[0:2] (TS_GS bits 7-6 of byte0, NPD bit 2 of byte0),
  UPL[2:4] bits, DFL[4:6] bits, SYNC[6], SYNC_D[7:9] bits, CRC-8 at [9]
  (poly 0xD5 over first 9 bytes; MODE = byte9 XOR CRC8 must be 0=NM or 1=HEM).
- Normal Mode user packet: CRC-8 (poly 0xD5) of the 187 bytes + 187 bytes
  (TS packet with sync byte removed), UPL = 188*8 = 1504.
"""
import os
import struct
import subprocess
import sys
from pathlib import Path

DATA = Path(os.environ["DATA_DIR"])
T2MI_PID = 0x0015
PMT_PID = 0x1000
SYNC = 0x47
UPL_BITS = 188 * 8
UPS_PER_BBFRAME = 20


def crc32_mpeg(data):
    crc = 0xFFFFFFFF
    for b in data:
        crc ^= b << 24
        for _ in range(8):
            crc = ((crc << 1) ^ 0x04C11DB7) & 0xFFFFFFFF if crc & 0x80000000 else (crc << 1) & 0xFFFFFFFF
    return crc


def crc8_dvb(data):
    crc = 0
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = ((crc << 1) ^ 0xD5) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc


def run(cmd, cwd):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if r.returncode != 0:
        print("CMD FAILED:", " ".join(cmd))
        print("stdout:", r.stdout)
        print("stderr:", r.stderr)
        sys.exit(1)
    return r


def build_t2mi_packet(count, frame_idx, plp, bbframe):
    payload = bytes([frame_idx, plp, 0x80]) + bbframe
    header = bytes([0x00, count, 0x00, 0x00]) + struct.pack(">H", len(payload) * 8)
    body = header + payload
    return body + struct.pack(">I", crc32_mpeg(body))


def build_t2mi_packets(ts_bytes, mode="nm"):
    """Chunk inner TS packets into BBFRAMEs; return list of T2-MI packets.

    mode="nm": spec Normal Mode (EN 302 755 5.1.8): UP = CRC-8 + 187 bytes,
               UPL = 188*8. Supported by TSDuck master only (post-3.45).
    mode="hem": UP = 187 bytes (sync stripped, no CRC-8), UPL = 0,
                MODE bit = BBHEADER CRC-8 XOR 1. Works on 3.45 and master.
    """
    up = []
    for i in range(0, len(ts_bytes), 188):
        pkt = ts_bytes[i:i + 188]
        assert len(pkt) == 188 and pkt[0] == SYNC
        if mode == "nm":
            up.append(bytes([crc8_dvb(pkt[1:])]) + pkt[1:])
        else:
            up.append(pkt[1:])
    upl = UPL_BITS if mode == "nm" else 0
    packets = []
    count = 0
    for start in range(0, len(up), UPS_PER_BBFRAME):
        datafield = b"".join(up[start:start + UPS_PER_BBFRAME])
        bbheader = bytes([0xD0, 0x00]) + struct.pack(">H", upl)
        bbheader += struct.pack(">H", len(datafield) * 8)  # DFL bits
        bbheader += bytes([SYNC]) + struct.pack(">H", 0)   # SYNC, SYNC_D=0 bits
        crc = crc8_dvb(bbheader)
        bbheader += bytes([crc if mode == "nm" else crc ^ 0x01])
        packets.append(build_t2mi_packet(count % 256, (start // UPS_PER_BBFRAME) % 256, 0, bbheader + datafield))
        count += 1
    return packets


def frame_outer(pat_bin, pmt_bin, t2mi_packets, trailing_nulls=50):
    """Packetize: PAT, PMT (1 packet each), T2-MI packets (section-like framing), nulls."""
    out = []
    cc = {T2MI_PID: 0, 0: 0, PMT_PID: 0}

    def add_pkt(pid, payload, pusi):
        body = payload[:184].ljust(184, b"\xff")
        h = bytes([SYNC,
                   (0x40 if pusi else 0) | ((pid >> 8) & 0x1F),
                   pid & 0xFF,
                   0x10 | (cc.get(pid, 0) & 0x0F)])
        out.append(h + body)
        cc[pid] = (cc.get(pid, 0) + 1) & 0x0F

    def add_section(pid, sec):
        add_pkt(pid, b"\x00" + sec, True)

    add_section(0, pat_bin)
    add_section(PMT_PID, pmt_bin)
    # T2-MI packets are packed back-to-back (section-like framing):
    # stuffing only at the end of the last payload, never between packets.
    t2mi_bytes = b"".join(t2mi_packets)
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
    null_cc = 0
    for _ in range(trailing_nulls):
        h = bytes([SYNC, 0x1F, 0xFF, 0x10 | null_cc])
        out.append(h + bytes(184))
        null_cc = (null_cc + 1) & 0x0F
    return b"".join(out)


def main():
    run(["tsp", "-I", "null", "500",
         "-P", "inject", "-p", "0", "--inter-packet", "100", "inner_pat.bin",
         "-P", "inject", "-p", "0x1000", "--inter-packet", "100", "inner_pmt.bin",
         "-O", "file", "inner.ts"], str(DATA))
    inner = (DATA / "inner.ts").read_bytes()
    assert len(inner) % 188 == 0 and len(inner) // 188 == 500, len(inner)

    for mode in ("nm", "hem"):
        t2mi_packets = build_t2mi_packets(inner, mode)
        outer = frame_outer((DATA / "outer_pat.bin").read_bytes(),
                            (DATA / "outer_pmt.bin").read_bytes(), t2mi_packets)
        name = "outer.ts" if mode == "nm" else "outer_hem.ts"
        (DATA / name).write_bytes(outer)
        print("%s: T2-MI packets %d, size %d B each, outer %d packets"
              % (name, len(t2mi_packets), len(t2mi_packets[0]), len(outer) // 188))
    print("inner.ts: %d bytes, %d packets" % (len(inner), len(inner) // 188))


if __name__ == "__main__":
    main()
