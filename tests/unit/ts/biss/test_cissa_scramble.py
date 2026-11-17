"""BISS2 CISSA scramble/descramble primitives (SPEC-611 §6/§7, TS 103 127
§6.3, ticket #127).

Seams under test: ``ts.biss.cissa`` — the fixed-IV pin, the §6.3.2
per-packet region rule (encrypted prefix + clear tail), the per-packet
restart independence (SPEC-611 §11: 改包 k 不影响包 k+1 输出), the
scramble/descramble roundtrip with structural self-checks, the
``biss.*`` payload ``mode`` field (ruling §10-7), and the dependency
face.

Crypto dependency: pycryptodome.  Absent → the module skips loudly with
the SPEC-611 §8 dependency reason (honest NOT RUN, ``-ra`` visible —
never a silent pass; the CI face installs pycryptodome so this runs
green there).

Packet bytes come from the canonical SPEC-108 generator chain (frozen
golden geometry — nothing hand-packed; tests/README §5 source rules).
"""

from __future__ import annotations

import pytest

try:
    import Crypto.Cipher.AES  # noqa: F401 — the dependency probe
except ImportError:
    pytest.skip(
        "pycryptodome absent — SPEC-611 §8 dependency face (CISSA); "
        "CISSA tests honestly NOT RUN without it",
        allow_module_level=True,
    )

from ts.biss.biss1 import (
    SELF_CHECK_OPAQUE,
    SELF_CHECK_PSI_CRC32,
    SELF_CHECK_TSC_STATE,
    TSC_EVEN_KEY,
)
from ts.biss.cissa import (
    BISS_MODE_1,
    BISS_MODE_2,
    BISS_MODE_E,
    CA_SYSTEM_ID_BISS2,
    CISSA_IV,
    SCRAMBLING_MODE_CISSA_V1,
    decrypt_payload,
    descramble,
    encrypt_payload,
    key_fingerprint,
    parse_ciss_key,
    scramble,
)
from tests.unit.faults._fault_builders import (
    GOLDEN_ES1_PID,
    GOLDEN_PAT_PID,
    golden_baseline_packets,
)
from tests._support.deterministic import seeded_bytes

pytestmark = pytest.mark.unit

# Deterministic 128-bit key material (sanctioned source — 32-hex literals
# are a data-rule violation).
CISS_KEY = seeded_bytes(0xC155A, 16).hex().upper()
WRONG_CISS_KEY = seeded_bytes(0xC155B, 16).hex().upper()
PID_SCOPE = (GOLDEN_PAT_PID, GOLDEN_ES1_PID)


def _packets():
    return golden_baseline_packets()


def _in_scope(packets, pid):
    return next(
        p for p in packets if p.pid == pid and p.payload is not None
    )


class TestWireConstants:
    def test_fixed_iv_is_the_ts103127_constant(self) -> None:
        """TS 103 127 §6.3.1.2: IV = 0x4456...5341 (ASCII
        DVBTMCPTAESCISSA) — a public standard constant."""
        assert CISSA_IV == b"DVBTMCPTAESCISSA"

    def test_signaling_constants_declared_not_delivered(self) -> None:
        assert CA_SYSTEM_ID_BISS2 == 0x2602  # BISS2 (Tech 3292 v3)
        assert SCRAMBLING_MODE_CISSA_V1 == 0x10  # §7 descriptor mode
        assert (BISS_MODE_1, BISS_MODE_E, BISS_MODE_2) == ("1", "E", "2")


class TestKeyFace:
    def test_parse_ciss_key_accepts_both_wire_shapes(self) -> None:
        raw = parse_ciss_key(CISS_KEY)
        assert len(raw) == 16
        assert parse_ciss_key(CISS_KEY.lower()) == raw
        assert parse_ciss_key(raw) == raw

    def test_parse_ciss_key_rejections_are_value_free(self) -> None:
        for bad in (CISS_KEY[1:], "ZZ" + CISS_KEY[2:], b"\x00" * 15):
            with pytest.raises(ValueError) as excinfo:
                parse_ciss_key(bad)
            assert CISS_KEY.lower() not in str(excinfo.value).lower()

    def test_key_fingerprint_stable_and_body_free(self) -> None:
        fingerprint = key_fingerprint(CISS_KEY)
        assert fingerprint.startswith("sha256:")
        assert fingerprint == key_fingerprint(CISS_KEY.lower())
        assert fingerprint == key_fingerprint(parse_ciss_key(CISS_KEY))
        assert CISS_KEY.lower() not in fingerprint


class TestPayloadRegionRule:
    def test_roundtrip_on_real_payload_regions(self) -> None:
        for packet in _packets():
            if packet.payload is None:
                continue
            scrambled = encrypt_payload(packet.payload, CISS_KEY)
            assert decrypt_payload(scrambled, CISS_KEY) == packet.payload

    def test_no_af_payload_encrypts_176_bytes_tail_clear(self) -> None:
        """§6.3.2 example 1: no AF ⇒ payload 184, 176 encrypted + 8
        clear tail (the frozen-geometry ES packets carry no AF)."""
        payload = _in_scope(_packets(), GOLDEN_ES1_PID).payload
        assert len(payload) == 184
        scrambled = encrypt_payload(payload, CISS_KEY)
        assert scrambled[:176] != payload[:176]
        assert scrambled[176:] == payload[176:]  # the clear tail

    def test_region_rule_holds_for_every_payload_length(self) -> None:
        """§6.3.2 region rule over the real generator mix (AF-carrying
        packets keep their payload regions short — 17/158/184 bytes):
        only ``payload − payload mod 16`` bytes transform, the tail (and
        the adaptation field, a separate object-model field) stay clear."""
        for packet in _packets():
            if packet.pid not in PID_SCOPE or packet.payload is None:
                continue
            payload = packet.payload
            cut = len(payload) - len(payload) % 16
            scrambled = encrypt_payload(payload, CISS_KEY)
            if cut:
                assert scrambled[:cut] != payload[:cut]
            assert scrambled[cut:] == payload[cut:]
            assert decrypt_payload(scrambled, CISS_KEY) == payload

    def test_partial_tail_rule_for_short_payload(self) -> None:
        """§6.3.2 region rule: ``payload − payload mod 16`` encrypted; a
        20-byte payload encrypts 16 bytes and leaves 4 clear."""
        payload = seeded_bytes(0xC155C, 20)
        scrambled = encrypt_payload(payload, CISS_KEY)
        assert scrambled[:16] != payload[:16]
        assert scrambled[16:] == payload[16:]
        assert decrypt_payload(scrambled, CISS_KEY) == payload

    def test_per_packet_restart_independence(self) -> None:
        """SPEC-611 §11 template: 改包 k 不影响包 k+1 输出 — CBC restarts
        from the fixed IV per packet, so packets carry no chain."""
        packets = _packets()
        in_scope = [
            p for p in packets
            if p.pid in PID_SCOPE and p.payload is not None
        ][:3]
        untouched = scramble(in_scope, CISS_KEY, PID_SCOPE)
        # Flip one payload byte of the middle packet (same slot shape).
        middle = in_scope[1]
        flipped = middle.__class__(
            pid=middle.pid,
            continuity_counter=middle.continuity_counter,
            payload=bytes([middle.payload[0] ^ 0xFF]) + middle.payload[1:],
            payload_unit_start_indicator=middle.payload_unit_start_indicator,
        )
        modified = [in_scope[0], flipped, in_scope[2]]
        after = scramble(modified, CISS_KEY, PID_SCOPE)
        # Packets 0 and 2 are byte-identical to their untouched outputs.
        assert after[0].to_bytes() == untouched[0].to_bytes()
        assert after[2].to_bytes() == untouched[2].to_bytes()
        # ...and the middle packet's clear tail byte position differs only
        # through its own payload (no cross-packet influence at all).
        assert after[1].payload[176:] == flipped.payload[176:]

    def test_scramble_is_deterministic(self) -> None:
        packets = _packets()
        first = scramble(packets, CISS_KEY, PID_SCOPE)
        second = scramble(packets, CISS_KEY, PID_SCOPE)
        assert b"".join(p.to_bytes() for p in first) == b"".join(
            p.to_bytes() for p in second
        )


class TestScrambleDescramble:
    def test_in_scope_payloads_transform_header_clear_tsc_marked(
        self,
    ) -> None:
        packets = _packets()
        target = _in_scope(packets, GOLDEN_PAT_PID)
        scrambled = scramble(packets, CISS_KEY, PID_SCOPE)
        after = _in_scope(scrambled, GOLDEN_PAT_PID)
        assert after.payload != target.payload
        original_header = target.to_bytes()[:4]
        after_header = after.to_bytes()[:4]
        assert after_header[:3] == original_header[:3]
        assert after_header[3] >> 6 == TSC_EVEN_KEY
        assert after_header[3] & 0x3F == original_header[3] & 0x3F
        assert len(after.to_bytes()) == 188  # slot-preserving

    def test_out_of_scope_packets_untouched(self) -> None:
        packets = _packets()
        scrambled = scramble(packets, CISS_KEY, (GOLDEN_PAT_PID,))
        for original, after in zip(packets, scrambled):
            if original.pid != GOLDEN_PAT_PID:
                assert after is original

    def test_roundtrip_restores_clear_packets_and_self_checks_pass(
        self,
    ) -> None:
        packets = _packets()
        scrambled = scramble(packets, CISS_KEY, PID_SCOPE)
        clear, checks = descramble(scrambled, CISS_KEY, PID_SCOPE)
        assert checks, "every in-scope packet is structurally self-checked"
        assert all(check.ok for check in checks)
        for original, after in zip(packets, clear):
            if original.pid in PID_SCOPE and original.payload is not None:
                assert after.payload == original.payload
                assert after.transport_scrambling_control == 0
            else:
                assert after is original


class TestEmissionSeams:
    def test_scramble_applied_payload_shape_with_mode(self) -> None:
        """Ruling §10-7 + SPEC-611 §5: the reserved seam payload carries
        the ``mode`` field (default ``"2"`` — declared CISSA key)."""
        seen: list[dict] = []
        scramble(
            _packets(),
            CISS_KEY,
            PID_SCOPE,
            on_scramble_applied=seen.append,
        )
        assert len(seen) == 1
        payload = seen[0]
        assert set(payload) == {
            "pid_scope",
            "packet_count",
            "key_fingerprint",
            "mutation_log_ref",
            "mode",
        }
        assert payload["mode"] == BISS_MODE_2
        assert payload["pid_scope"] == sorted(PID_SCOPE)
        assert payload["packet_count"] >= 1
        assert payload["key_fingerprint"] == key_fingerprint(CISS_KEY)
        assert payload["mutation_log_ref"] is None
        assert CISS_KEY.lower() not in str(payload)  # key body never leaks

    def test_mode_e_value_accepted_mode_1_rejected(self) -> None:
        seen: list[dict] = []
        scramble(
            _packets(),
            CISS_KEY,
            PID_SCOPE,
            mode=BISS_MODE_E,
            on_scramble_applied=seen.append,
        )
        assert seen[0]["mode"] == "E"
        with pytest.raises(ValueError):
            scramble(
                _packets(),
                CISS_KEY,
                PID_SCOPE,
                mode=BISS_MODE_1,  # the CSA1 face belongs to biss1
            )

    def test_descramble_failed_payload_shape_with_mode(self) -> None:
        """Wrong key → the SPEC-610 §7 evidence shape plus the SPEC-611
        §5 ``mode`` field (解扰失败 ≠ 码流损坏 — candidates, not facts)."""
        scrambled = scramble(_packets(), CISS_KEY, PID_SCOPE)
        seen: list[dict] = []
        _clear, checks = descramble(
            scrambled,
            WRONG_CISS_KEY,
            PID_SCOPE,
            mode=BISS_MODE_E,
            on_descramble_failed=seen.append,
        )
        failures = [check for check in checks if not check.ok]
        assert failures, "a wrong key must produce failure evidence"
        assert len(seen) == 1
        payload = seen[0]
        assert set(payload) == {
            "pid_scope",
            "failed_indices_sample",
            "self_check_kind",
            "key_fingerprint_ref",
            "mode",
        }
        assert payload["mode"] == BISS_MODE_E
        assert payload["pid_scope"] == sorted(PID_SCOPE)
        assert payload["failed_indices_sample"] == [
            check.index for check in failures
        ][:16]
        assert payload["self_check_kind"] == failures[0].self_check_kind
        assert payload["key_fingerprint_ref"] == key_fingerprint(
            WRONG_CISS_KEY
        )
        assert WRONG_CISS_KEY.lower() not in str(payload)

    def test_clear_in_scope_packet_is_explicit_tsc_state_evidence(
        self,
    ) -> None:
        """An in-scope packet NOT carrying the scrambled TSC is explicit
        evidence (``tsc_state``) — never silently passed or decrypted.
        With an all-clear input every in-scope packet lands in that
        state and nothing is decrypted."""
        packets = _packets()
        seen: list[dict] = []
        _clear, checks = descramble(
            packets, CISS_KEY, PID_SCOPE, on_descramble_failed=seen.append
        )
        in_scope_count = sum(
            1
            for p in packets
            if p.pid in PID_SCOPE and p.payload is not None
        )
        assert len(checks) == in_scope_count
        assert all(
            check.self_check_kind == SELF_CHECK_TSC_STATE
            for check in checks
        )
        assert all(not check.ok for check in checks)
        assert seen and set(seen[0]) == {
            "pid_scope",
            "failed_indices_sample",
            "self_check_kind",
            "key_fingerprint_ref",
            "mode",
        }
        assert seen[0]["self_check_kind"] == SELF_CHECK_TSC_STATE
