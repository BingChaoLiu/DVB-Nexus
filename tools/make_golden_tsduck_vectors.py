"""SPEC-506 §7 #2/#3 — golden vector constructors ``pat-minimal`` /
``pat-pmt-multi`` (TSDuck tsxml → tstabcomp → tsp inject).

L2 verification path (SPEC-506 §5/#14 Q1): **tsduck-generate→self-parse**
— the bytes are produced by TSDuck (tstabcomp compiles the reviewed tsxml
sources in ``tools/tsduck-tsxml/``, ``tsp -I null -P inject`` builds the
null-padded TS), and the conformance tests parse them with the self
parser.  ``generator_version``/``config_hash`` are provenance records
(#14 Q8: TSDuck version changes never invalidate a registered vector —
the sha256 is the identity).

The tested command chain (ticket #3 实测, docs/research/tsduck-env.md)::

    tstabcomp <xml> <bin>
    tsp -I null <N> -P inject -p <PID> --inter-packet 100 --stuffing <bin> \\
        [-P inject ...] -O file <out.ts>

Usage::

    python tools/make_golden_tsduck_vectors.py <pat-minimal|pat-pmt-multi> \\
        --output-dir <golden root>

Requires ``tstabcomp``/``tsp`` on PATH (or ``DVB_NEXUS_TSP_PATH`` pointing
at the TSDuck bin directory).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

VECTOR_IDS = ("pat-minimal", "pat-pmt-multi")

#: Injected table PIDs (also the expectations locators).
PAT_PID = 0x0000
PMT1_PID = 0x1000
PMT2_PID = 0x1100


def _tsduck_bin() -> Path | None:
    """TSDuck bin directory override (DVB_NEXUS_TSP_PATH), else PATH."""
    override = os.environ.get("DVB_NEXUS_TSP_PATH")
    if override:
        path = Path(override)
        return path if path.is_dir() else path.parent
    found = shutil.which("tsp")
    return Path(found).parent if found else None


def _run(tool_dir: Path | None, argv: list[str]) -> None:
    exe = argv[0]
    if tool_dir is not None and (tool_dir / f"{exe}.exe").is_file():
        argv = [str(tool_dir / f"{exe}.exe"), *argv[1:]]
    result = subprocess.run(argv, capture_output=True)
    if result.returncode != 0:
        raise SystemExit(
            f"{exe} failed ({result.returncode}): "
            f"{result.stderr.decode('utf-8', 'replace')}"
        )


def _tsp_version(tool_dir: Path | None) -> str:
    exe = ["tsp", "--version"]
    if tool_dir is not None and (tool_dir / "tsp.exe").is_file():
        exe = [str(tool_dir / "tsp.exe"), "--version"]
    result = subprocess.run(exe, capture_output=True)
    line = result.stdout.decode("utf-8", "replace").strip()
    return line.split(" - ")[-1] if line else "unknown"


# --- vector definitions -------------------------------------------------------


def pat_minimal_plan() -> dict:
    return {
        "packet_count": 50,
        "tables": [
            {"xml": "pat-minimal-pat.xml", "pid": PAT_PID},
            {"xml": "pat-minimal-pmt.xml", "pid": PMT1_PID},
        ],
        "related_specs": ["SPEC-103", "SPEC-108"],
        "expectations": {
            "expectations": [
                {
                    "event_type": "ts.psi_section_observed",
                    "locator": {"pid": PAT_PID},
                    "detail": {
                        "table_id": 0,
                        "transport_stream_id": 1,
                        "programs": [
                            {"program_number": 1, "pmt_pid": 0x1000}
                        ],
                        "packet_index": 0,
                    },
                },
                {
                    "event_type": "ts.psi_section_observed",
                    "locator": {"pid": PMT1_PID},
                    "detail": {
                        "table_id": 2,
                        "service_id": 1,
                        "pcr_pid": 0x0100,
                        "streams": [
                            {"stream_type": 0x1B, "pid": 0x0101}
                        ],
                        "packet_index": 1,
                    },
                },
            ]
        },
    }


def pat_pmt_multi_plan() -> dict:
    return {
        "packet_count": 60,
        "tables": [
            {"xml": "pat-multi-pat.xml", "pid": PAT_PID},
            {"xml": "pat-multi-pmt1.xml", "pid": PMT1_PID},
            {"xml": "pat-multi-pmt2.xml", "pid": PMT2_PID},
        ],
        "related_specs": ["SPEC-103", "SPEC-108"],
        "expectations": {
            "expectations": [
                {
                    "event_type": "ts.psi_section_observed",
                    "locator": {"pid": PAT_PID},
                    "detail": {
                        "table_id": 0,
                        "transport_stream_id": 1,
                        "programs": [
                            {"program_number": 1, "pmt_pid": 0x1000},
                            {"program_number": 2, "pmt_pid": 0x1100},
                        ],
                        "packet_index": 0,
                    },
                },
                {
                    "event_type": "ts.psi_section_observed",
                    "locator": {"pid": PMT1_PID},
                    "detail": {
                        "table_id": 2,
                        "service_id": 1,
                        "pcr_pid": 0x0100,
                        "streams": [
                            {"stream_type": 0x1B, "pid": 0x0101},
                            {"stream_type": 0x0F, "pid": 0x0102},
                        ],
                        "packet_index": 1,
                    },
                },
                {
                    "event_type": "ts.psi_section_observed",
                    "locator": {"pid": PMT2_PID},
                    "detail": {
                        "table_id": 2,
                        "service_id": 2,
                        "pcr_pid": 0x0110,
                        "streams": [
                            {"stream_type": 0x02, "pid": 0x0111},
                            {"stream_type": 0x03, "pid": 0x0112},
                        ],
                        "packet_index": 2,
                    },
                },
            ]
        },
    }


PLANS = {
    "pat-minimal": pat_minimal_plan,
    "pat-pmt-multi": pat_pmt_multi_plan,
}


def build_vector(vector_id: str, output_dir: Path, tool_dir: Path | None,
                 xml_dir: Path) -> str:
    """Run the tested TSDuck chain and register the trio. Returns sha256."""
    plan = PLANS[vector_id]()
    ts_path = output_dir / vector_id / f"{vector_id}.ts"
    ts_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        inject_args: list[str] = []
        for table in plan["tables"]:
            xml = xml_dir / table["xml"]
            binary = tmp_dir / (xml.stem + ".bin")
            _run(tool_dir, ["tstabcomp", "--output", str(binary), str(xml)])
            inject_args += [
                "-P", "inject", "-p", hex(table["pid"]),
                "--inter-packet", "100", "--stuffing", str(binary),
            ]
        _run(
            tool_dir,
            ["tsp", "-I", "null", str(plan["packet_count"]),
             *inject_args, "-O", "file", str(ts_path)],
        )
    size = ts_path.stat().st_size
    assert size == plan["packet_count"] * 188, (size, plan["packet_count"])
    sha256 = hashlib.sha256(ts_path.read_bytes()).hexdigest()

    xml_digest = hashlib.sha256(
        b"".join(
            sorted(
                (xml_dir / table["xml"]).read_bytes()
                for table in plan["tables"]
            )
        )
    ).hexdigest()
    manifest = {
        "vector_id": vector_id,
        "kind": "generated_ts",
        "related_specs": plan["related_specs"],
        "generator_version": f"tsduck {_tsp_version(tool_dir)} (tstabcomp+tsp inject)",
        "config_hash": f"sha256:{xml_digest}",
        "sha256": f"sha256:{sha256}",
        "packet_count": plan["packet_count"],
        "fault_plan_ref": None,
        "verification": {
            "path": "tsduck-cross",
            "direction": "tsduck-generate→self-parse",
            "evidence_ref": (
                f"docs/test-vectors/golden/{vector_id}/{vector_id}.verification.md"
            ),
        },
    }
    (output_dir / vector_id / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (output_dir / vector_id / "expectations.json").write_text(
        json.dumps(plan["expectations"], indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return sha256


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("vector", choices=sorted(PLANS))
    parser.add_argument("--output-dir", required=True)
    parser.add_argument(
        "--tsxml-dir",
        default=str(Path(__file__).resolve().parent / "tsduck-tsxml"),
    )
    args = parser.parse_args()
    tool_dir = _tsduck_bin()
    sha256 = build_vector(
        args.vector, Path(args.output_dir), tool_dir, Path(args.tsxml_dir)
    )
    print(f"{args.vector}: sha256={sha256}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
