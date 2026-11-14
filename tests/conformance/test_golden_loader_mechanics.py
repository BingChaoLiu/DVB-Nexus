"""``golden_loader`` fixture mechanics (SPEC-505 §4 → SPEC-506 §4).

Conformance layer. The loader consumes registered vectors read-only; these
scaffold tests exercise its mechanics against **private tmp registrations**
(never touching the repo golden tree — write access stays in tmp_path).
All TS bytes come from the deterministic constructors (SPEC-505 §6
sanctioned source), never hand-assembled literals.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests._support.deterministic import seeded_ts_stream
from tests.conformance.golden_loader import (
    GoldenRegistrationError,
    GoldenLoader,
    write_golden_vector,
)
from tests._support.paths import GOLDEN_ROOT

_EXPECTATIONS = (
    {"event_type": "ts.psi_section_observed", "locator": {"pid": 0}},
)

#: Sanctioned L2 verification triple for tmp registrations (SPEC-506 §5 gate,
#: ticket #38: every loadable registration carries an independent path whose
#: evidence file exists on disk — review fix A2 loader/validator parity).
#: Tmp registrations carry an absolute evidence path into the test's own tmp
#: tree; the loader resolves repo-relative refs against REPO_ROOT instead.
_CROSS_VERIFICATION = {
    "path": "tsduck-cross",
    "direction": "self-generate→tsduck-analyze",
    "evidence_ref": "evidence.md",
}


@pytest.fixture
def tmp_evidence(tmp_path: Path) -> str:
    """An existing evidence file for tmp registrations (absolute path)."""
    evidence = tmp_path / "evidence.md"
    evidence.write_text("# measured independent verification evidence\n", encoding="utf-8")
    return str(evidence)


@pytest.fixture
def tmp_golden_root(tmp_path: Path) -> Path:
    return tmp_path / "golden"


class TestLoadRegisteredVector:
    def test_three_piece_vector_loads_with_verified_sha(
        self, tmp_golden_root, tmp_evidence
    ):
        ts_bytes = seeded_ts_stream(77, 32)
        write_golden_vector(
            tmp_golden_root,
            "pat-minimal",
            ts_bytes,
            kind="generated_ts",
            related_specs=("SPEC-103", "SPEC-108"),
            generator_version="tstabcomp (tstduck 3.40-4165)",
            packet_count=32,
            expectations=_EXPECTATIONS,
            verification={**_CROSS_VERIFICATION, "evidence_ref": tmp_evidence},
        )
        vector = GoldenLoader(tmp_golden_root).load("pat-minimal")
        assert vector.vector_id == "pat-minimal"
        assert vector.kind == "generated_ts"
        assert vector.related_specs == ("SPEC-103", "SPEC-108")
        assert vector.ts_bytes == ts_bytes
        assert vector.packet_count == 32
        assert vector.expectations == _EXPECTATIONS
        assert vector.sha256 == json.loads(
            (tmp_golden_root / "pat-minimal" / "manifest.json").read_text(
                encoding="utf-8"
            )
        )["sha256"].removeprefix("sha256:")

    def test_sha_prefix_and_bare_hex_both_accepted(
        self, tmp_golden_root, tmp_evidence
    ):
        ts_bytes = seeded_ts_stream(78, 8)
        write_golden_vector(
            tmp_golden_root,
            "cc-wrap",
            ts_bytes,
            kind="generated_ts",
            verification={**_CROSS_VERIFICATION, "evidence_ref": tmp_evidence},
        )
        manifest_path = tmp_golden_root / "cc-wrap" / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["sha256"] = manifest["sha256"].removeprefix("sha256:")
        manifest_path.write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )
        vector = GoldenLoader(tmp_golden_root).load("cc-wrap")
        assert vector.sha256 == manifest["sha256"]

    def test_verification_record_round_trips(self, tmp_golden_root):
        ts_bytes = seeded_ts_stream(79, 8)
        write_golden_vector(
            tmp_golden_root,
            "packet-header-set",
            ts_bytes,
            kind="bit_level",
            verification={
                "path": "bit-level-review",
                "direction": "external-vector",
                "evidence_ref": "docs/test-vectors/CRC32-MPEG2.md",
            },
        )
        vector = GoldenLoader(tmp_golden_root).load("packet-header-set")
        assert vector.verification is not None
        assert vector.verification.path == "bit-level-review"
        assert vector.verification.evidence_ref.endswith("CRC32-MPEG2.md")


class TestRegistrationIntegrity:
    def test_tampered_bytes_fail_sha_check(self, tmp_golden_root):
        ts_bytes = seeded_ts_stream(80, 16)
        write_golden_vector(tmp_golden_root, "pcr-wrap", ts_bytes, kind="generated_ts")
        # overwrite the .ts with a *deterministic* different stream
        ts_path = tmp_golden_root / "pcr-wrap" / "pcr-wrap.ts"
        ts_path.write_bytes(seeded_ts_stream(81, 16))
        with pytest.raises(GoldenRegistrationError, match="sha256"):
            GoldenLoader(tmp_golden_root).load("pcr-wrap")

    @pytest.mark.parametrize("missing", ["manifest.json", "expectations.json"])
    def test_missing_trio_piece_rejected(self, tmp_golden_root, missing: str):
        ts_bytes = seeded_ts_stream(82, 8)
        write_golden_vector(tmp_golden_root, "incomplete", ts_bytes, kind="generated_ts")
        (tmp_golden_root / "incomplete" / missing).unlink()
        with pytest.raises(GoldenRegistrationError, match="三件套|trio|missing"):
            GoldenLoader(tmp_golden_root).load("incomplete")

    def test_manifest_id_mismatch_rejected(self, tmp_golden_root):
        ts_bytes = seeded_ts_stream(83, 8)
        write_golden_vector(tmp_golden_root, "one-id", ts_bytes, kind="generated_ts")
        manifest_path = tmp_golden_root / "one-id" / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["vector_id"] = "other-id"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with pytest.raises(GoldenRegistrationError, match="vector_id"):
            GoldenLoader(tmp_golden_root).load("one-id")

    @pytest.mark.parametrize("bad_kind", ["ts-stream", "", None])
    def test_unknown_kind_rejected(self, tmp_golden_root, bad_kind):
        ts_bytes = seeded_ts_stream(84, 8)
        write_golden_vector(tmp_golden_root, "kindless", ts_bytes, kind="generated_ts")
        manifest_path = tmp_golden_root / "kindless" / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["kind"] = bad_kind
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with pytest.raises(GoldenRegistrationError, match="kind"):
            GoldenLoader(tmp_golden_root).load("kindless")

    def test_expectations_entry_without_event_type_rejected(self, tmp_golden_root):
        ts_bytes = seeded_ts_stream(85, 8)
        write_golden_vector(
            tmp_golden_root,
            "bad-expectation",
            ts_bytes,
            kind="generated_ts",
            expectations=({"locator": {"pid": 0}},),
        )
        with pytest.raises(GoldenRegistrationError, match="event_type"):
            GoldenLoader(tmp_golden_root).load("bad-expectation")


class TestPathSafety:
    @pytest.mark.parametrize(
        "bad_id", ["../escape", "a/b", "a\\b", "..", ".hidden", "UPPER-ID"]
    )
    def test_unsafe_or_non_slug_vector_ids_rejected(self, tmp_golden_root, bad_id: str):
        with pytest.raises(GoldenRegistrationError, match="vector_id"):
            GoldenLoader(tmp_golden_root).load(bad_id)


class TestRegisteredEnumeration:
    def test_registered_ids_lists_complete_trios_only(
        self, tmp_golden_root, tmp_evidence
    ):
        write_golden_vector(
            tmp_golden_root,
            "alpha",
            seeded_ts_stream(86, 8),
            kind="generated_ts",
            verification={**_CROSS_VERIFICATION, "evidence_ref": tmp_evidence},
        )
        # beta has only a .ts — no manifest → not registered
        (tmp_golden_root / "beta").mkdir()
        (tmp_golden_root / "beta" / "beta.ts").write_bytes(
            seeded_ts_stream(87, 8)
        )
        loader = GoldenLoader(tmp_golden_root)
        assert loader.registered_ids() == ["alpha"]

    def test_load_all_returns_every_registered_vector(
        self, tmp_golden_root, tmp_evidence
    ):
        for index, name in enumerate(("alpha", "beta", "gamma")):
            write_golden_vector(
                tmp_golden_root,
                name,
                seeded_ts_stream(90 + index, 8),
                kind="generated_ts",
                verification={**_CROSS_VERIFICATION, "evidence_ref": tmp_evidence},
            )
        loader = GoldenLoader(tmp_golden_root)
        assert [vector.vector_id for vector in loader.load_all()] == [
            "alpha",
            "beta",
            "gamma",
        ]


def test_repo_golden_root_structure_present():
    """Repo-level golden tree exists per #14 Q4 (migrated out of spec pkg)."""
    assert GOLDEN_ROOT.is_dir()
    readme = GOLDEN_ROOT / "README.md"
    assert readme.is_file()
