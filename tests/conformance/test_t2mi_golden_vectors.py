"""SPEC-506 §6 / SPEC-600 §11.1 — golden conformance tests for ticket #122.

Loads the registered T2-MI vectors (``t2mi-minimal`` baseline +
``t2mi-crc-corrupt`` faulted counterpart) via the ``golden_loader``
fixture (sha256 verification mandatory) and asserts the SPEC-600 §6/§8
faces against them:

- expectations-driven parse: every registered expectation entry
  (event_type ``ts.packet_batch_observed``; detail keys mirror the
  ``T2miPacketDTO`` wire keys per SPEC-600 §5) must match the self
  parser's derived faces at the located packet index;
- determinism (SPEC-600 §7): same config double-run re-encodes
  byte-identically to the registered baseline bytes (L3 round-trip —
  regression coverage, never independent acceptance evidence);
- bad-packet face (SPEC-600 §8): the CRC-corrupted counterpart marks
  packet 0 ``crc32_valid=False`` and continues (packets 1..n stay
  valid, nothing dropped), with the byte difference to the baseline
  exactly the single flip recorded in the manifest fault_parameters.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import pytest

from tests._support.paths import REPO_ROOT
from ts.t2mi.builder import T2miBuildConfig, build
from ts.t2mi.packet import encode_packet
from ts.t2mi.parser import parse

VECTOR_MINIMAL = "t2mi-minimal"
VECTOR_CORRUPT = "t2mi-crc-corrupt"


def _manifest(golden_loader: Any, vector_id: str) -> Mapping[str, Any]:
    manifest_path = (
        REPO_ROOT / "docs" / "test-vectors" / "golden" / vector_id / "manifest.json"
    )
    return json.loads(manifest_path.read_text(encoding="utf-8"))


class TestT2miMinimalGolden:
    def test_registered_vector_loads_with_verified_sha(self, golden_loader: Any) -> None:
        vector = golden_loader.load(VECTOR_MINIMAL)
        assert vector.kind == "generated_ts"
        assert vector.packet_count == 3
        assert vector.sha256
        assert vector.ts_bytes

    def test_parse_matches_registered_expectations(self, golden_loader: Any) -> None:
        vector = golden_loader.load(VECTOR_MINIMAL)
        result = parse(vector.ts_bytes)
        assert not result.truncated
        assert result.trailing == b""
        for expectation in vector.expectations:
            packet = result[expectation["locator"]["packet_index"]]
            for key, expected in expectation["detail"].items():
                assert getattr(packet, key) == expected, (
                    f"packet[{expectation['locator']['packet_index']}].{key}"
                )

    def test_multi_up_tail_frame_survives_parse(self, golden_loader: Any) -> None:
        # The third registered frame is a smaller whole-UP tail frame —
        # the #105 shape TSDuck 3.45 silently loses. Self parse preserves it.
        vector = golden_loader.load(VECTOR_MINIMAL)
        result = parse(vector.ts_bytes)
        tail = result[2]
        assert tail.crc32_valid
        assert tail.packet_counter == 2
        assert tail.plp_id == 1

    def test_round_trip_double_run_is_byte_identical(self, golden_loader: Any) -> None:
        # SPEC-600 §7 同 config 双跑逐字节对拍: rebuild from the parsed
        # BBFRAMEs and re-encode — twice — and require byte identity with
        # the registered baseline.
        vector = golden_loader.load(VECTOR_MINIMAL)
        parsed = parse(vector.ts_bytes)
        frames = [packet.bbframe for packet in parsed]
        plp_ids = [packet.plp_id for packet in parsed]
        config = T2miBuildConfig()  # counters/frame indexes start at 0 (frozen geometry)
        first = b"".join(encode_packet(p) for p in build(frames, config, plp_ids=plp_ids))
        second = b"".join(encode_packet(p) for p in build(frames, config, plp_ids=plp_ids))
        assert first == second
        assert first == vector.ts_bytes

    def test_stage_summary_shape_from_golden_packets(self, golden_loader: Any) -> None:
        # Ruling §10-7: payload keys frozen; shape verified against the
        # registered PLP distribution [0, 0, 1].
        from ts.t2mi.summary import collect_stage_summary

        vector = golden_loader.load(VECTOR_MINIMAL)
        payload = collect_stage_summary(parse(vector.ts_bytes))
        assert payload["packet_count"] == 3
        assert payload["padding_count"] == 0
        assert payload["packet_type_distribution"] == {"bbframe": 3}
        assert payload["plp_distribution"] == {"0": 2, "1": 1}


class TestT2miCrcCorruptGolden:
    def test_faulted_vector_pair_links_to_baseline(self, golden_loader: Any) -> None:
        vector = golden_loader.load(VECTOR_CORRUPT)
        assert vector.kind == "faulted_ts"
        assert vector.fault_plan_ref == VECTOR_MINIMAL
        # Pair linkage sanity: the baseline loads too.
        golden_loader.load(VECTOR_MINIMAL)

    def test_crc_failure_marks_packet_and_continues(self, golden_loader: Any) -> None:
        vector = golden_loader.load(VECTOR_CORRUPT)
        result = parse(vector.ts_bytes)
        assert len(result) == 3  # nothing dropped
        assert not result.truncated
        assert not result[0].crc32_valid  # explicit bad-packet mark
        assert result[1].crc32_valid  # parse continues
        assert result[2].crc32_valid
        for expectation in vector.expectations:
            packet = result[expectation["locator"]["packet_index"]]
            for key, expected in expectation["detail"].items():
                assert getattr(packet, key) == expected, (
                    f"packet[{expectation['locator']['packet_index']}].{key}"
                )

    def test_byte_difference_is_exactly_the_recorded_flip(
        self, golden_loader: Any
    ) -> None:
        # Byte-level precision: the faulted bytes differ from the baseline
        # in exactly one bit, at the offset the independent transform
        # script recorded in manifest.fault_parameters — the golden stays
        # the byte oracle for the transform (house precedent).
        faulted = golden_loader.load(VECTOR_CORRUPT)
        baseline = golden_loader.load(VECTOR_MINIMAL)
        parameters = _manifest(golden_loader, VECTOR_CORRUPT)["fault_parameters"]
        assert parameters["crc_recomputed"] is False
        offset = parameters["flip_byte_offset"]
        mask = parameters["flip_mask"]
        differences = [
            index
            for index, (a, b) in enumerate(zip(baseline.ts_bytes, faulted.ts_bytes))
            if a != b
        ]
        assert differences == [offset]
        assert faulted.ts_bytes[offset] ^ baseline.ts_bytes[offset] == mask

    def test_corrupt_packet_payload_matches_baseline_except_flip(
        self, golden_loader: Any
    ) -> None:
        faulted = parse(golden_loader.load(VECTOR_CORRUPT).ts_bytes)
        baseline = parse(golden_loader.load(VECTOR_MINIMAL).ts_bytes)
        for index, (bad, good) in enumerate(zip(faulted, baseline)):
            assert bad.packet_counter == good.packet_counter
            assert bad.payload_bytes_len == good.payload_bytes_len
            if index == 0:
                assert bad.payload != good.payload
            else:
                assert bad.payload == good.payload


class TestRegistrationConsistency:
    def test_t2mi_vectors_listed_in_index(self, golden_loader: Any) -> None:
        # §4 index consistency (validator also enforces; this asserts the
        # intent visibly for the #122 pair).
        index_text = (
            REPO_ROOT / "docs" / "test-vectors" / "TEST-VECTOR-INDEX.md"
        ).read_text(encoding="utf-8")
        assert VECTOR_MINIMAL in index_text
        assert VECTOR_CORRUPT in index_text

    def test_registration_validator_passes_for_t2mi_rows(self) -> None:
        # Independent re-run of the SPEC-506 §8 validator (subprocess,
        # repo-rooted), asserting the registration gates stay green with
        # the two new vectors registered.
        import subprocess
        import sys

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
