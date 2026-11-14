"""Fixture-by-name wiring for ``golden_loader`` (SPEC-505 §4).

Conformance layer: the shared fixture binds to the repo-level registered
golden root (docs/test-vectors/golden, #14 Q4) and loads read-only.
"""

from __future__ import annotations

from tests._support.golden import GoldenLoader
from tests._support.paths import GOLDEN_ROOT


def test_golden_loader_fixture_binds_repo_root(golden_loader):
    assert isinstance(golden_loader, GoldenLoader)
    assert golden_loader.root == GOLDEN_ROOT


def test_golden_loader_fixture_reads_repo_golden_root(golden_loader):
    # Read-only consumption of the real registered tree: enumeration works
    # and every id it reports loads (vacuous while no vectors registered).
    for vector in golden_loader.load_all():
        assert vector.vector_id
