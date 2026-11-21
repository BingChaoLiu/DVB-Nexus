"""SPEC-506 §8 — golden vector registration validator.

Standalone (stdlib-only) checker for the repo-level registered golden tree
``docs/test-vectors/golden/``.  Enforces:

1. **Trio completeness + sha identity** (§3/§6): every ``manifest.json``
   directory carries ``<id>.ts`` + ``expectations.json``, the manifest ids
   match the directory, and the bytes hash to the manifest sha256.  This is
   an independent re-implementation of the loader contract — the CI gate
   runs it *and* the pytest golden_loader gate, so registration rot cannot
   slip past one implementation's blind spot.
2. **Event-type legality** (§8): every expectations entry's ``event_type``
   is in the SPEC-301 §4 authoritative registry (frozen list below).
3. **Pair linkage** (§4/§7): a ``faulted_ts`` vector must carry a
   ``fault_plan_ref`` pointing at a registered ``generated_ts`` baseline.
4. **Verification evidence** (§4/§5): every manifest carries the
   ``verification`` triple and the referenced evidence file exists.
5. **Index consistency** (§4): every registered vector id appears in
   ``docs/test-vectors/TEST-VECTOR-INDEX.md``.

Exit 0 = registration consistent; exit 1 = failures listed (machine and
human readable).  The conformance suite runs this tool as its
"registration consistency" gate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

DEFAULT_GOLDEN_ROOT = Path("docs/test-vectors/golden")
DEFAULT_INDEX = Path("docs/test-vectors/TEST-VECTOR-INDEX.md")

KINDS = ("generated_ts", "faulted_ts", "bit_level", "state_eval")

#: SPEC-506 §4 verification schema / §5 three-layer acceptance (#14 Q1,
#: ticket #38): the sanctioned independent-verification paths.  ``self-roundtrip``
#: (L3 自研 round-trip) is deliberately absent — 同源自证 = 登记拒绝.  Kept as an
#: independent re-implementation of the golden_loader gate (tests/conformance/
#: golden_loader.py ``VERIFICATION_PATHS``) — one implementation's blind spot
#: cannot accept a self-source claim.
VERIFICATION_PATHS = ("tsduck-cross", "bit-level-review")

#: SPEC-301 §4 authoritative event-type registry (the ``ts.*`` observation
#: family is the one golden expectations use; the full registered set is
#: enforced so a typo cannot smuggle an unregistered type past the gate).
EVENT_TYPE_REGISTRY: frozenset[str] = frozenset(
    {
        "simulation.session_created",
        "simulation.session_started",
        "simulation.session_paused",
        "simulation.session_resumed",
        "simulation.session_stopped",
        "simulation.run_started",
        "simulation.run_progress",
        "simulation.run_completed",
        "simulation.run_failed",
        "simulation.clock_advanced",
        "topology.state_changed",
        "ts.packet_batch_observed",
        "ts.continuity_error",
        "ts.pcr_jitter_observed",
        "ts.psi_section_observed",
        "ts.service_state_changed",
        "fault.injected",
        "fault.activated",
        "fault.applied",
        "fault.cleared",
        "scenario.step_started",
        "scenario.step_completed",
        "recovery.verification_completed",
        "diagnosis.raised",
        "diagnosis.updated",
        "diagnosis.cleared",
        # The Phase 3 state-observation namespaces (SPEC-303 §Phase3, #164;
        # the state_eval golden expectations' family face, ticket #172).
        "rf.state_observed",
        "sec.state_observed",
    }
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class Report:
    def __init__(self) -> None:
        self.failures: list[str] = []
        self.checked = 0

    def fail(self, message: str) -> None:
        self.failures.append(message)

    def finish(self) -> int:
        if self.failures:
            print(f"FAIL: {len(self.failures)} registration problem(s):")
            for failure in self.failures:
                print(f"  - {failure}")
            return 1
        print(f"OK: {self.checked} registered vector(s) validated.")
        return 0


def validate_vector(root: Path, directory: Path, report: Report, index_text: str) -> None:
    vector_id = directory.name
    report.checked += 1
    where = f"golden/{vector_id}"

    ts_path = directory / f"{vector_id}.ts"
    expectations_path = directory / "expectations.json"
    manifest_path = directory / "manifest.json"
    for path in (ts_path, expectations_path, manifest_path):
        if not path.is_file():
            report.fail(f"{where}: trio incomplete — missing {path.name} (SPEC-506 §3)")
            return

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("vector_id") != vector_id:
        report.fail(
            f"{where}: manifest vector_id {manifest.get('vector_id')!r} != "
            f"directory {vector_id!r}"
        )

    kind = manifest.get("kind")
    if kind not in KINDS:
        report.fail(f"{where}: kind {kind!r} outside closed enum {KINDS}")

    sha_manifest = str(manifest.get("sha256", "")).removeprefix("sha256:")
    if not _SHA256_RE.match(sha_manifest):
        report.fail(f"{where}: manifest sha256 not 64 hex chars")
    else:
        sha_actual = hashlib.sha256(ts_path.read_bytes()).hexdigest()
        if sha_actual != sha_manifest:
            report.fail(
                f"{where}: sha256 mismatch — manifest {sha_manifest}, bytes {sha_actual} "
                "(SPEC-506 §6: sha256 即身份; drift requires re-registration)"
            )

    for field in ("related_specs", "generator_version", "packet_count"):
        if field not in manifest:
            report.fail(f"{where}: manifest missing provenance field {field!r} (§4)")

    verification = manifest.get("verification")
    if not isinstance(verification, dict) or not {
        "path", "direction", "evidence_ref"
    }.issubset(verification):
        report.fail(
            f"{where}: verification needs path/direction/evidence_ref (SPEC-506 §4/§5)"
        )
    else:
        # §5 red line (ticket #38): 同源自证 = 登记拒绝 — only the sanctioned
        # independent-verification paths are acceptable registration evidence.
        verification_path = verification.get("path")
        if verification_path not in VERIFICATION_PATHS:
            report.fail(
                f"{where}: verification path {verification_path!r} outside sanctioned "
                f"independent paths {VERIFICATION_PATHS} — 同源自证 (L3 self-roundtrip) "
                "= 登记拒绝 (SPEC-506 §5)"
            )
        evidence_ref = verification.get("evidence_ref", "")
        evidence_path = Path(str(evidence_ref).split(" + ")[0])
        if not evidence_path.is_file():
            report.fail(f"{where}: verification evidence_ref missing on disk: {evidence_ref}")

    expectations = json.loads(expectations_path.read_text(encoding="utf-8"))
    entries = expectations.get("expectations")
    if not isinstance(entries, list) or not entries:
        report.fail(f"{where}: expectations.json must hold a non-empty list (§4)")
        return
    for position, entry in enumerate(entries):
        if not isinstance(entry, dict):
            report.fail(f"{where}: expectation {position} not an object")
            continue
        event_type = entry.get("event_type")
        if event_type not in EVENT_TYPE_REGISTRY:
            report.fail(
                f"{where}: expectation {position} event_type {event_type!r} not in the "
                "SPEC-301 §4 registry"
            )
        if not isinstance(entry.get("locator"), dict):
            report.fail(f"{where}: expectation {position} locator must be an object")

    if kind == "faulted_ts":
        baseline_ref = manifest.get("fault_plan_ref")
        baseline_dir = root / str(baseline_ref)
        baseline_manifest = baseline_dir / "manifest.json"
        if not baseline_manifest.is_file():
            report.fail(
                f"{where}: fault_plan_ref {baseline_ref!r} does not address a "
                "registered baseline vector"
            )
        else:
            baseline = json.loads(baseline_manifest.read_text(encoding="utf-8"))
            if baseline.get("kind") != "generated_ts":
                report.fail(
                    f"{where}: fault_plan_ref {baseline_ref!r} is kind "
                    f"{baseline.get('kind')!r}, expected generated_ts baseline"
                )
        if not isinstance(manifest.get("fault_parameters"), dict):
            report.fail(
                f"{where}: faulted_ts manifest missing fault_parameters "
                "(frozen SPEC-204 §6 transform record)"
            )

    if vector_id not in index_text:
        report.fail(
            f"{where}: vector id missing from TEST-VECTOR-INDEX.md (§4 index consistency)"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--golden-root", default=str(DEFAULT_GOLDEN_ROOT))
    parser.add_argument("--index", default=str(DEFAULT_INDEX))
    args = parser.parse_args()

    root = Path(args.golden_root)
    index_path = Path(args.index)
    report = Report()
    if not root.is_dir():
        report.fail(f"golden root not found: {root}")
        return report.finish()
    index_text = (
        index_path.read_text(encoding="utf-8-sig")
        if index_path.is_file()
        else ""
    )
    if not index_text:
        report.fail(f"index file missing or empty: {index_path}")

    for directory in sorted(path for path in root.iterdir() if path.is_dir()):
        if (directory / "manifest.json").is_file():
            validate_vector(root, directory, report, index_text)

    return report.finish()


if __name__ == "__main__":
    raise SystemExit(main())
