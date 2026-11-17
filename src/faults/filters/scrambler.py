"""ADR-0011 §2 — the scrambler filter type (ADR-0007 filters family,
layer=BISS), real implementation: SPEC-610 §6/§9, ticket #126.

BISS scrambling is a per-packet payload transform (header 4 bytes clear
except the TSC signaling bits, length 188 unchanged, packet order
unchanged), so the ``apply(index, packet)`` contract applies as-is — no
new transport-level component.  Construction features (scenario-declared
keys, the scenario ``biss`` section) and fault injection
(``FaultDefinition.parameters`` mismatched keys) drive the *same*
scrambler filter; only the key source differs (ADR-0011 §2/§3):

- ``ScramblerTransform`` — the filter type; the caller injects the key
  (``session_word``), the pid scope and the CSA1 batch backend.  #128's
  composition wiring drives the construction path with the scenario
  ``biss`` section key;
- ``BissKeyMismatchTransform`` — the fault-injection path: reads the
  mismatched key from ``BISS_KEY_MISMATCH`` parameters (Mode 1
  ``wrong_session_word`` variant; the Mode E ``wrong_esw`` /
  ``wrong_injected_id`` variants are explicitly dispatched to #127,
  SPEC-611) and self-registers via :func:`faults.factory.register_transform`
  at import time (ruling §10-4 — ``factory.py`` is never edited again).

Key discipline (SPEC-610 §9, ADR-0011 §3 — hard red line): key material
never enters the mutation log, journal events or artifacts.  This module
redacts the key from the evidence-facing definition snapshot before any
``MutationRecord`` or fault summary is produced — the log carries only
``key_fingerprint`` traces.

DLL discipline: importing this module does NOT dlopen libdvbcsa (the
adapter load is lazy, at first filter construction / first transform —
an explicit :class:`adapters.dvbcsa.DvbcsaUnavailableError` at that point
is the honest degradation, SPEC-610 §8; probes for startup/prepare
reporting go through :func:`adapters.dvbcsa.load_dvbcsa_backend`).
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping

from ts.biss.biss1 import (
    TSC_EVEN_KEY,
    BatchCipherBackend,
    derive_cw,
    key_fingerprint,
)
from ts.biss.cissa import BISS_MODE_1
from faults.filters.base import FaultTransform
from ts.packet import TSPacket

from faults.factory import register_transform
from faults.registry import FAULT_TYPE_BISS_KEY_MISMATCH

__all__ = [
    "ScramblerTransform",
    "BissKeyMismatchTransform",
    "redact_key_parameters",
]

#: Key-material parameter keys per BISS variant (SPEC-610 §5 / SPEC-611 §5).
#: Values under these keys never reach the mutation log — they are
#: redacted to ``<key>_fingerprint`` traces.
_KEY_PARAMETER_KEYS = (
    "wrong_session_word",
    "wrong_esw",
    "wrong_injected_id",
)


#: Overridable default-backend loader seam (tests swap it via a plain
#: try/finally context manager — the unit layer forbids fixture requests;
#: production keeps ``None`` → the dvbcsa dlopen adapter).
_DEFAULT_BACKEND_LOADER = None


def _default_backend() -> BatchCipherBackend:
    if _DEFAULT_BACKEND_LOADER is not None:
        return _DEFAULT_BACKEND_LOADER()
    from adapters.dvbcsa import load_dvbcsa_backend

    return load_dvbcsa_backend()


def redact_key_parameters(
    parameters: Mapping[str, Any],
) -> dict[str, Any]:
    """Replace key-material parameter values with their fingerprints.

    The mutation log's effective-parameter snapshot (SPEC-204 §8.2) and
    every per-record parameters entry keep pid scope and shape, but the
    key bodies become ``<param>_fingerprint`` hash prefixes (SPEC-610
    §2.1 "mutation log 密钥指纹语义（哈希前缀，不落密钥本体）").
    """
    redacted = dict(parameters)
    for key in _KEY_PARAMETER_KEYS:
        if key in redacted:
            redacted[f"{key}_fingerprint"] = key_fingerprint(
                redacted.pop(key)
            )
    return redacted


class ScramblerTransform(FaultTransform):
    """The scrambler filter type (ADR-0007 filters family, layer=BISS).

    Slot-preserving contract: one packet in, one packet out at the same
    index — 188-byte length and packet order unchanged (等位替换 invariant
    holds at the BISS layer).  In-scope payload slots are CSA1-encrypted
    under the injected key and TSC-marked ``10`` (J.96 §8.1 even-key
    slot); everything else passes through untouched.

    ``backend`` is the CSA1 batch cipher (production:
    :class:`adapters.dvbcsa.DvbcsaBatchCipher`; the composition root may
    inject any :class:`ts.biss.biss1.BatchCipherBackend`).  When omitted,
    the production backend is loaded lazily at first use — DLL absence
    raises :class:`adapters.dvbcsa.DvbcsaUnavailableError` loudly there.
    """

    LAYER = "BISS"

    def __init__(
        self,
        definition,
        *,
        session_word: "str | bytes",
        pid_scope,
        backend: BatchCipherBackend | None = None,
    ) -> None:
        # Evidence-facing definition snapshot: key bodies → fingerprints
        # BEFORE any record/summary machinery can see them (SPEC-610 §9).
        super().__init__(self._redact_definition(definition))
        self._session_word = session_word
        self._pid_scope = tuple(pid_scope)
        self._backend = backend
        self._scrambled_count = 0
        self._cw = derive_cw(session_word)[1]

    @staticmethod
    def _redact_definition(definition):
        if definition.fault_type == FAULT_TYPE_BISS_KEY_MISMATCH:
            return replace(
                definition,
                parameters=redact_key_parameters(definition.parameters),
            )
        return definition

    def _ensure_backend(self) -> BatchCipherBackend:
        if self._backend is None:
            self._backend = _default_backend()
        return self._backend

    def transform(self, index: int, packet: TSPacket) -> TSPacket:
        if packet.pid not in self._pid_scope or packet.payload is None:
            return packet
        backend = self._ensure_backend()
        (encrypted,) = backend.encrypt_batch([packet.payload], self._cw)
        self._scrambled_count += 1
        scrambled = replace(
            packet,
            payload=encrypted,
            transport_scrambling_control=TSC_EVEN_KEY,
        )
        self._record(index, packet, scrambled, change="biss_payload_scramble")
        return scrambled

    def scramble_summary(self) -> dict[str, Any]:
        """The ``biss.scramble_applied`` payload (reserved emission seam,
        ruling §10-7): ``{pid_scope, packet_count, key_fingerprint,
        mutation_log_ref, mode}``.  The runtime (#128) emits it at the fault
        terminal-event seam once the run's packet count is final —
        ``mutation_log_ref`` stays ``None`` here because the artifact
        binding is a runtime concern.  The SPEC-611 §5 ``mode`` field
        (#127 additive) carries ``"1"`` for this CSA1 face; the Mode E
        transform (``faults.filters.biss_mode_e``) emits ``"E"`` plus the
        derivation-chain reference."""
        return {
            "pid_scope": sorted(self._pid_scope),
            "packet_count": self._scrambled_count,
            "key_fingerprint": key_fingerprint(self._session_word),
            "mutation_log_ref": None,
            "mode": BISS_MODE_1,
        }


class BissKeyMismatchTransform(ScramblerTransform):
    """The fault-injection path of the scrambler filter (SPEC-610 §5).

    Key source = ``BISS_KEY_MISMATCH`` ``FaultDefinition.parameters``.
    Mode 1 declares the ``wrong_session_word`` variant (12 hex chars);
    the Mode E variants (``wrong_esw`` / ``wrong_injected_id``) are
    #127's SPEC-611 domain and are refused loudly here instead of being
    silently mis-transformed (explicit dispatch per the ticket split).
    """

    def __init__(
        self,
        definition,
        *,
        backend: BatchCipherBackend | None = None,
    ) -> None:
        parameters = definition.parameters
        if "wrong_esw" in parameters or "wrong_injected_id" in parameters:
            raise NotImplementedError(
                "BISS_KEY_MISMATCH Mode E variants (wrong_esw / "
                "wrong_injected_id) are owned by ticket #127 (SPEC-611 "
                "key derivation); the Mode 1 scrambler filter (#126) "
                "implements only the wrong_session_word variant"
            )
        if "wrong_session_word" not in parameters:
            raise ValueError(
                "BISS_KEY_MISMATCH Mode 1 requires the wrong_session_word "
                "parameter (12 hex chars, SPEC-610 §5)"
            )
        pid_scope = parameters["pid_scope"]
        if not pid_scope:
            raise ValueError(
                "BISS_KEY_MISMATCH pid_scope must be a non-empty PID list "
                "(registry schema v1)"
            )
        super().__init__(
            definition,
            session_word=parameters["wrong_session_word"],
            pid_scope=pid_scope,
            backend=backend,
        )


# --- self-registration (ruling §10-4 — factory.py is never edited again) ---------

register_transform(FAULT_TYPE_BISS_KEY_MISMATCH, BissKeyMismatchTransform)
