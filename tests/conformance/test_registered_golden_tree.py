"""CI gate: every repo-registered golden vector loads cleanly (SPEC-506 §6,
via the SPEC-505 conformance layer).

SPEC-506: conformance tests load **all registered vectors** with SHA-256
verification + expectations assertions. Observation-level assertions (via
SPEC-305 queries / journal replay) belong to the SPEC-506 implementation
tickets — this scaffold gate enforces the loading invariant: every
registered vector's trio parses, the manifest matches its directory, and
the file bytes hash to the manifest sha256. With zero registered vectors
the invariant holds vacuously; the structure asserts keep the gate honest
and the loader fixture wiring exercised.
"""

from __future__ import annotations

from tests.conformance.golden_loader import GoldenLoader
from tests._support.paths import GOLDEN_ROOT


def test_all_registered_vectors_load_with_verified_sha():
    loader = GoldenLoader(GOLDEN_ROOT)
    vectors = loader.load_all()
    assert len(vectors) == len(loader.registered_ids())
    for vector in vectors:
        assert vector.sha256
        assert vector.ts_bytes  # non-empty registered bytes
        assert vector.kind in ("generated_ts", "faulted_ts", "bit_level", "state_eval")
