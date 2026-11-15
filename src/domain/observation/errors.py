"""SPEC-301 section 9 structured envelope errors (SPEC-300 section 13 codes).

Malformed events are refused before journal submission and producers receive
a structured error carrying one of the canonical codes. The vocabulary lives
in ``domain.observation`` because the envelope contract is the unified
exchange interface (ADR-0005 decision 4); ``OBS_DUPLICATE_EVENT`` itself is
raised by the durable-append layer (ticket #47 / adapters.storage) — it is
declared here so every producer shares one error vocabulary.
"""

from enum import Enum


class EnvelopeErrorCode(str, Enum):
    """Structured rejection codes (SPEC-301 section 9, SPEC-300 section 13).

    Member names equal the canonical code strings so ``code.value`` and the
    name agree (structured payloads carry the ``OBS_*`` string).
    """

    #: Envelope structure, registry or payload-schema violation.
    OBS_INVALID_ENVELOPE = "OBS_INVALID_ENVELOPE"
    #: schema_version outside the supported document family (SPEC-301 §8).
    OBS_UNSUPPORTED_SCHEMA = "OBS_UNSUPPORTED_SCHEMA"
    #: Serialized payload above the 256 KiB default cap (SPEC-301 §7).
    OBS_PAYLOAD_TOO_LARGE = "OBS_PAYLOAD_TOO_LARGE"
    #: Duplicate (producer_id, event_id) on retry — journal append layer
    #: answers with the original journal_seq (SPEC-301 §5, ticket #47).
    OBS_DUPLICATE_EVENT = "OBS_DUPLICATE_EVENT"
    #: Comparison/arithmetic across clock domains refused (SPEC-300 §6
    #: rules 1/3, REQ-OBS-300-004); raised by the time-domain guard
    #: (``domain.observation.time_domain``) that M4 SPEC-302/303 wiring
    #: binds to — declared here so every consumer shares one vocabulary.
    OBS_INVALID_TIME_DOMAIN = "OBS_INVALID_TIME_DOMAIN"


class EnvelopeError(Exception):
    """Structured error for envelope contract violations (SPEC-301 §9)."""

    def __init__(self, code: EnvelopeErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code

    def __str__(self) -> str:  # pragma: no cover - trivial formatting
        return f"[{self.code.value}] {super().__str__()}"


__all__ = ["EnvelopeError", "EnvelopeErrorCode"]
