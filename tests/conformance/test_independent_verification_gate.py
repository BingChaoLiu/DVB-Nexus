"""SPEC-506 §5 独立验证红线 — 同源自证拒收负向门 (SPEC-506 0.6.0, #14 Q1, ticket #38).

三层来源地位 (#14 裁决): **L1** ``bit-level-review`` / **L2** ``tsduck-cross``
= 合格独立验证路径; **L3** 自研 round-trip = 仅回归覆盖, **永不构成独立验收
证据** — 同源自证 = 登记拒绝 (SPEC-506 §5 red line, REQ-CNF-506-002).

The gate is enforced on BOTH registration surfaces (deliberately independent
re-implementations — one implementation's blind spot cannot silently accept a
self-source claim, the same dual-gate discipline as the sha256 check):

- the pytest loader (``tests/conformance/golden_loader.py``, SPEC-506 §11);
- the §8 registration validator (``tools/validate_golden_registration.py``).

Negative-gate tests: a manifest whose ``verification.path`` claims a self-source
(L3 round-trip) path is refused at load and at validation.  Conformance layer;
pure registration mechanics — no TSDuck dependency (the gate must hold on any
machine, independent of the toolchain's presence).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests._support.deterministic import seeded_ts_stream
from tests._support.paths import REPO_ROOT
from tests.conformance.golden_loader import (
    GoldenRegistrationError,
    GoldenLoader,
    VERIFICATION_PATHS,
    write_golden_vector,
)

pytestmark = pytest.mark.conformance

#: The #14-surveyed L3 shape — self-generated, self-parsed, zero independent
#: evidence.  Any such claim must be rejected by both registration surfaces.
SELF_SOURCE_PATHS = (
    "self-roundtrip",
    "self-verify",
    "generator-roundtrip",
    "self-generate→self-parse",
)

_SANCTIONED = {
    "tsduck-cross": "self-generate→tsduck-analyze",
    "bit-level-review": "spec-table-derivation→self-parse",
}


@pytest.fixture
def tmp_golden_root(tmp_path: Path) -> Path:
    return tmp_path / "golden"


def _register(root: Path, vector_id: str, verification: dict | None) -> None:
    write_golden_vector(
        root,
        vector_id,
        seeded_ts_stream(38, 16),
        kind="generated_ts",
        expectations=(
            {"event_type": "ts.psi_section_observed", "locator": {"pid": 0}},
        ),
        verification=verification,
    )


class TestLoaderIndependentVerificationGate:
    def test_sanctioned_paths_enum_is_the_spec_surface(self):
        """SPEC-506 §4 verification schema: ``tsduck-cross | bit-level-review``."""
        assert VERIFICATION_PATHS == ("tsduck-cross", "bit-level-review")

    @pytest.mark.parametrize("path", sorted(_SANCTIONED))
    def test_sanctioned_independent_paths_load(self, tmp_golden_root, path: str):
        _register(
            tmp_golden_root,
            "sanctioned",
            {"path": path, "direction": _SANCTIONED[path], "evidence_ref": "evidence.md"},
        )
        vector = GoldenLoader(tmp_golden_root).load("sanctioned")
        assert vector.verification is not None
        assert vector.verification.path == path

    @pytest.mark.parametrize("path", SELF_SOURCE_PATHS)
    def test_self_source_verification_path_rejected(
        self, tmp_golden_root, path: str
    ):
        """同源自证 (L3 self-roundtrip) = 登记拒绝 (SPEC-506 §5, #14)."""
        _register(
            tmp_golden_root,
            "self-source",
            {"path": path, "direction": "self-generate→self-parse", "evidence_ref": "evidence.md"},
        )
        with pytest.raises(GoldenRegistrationError, match="independent|同源|verification path"):
            GoldenLoader(tmp_golden_root).load("self-source")

    def test_missing_verification_evidence_rejected(self, tmp_golden_root):
        """The §5 red line needs AT LEAST one independent validation path —
        a registration without any verification triple is not acceptable."""
        _register(tmp_golden_root, "no-evidence", None)
        with pytest.raises(GoldenRegistrationError, match="verification|独立验证"):
            GoldenLoader(tmp_golden_root).load("no-evidence")

    @pytest.mark.parametrize(
        "incomplete",
        [
            {"path": "tsduck-cross", "direction": "self-generate→tsduck-analyze"},
            {"path": "tsduck-cross", "evidence_ref": "evidence.md"},
            {"direction": "self-generate→tsduck-analyze", "evidence_ref": "evidence.md"},
        ],
    )
    def test_incomplete_verification_triple_rejected(
        self, tmp_golden_root, incomplete: dict
    ):
        _register(tmp_golden_root, "incomplete-verification", incomplete)
        with pytest.raises(GoldenRegistrationError, match="verification"):
            GoldenLoader(tmp_golden_root).load("incomplete-verification")


class TestValidatorIndependentVerificationGate:
    """The §8 validator tool enforces the same red line (dual-gate discipline)."""

    def _write_index(self, tmp_path: Path, vector_id: str) -> Path:
        index = tmp_path / "TEST-VECTOR-INDEX.md"
        index.write_text(
            f"# index\n\n| {vector_id} | registered |\n", encoding="utf-8"
        )
        return index

    def _run_validator(self, golden_root: Path, index: Path) -> subprocess.CompletedProcess:
        # The child runs ``-I`` (untrusted-data discipline), which implies ``-E``:
        # PYTHONIOENCODING cannot reach it, so on a GBK Windows console the
        # child's CJK text arrives mangled through the pipe (windows-shell
        # discipline).  Assertions therefore match ASCII-only fragments —
        # the offending *path claim* is asserted only for ASCII paths.
        return subprocess.run(
            [
                sys.executable, "-I",
                str(REPO_ROOT / "tools" / "validate_golden_registration.py"),
                "--golden-root", str(golden_root),
                "--index", str(index),
            ],
            capture_output=True,
            timeout=120,
        )

    def _write_evidence(self, tmp_path: Path) -> str:
        evidence = tmp_path / "evidence.md"
        evidence.write_text("# measured evidence\n", encoding="utf-8")
        return str(evidence)

    def test_validator_accepts_sanctioned_registration(self, tmp_path):
        evidence = self._write_evidence(tmp_path)
        _register(
            tmp_path / "golden",
            "sanctioned",
            {"path": "tsduck-cross", "direction": "self-generate→tsduck-analyze", "evidence_ref": evidence},
        )
        result = self._run_validator(tmp_path / "golden", self._write_index(tmp_path, "sanctioned"))
        assert result.returncode == 0, result.stdout.decode("utf-8", "replace")

    @pytest.mark.parametrize("path", ["self-roundtrip", "generator-roundtrip"])
    def test_validator_rejects_self_source_manifest(self, tmp_path, path: str):
        evidence = self._write_evidence(tmp_path)
        _register(
            tmp_path / "golden",
            "self-source",
            {"path": path, "direction": "self-generate→self-parse", "evidence_ref": evidence},
        )
        result = self._run_validator(tmp_path / "golden", self._write_index(tmp_path, "self-source"))
        assert result.returncode == 1
        output = result.stdout.decode("utf-8", "replace")
        assert path in output  # the offending claim is named, not silently swallowed
        assert "verification path" in output

    def test_validator_rejects_missing_verification(self, tmp_path):
        evidence = self._write_evidence(tmp_path)
        root = tmp_path / "golden"
        _register(root, "no-evidence", None)
        # strip the verification field entirely (write_golden_vector writes null)
        manifest_path = root / "no-evidence" / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        del manifest["verification"]
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        result = self._run_validator(root, self._write_index(tmp_path, "no-evidence"))
        assert result.returncode == 1
        assert "verification" in result.stdout.decode("utf-8", "replace")
