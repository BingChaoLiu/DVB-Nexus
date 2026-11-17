"""SPEC-506 §6 / SPEC-600 §11.1 — golden conformance tests for the T2-MI
negative set additions (``t2mi-unknown-type`` / ``t2mi-truncated``, the
M6 code-review fix round's #122 spec-partial completion).

Loads the two faulted vectors via the ``golden_loader`` fixture (sha256
verification mandatory) and asserts the SPEC-600 §8 faces against them,
each pair-linked to the ``t2mi-minimal`` baseline:

- unknown packet type: packet 0 surfaces ``payload_kind="unknown"`` with
  the BBFRAME-derived faces ``None`` while the CRC face stays green (the
  transform recomputed the trailer — the type face is isolated), and
  parsing continues (packets 1..2 keep their baseline details verbatim,
  nothing dropped);
- truncated tail: the parse result carries the explicit
  ``truncated=True`` state plus the verbatim ``trailing`` bytes while
  the complete packets (0..1) parse intact — no scan/resync mode
  (house ruling #11 precedent);
- byte-precision: each faulted byte string differs from the registered
  baseline in exactly the way the manifest's frozen
  ``fault_parameters`` record (header-only type override + trailer
  rewrite; pure prefix cut);
- determinism (SPEC-506 §6): the independent transform script re-run
  reproduces the registered bytes (same script + same baseline ⇒ same
  bytes; CI only verifies sha, never regenerates).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

import pytest

from tests._support.paths import REPO_ROOT
from ts.t2mi.parser import parse

VECTOR_BASELINE = "t2mi-minimal"
VECTOR_UNKNOWN_TYPE = "t2mi-unknown-type"
VECTOR_TRUNCATED = "t2mi-truncated"

UNKNOWN_TYPE_VALUE = 0x55


def _manifest(golden_loader: Any, vector_id: str) -> Mapping[str, Any]:
    manifest_path = (
        REPO_ROOT / "docs" / "test-vectors" / "golden" / vector_id / "manifest.json"
    )
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _assert_expectations_match(vector: Any, result: Any) -> None:
    for expectation in vector.expectations:
        packet = result[expectation["locator"]["packet_index"]]
        for key, expected in expectation["detail"].items():
            assert getattr(packet, key) == expected, (
                f"packet[{expectation['locator']['packet_index']}].{key}"
            )


class TestPairLinkage:
    def test_unknown_type_pair_links_to_baseline(self, golden_loader: Any) -> None:
        vector = golden_loader.load(VECTOR_UNKNOWN_TYPE)
        assert vector.kind == "faulted_ts"
        assert vector.fault_plan_ref == VECTOR_BASELINE
        assert vector.packet_count == 3
        golden_loader.load(VECTOR_BASELINE)

    def test_truncated_pair_links_to_baseline(self, golden_loader: Any) -> None:
        vector = golden_loader.load(VECTOR_TRUNCATED)
        assert vector.kind == "faulted_ts"
        assert vector.fault_plan_ref == VECTOR_BASELINE
        assert vector.packet_count == 2
        golden_loader.load(VECTOR_BASELINE)


class TestUnknownTypeVector:
    """SPEC-600 §8 注册表渐进: unknown packet_type is an explicit state."""

    def test_unknown_type_marks_packet_and_continues(
        self, golden_loader: Any
    ) -> None:
        vector = golden_loader.load(VECTOR_UNKNOWN_TYPE)
        result = parse(vector.ts_bytes)
        assert len(result) == 3  # nothing dropped
        assert not result.truncated
        assert not result.trailing
        packet0 = result[0]
        assert packet0.packet_type == UNKNOWN_TYPE_VALUE
        assert packet0.packet_type not in (0x00, 0xFF)  # neither bbframe nor padding
        assert packet0.payload_kind == "unknown"  # explicit state
        assert packet0.frame_index is None  # BBFRAME-derived faces absent
        assert packet0.plp_id is None
        assert packet0.crc32_valid  # CRC face green — trailer was recomputed
        assert result[1].payload_kind == "bbframe"  # parse continues
        assert result[2].payload_kind == "bbframe"
        for packet in result:
            assert packet.crc32_valid
        _assert_expectations_match(vector, result)

    def test_payload_bytes_are_verbatim_baseline(self, golden_loader: Any) -> None:
        """The type override is header-only: packet 0's payload (and the
        untouched packets) carry the baseline bytes verbatim — no payload
        reinterpretation happened."""
        faulted = golden_loader.load(VECTOR_UNKNOWN_TYPE).ts_bytes
        baseline = golden_loader.load(VECTOR_BASELINE).ts_bytes
        assert len(faulted) == len(baseline)
        assert faulted[6:3779] == baseline[6:3779]  # packet 0 payload
        assert faulted[3783:] == baseline[3783:]  # packets 1-2 verbatim

    def test_byte_difference_is_exactly_type_byte_plus_trailer(
        self, golden_loader: Any
    ) -> None:
        parameters = _manifest(golden_loader, VECTOR_UNKNOWN_TYPE)[
            "fault_parameters"
        ]
        assert parameters["transform"] == "packet_type_override"
        assert parameters["crc_recomputed"] is True
        assert parameters["new_packet_type"] == UNKNOWN_TYPE_VALUE
        faulted = golden_loader.load(VECTOR_UNKNOWN_TYPE).ts_bytes
        baseline = golden_loader.load(VECTOR_BASELINE).ts_bytes
        differing = [i for i, (a, b) in enumerate(zip(baseline, faulted)) if a != b]
        # type byte (offset 0) + the 4 recomputed CRC trailer bytes of packet 0
        assert differing[0] == parameters["type_byte_offset"] == 0
        assert differing[1:] == [3779, 3780, 3781, 3782]
        assert faulted[0] == UNKNOWN_TYPE_VALUE


class TestTruncatedVector:
    """SPEC-600 §8: truncation is an explicit observable, never a silent stop."""

    def test_truncation_state_and_verbatim_trailing(self, golden_loader: Any) -> None:
        vector = golden_loader.load(VECTOR_TRUNCATED)
        result = parse(vector.ts_bytes)
        parameters = _manifest(golden_loader, VECTOR_TRUNCATED)["fault_parameters"]
        assert parameters["transform"] == "tail_truncation"
        kept = parameters["kept_tail_bytes"]
        assert kept == 100
        assert result.truncated
        assert len(result) == 2  # only the complete packets
        assert result.trailing_bytes == kept
        baseline = golden_loader.load(VECTOR_BASELINE).ts_bytes
        # Baseline geometry: packets 0/1 are 3783 bytes each (header 6 +
        # payload 3773 + CRC 4); the faulted stream keeps both plus the
        # first `kept` bytes of packet 2.  trailing = the first `kept`
        # bytes of packet 2 — a verbatim slice of the baseline's middle,
        # not its end.
        packet_size = 3783
        assert len(vector.ts_bytes) == 2 * packet_size + kept
        assert result.trailing == vector.ts_bytes[-kept:]
        assert result.trailing == baseline[2 * packet_size : 2 * packet_size + kept]
        assert vector.ts_bytes == baseline[: len(vector.ts_bytes)]  # prefix cut
        _assert_expectations_match(vector, result)

    def test_complete_packets_match_baseline_details(self, golden_loader: Any) -> None:
        faulted = parse(golden_loader.load(VECTOR_TRUNCATED).ts_bytes)
        baseline = parse(golden_loader.load(VECTOR_BASELINE).ts_bytes)
        for index, (partial, good) in enumerate(zip(faulted, baseline)):
            assert partial.packet_counter == good.packet_counter
            assert partial.payload == good.payload
            assert partial.crc32_valid
            assert index < 2


class TestDeterminism:
    def test_transform_script_reproduces_registered_bytes(
        self, golden_loader: Any, tmp_path: Path
    ) -> None:
        """SPEC-506 §6: same script + same baseline ⇒ same bytes (the
        registered sha is the frozen identity; CI only verifies sha)."""
        baseline_ts = (
            REPO_ROOT
            / "docs"
            / "test-vectors"
            / "golden"
            / VECTOR_BASELINE
            / f"{VECTOR_BASELINE}.ts"
        )
        script = REPO_ROOT / "tools" / "golden_t2mi_fault_transform.py"
        for vector_id in (VECTOR_UNKNOWN_TYPE, VECTOR_TRUNCATED):
            completed = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    str(script),
                    "--vector",
                    vector_id,
                    "--baseline",
                    str(baseline_ts),
                    "--output-dir",
                    str(tmp_path),
                ],
                capture_output=True,
                text=True,
                timeout=300,
                check=False,
            )
            assert completed.returncode == 0, completed.stdout + completed.stderr
            rebuilt = (tmp_path / vector_id / f"{vector_id}.ts").read_bytes()
            assert rebuilt == golden_loader.load(vector_id).ts_bytes
