"""faults.filters.base — shared PSI section-header helper.

The PMT_INVALID_CRC and PMT_PID_MISMATCH transforms both decoded the
pointer_field offset and the 3-byte section header inline (duplicated PSI
framing, M3 review-fix #5); ``psi_section_header`` is the one shared
decoder. Byte-level transform behavior is unchanged — the oracle golden
pair (tests/integration/faults/test_fault_oracle_golden.py) stays the
authority.
"""

from faults.filters.base import psi_section_header


def _pusi_payload(pointer: int, table_id: int, section_length: int, body: int = 0):
    """A programmatic PUSI payload: pointer stuffing + 3-byte PSI header."""
    header = bytes([table_id, 0xF0 | (section_length >> 8), section_length & 0xFF])
    return bytes([pointer]) + b"\xff" * pointer + header + bytes([body])


def test_pointer_zero_section_starts_at_byte_one():
    payload = _pusi_payload(pointer=0, table_id=0x02, section_length=0x0D)
    assert psi_section_header(payload) == (1, 0x0D)


def test_pointer_field_skips_stuffing_bytes():
    payload = _pusi_payload(pointer=5, table_id=0x00, section_length=17)
    assert psi_section_header(payload) == (6, 17)


def test_length_high_nibble_is_reserved_bits_and_ignored():
    """Only the low 4 bits of the second header byte feed the 12-bit length."""
    payload = _pusi_payload(pointer=0, table_id=0x02, section_length=0x00F)
    # Same slot with reserved-nibble garbage in the length byte's high half.
    tampered = bytes([payload[0], payload[1], 0xA0, payload[3], payload[4]])
    assert psi_section_header(tampered) == (1, 0x00F)


def test_truncated_header_returns_none():
    payload = _pusi_payload(pointer=0, table_id=0x02, section_length=9)
    assert psi_section_header(payload[:3]) is None


def test_pointer_pushing_header_past_slot_returns_none():
    payload = _pusi_payload(pointer=8, table_id=0x02, section_length=9)
    assert psi_section_header(payload[:6]) is None
