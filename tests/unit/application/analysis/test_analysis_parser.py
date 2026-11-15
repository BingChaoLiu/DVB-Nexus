"""The analysis-bridge parser facts over the golden geometry (ticket #58).

The parser (``application.analysis.parser``) is the PURE semantic-layer
half of the 裁定 A analysis bridge: real artifact bytes + the run's
generator config in, deterministic facts out (no I/O, no wall clock, no
publisher). The four pinned signal families (SPEC-204 §6 symptom
families / SPEC-307 §6 expected evidence):

- PAT presence supervision (pat-missing family),
- PMT CRC verification (pmt-invalid-crc family),
- PAT↔PMT mapping declaration facts (pmt-pid-mismatch family),
- continuity-counter sequence (cc-discontinuity family).

The golden fault pairs are the oracle: the faulted variants here are
produced by the PRODUCTION semantic filter chain (the same chain the e2e
loops drive over REST), whose golden-pair byte equality is pinned in
``tests/conformance/test_faulted_pairs.py`` and re-proven end to end by
the e2e suite.
"""

from __future__ import annotations

import pytest

from faults.definition import FaultActivation, FaultDefinition
from faults.factory import create_fault_filter
from ts.packet import TSPacket

from application.analysis.parser import (
    BatchFact,
    ContinuityErrorFact,
    PatMissingFact,
    PatSectionFact,
    PmtSectionFact,
    analyze_transport_stream,
)
from tests._support.fault_lab_materials import (
    generate_golden_geometry_bytes,
    golden_geometry_config,
)

pytestmark = pytest.mark.unit

#: The conformance-layer frame facts of the frozen golden bytes
#: (tests/conformance/test_faulted_pairs.py top constants — mirrored here
#: as the parser expectations; the byte identity itself is the e2e's
#: golden SHA oracle).
PAT_MISSING_ACTIVATION = 202
CC_DISCONTINUITY_ACTIVATION = 30
CC_DISCONTINUITY_LANDING = 50
CC_DISCONTINUITY_DELTA = 3
PMT_PID_MISMATCH_WRONG_PID = 4100


def _baseline_bytes() -> bytes:
    return generate_golden_geometry_bytes()


def _faulted_bytes(fault: FaultDefinition) -> bytes:
    """Run the PRODUCTION semantic filter over the baseline bytes."""
    config = golden_geometry_config()
    packets = [
        TSPacket.from_bytes(_baseline_bytes()[offset : offset + 188])
        for offset in range(0, len(_baseline_bytes()), 188)
    ]
    filt = create_fault_filter((fault,), config, run_id="run-parser")
    return b"".join(
        filt.apply(index, packet).to_bytes()
        for index, packet in enumerate(packets)
    )


def _fault(
    fault_type: str,
    pid: int,
    parameters: dict,
    packet_index: int,
) -> FaultDefinition:
    return FaultDefinition(
        fault_id="fd000000-0000-4000-8000-000000000001",
        fault_type=fault_type,
        target_id=f"mux-0:pid:0x{pid:04x}",
        parameters=parameters,
        activation=FaultActivation(
            kind="packet_index", packet_index=packet_index
        ),
        expected_observations=("ts.psi_section_observed",),
    )


# --- slice 1: clean-stream facts -----------------------------------------------


class TestCleanStreamFacts:
    def test_baseline_yields_three_pat_and_three_pmt_facts(self):
        facts = analyze_transport_stream(
            _baseline_bytes(), golden_geometry_config()
        )
        pat = [f for f in facts if isinstance(f, PatSectionFact)]
        pmt = [f for f in facts if isinstance(f, PmtSectionFact)]
        assert [f.packet_index for f in pat] == [0, 202, 404]
        assert [f.packet_index for f in pmt] == [1, 206, 412]
        assert all(f.crc_valid for f in pat + pmt)
        assert all(f.program_map_pids == (4096,) for f in pat)
        assert not [f for f in facts if isinstance(f, PatMissingFact)]
        assert not [f for f in facts if isinstance(f, ContinuityErrorFact)]

    def test_psi_repetition_gaps_follow_the_declared_periods(self):
        facts = analyze_transport_stream(
            _baseline_bytes(), golden_geometry_config()
        )
        pat = [f for f in facts if isinstance(f, PatSectionFact)]
        pmt = [f for f in facts if isinstance(f, PmtSectionFact)]
        assert pat[0].gap_ms is None  # first instance anchors the schedule
        assert [f.gap_ms for f in pat[1:]] == [101, 101]
        # PMT rides the offset-1 schedule: first-to-second gap is 205
        # slots (102.5 ms, integer-ms truncated), second-to-third 206
        # slots (103 ms) — frozen-frame facts of the golden geometry.
        assert [f.gap_ms for f in pmt[1:]] == [102, 103]

    def test_batch_fact_reports_stream_coverage(self):
        facts = analyze_transport_stream(
            _baseline_bytes(), golden_geometry_config()
        )
        batches = [f for f in facts if isinstance(f, BatchFact)]
        assert len(batches) == 1
        batch = batches[0]
        assert batch.packet_count == 600
        assert batch.byte_count == 600 * 188
        assert batch.duration_ns == 600 * 500_000  # 0.5 ms slots
        assert batch.continuity_error_count == 0
        # The CBR mux stuffs the unfilled program rate with null packets —
        # recounted independently from the baseline bytes.
        nulls = sum(
            1
            for offset in range(0, len(_baseline_bytes()), 188)
            if TSPacket.from_bytes(
                _baseline_bytes()[offset : offset + 188]
            ).pid
            == 0x1FFF
        )
        assert batch.null_packet_count == nulls
        assert nulls > 0

    def test_null_packets_and_psi_pids_are_cc_exempt(self):
        """The generator emits CC=0 on every PSI retransmission
        (SPEC-108 PSI-burst convention) and CC-carrying null packets on
        0x1FFF; the supervision family covers the ES PIDs only — the
        clean stream must produce ZERO continuity errors."""
        facts = analyze_transport_stream(
            _baseline_bytes(), golden_geometry_config()
        )
        assert not [f for f in facts if isinstance(f, ContinuityErrorFact)]


# --- slice 2: PAT_MISSING supervision ------------------------------------------


class TestPatMissingSupervision:
    def test_null_substituted_windows_report_present_missing(self):
        fault = _fault("PAT_MISSING", 0x0000, {}, PAT_MISSING_ACTIVATION)
        facts = analyze_transport_stream(
            _faulted_bytes(fault), golden_geometry_config()
        )
        missing = [f for f in facts if isinstance(f, PatMissingFact)]
        # Slot 0 (pre-activation) stays; 202 and 404 are null-substituted.
        assert [f.packet_index for f in missing] == [202, 404]

    def test_pre_activation_pat_survives_as_a_present_fact(self):
        fault = _fault("PAT_MISSING", 0x0000, {}, PAT_MISSING_ACTIVATION)
        facts = analyze_transport_stream(
            _faulted_bytes(fault), golden_geometry_config()
        )
        present = [f for f in facts if isinstance(f, PatSectionFact)]
        assert [f.packet_index for f in present] == [0]


# --- slice 3: PMT CRC supervision -----------------------------------------------


class TestPmtCrcSupervision:
    def test_inverted_crc_instances_report_crc_invalid(self):
        fault = _fault(
            "PMT_INVALID_CRC",
            0x1000,
            {"mode": "persistent", "corruption": "invert"},
            1,
        )
        facts = analyze_transport_stream(
            _faulted_bytes(fault), golden_geometry_config()
        )
        bad = [
            f
            for f in facts
            if isinstance(f, PmtSectionFact) and not f.crc_valid
        ]
        assert [f.packet_index for f in bad] == [1, 206, 412]

    def test_pat_instances_stay_valid_on_the_crc_fault_stream(self):
        fault = _fault(
            "PMT_INVALID_CRC",
            0x1000,
            {"mode": "persistent", "corruption": "invert"},
            1,
        )
        facts = analyze_transport_stream(
            _faulted_bytes(fault), golden_geometry_config()
        )
        pat = [f for f in facts if isinstance(f, PatSectionFact)]
        assert [f.packet_index for f in pat] == [0, 202, 404]


# --- slice 4: CC sequence supervision -------------------------------------------


class TestContinuitySupervision:
    def test_relative_offset_lands_one_error_at_the_shared_frame_slot(self):
        fault = _fault(
            "CC_DISCONTINUITY", 0x0100, {"delta": CC_DISCONTINUITY_DELTA},
            CC_DISCONTINUITY_ACTIVATION,
        )
        facts = analyze_transport_stream(
            _faulted_bytes(fault), golden_geometry_config()
        )
        errors = [f for f in facts if isinstance(f, ContinuityErrorFact)]
        assert len(errors) == 1
        error = errors[0]
        assert error.packet_index == CC_DISCONTINUITY_LANDING
        assert error.pid == 256
        # The golden expectations detail (expected 1 → actual 4, delta 3):
        # expected derives from the FAULTED stream's own previous CC.
        assert error.expected_cc == 1
        assert error.actual_cc == 4

    def test_psi_pid_fault_streams_stay_cc_clean(self):
        """The PSI-PID faults must not fabricate continuity symptoms."""
        for fault in (
            _fault("PAT_MISSING", 0x0000, {}, PAT_MISSING_ACTIVATION),
            _fault(
                "PMT_INVALID_CRC", 0x1000,
                {"mode": "persistent", "corruption": "invert"}, 1,
            ),
            _fault(
                "PMT_PID_MISMATCH", 0x0000, {"wrong_pmt_pid": 4100}, 0
            ),
        ):
            facts = analyze_transport_stream(
                _faulted_bytes(fault), golden_geometry_config()
            )
            assert not [
                f for f in facts if isinstance(f, ContinuityErrorFact)
            ], fault.fault_type


# --- slice 5: mapping declaration facts ------------------------------------------


class TestMappingDeclarationFacts:
    def test_pat_facts_carry_the_declared_program_map_pid(self):
        facts = analyze_transport_stream(
            _baseline_bytes(), golden_geometry_config()
        )
        pat = [f for f in facts if isinstance(f, PatSectionFact)]
        assert all(f.program_map_pids == (4096,) for f in pat)

    def test_repointed_pat_declares_the_wrong_pid(self):
        fault = _fault(
            "PMT_PID_MISMATCH", 0x0000, {"wrong_pmt_pid": 4100}, 0
        )
        facts = analyze_transport_stream(
            _faulted_bytes(fault), golden_geometry_config()
        )
        pat = [f for f in facts if isinstance(f, PatSectionFact)]
        assert len(pat) == 3
        assert all(
            f.program_map_pids == (PMT_PID_MISMATCH_WRONG_PID,) for f in pat
        )
        # The real PMT stays on 4096 (orphaned by the repointing) and its
        # sections still verify — the declaration is what contradicts.
        pmt = [f for f in facts if isinstance(f, PmtSectionFact)]
        assert [f.packet_index for f in pmt] == [1, 206, 412]
        assert all(f.crc_valid for f in pmt)
