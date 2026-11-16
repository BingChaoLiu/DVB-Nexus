"""ADR-0011 §2 — the scrambler filter-type skeleton (ticket #121).

The filters family gains the ``scrambler`` type in Phase 2: BISS
scrambling is a per-packet payload transform (header 4 bytes clear,
length 188 unchanged, packet order unchanged), so the ``apply(index,
packet)`` contract applies as-is — no new transport-level component.
Construction features (scenario-declared keys) and fault injection
(``FaultDefinition.params`` mismatched keys) drive the *same* scrambler
filter; only the key source differs.

#121 lands the skeleton only (the brief's seam matrix assigns the
dvbcsa adapter + ``src/ts/biss/`` + the real filter implementation to
#126).  The skeleton is an honest placeholder: it refuses to transform
rather than passing packets through unscrambled.
"""

from __future__ import annotations

import dataclasses

import pytest

from faults.definition import FaultActivation, FaultDefinition
from faults.filters.base import FaultTransform
from faults.filters.scrambler import ScramblerTransform
from faults.filters.pat_missing import null_packet

pytestmark = pytest.mark.unit


class TestScramblerSkeleton:
    def test_skeleton_is_a_fault_transform_subclass(self) -> None:
        assert issubclass(ScramblerTransform, FaultTransform)

    def test_declared_layer_is_biss(self) -> None:
        # ADR-0011 §2 / ADR-0007 addendum: filters family gains the
        # scrambler type with layer="BISS".
        assert ScramblerTransform.LAYER == "BISS"

    def test_apply_refuses_to_silently_pass_through(self) -> None:
        definition = FaultDefinition(
            fault_id="f-scramble",
            fault_type="BISS_KEY_MISMATCH",
            target_id="biss-scrambler-0",
            activation=FaultActivation(kind="session_start", packet_index=None),
            expected_observations=("biss.descramble_failed",),
            layer="BISS",
        )
        transform = ScramblerTransform(definition)
        with pytest.raises(NotImplementedError):
            transform.apply(0, null_packet())

    def test_owner_points_at_ticket_126(self) -> None:
        assert "#126" in ScramblerTransform._owner_ticket

    def test_fault_definition_stays_frozen_additive(self) -> None:
        # Scrambler consumes the canonical definition shape; the Phase 2
        # layer attribute is the only additive field.
        field_names = {
            field.name for field in dataclasses.fields(FaultDefinition)
        }
        assert "layer" in field_names
