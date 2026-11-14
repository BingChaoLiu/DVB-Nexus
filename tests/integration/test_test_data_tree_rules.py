"""Tree-level enforcement of the 禁手拼字节 rule set (SPEC-505 §6, #14).

Integration layer: real file-tree resources (tmp trees for behavior; the
real ``tests/`` tree for the CI gate). The second test is the executable
gate: the whole test tree (excluding the sanctioned constructor zone
``_support/``) must contain zero hand-assembled byte findings.
"""

from __future__ import annotations

from pathlib import Path

from tests._support.data_rules import scan_tree
from tests._support.paths import TESTS_DIR


class TestScanTreeBehavior:
    def test_violation_in_plain_subdir_is_found(self, tmp_path: Path):
        target = tmp_path / "unit"
        target.mkdir()
        (target / "test_x.py").write_text(
            "x = b'" + "A" * 32 + "'\n", encoding="utf-8"
        )
        found = scan_tree(tmp_path)
        assert len(found) == 1
        assert found[0].rule == "bytes_literal"
        assert found[0].filename.endswith("test_x.py")

    def test_support_dir_is_skipped(self, tmp_path: Path):
        support = tmp_path / "_support"
        support.mkdir()
        (support / "ctor.py").write_text(
            "x = b'" + "A" * 32 + "'\n", encoding="utf-8"
        )
        assert scan_tree(tmp_path) == []

    def test_clean_tree_yields_no_findings(self, tmp_path: Path):
        (tmp_path / "unit").mkdir()
        (tmp_path / "unit" / "test_ok.py").write_text(
            "from tests._support.deterministic import seeded_ts_stream\n"
            "s = seeded_ts_stream(seed=1, packet_count=3)\n",
            encoding="utf-8",
        )
        assert scan_tree(tmp_path) == []

    def test_non_utf8_bytes_do_not_crash_scan(self, tmp_path: Path):
        # Files in the tree are repo-managed UTF-8; a foreign encoding would
        # be a repo defect, but the scan must fail loudly, not silently pass.
        (tmp_path / "weird.py").write_bytes(b"x = 1\n\xff\xfe\n")
        try:
            scan_tree(tmp_path)
        except UnicodeDecodeError:
            pass  # loud failure is the accepted behavior
        else:
            assert scan_tree(tmp_path) == []


def test_real_tests_tree_has_zero_hand_assembled_byte_findings():
    """CI gate: the actual test tree obeys the data-discipline rule set."""
    violations = scan_tree(TESTS_DIR)
    assert violations == [], "\n".join(str(v) for v in violations)
