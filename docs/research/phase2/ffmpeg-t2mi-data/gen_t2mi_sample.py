import os, struct
from pathlib import Path

OUT = Path(os.environ["OUT_DIR_W"])

def crc32_mpeg(data: bytes) -> int:
    crc = 0xFFFFFFFF
    for b in data:
        crc ^= b << 24
        for _ in range(8):
            crc = ((crc << 1) ^ 0x04C11DB7) & 0xFFFFFFFF if crc & 0x80000000 else (crc << 1) & 0xFFFFFFFF
    return crc

def crc8_bbheader(bbh9: bytes) -> int:
    # TSDuck T2MIDemux::BBHeaderCRC8: poly 0xD5, over first 9 bytes of BBHEADER
    crc = 0
    for b in bbh9:
        crc ^= b
        for _ in range(8):
            crc = (crc << 1) ^ 0xD5 if crc & 0x80 else crc << 1
            crc &= 0xFF
    return crc

def ts_packet(pid: int, cc: int, pusi: bool, payload: bytes) -> bytes:
    assert len(payload) == 184
    b1 = (0x40 if pusi else 0x00) | ((pid >> 8) & 0x1F)  # PUSI is bit 6 of byte 1
    b3 = 0x10 | (cc & 0x0F)                              # TSC=00, AFC=01 (payload only)
    return bytes([0x47, b1, pid & 0xFF, b3]) + payload

def section_packet(pid: int, cc: int, section: bytes) -> bytes:
    full = section + crc32_mpeg(section).to_bytes(4, "big")
    pl = bytes([0x00]) + full + b"\xff" * (184 - 1 - len(full))  # pointer_field + section + stuffing
    return ts_packet(pid, cc, True, pl)

# --- inner TS: PAT, PMT (with T2MI_descriptor on ES PID 0x64), null ---
pat_section = bytes([0x00, 0xB0, 0x0D, 0x00, 0x01, 0xC1, 0x00, 0x00, 0x00, 0x01, 0xE1, 0x00])
# PMT: prog 1, PCR PID 0x100, one ES: type 0x06 on PID 0x64 with T2MI_descriptor (ext 0x7F/0x11, 3-byte payload)
t2mi_desc = bytes([0x7F, 0x11, 0x03, 0x00, 0x00, 0x00])
pmt_inner_body = bytes([0x02, 0xB0, 0x12, 0x00, 0x01, 0xC1, 0x00, 0x00, 0xE1, 0x00, 0xF0, 0x00,
                        0x1B, 0xE1, 0x01, 0xF0, 0x00])
# PMT body compiled by TSDuck tstabcomp (T2MI_descriptor ext descriptor 0x7F/0x11,
# EN 300 468 wire order: [tag 0x7F][length=4][ext=0x11][payload 00 00 00]); CRC appended below.
pmt_outer_body = bytes.fromhex("02b0180001c10000e100f00006e064f0067f0411000000")
null_pkt = ts_packet(0x1FFF, 0, False, b"\xff" * 184)

inner_ts = [
    section_packet(0x0000, 0, pat_section),
    section_packet(0x0100, 0, pmt_inner_body),
    null_pkt,
]

# Outer TS signalization: PAT + PMT carrying T2MI_descriptor (EN 300 468 ext
# descriptor tag 0x7F / ext id 0x11) on the component that carries T2-MI (PID 0x64)
outer_sigs = [
    section_packet(0x0000, 0, pat_section),
    section_packet(0x0100, 0, pmt_outer_body),
]

# --- T2-MI packet (type 0x00 Baseband Frame), TS 102 773 5.1/5.2, EN 302 755 5.1.7 ---
def t2mi_bbframe(counter: int, plp: int, inner_pkts: list[bytes]) -> bytes:
    # HEM (High Efficiency Mode): UP = 187 bytes (TS without sync byte), no CRC-8.
    # Works identically on TSDuck 3.45 (187-byte UP reader) and master (HEM branch).
    data = bytearray()
    for pkt in inner_pkts:
        data += pkt[1:]  # TS without sync byte
    dfl_bits = len(inner_pkts) * 187 * 8
    upl_bits = 187 * 8
    bbh = bytearray(9)
    bbh[0] = 0xC0          # MATYPE-1: TS/GS = 0b11 (TS mode), no NPD
    bbh[1] = 0x00          # MATYPE-2 (ISI, unused here)
    bbh[2:4] = upl_bits.to_bytes(2, "big")    # UPL (bits)
    bbh[4:6] = dfl_bits.to_bytes(2, "big")    # DFL (bits)
    bbh[6] = 0x47          # SYNC
    bbh[7:9] = b"\x00\x00" # SYNCD = 0 (UP starts at data field start)
    bbh9 = bytes(bbh)
    mode_hem = 0x01
    rp_mode = mode_hem ^ crc8_bbheader(bbh9)  # so that data[9]^crc8 == 1 (HEM)
    bbheader = bbh9 + bytes([rp_mode])
    payload = bytes([0x00, plp, 0x00]) + bbheader + bytes(data)  # frame_idx, plp, x + BBHEADER + data field
    hdr = bytes([0x00]) + counter.to_bytes(3, "big") + (len(payload) * 8).to_bytes(2, "big")
    body = hdr + payload
    return body + crc32_mpeg(body).to_bytes(4, "big")

T2MI_PID = 0x0064
import sys
n_ups = int(os.environ.get("N_UPS", "3"))
n_t2mi = int(os.environ.get("N_T2MI", "2"))
t2mi_packets = [t2mi_bbframe(c, 0, inner_ts[:n_ups]) for c in range(n_t2mi)]
if os.environ.get("FLUSH_DUMMY"):
    # Trailing dummy T2-MI Baseband Frame whose single UP is a null TS packet
    # (PID 0x1FFF): forces the demux to flush the previous BBFrame's pending UPs.
    # The dummy's own UP is a valid null TS packet - strip it from the output.
    null_pkt = inner_ts[2]
    data_field = null_pkt[1:]
    bbh = bytearray(9)
    bbh[0] = 0xC0
    bbh[2:4] = (187 * 8).to_bytes(2, "big")
    bbh[4:6] = (len(data_field) * 8).to_bytes(2, "big")
    bbh[6] = 0x47
    bbh[7:9] = bytes([0, 0])
    rp = crc8_bbheader(bytes(bbh)) ^ 0x01
    payload = bytes([0x00, 0x00, 0x00]) + bytes(bbh) + bytes([rp]) + data_field
    hdr = bytes([0x00]) + (n_t2mi).to_bytes(3, "big") + (len(payload) * 8).to_bytes(2, "big")
    body = hdr + payload
    t2mi_packets.append(body + crc32_mpeg(body).to_bytes(4, "big"))


# --- outer TS: contiguous T2-MI byte stream on PID 0x64, section-like pointer_field packetization ---
buf = b"".join(t2mi_packets)
outer = bytearray(b"".join(outer_sigs))
first = True
cc = 0
while buf:
    if first:
        pl = bytes([0x00]) + buf[:183]
        buf = buf[183:]
        outer += ts_packet(T2MI_PID, cc, True, pl)
        first = False
    else:
        chunk = buf[:184]
        buf = buf[184:]
        pad = b"\xff" * (184 - len(chunk))
        outer += ts_packet(T2MI_PID, cc, False, chunk + pad)
    cc = (cc + 1) & 0x0F

(OUT / "t2mi_in_ts.ts").write_bytes(bytes(outer))
(OUT / "raw_t2mi.bin").write_bytes(b"".join(t2mi_packets))
(OUT / "expected_inner.ts").write_bytes(b"".join(inner_ts + inner_ts))
print("outer TS:", len(outer), "bytes,", len(outer) // 188, "packets")
print("raw T2MI:", len(b"".join(t2mi_packets)), "bytes; one T2-MI packet:", len(t2mi_packets[0]), "bytes")
