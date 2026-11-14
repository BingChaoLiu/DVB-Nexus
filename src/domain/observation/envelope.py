"""SPEC-301 — canonical event envelope models (ADR-0006 decision 1).

The authoritative envelope behind ``schemas/event-envelope.schema.json``
v1.0 (SPEC-301 sections 2/3). One envelope for TS Core, the Simulation
Engine and Observation (ADR-0005 decision 4 hub); no fourth envelope may
be invented.

Deliberate divergence from the ``DomainModel`` default (documented in
``domain._base``): the envelope layer uses ``extra="ignore"`` everywhere
(top level + producer/scope/time/correlation/timepoint) because SPEC-301
section 8 / ADR-0006 decision 4 make the envelope LOOSE — consumers MUST
ignore unknown optional fields (multi-schema-document forward
compatibility). Tightness lives in the payload: it is validated per event
type by the registry (``loose envelope, tight payload``); the payload stays
an opaque JSON object here and carries business fields such as ``source``
and ``confidence`` (ADR-0006 decision 4: never envelope fields).

journal_seq semantics (ADR-0006 decision 2, ticket-scoped to field +
validation here): the unique per-session total order is stamped by the
gateway at durable append (ticket #47 / adapters.storage owns the journal);
producers never fill it — ``ensure_publishable`` enforces the publish view.
"""

import json
import uuid
from enum import Enum
from typing import Annotated, Any, Optional

from pydantic import Field, StringConstraints, model_validator

from domain._base import DomainModel
from domain.observation.errors import EnvelopeError, EnvelopeErrorCode
from domain.observation.registry import validate_event_type, validate_payload


class Severity(str, Enum):
    """SPEC-301 section 3 severity ladder."""

    DEBUG = "debug"
    INFO = "info"
    NOTICE = "notice"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class Timepoint(DomainModel):
    """Clock reading (SPEC-301 section 3/6): value + domain + epoch.

    The envelope timepoint deliberately has NO ``semantics`` field — the
    ``source``/``observed`` field names carry the semantics (SPEC-301 §6;
    record-level timepoints elsewhere carry explicit semantics, SPEC-300 §6).
    """

    model_config = DomainModel.model_config | {"extra": "ignore"}

    value_ns: int
    clock_domain: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    clock_epoch: int = Field(ge=0)


class Time(DomainModel):
    """Dual timepoints: source clock + ingestion observation (SPEC-301 §6)."""

    model_config = DomainModel.model_config | {"extra": "ignore"}

    source: Timepoint
    observed: Timepoint


class Producer(DomainModel):
    """SPEC-301 section 3 producer block."""

    model_config = DomainModel.model_config | {"extra": "ignore"}

    producer_id: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    producer_version: str
    instance_id: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    producer_seq: Optional[int] = Field(default=None, ge=0)


class Scope(DomainModel):
    """SPEC-301 section 3 scope block.

    ``session_id`` is required as a key but nullable (system-level events
    only); ``run_id`` attributes events to the run — the event-ownership
    unit of the eight-step closed loop (ADR-0002, ADR-0006 decision 1).
    """

    model_config = DomainModel.model_config | {"extra": "ignore"}

    tenant_id: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    session_id: Optional[Annotated[str, StringConstraints(max_length=128)]] = (
        Field(...)
    )
    run_id: Optional[Annotated[str, StringConstraints(max_length=128)]] = None
    scenario_id: Optional[Annotated[str, StringConstraints(max_length=128)]] = (
        None
    )


class Correlation(DomainModel):
    """SPEC-301 section 3 correlation block; all fields nullable/optional.

    Target addressing dual form (ADR-0006 decision 3): ``node_id`` alone =
    node level (state surface); ``node_id`` + ``pid`` = stream level
    (SIM_TS, pid 0..8191). ``port_id`` addresses ports (ADR-0005 decision 5,
    multi-port Mux).
    """

    model_config = DomainModel.model_config | {"extra": "ignore"}

    trace_id: Optional[str] = None
    span_id: Optional[str] = None
    parent_event_id: Optional[str] = None
    fault_id: Optional[str] = None
    node_id: Optional[str] = None
    port_id: Optional[str] = None
    service_id: Optional[str] = None
    pid: Optional[int] = Field(default=None, ge=0, le=8191)


class EventEnvelope(DomainModel):
    """The canonical envelope (SPEC-301 sections 2/3, schema v1.0)."""

    model_config = DomainModel.model_config | {"extra": "ignore"}

    schema_version: str
    event_id: Annotated[str, StringConstraints(min_length=8, max_length=128)]
    event_type: str
    producer: Producer
    scope: Scope
    time: Time
    correlation: Optional[Correlation] = None
    severity: Severity
    payload: dict[str, Any]
    tags: Annotated[
        list[Annotated[str, StringConstraints(max_length=64)]],
        Field(max_length=32),
    ]
    journal_seq: Optional[int] = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _validate_contract(self) -> "EventEnvelope":
        # Multi-schema-document policy (SPEC-301 section 8 / ADR-0006
        # decision 4): this model implements exactly the 1.0 document
        # (const); a 1.1 is a NEW schema document with a new $id; a major
        # bump is breaking and refused.
        if self.schema_version != "1.0":
            raise EnvelopeError(
                EnvelopeErrorCode.OBS_UNSUPPORTED_SCHEMA,
                f"unsupported schema_version {self.schema_version!r}: this "
                "document implements 1.0 only (SPEC-301 section 8)",
            )
        validate_event_type(self.event_type)
        validate_payload(self.event_type, self.payload)
        _validate_payload_size(self.payload)
        _validate_payload_secrets(self.payload)
        return self

    @property
    def dedup_key(self) -> tuple[str, str]:
        """At-least-once dedup key (SPEC-301 section 5)."""
        return (self.producer.producer_id, self.event_id)

    def ensure_publishable(self) -> None:
        """Producer publish view: journal_seq must be absent.

        ``journal_seq`` is stamped by the gateway at durable append
        (per session monotonic, ADR-0006 decision 2); a producer that fills
        it is manufacturing a total order and is refused (ticket #47 owns
        the stamping itself).
        """
        if self.journal_seq is not None:
            raise EnvelopeError(
                EnvelopeErrorCode.OBS_INVALID_ENVELOPE,
                "producers never fill journal_seq — it is gateway-stamped "
                "at durable append (ADR-0006 decision 2)",
            )


# --- payload policy (SPEC-301 section 7) -------------------------------------

#: Serialized payload default cap (256 KiB).
PAYLOAD_MAX_BYTES = 256 * 1024

#: Payload key tokens that always indicate forbidden key material
#: (secrets/BISS keys/credentials/private keys, SPEC-301 section 7).
_SECRET_TOKENS = frozenset(
    {
        "secret",
        "password",
        "passwd",
        "credential",
        "credentials",
        "token",
        "apikey",
        "privatekey",
        "biss",
    }
)

#: A bare ``key`` token is only suspicious combined with one of these
#: (``keyframe_count`` stays legal; ``api_key``/``private_key`` do not).
_KEY_COMPOUND_TRIGGERS = frozenset({"api", "private", "biss", "access", "encrypt"})


def _key_tokens(name: str) -> set[str]:
    # camelCase/snake_case/kebab-case all degrade to lowercase word tokens.
    tokens = {part.lower() for part in _split_words(name)}
    return tokens


def _split_words(name: str) -> list[str]:
    current: list[str] = []
    words: list[str] = []
    for char in name:
        if char.isalnum():
            current.append(char.lower())
        else:
            if current:
                words.append("".join(current))
                current = []
    if current:
        words.append("".join(current))
    return words


def _validate_payload_size(payload: dict[str, Any]) -> None:
    serialized = json.dumps(payload, ensure_ascii=False, default=str)
    size = len(serialized.encode("utf-8"))
    if size > PAYLOAD_MAX_BYTES:
        raise EnvelopeError(
            EnvelopeErrorCode.OBS_PAYLOAD_TOO_LARGE,
            f"serialized payload is {size} bytes, above the "
            f"{PAYLOAD_MAX_BYTES} byte cap (SPEC-301 section 7); binary "
            "data belongs in artifact storage behind a scoped content id",
        )


def _validate_payload_secrets(payload: Any) -> None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            _check_key(str(key))
            _validate_payload_secrets(value)
    elif isinstance(payload, (list, tuple)):
        for item in payload:
            _validate_payload_secrets(item)


def _check_key(name: str) -> None:
    tokens = _key_tokens(name)
    if tokens & _SECRET_TOKENS:
        raise EnvelopeError(
            EnvelopeErrorCode.OBS_INVALID_ENVELOPE,
            f"payload key {name!r} looks like secret material — keys, BISS "
            "keys, credentials and private keys are banned from payloads "
            "(SPEC-301 section 7)",
        )
    if "key" in tokens and tokens & _KEY_COMPOUND_TRIGGERS:
        raise EnvelopeError(
            EnvelopeErrorCode.OBS_INVALID_ENVELOPE,
            f"payload key {name!r} looks like secret material — keys, BISS "
            "keys, credentials and private keys are banned from payloads "
            "(SPEC-301 section 7)",
        )


def parse_envelope(raw: Any) -> EventEnvelope:
    """Parse a wire document into the canonical envelope.

    Structural violations (missing required fields, wrong types) and
    contract violations (registry, payload policy, schema version) both
    surface as :class:`EnvelopeError` with a SPEC-300 section 13 code —
    producers receive structured errors, never a raw validation dump
    (SPEC-301 section 9).
    """
    try:
        return EventEnvelope.model_validate(raw)
    except EnvelopeError:
        raise
    except Exception as exc:  # pydantic ValidationError on this path
        raise EnvelopeError(
            EnvelopeErrorCode.OBS_INVALID_ENVELOPE,
            f"malformed event envelope (SPEC-301 sections 3/9): {exc}",
        ) from exc


def new_event_id() -> str:
    """uuid4 opaque event ID (ADR-0006 decision 3; ULID retired).

    Producers generate the ID before first publish and reuse it on retry
    (at-least-once dedup half of ``(producer_id, event_id)``).
    """
    return str(uuid.uuid4())


__all__ = [
    "PAYLOAD_MAX_BYTES",
    "Correlation",
    "EventEnvelope",
    "Producer",
    "Scope",
    "Severity",
    "Time",
    "Timepoint",
    "new_event_id",
    "parse_envelope",
]
