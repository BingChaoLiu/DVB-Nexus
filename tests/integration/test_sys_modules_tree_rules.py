"""Whole-tree ``sys.modules`` mutation rule gate (M4 retro finding A2).

``tests/_support/io_rules`` ``io_sys_modules_write`` flags direct
``sys.modules`` writes (``del`` / subscript assign / ``pop`` / ``clear`` /
``update`` / ``setdefault``) anywhere in the test tree: a purge without
restore mints duplicate class objects whose identity splits against every
pre-imported binding — order-dependent pollution (M4 挂账 1: ~24
rest_runs/rest_artifacts failures under the explicit path order, root
cause ``tests/unit/ts/test_generator.py`` purge). The sanctioned shape is
a snapshot + finally-restore pair, marked ``# sysmodules-ok:`` waivers
(grep-visible review focus, same discipline as ``io-ok:`` — waiver-face
zero is the standing goal).

Unlike the unit-layer I/O gate (which scans ``tests/unit/`` only), this
rule is layer-agnostic — module-state pollution breaks class identity in
any layer — so the gate scans the whole ``tests/`` tree.
"""

from __future__ import annotations

from tests._support.io_rules import (
    RULE_IO_SYS_MODULES_WRITE,
    find_io_violations,
)
from tests._support.paths import TESTS_DIR

import pytest

pytestmark = pytest.mark.integration


def test_no_unwaived_sys_modules_writes_anywhere_in_test_tree() -> None:
    violations = [
        violation
        for path in sorted(TESTS_DIR.rglob("*.py"))
        for violation in find_io_violations(
            path.read_text(encoding="utf-8"), filename=str(path)
        )
        if violation.rule == RULE_IO_SYS_MODULES_WRITE
    ]
    assert violations == [], (
        "unwaived sys.modules writes pollute module state across tests "
        "(snapshot + finally-restore with `# sysmodules-ok:` is the "
        "sanctioned shape):\n" + "\n".join(map(str, violations))
    )


def test_rule_detects_purge_and_mutator_shapes() -> None:
    source = "\n".join(
        [
            "import sys",
            "del sys.modules['x']",
            "sys.modules['x'] = None",
            "sys.modules.pop('x', None)",
            "sys.modules.clear()",
            "sys.modules.update({})",
            "snapshot = set(sys.modules)",  # reads stay allowed
        ]
    )
    found = find_io_violations(source)
    assert [violation.rule for violation in found] == [
        RULE_IO_SYS_MODULES_WRITE
    ] * 5


def test_rule_honors_sysmodules_ok_waiver() -> None:
    source = "\n".join(
        [
            "import sys",
            "del sys.modules['x']  # sysmodules-ok: snapshot-restore pair",
        ]
    )
    assert find_io_violations(source) == []
