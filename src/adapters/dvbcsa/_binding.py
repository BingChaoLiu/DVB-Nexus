"""ctypes binding for libdvbcsa (SSE2 bitslice batch API) — the dlopen
face of the dvbcsa adapter (SPEC-610 §4/§9, ADR-0011 §1, ticket #126).

Importing this module is side-effect free (no dlopen, no DLL probe):
the binding is established lazily inside :func:`load_dvbcsa_backend`,
keeping libdvbcsa out of the static import graph (ADR-0011 §1 许可证纪律).

Binding shape mirrors the verified research #106 ctypes harness
(``dvbcsa_bs_key_alloc`` / ``dvbcsa_bs_key_set`` / ``dvbcsa_bs_batch_size``
/ ``dvbcsa_bs_encrypt`` / ``dvbcsa_bs_decrypt`` over the
``{unsigned char *data; unsigned int len;}`` batch array with a NULL-data
termination entry; ``maxlen`` must be a multiple of 8 — TS payload
regions are ≤184 and 184 is a multiple of 8).
"""

from __future__ import annotations

import ctypes
import ctypes.util
import os
from dataclasses import dataclass
from typing import Sequence

__all__ = [
    "DvbcsaBatchCipher",
    "DvbcsaUnavailableError",
    "DvbcsaDllProbe",
    "ENV_DVBCSA_DLL",
    "probe_dvbcsa_dll",
    "load_dvbcsa_backend",
]

#: Explicit DLL path override for libdvbcsa_bs (SSE2 bitslice build).
ENV_DVBCSA_DLL = "DVB_NEXUS_DVBCSA_DLL"

#: CSA1 packet payload region cap (DVBCSA_BS_MAX_PACKET_LEN, dvbcsa.h).
CSA_MAX_PAYLOAD_LEN = 184

#: maxlen passed to the batch calls: the bitslice width must be a
#: multiple of 8 and covers the largest TS payload region (184 = 23×8).
_BATCH_MAXLEN = CSA_MAX_PAYLOAD_LEN


class DvbcsaUnavailableError(RuntimeError):
    """libdvbcsa_bs could not be loaded (SPEC-610 §8 explicit degradation).

    Raised by :func:`load_dvbcsa_backend` and
    :class:`DvbcsaBatchCipher` construction — DLL 缺失是诚实显式错误，
    绝不静默回落（no silent fallback, ADR-0011 §1; CI NOT RUN semantics,
    ADR-0011 §5).  Composition roots surface this at startup/prepare.
    """


@dataclass(frozen=True)
class DvbcsaDllProbe:
    """One DLL availability probe result (immutable, cacheable)."""

    available: bool
    path: str | None
    detail: str


def probe_dvbcsa_dll() -> DvbcsaDllProbe:
    """Locate ``libdvbcsa_bs`` and report honestly (no silent skip).

    Resolution order: the explicit ``DVB_NEXUS_DVBCSA_DLL`` path, then
    the OS library search paths (``ctypes.util.find_library``).
    """
    explicit = os.environ.get(ENV_DVBCSA_DLL)
    if explicit:
        candidate_path = os.fspath(explicit)
        if not os.path.isfile(candidate_path):
            return DvbcsaDllProbe(
                available=False,
                path=candidate_path,
                detail=(
                    f"{ENV_DVBCSA_DLL}={candidate_path} does not address "
                    "an existing file"
                ),
            )
        return DvbcsaDllProbe(
            available=True,
            path=candidate_path,
            detail=f"explicit {ENV_DVBCSA_DLL} hit",
        )
    found = ctypes.util.find_library("dvbcsa_bs")
    if found:
        return DvbcsaDllProbe(
            available=True, path=found, detail="ctypes.util.find_library hit"
        )
    return DvbcsaDllProbe(
        available=False,
        path=None,
        detail=(
            "libdvbcsa_bs (SSE2 bitslice build) not found — set "
            f"{ENV_DVBCSA_DLL} to a local build (see "
            "tools/build_dvbcsa_dll.sh); on CI the DLL tests are honestly "
            "NOT RUN (ADR-0011 §5)"
        ),
    )


class _BsBatch(ctypes.Structure):
    """"struct dvbcsa_bs_batch_s { unsigned char *data; unsigned int len; }"""

    _fields_ = [
        ("data", ctypes.POINTER(ctypes.c_ubyte)),
        ("len", ctypes.c_uint),
    ]


def _load_library(dll_path: str | None) -> ctypes.CDLL:
    """dlopen libdvbcsa_bs and bind the batch API signatures."""
    path = dll_path
    if path is None:
        probe = probe_dvbcsa_dll()
        if not probe.available:
            raise DvbcsaUnavailableError(
                "libdvbcsa_bs could not be loaded: "
                f"{probe.detail} (DLL 缺失显式降级 — SPEC-610 §8; local "
                f"builds: tools/build_dvbcsa_dll.sh or set {ENV_DVBCSA_DLL})"
            )
        path = probe.path
    try:
        lib = ctypes.CDLL(path)
    except OSError as exc:
        raise DvbcsaUnavailableError(
            f"libdvbcsa_bs could not be loaded from {path!r}: {exc} "
            "(explicit degradation — SPEC-610 §8)"
        ) from exc

    lib.dvbcsa_bs_key_alloc.restype = ctypes.c_void_p
    lib.dvbcsa_bs_key_alloc.argtypes = []
    lib.dvbcsa_bs_key_free.restype = None
    lib.dvbcsa_bs_key_free.argtypes = [ctypes.c_void_p]
    # dvbcsa_cw_t is unsigned char[8]; as a parameter it decays to a pointer.
    lib.dvbcsa_bs_key_set.restype = None
    lib.dvbcsa_bs_key_set.argtypes = [ctypes.c_char_p, ctypes.c_void_p]
    lib.dvbcsa_bs_batch_size.restype = ctypes.c_uint
    lib.dvbcsa_bs_batch_size.argtypes = []
    # Batch call order per dvbcsa/dvbcsa.h: (key, pcks, maxlen).
    lib.dvbcsa_bs_encrypt.restype = None
    lib.dvbcsa_bs_encrypt.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(_BsBatch),
        ctypes.c_uint,
    ]
    lib.dvbcsa_bs_decrypt.restype = None
    lib.dvbcsa_bs_decrypt.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(_BsBatch),
        ctypes.c_uint,
    ]
    return lib


class DvbcsaBatchCipher:
    """Batch CSA1 cipher over one loaded libdvbcsa_bs instance.

    Satisfies the :class:`ts.biss.biss1.BatchCipherBackend` structural
    protocol: per-packet independent payload transforms (encrypt/decrypt
    batches of ≤184-byte payload regions under one 8-byte control word).
    Results are new bytes objects (inputs never mutated).
    """

    def __init__(self, dll_path: str | None = None) -> None:
        self._lib = _load_library(dll_path)
        self._batch_size = int(self._lib.dvbcsa_bs_batch_size())
        if self._batch_size < 1:
            raise DvbcsaUnavailableError(
                "libdvbcsa_bs reported a non-positive batch size "
                f"({self._batch_size}) — broken build"
            )

    def batch_size(self) -> int:
        """The library's packets-per-batch cap (SSE2 build: 128)."""
        return self._batch_size

    def encrypt_batch(
        self, payloads: Sequence[bytes], cw: bytes
    ) -> "tuple[bytes, ...]":
        """CSA1-encrypt each payload under ``cw`` (per-packet independent)."""
        return self._run_batch(payloads, cw, self._lib.dvbcsa_bs_encrypt)

    def decrypt_batch(
        self, payloads: Sequence[bytes], cw: bytes
    ) -> "tuple[bytes, ...]":
        """CSA1-decrypt each payload under ``cw`` (per-packet independent)."""
        return self._run_batch(payloads, cw, self._lib.dvbcsa_bs_decrypt)

    # --- internals ---------------------------------------------------------

    def _run_batch(
        self, payloads: Sequence[bytes], cw: bytes, batch_fn
    ) -> "tuple[bytes, ...]":
        key = self._make_key(cw)
        try:
            buffers = [self._validated_buffer(payload) for payload in payloads]
            lengths = [len(payload) for payload in payloads]
            out: list[bytes] = []
            for start in range(0, len(buffers), self._batch_size):
                chunk = buffers[start:start + self._batch_size]
                chunk_lengths = lengths[start:start + self._batch_size]
                out.extend(self._call_batch(batch_fn, chunk, chunk_lengths, key))
        finally:
            # Native key lifecycle: every alloc is paired with exactly one
            # free — including the ValueError path (payload >184) and any
            # batch_fn failure (no handle leaks across the ctypes boundary).
            self._lib.dvbcsa_bs_key_free(key)
        return tuple(out)

    def _make_key(self, cw: bytes) -> int:
        if not isinstance(cw, (bytes, bytearray)) or len(cw) != 8:
            raise ValueError(
                "CSA control word must be exactly 8 bytes, got "
                f"{len(cw) if isinstance(cw, (bytes, bytearray)) else cw!r}"
            )
        key = self._lib.dvbcsa_bs_key_alloc()
        if not key:
            raise DvbcsaUnavailableError(
                "dvbcsa_bs_key_alloc returned NULL — broken libdvbcsa build"
            )
        self._lib.dvbcsa_bs_key_set(bytes(cw), key)
        return key

    @staticmethod
    def _validated_buffer(payload: bytes) -> ctypes.create_string_buffer:
        if len(payload) > CSA_MAX_PAYLOAD_LEN:
            raise ValueError(
                f"CSA payload region must be ≤{CSA_MAX_PAYLOAD_LEN} bytes, "
                f"got {len(payload)} (TS payload region cap)"
            )
        return ctypes.create_string_buffer(bytes(payload), len(payload) or 1)

    @staticmethod
    def _call_batch(batch_fn, buffers, lengths, key) -> "list[bytes]":
        count = len(buffers)
        # +1: the NULL-data termination entry the API contract requires.
        entries = (_BsBatch * (count + 1))()
        for i, buf in enumerate(buffers):
            entries[i].data = ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte))
            entries[i].len = lengths[i]
        entries[count].data = None
        entries[count].len = 0
        batch_fn(key, entries, _BATCH_MAXLEN)
        return [bytes(buffers[i].raw[: lengths[i]]) for i in range(count)]


def load_dvbcsa_backend() -> DvbcsaBatchCipher:
    """Load libdvbcsa_bs and return the batch-cipher backend.

    Composition-root entry point (#128 wiring / prepare-time probes):
    DLL absence raises :class:`DvbcsaUnavailableError` — honest explicit
    degradation at startup/prepare, never a silent fallback.
    """
    return DvbcsaBatchCipher()
