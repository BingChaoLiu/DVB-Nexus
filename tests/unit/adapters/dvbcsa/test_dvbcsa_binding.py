"""dvbcsa adapter binding tests (SPEC-610 §6/§8/§9, ADR-0011 §1, #126).

Seam: :class:`adapters.dvbcsa.DvbcsaBatchCipher` — the dlopen + ctypes
face over the libdvbcsa SSE2 batch API.  Independent truth: the
libdvbcsa static test vectors (tests/data/biss/csa1_static_vectors.json,
extracted programmatically from ``test/testdec.c`` by research #106) and
the pure-Python CSA1 oracle (``tests/_support/csa1_oracle.py``) as the
cross-implementation对拍.

These tests are DLL-gated: the ``dvbcsa_dll`` fixture skips with a
visible reason when libdvbcsa_bs is absent — on CI this file is honestly
NOT RUN (ADR-0011 §5; ruling §10-2).  The loader-missing behavior tests
(degradation honesty) are pure and always run.
"""

import pytest

from adapters.dvbcsa import (
    DvbcsaBatchCipher,
    DvbcsaUnavailableError,
    load_dvbcsa_backend,
)
from tests._support.csa1_oracle import (
    Csa1Oracle,
    load_csa1_static_vectors,
)

CSA_VECTORS = load_csa1_static_vectors()


class _RecordingKeyLib:
    """Fake of the loaded libdvbcsa_bs ctypes face — records every
    ``dvbcsa_bs_key_alloc`` / ``dvbcsa_bs_key_free`` call so the
    alloc/free pairing invariant is observable in a pure unit test
    (no DLL, no ctypes; the handle is an opaque truthy sentinel)."""

    def __init__(self):
        self.alloc_calls = 0
        self.free_calls = 0
        self.allocated = []
        self.freed = []

    def dvbcsa_bs_key_alloc(self):
        self.alloc_calls += 1
        handle = object()  # opaque truthy native-handle stand-in
        self.allocated.append(handle)
        return handle

    def dvbcsa_bs_key_free(self, key):
        self.free_calls += 1
        self.freed.append(key)

    def dvbcsa_bs_key_set(self, cw, key):
        pass

    def dvbcsa_bs_batch_size(self):
        return 4

    def dvbcsa_bs_encrypt(self, key, entries, maxlen):
        pass

    def dvbcsa_bs_decrypt(self, key, entries, maxlen):
        pass


def _cipher_with_recording_lib() -> "tuple[DvbcsaBatchCipher, _RecordingKeyLib]":
    """Build a :class:`DvbcsaBatchCipher` around the recording fake lib
    (bypasses ``__init__``/dlopen — the lifecycle contract under test
    lives in ``_run_batch``/``_make_key``)."""
    lib = _RecordingKeyLib()
    cipher = object.__new__(DvbcsaBatchCipher)
    cipher._lib = lib
    cipher._batch_size = lib.dvbcsa_bs_batch_size()
    return cipher, lib


class TestLoaderDegradation:
    def test_missing_dll_raises_unavailable_error(self):
        """DLL 缺失 = 显式降级错误（诚实态，不静默回落）— SPEC-610 §8.

        A path that cannot exist exercises the load-failure branch
        deterministically on every machine (no env mutation — the unit
        layer forbids fixture requests, SPEC-505 §8 io_rules)."""
        bogus = "Z:/definitely/not/libdvbcsa_bs.dll"
        with pytest.raises(DvbcsaUnavailableError) as excinfo:
            DvbcsaBatchCipher(bogus)
        assert "libdvbcsa_bs" in str(excinfo.value)
        assert bogus in str(excinfo.value)

    def test_error_is_a_runtime_error_not_silent_fallback(self):
        """The degradation error type is raised (not swallowed into a
        None-returning factory): honest absence, never a fake backend."""
        assert issubclass(DvbcsaUnavailableError, RuntimeError)


class TestKeyLifecyclePairing:
    """Native key alloc/free pairing (M6 code-review fix round).

    ``dvbcsa_bs_key_alloc`` hands back a native handle the GC cannot
    see — every batch run must pair it with exactly one
    ``dvbcsa_bs_key_free``, on the happy path *and* on every failure
    path (payload validation, batch_fn failure).  Recorded via the
    fake lib; the DLL-gated correctness tests above exercise the real
    allocator locally (``DVB_NEXUS_DVBCSA_DLL``)."""

    def test_happy_path_pairs_one_free_with_one_alloc(self):
        cipher, lib = _cipher_with_recording_lib()
        payloads = tuple(bytes(8 * (i + 1)) for i in range(6))  # 2 chunks
        cipher.encrypt_batch(payloads, bytes(8))
        assert lib.alloc_calls == 1
        assert lib.free_calls == 1
        assert lib.freed == lib.allocated

    def test_payload_validation_failure_still_frees_key(self):
        cipher, lib = _cipher_with_recording_lib()
        with pytest.raises(ValueError):
            cipher.encrypt_batch([bytes(8), bytes(185)], bytes(8))
        assert lib.alloc_calls == 1
        assert lib.free_calls == 1
        assert lib.freed == lib.allocated

    def test_batch_fn_failure_still_frees_key(self):
        cipher, lib = _cipher_with_recording_lib()

        def exploding_encrypt(key, entries, maxlen):
            raise RuntimeError("simulated native failure")

        lib.dvbcsa_bs_encrypt = exploding_encrypt
        with pytest.raises(RuntimeError):
            cipher.encrypt_batch([bytes(8)], bytes(8))
        assert lib.alloc_calls == 1
        assert lib.free_calls == 1
        assert lib.freed == lib.allocated

    def test_invalid_control_word_allocates_and_frees_nothing(self):
        cipher, lib = _cipher_with_recording_lib()
        with pytest.raises(ValueError):
            cipher.encrypt_batch([bytes(8)], b"\x01\x02\x03")
        assert lib.alloc_calls == 0
        assert lib.free_calls == 0

    def test_decrypt_batch_pairs_free_with_alloc(self):
        cipher, lib = _cipher_with_recording_lib()
        cipher.decrypt_batch([bytes(8)], bytes(8))
        assert lib.alloc_calls == 1
        assert lib.free_calls == 1
        assert lib.freed == lib.allocated


class TestDvbcsaBatchCipher:
    """DLL-gated binding behavior (CI: NOT RUN with visible reason)."""

    def test_static_vectors_encrypt_decrypt_roundtrip(
        self, dvbcsa_dll
    ):
        cipher = DvbcsaBatchCipher(dvbcsa_dll.path)
        for cw, scrambled, plaintext in CSA_VECTORS:
            assert cipher.encrypt_batch([plaintext], cw) == (scrambled,)
            assert cipher.decrypt_batch([scrambled], cw) == (plaintext,)
            # roundtrip through the same buffer shape
            assert cipher.decrypt_batch(
                cipher.encrypt_batch([plaintext], cw), cw
            ) == (plaintext,)

    def test_matches_pure_python_oracle(self, dvbcsa_dll):
        """正确性对拍 (CI oracle): DLL batch output == pure-Python CSA1
        oracle output for the static vectors and a random-ish payload set
        (correctness only — the oracle's throughput is irrelevant)."""
        oracle = Csa1Oracle()
        cipher = DvbcsaBatchCipher(dvbcsa_dll.path)
        cw, _, plaintext = CSA_VECTORS[0]
        extra_payloads = tuple(
            bytes((i * 7 + k) % 256 for k in range(184)) for i in range(5)
        )
        payloads = (plaintext,) + extra_payloads
        assert cipher.encrypt_batch(payloads, cw) == (
            oracle.encrypt_batch(payloads, cw)
        )
        scrambled = cipher.encrypt_batch(payloads, cw)
        assert cipher.decrypt_batch(scrambled, cw) == payloads
        assert oracle.decrypt_batch(scrambled, cw) == payloads

    def test_batch_larger_than_lib_batch_size_chunks(self, dvbcsa_dll):
        """Payloads beyond ``dvbcsa_bs_batch_size()`` are chunked — the
        caller never sees a partial result."""
        cipher = DvbcsaBatchCipher(dvbcsa_dll.path)
        batch_size = cipher.batch_size()
        assert batch_size >= 1
        cw, _, plaintext = CSA_VECTORS[0]
        payloads = tuple(plaintext for _ in range(batch_size * 2 + 3))
        scrambled = cipher.encrypt_batch(payloads, cw)
        assert len(scrambled) == len(payloads)
        assert cipher.decrypt_batch(scrambled, cw) == payloads

    def test_batch_size_is_positive_int(self, dvbcsa_dll):
        cipher = DvbcsaBatchCipher(dvbcsa_dll.path)
        assert isinstance(cipher.batch_size(), int)
        assert cipher.batch_size() > 0

    def test_rejects_payload_longer_than_184(self, dvbcsa_dll):
        cipher = DvbcsaBatchCipher(dvbcsa_dll.path)
        cw = CSA_VECTORS[0][0]
        with pytest.raises(ValueError):
            cipher.encrypt_batch([bytes(185)], cw)

    def test_rejects_non_8_byte_control_word(self, dvbcsa_dll):
        cipher = DvbcsaBatchCipher(dvbcsa_dll.path)
        with pytest.raises(ValueError):
            cipher.encrypt_batch([bytes(184)], b"\x01\x02\x03")

    def test_load_dvbcsa_backend_returns_batch_cipher(self, dvbcsa_dll):
        backend = load_dvbcsa_backend()
        assert isinstance(backend, DvbcsaBatchCipher)
