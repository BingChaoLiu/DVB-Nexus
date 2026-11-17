"""BISS Mode E derivation (SPEC-611 §4/§6, J.96 §9.3, ticket #127).

Seams under test: ``ts.biss.mode_e`` — wire parsers (prepare-time
rejection, value-free errors), the J.96 §9.3.3 a mapping (odd-parity
expansion), the deterministic ``derive_sw`` known answer, the Mode 1 CW
continuity (biss1 J.96 §8 checksum), the sandbox Mode E → CISSA key
composition, and the redacted evidence face.

Byte discipline (tests/README §5): the ESW/Injected-ID constants come
from the deterministic generator (sanctioned source 2 — ``seeded_bytes``);
32-hex literals are a data-rule violation.  The full-chain known-answer
pin against an INDEPENDENT generator lives in the conformance layer
(``tests/conformance/test_biss_mode_e_golden.py``); this unit layer pins
determinism and formula-component shapes only.
"""

from __future__ import annotations

import pytest

from ts.biss.biss1 import derive_cw as derive_cw_from_session_word
from ts.biss.biss1 import parse_session_word
from ts.biss.cissa import CISSA_KEY_BYTES
from ts.biss.mode_e import (
    ESW_BYTES,
    ESW_CHARS,
    INJECTED_ID_BYTES,
    INJECTED_ID_CHARS,
    active_id_from_injected_id,
    derive_ciss_key,
    derive_cw,
    derive_sw,
    derivation_ref,
    key_fingerprint,
    map_active_id,
    parse_esw,
    parse_injected_id,
)
from tests._support.deterministic import seeded_bytes

pytestmark = pytest.mark.unit

# Deterministic wire constants (sanctioned byte source — no hand-packed
# literals; same seeds always yield the same material).
INJECTED_ID = seeded_bytes(0xA11CE, 16).hex().upper()
ESW = seeded_bytes(0xE5, 8).hex().upper()

# The deterministic known answer for the constants above (determinism
# pin — the standard-anchored cross-check is the conformance golden).
KNOWN_SESSION_WORD = "6CE60DE46286"
KNOWN_CW = "6CE60D5FE46286CC"


class TestWireParsers:
    def test_esw_and_id_accept_both_wire_shapes(self) -> None:
        assert len(parse_esw(ESW)) == ESW_BYTES
        assert parse_esw(ESW) == parse_esw(ESW.lower())  # case-insensitive
        assert len(parse_injected_id(INJECTED_ID)) == INJECTED_ID_BYTES
        assert (
            parse_injected_id(INJECTED_ID)
            == parse_injected_id(INJECTED_ID.lower())
        )
        assert parse_esw(ESW) == bytes.fromhex(ESW.lower())

    def test_esw_format_rejections_are_value_free(self) -> None:
        """SPEC-611 §8: format-illegal ESW is a prepare-time rejection,
        and the key body never leaks into the error (key discipline)."""
        for bad in ("A9D55F873375AA", "Z9D55F873375AA23", 12345):
            with pytest.raises(ValueError) as excinfo:
                parse_esw(bad)
            assert "A9D55F873375AA23".lower() not in str(
                excinfo.value
            ).lower()

    def test_injected_id_format_rejections_are_value_free(self) -> None:
        for bad in ("2A48ADBE", "ZZ48ADBEA4A897CB66CD6DA66112CC96", b"\x00" * 5):
            with pytest.raises(ValueError) as excinfo:
                parse_injected_id(bad)
            assert INJECTED_ID.lower() not in str(excinfo.value).lower()


class TestJ96Mapping:
    def test_active_id_is_the_low_56_bits(self) -> None:
        """The DES key face consumes the trailing 7 bytes / 14 hex chars
        (the sandbox pin for the Tech 3292-s1 session-key semantics)."""
        active = active_id_from_injected_id(INJECTED_ID)
        assert active == bytes.fromhex(INJECTED_ID.lower())[-7:]
        assert len(active) == 7

    def test_mapped_active_id_is_odd_parity_expansion(self) -> None:
        """J.96 §9.3.3 a / Table 2: 56 bits into the upper seven bits of
        8 bytes, each byte's LSB set for odd parity."""
        mapped = map_active_id(active_id_from_injected_id(INJECTED_ID))
        assert len(mapped) == 8
        for byte in mapped:
            assert bin(byte).count("1") % 2 == 1, "odd parity per byte"
        # The seven payload bits of each byte carry the Active ID bits in
        # order (msb-first) — rebuild and compare.
        rebuilt = 0
        for byte in mapped:
            rebuilt = (rebuilt << 7) | (byte >> 1)
        active_value = int.from_bytes(
            active_id_from_injected_id(INJECTED_ID), "big"
        )
        assert rebuilt == active_value

    def test_mapped_active_id_rejects_wrong_shape(self) -> None:
        with pytest.raises(ValueError):
            map_active_id(b"\x00" * 6)


class TestDeriveSw:
    def test_known_answer_deterministic(self) -> None:
        """Determinism pin (SPEC-611 §6/AC-611-01): same inputs → same
        12-hex session word; the independent-implementation cross-check
        is the conformance golden."""
        first = derive_sw(ESW, INJECTED_ID)
        assert first == KNOWN_SESSION_WORD
        assert derive_sw(ESW, INJECTED_ID) == first
        assert derive_sw(ESW.lower(), INJECTED_ID.lower()) == first
        assert len(first) == 12  # 48-bit session word wire shape

    def test_wrong_session_word_shows_as_different_derivation(self) -> None:
        """A format-valid but wrong ESW still derives — to a DIFFERENT
        session word (SPEC-611 §7: 错 ESW → 派生出错误 SW; no structural
        check flags it, the evidence fingerprints do)."""
        wrong_esw = seeded_bytes(0xE6, 8).hex().upper()
        assert derive_sw(wrong_esw, INJECTED_ID) != KNOWN_SESSION_WORD

    def test_wrong_injected_id_shows_as_different_derivation(self) -> None:
        wrong_id = seeded_bytes(0xA11D, 16).hex().upper()
        assert derive_sw(ESW, wrong_id) != KNOWN_SESSION_WORD

    def test_cw_rides_the_single_j96_check_implementation(self) -> None:
        """``session word → CW`` is the biss1 J.96 §8 checksum formula —
        the Mode E chain must land exactly on it (single CW face)."""
        session_word = derive_sw(ESW, INJECTED_ID)
        cw_odd, cw_even = derive_cw_from_session_word(session_word)
        me_odd, me_even = derive_cw(ESW, INJECTED_ID)
        assert (me_odd, me_even) == (cw_odd, cw_even)
        assert me_odd == me_even  # Mode 1: one CW, both parity slots
        assert me_even.hex().upper() == KNOWN_CW


class TestCissKeyComposition:
    def test_ciss_key_is_the_documented_cw_doubling(self) -> None:
        """Sandbox composition pin: ``ciss_key = CW ‖ CW`` (16-byte
        AES-128 key; documented rule, golden-pinned in conformance)."""
        cw = derive_cw(ESW, INJECTED_ID)[1]
        ciss_key = derive_ciss_key(ESW, INJECTED_ID)
        assert len(ciss_key) == CISSA_KEY_BYTES
        assert ciss_key == cw + cw


class TestEvidenceFace:
    def test_derivation_ref_carries_fingerprints_only(self) -> None:
        """SPEC-611 §5 派生链引用: fingerprints only — none of the key
        bodies may appear in the reference (hard red line)."""
        ref = derivation_ref(ESW, INJECTED_ID)
        assert set(ref) == {
            "esw_fingerprint",
            "injected_id_fingerprint",
            "session_word_fingerprint",
            "ciss_key_fingerprint",
        }
        blob = " ".join(ref.values())
        for body in (ESW, INJECTED_ID, KNOWN_SESSION_WORD):
            assert body.lower() not in blob
        assert all(
            value.startswith("sha256:") for value in ref.values()
        )

    def test_mismatch_faces_are_distinguishable(self) -> None:
        """SPEC-611 §8: the two wrong-key variants are distinguishable in
        evidence — each wrong face moves ITS OWN fingerprint while the
        other face's fingerprint stays pinned to the declared chain."""
        declared = derivation_ref(ESW, INJECTED_ID)
        wrong_esw_ref = derivation_ref(seeded_bytes(0xE6, 8), INJECTED_ID)
        wrong_id_ref = derivation_ref(ESW, seeded_bytes(0xA11D, 16))
        assert (
            wrong_esw_ref["esw_fingerprint"]
            != declared["esw_fingerprint"]
        )
        assert (
            wrong_esw_ref["injected_id_fingerprint"]
            == declared["injected_id_fingerprint"]
        )
        assert (
            wrong_id_ref["injected_id_fingerprint"]
            != declared["injected_id_fingerprint"]
        )
        assert wrong_id_ref["esw_fingerprint"] == declared["esw_fingerprint"]
        # Both wrong chains land somewhere new downstream.
        assert (
            wrong_esw_ref["session_word_fingerprint"]
            != declared["session_word_fingerprint"]
        )
        assert (
            wrong_id_ref["session_word_fingerprint"]
            != declared["session_word_fingerprint"]
        )

    def test_key_fingerprint_is_stable_across_case(self) -> None:
        session_word = parse_session_word(derive_sw(ESW, INJECTED_ID))
        assert key_fingerprint(session_word).startswith("sha256:")
        assert key_fingerprint(session_word) == key_fingerprint(
            session_word.hex().upper()
        )
