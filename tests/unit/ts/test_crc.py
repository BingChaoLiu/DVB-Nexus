"""MPEG-2 CRC-32 unit contract (SPEC-101, ticket #26).

Primary tests follow the TRACEABILITY.md pre-assignment:

- REQ-TS-101-001 -> ``test_crc32_mpeg2_check_vector``
- REQ-TS-101-002 -> ``test_crc_incremental_equivalence``
- REQ-TS-101-003 -> ``test_crc_append_verify``
- REQ-TS-101-004 -> ``test_crc_input_validation``

Frozen authority for test vectors: SPEC-101 §3/§7 (check vector
``b"123456789"`` -> ``0x0376E6E7``, empty input -> ``0xFFFFFFFF``) and
``docs/test-vectors/CRC32-MPEG2.md``. Pure unit layer: no I/O, no wall
clock; random use is seeded and therefore deterministic.
"""

from __future__ import annotations

import random
import types

import pytest

from ts import crc
from ts.crc import (
    CRC32_MPEG2_INIT,
    CRC32_MPEG2_POLY,
    MPEG2CRC32,
    append_mpeg2_crc32,
    mpeg2_crc32,
    verify_mpeg2_crc32,
)

CHECK_DATA = b"123456789"
CHECK_CRC = 0x0376E6E7


def _stream_crc(data: bytes, *, initial: int) -> int:
    """Helper: feed ``data`` through the incremental API in two halves."""
    hasher = MPEG2CRC32(initial=initial)
    cut = len(data) // 2
    hasher.update(data[:cut])
    hasher.update(data[cut:])
    return hasher.value()


# ---------------------------------------------------------------------------
# REQ-TS-101-001: CRC parameters and check vector.
# ---------------------------------------------------------------------------
class TestReqTs101001CheckVector:
    @pytest.mark.unit
    def test_crc32_mpeg2_check_vector(self):
        """Frozen check vector: b"123456789" -> 0x0376E6E7 (SPEC-101 §3)."""
        assert mpeg2_crc32(CHECK_DATA) == CHECK_CRC

    @pytest.mark.unit
    def test_empty_input_returns_init(self):
        """Empty input returns the initial state 0xFFFFFFFF (SPEC-101 §5)."""
        assert mpeg2_crc32(b"") == CRC32_MPEG2_INIT

    @pytest.mark.unit
    def test_frozen_parameters(self):
        """CRC parameter constants match SPEC-101 §3 (contract §5)."""
        assert CRC32_MPEG2_POLY == 0x04C11DB7
        assert CRC32_MPEG2_INIT == 0xFFFFFFFF

    @pytest.mark.unit
    def test_result_is_32bit_unsigned(self):
        """Output is always a 32-bit unsigned int (SPEC-101 §3)."""
        result = mpeg2_crc32(CHECK_DATA)
        assert isinstance(result, int)
        assert 0 <= result <= 0xFFFFFFFF

    @pytest.mark.unit
    def test_multiple_known_shapes_stay_32bit(self):
        """Longer inputs still produce masked 32-bit values."""
        for data in (bytes(64), bytes(range(256)), b"ABCDEFGHI"):
            assert 0 <= mpeg2_crc32(data) <= 0xFFFFFFFF


# ---------------------------------------------------------------------------
# REQ-TS-101-002: incremental == one-shot.
# ---------------------------------------------------------------------------
class TestReqTs101002Incremental:
    @pytest.mark.unit
    def test_crc_incremental_equivalence(self):
        """Streaming updates equal the one-shot result (SPEC-101 §5).

        Split points cover 0, 1, mid, len-1, len (SPEC-101 §7.6).
        """
        data = bytes(range(256)) * 4
        expected = mpeg2_crc32(data)
        mid = len(data) // 2
        split_points = {0, 1, mid, len(data) - 1, len(data)}
        for cut in sorted(split_points):
            hasher = MPEG2CRC32()
            hasher.update(data[:cut])
            hasher.update(data[cut:])
            assert hasher.value() == expected, f"split at {cut}"

    @pytest.mark.unit
    def test_incremental_byte_by_byte(self):
        """Byte-by-byte updates equal the one-shot result."""
        data = bytes(range(64))
        hasher = MPEG2CRC32()
        for byte in data:
            hasher.update(bytes([byte]))
        assert hasher.value() == mpeg2_crc32(data)

    @pytest.mark.unit
    def test_custom_initial_one_shot_matches_incremental(self):
        """Custom initial value behaves identically for both API styles."""
        initial = 0xDEADBEEF
        data = bytes(range(1, 32))
        assert mpeg2_crc32(data, initial=initial) == _stream_crc(
            data, initial=initial
        )

    @pytest.mark.unit
    def test_incremental_empty_updates_are_noops(self):
        """``update(b"")`` does not change the state (SPEC-101 §5)."""
        hasher = MPEG2CRC32()
        before = hasher.value()
        hasher.update(b"")
        assert hasher.value() == before == CRC32_MPEG2_INIT

    @pytest.mark.unit
    def test_copy_is_independent(self):
        """copy() snapshots the state; the original keeps updating."""
        hasher = MPEG2CRC32()
        hasher.update(b"1234")
        snapshot = hasher.copy()
        hasher.update(b"56789")
        assert snapshot.value() == mpeg2_crc32(b"1234")
        assert hasher.value() == mpeg2_crc32(CHECK_DATA)


# ---------------------------------------------------------------------------
# REQ-TS-101-003: append/verify big-endian remainder semantics.
# ---------------------------------------------------------------------------
class TestReqTs101003AppendVerify:
    @pytest.mark.unit
    def test_crc_append_verify(self):
        """append then verify round-trips for varied payloads (§7.3)."""
        payloads = [
            b"",
            b"\x00",
            b"123456789",
            bytes(range(256)),
            bytes(range(256)) * 3,
        ]
        for payload in payloads:
            combined = append_mpeg2_crc32(payload)
            assert verify_mpeg2_crc32(combined) is True, f"payload {payload[:8]!r}"

    @pytest.mark.unit
    def test_append_endianness_big_endian(self):
        """CRC bytes are big-endian: 0x0376E6E7 -> 03 76 E6 E7 (§7.5)."""
        combined = append_mpeg2_crc32(CHECK_DATA)
        assert combined == CHECK_DATA + b"\x03\x76\xe6\xe7"
        assert combined[-4:] == CHECK_CRC.to_bytes(4, "big")

    @pytest.mark.unit
    def test_append_length(self):
        """append adds exactly 4 bytes; empty payload appends its own CRC."""
        assert len(append_mpeg2_crc32(CHECK_DATA)) == len(CHECK_DATA) + 4
        # Empty payload: CRC is the initial state 0xFFFFFFFF (SPEC-101 §5).
        assert append_mpeg2_crc32(b"") == b"\xff\xff\xff\xff"

    @pytest.mark.unit
    def test_single_bit_flip_fails_verification(self):
        """Flipping any one bit of the combined bytes verifies False (§7.4)."""
        combined = bytearray(append_mpeg2_crc32(bytes(range(64))))
        rng = random.Random(20261114)
        positions = rng.sample(range(len(combined) * 8), 24)
        for flat_index in positions:
            byte_index, bit_index = divmod(flat_index, 8)
            corrupted = bytearray(combined)
            corrupted[byte_index] ^= 1 << bit_index
            assert verify_mpeg2_crc32(bytes(corrupted)) is False, (
                f"flipped bit {flat_index}"
            )

    @pytest.mark.unit
    def test_verify_payload_without_crc_is_false(self):
        """Raw payload without appended CRC must not verify."""
        assert verify_mpeg2_crc32(CHECK_DATA) is False

    @pytest.mark.unit
    def test_verify_shorter_than_crc_width_is_false(self):
        """Fewer than 4 bytes cannot carry a CRC remainder: verify is False."""
        assert verify_mpeg2_crc32(b"") is False
        assert verify_mpeg2_crc32(b"\x00\x01\x02") is False

    @pytest.mark.unit
    def test_verify_synthetic_section_fixture(self):
        """Section-shaped fixture with CRC verifies; one content bit flip fails (§7.8).

        Synthetic section bytes (table_id/length shaped; SPEC-103 not
        required): the CRC property under test belongs to SPEC-101 alone.
        """
        section_body = bytes(
            [
                0x00,  # table_id
                0xB0, 0x0D,  # section_syntax + section_length = 13
                0x00, 0x01,  # arbitrary 16-bit field
                0xC1, 0x00, 0x00,  # version/current_next/section_number
                0x00, 0x00, 0x00, 0x2B,  # arbitrary payload words
            ]
        )
        section = append_mpeg2_crc32(section_body)
        assert len(section) == len(section_body) + 4
        assert verify_mpeg2_crc32(section) is True
        corrupted = bytearray(section)
        corrupted[1] ^= 0x01  # flip one content bit
        assert verify_mpeg2_crc32(bytes(corrupted)) is False

    @pytest.mark.unit
    def test_append_does_not_mutate_input(self):
        """append accepts immutable input and returns a new bytes object."""
        payload = b"immutable"
        combined = append_mpeg2_crc32(payload)
        assert payload == b"immutable"
        assert combined[: len(payload)] == payload


# ---------------------------------------------------------------------------
# REQ-TS-101-004: stdlib independence and input validation.
# ---------------------------------------------------------------------------
class TestReqTs101004InputValidation:
    @pytest.mark.unit
    def test_crc_input_validation(self):
        """Non-bytes-like input raises TypeError; no silent coercion (§6)."""
        for bad_input in ("123456789", 123456789, 12.5, None, object()):
            with pytest.raises(TypeError):
                mpeg2_crc32(bad_input)
            with pytest.raises(TypeError):
                MPEG2CRC32().update(bad_input)
            with pytest.raises(TypeError):
                append_mpeg2_crc32(bad_input)
            with pytest.raises(TypeError):
                verify_mpeg2_crc32(bad_input)

    @pytest.mark.unit
    def test_initial_range_validation(self):
        """initial outside 0..0xFFFFFFFF raises ValueError (SPEC-101 §6)."""
        for bad_initial in (-1, 0x100000000, 0xFFFFFFFF + 1, -(2**32)):
            with pytest.raises(ValueError):
                mpeg2_crc32(b"data", initial=bad_initial)
            with pytest.raises(ValueError):
                MPEG2CRC32(initial=bad_initial)

    @pytest.mark.unit
    def test_initial_type_validation(self):
        """Non-int initial raises TypeError; bool is rejected explicitly."""
        for bad_initial in ("0xFFFFFFFF", 1.0, None, True, False):
            with pytest.raises(TypeError):
                mpeg2_crc32(b"data", initial=bad_initial)
            with pytest.raises(TypeError):
                MPEG2CRC32(initial=bad_initial)

    @pytest.mark.unit
    def test_initial_boundary_values_accepted(self):
        """initial 0 and 0xFFFFFFFF are legal bounds."""
        assert mpeg2_crc32(b"", initial=0) == 0
        assert mpeg2_crc32(b"", initial=0xFFFFFFFF) == 0xFFFFFFFF
        assert MPEG2CRC32(initial=0).value() == 0

    @pytest.mark.unit
    def test_bytes_like_inputs_accepted(self):
        """bytes, bytearray and memoryview are supported (SPEC-101 §6)."""
        payload = bytes(range(32))
        expected = mpeg2_crc32(payload)
        assert mpeg2_crc32(bytearray(payload)) == expected
        assert mpeg2_crc32(memoryview(payload)) == expected
        hasher = MPEG2CRC32()
        hasher.update(bytearray(payload))
        hasher.update(memoryview(payload))
        assert hasher.value() == mpeg2_crc32(payload + payload)
        assert verify_mpeg2_crc32(memoryview(append_mpeg2_crc32(payload))) is True
        assert append_mpeg2_crc32(bytearray(payload)) == append_mpeg2_crc32(payload)

    @pytest.mark.unit
    def test_module_imports_no_third_party_or_project_modules(self):
        """No third-party / project module leaks into ts.crc globals (§8).

        zlib.crc32 is explicitly forbidden as the implementation (SPEC-101
        §5); pydantic/fastapi/adapters must never appear either (contract
        §2.2/§11, importlinter ``ts`` purity).
        """
        forbidden = {
            "zlib",
            "pydantic",
            "fastapi",
            "httpx",
            "requests",
            "adapters",
            "domain",
            "api",
            "application",
            "simulation",
        }
        for name, value in vars(crc).items():
            if isinstance(value, types.ModuleType):
                top_level = value.__name__.split(".")[0]
                assert top_level not in forbidden, (
                    f"ts.crc global {name!r} binds module {value.__name__!r}"
                )

    @pytest.mark.unit
    def test_bitwise_and_table_driven_agree(self):
        """Cross implementation: bitwise vs table-driven on seeded vectors (§7.7)."""
        rng = random.Random(0x04C11DB7)
        vectors = [b"", b"\x00", CHECK_DATA]
        for _ in range(64):
            length = rng.randrange(0, 300)
            vectors.append(bytes(rng.randrange(256) for _ in range(length)))
        for vector in vectors:
            assert crc._mpeg2_crc32_table(vector) == mpeg2_crc32(vector)

    @pytest.mark.unit
    def test_table_driven_check_vector(self):
        """The table-driven path agrees with the frozen check vector too."""
        assert crc._mpeg2_crc32_table(CHECK_DATA) == CHECK_CRC
        assert crc._mpeg2_crc32_table(b"") == CRC32_MPEG2_INIT
