"""Unit-layer tests for the marker-discipline pure logic (SPEC-505 §8).

The rules module maps a test path to its layer (directory is the layer
source of truth) and decides inject/ok/fail for explicit layer markers.
Pure functions only — no I/O, no wall clock (unit layer discipline).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests._support.markers import (
    LAYER_NAMES,
    check_layer_markers,
    layer_for_path,
)
from tests._support.paths import TESTS_DIR


class TestLayerForPath:
    def test_layer_dir_maps_to_its_marker_name(self):
        for name in LAYER_NAMES:
            assert layer_for_path(TESTS_DIR / name / "test_x.py") == name

    def test_nested_file_still_resolves_to_top_layer_dir(self):
        assert layer_for_path(TESTS_DIR / "unit" / "sub" / "test_x.py") == "unit"

    def test_support_dir_is_not_a_layer(self):
        assert layer_for_path(TESTS_DIR / "_support" / "helpers.py") is None

    def test_root_conftest_is_not_a_layer(self):
        assert layer_for_path(TESTS_DIR / "conftest.py") is None

    def test_path_outside_tests_is_not_a_layer(self, tmp_path: Path):
        assert layer_for_path(tmp_path / "unit" / "test_x.py") is None


class TestCheckLayerMarkers:
    def test_no_explicit_layer_marker_injects_derived_layer(self):
        assert check_layer_markers("unit", frozenset()) == ("inject", "unit")

    def test_non_layer_markers_do_not_block_injection(self):
        assert check_layer_markers("e2e", frozenset({"slow", "tsduck"})) == (
            "inject",
            "e2e",
        )

    def test_matching_explicit_marker_is_kept_as_is(self):
        assert check_layer_markers("integration", frozenset({"integration"})) == (
            "ok",
            "integration",
        )

    def test_matching_marker_plus_extra_markers_is_ok(self):
        assert check_layer_markers(
            "conformance", frozenset({"conformance", "slow"})
        ) == ("ok", "conformance")

    @pytest.mark.parametrize("wrong_layer", sorted(set(LAYER_NAMES) - {"unit"}))
    def test_contradictory_layer_marker_fails(self, wrong_layer: str):
        action, detail = check_layer_markers("unit", frozenset({wrong_layer}))
        assert action == "fail"
        assert "unit" in detail
        assert wrong_layer in detail

    def test_multiple_contradictions_all_named_in_failure(self):
        action, detail = check_layer_markers(
            "unit", frozenset({"integration", "e2e"})
        )
        assert action == "fail"
        assert "integration" in detail and "e2e" in detail

    def test_passthrough_outside_layer_dirs(self):
        assert check_layer_markers(None, frozenset({"unit"})) == ("passthrough", None)
