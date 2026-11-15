"""Byte-level oracle 对拍 (SPEC-506 §5 independent-verification discipline).

The registered golden faulted vectors (docs/test-vectors/golden/, #14
products of the independent ``tools/golden_fault_transform.py`` byte
transform) are the acceptance authority for the #44 semantic filter: the
filter's output over the same baseline must be **byte-identical** to the
golden faulted bytes — self-consistent round-trips are only regression
coverage (CONTEXT.md 独立验证词条).

The baseline half comes from the registered golden baseline bytes parsed
through the strict ``ts.packet.TSPacket`` model (lossless, sha-checked by
the golden loader); the fault definitions mirror the frozen parameters in
the faulted manifests' ``fault_parameters`` blocks (SPEC-204 §6 schema v1).
"""

from __future__ import annotations

import pytest
from ts.packet import TSPacket

from faults.factory import build_semantic_filter_factory
from ts.generator.config import GeneratorConfig

from tests.unit.faults._fault_builders import (
    cc_discontinuity_fault,
    golden_baseline_packets,
    golden_geometry_config,
    pat_missing_fault,
    pmt_invalid_crc_fault,
    pmt_pid_mismatch_fault,
)

pytestmark = pytest.mark.integration

#: The four golden fault pairs (vector_id → plan builder).
ORACLE_PAIRS = {
    "pat-missing": pat_missing_fault,
    "pmt-invalid-crc": pmt_invalid_crc_fault,
    "cc-discontinuity": cc_discontinuity_fault,
    "pmt-pid-mismatch": pmt_pid_mismatch_fault,
}


def _faulted_bytes(spec_filter, baseline_packets) -> bytes:
    faulted = [spec_filter.apply(i, p) for i, p in enumerate(baseline_packets)]
    return b"".join(packet.to_bytes() for packet in faulted)


class TestGoldenOracleParity:
    """REQ-SIM-204-002/003/008 acceptance: filter output == golden faulted."""

    @pytest.mark.parametrize("vector_id", sorted(ORACLE_PAIRS))
    def test_filter_output_is_byte_identical_to_golden(
        self, golden_loader, vector_id: str
    ) -> None:
        baseline = golden_loader.load(f"{vector_id}-baseline")
        faulted_golden = golden_loader.load(vector_id)
        assert faulted_golden.fault_plan_ref == f"{vector_id}-baseline"

        plan = (ORACLE_PAIRS[vector_id](),)
        spec_filter = build_semantic_filter_factory()(plan, golden_geometry_config())
        output = _faulted_bytes(spec_filter, baseline_packets_of(baseline.ts_bytes))
        assert output == faulted_golden.ts_bytes, (
            f"{vector_id}: filter output deviates from the golden faulted "
            "vector (byte-level oracle 对拍)"
        )

    @pytest.mark.parametrize("vector_id", sorted(ORACLE_PAIRS))
    def test_filter_output_changes_the_faulted_hash(
        self, golden_loader, vector_id: str
    ) -> None:
        """REQ-SIM-204-003/006: L1 faults change the artifact digest."""
        import hashlib

        baseline = golden_loader.load(f"{vector_id}-baseline")
        faulted_golden = golden_loader.load(vector_id)
        plan = (ORACLE_PAIRS[vector_id](),)
        spec_filter = build_semantic_filter_factory()(plan, golden_geometry_config())
        output = _faulted_bytes(spec_filter, baseline_packets_of(baseline.ts_bytes))
        assert hashlib.sha256(output).hexdigest() == faulted_golden.sha256
        assert faulted_golden.sha256 != baseline.sha256

    def test_generator_reproduces_the_registered_baseline(
        self, golden_loader
    ) -> None:
        """The golden baseline IS a SPEC-108 generator run of the frozen
        geometry — the end-to-end tee oracle builds on this identity."""
        import hashlib

        baseline = golden_loader.load("cc-discontinuity-baseline")
        packets = tuple(golden_baseline_packets())
        data = b"".join(p.to_bytes() for p in packets)
        assert hashlib.sha256(data).hexdigest() == baseline.sha256


def baseline_packets_of(ts_bytes: bytes) -> list[TSPacket]:
    """Parse a registered baseline into the strict packet model (lossless)."""
    return [
        TSPacket.from_bytes(ts_bytes[i : i + 188])
        for i in range(0, len(ts_bytes), 188)
    ]


class TestSlotPreservingInvariant:
    """SPEC-204 §7: shared packet frame, equal counts, declared-only diffs."""

    @pytest.mark.parametrize("vector_id", sorted(ORACLE_PAIRS))
    def test_baseline_and_faulted_share_the_packet_frame(
        self, golden_loader, vector_id: str
    ) -> None:
        baseline = golden_loader.load(f"{vector_id}-baseline")
        faulted_golden = golden_loader.load(vector_id)
        baseline_packets = baseline_packets_of(baseline.ts_bytes)
        faulted_packets = baseline_packets_of(faulted_golden.ts_bytes)
        # (1) equal slot count and 188 alignment → byte_count == n × 188
        assert len(baseline_packets) == len(faulted_packets)
        assert len(faulted_golden.ts_bytes) % 188 == 0
        # (2) same index → same slot: PID/CC-affine header identity holds on
        # untouched slots; every changed slot is a declared transform slot.
        spec_filter = build_semantic_filter_factory()(
            (ORACLE_PAIRS[vector_id](),), golden_geometry_config()
        )
        declared = set()
        for index, packet in enumerate(baseline_packets):
            mutated = spec_filter.apply(index, packet)
            if mutated.to_bytes() != packet.to_bytes():
                declared.add(index)
        golden_diff = {
            index
            for index, (b, f) in enumerate(
                zip(baseline_packets, faulted_packets)
            )
            if b.to_bytes() != f.to_bytes()
        }
        assert golden_diff == declared
        # CBR: every slot serializes to exactly 188 bytes on both streams.
        for packet in faulted_packets:
            assert len(packet.to_bytes()) == 188

    def test_activation_index_addresses_the_same_slot_in_both_streams(
        self, golden_loader
    ) -> None:
        """AC-204-07 frozen definition: packet_index injection is stable —
        the CC golden activation (index 30) and its landing (50) address the
        same slots on both streams (oracle expectations parity)."""
        faulted_golden = golden_loader.load("cc-discontinuity")
        expectations = faulted_golden.expectations
        landing = expectations[0]["locator"]["packet_index"]
        baseline_packets = baseline_packets_of(
            golden_loader.load("cc-discontinuity-baseline").ts_bytes
        )
        assert baseline_packets[landing].pid == 0x0100
        assert baseline_packets[landing].payload is not None
        detail = expectations[0]["detail"]
        assert detail["expected_cc"] == baseline_packets[landing].continuity_counter


class TestFilterOnGeneratorOutput:
    """The filter must also be oracle-identical when driven from the real
    generator chain (not only parsed golden bytes)."""

    @pytest.mark.parametrize("vector_id", ["pat-missing", "cc-discontinuity"])
    def test_generator_driven_output_matches_golden(
        self, golden_loader, vector_id: str
    ) -> None:
        faulted_golden = golden_loader.load(vector_id)
        plan = (ORACLE_PAIRS[vector_id](),)
        config: GeneratorConfig = golden_geometry_config()
        spec_filter = build_semantic_filter_factory()(plan, config)
        packets = golden_baseline_packets()
        output = _faulted_bytes(spec_filter, packets)
        assert output == faulted_golden.ts_bytes
