"""Fault-lab shared materials (ticket #58, the four golden fault pairs).

The frozen generator geometry of the four golden fault pairs
(``tools/make_golden_baseline.py`` GEOMETRY — ticket #34 pull-safe
examples; SPEC-506 §7 #7-#10). This module is the sanctioned
shared-constructor area for the #58 fault-lab tests: both the unit-layer
analysis-bridge tests and the e2e fault-lab loops build their runs from
this ONE config so a drift shows up as the golden SHA oracle failing
(the registered sha256 is the vector identity — SPEC-506 §6).

Byte discipline (tests/README §5): TS bytes in the fault-lab tests come
from the real SPEC-108 generator chain driven by THIS config (source 2:
deterministic fixed-seed construction); the faulted variants come from
the production semantic filter chain; the golden trios themselves load
through the ``golden_loader`` fixture. Nothing here assembles bytes.
"""

from __future__ import annotations

from typing import Any

from ts.generator.config import (
    ElementaryStreamConfig,
    GeneratorConfig,
    ProgramConfig,
)

#: The frozen pull-safe geometry (tools/make_golden_baseline.py GEOMETRY):
#: B = 3 008 000 (0.5 ms slots), 600 packets, PAT 101 ms / PMT 103 ms /
#: PCR 40 ms, ES1 = B/25 on PID 256 (PCR carrier), ES2 = B/50 on PID 257,
#: PMT on 4096, seed 1234567.
GOLDEN_GEOMETRY: dict[str, Any] = {
    "schema_version": 1,
    "profile": "analysis_only",
    "deterministic": True,
    "seed": 1234567,
    "initial_media_clock_27mhz": 0,
    "target_bitrate_bps": 3_008_000,
    "output_packet_count": 600,
    "pat_period_ms": 101,
    "pmt_period_ms": 103,
    "pcr_interval_ms": 40,
    "pcr_insertion_policy": "payload_packet_first",
    "transport_stream_id": 1,
    "program_number": 1,
    "pmt_pid": 4096,
    "pcr_pid": 256,
    "version_number": 0,
    "es1": {
        "pid": 256,
        "stream_type": 27,
        "stream_id": 0xE0,
        "bitrate_bps": 120_320,
        "payload_profile": "synthetic_test_data",
        "payload_seed_offset": 0,
    },
    "es2": {
        "pid": 257,
        "stream_type": 3,
        "stream_id": 0xC0,
        "bitrate_bps": 60_160,
        "payload_profile": "synthetic_test_data",
        "payload_seed_offset": 1,
    },
}

#: The mux node id the fault-lab scenarios attribute their fault targets
#: to (the scenario initial_topology node; ADR-0006 decision 3 slug).
FAULT_LAB_NODE_ID = "mux-0"


def golden_geometry_config() -> GeneratorConfig:
    """The frozen geometry as the domain :class:`GeneratorConfig`."""
    geometry = GOLDEN_GEOMETRY
    program = ProgramConfig(
        transport_stream_id=geometry["transport_stream_id"],
        program_number=geometry["program_number"],
        pmt_pid=geometry["pmt_pid"],
        pcr_pid=geometry["pcr_pid"],
        version_number=geometry["version_number"],
        streams=(
            ElementaryStreamConfig(**geometry["es1"]),
            ElementaryStreamConfig(**geometry["es2"]),
        ),
        program_descriptors=b"",
    )
    return GeneratorConfig(
        schema_version=geometry["schema_version"],
        profile=geometry["profile"],
        deterministic=geometry["deterministic"],
        seed=geometry["seed"],
        initial_media_clock_27mhz=geometry["initial_media_clock_27mhz"],
        target_bitrate_bps=geometry["target_bitrate_bps"],
        output_packet_count=geometry["output_packet_count"],
        program=program,
        pat_period_ms=geometry["pat_period_ms"],
        pmt_period_ms=geometry["pmt_period_ms"],
        pcr_interval_ms=geometry["pcr_interval_ms"],
        pcr_insertion_policy=geometry["pcr_insertion_policy"],
    )


def golden_geometry_wire_config() -> dict[str, Any]:
    """The frozen geometry as the SPEC-108 §4 wire body (bytes → hex)."""
    from bootstrap.backends import wire_generator_config

    return wire_generator_config(golden_geometry_config())


def generate_golden_geometry_bytes() -> bytes:
    """Run the real generator over the frozen geometry (deterministic)."""
    from ts.generator.generator import TSGenerator

    class _Sink:
        def __init__(self) -> None:
            self.chunks: list[bytes] = []

        def write(self, data: bytes) -> int:
            self.chunks.append(bytes(data))
            return len(data)

    sink = _Sink()
    TSGenerator().generate_to(golden_geometry_config(), sink)
    return b"".join(sink.chunks)
