"""SPEC-506 §6 / SPEC-601 §11 — golden conformance tests for ticket #123.

Loads the registered BBFRAME vectors (``bbframe-nups3`` baseline + the
``bbframe-b2-corrupt`` / ``bbframe-b2-shift`` faulted形态对) via the
``golden_loader`` fixture (sha256 verification mandatory) and asserts
the SPEC-601 §6/§7/§8 faces against them:

- expectations-driven parse: every registered expectation entry (wire
  keys per SPEC-601 §5 + explicit ``state`` per §8) must match the self
  parser's derived faces at the located frame index;
- tail-stuffing pinning (SPEC-601 §7): the N_UPS=3 tail frame carries
  ``0xFF`` baseband stuffing up to capacity with DFL declaring the real
  payload bits — byte-exactly (the #105 multi-UP-tail defect class);
- determinism (SPEC-601 §7): reassembled UP stream re-encapsulates
  byte-identically, double run (L3 regression — never acceptance
  evidence, SPEC-506 §5);
- B2 pair evidence shapes: corrupt breaks the CRC-8 (one byte of
  difference, recovery_failed face), shift keeps it valid with the
  SYNCD misalignment state (two bytes of difference) — the two
  distinguishable B2 evidence forms, byte-pinned;
- registration consistency: index rows + SPEC-506 §8 validator PASS +
  the NOT TRUSTED annotation in place (ruling §10-9 — TSDuck has zero
  BBFrame user-side capability, #104).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

from tests._support.paths import REPO_ROOT
from ts.t2mi.bbframe import (
    BBHEADER_SIZE,
    BBFrameBuildConfig,
    build,
    crc8_dvb,
    parse,
)
from ts.t2mi.bbframe_summary import collect_recovery_failed, collect_stage_summary

VECTOR_BASELINE = "bbframe-nups3"
VECTOR_CORRUPT = "bbframe-b2-corrupt"
VECTOR_SHIFT = "bbframe-b2-shift"

_STUFFING_BYTE = 0xFF


def _manifest(vector_id: str) -> Mapping[str, Any]:
    manifest_path = (
        REPO_ROOT / "docs" / "test-vectors" / "golden" / vector_id / "manifest.json"
    )
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _slice_frames(ts_bytes: bytes, expectations: tuple[Mapping[str, Any], ...]) -> list[bytes]:
    """Slice the back-to-back stream using the frozen build-side geometry.

    The deterministic tail rule reserves ``n_ups * upl`` data-field bytes
    per frame, so every frame in a built stream has the same size:
    ``BBHEADER + capacity * upl_bytes`` — both derived from the
    registered expectations (no hardcoded geometry).
    """
    first = expectations[0]["detail"]
    upl_bytes = first["upl"] // 8
    capacity = max(entry["detail"]["up_count"] for entry in expectations)
    frame_size = BBHEADER_SIZE + capacity * upl_bytes
    assert len(ts_bytes) % frame_size == 0
    return [
        ts_bytes[offset : offset + frame_size]
        for offset in range(0, len(ts_bytes), frame_size)
    ]


def _assert_expectations(frames: list[bytes], expectations: tuple[Mapping[str, Any], ...]) -> None:
    parsed = parse(frames)
    assert len(parsed) == len(expectations)
    for expectation in expectations:
        frame = parsed[expectation["locator"]["frame_index"]]
        for key, expected in expectation["detail"].items():
            actual = getattr(frame, key)
            if isinstance(expected, list):
                actual = list(actual)
            assert actual == expected, (
                f"frame[{expectation['locator']['frame_index']}].{key}"
            )


class TestBBFrameNups3Golden:
    def test_registered_vector_loads_with_verified_sha(self, golden_loader: Any) -> None:
        vector = golden_loader.load(VECTOR_BASELINE)
        assert vector.kind == "generated_ts"
        assert vector.packet_count == 3
        assert vector.sha256
        assert vector.ts_bytes

    def test_parse_matches_registered_expectations(self, golden_loader: Any) -> None:
        vector = golden_loader.load(VECTOR_BASELINE)
        frames = _slice_frames(vector.ts_bytes, vector.expectations)
        _assert_expectations(frames, vector.expectations)

    def test_tail_frame_stuffing_is_byte_pinned(self, golden_loader: Any) -> None:
        vector = golden_loader.load(VECTOR_BASELINE)
        parsed = parse(_slice_frames(vector.ts_bytes, vector.expectations))
        tail = parsed[2]
        assert tail.up_count == 2
        assert tail.stuffing_bytes == tail.upl // 8  # one UP's worth
        assert tail.data_field[-tail.stuffing_bytes :] == bytes(
            [_STUFFING_BYTE]
        ) * tail.stuffing_bytes
        # Frames 0/1 carry no stuffing at all.
        assert parsed[0].stuffing_bytes == 0
        assert parsed[1].stuffing_bytes == 0

    def test_reassembly_and_double_run_rebuild_byte_identically(
        self, golden_loader: Any
    ) -> None:
        vector = golden_loader.load(VECTOR_BASELINE)
        frames = _slice_frames(vector.ts_bytes, vector.expectations)
        parsed = parse(frames)
        detail = vector.expectations[0]["detail"]
        upl_bytes = detail["upl"] // 8
        stream = b"".join(
            frame.data_field[start : start + upl_bytes]
            for frame in parsed
            for start in frame.up_indices
        )
        config = BBFrameBuildConfig(n_ups=3, matype_value=detail["matype"])
        first_run = build(stream, config)
        second_run = build(stream, config)
        assert first_run == second_run
        assert b"".join(first_run) == vector.ts_bytes

    def test_stage_summary_shape_from_golden_frames(self, golden_loader: Any) -> None:
        vector = golden_loader.load(VECTOR_BASELINE)
        parsed = parse(_slice_frames(vector.ts_bytes, vector.expectations))
        payload = collect_stage_summary(parsed)
        assert payload["frame_count"] == 3
        assert payload["n_ups_distribution"] == {"3": 2, "2": 1}
        upl_bytes = vector.expectations[0]["detail"]["upl"] // 8
        capacity_bytes = 3 * upl_bytes  # every frame reserves full N_UPS capacity
        expected_ratio = upl_bytes / (3 * capacity_bytes)
        assert payload["stuffing_ratio"] == expected_ratio
        recovery = collect_recovery_failed(parsed)
        assert recovery["failure_count"] == 0
        assert recovery["first_failed_frame_index"] is None


class TestB2PairGolden:
    def test_faulted_vectors_pair_link_to_baseline(self, golden_loader: Any) -> None:
        for vector_id in (VECTOR_CORRUPT, VECTOR_SHIFT):
            vector = golden_loader.load(vector_id)
            assert vector.kind == "faulted_ts"
            assert vector.fault_plan_ref == VECTOR_BASELINE
        golden_loader.load(VECTOR_BASELINE)

    def test_corrupt_breaks_crc8_and_withholds_boundaries(
        self, golden_loader: Any
    ) -> None:
        vector = golden_loader.load(VECTOR_CORRUPT)
        frames = _slice_frames(vector.ts_bytes, vector.expectations)
        _assert_expectations(frames, vector.expectations)
        parsed = parse(frames)
        assert parsed[0].crc8_valid is False
        assert parsed[0].up_count == 0
        assert parsed[1].state == "ok"  # parse continues, nothing dropped
        assert parsed[2].up_count == 2
        recovery = collect_recovery_failed(parsed)
        assert recovery["failure_count"] == 1
        assert recovery["first_failed_frame_index"] == 0

    def test_corrupt_byte_difference_is_exactly_the_recorded_flip(
        self, golden_loader: Any
    ) -> None:
        faulted = golden_loader.load(VECTOR_CORRUPT)
        baseline = golden_loader.load(VECTOR_BASELINE)
        parameters = _manifest(VECTOR_CORRUPT)["fault_parameters"]
        assert parameters["crc8_recomputed"] is False
        offset = parameters["target_byte_offset"]  # frame 0 starts at 0
        mask = parameters["corrupt_mask"]
        differences = [
            index
            for index, (a, b) in enumerate(zip(baseline.ts_bytes, faulted.ts_bytes))
            if a != b
        ]
        assert differences == [offset]
        assert faulted.ts_bytes[offset] ^ baseline.ts_bytes[offset] == mask

    def test_shift_stays_crc_valid_but_misaligns(self, golden_loader: Any) -> None:
        vector = golden_loader.load(VECTOR_SHIFT)
        frames = _slice_frames(vector.ts_bytes, vector.expectations)
        _assert_expectations(frames, vector.expectations)
        parsed = parse(frames)
        assert parsed[0].crc8_valid is True
        assert parsed[0].state == "syncd_misaligned"
        assert parsed[0].syncd == 1  # SYNCD 是位距离，不是同步字节
        assert parsed[0].up_count == 0
        assert collect_recovery_failed(parsed)["failure_count"] == 0

    def test_shift_byte_difference_is_field_plus_recomputed_crc(
        self, golden_loader: Any
    ) -> None:
        faulted = golden_loader.load(VECTOR_SHIFT)
        baseline = golden_loader.load(VECTOR_BASELINE)
        parameters = _manifest(VECTOR_SHIFT)["fault_parameters"]
        assert parameters["crc8_recomputed"] is True
        differences = [
            index
            for index, (a, b) in enumerate(zip(baseline.ts_bytes, faulted.ts_bytes))
            if a != b
        ]
        assert differences == [parameters["target_byte_offset"] + 1, 9]
        # The recomputed CRC-8 byte matches the faulted header's own check.
        header9 = faulted.ts_bytes[0:9]  # frame 0 starts at absolute 0
        stored = faulted.ts_bytes[9]
        assert (stored ^ crc8_dvb(header9)) == 0  # NM residue preserved

    def test_untouched_frames_are_byte_identical_to_baseline(
        self, golden_loader: Any
    ) -> None:
        baseline = golden_loader.load(VECTOR_BASELINE)
        for vector_id in (VECTOR_CORRUPT, VECTOR_SHIFT):
            faulted = golden_loader.load(vector_id)
            frame_size = len(baseline.ts_bytes) // 3
            assert (
                faulted.ts_bytes[frame_size:] == baseline.ts_bytes[frame_size:]
            )


class TestRegistrationConsistency:
    def test_bbframe_vectors_listed_in_index(self, golden_loader: Any) -> None:
        index_text = (
            REPO_ROOT / "docs" / "test-vectors" / "TEST-VECTOR-INDEX.md"
        ).read_text(encoding="utf-8")
        for vector_id in (VECTOR_BASELINE, VECTOR_CORRUPT, VECTOR_SHIFT):
            assert vector_id in index_text

    def test_not_trusted_annotation_in_place(self, golden_loader: Any) -> None:
        # Ruling §10-9: the TSDuck-cross impossibility (#104) is recorded
        # with the NOT TRUSTED framing in every bbframe vector's
        # verification direction — shape assertion, no environment
        # literals (tests/README §6).
        for vector_id in (VECTOR_BASELINE, VECTOR_CORRUPT, VECTOR_SHIFT):
            direction = _manifest(vector_id)["verification"]["direction"]
            assert "NOT TRUSTED" in direction
            assert "#104" in direction

    def test_registration_validator_passes_for_bbframe_rows(self) -> None:
        # Independent re-run of the SPEC-506 §8 validator (subprocess,
        # repo-rooted), asserting the registration gates stay green with
        # the three new vectors registered.
        completed = subprocess.run(
            [
                sys.executable,
                "-I",
                str(REPO_ROOT / "tools" / "validate_golden_registration.py"),
            ],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            check=False,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr
