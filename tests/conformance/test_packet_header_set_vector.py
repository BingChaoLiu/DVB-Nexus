"""First-batch golden vector ``packet-header-set`` — L1 bit-level assertions.

Conformance layer (SPEC-505 §3 / SPEC-506 §7 #1). The vector is a set of 10
hand-derived 188-byte header samples (TEI / PUSI / priority / CC / AFC /
scrambling edges), bytes produced by the SPEC-100 §3 derivation script
``tools/make_golden_packet_header_set.py`` and frozen by sha256
(SPEC-506 §6).  Verification path: L1 spec-table derivation + review — the
expected field values below are derived independently from the SPEC-100 §3
wire table, so parser agreement is the cross-check (no TSDuck needed for
L1, #14 Q1).

The registered trio is consumed read-only through the ``golden_loader``
fixture; expectations.json is interpreted here (event_type
``ts.packet_batch_observed`` + locator.packet_index + header detail).
"""

from __future__ import annotations

import pytest

from ts.packet import TSPacket, TS_SYNC_BYTE

pytestmark = pytest.mark.conformance

VECTOR_ID = "packet-header-set"

#: The 10 samples' expected header fields, hand-derived from the SPEC-100 §3
#: wire table (independent derivation — the constructor script must agree).
EXPECTED_HEADERS: tuple[dict, ...] = (
    # s0: minimal section-start packet (PAT-shaped): PID 0, PUSI, payload-only.
    dict(tei=0, pusi=1, priority=0, pid=0x0000, scrambling=0, afc=1, cc=0),
    # s1: TEI set (transport_error_indicator edge).
    dict(tei=1, pusi=0, priority=0, pid=0x0000, scrambling=0, afc=1, cc=1),
    # s2: transport_priority set + CC upper edge (15).
    dict(tei=0, pusi=0, priority=1, pid=0x0001, scrambling=0, afc=1, cc=15),
    # s3: null-PID packet (0x1FFF edge, canonical null-packet shape).
    dict(tei=0, pusi=0, priority=0, pid=0x1FFF, scrambling=0, afc=1, cc=0),
    # s4: largest non-null PID (0x1FFE) + PUSI.
    dict(tei=0, pusi=1, priority=0, pid=0x1FFE, scrambling=0, afc=1, cc=8),
    # s5: reserved scrambling control 01 (kept verbatim + flagged).
    dict(tei=0, pusi=0, priority=0, pid=0x0010, scrambling=1, afc=1, cc=3),
    # s6: even scrambling (10) + AFC=11 carrying a PCR adaptation field.
    dict(tei=0, pusi=0, priority=0, pid=0x0100, scrambling=2, afc=3, cc=4),
    # s7: odd scrambling (11) + adaptation-only reusing the last CC (§5.4):
    #     same PID as s6, CC 4 again (no payload packet in between).
    dict(tei=0, pusi=0, priority=0, pid=0x0100, scrambling=3, afc=2, cc=4),
    # s8: adaptation-only with discontinuity flag and maximal AF length (183).
    dict(tei=0, pusi=0, priority=0, pid=0x0011, scrambling=0, afc=2, cc=9),
    # s9: AFC=11 with zero-length adaptation field (minimum edge).
    dict(tei=0, pusi=1, priority=0, pid=0x0012, scrambling=0, afc=3, cc=10),
)

#: Hand-set PCR carried by s6's adaptation field (cross-linked to
#: PCR-PTS.md bit-packing: base 33-bit + reserved 111111 + 9-bit ext).
S6_PCR_BASE = 12345
S6_PCR_EXT = 0


def _load_vector(golden_loader):
    return golden_loader.load(VECTOR_ID)


def test_packet_header_set_registered_with_frozen_bytes(golden_loader):
    vector = _load_vector(golden_loader)
    assert vector.kind == "bit_level"
    assert vector.packet_count == len(EXPECTED_HEADERS)
    assert len(vector.ts_bytes) == 188 * len(EXPECTED_HEADERS)
    # Sync byte column of the §3 table: every sample starts 0x47.
    for index in range(len(EXPECTED_HEADERS)):
        assert vector.ts_bytes[index * 188] == TS_SYNC_BYTE


def test_expectations_declare_every_sample(golden_loader):
    vector = _load_vector(golden_loader)
    entries = list(vector.expectations)
    assert len(entries) == len(EXPECTED_HEADERS)
    for index, entry in enumerate(entries):
        assert entry["event_type"] == "ts.packet_batch_observed"
        assert entry["locator"]["packet_index"] == index
        detail = entry["detail"]
        expected = EXPECTED_HEADERS[index]
        for field, value in expected.items():
            assert detail[field] == value, f"sample {index}: field {field}"


def test_every_sample_strict_parses_to_expected_header(golden_loader):
    vector = _load_vector(golden_loader)
    for index in range(len(EXPECTED_HEADERS)):
        chunk = vector.ts_bytes[index * 188 : (index + 1) * 188]
        packet = TSPacket.from_bytes(chunk)  # strict: samples are valid
        expected = EXPECTED_HEADERS[index]
        assert packet.transport_error_indicator == bool(expected["tei"])
        assert packet.payload_unit_start_indicator == bool(expected["pusi"])
        assert packet.transport_priority == bool(expected["priority"])
        assert packet.pid == expected["pid"]
        assert packet.transport_scrambling_control == expected["scrambling"]
        assert packet.adaptation_field_control.value == expected["afc"]
        assert packet.continuity_counter == expected["cc"]


def test_reserved_scrambling_sample_kept_verbatim_and_flagged(golden_loader):
    # SPEC-100 §5.3: tsc=01 is preserved (round-trip) and reported.
    vector = _load_vector(golden_loader)
    chunk = vector.ts_bytes[5 * 188 : 6 * 188]
    packet = TSPacket.from_bytes(chunk)
    assert packet.transport_scrambling_control == 1
    codes = [issue.code for issue in packet.validate()]
    assert "TS_SCRAMBLING_RESERVED" in codes
    # No silent rewrite: the wire byte keeps the reserved value.
    assert (chunk[3] >> 6) & 0x03 == 1


def test_pcr_sample_decodes_to_hand_set_value(golden_loader):
    # s6 adaptation field carries the hand-set PCR (L1: PCR-PTS.md packing).
    vector = _load_vector(golden_loader)
    packet = TSPacket.from_bytes(vector.ts_bytes[6 * 188 : 7 * 188])
    assert packet.adaptation_field is not None
    assert packet.adaptation_field.pcr is not None
    assert packet.adaptation_field.pcr.base == S6_PCR_BASE
    assert packet.adaptation_field.pcr.extension == S6_PCR_EXT


def test_cc_reuse_pair_demonstrates_adaptation_only_rule(golden_loader):
    # §5.4: adaptation-only packet reuses the last CC — s6/s7 same PID,
    # consecutive, s7 adaptation-only ⇒ same CC value on the wire.
    vector = _load_vector(golden_loader)
    cc6 = (vector.ts_bytes[6 * 188 + 3]) & 0x0F
    cc7 = (vector.ts_bytes[7 * 188 + 3]) & 0x0F
    assert cc6 == cc7 == 4


def test_discontinuity_flag_sample(golden_loader):
    vector = _load_vector(golden_loader)
    packet = TSPacket.from_bytes(vector.ts_bytes[8 * 188 : 9 * 188])
    assert packet.adaptation_field is not None
    assert packet.adaptation_field.discontinuity_indicator is True


def test_zero_length_adaptation_field_sample(golden_loader):
    vector = _load_vector(golden_loader)
    packet = TSPacket.from_bytes(vector.ts_bytes[9 * 188 : 10 * 188])
    assert packet.adaptation_field is not None
    assert packet.adaptation_field_control.value == 3
    # AF length byte on the wire is 0.
    assert vector.ts_bytes[9 * 188 + 4] == 0


def test_registration_verification_is_l1_bit_level_review(golden_loader):
    vector = _load_vector(golden_loader)
    assert vector.verification is not None
    assert vector.verification.path == "bit-level-review"
    assert vector.verification.evidence_ref  # derivation doc anchor present


def test_constructor_script_reproduces_registered_bytes(golden_loader, tmp_path):
    """SPEC-506 §6 determinism: same script + version ⇒ same bytes."""
    import subprocess
    import sys
    from tests._support.paths import REPO_ROOT

    vector = _load_vector(golden_loader)
    script = REPO_ROOT / "tools" / "make_golden_packet_header_set.py"
    result = subprocess.run(
        [sys.executable, "-I", str(script), "--output-dir", str(tmp_path)],
        capture_output=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    rebuilt = (tmp_path / VECTOR_ID / f"{VECTOR_ID}.ts").read_bytes()
    assert rebuilt == vector.ts_bytes
