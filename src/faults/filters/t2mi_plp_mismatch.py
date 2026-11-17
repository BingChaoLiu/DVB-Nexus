"""T2MI_PLP_MISMATCH real transform — SPEC-602 §7 B1 path (ticket #124).

Replaces the #121 ``T2miPlpMismatchSkeletonTransform`` via import-time
self-registration (orchestrator ruling §10-4 — ``factory.py`` is never
edited again): importing this module binds
:class:`T2miPlpMismatchTransform` as the builder for
``FAULT_TYPE_T2MI_PLP_MISMATCH``.

Injection semantics (SPEC-602 §7 / ticket #124): in the faulted run the
encapsulator assigns the business PLP as ``actual_plp`` while the demux
still filters on ``expected_plp`` — the wire face at this layer is a
**transport-prefix PLP re-stamp** on matching BBFRAME T2-MI packets
(the prefix byte layout ``frame_idx(1) + PLP_id(1) + flags(1)`` comes
from the #122 builder; the fault rewrites exactly the PLP byte and
recomputes the CRC-32 so the faulted stream stays structurally
parseable — the B1 symptom is semantic drift with an outer green light:
T2-MI packets lock and parse fine, Inner TS loses its business, and the
demux-side :func:`ts.t2mi.plp.filter` absence face raises the
``t2mi.plp_mismatch`` candidate).

Activation mapping (SPEC-204 §7 / ADR-0007 item 3, per #121's registry):

- ``session_start`` (default): whole-run restamp — every matching packet
  drifts to ``actual_plp``;
- ``packet_index``: the restamp starts at the shared T2-MI packet index —
  with ``plp_version_switch=True`` this is the #111 mid-stream PLP
  version-switch variant (expected before, actual from the switch point
  through run end); the switch variant therefore requires a
  ``packet_index`` activation and refuses otherwise (no switch point, no
  switch — honest construction-time refusal).

Slot preservation (ADR-0007 item 4): one packet in, one packet out at
the same index; packet_counter / frame_index / payload_bits / size are
untouched; only the PLP byte differs.  Non-BBFRAME packets (padding /
unknown states) and packets already carrying a different PLP pass
through without a record — only actual changes are recorded (SPEC-204
§8.2 mutation log discipline).

Layer discipline: this is a T2MI-layer transform driven with
:class:`ts.t2mi.packet.T2miPacket` inputs by the layer chain (#128's
layer routing; ``FaultDefinition.layer == "T2MI"`` is registry-enforced
since #121).  A TS-layer slot (:class:`ts.packet.TSPacket`) input raises
``TypeError`` loudly — silently passing a TS slot would fake a green
run (the skeleton's honest-refusal discipline, continued).

Registry interplay: ``expected_plp`` / ``actual_plp`` value domains and
the unequal-pair rule are validated by ``faults.registry`` (#121) before
any transform is built; this module trusts that face.
"""

from __future__ import annotations

import hashlib
from typing import Any

from ts.crc import mpeg2_crc32
from ts.t2mi.packet import PAYLOAD_KIND_BBFRAME, T2miPacket

from faults.definition import FaultDefinition
from faults.filters.base import FaultTransform, MutationRecord
from faults.factory import register_transform
from faults.registry import (
    FAULT_TYPE_T2MI_PLP_MISMATCH,
    PARAMETERS_SCHEMA_VERSION,
)

__all__ = [
    "T2miPlpMismatchTransform",
    "slot_summary",
]

#: Transport-prefix layout: ``frame_idx(0) + PLP_id(1) + flags(2)`` —
#: the byte the fault rewrites (the #122 builder's byte-aligned face).
_PLP_BYTE_OFFSET = 1
_MASK8 = 0xFF


def slot_summary(packet: T2miPacket) -> dict[str, Any]:
    """Offline-verifiable T2-MI slot summary (the T2-MI twin of the base
    class's TS ``summarize_packet``): identity fields + slot digest, so
    any consumer re-derives the slot from either artifact side.
    """
    return {
        "packet_counter": packet.packet_counter,
        "frame_index": packet.frame_index,
        "plp_id": packet.plp_id,
        "payload_kind": packet.payload_kind,
        "slot_sha256": hashlib.sha256(packet.to_bytes()).hexdigest(),
    }


class T2miPlpMismatchTransform(FaultTransform):
    """The T2MI-layer PLP drift transform (SPEC-602 §7 B1 path).

    Slot-preserving at the T2-MI packet frame: matching BBFRAME packets
    (transport-prefix PLP == ``expected_plp``) are re-stamped to
    ``actual_plp`` from the activation index through run end; everything
    else passes untouched.  Every actual change appends one
    :class:`~faults.filters.base.MutationRecord` whose before/after slot
    summaries carry the T2-MI identity faces (packet_counter, frame_index,
    plp_id, payload_kind, slot digest) — the offline-verifiable evidence
    the layered mutation log is built from.
    """

    LAYER = "T2MI"

    def __init__(self, definition: FaultDefinition) -> None:
        super().__init__(definition)
        parameters = definition.parameters
        self._expected_plp = parameters["expected_plp"]
        self._actual_plp = parameters["actual_plp"]
        self._version_switch = bool(parameters.get("plp_version_switch", False))
        if self._version_switch and definition.activation.kind != "packet_index":
            raise ValueError(
                "T2MI_PLP_MISMATCH plp_version_switch=True is the mid-stream "
                "PLP version-switch variant and requires a packet_index "
                "activation (the switch point IS the activation index, "
                "SPEC-602 §7 / #111)"
            )
        self._first_restatement_index: int | None = None
        self._restamped_count = 0

    # --- filter hook (T2-MI packet frame) ---------------------------------------

    def apply(self, index: int, packet: object) -> T2miPacket:
        """One slot in, one slot out — T2-MI packet frame discipline.

        A TS-layer slot here means the fault was routed to the wrong
        layer; the honest refusal keeps a mis-routed run from passing
        green.
        """
        if not isinstance(packet, T2miPacket):
            raise TypeError(
                "T2miPlpMismatchTransform is a T2MI-layer transform: it "
                "takes ts.t2mi.packet.T2miPacket inputs (the layer chain "
                "drives it, #128 layer routing), got "
                f"{type(packet).__name__} — a TS-layer slot must not be "
                "silently passed through"
            )
        if index < self.activation_index:
            return packet
        return self.transform(index, packet)

    def transform(self, index: int, packet: T2miPacket) -> T2miPacket:
        if packet.payload_kind != PAYLOAD_KIND_BBFRAME:
            return packet
        if packet.plp_id != self._expected_plp:
            return packet
        restamped = self._restamp(packet, self._actual_plp)
        self._record_restamp(index, packet, restamped)
        return restamped

    # --- the wire face: PLP byte swap + CRC re-encode ---------------------------

    @staticmethod
    def _restamp(packet: T2miPacket, actual_plp: int) -> T2miPacket:
        """Rewrite the transport-prefix PLP byte; recompute the CRC-32.

        The drift is semantic, not structural: the faulted packet must
        re-parse with a valid CRC so the B1 symptom stays "outer green
        light" (the stream locks, the business is gone).
        """
        new_payload = (
            packet.payload[:_PLP_BYTE_OFFSET]
            + bytes([actual_plp & _MASK8])
            + packet.payload[_PLP_BYTE_OFFSET + 1 :]
        )
        header_prefix = bytes(
            [
                packet.packet_type & _MASK8,
                packet.packet_counter & _MASK8,
                packet.reserved[0] & _MASK8,
                packet.reserved[1] & _MASK8,
            ]
        ) + packet.payload_bits.to_bytes(2, "big")
        return T2miPacket(
            packet_type=packet.packet_type,
            packet_counter=packet.packet_counter,
            reserved=packet.reserved,
            payload_bits=packet.payload_bits,
            payload=new_payload,
            crc32=mpeg2_crc32(header_prefix + new_payload),
        )

    # --- records (SPEC-204 §8.2) --------------------------------------------------

    def _record_restamp(
        self, index: int, before: T2miPacket, after: T2miPacket
    ) -> None:
        self.records.append(
            MutationRecord(
                fault_id=self._definition.fault_id,
                fault_type=self._definition.fault_type,
                target_node_id=self.target.node_id,
                target_pid=self.target.pid if self.target.pid is not None else -1,
                packet_index=index,
                before=slot_summary(before),
                after=slot_summary(after),
                change="t2mi_plp_restamp",
                parameters=dict(self._definition.parameters),
                parameters_schema_version=PARAMETERS_SCHEMA_VERSION,
            )
        )
        self._restamped_count += 1
        if self._first_restatement_index is None:
            self._first_restatement_index = index

    # --- observability convenience (fault terminal events, #128) -----------------

    def restamp_summary(self) -> dict[str, Any]:
        """Restamp statistics for the run's fault terminal events.

        Not a frozen event payload — the emission keys for
        ``t2mi.plp_mismatch`` are frozen in :mod:`ts.t2mi.plp`; this dict
        is the transform-level stat face (#128 composes event payloads
        from it plus the run context).
        """
        return {
            "restamped_packet_count": self._restamped_count,
            "expected_plp": self._expected_plp,
            "actual_plp": self._actual_plp,
            "plp_version_switch": self._version_switch,
            "first_restatement_index": self._first_restatement_index,
        }


# --- self-registration (ruling §10-4 — factory.py is never edited again) ---------

register_transform(FAULT_TYPE_T2MI_PLP_MISMATCH, T2miPlpMismatchTransform)
