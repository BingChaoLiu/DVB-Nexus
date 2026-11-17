"""BISS Mode 1 CW derivation + key fingerprint (SPEC-610 §5/§6, ticket #126).

Independent truth: the ITU-T J.96 §8 example session word
``A13DBC42908F`` derives to control word ``A13DBC9A42908F61`` (checksum
bytes per the Tech 3292/J.96 formula, cross-checked by three independent
implementations in research #106).  The J.96 session word is a *published
standard constant* (a public test vector, not key material) — pinning it
in tests is the golden-pinning discipline the ticket mandates.
"""

import pytest

from ts.biss.biss1 import (
    SESSION_WORD_CHARS,
    SESSION_WORD_BYTES,
    derive_cw,
    key_fingerprint,
)

J96_SESSION_WORD = "A13DBC42908F"
J96_CW_HEX = "A13DBC9A42908F61"


class TestDeriveCw:
    def test_j96_example_vector(self):
        odd, even = derive_cw(J96_SESSION_WORD)
        assert even.hex().upper() == J96_CW_HEX

    def test_mode1_single_cw_serves_both_parity_slots(self):
        """J.96 Mode 1 defines ONE control word (TSC pinned to `10`, the
        even slot); the odd slot mirrors the same derived CW for interface
        symmetry — both parity positions carry the identical key."""
        odd, even = derive_cw(J96_SESSION_WORD)
        assert odd == even

    def test_checksum_bytes_are_byte_sums_mod_256(self):
        """CW[3] = (CW[0]+CW[1]+CW[2]) mod 256; CW[7] = (CW[4]+CW[5]+CW[6])
        mod 256 — the formula survives independently on the J.96 vector:
        0xA1+0x3D+0xBC = 0x9A, 0x42+0x90+0x8F = 0x61."""
        cw = derive_cw(J96_SESSION_WORD)[1]
        assert cw[3] == (cw[0] + cw[1] + cw[2]) % 256
        assert cw[7] == (cw[4] + cw[5] + cw[6]) % 256

    def test_accepts_lowercase_hex(self):
        assert derive_cw(J96_SESSION_WORD.lower()) == derive_cw(
            J96_SESSION_WORD
        )

    def test_session_word_shaped_as_bytes(self):
        odd, even = derive_cw(bytes.fromhex(J96_SESSION_WORD))
        assert even.hex().upper() == J96_CW_HEX

    @pytest.mark.parametrize(
        "bad", ["", "A13DBC42908", "A13DBC42908FF", "Z13DBC42908F", None, 123]
    )
    def test_invalid_session_word_rejected(self, bad):
        with pytest.raises(ValueError):
            derive_cw(bad)


class TestKeyFingerprint:
    def test_shape_is_sha256_prefix(self):
        fp = key_fingerprint(bytes.fromhex(J96_SESSION_WORD))
        assert fp.startswith("sha256:")
        suffix = fp.removeprefix("sha256:")
        assert len(suffix) == 16
        int(suffix, 16)  # hex chars only

    def test_same_key_same_fingerprint(self):
        a = key_fingerprint(bytes.fromhex(J96_SESSION_WORD))
        b = key_fingerprint(bytes.fromhex(J96_SESSION_WORD))
        assert a == b

    def test_case_insensitive_hex_equivalence(self):
        """The same key spelled in different hex case is the same key —
        the fingerprint must not fork on spelling."""
        upper = key_fingerprint(J96_SESSION_WORD)
        lower = key_fingerprint(J96_SESSION_WORD.lower())
        assert upper == lower

    def test_different_keys_different_fingerprints(self):
        a = key_fingerprint(bytes.fromhex(J96_SESSION_WORD))
        b = key_fingerprint(bytes.fromhex("0123456789AB"))
        assert a != b

    def test_fingerprint_is_not_reversible_key_material(self):
        """16 hex chars = 64 bits of a 256-bit hash — the fingerprint
        carries no reversible key material (SPEC-610 §9 discipline)."""
        fp = key_fingerprint(bytes.fromhex(J96_SESSION_WORD))
        assert J96_SESSION_WORD.lower() not in fp.lower()
