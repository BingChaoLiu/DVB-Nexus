"""SPEC-506 §6 / SPEC-603 §11 — golden conformance tests for ticket #125.

Loads the registered ``inner-ts-roundtrip`` vector (the expected side of
the three-level demux chain — the #105 research baseline
``expected_inner.ts``, captured verbatim from the independent external
generator) via the ``golden_loader`` fixture (sha256 mandatory) and
asserts the SPEC-603 §6/§7/§8 faces against it:

- chain round-trip: ``reconstruct(parse(chain input))`` equals the
  registered baseline byte-for-byte, ``ok`` status, PLP selection
  applied (SPEC-603 §11 正向 — the reconstruction target is externally
  authoritative; the self chain is L3 regression per SPEC-506 §5);
- expectations-driven TS parse: the reconstructed stream re-parses at
  the inspect face (``TSPacket.from_bytes`` strict) with every
  registered expectation satisfied (SPEC-100 consumption, SPEC-603 §2.1
  "接 SPEC-100 既有 analyze/inspect 消费面");
- wire face: ``wire_detail()`` carries exactly the frozen six keys and
  ``artifact_ref`` is the content address of the golden bytes
  (SPEC-503 identity — landing via ``ArtifactStore.store_bytes``
  converges on this address);
- registration consistency: index row + additive sha identity pin +
  NOT TRUSTED annotation in place (ruling §10-9);
- live L2 cross (``tsduck``-marked): ``tsp -P t2mi --extract`` against
  the TS-framed chain input, byte-diff through
  ``verify_against_tsduck`` — the record must be ``NOT TRUSTED``
  (trusted-release registry empty, master 147deab3 unreleased) and the
  extraction must be either byte-identical (fixed release) or a
  188-aligned byte-prefix of the baseline (the #105 multi-UP tail-loss
  face, honestly observable).  Local runs without TSDuck skip with a
  summary-visible reason — NOT RUN never counts as PASS.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from tests._support.paths import REPO_ROOT
from ts.packet import TSPacket
from ts.t2mi.inner_ts import (
    FIRST_FAILURE_REF_KEYS,
    INNER_TS_WIRE_KEYS,
    RECONSTRUCTION_STATUS_OK,
    reconstruct,
    verify_against_tsduck,
)
from ts.t2mi.parser import parse
from ts.t2mi.plp import PlpFilterConfig

VECTOR_ID = "inner-ts-roundtrip"

#: Additive identity pin (own-file precedent, #122/#123/#126; the frozen
#: #14 table stays untouched — brief §3.6-5, #136 collects).
VECTOR_SHA256 = "08fcc6347a4e358c59c856371240610e46933ad5ca239ce80314a348075cb5d6"

CHAIN_INPUT_PATH = (
    REPO_ROOT / "tests" / "data" / "t2mi" / "inner_ts_roundtrip_input.bin"
)
OUTER_TS_PATH = (
    REPO_ROOT / "tests" / "data" / "t2mi" / "inner_ts_roundtrip_outer.ts"
)

#: The research outer TS carries the T2-MI stream on PID 0x64 (decimal 100).
T2MI_PID_DECIMAL = 100

_TS_PACKET_BYTES = 188


def _demux_packets() -> Any:
    result = parse(CHAIN_INPUT_PATH.read_bytes())
    assert not result.truncated
    assert result.trailing == b""
    return result


class TestInnerTsRoundtripGolden:
    def test_registered_vector_loads_with_verified_sha(
        self, golden_loader: Any
    ) -> None:
        vector = golden_loader.load(VECTOR_ID)
        assert vector.kind == "generated_ts"
        assert vector.packet_count == 6
        assert vector.sha256 == VECTOR_SHA256
        assert len(vector.ts_bytes) % _TS_PACKET_BYTES == 0
        # The independent-verification evidence exists and annotates the
        # L2 cross NOT TRUSTED (SPEC-603 §8 row 4, ruling §10-9).
        assert vector.verification is not None
        assert "NOT TRUSTED" in vector.verification.direction

    def test_chain_round_trip_matches_the_registered_baseline(
        self, golden_loader: Any
    ) -> None:
        vector = golden_loader.load(VECTOR_ID)
        config = PlpFilterConfig(mode="expected", expected_plp=0)
        result = reconstruct(_demux_packets(), config)
        assert result.reconstruction_status == RECONSTRUCTION_STATUS_OK
        assert result.inner_ts == vector.ts_bytes
        assert result.up_assembled == vector.packet_count
        assert result.packet_count == len(vector.ts_bytes) // _TS_PACKET_BYTES
        assert result.stuffing_bytes == 0
        assert result.anomalies == ()
        assert result.first_failure_ref is None

    def test_chain_round_trip_is_deterministic(self, golden_loader: Any) -> None:
        golden_loader.load(VECTOR_ID)  # trio + sha gate stays green
        packets = _demux_packets()
        first = reconstruct(packets, PlpFilterConfig(mode="expected", expected_plp=0))
        second = reconstruct(packets, PlpFilterConfig(mode="all"))
        assert first.inner_ts == second.inner_ts
        assert first.wire_detail() == second.wire_detail()

    def test_expectations_drive_the_inspect_face_parse(
        self, golden_loader: Any
    ) -> None:
        vector = golden_loader.load(VECTOR_ID)
        config = PlpFilterConfig(mode="expected", expected_plp=0)
        reconstructed = reconstruct(_demux_packets(), config).inner_ts
        for offset, expectation in zip(
            range(0, len(reconstructed), _TS_PACKET_BYTES), vector.expectations
        ):
            packet = TSPacket.from_bytes(
                reconstructed[offset : offset + _TS_PACKET_BYTES]
            )
            assert packet.parse_issues == ()
            assert expectation["locator"]["packet_index"] == offset // _TS_PACKET_BYTES
            for key, expected in expectation["detail"].items():
                assert getattr(packet, key) == expected, (
                    f"packet[{offset // _TS_PACKET_BYTES}].{key}"
                )

    def test_wire_face_keys_and_content_address(self, golden_loader: Any) -> None:
        vector = golden_loader.load(VECTOR_ID)
        result = reconstruct(_demux_packets(), PlpFilterConfig(mode="all"))
        wire = result.wire_detail()
        assert set(wire) == set(INNER_TS_WIRE_KEYS)
        assert set(FIRST_FAILURE_REF_KEYS) == {"frame_index", "reason", "packet_position"}
        assert wire["artifact_ref"] == VECTOR_SHA256
        assert wire["artifact_ref"] == vector.sha256

    def test_vector_listed_in_index(self) -> None:
        index_text = (
            REPO_ROOT / "docs" / "test-vectors" / "TEST-VECTOR-INDEX.md"
        ).read_text(encoding="utf-8")
        assert f"`{VECTOR_ID}`" in index_text


class TestTsduckLiveCross:
    """The L2 second-opinion protocol, executed live when TSDuck is present.

    ``tsduck``-marked (SPEC-505 §5): CI Windows job runs it in full; a
    local machine without TSDuck skips with a summary-visible reason —
    the vector stays honestly NOT RUN, never a silent PASS.
    """

    @pytest.mark.tsduck
    def test_extract_diff_record_is_not_trusted(
        self, golden_loader: Any, tsduck: Any, tmp_path: Path
    ) -> None:
        vector = golden_loader.load(VECTOR_ID)
        output_path = tmp_path / "tsduck_extract.ts"
        completed = subprocess.run(
            [
                tsduck.executable,
                "-I",
                "file",
                str(OUTER_TS_PATH),
                "-P",
                "t2mi",
                "--extract",
                "--pid",
                str(T2MI_PID_DECIMAL),
                "--output-file",
                str(output_path),
                "-O",
                "drop",
            ],
            capture_output=True,
            timeout=120,
        )
        assert completed.returncode == 0, completed.stderr.decode(
            "utf-8", "replace"
        )
        extracted = output_path.read_bytes()
        assert len(extracted) % _TS_PACKET_BYTES == 0

        record = verify_against_tsduck(vector.ts_bytes, extracted)
        # Trust annotation: registry-gated, never "对拍绿" (ruling §10-9).
        assert record["trusted"] is False
        assert record["trust_annotation"] == "NOT TRUSTED"
        assert record["not_trusted_reason"]
        # Shape face: either byte-identical (a release past the demux
        # rewrite) or the honest #105 prefix face — an 188-aligned
        # byte-prefix of the baseline, never a mid-packet mangling.
        if record["match"]:
            assert record["tsduck_byte_size"] == record["inner_byte_size"]
        else:
            prefix = record["prefix_match_bytes"]
            assert prefix == record["tsduck_byte_size"]
            assert prefix % _TS_PACKET_BYTES == 0
            assert vector.ts_bytes[:prefix] == extracted[:prefix]
