"""SPEC-107 §5.1 — Null Packet construction (ticket #33).

The Null Packet is the CBR filler: PID 0x1FFF, AFC=payload-only, payload
filled with 0xFF, continuity counter fixed at 0 (MVP: no pseudo continuity
semantics on the null PID).  It is a plain payload-only frame — no
adaptation field is built or modified here, so the contract §9 rule (the
mux never touches AFs) is satisfied by construction.  Null Packets exist
only to complete a packet slot; they never carry scheduling payload.
"""

from __future__ import annotations

from ts.packet import PID_NULL, TS_HEADER_SIZE, TS_PACKET_SIZE, TSPacket

#: Fixed CC for null packets (SPEC-107 §5.1: "MVP 固定为 0").
NULL_PACKET_CC = 0

#: 184 bytes of 0xFF — the full payload region of a payload-only packet.
NULL_PACKET_PAYLOAD = b"\xff" * (TS_PACKET_SIZE - TS_HEADER_SIZE)


def build_null_packet() -> TSPacket:
    """Build the one canonical Null Packet (PID 0x1FFF, CC 0, 0xFF body)."""
    return TSPacket(
        pid=PID_NULL,
        continuity_counter=NULL_PACKET_CC,
        payload=NULL_PACKET_PAYLOAD,
    )
