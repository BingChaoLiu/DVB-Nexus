"""Unit-layer tests for the 禁手拼字节 detector (SPEC-505 §6, #14).

`find_hand_assembled_bytes` is a pure source-text analyzer: no I/O, no wall
clock. Tree-level application lives in the integration layer
(test_test_data_tree_rules.py).
"""

from __future__ import annotations

from tests._support.data_rules import (
    MAX_BYTES_LITERAL,
    MIN_HEX_CHARS,
    MIN_INT_LIST,
    find_hand_assembled_bytes,
)

SHORT_SYNC = b"\x47"


def violations_of(source: str):
    return find_hand_assembled_bytes(source, filename="<test>")


class TestBytesLiterals:
    def test_single_byte_literal_passes(self):
        assert violations_of("x = b'\\x47'\n") == []

    def test_literal_at_threshold_passes(self):
        # Rule: flagged strictly above MAX_BYTES_LITERAL bytes.
        payload = "A" * MAX_BYTES_LITERAL
        assert violations_of(f"x = b'{payload}'\n") == []

    def test_literal_above_threshold_flagged(self):
        payload = "A" * (MAX_BYTES_LITERAL + 1)
        found = violations_of(f"x = b'{payload}'\n")
        assert len(found) == 1
        assert found[0].rule == "bytes_literal"
        assert found[0].line == 1

    def test_escape_packed_literal_measured_decoded(self):
        # 17 escaped bytes: b"\x47" * 17 written as escapes.
        escaped = "\\x47" * (MAX_BYTES_LITERAL + 1)
        found = violations_of(f"x = b'{escaped}'\n")
        assert len(found) == 1
        assert found[0].rule == "bytes_literal"


class TestByteListCalls:
    def test_multiplied_bytes_literal_flagged(self):
        found = violations_of("x = b'\\x47' * 188\n")
        assert len(found) == 1
        assert found[0].rule == "bytes_literal"

    def test_multiplied_short_literal_below_threshold_passes(self):
        assert violations_of("x = b'\\x47' * 16\n") == []

    def test_int_list_below_threshold_passes(self):
        ints = ", ".join("1" * 1 for _ in range(MIN_INT_LIST - 1))
        assert violations_of(f"x = bytes([{ints}])\n") == []

    def test_bytes_int_list_at_threshold_flagged(self):
        ints = ", ".join("1" for _ in range(MIN_INT_LIST))
        found = violations_of(f"x = bytes([{ints}])\n")
        assert len(found) == 1
        assert found[0].rule == "bytes_int_list"

    def test_bytearray_int_list_flagged(self):
        ints = ", ".join("1" for _ in range(MIN_INT_LIST + 5))
        found = violations_of(f"x = bytearray([{ints}])\n")
        assert len(found) == 1
        assert found[0].rule == "bytes_int_list"


class TestHexConstruction:
    def test_short_fromhex_passes(self):
        hexchars = "47" * (MIN_HEX_CHARS // 2 - 1)
        assert violations_of(f"x = bytes.fromhex('{hexchars}')\n") == []

    def test_long_fromhex_flagged(self):
        hexchars = "47" * (MIN_HEX_CHARS // 2)
        found = violations_of(f"x = bytes.fromhex('{hexchars}')\n")
        assert len(found) == 1
        assert found[0].rule == "bytes_fromhex"

    def test_long_unhexlify_flagged(self):
        import binascii  # noqa: F401  (name referenced as text in source)

        hexchars = "47" * (MIN_HEX_CHARS // 2)
        found = violations_of(f"import binascii\nx = binascii.unhexlify('{hexchars}')\n")
        assert len(found) == 1
        assert found[0].rule == "bytes_fromhex"


class TestWaivers:
    def test_waiver_comment_suppresses_line_finding(self):
        payload = "A" * (MAX_BYTES_LITERAL + 1)
        source = f"x = b'{payload}'  # testdata-ok: checked-in golden sample copy\n"
        assert violations_of(source) == []

    def test_waiver_on_multiline_literal_end_line_suppresses(self):
        payload = "A" * (MAX_BYTES_LITERAL + 1)
        source = (
            "x = (\n"
            f"    b'{payload}'\n"
            "    # testdata-ok:理由\n"
            ")\n"
        )
        assert violations_of(source) == []

    def test_waiver_does_not_hide_other_lines(self):
        payload = "A" * (MAX_BYTES_LITERAL + 1)
        source = (
            f"a = b'{payload}'  # testdata-ok: covered\n"
            f"b = b'{payload}'\n"
        )
        found = violations_of(source)
        assert [v.line for v in found] == [2]


class TestSanctionedCodePasses:
    def test_constructor_calls_and_short_literals_pass(self):
        source = (
            "from tests._support.deterministic import seeded_ts_stream\n"
            "\n"
            "SYNC = b'\\x47'\n"
            "stream = seeded_ts_stream(seed=3, packet_count=8)\n"
            "blob = bytes(stream[:16])\n"
        )
        assert violations_of(source) == []

    def test_syntax_error_source_reported_not_crashed(self):
        assert violations_of("def broken(:\n") == []
