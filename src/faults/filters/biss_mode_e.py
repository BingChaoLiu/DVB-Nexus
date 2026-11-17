"""ADR-0011 §2/§4 — the BISS Mode E face of the ``BISS_KEY_MISMATCH``
scrambler filter (SPEC-611 §7/§8, ticket #127; filter family layer=BISS).

#126's scrambler filter (:mod:`faults.filters.scrambler`) implements the
Mode 1 ``wrong_session_word`` variant and refused the Mode E variants
loudly at its explicit #127 dispatch point.  This module lands that
dispatch (SPEC-611 owns the ESW / Injected ID key derivation):

- ``BissModeEMismatchTransform`` — the fault-injection path for the
  ``wrong_esw`` / ``wrong_injected_id`` variants: the wrong key chain is
  derived through :mod:`ts.biss.mode_e` (ESW + Injected ID → session
  word → CW → CISSA key, golden-pinned) and the in-scope payload regions
  are CISSA-scrambled under it (TS 103 127 §6.3 per-packet restart, via
  :mod:`ts.biss.cissa`);
- a dispatching builder that routes ``BISS_KEY_MISMATCH`` definitions to
  the Mode E transform or back to #126's Mode 1 transform, self-registered
  via :func:`faults.factory.register_transform(..., allow_replace=True)`
  at import time (ruling §10-4 — ``factory.py`` is never edited).

Import-order invariant: this module imports
:mod:`faults.filters.scrambler` first, so #126's registration is always
in place before the dispatching builder replaces it (a plain re-import
of ``scrambler`` never re-registers — module caching).

Wrong-chain derivation (self-contained fault face): the fault parameters
carry the WRONG face(s); a face the fault does not declare pairs with the
**zero block** convention (``wrong_esw`` only ⇒ zero Injected ID;
``wrong_injected_id`` only ⇒ zero ESW; both ⇒ full wrong chain).  The
sandbox fault scrambler is definition-driven (builder takes the
definition alone, ruling §10-4), so the declared counterpart from the
scenario ``biss`` section is not available here — the zero-face
convention keeps the derivation deterministic and self-contained while
the wrong key still differs from every declared chain.  The redacted
``derivation_ref`` evidence records the whole wrong chain's fingerprints,
which is exactly what makes the two mismatch variants distinguishable
(SPEC-611 §8): a ``wrong_esw`` fault shows the ESW face fingerprint
diverging from the declared chain; a ``wrong_injected_id`` fault shows
the ID face diverging.

Key discipline (SPEC-610 §9 / SPEC-611 inherited — hard red line): key
material never enters the mutation log, journal events or artifacts.
The evidence-facing definition snapshot is redacted before any record is
produced (:func:`redact_mode_e_key_parameters` — #126's redaction
pattern with the Mode E fingerprint domain, since the shared helper
hashes the 12-hex session-word domain only); payloads carry
fingerprints and the ``mode: "E"`` / ``derivation_ref`` /
``mismatch_variants`` fields only (ruling §10-7 payload keys).

Crypto dependency: the CISSA face needs pycryptodome (lazy).  Absence
raises :class:`ts.biss.cissa.PycryptodomeUnavailableError` at transform
construction (the derivation needs DES) — the explicit SPEC-611 §8
degradation, never a silent fallback.  The payload cipher is injectable
so the filter/evidence faces stay testable without the crypto stack.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable, Mapping, Protocol

from ts.biss.biss1 import TSC_EVEN_KEY
from ts.biss.cissa import (
    BISS_MODE_E,
    encrypt_payload as _cissa_encrypt_payload,
)
from ts.biss.mode_e import (
    derive_ciss_key,
    derivation_ref,
    key_fingerprint,
    parse_esw,
    parse_injected_id,
)
from faults.filters.base import FaultTransform
from faults.filters.scrambler import BissKeyMismatchTransform
from ts.packet import TSPacket

from faults.factory import register_transform
from faults.registry import FAULT_TYPE_BISS_KEY_MISMATCH

__all__ = [
    "BissModeEMismatchTransform",
    "redact_mode_e_key_parameters",
    "build_biss_key_mismatch",
]

#: The zero-face convention blocks (see module docstring): a fault that
#: declares only one wrong face pairs it with the zero block for the
#: missing face.  Derived, not configured — the derivation_ref evidence
#: always shows the exact chain in use.
_ZERO_ESW = bytes(8)
_ZERO_INJECTED_ID = bytes(16)

#: The mode-E key-mismatch parameter keys (SPEC-204 §Phase2 item 3 /
#: SPEC-611 §5 — registry schema v1 allowed set).
_MODE_E_VARIANT_KEYS = ("wrong_esw", "wrong_injected_id")


class PayloadCipher(Protocol):
    """The injectable per-packet payload cipher seam (structural — no
    import edge).  Production: the :mod:`ts.biss.cissa` module functions
    (pycryptodome AES-128-CBC per-packet restart); tests may inject
    deterministic fakes to exercise the filter/evidence faces without
    the crypto stack."""

    def __call__(
        self, payload: bytes, ciss_key: "str | bytes"
    ) -> bytes: ...


def _derive_chain(
    chain_esw: bytes, chain_injected_id: bytes
) -> "tuple[bytes, dict[str, str]]":
    """The production wrong-chain derivation: CISSA key + redacted chain
    reference (SPEC-611 §4/§5).  Injectable as one seam so the
    filter/evidence faces stay testable without the crypto stack."""
    return (
        derive_ciss_key(chain_esw, chain_injected_id),
        derivation_ref(chain_esw, chain_injected_id),
    )


def redact_mode_e_key_parameters(
    parameters: Mapping[str, Any],
) -> dict[str, Any]:
    """Replace Mode E key-material parameter values with fingerprints.

    The redaction PATTERN is #126's
    :func:`faults.filters.scrambler.redact_key_parameters` (mutation log
    ``faults[]``/``mutations[]`` both stay clean, SPEC-610 §9) — the
    fingerprint FUNCTION is Mode E's (:mod:`ts.biss.mode_e.key_fingerprint`)
    because the #126 helper hashes the 12-hex session-word domain, which
    rejects the 16-hex ESW / 32-hex Injected ID wire shapes (SPEC-611
    §5).  Only the two Mode E variant keys are handled here; a Mode 1
    definition never reaches this transform (the dispatcher routes it to
    #126's transform and its redaction)."""
    redacted = dict(parameters)
    for key in _MODE_E_VARIANT_KEYS:
        if key in redacted:
            redacted[f"{key}_fingerprint"] = key_fingerprint(
                redacted.pop(key)
            )
    return redacted


class BissModeEMismatchTransform(FaultTransform):
    """The BISS Mode E fault-injection path (SPEC-611 §7/§8).

    Slot-preserving contract (inherited from the scrambler filter
    family): one packet in, one packet out at the same index — 188-byte
    length and packet order unchanged; in-scope payload regions are
    CISSA-scrambled under the wrong derived key and TSC-marked ``10``;
    everything else passes through untouched (等位替换 invariant holds —
    CISSA's per-packet CBC restart carries no cross-packet state).

    The evidence-facing definition snapshot is key-redacted before any
    mutation record exists; the emitted ``biss.scramble_applied`` payload
    (:meth:`scramble_summary`) adds the SPEC-611 §5 ``mode`` field and
    the redacted ``derivation_ref`` / ``mismatch_variants`` keys.
    """

    LAYER = "BISS"

    def __init__(
        self,
        definition,
        *,
        encrypt_payload: PayloadCipher | None = None,
        derive_chain: "Callable[[bytes, bytes], tuple[bytes, dict[str, str]]] | None" = None,
    ) -> None:
        # Evidence-facing definition snapshot: key bodies → fingerprints
        # BEFORE any record/summary machinery can see them (SPEC-610 §9 /
        # SPEC-611 inherited — the Mode E fingerprint domain).
        super().__init__(self._redact_definition(definition))
        parameters = definition.parameters
        wrong_esw = parameters.get("wrong_esw")
        wrong_injected_id = parameters.get("wrong_injected_id")
        if wrong_esw is None and wrong_injected_id is None:
            raise ValueError(
                "BISS_KEY_MISMATCH Mode E requires a wrong_esw and/or "
                "wrong_injected_id parameter (SPEC-611 §5)"
            )
        pid_scope = parameters.get("pid_scope")
        if not pid_scope:
            raise ValueError(
                "BISS_KEY_MISMATCH pid_scope must be a non-empty PID list "
                "(registry schema v1)"
            )
        self._encrypt = encrypt_payload or _cissa_encrypt_payload
        self._pid_scope = tuple(pid_scope)
        self._scrambled_count = 0
        # The wrong key chain (self-contained; zero-face convention).
        chain_esw = parse_esw(wrong_esw) if wrong_esw is not None else _ZERO_ESW
        chain_id = (
            parse_injected_id(wrong_injected_id)
            if wrong_injected_id is not None
            else _ZERO_INJECTED_ID
        )
        self._chain = (chain_esw, chain_id)
        # Loud, early crypto dependency face: the production derivation
        # needs DES (SPEC-611 §8 — construction failure beats mid-run
        # failure; the injectable seam keeps the evidence faces testable).
        self._ciss_key, self._derivation = (derive_chain or _derive_chain)(
            chain_esw, chain_id
        )
        self._variants = tuple(
            key for key in _MODE_E_VARIANT_KEYS if key in parameters
        )

    @staticmethod
    def _redact_definition(definition):
        if definition.fault_type == FAULT_TYPE_BISS_KEY_MISMATCH:
            return replace(
                definition,
                parameters=redact_mode_e_key_parameters(
                    definition.parameters
                ),
            )
        return definition

    def transform(self, index: int, packet: TSPacket) -> TSPacket:
        if packet.pid not in self._pid_scope or packet.payload is None:
            return packet
        encrypted = self._encrypt(packet.payload, self._ciss_key)
        self._scrambled_count += 1
        scrambled = replace(
            packet,
            payload=encrypted,
            transport_scrambling_control=TSC_EVEN_KEY,
        )
        self._record(
            index, packet, scrambled, change="biss_mode_e_payload_scramble"
        )
        return scrambled

    def scramble_summary(self) -> dict[str, Any]:
        """The ``biss.scramble_applied`` payload for the Mode E face
        (reserved emission seam, ruling §10-7): the shared scrambler keys
        plus the SPEC-611 §5 ``mode`` field and the redacted
        ``derivation_ref`` / ``mismatch_variants`` keys.  The runtime
        (#128) emits it at the fault terminal-event seam;
        ``mutation_log_ref`` stays ``None`` here (artifact binding is a
        runtime concern)."""
        return {
            "pid_scope": sorted(self._pid_scope),
            "packet_count": self._scrambled_count,
            "key_fingerprint": key_fingerprint(self._ciss_key),
            "mutation_log_ref": None,
            "mode": BISS_MODE_E,
            "derivation_ref": dict(self._derivation),
            "mismatch_variants": list(self._variants),
        }


# --- registration: the dispatching builder (ruling §10-4) -------------------------


def build_biss_key_mismatch(definition):
    """``BISS_KEY_MISMATCH`` builder: Mode E variants → the SPEC-611
    transform, Mode 1 → #126's transform.  Self-registered below with
    ``allow_replace=True`` over #126's registration (the sanctioned
    downstream-vs-downstream replacement; #126's direct-construction
    Mode E refusal stays as the class-level guard)."""
    parameters: Mapping[str, Any] = definition.parameters
    if any(key in parameters for key in _MODE_E_VARIANT_KEYS):
        return BissModeEMismatchTransform(definition)
    return BissKeyMismatchTransform(definition)


register_transform(
    FAULT_TYPE_BISS_KEY_MISMATCH,
    build_biss_key_mismatch,
    allow_replace=True,
)
