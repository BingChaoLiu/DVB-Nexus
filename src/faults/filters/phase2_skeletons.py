"""Phase 2 filter skeletons — explicit ``NotImplementedError`` placeholders.

Ticket #121 (domain foundation) wires the four Phase 2 primitives into the
fault registry with skeleton transforms so the plumbing is testable end to
end at the unit level.  The real per-layer transforms are owned by the
downstream tickets and self-register via
:func:`faults.factory.register_transform` (orchestrator ruling §10-4 —
``factory.py`` is never edited again):

- ``T2miPlpMismatchSkeletonTransform``  → real implementation in #124
  (``faults.filters.t2mi_plp_mismatch``);
- ``BBHeaderSyncFaultSkeletonTransform`` → real implementation in #123
  (``faults.filters.bbheader_sync``);
- ``BissKeyMismatchSkeletonTransform``  → real implementation in #126
  (scrambler filter family, ``faults.filters.scrambler``);
- ``PmtPidDriftSkeletonTransform``      → real implementation in #139
  (``faults.filters.pmt_pid_drift``, the #136 收口 patch ticket D-2).

Skeletons are honest placeholders, never silent pass-throughs: applying
one raises ``NotImplementedError`` naming the owning ticket.  A prepared
run whose plan still resolves to a skeleton therefore fails loudly at the
first applied slot instead of mis-generating an unfaulted stream.

The layer routing (``FaultDefinition.layer``) means the runtime (#128)
instantiates per-layer filter chains; these skeletons subclass the MVP
:class:`FaultTransform` so the existing semantic-filter composition works
unchanged for TS-layer plans and for unit-level verification.
"""

from __future__ import annotations

from ts.packet import TSPacket

from faults.filters.base import FaultTransform

__all__ = [
    "BBHeaderSyncFaultSkeletonTransform",
    "BissKeyMismatchSkeletonTransform",
    "PmtPidDriftSkeletonTransform",
    "T2miPlpMismatchSkeletonTransform",
]


class _Phase2SkeletonTransform(FaultTransform):
    """Shared skeleton behavior: refuse to fake a not-yet-built transform."""

    _owner_ticket: str = "the owning Phase 2 ticket"

    def transform(self, index: int, packet: TSPacket) -> TSPacket:
        raise NotImplementedError(
            f"{type(self).__name__} is the #121 domain-foundation skeleton; "
            f"the real transform is owned by {self._owner_ticket} and must "
            "register itself via faults.factory.register_transform "
            "(orchestrator ruling §10-4)"
        )


class T2miPlpMismatchSkeletonTransform(_Phase2SkeletonTransform):
    """T2MI_PLP_MISMATCH skeleton (T2MI layer) — implementation owned by #124."""

    _owner_ticket = "#124 (faults.filters.t2mi_plp_mismatch)"


class BBHeaderSyncFaultSkeletonTransform(_Phase2SkeletonTransform):
    """BBHEADER_SYNC_FAULT skeleton (BBFRAME layer) — implementation owned by #123."""

    _owner_ticket = "#123 (faults.filters.bbheader_sync)"


class BissKeyMismatchSkeletonTransform(_Phase2SkeletonTransform):
    """BISS_KEY_MISMATCH skeleton (BISS layer) — implementation owned by #126."""

    _owner_ticket = "#126 (scrambler filter family)"


class PmtPidDriftSkeletonTransform(_Phase2SkeletonTransform):
    """PMT_PID_DRIFT skeleton (TS layer) — implementation owned by #128."""

    _owner_ticket = "#128 (TS-layer runtime wiring)"
