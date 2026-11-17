"""ADR-0011 §2 — the scrambler filter type (layer=BISS).

#121 landed this as an explicit-``NotImplementedError`` skeleton; #126
(ticket, this tree) replaced the skeleton with the real transform.  This
file keeps the filter-type identity pins that survive the migration:
class shape, layer declaration, and the FaultDefinition additive-field
contract.  The behavioral suite lives in
``tests/unit/faults/test_biss_key_mismatch_transform.py`` and the
``ts.biss`` primitive suites.
"""

from __future__ import annotations

import dataclasses

import pytest

from faults.definition import FaultActivation, FaultDefinition
from faults.filters.base import FaultTransform
from faults.filters.scrambler import ScramblerTransform
from faults.filters.pat_missing import null_packet
from ts.packet import TSPacket

pytestmark = pytest.mark.unit


def _definition() -> FaultDefinition:
    return FaultDefinition(
        fault_id="f-scramble",
        fault_type="BISS_KEY_MISMATCH",
        target_id="biss-scrambler-0",
        parameters={"wrong_session_word": "0123456789AB", "pid_scope": [0x0100]},
        activation=FaultActivation(kind="session_start", packet_index=None),
        expected_observations=("biss.descramble_failed",),
        layer="BISS",
    )


class TestScramblerFilterType:
    def test_is_a_fault_transform_subclass(self) -> None:
        assert issubclass(ScramblerTransform, FaultTransform)

    def test_declared_layer_is_biss(self) -> None:
        # ADR-0011 §2 / ADR-0007 addendum: filters family gains the
        # scrambler type with layer="BISS".
        assert ScramblerTransform.LAYER == "BISS"

    def test_no_longer_refuses_in_scope_slots(self) -> None:
        """The #126 real transform scrambles in-scope slots (the #121
        skeleton's NotImplementedError refusal is retired)."""
        transform = ScramblerTransform(
            _definition(),
            session_word="0123456789AB",
            pid_scope=(0x0100,),
            backend=_ShapeBackend(),
        )
        packet = TSPacket(
            pid=0x0100, continuity_counter=0, payload=null_packet().payload
        )
        after = transform.apply(0, packet)
        assert after.transport_scrambling_control == 0b10

    def test_out_of_scope_slots_still_pass_through_untouched(self) -> None:
        transform = ScramblerTransform(
            _definition(),
            session_word="0123456789AB",
            pid_scope=(0x0100,),
            backend=_ShapeBackend(),
        )
        original = null_packet()
        assert transform.apply(0, original) is original

    def test_fault_definition_stays_frozen_additive(self) -> None:
        # Scrambler consumes the canonical definition shape; the Phase 2
        # layer attribute is the only additive field.
        field_names = {
            field.name for field in dataclasses.fields(FaultDefinition)
        }
        assert "layer" in field_names


class _ShapeBackend:
    """Minimal BatchCipherBackend shape (real CSA1 verified elsewhere)."""

    def encrypt_batch(self, payloads, cw):
        return tuple(bytes(len(p)) for p in payloads)

    def decrypt_batch(self, payloads, cw):
        return tuple(bytes(len(p)) for p in payloads)
