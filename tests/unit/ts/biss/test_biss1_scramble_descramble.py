"""BISS Mode 1 scramble/descramble primitives (SPEC-610 §6/§7, #126).

Seam: ``biss1.scramble`` / ``biss1.descramble`` with an injected backend.
Independent truth: the pure-Python CSA1 oracle (research #106 port,
vector-checked against libdvbcsa's own static vectors) — the production
dlopen backend is cross-checked against the same oracle in the adapter
tests.  Packet bytes come from the deterministic SPEC-108 generator chain
(frozen golden geometry, tests/README §5 byte-source rule 2 — nothing
hand-packed).
"""

from __future__ import annotations

import hashlib

import pytest

from ts.biss.biss1 import (
    BISS_DESCRAMBLE_FAILED_EVENT,
    BISS_SCRAMBLE_APPLIED_EVENT,
    CA_PID_BISS,
    CA_SYSTEM_ID_BISS_MODE_1,
    SELF_CHECK_OPAQUE,
    SELF_CHECK_STRUCTURE,
    SELF_CHECK_PSI_CRC32,
    SELF_CHECK_TSC_STATE,
    TSC_EVEN_KEY,
    descramble,
    key_fingerprint,
    scramble,
    unseen_pid_scope,
)
from tests._support.csa1_oracle import Csa1Oracle
from tests.unit.faults._fault_builders import (
    GOLDEN_ES1_PID,
    GOLDEN_PAT_PID,
    GOLDEN_PMT_PID,
    golden_baseline_packets,
)

SESSION_WORD = "A13DBC42908F"  # the J.96 §8 example session word
WRONG_SESSION_WORD = "0123456789AB"
PID_SCOPE = (GOLDEN_PAT_PID,)
WIDE_SCOPE = (GOLDEN_PAT_PID, GOLDEN_PMT_PID, GOLDEN_ES1_PID)

ORACLE = Csa1Oracle()


def _packets():
    return golden_baseline_packets()


def _first_in_scope(packets, pid):
    return next(p for p in packets if p.pid == pid and p.payload is not None)


class TestScrambleBasics:
    def test_in_scope_payloads_change_header_stays_clear(self):
        """Payload region transforms; the header stays clear except the
        TSC signaling bits (byte 3 bits 7:6) which flip to `10`."""
        packets = _packets()
        target = _first_in_scope(packets, GOLDEN_PAT_PID)
        scrambled = scramble(packets, SESSION_WORD, PID_SCOPE, backend=ORACLE)
        after = next(
            p for p in scrambled
            if p.pid == GOLDEN_PAT_PID
            and p.payload_unit_start_indicator
            and p.payload is not None
        )
        assert after.payload != target.payload
        original_header = target.to_bytes()[:4]
        after_header = after.to_bytes()[:4]
        assert after_header[:3] == original_header[:3]
        assert after_header[3] & 0x3F == original_header[3] & 0x3F
        assert after_header[3] >> 6 == TSC_EVEN_KEY
        assert len(after.to_bytes()) == 188

    def test_tsc_set_to_even_key_in_scope(self):
        scrambled = scramble(_packets(), SESSION_WORD, PID_SCOPE, backend=ORACLE)
        for packet in scrambled:
            if packet.pid == GOLDEN_PAT_PID:
                assert packet.transport_scrambling_control == TSC_EVEN_KEY
            else:
                assert packet.transport_scrambling_control == 0

    def test_out_of_scope_packets_untouched(self):
        packets = _packets()
        scrambled = scramble(packets, SESSION_WORD, PID_SCOPE, backend=ORACLE)
        for original, after in zip(packets, scrambled):
            if original.pid != GOLDEN_PAT_PID:
                assert after.to_bytes() == original.to_bytes()

    def test_slot_preserving_invariant(self):
        """等位替换: same count, same order, same 188-byte slots."""
        packets = _packets()
        scrambled = scramble(
            packets, SESSION_WORD, WIDE_SCOPE, backend=ORACLE
        )
        assert len(scrambled) == len(packets)
        for original, after in zip(packets, scrambled):
            assert after.pid == original.pid
            assert after.continuity_counter == original.continuity_counter
            assert len(after.to_bytes()) == 188

    def test_determinism_same_input_same_output(self):
        packets = _packets()
        first = tuple(
            p.to_bytes()
            for p in scramble(packets, SESSION_WORD, WIDE_SCOPE, backend=ORACLE)
        )
        second = tuple(
            p.to_bytes()
            for p in scramble(packets, SESSION_WORD, WIDE_SCOPE, backend=ORACLE)
        )
        assert first == second
        digest = hashlib.sha256(b"".join(first)).hexdigest()
        assert len(digest) == 64  # pinned shape; golden钉扎 in conformance

    def test_inputs_not_mutated(self):
        packets = _packets()
        before = tuple(p.to_bytes() for p in packets)
        scramble(packets, SESSION_WORD, WIDE_SCOPE, backend=ORACLE)
        assert tuple(p.to_bytes() for p in packets) == before

    def test_matches_csa_oracle_payload_transform(self):
        """The scrambled payload region equals the oracle's CSA1 transform
        of the payload under the derived CW (independent implementation
        cross-check)."""
        from ts.biss.biss1 import derive_cw

        packets = _packets()
        target = _first_in_scope(packets, GOLDEN_PAT_PID)
        cw = derive_cw(SESSION_WORD)[1]
        scrambled = scramble(packets, SESSION_WORD, PID_SCOPE, backend=ORACLE)
        after = next(
            p for p in scrambled
            if p.pid == GOLDEN_PAT_PID
            and p.payload_unit_start_indicator
            and p.payload is not None
        )
        expected_payload = ORACLE.encrypt_batch([target.payload], cw)[0]
        assert after.payload == expected_payload

    def test_bad_session_word_rejected(self):
        with pytest.raises(ValueError):
            scramble(_packets(), "nothex", PID_SCOPE, backend=ORACLE)


class TestDescramble:
    def test_roundtrip_with_declared_key(self):
        packets = _packets()
        scrambled = scramble(packets, SESSION_WORD, WIDE_SCOPE, backend=ORACLE)
        clear, checks = descramble(
            scrambled, SESSION_WORD, WIDE_SCOPE, backend=ORACLE
        )
        assert all(check.ok for check in checks)
        for original, after in zip(packets, clear):
            assert after.to_bytes() == original.to_bytes()

    def test_tsc_reset_to_clear(self):
        scrambled = scramble(_packets(), SESSION_WORD, WIDE_SCOPE, backend=ORACLE)
        clear, _ = descramble(
            scrambled, SESSION_WORD, WIDE_SCOPE, backend=ORACLE
        )
        for packet in clear:
            if packet.pid in WIDE_SCOPE:
                assert packet.transport_scrambling_control == 0

    def test_self_check_kinds_reported(self):
        """PAT packets (PSI) get the CRC-32 self-check; PES payload
        packets are honestly reported as opaque (no decodable structure)."""
        scrambled = scramble(_packets(), SESSION_WORD, WIDE_SCOPE, backend=ORACLE)
        _, checks = descramble(
            scrambled, SESSION_WORD, WIDE_SCOPE, backend=ORACLE
        )
        kinds = {check.index: check.self_check_kind for check in checks}
        pat_indices = {
            i for i, p in enumerate(scrambled) if p.pid == GOLDEN_PAT_PID
        }
        pes_indices = {
            i for i, p in enumerate(scrambled)
            if p.pid == GOLDEN_ES1_PID and p.payload is not None
        }
        assert all(
            kinds[i] == SELF_CHECK_PSI_CRC32 for i in pat_indices
        )
        assert all(kinds[i] == SELF_CHECK_OPAQUE for i in pes_indices)

    def test_wrong_key_descramble_yields_structural_failure_evidence(self):
        """错密钥解扰 → 结构自检失败证据（C1 形态）; the scrambled
        precondition itself still holds, the mismatch evidence comes from
        the payload-structure / PSI-CRC checks (解扰失败 ≠ 码流损坏 —
        explicit evidence, never a silent pass)."""
        packets = _packets()
        scrambled = scramble(packets, SESSION_WORD, PID_SCOPE, backend=ORACLE)
        _, checks = descramble(
            scrambled, WRONG_SESSION_WORD, PID_SCOPE, backend=ORACLE
        )
        failures = [check for check in checks if not check.ok]
        assert failures, "wrong-key descramble must produce evidence"
        assert all(
            c.self_check_kind != SELF_CHECK_TSC_STATE for c in failures
        )
        assert all(
            c.self_check_kind in (SELF_CHECK_PSI_CRC32, SELF_CHECK_STRUCTURE)
            for c in failures
        )

    def test_wrong_key_leaves_garbage_payload(self):
        packets = _packets()
        scrambled = scramble(packets, SESSION_WORD, PID_SCOPE, backend=ORACLE)
        clear, _ = descramble(
            scrambled, WRONG_SESSION_WORD, PID_SCOPE, backend=ORACLE
        )
        target = _first_in_scope(packets, GOLDEN_PAT_PID)
        after = next(
            p for p in clear
            if p.pid == GOLDEN_PAT_PID
            and p.payload_unit_start_indicator
            and p.payload is not None
        )
        assert after.payload != target.payload

    def test_descramble_clear_packet_tsc_state_failure(self):
        """A clear (TSC=0) packet in scope fails the scrambled-precondition
        check — 无解扰记录 ≠ 码流干净 (honest explicit state)."""
        packets = _packets()
        _, checks = descramble(
            packets, SESSION_WORD, PID_SCOPE, backend=ORACLE
        )
        failures = [c for c in checks if not c.ok]
        assert failures
        assert all(
            c.self_check_kind == SELF_CHECK_TSC_STATE for c in failures
        )


class TestEventSeam:
    """Reserved emission seam (ruling §10-7): payload shapes pinned by
    mock-emitter tests; registry registration is #129, end-to-end #128."""

    def test_scramble_applied_payload_shape(self):
        emitter = {}
        packets = _packets()
        scramble(
            packets,
            SESSION_WORD,
            PID_SCOPE,
            backend=ORACLE,
            on_scramble_applied=lambda payload: emitter.update(payload),
        )
        assert set(emitter) == {
            "pid_scope",
            "packet_count",
            "key_fingerprint",
            "mutation_log_ref",
        }
        assert emitter["pid_scope"] == [GOLDEN_PAT_PID]
        assert emitter["packet_count"] == sum(
            1 for p in packets if p.pid == GOLDEN_PAT_PID
        )
        assert emitter["key_fingerprint"] == key_fingerprint(SESSION_WORD)
        assert emitter["mutation_log_ref"] is None  # resolved by #128

    def test_no_emitter_is_silent(self):
        packets = _packets()
        result = scramble(packets, SESSION_WORD, PID_SCOPE, backend=ORACLE)
        assert len(result) == len(packets)

    def test_descramble_failed_payload_shape(self):
        emitter = {}
        scrambled = scramble(_packets(), SESSION_WORD, PID_SCOPE, backend=ORACLE)
        descramble(
            scrambled,
            WRONG_SESSION_WORD,
            PID_SCOPE,
            backend=ORACLE,
            on_descramble_failed=lambda payload: emitter.update(payload),
        )
        assert set(emitter) == {
            "pid_scope",
            "failed_indices_sample",
            "self_check_kind",
            "key_fingerprint_ref",
        }
        assert emitter["pid_scope"] == [GOLDEN_PAT_PID]
        assert emitter["failed_indices_sample"], "sample must be non-empty"
        assert emitter["self_check_kind"] in (
            SELF_CHECK_PSI_CRC32,
            SELF_CHECK_STRUCTURE,
        )
        assert emitter["key_fingerprint_ref"] == key_fingerprint(
            WRONG_SESSION_WORD
        )

    def test_descramble_failed_not_emitted_on_success(self):
        emitter = {}
        scrambled = scramble(_packets(), SESSION_WORD, PID_SCOPE, backend=ORACLE)
        descramble(
            scrambled,
            SESSION_WORD,
            PID_SCOPE,
            backend=ORACLE,
            on_descramble_failed=lambda payload: emitter.update(payload),
        )
        assert emitter == {}

    def test_event_type_constants_shape(self):
        for event_type in (
            BISS_SCRAMBLE_APPLIED_EVENT,
            BISS_DESCRAMBLE_FAILED_EVENT,
        ):
            namespace, _, name = event_type.partition(".")
            assert namespace == "biss"
            assert name

    def test_signaling_constants(self):
        """BISS carries no ECM: CA_system_ID 0x2600 / CA_PID 0x1FFF
        (Tech 3292; declared constants, C2 distinction per SPEC-612)."""
        assert CA_SYSTEM_ID_BISS_MODE_1 == 0x2600
        assert CA_PID_BISS == 0x1FFF


class TestPidScopeValidation:
    def test_empty_pid_scope_rejected(self):
        with pytest.raises(ValueError):
            scramble(_packets(), SESSION_WORD, (), backend=ORACLE)

    def test_out_of_range_pid_rejected(self):
        with pytest.raises(ValueError):
            scramble(_packets(), SESSION_WORD, (0x2000,), backend=ORACLE)

    def test_unseen_declared_pid_is_reported(self):
        """pid_scope 含不存在 PID → 显式警告态（SPEC-610 §8 裁量）:
        unseen declared pids are discoverable via ``unseen_pid_scope``."""
        packets = _packets()
        assert unseen_pid_scope(packets, (GOLDEN_PAT_PID, 0x0510)) == frozenset(
            {0x0510}
        )
        assert unseen_pid_scope(packets, (GOLDEN_PAT_PID,)) == frozenset()
