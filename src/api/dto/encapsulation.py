"""Phase 2 encapsulation wire DTOs (ticket #129).

The Pydantic mirrors of the layered pipeline's wire faces — the packet
inspector's structure views (SPEC-404 §Phase2 data source, the #128
json_map chain) and the scenario ``biss`` section (SPEC-610 §5 /
SPEC-611 §5 wire). Mirror discipline: the key sets are the LIVE
projections read verbatim — no invented keys, no dropped keys (the
round-trip unit tests validate the models against the real assemblies).

- ``T2miPacketDTO`` — the per-packet structure row (#122 wire keys
  ``packet_type/packet_counter/payload_kind/payload_bytes_len/
  crc32_valid/frame_index/plp_id`` + the ``packet_index`` transport
  locator the row carries);
- ``BBFrameDTO`` — the frozen nine-key ``BBFrame.wire_detail()`` projection
  (#123): ``matype`` is the 16-bit raw header value; ``upl``/``dfl``/
  ``syncd`` are wire BITS; ``sync`` is the raw byte value; bytes never
  enter the projection;
- ``InnerTsResultDTO`` — the frozen six-key ``InnerTsResult.wire_detail()``
  projection (#125, SPEC-603 §5);
- ``StructureViewDTO`` — the discriminated union of the three per-view
  envelopes (``view=t2mi|bbframe|ts``), the response face of the additive
  ``GET /artifacts/{id}/structure`` route;
- ``BissMode1ConfigDTO``/``BissModeEConfigDTO`` — the scenario document's
  ``biss`` section. ``simulation.scenario.schema`` owns the PARSE (the
  §10-6 ruling face); the api layer cannot import ``simulation``
  (import-linter C6), so the shapes are restated here and pinned
  identical by the field-set unit test. Wire is snake_case verbatim.

All wire faces are snake_case (SPEC-500 §5).
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "BBFrameDTO",
    "BBFrameStructureViewDTO",
    "BissMode1ConfigDTO",
    "BissModeEConfigDTO",
    "FirstFailureRefDTO",
    "InnerTsResultDTO",
    "InnerTsStructureViewDTO",
    "ReconstructionAnomalyDTO",
    "StructureViewDTO",
    "T2miPacketDTO",
    "T2miStructureViewDTO",
]


class _StrictDTO(BaseModel):
    """snake_case wire contract: extra keys are a schema violation."""

    model_config = ConfigDict(extra="forbid")


# --- T2-MI packet face (#122; the t2mi view's per-packet row) -------------------


class T2miPacketDTO(_StrictDTO):
    """One T2-MI packet row (TS 102 773 §5.1 face; #122 wire keys).

    ``payload_kind`` is the explicit MVP state vocabulary
    (``bbframe`` / ``padding`` / ``unknown`` — the #122 三态; 0xFF is the
    stuffing-byte padding identity, never silently dropped). ``frame_index``
    / ``plp_id`` are ``None`` for non-BBFRAME packets — the honest
    three-state payload discipline, never a fabricated default.
    """

    packet_index: int = Field(ge=0, description="Row locator (stream order).")
    packet_type: int = Field(ge=0, le=255, description="Header byte 0 verbatim.")
    packet_counter: int = Field(
        ge=0, le=255, description="Header byte 1 verbatim (mod-256 counter)."
    )
    payload_kind: Literal["bbframe", "padding", "unknown"]
    payload_bytes_len: int = Field(ge=0, description="Payload length in bytes.")
    crc32_valid: bool = Field(
        description="CRC-32 remainder check over header+payload."
    )
    frame_index: int | None = Field(
        default=None,
        ge=0,
        description="BBFRAME ordinal (BBFRAME packets only, else None).",
    )
    plp_id: int | None = Field(
        default=None,
        ge=0,
        le=255,
        description="Transport-prefix PLP id (BBFRAME packets only, else None).",
    )


# --- BBFrame face (#123; wire_detail() nine keys) --------------------------------


class BBFrameDTO(_StrictDTO):
    """One BBFRAME (EN 302 755 §5.1.7 face; #123 wire keys).

    Units: ``matype`` is the 16-bit raw MATYPE value; ``upl``/``dfl``/
    ``syncd`` are wire BITS (``dfl`` counts the real payload bits —
    stuffing is excluded); ``sync`` is the raw sync byte value.
    ``state`` is the #123 §8 explicit error-state vocabulary.
    """

    matype: int = Field(ge=0, le=0xFFFF, description="16-bit raw MATYPE.")
    upl: int = Field(ge=0, description="User Packet Length in bits.")
    dfl: int = Field(ge=0, description="Data Field Length in bits (real payload).")
    sync: int = Field(ge=0, le=255, description="Raw SYNC byte value.")
    syncd: int = Field(
        ge=0,
        description=(
            "Bit distance to the first UP inside the data field — "
            "NOT a sync byte (the teaching anchor, SPEC-404 §Phase2)."
        ),
    )
    crc8_valid: bool = Field(description="CRC-8 over the first 9 header bytes.")
    up_count: int = Field(ge=0, description="User packets recovered.")
    up_indices: list[int] = Field(
        default_factory=list,
        description="UP start offsets (bytes) inside the data field.",
    )
    state: str = Field(description="Explicit §8 state (ok / crc8_invalid / …).")


class BBFrameStructureRowDTO(BBFrameDTO):
    """One bbframe-view row: the caller-side ``frame_index`` + the
    nine ``wire_detail()`` keys (inheritance ADDS a field — the wire is
    the row #128 assembles)."""

    frame_index: int = Field(ge=0, description="Row locator (frame order).")


# --- Inner TS face (#125; wire_detail() six keys) ---------------------------------


class FirstFailureRefDTO(_StrictDTO):
    """The dual failure locator (SPEC-603 §5; the #104 Worker duty)."""

    frame_index: int | None = Field(
        default=None,
        ge=0,
        description="BBFrame ordinal in the selected stage (None = stream-level).",
    )
    reason: str = Field(description="The frozen reason vocabulary (SPEC-603 §5).")
    packet_position: int | None = Field(
        default=None,
        ge=0,
        description="T2-MI packet position (the t2mi-view locator, #132).",
    )


class InnerTsResultDTO(_StrictDTO):
    """The reconstructed Inner TS answer (SPEC-603 §5 six-key projection).

    ``artifact_ref`` is the lowercase SHA-256 content address of the
    reconstructed bytes (kind ``inner_ts``, SPEC-503). ``artifact_ref``
    and ``first_failure_ref`` are the consumption faces; ``reconstruction_status``
    is the closed ``ok | partial | failed`` set — a partial rebuild is
    explicit, never fabricated.
    """

    artifact_ref: str = Field(min_length=1)
    packet_count: int = Field(ge=0, description="188-byte TS packets restored.")
    up_assembled: int = Field(ge=0, description="User packets assembled.")
    stuffing_bytes: int = Field(ge=0, description="Tail stuffing bytes seen.")
    reconstruction_status: Literal["ok", "partial", "failed"]
    first_failure_ref: FirstFailureRefDTO | None = None


class ReconstructionAnomalyDTO(_StrictDTO):
    """One reconstruction discipline record (the §7 mirror face)."""

    kind: str = Field(description="The frozen anomaly reason vocabulary.")
    packet_position: int | None = Field(
        default=None, ge=0, description="T2-MI packet position (None = stream end)."
    )
    byte_size: int = Field(ge=0, description="Affected byte count.")


# --- structure view envelopes (the #128 json_map assembly faces) ------------------


class T2miStructureViewDTO(_StrictDTO):
    """``view=t2mi`` — the T2-MI layer structure (per-packet rows)."""

    view: Literal["t2mi"]
    packet_count: int = Field(ge=0)
    truncated: bool = Field(description="Stream tail cut mid-packet (honest face).")
    trailing_bytes: int = Field(ge=0, description="Verbatim-kept tail byte count.")
    packets: list[T2miPacketDTO] = Field(default_factory=list)


class BBFrameStructureViewDTO(_StrictDTO):
    """``view=bbframe`` — the BBFrame layer structure (per-frame rows)."""

    view: Literal["bbframe"]
    frame_count: int = Field(ge=0)
    frames: list[BBFrameStructureRowDTO] = Field(default_factory=list)


class InnerTsStructureViewDTO(InnerTsResultDTO):
    """``view=ts`` — the Inner TS face (default view, the demux chain).

    The view = the six-key ``InnerTsResult`` projection + the ``view``
    discriminator + the anomaly records — the flat shape #128 assembles
    (``{"view": "ts", **wire_detail(), "anomalies": [...]}``); inheritance
    ADDS fields, the wire stays flat.
    """

    view: Literal["ts"]
    anomalies: list[ReconstructionAnomalyDTO] = Field(default_factory=list)


#: The ``view``-discriminated union — the response face of
#: ``GET /artifacts/{id}/structure`` (SPEC-404 §Phase2 view parameter).
StructureViewDTO = Annotated[
    T2miStructureViewDTO | BBFrameStructureViewDTO | InnerTsStructureViewDTO,
    Field(discriminator="view"),
]


# --- biss scenario config faces (SPEC-610 §5 / SPEC-611 §5) -----------------------

#: 12-hex (48-bit session word) / 16-hex (64-bit ESW) / 32-hex (128-bit
#: Injected ID) — the schema.py wire patterns restated (C6: no simulation
#: import); the field-set unit test pins the mirror identical.
_SW_WIRE = r"^[0-9A-Fa-f]{12}$"
_ESW_WIRE = r"^[0-9A-Fa-f]{16}$"
_INJECTED_ID_WIRE = r"^[0-9A-Fa-f]{32}$"


class BissMode1ConfigDTO(_StrictDTO):
    """Scenario ``biss`` section, Mode 1 face (SPEC-610 §5).

    ``ca_pid`` is constant-semantics (BISS carries no ECM, Tech 3292) and
    defaults to 0x1FFF when the wire key is absent. The session word is
    key material: it lives in the scenario document's frozen config only
    and never enters journal events or artifacts (SPEC-610 §9).
    """

    mode: Literal["1"]
    session_word: str = Field(pattern=_SW_WIRE)
    pid_scope: list[int] = Field(min_length=1)
    ca_pid: int = Field(default=8191, description="0x1FFF constant semantics.")


class BissModeEConfigDTO(_StrictDTO):
    """Scenario ``biss`` section, Mode E face (SPEC-611 §5).

    The ESW travels out of band; the 128-bit Injected ID is statically
    provisioned in the receiver and never transmitted in the stream.
    ``ca_system_id`` defaults to 0x2602 (BISS2, Tech 3292 v3).
    """

    mode: Literal["E"]
    encrypted_sw: str = Field(pattern=_ESW_WIRE)
    injected_id: str = Field(pattern=_INJECTED_ID_WIRE)
    pid_scope: list[int] = Field(min_length=1)
    ca_pid: int = Field(default=8191, description="0x1FFF constant semantics.")
    ca_system_id: int = Field(
        default=9730, description="0x2602 constant semantics (BISS2)."
    )
