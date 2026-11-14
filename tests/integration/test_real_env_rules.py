"""Tree-level enforcement of the real-environment literal rule (ticket #70).

Integration layer: real file-tree resources (tmp trees for behavior; the
real ``tests`` tree for the CI gate). tests/README.md §6: "实机测试断言
形状，禁钉环境字面值" — the #69 CI first run went red on three literal
pins (version token / drive letter / on-disk casing) against a *correct*
probe. The rule was documentation-only; the last two tests are the
executable gates: every real-environment-marked test file in the tree must
contain zero literal-pin findings, and the ``env-ok:`` waiver surface must
stay at zero (standing goal per §6; introducing a waiver is a conscious,
review-visible act that updates this audit).
"""

from __future__ import annotations

import tokenize
from pathlib import Path

from tests._support.env_rules import SUPPORT_DIRNAME, scan_tree
from tests._support.paths import TESTS_DIR

MARKED_HEADER = "import pytest\npytestmark = [pytest.mark.tsduck]\n"


class TestScanTreeBehavior:
    def test_pin_in_marked_file_is_found(self, tmp_path: Path):
        (tmp_path / "test_probe_like.py").write_text(
            MARKED_HEADER + 'assert probe.version == "3.40-4165"\n',
            encoding="utf-8",
        )
        found = scan_tree(tmp_path)
        assert [v.rule for v in found] == ["env_version_literal"]
        assert found[0].filename.endswith("test_probe_like.py")

    def test_identical_pin_in_unmarked_file_is_ignored(self, tmp_path: Path):
        (tmp_path / "test_unit_like.py").write_text(
            'assert probe.version == "3.40-4165"\n',
            encoding="utf-8",
        )
        assert scan_tree(tmp_path) == []

    def test_support_zone_is_excluded_from_scan(self, tmp_path: Path):
        support = tmp_path / SUPPORT_DIRNAME
        support.mkdir()
        # The constructor zone may document incident tokens verbatim (its
        # own correctness is constrained by the unit layer).
        (support / "fixture_anchor.py").write_text(
            'MARKER_DOC = "reference machine runs 3.40-4165 on D:\\\\TSDuck"\n',
            encoding="utf-8",
        )
        assert scan_tree(tmp_path) == []

    def test_syntax_error_file_does_not_crash_scan(self, tmp_path: Path):
        (tmp_path / "broken.py").write_text("def broken(:\n", encoding="utf-8")
        assert scan_tree(tmp_path) == []

    def test_shape_assertion_file_is_clean(self, tmp_path: Path):
        (tmp_path / "test_probe_real_like.py").write_text(
            MARKED_HEADER
            + 'assert re.fullmatch(r"\\d+\\.\\d+-\\d+", probe.version)\n'
            'assert probe.path.name.lower() == "tsp.exe"\n',
            encoding="utf-8",
        )
        assert scan_tree(tmp_path) == []


def test_real_tests_tree_has_zero_env_literal_violations():
    """CI gate: the whole tests tree obeys §6 (ticket #70, #69 lesson)."""
    violations = scan_tree(TESTS_DIR)
    assert violations == [], "\n".join(str(v) for v in violations)


def test_real_tests_tree_has_zero_env_ok_waivers():
    """CI gate: the ``env-ok:`` waiver surface stays at zero (§6 standing
    goal). A waiver is never silent — adding one means updating this audit
    consciously, with the reason documented at the waiving line. The audit
    reads real comment tokens (tokenize), so prose mentioning the marker in
    docstrings or generated-source strings stays out of scope."""
    waivers: list[str] = []
    for path in sorted(TESTS_DIR.rglob("*.py")):
        if SUPPORT_DIRNAME in path.parts:
            continue
        with tokenize.open(path) as handle:
            for token in tokenize.generate_tokens(handle.readline):
                if token.type == tokenize.COMMENT and "env-ok:" in token.string:
                    waivers.append(f"{path.relative_to(TESTS_DIR)}:{token.start[0]}")
    assert waivers == [], "env-ok waivers present: " + ", ".join(waivers)
