"""Unit-layer I/O structural rule engine (SPEC-505 §8 分层互斥, review-fix #6).

SPEC-505 §8: "分层互斥：unit 层出现 I/O 即结构违规。" The documented
operational interpretation (tests/README.md §1) is what this module makes
enforceable: unit tests request no resource-class fixtures, touch no disk,
spawn no subprocesses, and open no network. Like the 禁手拼字节 engine
(:mod:`tests._support.data_rules`, the model to follow), it parses Python
sources with :mod:`ast` (exact, no regex guessing) and reports

- ``io_fixture_request`` — a function parameter requesting a resource-class
  pytest fixture (``tmp_path`` / ``tmp_path_factory`` / ``tmpdir`` /
  ``monkeypatch``);
- ``io_builtin_open``  — a builtin ``open(...)`` call;
- ``io_path_method``   — Path-style I/O attribute calls (``write_text``,
  ``read_bytes``, ``unlink``, ``mkdir``, ``exists``, ... — stat probes
  included; pure ``resolve`` normalization excluded);
- ``io_os_function``   — ``os.<io>`` calls (file mutation, listing,
  ``system``/``popen``/exec/spawn families); ``os.path`` helpers stay pure;
- ``io_module_import`` — import of an I/O module (subprocess, shutil,
  tempfile, socket, httpx, requests, urllib, ftplib, smtplib) — aliases and
  from-imports included, so aliased usage is caught at the import line;
- ``io_module_call``   — attribute call on a bare I/O module name;
- ``io_sqlite_file``   — a ``connect(...)`` call whose first argument is a
  compile-time string other than ``":memory:"``. In-memory SQLite is the
  documented unit-layer posture (no file I/O — see
  tests/unit/adapters/storage/test_journal.py); dynamic arguments escape
  the heuristic (conservative, like data_rules thresholds).

Line-level waiver: a trailing/adjacent comment containing ``io-ok:``
suppresses findings whose source span covers that line. Waivers must state
a reason; they are grep-visible review focus points.

Out of scope (kept honest, not silently): wall-clock *assertions* are the
§6/§8 determinism discipline, not the I/O rule, and are not detected here.
``scan_tree`` applies the rules to a real tree — the CI 必绿组合 gate is
``tests/integration/test_unit_io_rules.py`` scanning the whole
``tests/unit/`` tree.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

#: Resource-class pytest fixtures a unit test must not request
#: (tests/README.md §1: "不请求 tmp_path / monkeypatch 等资源类 fixture").
#: Capture fixtures (caplog/capsys/capfd) stay in-process and are not I/O.
IO_FIXTURE_PARAMS: frozenset[str] = frozenset(
    {"tmp_path", "tmp_path_factory", "tmpdir", "monkeypatch"}
)

#: Modules whose import is I/O intent (process, filesystem, network).
IO_MODULE_NAMES: frozenset[str] = frozenset(
    {
        "subprocess",
        "shutil",
        "tempfile",
        "socket",
        "httpx",
        "requests",
        "urllib",
        "ftplib",
        "smtplib",
    }
)

#: Path-style I/O attribute calls (read/write/mutate/stat-probe).
PATH_IO_METHODS: frozenset[str] = frozenset(
    {
        "open",
        "read_text",
        "read_bytes",
        "write_text",
        "write_bytes",
        "unlink",
        "rmdir",
        "mkdir",
        "touch",
        "rename",
        "replace",
        "iterdir",
        "glob",
        "rglob",
        "stat",
        "lstat",
        "chmod",
        "exists",
        "is_dir",
        "is_file",
        "is_symlink",
        "is_block_device",
        "is_char_device",
        "is_fifo",
        "is_socket",
    }
)

#: ``os`` attribute calls that perform I/O (mutation, listing, processes).
#: ``os.path`` arithmetic (join/split/...) and pure constants stay allowed.
OS_IO_FUNCTIONS: frozenset[str] = frozenset(
    {
        "system",
        "popen",
        "startfile",
        "fork",
        "remove",
        "removedirs",
        "rename",
        "renames",
        "replace",
        "rmdir",
        "unlink",
        "mkdir",
        "makedirs",
        "listdir",
        "scandir",
        "walk",
        "stat",
        "lstat",
        "truncate",
        "link",
        "symlink",
        "readlink",
    }
)

#: In-memory SQLite token (documented unit-layer posture: no file I/O).
MEMORY_DB_TOKEN: str = ":memory:"

#: Waiver comment token (must be followed by ": " + reason in practice).
WAIVER_MARK: str = "io-ok"

RULE_IO_FIXTURE_REQUEST = "io_fixture_request"
RULE_IO_BUILTIN_OPEN = "io_builtin_open"
RULE_IO_PATH_METHOD = "io_path_method"
RULE_IO_OS_FUNCTION = "io_os_function"
RULE_IO_MODULE_IMPORT = "io_module_import"
RULE_IO_MODULE_CALL = "io_module_call"
RULE_IO_SQLITE_FILE = "io_sqlite_file"

_PROCESS_FAMILIES = ("exec", "spawn")


@dataclass(frozen=True)
class Violation:
    """One unit-layer I/O finding."""

    filename: str
    line: int
    rule: str
    snippet: str

    def __str__(self) -> str:  # pragma: no cover - display helper
        return f"{self.filename}:{self.line}: {self.rule}: {self.snippet}"


def _waived(lines: list[str], node: ast.AST) -> bool:
    """True if a waiver comment covers the node's span or the line right
    after it (parenthesized expressions carry their waiver on the next
    line) — same window discipline as the data_rules engine."""
    start = getattr(node, "lineno", None)
    end = getattr(node, "end_lineno", None) or start
    if start is None:
        return False
    first = start - 1
    last = min(end, len(lines))  # end (1-based) inclusive == index end
    window = range(first, last + 1)
    return any(0 <= offset < len(lines) and WAIVER_MARK in lines[offset] for offset in window)


def _is_io_module_import(node: ast.AST) -> bool:
    """True for Import/ImportFrom of a banned I/O module (aliases count)."""
    if isinstance(node, ast.Import):
        return any(
            alias.name == module or alias.name.startswith(module + ".")
            for module in IO_MODULE_NAMES
            for alias in node.names
        )
    if isinstance(node, ast.ImportFrom):
        if node.module is None:
            return False
        return any(
            node.module == module or node.module.startswith(module + ".")
            for module in IO_MODULE_NAMES
        )
    return False


def _call_name(node: ast.Call) -> tuple[str | None, str | None]:
    """Return ``(base_name, attribute_name)`` of the call's target."""
    func = node.func
    if isinstance(func, ast.Name):
        return func.id, None
    if isinstance(func, ast.Attribute):
        base = func.value.id if isinstance(func.value, ast.Name) else None
        return base, func.attr
    return None, None


def _classify_call(node: ast.Call) -> str | None:
    base, attr = _call_name(node)
    if base == "open":
        return RULE_IO_BUILTIN_OPEN
    if attr is not None:
        if base == "os" and (
            attr in OS_IO_FUNCTIONS or attr.startswith(_PROCESS_FAMILIES)
        ):
            return RULE_IO_OS_FUNCTION
        if base in IO_MODULE_NAMES:
            return RULE_IO_MODULE_CALL
        if attr in PATH_IO_METHODS:
            return RULE_IO_PATH_METHOD
        if attr == "connect" and node.args:
            first = node.args[0]
            if (
                isinstance(first, ast.Constant)
                and isinstance(first.value, str)
                and first.value != MEMORY_DB_TOKEN
            ):
                return RULE_IO_SQLITE_FILE
    elif base == "connect" and node.args:
        first = node.args[0]
        if (
            isinstance(first, ast.Constant)
            and isinstance(first.value, str)
            and first.value != MEMORY_DB_TOKEN
        ):
            return RULE_IO_SQLITE_FILE
    return None


def _fixture_param_violations(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> list[ast.arg]:
    args = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
    return [arg for arg in args if arg.arg in IO_FIXTURE_PARAMS]


def find_io_violations(source: str, *, filename: str = "<memory>") -> list[Violation]:
    """Report unit-layer I/O shapes in one Python source text.

    Unparsable sources yield no findings (syntax errors are the tests'
    own collection failures, not layer-discipline findings).
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    lines = source.splitlines()
    findings: list[Violation] = []

    for node in ast.walk(tree):
        if _is_io_module_import(node):
            if not _waived(lines, node):
                name = (
                    node.names[0].name
                    if isinstance(node, ast.Import)
                    else f"from {node.module} import ..."
                )
                findings.append(
                    Violation(filename, node.lineno, RULE_IO_MODULE_IMPORT, name)
                )
        elif isinstance(node, ast.Call):
            rule = _classify_call(node)
            if rule and not _waived(lines, node):
                findings.append(
                    Violation(filename, node.lineno, rule, ast.dump(node)[:60])
                )
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for arg in _fixture_param_violations(node):
                if not _waived(lines, arg):
                    findings.append(
                        Violation(
                            filename,
                            arg.lineno,
                            RULE_IO_FIXTURE_REQUEST,
                            f"{node.name}({arg.arg})",
                        )
                    )

    findings.sort(key=lambda violation: (violation.line, violation.rule))
    return findings


def scan_tree(root: Path) -> list[Violation]:
    """Scan ``*.py`` files under ``root`` (the unit layer for the CI gate).

    Files are read with explicit ``encoding="utf-8"`` (Windows-first).
    """
    violations: list[Violation] = []
    for path in sorted(Path(root).rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        violations.extend(find_io_violations(source, filename=str(path)))
    return violations
