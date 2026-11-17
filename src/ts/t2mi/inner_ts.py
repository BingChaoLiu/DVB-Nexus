"""SPEC-603 §5/§6/§7/§8 — Inner TS reconstruction (ticket #125).

``reconstruct(frames, plp_filter) -> InnerTsResult``: the deterministic
UP-reassembly end of the three-level demux chain (outer TS → SPEC-600
parse → SPEC-601 parse → SPEC-602 filter → *this* reconstruction →
Inner TS, SPEC-603 §4).

Input contract (pinned for #128/#129): ``frames`` is the demux-side
**T2-MI packet sequence** — the :func:`ts.t2mi.parser.parse` output
(face of the #122 parse).  The SPEC-603 §6 pseudonym ``frames`` refers
to the BBFRAME-carrying packets at that level; pinning the packet level
(highest input granularity) is what makes the two §7 duties expressible
*inside* the reconstruction:

- the back-to-back-discipline **consumption-side mirror**: a padding /
  unknown T2-MI packet between BBFRAME packets is explicit anomaly
  evidence (the construction side refuses to produce it — #122
  ``inter_frame_padding`` refusal; the parse side never silently
  consumes it — #104 demux-stall lesson);
- the PLP selection (SPEC-602) can be applied internally from the
  transport prefix, or externally via :func:`ts.t2mi.plp.filter` — both
  paths are first-class and agree byte-for-byte.

UP assembly (§7): per frame the trusted BBHEADER (CRC-8 mandatory,
#123) locates the first UP at ``SYNCD // 8``; the bytes before it, and
a ``SYNCD=0xFFFF`` continuation frame's whole declared field, are the
**carry-over** of the partial UP from the previous frame (the
SYNCD-carry-over semantics — SPEC-603 §3).  Complete UPs are extracted
from the carry buffer and restored to TS packets: HEM UPs (187 bytes,
sync stripped) regain the header's SYNC byte; NM UPs (188 transmitted
bytes: per-UP CRC-8 + 187 body, §5.1.8) regain the SYNC byte in place
of the CRC-8.  The SYNC source of truth is the frame's own BBHEADER
field, never a hardcoded constant.  Tail-frame ``0xFF`` baseband
stuffing (DFL declares real payload only, SPEC-601 §7) is skipped and
*counted* (``stuffing_bytes``), never emitted.

Degradation faces (§8 — explicit states, never silent):

- a frame whose UP boundary is not derivable (``crc8_invalid`` /
  ``malformed_short`` / ``matype_unsupported`` / ``upl_invalid`` /
  ``dfl_mismatch`` / ``syncd_out_of_range`` / ``syncd_misaligned``) is
  refused whole (its header is untrusted) and recorded;
- ``reconstruction_status`` = ``ok`` (every UP recovered, no leftover) /
  ``partial`` (some UPs recovered, at least one recorded loss) /
  ``failed`` (nothing recovered); the first loss is located by
  ``first_failure_ref`` — the #104 Worker content-validation duty,
  contractualised: consumers of a ``partial`` stream MUST content-check;
- an incomplete trailing UP (stream cut mid-packet) and orphan
  carry-over bytes (continuation with nothing pending) are recorded
  losses, not fabricated bytes;
- NPD-marked and ISSY-marked frames are refused with an explicit
  progressive-boundary reason (null-packet re-insertion / ISSY sizing
  are not registered — emitting the stream without them would be the
  silent-falsification face);
- expected-mode PLP selection matching zero packets → the explicit
  empty ``failed`` face (缺失 ≠ 零, SPEC-602 承接 — the
  ``t2mi.plp_mismatch`` candidate travels on the injected ``emitter``
  when the selection happens here).

Output faces: ``inner_ts`` (implementation bytes face — artifact
addressed, never wire-projected), ``artifact_ref`` = the SHA-256
content address of those bytes (the SPEC-503 identity: landing the
artifact through ``adapters.storage.ArtifactStore.store_bytes(bytes,
ext="ts")`` converges on exactly this address; index registration with
``kind=inner_ts`` happens at the composition layers, #128) and
``wire_detail()`` — the frozen six-key wire projection (#129 mirrors it
verbatim into ``InnerTsResultDTO``).  This module carries the ts-side
``inner_ts`` kind *string*; ``ts`` imports no other project package
(ts purity, ADR-0005), so the domain enum mirrors the constant, not the
reverse.

Second-opinion protocol (§6): ``verify_against_tsduck(inner_artifact,
tsduck_extract_output)`` is the pure byte-level diff + trust annotation
half of the L2 record (SPEC-506 机制); running ``tsp`` belongs to the
caller (tsduck-marked tests / the adapter layer).  **NOT TRUSTED is the
default state** (ruling §10-9): the NM/ISSY/NPD demux fix (TSDuck
master commit 147deab3, 2026-11-09) is unreleased, so the
:data:`TSDUCK_TRUSTED_VERSIONS` registry is empty and every record
carries ``trust_annotation="NOT TRUSTED"`` until an official release
passes the §5.3 retest matrix and is added there.

Error codes owned here (module-owned per contract §7 归属约定):
``INNER_TS_TSDUCK_VERSION_INVALID`` — the only prepare-time exception;
every reconstruction degradation is a *state* on the result.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from ts._bytesutil import _coerce_bytes
from ts.t2mi.bbframe import (
    BBFRAME_STATE_OK,
    BBFRAME_SYNCD_CONTINUATION,
    BBFrame,
    parse as bbframe_parse,
)
from ts.t2mi.errors import T2miError
from ts.t2mi.packet import (
    PAYLOAD_KIND_BBFRAME,
    PAYLOAD_KIND_PADDING,
    PAYLOAD_KIND_UNKNOWN,
    T2miPacket,
)
from ts.t2mi.plp import (
    PlpFilterConfig,
    PlpMismatchEmitter,
    collect_plp_mismatch,
    emit_plp_mismatch,
)

__all__ = [
    "FIRST_FAILURE_REF_KEYS",
    "INNER_TS_ARTIFACT_KIND",
    "INNER_TS_TSDUCK_VERSION_INVALID",
    "INNER_TS_WIRE_KEYS",
    "REASON_INCOMPLETE_TRAILING_UP",
    "REASON_ISSY_UNSUPPORTED",
    "REASON_NO_BBFRAME_PACKETS",
    "REASON_NPD_REINSERTION_UNSUPPORTED",
    "REASON_ORPHAN_CARRYOVER_BYTES",
    "REASON_PACKET_PAYLOAD_SHORT",
    "REASON_PLP_FILTER_MATCHED_ZERO",
    "REASON_UP_SIZE_CHANGED",
    "REASON_UP_SIZE_NOT_TS",
    "RECONSTRUCTION_STATUS_FAILED",
    "RECONSTRUCTION_STATUS_OK",
    "RECONSTRUCTION_STATUS_PARTIAL",
    "TSDUCK_TRUSTED_VERSIONS",
    "TSDUCK_TRUST_ANNOTATION_NOT_TRUSTED",
    "TSDUCK_TRUST_ANNOTATION_TRUSTED",
    "VERIFY_RECORD_KEYS",
    "InnerTsResult",
    "reconstruct",
    "verify_against_tsduck",
]

# --- error codes owned by this module ----------------------------------------------

INNER_TS_TSDUCK_VERSION_INVALID = "INNER_TS_TSDUCK_VERSION_INVALID"

# --- SPEC-603 §5 wire face ----------------------------------------------------------

#: Frozen wire keys of the ``InnerTsResultDTO`` projection (#129 mirrors
#: these verbatim; SPEC-603 §5).
INNER_TS_WIRE_KEYS: frozenset[str] = frozenset(
    {
        "artifact_ref",
        "packet_count",
        "up_assembled",
        "stuffing_bytes",
        "reconstruction_status",
        "first_failure_ref",
    }
)

#: The artifact kind string for the reconstructed stream (SPEC-603 §5
#: ``kind=inner_ts``; the domain ``ArtifactKind`` enum mirrors this —
#: ts purity keeps the import direction one-way).
INNER_TS_ARTIFACT_KIND = "inner_ts"

#: ``reconstruction_status`` closed set (SPEC-603 §5).
RECONSTRUCTION_STATUS_OK = "ok"
RECONSTRUCTION_STATUS_PARTIAL = "partial"
RECONSTRUCTION_STATUS_FAILED = "failed"

#: Frozen ``first_failure_ref`` keys — the dual locator: ``frame_index``
#: is the BBFrame ordinal inside the (selected) frame stage (the
#: ``bbframe.*`` event convention, correlated with
#: ``bbframe.recovery_failed``), ``packet_position`` is the index into
#: the caller's ``frames`` sequence (the T2-MI view locator, #132).
FIRST_FAILURE_REF_KEYS: frozenset[str] = frozenset(
    {"frame_index", "reason", "packet_position"}
)

# --- first_failure_ref / anomaly reason vocabulary -----------------------------------
# Frame-level reasons reuse the #123 explicit-state strings verbatim
# (crc8_invalid / malformed_short / matype_unsupported / upl_invalid /
# dfl_mismatch / syncd_out_of_range / syncd_misaligned) — 回到既有语义域.

#: Stream cut mid-UP with no continuation frame left.
REASON_INCOMPLETE_TRAILING_UP = "incomplete_trailing_up"
#: Continuation bytes (pre-first-UP region or 0xFFFF field) with no
#: pending partial UP — the data belongs to nothing derivable.
REASON_ORPHAN_CARRYOVER_BYTES = "orphan_carryover_bytes"
#: A frame's transmitted UP size disagrees with the established stream
#: grammar — boundary math would be a guess, so the frame is refused.
REASON_UP_SIZE_CHANGED = "up_size_changed"
#: Restored UPs would not form a 188-byte-aligned TS stream
#: (SPEC-603 §2.1: 188 对齐字节流).
REASON_UP_SIZE_NOT_TS = "up_size_not_ts"
#: Null packets were deleted upstream (NPD); re-insertion is not
#: registered, so the pre-deletion stream is not reconstructible here.
REASON_NPD_REINSERTION_UNSUPPORTED = "npd_reinsertion_unsupported"
#: ISSY-marked frame — per-UP ISSY sizing is not registered.
REASON_ISSY_UNSUPPORTED = "issy_unsupported"
#: BBFRAME-type packet whose payload cannot even hold the transport prefix.
REASON_PACKET_PAYLOAD_SHORT = "packet_payload_short"
#: Expected-mode PLP selection matched zero packets (B1, 缺失 ≠ 零).
REASON_PLP_FILTER_MATCHED_ZERO = "plp_filter_matched_zero_packets"
#: No BBFRAME packet reached the assembly at all.
REASON_NO_BBFRAME_PACKETS = "no_bbframe_packets"

# --- anomaly kinds (§7 mirror face) --------------------------------------------------

_KIND_PADDING_BETWEEN_FRAMES = "padding_between_frames"
_KIND_UNKNOWN_PACKET_BETWEEN_FRAMES = "unknown_packet_between_frames"

#: The restored TS packet size (SPEC-603 §2.1: 188 对齐字节流).
_TS_PACKET_BYTES = 188

#: HEM transmitted UP size (sync stripped; NPD frames are refused above).
_HEM_UP_BYTES = 187

# --- L2 second-opinion trust faces (ruling §10-9) ------------------------------------

#: TSDuck releases whose ``t2mi`` extract is trusted for the L2
#: byte-diff record.  **Empty by design**: the NM/ISSY/NPD demux rewrite
#: (master commit 147deab3, 2026-11-09) is unreleased — 3.45-4798
#: silently drops multi-UP tails and fails Normal Mode (#104/#105
#: measured, research-branch evidence).  A version lands here only
#: after the official release passes the §5.3 retest matrix.  Until
#: then every record is annotated NOT TRUSTED — the annotation logic is
#: in place; the trusted set is honestly empty (SPEC-603 §8 row 4).
TSDUCK_TRUSTED_VERSIONS: frozenset[str] = frozenset()

#: Frozen ``verify_against_tsduck`` record keys (the L2 record shape).
VERIFY_RECORD_KEYS: frozenset[str] = frozenset(
    {
        "match",
        "first_diff_offset",
        "prefix_match_bytes",
        "inner_byte_size",
        "tsduck_byte_size",
        "trusted",
        "trust_annotation",
        "tsduck_version",
        "not_trusted_reason",
    }
)

#: Wire annotation strings (rendered verbatim by consumers).
TSDUCK_TRUST_ANNOTATION_TRUSTED = "TRUSTED"
TSDUCK_TRUST_ANNOTATION_NOT_TRUSTED = "NOT TRUSTED"

_NOT_TRUSTED_REASON_UNATTESTED = "tsduck_version_not_attested"
_NOT_TRUSTED_REASON_UNREGISTERED = "tsduck_version_not_in_trusted_registry"

_TSDUCK_VERSION_PATTERN = re.compile(r"^\d+\.\d+-\d+$")


# --- result object -------------------------------------------------------------------


@dataclass(frozen=True)
class InnerTsResult:
    """The SPEC-603 §5 result (wire keys frozen; bytes face separate).

    Wire projection (:meth:`wire_detail` — #129's ``InnerTsResultDTO``
    mirrors these keys verbatim): ``artifact_ref / packet_count /
    up_assembled / stuffing_bytes / reconstruction_status /
    first_failure_ref``.  ``artifact_ref`` is the lowercase SHA-256 hex
    of :attr:`inner_ts` — the SPEC-503 content address; ``inner_ts`` and
    ``anomalies`` are implementation faces and stay out of the wire
    projection (bytes are artifact-addressed, SPEC-600 §5 discipline).

    ``first_failure_ref`` carries exactly :data:`FIRST_FAILURE_REF_KEYS`
    (or ``None`` on ``ok``): ``reason`` reuses the #123 frame-state
    strings for frame-level losses and the module reason vocabulary
    otherwise.  ``anomalies`` records uniform
    ``{kind, packet_position, byte_size}`` evidence rows (§7 mirror
    face).  Consumers of a ``partial`` result MUST content-validate the
    bytes (#104 lesson, contractualised).
    """

    artifact_ref: str
    packet_count: int
    up_assembled: int
    stuffing_bytes: int
    reconstruction_status: str
    first_failure_ref: Mapping[str, Any] | None
    inner_ts: bytes = field(default=b"", repr=False)
    anomalies: tuple[Mapping[str, Any], ...] = field(default=(), repr=False)

    def wire_detail(self) -> dict[str, Any]:
        """The frozen six-key wire projection (SPEC-603 §5)."""
        return {
            "artifact_ref": self.artifact_ref,
            "packet_count": self.packet_count,
            "up_assembled": self.up_assembled,
            "stuffing_bytes": self.stuffing_bytes,
            "reconstruction_status": self.reconstruction_status,
            "first_failure_ref": (
                dict(self.first_failure_ref) if self.first_failure_ref else None
            ),
        }


# --- reconstruction -------------------------------------------------------------------


def _frame_up_size(frame: BBFrame) -> int:
    """Transmitted UP size in bytes for a trusted header (0 = undeterminable).

    HEM: 187-byte sync-stripped UPs (NPD frames are refused before this
    point, so no DNP byte lands here).  NM: the BBHEADER UPL in bytes.
    """
    if frame.mode == "hem":
        return _HEM_UP_BYTES
    if frame.mode == "nm":
        return frame.upl // 8 if frame.upl % 8 == 0 and frame.upl >= 8 else 0
    return 0


def _restore_up(frame: BBFrame, up: bytes) -> bytes:
    """Restore one transmitted UP to its 188-byte TS packet form.

    HEM: the sync byte was stripped — prepend the BBHEADER's SYNC byte.
    NM: the sync byte was replaced by the per-UP CRC-8 (§5.1.8) — put
    the BBHEADER's SYNC byte back in its place.
    """
    if frame.mode == "nm":
        return bytes([frame.sync]) + up[1:]
    return bytes([frame.sync]) + up


def _failure(frame_index: int | None, reason: str, packet_position: int | None) -> dict:
    return {
        "frame_index": frame_index,
        "reason": reason,
        "packet_position": packet_position,
    }


def _empty_face(reason: str) -> InnerTsResult:
    """The explicit empty failed face (§8): nothing fabricated."""
    empty = b""
    return InnerTsResult(
        artifact_ref=hashlib.sha256(empty).hexdigest(),
        packet_count=0,
        up_assembled=0,
        stuffing_bytes=0,
        reconstruction_status=RECONSTRUCTION_STATUS_FAILED,
        first_failure_ref=_failure(None, reason, None),
        inner_ts=empty,
        anomalies=(),
    )


def reconstruct(
    frames: Sequence[T2miPacket],
    plp_filter: PlpFilterConfig | None = None,
    *,
    emitter: PlpMismatchEmitter | None = None,
) -> InnerTsResult:
    """Reassemble the Inner TS from the demux-side packet sequence (§6/§7).

    Args:
        frames: the T2-MI packet sequence (:func:`ts.t2mi.parser.parse`
            output).  BBFRAME-kind packets carry the assembly; padding /
            unknown packets between them are recorded discipline
            evidence and never consumed.
        plp_filter: optional demux-side filter config (SPEC-602).  When
            expected-mode, the selection is applied here; zero matches
            produce the explicit empty failed face plus the
            ``t2mi.plp_mismatch`` candidate on ``emitter`` (SPEC-602
            承接).  Callers that pre-filter with
            :func:`ts.t2mi.plp.filter` pass ``None`` (or ``mode="all"``)
            — both paths agree byte-for-byte.
        emitter: the reserved §10-7 seam ``(event_type, payload) ->
            None``; fires exactly once, and only when this call performed
            an expected-mode selection that matched zero packets.

    Returns:
        :class:`InnerTsResult` — deterministic: same input → equal wire
        face, equal bytes, equal evidence (§7 拼装确定性).
    """
    selected: tuple[T2miPacket, ...] = tuple(frames)
    if plp_filter is not None and plp_filter.mode == "expected":
        expected = plp_filter.expected_plp
        assert expected is not None  # construction-time validated (SPEC-602)
        selected = tuple(
            packet
            for packet in selected
            if packet.payload_kind == PAYLOAD_KIND_BBFRAME and packet.plp_id == expected
        )
        if not selected:
            if emitter is not None:
                payload = collect_plp_mismatch(frames, plp_filter)
                if payload is not None:
                    emit_plp_mismatch(emitter, payload)
            return _empty_face(REASON_PLP_FILTER_MATCHED_ZERO)

    # --- packet walk: BBFRAME blobs + discipline evidence -------------------
    frame_blobs: list[bytes] = []
    frame_positions: list[int] = []
    anomalies: list[dict[str, Any]] = []
    for position, packet in enumerate(selected):
        kind = packet.payload_kind
        if kind == PAYLOAD_KIND_BBFRAME:
            blob = packet.bbframe
            if blob is None:
                anomalies.append(
                    {
                        "kind": REASON_PACKET_PAYLOAD_SHORT,
                        "packet_position": position,
                        "byte_size": len(packet.payload),
                    }
                )
                continue
            frame_blobs.append(blob)
            frame_positions.append(position)
        elif kind == PAYLOAD_KIND_PADDING:
            anomalies.append(
                {
                    "kind": _KIND_PADDING_BETWEEN_FRAMES,
                    "packet_position": position,
                    "byte_size": len(packet.payload),
                }
            )
        elif kind == PAYLOAD_KIND_UNKNOWN:
            anomalies.append(
                {
                    "kind": _KIND_UNKNOWN_PACKET_BETWEEN_FRAMES,
                    "packet_position": position,
                    "byte_size": len(packet.payload),
                }
            )
    if not frame_blobs:
        return _empty_face(REASON_NO_BBFRAME_PACKETS)

    # --- UP assembly with SYNCD carry-over (§7) ------------------------------
    parsed = bbframe_parse(frame_blobs)
    buffer = bytearray()
    emitted: list[bytes] = []
    failures: list[dict[str, Any]] = []
    stuffing_total = 0
    established_up_size: int | None = None

    for stage, frame in enumerate(parsed):
        position = frame_positions[stage]
        if frame.state != BBFRAME_STATE_OK:
            # Untrusted header → UP boundaries not derivable → the frame
            # is refused whole and recorded (§8; nothing silently skipped).
            failures.append(_failure(stage, frame.state, position))
            continue
        stuffing_total += frame.stuffing_bytes
        if frame.npd_enabled:
            failures.append(_failure(stage, REASON_NPD_REINSERTION_UNSUPPORTED, position))
            continue
        if frame.issy_present:
            failures.append(_failure(stage, REASON_ISSY_UNSUPPORTED, position))
            continue
        up_size = _frame_up_size(frame)
        if frame.mode == "nm" and up_size != _TS_PACKET_BYTES:
            # Restored stream would break the 188-byte alignment face.
            failures.append(_failure(stage, REASON_UP_SIZE_NOT_TS, position))
            continue
        if up_size == 0:
            failures.append(_failure(stage, REASON_UP_SIZE_NOT_TS, position))
            continue
        if established_up_size is None:
            established_up_size = up_size
        elif up_size != established_up_size:
            failures.append(_failure(stage, REASON_UP_SIZE_CHANGED, position))
            continue

        dfl_bytes = frame.dfl_bytes
        if frame.syncd == BBFRAME_SYNCD_CONTINUATION:
            # 0xFFFF: the whole declared field continues the pending UP;
            # no UP starts in this frame.
            continuation_bytes = dfl_bytes
            up_region: bytes = b""
        else:
            # Byte-aligned (state ok ⇒ SYNCD is a whole byte multiple).
            continuation_bytes = frame.syncd // 8
            up_region = frame.data_field[continuation_bytes:dfl_bytes]

        if buffer:
            # The pre-first-UP region (or the whole 0xFFFF field) continues
            # the pending partial UP — the SYNCD carry-over semantics.
            buffer += frame.data_field[: min(continuation_bytes, dfl_bytes)]
        elif continuation_bytes:
            # Carry-over with nothing pending: the bytes belong to no
            # derivable UP — recorded loss, dropped, never fabricated.
            anomalies.append(
                {
                    "kind": REASON_ORPHAN_CARRYOVER_BYTES,
                    "packet_position": position,
                    "byte_size": min(continuation_bytes, dfl_bytes),
                }
            )
            failures.append(_failure(stage, REASON_ORPHAN_CARRYOVER_BYTES, position))
        buffer += up_region
        assert established_up_size is not None
        while len(buffer) >= established_up_size:
            up = bytes(buffer[:established_up_size])
            del buffer[:established_up_size]
            emitted.append(_restore_up(frame, up))

    if buffer:
        # Stream end with a partial UP pending — recorded, not fabricated.
        failures.append(_failure(None, REASON_INCOMPLETE_TRAILING_UP, None))
        anomalies.append(
            {
                "kind": REASON_INCOMPLETE_TRAILING_UP,
                "packet_position": None,
                "byte_size": len(buffer),
            }
        )

    inner_ts = b"".join(emitted)
    if failures or buffer:
        status = (
            RECONSTRUCTION_STATUS_PARTIAL if emitted else RECONSTRUCTION_STATUS_FAILED
        )
    else:
        status = RECONSTRUCTION_STATUS_OK
    return InnerTsResult(
        artifact_ref=hashlib.sha256(inner_ts).hexdigest(),
        packet_count=len(emitted),
        up_assembled=len(emitted),
        stuffing_bytes=stuffing_total,
        reconstruction_status=status,
        first_failure_ref=failures[0] if failures else None,
        inner_ts=inner_ts,
        anomalies=tuple(anomalies),
    )


# --- L2 second-opinion diff (§6; pure half — tsp belongs to the caller) ---------------


def verify_against_tsduck(
    inner_artifact: bytes,
    tsduck_extract_output: bytes,
    *,
    tsduck_version: str | None = None,
) -> dict[str, Any]:
    """Byte-level diff of the two streams + NOT TRUSTED annotation (§6/§8).

    The pure, deterministic half of the L2 second-opinion record
    (SPEC-506 机制): ``inner_artifact`` is the reconstruction output,
    ``tsduck_extract_output`` the ``tsp -P t2mi --extract`` output the
    caller captured.  ``tsduck_version`` attests the producing release
    (``\\d+\\.\\d+-\\d+`` house shape); a malformed version refuses
    before the diff (:class:`ts.t2mi.errors.T2miError`), an absent
    version is honest unattested evidence.

    Trust semantics (ruling §10-9, SPEC-603 §8 row 4): ``trusted=True``
    requires the attested version to be in
    :data:`TSDUCK_TRUSTED_VERSIONS` — empty today (master 147deab3
    unreleased), so every current record is annotated ``NOT TRUSTED``.
    The record carries exactly :data:`VERIFY_RECORD_KEYS`.
    """
    inner = _coerce_bytes(inner_artifact, param="inner_artifact")
    tsduck_out = _coerce_bytes(tsduck_extract_output, param="tsduck_extract_output")

    version: str | None = None
    if tsduck_version is not None:
        candidate = str(tsduck_version)
        if not _TSDUCK_VERSION_PATTERN.match(candidate):
            raise T2miError(
                f"{INNER_TS_TSDUCK_VERSION_INVALID}: tsduck_version "
                f"{candidate!r} is not a release token of the shape "
                "'<major>.<minor>-<build>' (house env shape discipline)"
            )
        version = candidate

    trusted = version is not None and version in TSDUCK_TRUSTED_VERSIONS
    if trusted:
        annotation = TSDUCK_TRUST_ANNOTATION_TRUSTED
        not_trusted_reason: str | None = None
    else:
        annotation = TSDUCK_TRUST_ANNOTATION_NOT_TRUSTED
        not_trusted_reason = (
            _NOT_TRUSTED_REASON_UNATTESTED
            if version is None
            else _NOT_TRUSTED_REASON_UNREGISTERED
        )

    common = min(len(inner), len(tsduck_out))
    first_diff: int | None = None
    for offset in range(common):
        if inner[offset] != tsduck_out[offset]:
            first_diff = offset
            break
    if first_diff is None and len(inner) != len(tsduck_out):
        # One stream is a byte-prefix of the other: the EOF point is the
        # first difference (the shorter stream ends there).
        first_diff = common
    match = first_diff is None
    return {
        "match": match,
        "first_diff_offset": first_diff,
        "prefix_match_bytes": first_diff if first_diff is not None else common,
        "inner_byte_size": len(inner),
        "tsduck_byte_size": len(tsduck_out),
        "trusted": trusted,
        "trust_annotation": annotation,
        "tsduck_version": version,
        "not_trusted_reason": not_trusted_reason,
    }
