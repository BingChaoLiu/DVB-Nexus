"""SPEC-204 §6.3 — CC_DISCONTINUITY transform behavior tests.

The frozen geometry gives real landing behavior: activation 30 → the
first PID-0x0100 payload packet after it is slot 50 (oracle parity), with
adaptation-only slots (e.g. 80) interleaved later.
"""

from __future__ import annotations

import pytest

from faults.filters.cc_discontinuity import CCDiscontinuityTransform

from tests.unit.faults._fault_builders import (
    GOLDEN_ES1_PID,
    golden_baseline_packets,
    cc_discontinuity_fault,
)

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def baseline() -> tuple:
    return golden_baseline_packets()


def _pid_slots(packets, pid: int) -> list[int]:
    return [i for i, packet in enumerate(packets) if packet.pid == pid]


class TestLandingSemantics:
    def test_lands_on_first_payload_packet_after_activation(self, baseline) -> None:
        transform = CCDiscontinuityTransform(cc_discontinuity_fault())
        faulted = [transform.apply(i, p) for i, p in enumerate(baseline)]
        changed = [
            i
            for i, (before, after) in enumerate(zip(baseline, faulted))
            if before.to_bytes() != after.to_bytes()
        ]
        target_slots = _pid_slots(baseline, GOLDEN_ES1_PID)
        assert changed[0] == 50  # oracle: landing slot 50
        assert changed == [slot for slot in target_slots if slot >= 50]

    def test_delta_applies_to_landing_cc(self, baseline) -> None:
        transform = CCDiscontinuityTransform(cc_discontinuity_fault())
        faulted_packet = transform.apply(50, baseline[50])
        assert faulted_packet.continuity_counter == (
            (baseline[50].continuity_counter + 3) & 0x0F
        )

    def test_offset_persists_across_the_run(self, baseline) -> None:
        transform = CCDiscontinuityTransform(cc_discontinuity_fault())
        faulted = [transform.apply(i, p) for i, p in enumerate(baseline)]
        for index in _pid_slots(baseline, GOLDEN_ES1_PID):
            if index < 50:
                continue
            expected = (baseline[index].continuity_counter + 3) & 0x0F
            assert faulted[index].continuity_counter == expected


class TestAdaptationOnlyHandling:
    def test_landing_skips_adaptation_only_packets(self, baseline) -> None:
        # no PID-0x0100 slot exists between activation 30 and landing 50,
        # and the landing packet carries a payload (never adaptation-only).
        assert baseline[50].payload is not None

    def test_af_only_after_breakpoint_follows_reuse_rule(self, baseline) -> None:
        transform = CCDiscontinuityTransform(cc_discontinuity_fault())
        faulted = [transform.apply(i, p) for i, p in enumerate(baseline)]
        # slot 80 is adaptation-only (AFC=10) and after the breakpoint: its
        # CC must equal the faulted stream's last payload CC (slot 75's
        # baseline CC + delta) — not its own baseline CC + delta + 1.
        assert baseline[80].payload is None
        assert baseline[80].continuity_counter == baseline[75].continuity_counter
        expected = (baseline[75].continuity_counter + 3) & 0x0F
        assert faulted[80].continuity_counter == expected


class TestWrapAndBounds:
    def test_delta_wraps_modulo_16(self, baseline) -> None:
        transform = CCDiscontinuityTransform(cc_discontinuity_fault())
        faulted = [transform.apply(i, p) for i, p in enumerate(baseline)]
        # baseline CC at slot 400 is 15: the faulted value wraps to
        # (15 + 3) mod 16 == 2, and the next payload packet continues +1.
        assert baseline[400].continuity_counter == 15
        assert faulted[400].continuity_counter == 2
        assert faulted[425].continuity_counter == 3

    def test_other_pids_untouched(self, baseline) -> None:
        transform = CCDiscontinuityTransform(cc_discontinuity_fault())
        faulted = [transform.apply(i, p) for i, p in enumerate(baseline)]
        for index, (before, after) in enumerate(zip(baseline, faulted)):
            if before.pid == GOLDEN_ES1_PID and index >= 50:
                continue
            assert after.to_bytes() == before.to_bytes()

    def test_session_start_lands_on_first_payload_packet(self, baseline) -> None:
        transform = CCDiscontinuityTransform(
            cc_discontinuity_fault(packet_index=None)
        )
        faulted = [transform.apply(i, p) for i, p in enumerate(baseline)]
        changed = [
            i
            for i, (before, after) in enumerate(zip(baseline, faulted))
            if before.to_bytes() != after.to_bytes()
        ]
        assert changed[0] == _pid_slots(baseline, GOLDEN_ES1_PID)[0]

    def test_no_payload_target_packets_never_lands(self, baseline) -> None:
        """A target PID absent from the stream cannot land — the transform
        stays a no-op (no mutation records, no run failure)."""
        from faults.definition import FaultActivation, FaultDefinition

        definition = FaultDefinition(
            fault_id="f",
            fault_type="CC_DISCONTINUITY",
            target_id="demux-0:pid:0x1234",
            parameters={"delta": 3},
            activation=FaultActivation(kind="session_start"),
            expected_observations=("ts.continuity_error",),
        )
        transform = CCDiscontinuityTransform(definition)
        for index, packet in enumerate(baseline):
            transform.apply(index, packet)
        assert transform.records == []
