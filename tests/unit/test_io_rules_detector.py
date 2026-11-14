"""Unit-layer tests for the unit-layer I/O detector (SPEC-505 §8 分层互斥).

`find_io_violations` is a pure source-text analyzer: no I/O, no wall clock.
Tree-level application lives in the integration layer
(test_unit_io_rules.py). This file is itself part of the scanned unit tree
and must therefore stay finding-free — it exercises the detector on
in-memory source strings only.
"""

from __future__ import annotations

from tests._support.io_rules import (
    IO_FIXTURE_PARAMS,
    IO_MODULE_NAMES,
    find_io_violations,
)

# Pure framing bytes below MAX_BYTES_LITERAL (data_rules sanction).
SYNC = b"\x47"


def violations_of(source: str):
    return find_io_violations(source, filename="<test>")


def rules_of(source: str) -> list[str]:
    return [violation.rule for violation in violations_of(source)]


class TestIoModuleImports:
    def test_subprocess_import_flagged(self):
        assert rules_of("import subprocess\n") == ["io_module_import"]

    def test_aliased_io_import_flagged(self):
        assert rules_of("import shutil as sh\n") == ["io_module_import"]

    def test_from_import_flagged(self):
        assert rules_of("from subprocess import run\n") == ["io_module_import"]

    def test_network_modules_flagged(self):
        for module in ("socket", "httpx", "requests", "urllib.request"):
            assert rules_of(f"import {module}\n") == ["io_module_import"]

    def test_every_registered_io_module_is_flagged(self):
        for module in IO_MODULE_NAMES:
            assert rules_of(f"import {module}\n") == ["io_module_import"]

    def test_pure_module_imports_pass(self):
        assert violations_of("import json\nimport sqlite3\nfrom pathlib import Path\n") == []


class TestIoModuleCalls:
    def test_subprocess_call_flagged(self):
        source = (
            "import subprocess\n"
            "subprocess.run(['x'], capture_output=True)\n"
        )
        assert set(rules_of(source)) == {"io_module_import", "io_module_call"}

    def test_shutil_call_flagged(self):
        source = "import shutil\nshutil.copytree('a', 'b')\n"
        assert set(rules_of(source)) == {"io_module_import", "io_module_call"}


class TestBuiltinOpen:
    def test_open_call_flagged(self):
        assert rules_of("with open('f.txt') as handle:\n    data = handle.read()\n") == [
            "io_builtin_open"
        ]

    def test_open_in_expression_flagged(self):
        assert rules_of("text = open('f.txt', encoding='utf-8').read()\n") == [
            "io_builtin_open"
        ]


class TestPathIoMethods:
    def test_write_text_flagged(self):
        source = "from pathlib import Path\nPath('x').write_text('data')\n"
        assert rules_of(source) == ["io_path_method"]

    def test_read_text_and_exists_flagged(self):
        source = "from pathlib import Path\np = Path('x')\nif p.exists():\n    p.read_text()\n"
        assert set(rules_of(source)) == {"io_path_method"}

    def test_path_construction_alone_passes(self):
        # Value-object construction is pure (measured posture: version.py
        # payloads carry Path values).
        source = "from pathlib import Path\nexe = Path('tsp.exe')\n"
        assert violations_of(source) == []


class TestOsFunctions:
    def test_os_remove_flagged(self):
        source = "import os\nos.remove('x')\n"
        assert rules_of(source) == ["io_os_function"]

    def test_os_system_flagged(self):
        source = "import os\nos.system('dir')\n"
        assert rules_of(source) == ["io_os_function"]

    def test_os_path_join_passes(self):
        # os.path helpers are string arithmetic, not I/O.
        assert violations_of("import os\np = os.path.join('a', 'b')\n") == []


class TestSqliteFileConnect:
    def test_file_path_connect_flagged(self):
        assert rules_of("import sqlite3\nsqlite3.connect('db.sqlite3')\n") == [
            "io_sqlite_file"
        ]

    def test_memory_connect_passes(self):
        # Documented unit posture: in-memory SQLite is not file I/O.
        source = (
            "import sqlite3\n"
            "conn = sqlite3.connect(':memory:')\n"
        )
        assert violations_of(source) == []

    def test_db_memory_connect_passes(self):
        source = "from adapters.storage import db\nconn = db.connect(':memory:')\n"
        assert violations_of(source) == []

    def test_non_constant_connect_arg_escapes_the_heuristic(self):
        # Conservative: dynamic arguments are not proven file paths; the
        # heuristic only flags compile-time constants (documented boundary).
        source = "import sqlite3\nsqlite3.connect(path)\n"
        assert violations_of(source) == []


class TestResourceFixtures:
    def test_tmp_path_param_flagged(self):
        source = "def test_uses_tmp(tmp_path):\n    assert tmp_path\n"
        found = violations_of(source)
        assert [v.rule for v in found] == ["io_fixture_request"]
        assert found[0].line == 1

    def test_every_registered_fixture_param_is_flagged(self):
        for name in IO_FIXTURE_PARAMS:
            source = f"def test_uses({name}):\n    assert {name}\n"
            assert rules_of(source) == ["io_fixture_request"]

    def test_helper_function_param_flagged_too(self):
        source = "def _build(tmp_path):\n    return tmp_path\n"
        assert rules_of(source) == ["io_fixture_request"]

    def test_capture_fixtures_are_not_resource_io(self):
        # caplog/capsys capture in-process; they reach no disk/network/subprocess
        # (documented boundary of the resource-fixture rule).
        source = "def test_captures(caplog):\n    assert caplog\n"
        assert violations_of(source) == []

    def test_plain_params_pass(self):
        assert violations_of("def test_plain(seed):\n    assert seed\n") == []


class TestWaivers:
    def test_waiver_comment_suppresses_line_finding(self):
        source = "import subprocess  # io-ok: fresh-interpreter acyclicity proof\n"
        assert violations_of(source) == []

    def test_waiver_on_call_line_suppresses(self):
        source = (
            "from pathlib import Path\n"
            "Path('x').write_text('data')  # io-ok: reason here\n"
        )
        assert violations_of(source) == []

    def test_waiver_does_not_hide_other_lines(self):
        source = (
            "from pathlib import Path\n"
            "a = Path('x')\n"
            "a.unlink()  # io-ok: covered\n"
            "b = Path('y')\n"
            "b.unlink()\n"
        )
        found = violations_of(source)
        assert [v.line for v in found] == [5]


class TestSanctionedCodePasses:
    def test_documented_unit_postures_pass(self):
        # The exact shapes the unit layer legitimately uses today (in-memory
        # storage tests, deterministic constructors, pure parsing).
        source = (
            "import sqlite3\n"
            "from adapters.storage import db\n"
            "from tests._support.deterministic import seeded_ts_stream\n"
            "\n"
            "SYNC = b'\\x47'\n"
            "\n"
            "def _journal():\n"
            "    conn = db.connect(':memory:')\n"
            "    return conn\n"
            "\n"
            "def test_stream():\n"
            "    stream = seeded_ts_stream(seed=1, packet_count=3)\n"
            "    assert stream[0] == SYNC\n"
        )
        assert violations_of(source) == []

    def test_syntax_error_source_reported_not_crashed(self):
        assert violations_of("def broken(:\n") == []
