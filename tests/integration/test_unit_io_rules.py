"""Tree-level enforcement of the unit-layer I/O structural rule (SPEC-505 §8).

Integration layer: real file-tree resources (tmp trees for behavior; the
real ``tests/unit`` tree for the CI gate). SPEC-505 §8 分层互斥第一规则:
"unit 层出现 I/O 即结构违规" — the last test is the executable gate: the
whole unit layer must contain zero I/O findings (review-fix #6, AST
detector in the style of the data_rules engine).
"""

from __future__ import annotations

from pathlib import Path

from tests._support.io_rules import scan_tree
from tests._support.paths import TESTS_DIR


class TestScanTreeBehavior:
    def test_io_in_unit_tree_is_found(self, tmp_path: Path):
        unit = tmp_path / "unit"
        unit.mkdir()
        (unit / "test_x.py").write_text(
            "from pathlib import Path\n"
            "def test_writes(tmp_path):\n"
            "    Path('x').write_text('data')\n",
            encoding="utf-8",
        )
        found = scan_tree(tmp_path)
        assert [v.rule for v in found] == ["io_fixture_request", "io_path_method"]
        assert found[0].filename.endswith("test_x.py")

    def test_clean_unit_tree_yields_no_findings(self, tmp_path: Path):
        unit = tmp_path / "unit"
        unit.mkdir()
        (unit / "test_ok.py").write_text(
            "from tests._support.deterministic import seeded_ts_stream\n"
            "stream = seeded_ts_stream(seed=1, packet_count=3)\n",
            encoding="utf-8",
        )
        assert scan_tree(tmp_path) == []

    def test_syntax_error_file_does_not_crash_scan(self, tmp_path: Path):
        # A syntax error is the file's own collection failure, not a
        # data-discipline finding — the scan must not crash on it.
        (tmp_path / "broken.py").write_text("def broken(:\n", encoding="utf-8")
        assert scan_tree(tmp_path) == []


def test_real_unit_tree_has_zero_io_findings():
    """CI gate: the actual unit layer obeys 分层互斥 (SPEC-505 §8)."""
    violations = scan_tree(TESTS_DIR / "unit")
    assert violations == [], "\n".join(str(v) for v in violations)
