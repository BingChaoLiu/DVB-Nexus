"""SPEC-506 §7 #7-#10 — baseline golden vector constructor (TS Core).

The four faulted pairs (``pat-missing`` / ``pmt-invalid-crc`` /
``cc-discontinuity`` / ``pmt-pid-mismatch``, #14) each pair a faulted
stream with its **baseline**: a clean TS Core Generator run (SPEC-108,
ticket #34) using the hand-proven pull-safe geometry of the #34 examples
(B = 3 008 000 ⇒ 0.5 ms slots; PAT 101 ms / PMT 103 ms / PCR 40 ms;
ES1 = B/25 on PID 256 carrying PCR, ES2 = B/50 on PID 257; N = 600).

Baseline verification path (SPEC-506 §5, L2): **self-generate →
tsduck-analyze** — ``tsanalyze`` on the registered bytes reports a clean
stream with the expected PID table (see the baseline verification note).
The faulted half of each pair is produced by the *independent* transform
script (``tools/golden_fault_transform.py``, no ``src/ts`` import), never
by this script.

Determinism (SPEC-108 §8 / SPEC-506 §6): the Generator consumes no wall
clock and the config is frozen; identical config ⇒ byte-identical output.
The registered sha256 is the vector identity.

Usage::

    python tools/make_golden_baseline.py <fault_id> --output-dir <golden root>

writes ``<dir>/<fault_id>-baseline/`` (SPEC-506 §3 trio).
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

FAULT_IDS = (
    "pat-missing",
    "pmt-invalid-crc",
    "cc-discontinuity",
    "pmt-pid-mismatch",
)

#: The frozen pull-safe geometry (ticket #34 examples, tests/unit/ts/
#: test_generator.py module docstring).  All values are hand-proven for the
#: frozen SPEC-107 deadline window.
GEOMETRY = {
    "schema_version": 1,
    "profile": "analysis_only",
    "deterministic": True,
    "seed": 1234567,
    "initial_media_clock_27mhz": 0,
    "target_bitrate_bps": 3_008_000,  # slot = 13 500 ticks = 0.5 ms exactly
    "output_packet_count": 600,
    "pat_period_ms": 101,  # 202 slots
    "pmt_period_ms": 103,  # 206 slots
    "pcr_interval_ms": 40,  # 80 slots
    "pcr_insertion_policy": "payload_packet_first",
    "program": {
        "transport_stream_id": 1,
        "program_number": 1,
        "pmt_pid": 4096,
        "pcr_pid": 256,  # rides ES1 (allowed reuse, SPEC-108 §5)
        "version_number": 0,
        "streams": [
            {
                "pid": 256,
                "stream_type": 27,  # 0x1B AVC — declaration matches config
                "stream_id": 0xE0,
                "bitrate_bps": 120_320,  # B/25
                "payload_profile": "synthetic_test_data",
                "payload_seed_offset": 0,
            },
            {
                "pid": 257,
                "stream_type": 3,  # 0x03 MPEG-1 audio
                "stream_id": 0xC0,
                "bitrate_bps": 60_160,  # B/50
                "payload_profile": "synthetic_test_data",
                "payload_seed_offset": 1,
            },
        ],
        "program_descriptors": "",
    },
}

GENERATOR_VERSION = "dvb-nexus-ts-generator/0.5.0 (SPEC-108)"


def build_config():
    """The frozen :class:`ts.generator.config.GeneratorConfig`."""
    from ts.generator.config import (
        ElementaryStreamConfig,
        GeneratorConfig,
        ProgramConfig,
    )

    program = ProgramConfig(
        transport_stream_id=GEOMETRY["program"]["transport_stream_id"],
        program_number=GEOMETRY["program"]["program_number"],
        pmt_pid=GEOMETRY["program"]["pmt_pid"],
        pcr_pid=GEOMETRY["program"]["pcr_pid"],
        version_number=GEOMETRY["program"]["version_number"],
        streams=tuple(
            ElementaryStreamConfig(**stream)
            for stream in GEOMETRY["program"]["streams"]
        ),
        program_descriptors=b"",
    )
    return GeneratorConfig(
        schema_version=GEOMETRY["schema_version"],
        profile=GEOMETRY["profile"],
        deterministic=GEOMETRY["deterministic"],
        seed=GEOMETRY["seed"],
        initial_media_clock_27mhz=GEOMETRY["initial_media_clock_27mhz"],
        target_bitrate_bps=GEOMETRY["target_bitrate_bps"],
        output_packet_count=GEOMETRY["output_packet_count"],
        program=program,
        pat_period_ms=GEOMETRY["pat_period_ms"],
        pmt_period_ms=GEOMETRY["pmt_period_ms"],
        pcr_interval_ms=GEOMETRY["pcr_interval_ms"],
        pcr_insertion_policy=GEOMETRY["pcr_insertion_policy"],
    )


def build_bytes() -> bytes:
    from ts.generator.generator import TSGenerator

    class _Sink:
        def __init__(self) -> None:
            self.chunks: list[bytes] = []

        def write(self, data: bytes) -> int:
            self.chunks.append(bytes(data))
            return len(data)

    sink = _Sink()
    TSGenerator().generate_to(build_config(), sink)
    return b"".join(sink.chunks)


def build_expectations() -> dict:
    """Baseline structure pins (facts of the frozen bytes; the faulted
    transforms and the pair tests share this packet-order frame, ADR-0007
    第 4 条)."""
    return {
        "expectations": [
            {
                "event_type": "ts.psi_section_observed",
                "locator": {"pid": 0},
                "detail": {
                    "table_id": 0,
                    "transport_stream_id": 1,
                    "programs": [{"program_number": 1, "pmt_pid": 4096}],
                    "packet_index": [0, 202, 404],
                },
            },
            {
                "event_type": "ts.psi_section_observed",
                "locator": {"pid": 4096},
                "detail": {
                    "table_id": 2,
                    "service_id": 1,
                    "pcr_pid": 256,
                    "streams": [
                        {"stream_type": 27, "pid": 256},
                        {"stream_type": 3, "pid": 257},
                    ],
                    "packet_index": [1, 206, 412],
                },
            },
            {
                "event_type": "ts.packet_batch_observed",
                "locator": {"pid": 256, "packet_index": 25},
                "detail": {"cc": 0, "note": "first ES1 payload packet"},
            },
            {
                "event_type": "ts.packet_batch_observed",
                "locator": {"pid": 256, "packet_index": 80},
                "detail": {"afc": 2, "pcr_present": True, "note": "PCR carrier"},
            },
        ]
    }


def build_manifest(vector_id: str, sha256: str, config_hash: str) -> dict:
    return {
        "vector_id": vector_id,
        "kind": "generated_ts",
        "related_specs": ["SPEC-108", "SPEC-204"],
        "generator_version": GENERATOR_VERSION,
        "config_hash": f"sha256:{config_hash}",
        "sha256": f"sha256:{sha256}",
        "packet_count": GEOMETRY["output_packet_count"],
        "fault_plan_ref": None,
        "verification": {
            "path": "tsduck-cross",
            "direction": "self-generate→tsduck-analyze",
            "evidence_ref": (
                f"docs/test-vectors/golden/{vector_id}/{vector_id}.verification.md"
            ),
        },
    }


def write_trio(output_dir: Path, fault_id: str) -> Path:
    ts_bytes = build_bytes()
    sha256 = hashlib.sha256(ts_bytes).hexdigest()
    config_hash = hashlib.sha256(
        json.dumps(GEOMETRY, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    vector_id = f"{fault_id}-baseline"
    base = output_dir / vector_id
    base.mkdir(parents=True, exist_ok=True)
    (base / f"{vector_id}.ts").write_bytes(ts_bytes)
    (base / "manifest.json").write_text(
        json.dumps(build_manifest(vector_id, sha256, config_hash),
                   indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (base / "expectations.json").write_text(
        json.dumps(build_expectations(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return base


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("fault_id", choices=FAULT_IDS)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    base = write_trio(Path(args.output_dir), args.fault_id)
    ts_bytes = build_bytes()
    print(f"{args.fault_id}-baseline: {len(ts_bytes)} bytes, "
          f"sha256={hashlib.sha256(ts_bytes).hexdigest()}")
    print(f"trio written under {base}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
