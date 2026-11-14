"""First-batch golden vectors ``cc-wrap`` and ``pcr-wrap`` — assertions.

Conformance layer (SPEC-505 §3 / SPEC-506 §7 #4/#5).

- ``cc-wrap``: single PID ≥17 payload packets riding the CC 15→0 wrap
  (SPEC-100 §5.4 modulo-16 rule).  Script-constructed bytes, verified via
  L2 TSDuck ``continuity`` plugin (registered evidence; the plugin is
  silent on correct wraps and flags jumps — see the vector's verification
  note).
- ``pcr-wrap``: hand-set PCR values around the 2^33 base wrap
  (SPEC-105: base wraps at 2^33, combined 27 MHz ticks wrap at 2^33·300;
  modular_delta direction window [0, modulus/2)).

Both are consumed read-only through ``golden_loader``; expectations.json
entries use ``ts.packet_batch_observed`` + locator {pid, packet_index}.
"""

from __future__ import annotations

import pytest

from ts.pcr import PCR_MODULUS, pcr_to_27mhz_ticks
from ts.packet import TSPacket

pytestmark = pytest.mark.conformance

CC_WRAP_ID = "cc-wrap"
PCR_WRAP_ID = "pcr-wrap"

#: cc-wrap constructor constants (tools/make_golden_ts_vectors.py).
CC_WRAP_PID = 0x0123
CC_WRAP_PACKETS = 18  # CC 0..15 then 0,1 — wrap between index 15 and 16
CC_WRAP_CC_SEQUENCE = tuple(index % 16 for index in range(CC_WRAP_PACKETS))

#: pcr-wrap constructor constants.
PCR_WRAP_PID = 0x0100
PCR_WRAP_BASES = (
    (1 << 33) - 3,
    (1 << 33) - 2,
    (1 << 33) - 1,  # largest legal base (SPEC-105 §11)
    0,              # the wrap step: 2^33-1 → 0
    1,
    2,
)
PCR_WRAP_EXT = 0
HALF_PERIOD_27MHZ = PCR_MODULUS // 2


def _packets(vector) -> list[TSPacket]:
    out = []
    for offset in range(0, len(vector.ts_bytes), 188):
        out.append(TSPacket.from_bytes(vector.ts_bytes[offset : offset + 188]))
    return out


# --- cc-wrap -----------------------------------------------------------------


def test_cc_wrap_shape_and_registration(golden_loader):
    vector = golden_loader.load(CC_WRAP_ID)
    assert vector.kind == "generated_ts"
    assert vector.packet_count == CC_WRAP_PACKETS
    assert len(vector.ts_bytes) == CC_WRAP_PACKETS * 188
    assert vector.verification is not None
    assert vector.verification.path == "tsduck-cross"
    assert vector.fault_plan_ref is None


def test_cc_wrap_rides_the_15_to_0_boundary(golden_loader):
    packets = _packets(golden_loader.load(CC_WRAP_ID))
    observed = tuple(packet.continuity_counter for packet in packets)
    assert observed == CC_WRAP_CC_SEQUENCE
    # The wrap step itself: index 15 carries CC 15, index 16 wraps to 0.
    assert packets[15].continuity_counter == 15
    assert packets[16].continuity_counter == 0
    # All packets are payload packets on the single PID (§7: 单 PID ≥17
    # payload 包).
    assert {packet.pid for packet in packets} == {CC_WRAP_PID}
    for packet in packets:
        assert packet.adaptation_field is None


def test_cc_wrap_expectations_pin_the_wrap_slots(golden_loader):
    vector = golden_loader.load(CC_WRAP_ID)
    entries = {entry["locator"]["packet_index"]: entry for entry in vector.expectations}
    # The wrap-adjacent slots are declared explicitly.
    assert entries[15]["detail"]["cc"] == 15
    assert entries[16]["detail"]["cc"] == 0
    assert all(entry["event_type"] == "ts.packet_batch_observed" for entry in entries.values())
    assert all(entry["locator"]["pid"] == CC_WRAP_PID for entry in entries.values())


def test_cc_wrap_constructor_reproduces_registered_bytes(golden_loader, tmp_path):
    import subprocess
    import sys
    from tests._support.paths import REPO_ROOT

    vector = golden_loader.load(CC_WRAP_ID)
    script = REPO_ROOT / "tools" / "make_golden_ts_vectors.py"
    result = subprocess.run(
        [sys.executable, "-I", str(script), "cc-wrap", "--output-dir", str(tmp_path)],
        capture_output=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    rebuilt = (tmp_path / CC_WRAP_ID / f"{CC_WRAP_ID}.ts").read_bytes()
    assert rebuilt == vector.ts_bytes


# --- pcr-wrap ----------------------------------------------------------------


def test_pcr_wrap_shape_and_registration(golden_loader):
    vector = golden_loader.load(PCR_WRAP_ID)
    assert vector.kind == "generated_ts"
    assert vector.packet_count == len(PCR_WRAP_BASES)
    assert vector.verification is not None
    assert vector.verification.path == "tsduck-cross"


def test_pcr_wrap_hand_set_values_wrap_at_2_power_33(golden_loader):
    packets = _packets(golden_loader.load(PCR_WRAP_ID))
    assert len(packets) == len(PCR_WRAP_BASES)
    ticks: list[int] = []
    for packet, expected_base in zip(packets, PCR_WRAP_BASES):
        assert packet.pid == PCR_WRAP_PID
        assert packet.adaptation_field is not None
        pcr = packet.adaptation_field.pcr
        assert pcr is not None
        assert pcr.base == expected_base
        assert pcr.extension == PCR_WRAP_EXT
        ticks.append(pcr_to_27mhz_ticks(pcr))
    # The wrap: 2^33-1 (max base) → 0, i.e. combined ticks (2^33-1)·300 → 0.
    assert ticks[2] == ((1 << 33) - 1) * 300
    assert ticks[3] == 0
    # Forward modular deltas stay inside the direction-decidable half-period
    # window (SPEC-105 §6) across the wrap step.
    deltas = [
        (current - previous) % PCR_MODULUS
        for previous, current in zip(ticks, ticks[1:])
    ]
    assert all(delta < HALF_PERIOD_27MHZ for delta in deltas)
    assert deltas[3] == 300  # wrap step is a small forward delta, not a jump


def test_pcr_wrap_adaptation_only_cc_reuse(golden_loader):
    # Every pcr-wrap packet is adaptation-only ⇒ CC reuses the initial
    # value (SPEC-100 §5.4) — no CC increments on this PID.
    packets = _packets(golden_loader.load(PCR_WRAP_ID))
    assert {packet.continuity_counter for packet in packets} == {0}
    assert all(packet.payload is None for packet in packets)


def test_pcr_wrap_expectations_pin_pcr_values(golden_loader):
    vector = golden_loader.load(PCR_WRAP_ID)
    entries = list(vector.expectations)
    assert len(entries) == len(PCR_WRAP_BASES)
    for index, entry in enumerate(entries):
        assert entry["event_type"] == "ts.packet_batch_observed"
        assert entry["locator"] == {"pid": PCR_WRAP_PID, "packet_index": index}
        assert entry["detail"]["pcr_base"] == PCR_WRAP_BASES[index]
        assert entry["detail"]["pcr_extension"] == PCR_WRAP_EXT


def test_pcr_wrap_constructor_reproduces_registered_bytes(golden_loader, tmp_path):
    import subprocess
    import sys
    from tests._support.paths import REPO_ROOT

    vector = golden_loader.load(PCR_WRAP_ID)
    script = REPO_ROOT / "tools" / "make_golden_ts_vectors.py"
    result = subprocess.run(
        [sys.executable, "-I", str(script), "pcr-wrap", "--output-dir", str(tmp_path)],
        capture_output=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    rebuilt = (tmp_path / PCR_WRAP_ID / f"{PCR_WRAP_ID}.ts").read_bytes()
    assert rebuilt == vector.ts_bytes
