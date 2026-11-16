"""ADR-0011 §2 — the scrambler filter-type skeleton (Phase 2, #121).

The filters family gains the ``scrambler`` type in Phase 2: BISS
scrambling is a per-packet payload transform (header 4 bytes clear,
length 188 unchanged, packet order unchanged), so the ``apply(index,
packet)`` contract applies as-is — no new transport-level component.
Construction features (scenario-declared keys, the scenario ``biss``
section) and fault injection (``FaultDefinition.parameters`` mismatched
keys) drive the *same* scrambler filter; only the key source differs
(ADR-0011 §2/§3).

#121 lands this skeleton only.  The real implementation — dvbcsa adapter
(:mod:`adapters.dvbcsa`), the ``src/ts/biss/`` scramble/descramble
primitives and this filter's payload transform — is owned by ticket
#126, which registers nothing here (the scrambler is a filter *type*,
not a fault-type builder; ``factory.py`` registration is for the fault
primitives).

Evidence discipline (ADR-0011 §3/§4): every actual transformation lands
a mutation record carrying before/after packet summaries and the key
* fingerprint* — the key material itself never enters the mutation log,
journal or artifacts.  The skeleton already runs through the shared
:class:`FaultTransform` record machinery; #126 fills :meth:`transform`.
"""

from __future__ import annotations

from ts.packet import TSPacket

from faults.filters.base import FaultTransform

__all__ = ["ScramblerTransform"]


class ScramblerTransform(FaultTransform):
    """BISS scrambler filter skeleton (ADR-0011 §2, implementation in #126).

    ``LAYER`` pins the pipeline layer the runtime (#128) routes this
    filter type into.  Slot-preserving contract: one packet in, one
    packet out at the same index — 188-byte length and packet order
    unchanged (the等位替换 invariant holds at the BISS layer too).
    """

    LAYER = "BISS"

    _owner_ticket = "#126 (src/adapters/dvbcsa + src/ts/biss)"

    def transform(self, index: int, packet: TSPacket) -> TSPacket:
        raise NotImplementedError(
            "ScramblerTransform is the #121 domain-foundation skeleton; "
            f"the real payload transform is owned by {self._owner_ticket} "
            "(ADR-0011 §2 — construction features and fault injection "
            "drive the same scrambler filter, only the key source differs)"
        )

    # Slot-preserving invariant (等位替换) holds at the BISS layer too:
    # 188-byte length and packet order unchanged — enforced by #126's
    # real transform, which must keep one packet in / one packet out.
