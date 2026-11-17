"""SPEC-204 §Phase2 item 2 / SPEC-601 §4 — BBHEADER_SYNC_FAULT transform.

The real BBFRAME-layer filter for the B2 primitive (ticket #123), self-
registered per orchestrator ruling §10-4: importing this module binds
:class:`BBHeaderSyncFaultTransform` into
:func:`faults.factory.transform_builder_for` — ``factory.py`` is never
edited again.  The #121 skeleton
(``faults.filters.phase2_skeletons.BBHeaderSyncFaultSkeletonTransform``)
stays in place for plans that never import this module and fails loudly
there; a plan resolved *after* the import gets this real transform.

Semantics (frozen, SPEC-204 §Phase2: ``field`` × ``mode`` over the six
BBHEADER fields, EN 302 755 §5.1.7 byte ranges shared with
:mod:`ts.t2mi.bbframe`) — the two modes produce **distinguishable
evidence shapes** (the B2 teaching point):

- ``corrupt`` — flip bit 1 (mask ``0x02``) of the field's first byte
  **without** recomputing the BBHEADER CRC-8: an integrity break.  Parse
  surfaces ``crc8_valid=False`` / state ``crc8_invalid`` and the
  ``bbframe.recovery_failed`` count (SPEC-601 §8 — the TSDuck 3.45
  silent-propagation defect #104, inverted into a visible mark).  Bit 1
  rather than bit 0 so a CRC-8-byte flip cannot alias NM↔HEM (the stored
  byte is CRC-8 XOR MODE; residue ``0x02`` is outside the valid MODE set
  {0x00 NM, 0x01 HEM}, so the corruption is always detected).
- ``shift`` — advance the field's value by one step in its natural unit
  (+1 on the big-endian integer, modulo the field width) **and**
  recompute the CRC-8 with the MODE residue preserved: the header stays
  internally consistent but semantically wrong — the realistic
  mis-declaring-encapsulator fault.  Parse surfaces the alignment
  symptoms (``syncd_misaligned`` / ``upl_invalid`` / ``dfl_mismatch``)
  with ``crc8_valid=True``.  For the ``CRC-8`` field itself the +1 is
  applied without a recompute (recomputing over an unchanged header
  would self-cancel the fault).

Slot-preserving invariant (SPEC-601 §7 / ADR-0007 item 4): the transform
maps one BBFRAME at shared-frame index ``index`` to exactly one BBFRAME
at the same index, byte length unchanged — faulted/baseline frame counts
and indexes stay aligned (等位替换).

Layer boundary: the transform acts on **BBFRAME byte frames** (the
layered pipeline's frame hand-off, ADR-0010 §3).  Feeding it the MVP
TS-packet object model is a category error and raises loudly (never a
silent pass-through) — the layered runtime (#128) routes by
``FaultDefinition.layer == "BBFRAME"``.
"""

from __future__ import annotations

import hashlib
from typing import Any

from ts._bytesutil import _coerce_bytes
from ts.packet import TSPacket
from ts.t2mi.bbframe import BBHEADER_FIELD_RANGES, BBHEADER_SIZE, crc8_dvb

from faults.filters.base import FaultTransform, MutationRecord
from faults.registry import PARAMETERS_SCHEMA_VERSION

__all__ = ["BBHeaderSyncFaultTransform"]

#: The two registered modes (SPEC-204 §Phase2 item 2).
_MODE_CORRUPT = "corrupt"
_MODE_SHIFT = "shift"

#: Bit 1 (not bit 0) so a CRC-8-byte flip cannot alias NM↔HEM: the stored
#: byte is CRC-8 XOR MODE and residue 0x02 is outside the valid MODE set.
_CORRUPT_MASK = 0x02


class BBHeaderSyncFaultTransform(FaultTransform):
    """Deterministic BBHEADER field corrupt/shift (BBFRAME layer)."""

    def __init__(self, definition: Any) -> None:
        super().__init__(definition)
        self._field: str = definition.parameters["field"]
        if self._field not in BBHEADER_FIELD_RANGES:
            raise ValueError(
                f"BBHEADER_SYNC_FAULT field {self._field!r} is not one of "
                f"{sorted(BBHEADER_FIELD_RANGES)} (EN 302 755 §5.1.7)"
            )
        self._mode: str = definition.parameters["mode"]
        if self._mode not in (_MODE_CORRUPT, _MODE_SHIFT):
            raise ValueError(
                f"BBHEADER_SYNC_FAULT mode {self._mode!r} is not one of "
                f"[{_MODE_CORRUPT!r}, {_MODE_SHIFT!r}] (SPEC-204 §Phase2)"
            )
        self._start, self._end = BBHEADER_FIELD_RANGES[self._field]

    # --- FaultTransform protocol ------------------------------------------------------

    def apply(self, index: int, frame: Any) -> Any:
        """Filter hook over BBFRAME byte frames (layered pipeline shape).

        Frames before the activation index pass through untouched; the
        TS-packet object model is rejected loudly (layer mismatch — the
        runtime routes ``BBHEADER_SYNC_FAULT`` to the BBFRAME layer).
        """
        if isinstance(frame, TSPacket):
            raise TypeError(
                "BBHEADER_SYNC_FAULT acts on the BBFRAME layer (byte frames "
                "per ADR-0010 §3), not on ts.packet.TSPacket — a plan "
                f"routing this fault ({self._definition.fault_id!r}, "
                f"layer={self._definition.layer!r}) through the MVP TS "
                "filter is a composition error; the layered runtime (#128) "
                "routes FaultDefinition.layer == 'BBFRAME' to the frame "
                "chain"
            )
        if index < self.activation_index:
            return frame
        return self.transform_frame(index, frame)

    def transform(self, index: int, packet: TSPacket) -> TSPacket:
        """The inherited TS-packet protocol shape: always a layer error."""
        raise TypeError(
            "BBHEADER_SYNC_FAULT has no TSPacket transform (BBFRAME layer, "
            "SPEC-204 §Phase2) — use apply(index, frame_bytes); the layered "
            "runtime (#128) routes by FaultDefinition.layer"
        )

    # --- byte-frame core ----------------------------------------------------------------

    def transform_frame(self, index: int, frame: Any) -> bytes:
        """Fault one BBHEADER field in ``frame`` (bytes), same slot/length.

        Deterministic: same frame + same definition → same faulted bytes.
        The mutation is recorded once per actually-faulted frame.
        """
        blob = _coerce_bytes(frame, param="frame")
        if len(blob) < BBHEADER_SIZE:
            raise ValueError(
                f"BBHEADER_SYNC_FAULT frame at index {index} has "
                f"{len(blob)} byte(s); a BBFRAME must carry at least a "
                f"{BBHEADER_SIZE}-byte BBHEADER (EN 302 755 §5.1.7)"
            )
        faulted, change = self._fault_bbheader(blob)
        self._record_frame(index, blob, faulted, change)
        return faulted

    def _fault_bbheader(self, blob: bytes) -> tuple[bytes, str]:
        """Apply the frozen field×mode semantics to the 10-byte header.

        Returns the faulted frame and the human-readable change text for
        the mutation record.
        """
        out = bytearray(blob)
        if self._mode == _MODE_CORRUPT:
            out[self._start] ^= _CORRUPT_MASK
            change = (
                f"bbheader {self._field} corrupt (bit flip, crc-8 not "
                "recomputed — integrity break, SPEC-204 §Phase2)"
            )
        else:
            width = self._end - self._start
            value = int.from_bytes(blob[self._start : self._end], "big")
            shifted = (value + 1) % (1 << (8 * width))
            out[self._start : self._end] = shifted.to_bytes(width, "big")
            if self._field == "CRC-8":
                crc_note = "crc-8 not recomputed — the field IS the check"
            else:
                # Preserve the MODE residue (NM/HEM identity) so the
                # faulted header stays internally consistent — the
                # misalignment symptoms stay observable past CRC-8.
                original_mode = blob[9] ^ crc8_dvb(blob[0:9])
                out[9] = crc8_dvb(bytes(out[0:9])) ^ original_mode
                crc_note = "crc-8 recomputed with MODE preserved"
            change = (
                f"bbheader {self._field} shift ({self._field} "
                f"{value:#0{2 * width}x} -> {shifted:#0{2 * width}x}; "
                f"{crc_note}, SPEC-204 §Phase2)"
            )
        return bytes(out), change

    # --- mutation records (SPEC-204 §8.2, BBFRAME-shaped summaries) -------

    def _record_frame(
        self, index: int, before: bytes, after: bytes, change: str
    ) -> None:
        self.records.append(
            MutationRecord(
                fault_id=self._definition.fault_id,
                fault_type=self._definition.fault_type,
                target_node_id=self.target.node_id,
                target_pid=self.target.pid if self.target.pid is not None else -1,
                packet_index=index,
                before=_summarize_frame(before),
                after=_summarize_frame(after),
                change=change,
                parameters=dict(self._definition.parameters),
                parameters_schema_version=PARAMETERS_SCHEMA_VERSION,
            )
        )


def _summarize_frame(frame: bytes) -> dict[str, Any]:
    """Offline-verifiable frame slot summary (length + digest + CRC byte)."""
    return {
        "frame_len": len(frame),
        "bbheader_crc8_stored": frame[9] if len(frame) > 9 else None,
        "frame_sha256": hashlib.sha256(frame).hexdigest(),
    }


# --- ruling §10-4 self-registration (import side effect) ---------------------------
#
# Binding happens here, inside the #123-owned filter module — factory.py
# and registry.py stay untouched.  Re-registration of the same builder is
# an idempotent no-op (frozen register_transform semantics).

from faults.factory import register_transform  # noqa: E402
from faults.registry import FAULT_TYPE_BBHEADER_SYNC_FAULT  # noqa: E402

register_transform(FAULT_TYPE_BBHEADER_SYNC_FAULT, BBHeaderSyncFaultTransform)
