"""SPEC-506 golden vector registration format (§4) — loader + test writer.

Home: ``tests/conformance/golden_loader.py`` per SPEC-506 §11 交付要求
(moved from ``tests/_support/golden.py``; import surface is
``tests.conformance.golden_loader``).

The ``golden_loader`` fixture (SPEC-505 §4) yields :class:`GoldenLoader`.
A registered vector is a trio under ``<root>/<vector_id>/``:

- ``<vector_id>.ts``     — the bytes (SPEC-506 §3 tree);
- ``manifest.json``      — machine-readable registration (§4);
- ``expectations.json``  — expected observations, same structure as
  FaultDefinition ``expected_observations`` (ADR-0007 第 5 条).

Loader enforcement: trio completeness (缺一不予登记), manifest↔directory
identity, kind closed enum, sha256(bytes) == manifest sha256 (``sha256:``
prefix optional), minimal expectations shape, path-safe vector ids, and the
SPEC-506 §5 independent-verification gate (ticket #38): every registration
carries a ``verification`` triple whose ``path`` is in the sanctioned
``VERIFICATION_PATHS`` closed enum and whose ``evidence_ref`` addresses an
existing file — 同源自证 (L3 self-roundtrip) = 登记拒绝.
``write_golden_vector`` exists for **tests only** — it registers private tmp
copies; bytes must come from sanctioned constructors (SPEC-505 §6), and the
digest is always computed from the given bytes, never trusted from callers.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from tests._support.paths import REPO_ROOT

#: SPEC-506 §4 manifest kind closed enum.
KINDS: tuple[str, ...] = ("generated_ts", "faulted_ts", "bit_level")

#: SPEC-506 §4 verification schema / §5 three-layer acceptance (#14 Q1, ticket
#: #38): the only sanctioned independent-verification paths.  ``tsduck-cross``
#: is the L2 TSDuck bidirectional cross; ``bit-level-review`` is the L1
#: externally-reviewed bit-level vector.  ``self-roundtrip`` (L3 自研
#: round-trip) is deliberately ABSENT — 同源自证 = 登记拒绝 (§5 red line):
#: a golden file must never be accepted solely because the same implementation
#: parses its own output.
VERIFICATION_PATHS: tuple[str, ...] = ("tsduck-cross", "bit-level-review")

#: SPEC-506 §3: vector_id is a semantic slug (e.g. ``pat-minimal``).
_VECTOR_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")

_TS_SUFFIX = ".ts"
_MANIFEST_NAME = "manifest.json"
_EXPECTATIONS_NAME = "expectations.json"


class GoldenRegistrationError(Exception):
    """A golden vector violates the SPEC-506 registration contract."""


@dataclass(frozen=True)
class VerificationRecord:
    """SPEC-506 §4 manifest ``verification`` field (three-layer evidence)."""

    path: str
    direction: str
    evidence_ref: str


@dataclass(frozen=True)
class GoldenVector:
    """One registered golden vector, fully verified at load time."""

    vector_id: str
    kind: str
    related_specs: tuple[str, ...]
    generator_version: str | None
    config_hash: str | None
    sha256: str
    packet_count: int | None
    fault_plan_ref: str | None
    verification: VerificationRecord | None
    ts_bytes: bytes
    expectations: tuple[Mapping[str, Any], ...]


def _validate_vector_id(vector_id: str) -> str:
    if not isinstance(vector_id, str) or not _VECTOR_ID_PATTERN.match(vector_id):
        raise GoldenRegistrationError(
            f"vector_id must be a semantic slug (lowercase alnum/dash, SPEC-506 §3), "
            f"got {vector_id!r}"
        )
    return vector_id


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise GoldenRegistrationError(f"unreadable/invalid JSON {path.name}: {error}") from error


def _normalize_sha(manifest: Mapping[str, Any]) -> str:
    value = manifest.get("sha256")
    if not isinstance(value, str):
        raise GoldenRegistrationError("manifest sha256 missing or not a string")
    normalized = value.strip().lower().removeprefix("sha256:")
    if len(normalized) != 64 or any(
        character not in "0123456789abcdef" for character in normalized
    ):
        raise GoldenRegistrationError(
            f"manifest sha256 is not 64 hex chars: {value!r}"
        )
    return normalized


def _validate_expectations(raw: Any) -> tuple[Mapping[str, Any], ...]:
    """Minimal expectations shape per SPEC-506 §4 / ADR-0007 第 5 条."""
    if not isinstance(raw, list):
        raise GoldenRegistrationError("expectations.json must hold a top-level list")
    validated: list[Mapping[str, Any]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise GoldenRegistrationError("each expectation entry must be an object")
        event_type = entry.get("event_type")
        if not isinstance(event_type, str) or not event_type:
            raise GoldenRegistrationError(
                "expectation entry missing string event_type"
            )
        validated.append(dict(entry))
    return tuple(validated)


def load_golden_vector(root: Path, vector_id: str) -> GoldenVector:
    """Load and verify one registered vector (read-only)."""
    checked_id = _validate_vector_id(vector_id)
    base = Path(root) / checked_id
    ts_path = base / f"{checked_id}{_TS_SUFFIX}"
    manifest_path = base / _MANIFEST_NAME
    expectations_path = base / _EXPECTATIONS_NAME

    missing = [path.name for path in (ts_path, manifest_path, expectations_path) if not path.is_file()]
    if missing:
        raise GoldenRegistrationError(
            f"vector {checked_id!r}: trio incomplete (三件套缺一不予登记, SPEC-506 §3), "
            f"missing: {missing}"
        )

    manifest = _read_json(manifest_path)
    if manifest.get("vector_id") != checked_id:
        raise GoldenRegistrationError(
            f"vector {checked_id!r}: manifest vector_id mismatch "
            f"({manifest.get('vector_id')!r} != {checked_id!r})"
        )

    kind = manifest.get("kind")
    if kind not in KINDS:
        raise GoldenRegistrationError(
            f"vector {checked_id!r}: kind {kind!r} outside closed enum {KINDS} (SPEC-506 §4)"
        )

    expectations_raw = _read_json(expectations_path)
    expectations = _validate_expectations(expectations_raw.get("expectations"))

    ts_bytes = ts_path.read_bytes()
    actual_sha = hashlib.sha256(ts_bytes).hexdigest()
    manifest_sha = _normalize_sha(manifest)
    if actual_sha != manifest_sha:
        raise GoldenRegistrationError(
            f"vector {checked_id!r}: sha256 mismatch — manifest {manifest_sha}, "
            f"bytes {actual_sha} (SPEC-506 §6: sha256 即身份)"
        )

    verification_raw = manifest.get("verification")
    # §5 red line (ticket #38): EVERY registered vector carries at least one
    # independent-verification path — a missing/incomplete triple is not a
    # loadable registration (同源自证拒绝 includes the vacuous self-claim).
    if not isinstance(verification_raw, dict) or not {
        "path",
        "direction",
        "evidence_ref",
    } <= set(verification_raw):
        raise GoldenRegistrationError(
            f"vector {checked_id!r}: manifest must carry a verification triple "
            "path/direction/evidence_ref (SPEC-506 §4/§5 独立验证红线 — "
            "at least one independent validation path is mandatory)"
        )
    verification_path = verification_raw["path"]
    if verification_path not in VERIFICATION_PATHS:
        raise GoldenRegistrationError(
            f"vector {checked_id!r}: verification path {verification_path!r} "
            f"is outside the sanctioned independent-verification paths "
            f"{VERIFICATION_PATHS} — 同源自证 (L3 self-roundtrip) = 登记拒绝 "
            "(SPEC-506 §5, #14 Q1)"
        )
    direction = verification_raw["direction"]
    evidence_ref = verification_raw["evidence_ref"]
    if (
        not isinstance(direction, str)
        or not direction.strip()
        or not isinstance(evidence_ref, str)
        or not evidence_ref.strip()
    ):
        raise GoldenRegistrationError(
            f"vector {checked_id!r}: verification direction/evidence_ref must "
            "be non-empty strings (SPEC-506 §4)"
        )
    # Evidence must exist on disk — parity with the §8 validator (review fix
    # A2: the loader only checked non-empty while the validator stat'ed the
    # file, so the two gates disagreed). Resolution convention matches the
    # validator's ``evidence_ref.split(" + ")[0]`` shape: repo-relative for
    # registered-tree assets, absolute for tmp private registrations — but
    # resolved from REPO_ROOT (derived from __file__), never the process cwd
    # (tests/README.md §6), so the loader gate is cwd-independent where the
    # validator relies on being run from the repo root.
    evidence_anchor = Path(evidence_ref.split(" + ")[0])
    if not evidence_anchor.is_absolute():
        evidence_anchor = REPO_ROOT / evidence_anchor
    if not evidence_anchor.is_file():
        raise GoldenRegistrationError(
            f"vector {checked_id!r}: verification evidence_ref missing on "
            f"disk: {evidence_ref} (SPEC-506 §4/§5 — 独立验证证据必须存在)"
        )
    verification = VerificationRecord(
        path=str(verification_path),
        direction=direction,
        evidence_ref=evidence_ref,
    )

    related_specs_raw = manifest.get("related_specs", [])
    if not isinstance(related_specs_raw, list):
        raise GoldenRegistrationError(
            f"vector {checked_id!r}: related_specs must be a list"
        )

    packet_count = manifest.get("packet_count")
    if packet_count is not None and not isinstance(packet_count, int):
        raise GoldenRegistrationError(
            f"vector {checked_id!r}: packet_count must be int or null"
        )

    return GoldenVector(
        vector_id=checked_id,
        kind=str(kind),
        related_specs=tuple(str(spec) for spec in related_specs_raw),
        generator_version=manifest.get("generator_version"),
        config_hash=manifest.get("config_hash"),
        sha256=manifest_sha,
        packet_count=packet_count,
        fault_plan_ref=manifest.get("fault_plan_ref"),
        verification=verification,
        ts_bytes=ts_bytes,
        expectations=expectations,
    )


class GoldenLoader:
    """Read-only loader bound to a golden root (yielded by the fixture)."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def registered_ids(self) -> list[str]:
        """Vector ids whose directory holds a manifest (full trio checked at load)."""
        if not self.root.is_dir():
            return []
        return sorted(
            child.name
            for child in self.root.iterdir()
            if child.is_dir() and (child / _MANIFEST_NAME).is_file()
        )

    def load(self, vector_id: str) -> GoldenVector:
        return load_golden_vector(self.root, vector_id)

    def load_all(self) -> list[GoldenVector]:
        """Load every registered vector — the CI gate primitive (SPEC-506 §6)."""
        return [self.load(vector_id) for vector_id in self.registered_ids()]


def write_golden_vector(
    root: Path,
    vector_id: str,
    ts_bytes: bytes,
    *,
    kind: str,
    related_specs: Sequence[str] = (),
    generator_version: str | None = None,
    config_hash: str | None = None,
    packet_count: int | None = None,
    fault_plan_ref: str | None = None,
    verification: Mapping[str, str] | None = None,
    expectations: Sequence[Mapping[str, Any]] = (),
) -> Path:
    """Register a vector trio under ``root`` (tests / tmp registrations only).

    The sha256 is computed from ``ts_bytes`` here — bytes are the single
    source of identity (SPEC-506 §6). Callers must pass sanctioned bytes
    (deterministic constructors / checked-in assets), never literals.
    """
    checked_id = _validate_vector_id(vector_id)
    if kind not in KINDS:
        raise GoldenRegistrationError(f"kind {kind!r} outside closed enum {KINDS}")
    base = Path(root) / checked_id
    base.mkdir(parents=True, exist_ok=True)

    (base / f"{checked_id}{_TS_SUFFIX}").write_bytes(ts_bytes)

    manifest: dict[str, Any] = {
        "vector_id": checked_id,
        "kind": kind,
        "related_specs": list(related_specs),
        "generator_version": generator_version,
        "config_hash": config_hash,
        "sha256": f"sha256:{hashlib.sha256(ts_bytes).hexdigest()}",
        "packet_count": packet_count,
        "fault_plan_ref": fault_plan_ref,
        "verification": dict(verification) if verification else None,
    }
    (base / _MANIFEST_NAME).write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (base / _EXPECTATIONS_NAME).write_text(
        json.dumps({"expectations": list(expectations)}, indent=2, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    return base
