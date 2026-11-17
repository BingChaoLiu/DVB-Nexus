"""Programmatic builders for the SPEC-204 fault-transform tests (#44).

Byte discipline (tests/README.md section 5): every TS byte in these tests
comes from the real SPEC-108 generator chain driven by the **frozen golden
geometry** — the same config ``tools/make_golden_baseline.py`` used to
produce the registered fault-pair baselines (SPEC-506 §7, #14).  Nothing
is hand-assembled; the four fault ``FaultDefinition`` builders mirror the
frozen golden fault parameters recorded in the faulted vectors'
manifests (``tools/golden_fault_transform.py`` FAULT_PARAMS, SPEC-204 §6
schema v1).

Owned by ticket #44 (SIM-E) — thin test-construction seam in the
``tests/_support``-adjacent style of the #43 ``_ts_runtime_builders``.
"""

from __future__ import annotations

from ts.generator.config import (
    ElementaryStreamConfig,
    GeneratorConfig,
    ProgramConfig,
)
from ts.generator.generator import TSGenerator
from ts.packet import TSPacket

from faults.definition import FaultActivation, FaultDefinition

# --- frozen golden geometry (tools/make_golden_baseline.py GEOMETRY) ---------

GOLDEN_BASELINE_SHA256 = (
    # All four registered baselines share this digest.
    "b0afe1ef6068b9f1f0d3ed788cbaaf95d48f4f23bc1c7f8623895de6888a8f4c"
)

#: PAT/PMT pids of the frozen geometry (single program).
GOLDEN_PAT_PID = 0x0000
GOLDEN_PMT_PID = 0x1000
#: ES1 rides PCR (the allowed reuse); the CC_DISCONTINUITY golden target.
GOLDEN_ES1_PID = 0x0100
GOLDEN_ES2_PID = 0x0101

#: Golden packet frame: 600 slots; PAT at 0/202/404, PMT at 1/206/412.
GOLDEN_PACKET_COUNT = 600


def golden_geometry_config() -> GeneratorConfig:
    """The frozen pull-safe geometry (hand-proven for SPEC-107 deadlines)."""
    program = ProgramConfig(
        transport_stream_id=1,
        program_number=1,
        pmt_pid=GOLDEN_PMT_PID,
        pcr_pid=GOLDEN_ES1_PID,
        version_number=0,
        streams=(
            ElementaryStreamConfig(
                pid=GOLDEN_ES1_PID,
                stream_type=27,
                stream_id=0xE0,
                bitrate_bps=120_320,
                payload_seed_offset=0,
            ),
            ElementaryStreamConfig(
                pid=GOLDEN_ES2_PID,
                stream_type=3,
                stream_id=0xC0,
                bitrate_bps=60_160,
                payload_seed_offset=1,
            ),
        ),
        program_descriptors=b"",
    )
    return GeneratorConfig(
        schema_version=1,
        profile="analysis_only",
        deterministic=True,
        seed=1234567,
        initial_media_clock_27mhz=0,
        target_bitrate_bps=3_008_000,
        output_packet_count=GOLDEN_PACKET_COUNT,
        program=program,
        pat_period_ms=101,
        pmt_period_ms=103,
        pcr_interval_ms=40,
        pcr_insertion_policy="payload_packet_first",
    )


def golden_baseline_packets() -> tuple[TSPacket, ...]:
    """The deterministic baseline packet frame (generator-driven bytes)."""
    generator = TSGenerator()
    return tuple(generator.iter_packets(golden_geometry_config()))


# --- golden fault definitions (SPEC-204 §6 v1, golden manifests) --------------


def pat_missing_fault() -> FaultDefinition:
    return FaultDefinition(
        fault_id="fault-pat-missing",
        fault_type="PAT_MISSING",
        target_id="demux-0:pid:0x0000",
        parameters={},
        activation=FaultActivation(kind="packet_index", packet_index=202),
        expected_observations=("ts.psi_section_observed",),
    )


def pmt_invalid_crc_fault(
    *, mode: str = "persistent", corruption: str = "invert"
) -> FaultDefinition:
    return FaultDefinition(
        fault_id="fault-pmt-invalid-crc",
        fault_type="PMT_INVALID_CRC",
        target_id="demux-0:pid:0x1000",
        parameters={"mode": mode, "corruption": corruption},
        activation=FaultActivation(kind="packet_index", packet_index=1),
        expected_observations=("ts.psi_section_observed",),
    )


def cc_discontinuity_fault(
    *, delta: int = 3, packet_index: int | None = 30
) -> FaultDefinition:
    return FaultDefinition(
        fault_id="fault-cc-discontinuity",
        fault_type="CC_DISCONTINUITY",
        target_id="demux-0:pid:0x0100",
        parameters={"delta": delta},
        activation=FaultActivation(
            kind="packet_index" if packet_index is not None else "session_start",
            packet_index=packet_index,
        ),
        expected_observations=("ts.continuity_error",),
    )


def pmt_pid_mismatch_fault(*, wrong_pmt_pid: int = 4100) -> FaultDefinition:
    return FaultDefinition(
        fault_id="fault-pmt-pid-mismatch",
        fault_type="PMT_PID_MISMATCH",
        target_id="demux-0:pid:0x0000",
        parameters={"wrong_pmt_pid": wrong_pmt_pid},
        activation=FaultActivation(kind="packet_index", packet_index=0),
        expected_observations=("ts.psi_section_observed",),
    )


def pmt_pid_drift_fault(
    *,
    new_pid_map: dict | None = None,
    pmt_version_bump: bool = True,
    packet_index: int = 100,
) -> FaultDefinition:
    """The SC-09-shaped drift fault (SPEC-204 §Phase2 item 4).

    Defaults carry the SC-09 wire's declaration face (the digit-string key
    program 1 → drifted pmt_pid 4608) on the PMT stream target, but the
    unit layer drives a generic mid-stream activation index (100, not the
    frozen pack's 400) and a single observation symbol — the frozen lab
    pack wire itself stays pinned by tests/integration/simulation/
    test_lab_pack_v2.py::test_sc09_fault_face.
    """
    return FaultDefinition(
        fault_id="fault-pmt-pid-drift",
        fault_type="PMT_PID_DRIFT",
        target_id="demux-0:pid:0x1000",
        parameters={
            "new_pid_map": (
                {"1": 4608} if new_pid_map is None else new_pid_map
            ),
            "pmt_version_bump": pmt_version_bump,
        },
        activation=FaultActivation(
            kind="packet_index", packet_index=packet_index
        ),
        expected_observations=("ts.psi_section_observed",),
    )
