"""SPEC-106 §9 — packetizer-owned error-code constants (ticket #32).

Module-owned per the contract §7 归属约定: the ``PACKETIZER_*`` family
maps onto :class:`ts.errors.PacketizationError`, and the constants live in
the subpackage that raises them (same pattern as ``ts.packet`` owning the
``TS_*`` constants). SPEC-106 §9 enumerates the family verbatim; the
firing conditions are documented on the raising sites.

None of these codes trigger an implicit fix: every one of them aborts the
packetization run with a typed exception (contract §2.5 无隐式修复).
"""

from __future__ import annotations

#: PID argument is out of the 13-bit range or is the null PID (0x1FFF) —
#: null packets are owned by the Mux (SPEC-106 §8), never created by a
#: Section/PES packetizer.
PACKETIZER_PID_INVALID = "PACKETIZER_PID_INVALID"

#: A section packetization run received zero section bytes.
PACKETIZER_EMPTY_SECTION = "PACKETIZER_EMPTY_SECTION"

#: A PES packetization run received zero PES bytes.
PACKETIZER_EMPTY_PES = "PACKETIZER_EMPTY_PES"

#: Section bytes cannot be framed honestly: fewer than the 3-byte header,
#: or the declared ``section_length`` field disagrees with the actual byte
#: count (MVP precondition: exactly one complete section per run, §5.2).
PACKETIZER_SECTION_HEADER_INVALID = "PACKETIZER_SECTION_HEADER_INVALID"

#: PES bytes cannot be framed honestly: fewer than 6 bytes (no room for
#: packet_start_code_prefix + stream_id + PES_packet_length), a wrong
#: start-code prefix, or a non-zero declared ``PES_packet_length`` that
#: disagrees with the actual byte count. The unbounded video profile
#: (declared length 0) is accepted as-is.
PACKETIZER_PES_HEADER_INVALID = "PACKETIZER_PES_HEADER_INVALID"

#: The requested adaptation-field content cannot coexist with the payload
#: in a 188-byte frame (§7 capacity arithmetic). Raised for
#: ``random_access`` requests that do not fit a single-packet PES and as
#: the defensive guard of the AF selector.
PACKETIZER_AF_CAPACITY_EXCEEDED = "PACKETIZER_AF_CAPACITY_EXCEEDED"

#: ``first_packet_pcr`` requested but the first packet's AF space cannot
#: hold the PCR field next to the PES bytes (§6: 配置应失败，而不是覆盖
#: PES bytes — the packetizer fails instead of shrinking/overwriting the
#: first packet's PES payload to make AF room).
PACKETIZER_PCR_DOES_NOT_FIT = "PACKETIZER_PCR_DOES_NOT_FIT"

#: Defense-in-depth invariant: a constructed packet failed to serialize to
#: exactly 188 bytes. Unreachable while the §7 arithmetic holds (the
#: SPEC-100 constructor validates frame shapes first); it exists so a
#: packetizer arithmetic bug can never leak a non-canonical packet.
PACKETIZER_PACKET_SIZE_INVARIANT_FAILED = "PACKETIZER_PACKET_SIZE_INVARIANT_FAILED"
