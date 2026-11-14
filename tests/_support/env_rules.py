"""Real-environment literal-assertion rule engine (tests/README.md §6, ticket #70).

The #69 CI first-run lesson: tests carrying the real-environment markers
pinned the *reference machine's* environment — the version token
``3.40-4165``, the drive-letter path ``D:\\...``, the on-disk casing
``tsp.exe`` — and went red on a *correct* probe when winget installed
3.45-4798 on the runner. §6 now mandates shape assertions; this module
makes that rule mechanically enforceable, in the style of the
:mod:`tests._support.data_rules` / :mod:`tests._support.io_rules` engines:
exact :mod:`ast` analysis (no regex guessing over source text), conservative
shapes, and line-level waivers.

Scan surface — a ``*.py`` file under ``tests/`` (``tests/_support/`` itself
excluded: the sanctioned constructor zone) that *statically* carries a
real-environment marker (``tsduck`` / ``windows_only``), via a module-level
``pytestmark`` assignment (marker attribute or plain string entry) or any
function-level decorator. Both markers are in scope per ticket #70; the
incident class is machine-varying toolchain state, and both markers mark
tests whose assertions may observe it.

Violations (all conservative; only compile-time ``str`` constants):

- ``env_version_literal`` — a version-shaped token (``\\d+\\.\\d+-\\d+``)
  anywhere inside a string constant used in an ``==`` / ``!=`` / ``in`` /
  ``not in`` comparison (containment included: the #69 update-notification
  noise line embeds the token in longer text). Named-constant comparisons,
  integer component pins, and shape-regex strings (which contain no digit
  characters) escape on purpose — documented conservative bounds.
- ``env_drive_path_literal`` — a string constant containing a drive-letter
  path (``[A-Za-z]:[\\\\/]``) in *any* expression context. Scripted
  fixtures live in ``tmp_path``, so an absolute drive path in test text is
  always a pin candidate; relative paths, UNC shares, and the
  platform-fixed ``os.sep`` constant escape.
- ``env_executable_name_comparison`` — a bare filename constant with an
  executable suffix (``.exe`` / ``.cmd`` / ``.bat`` / ``.ps1`` / ``.dll`` /
  ``.com``) compared with ``==`` / ``!=`` / ``in`` / ``not in`` where the
  other operand is not itself a constant. Comparisons that are
  case-insensitive by construction (either operand subtree calls
  ``lower()`` / ``upper()`` / ``casefold()`` — the documented §6
  shape-assertion form) and data-file suffixes (golden/asset names are
  synthetic-fixture anchors) escape.

Docstrings are exempt everywhere: incident narratives and fixture anchors
cite the measured tokens verbatim (that is what made them greppable in the
first place). f-strings escape the constant-only heuristic (documented
bound — a constant part of a ``JoinedStr`` is not an ``ast.Constant``).

Line-level waiver: a comment containing ``env-ok:`` suppresses findings
whose source span covers that line (plus the line after, for parenthesized
expressions) — same window discipline as the io_rules engine. Waivers must
state a reason; they are grep-visible review focus points and the zero-waiver
surface is the standing goal (tests/README.md §6).

Out of scope (kept honest, not silently): integer component pins
(``(3, 40, 4165)``) are fixture data outside the string-literal shapes;
assignment-site constants are review-visible fixture anchors, not
comparison pins. ``scan_tree`` applies the rules to a real tree — the CI
必绿组合 gate is ``tests/integration/test_real_env_rules.py`` scanning the
whole ``tests/`` tree.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

#: Real-environment markers (ticket #70 scan surface; pyproject registration
#: is the authoritative wording, these are the statically readable names).
REAL_ENV_MARKERS: frozenset[str] = frozenset({"tsduck", "windows_only"})

#: Measured version-token shape (tests/README.md §6, tsduck-env.md §2.1).
VERSION_TOKEN_RE: re.Pattern[str] = re.compile(r"\d+\.\d+-\d+")

#: Drive-letter path shape (the #69 pin class; forward slashes included).
DRIVE_PATH_RE: re.Pattern[str] = re.compile(r"[A-Za-z]:[\\/]")

#: Executable suffixes whose on-disk casing varies per install (#69 shape 3).
#: Data-file suffixes (.ts/.xml/.md/...) are synthetic-fixture anchors and
#: deliberately out of scope.
EXECUTABLE_SUFFIXES: frozenset[str] = frozenset(
    {".exe", ".cmd", ".bat", ".ps1", ".dll", ".com"}
)

#: Comparison operators that count as pinning (identity ``is`` is not:
#: it never appears in value assertions).
PINNING_OPS: tuple[type[ast.cmpop], ...] = (ast.Eq, ast.NotEq, ast.In, ast.NotIn)

#: Methods whose presence makes a comparison case-insensitive by construction.
CASEFOLD_METHODS: frozenset[str] = frozenset({"lower", "upper", "casefold"})

#: Waiver comment token (must be followed by a reason in practice).
WAIVER_MARK: str = "env-ok"

RULE_ENV_VERSION_LITERAL = "env_version_literal"
RULE_ENV_DRIVE_PATH_LITERAL = "env_drive_path_literal"
RULE_ENV_EXECUTABLE_NAME_COMPARISON = "env_executable_name_comparison"

#: Tree-scan zone excluded from the gate (sanctioned constructor/test-support
#: area — same discipline as the data_rules engine's scan surface).
SUPPORT_DIR_NAME = "_support"


@dataclass(frozen=True)
class Violation:
    """One real-environment literal finding."""

    filename: str
    line: int
    rule: str
    snippet: str

    def __str__(self) -> str:  # pragma: no cover - display helper
        return f"{self.filename}:{self.line}: {self.rule}: {self.snippet}"


def _waived(lines: list[str], node: ast.AST) -> bool:
    """True if an ``env-ok:`` comment covers the node's span or the line
    right after it (parenthesized expressions carry their waiver on the
    next line) — same window discipline as the io_rules engine."""
    start = getattr(node, "lineno", None)
    end = getattr(node, "end_lineno", None) or start
    if start is None:
        return False
    first = start - 1
    last = min(end, len(lines))  # end (1-based) inclusive == index end
    window = range(first, last + 1)
    return any(0 <= offset < len(lines) and WAIVER_MARK in lines[offset] for offset in window)


def _marker_attribute_name(node: ast.AST) -> str | None:
    """Marker name for a ``pytest.mark.<name>`` attribute chain, else None."""
    if isinstance(node, ast.Attribute) and node.attr in REAL_ENV_MARKERS:
        base = node.value
        if isinstance(base, ast.Attribute) and base.attr == "mark":
            return node.attr
    return None


def has_real_env_marker(source: str) -> bool:
    """True if the source statically carries a real-environment marker.

    Detected forms: ``pytest.mark.<marker>`` attribute chains (module
    ``pytestmark`` entries and function decorators alike) and plain string
    entries inside a ``pytestmark`` assignment (pytest accepts marker-name
    strings). Unparsable sources report no marker (their syntax error is
    the file's own collection failure, not a scope question).
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if _marker_attribute_name(node) is not None:
            return True
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            value = node.value
            if not isinstance(value, (ast.List, ast.Tuple)):
                continue
            for element in value.elts:
                if isinstance(element, ast.Constant) and element.value in REAL_ENV_MARKERS:
                    return True
    return False


def _docstring_nodes(tree: ast.Module) -> set[int]:
    """Node ids of docstring constants (module/class/function first stmts)."""
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body:
                first = body[0]
                if (
                    isinstance(first, ast.Expr)
                    and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)
                ):
                    docstrings.add(id(first.value))
    return docstrings


def _is_string_constant(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


def _has_casefold_call(node: ast.AST) -> bool:
    """True if the subtree calls lower()/upper()/casefold() anywhere —
    the comparison is then case-insensitive by construction (§6 form)."""
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            func = child.func
            if isinstance(func, ast.Attribute) and func.attr in CASEFOLD_METHODS:
                return True
    return False


def _executable_name(value: str) -> bool:
    """True for a bare filename constant with an executable suffix."""
    if "/" in value or "\\" in value:
        return False  # path shapes belong to the drive-path rule
    if len(value) > 64 or "." not in value:
        return False
    suffix = value[value.rindex("."):]
    return suffix.lower() in EXECUTABLE_SUFFIXES


def _literal_candidates(operand: ast.AST) -> list[ast.Constant]:
    """String constants in pinning position on one comparison side.

    A bare constant, or the string elements of a list/tuple literal
    (membership pins: ``assert probe.token in ["3.40-4165"]``).
    """
    if _is_string_constant(operand):
        return [operand]
    if isinstance(operand, (ast.List, ast.Tuple)):
        return [elt for elt in operand.elts if _is_string_constant(elt)]
    return []


def _pairs(literal_side: ast.AST, other_side: ast.AST) -> list[tuple[ast.Constant, ast.AST]]:
    return [(literal, other_side) for literal in _literal_candidates(literal_side)]


def _comparison_findings(
    node: ast.Compare,
    lines: list[str],
    docstrings: set[int],
    filename: str,
) -> list[Violation]:
    """Version-token and executable-name pins inside comparison operands."""
    findings: list[Violation] = []
    operands = [node.left, *node.comparators]
    ops = list(node.ops)
    for index, op in enumerate(ops):
        if not isinstance(op, PINNING_OPS):
            continue
        left = operands[index]
        right = operands[index + 1]
        for literal, other in (*_pairs(left, right), *_pairs(right, left)):
            if id(literal) in docstrings:
                continue
            value = literal.value
            if VERSION_TOKEN_RE.search(value):
                rule = RULE_ENV_VERSION_LITERAL
            elif _executable_name(value) and not _is_string_constant(other):
                if _has_casefold_call(other):
                    continue  # §6 case-insensitive-by-construction shape
                rule = RULE_ENV_EXECUTABLE_NAME_COMPARISON
            else:
                continue
            if not _waived(lines, literal):
                findings.append(
                    Violation(filename, literal.lineno, rule, value[:60])
                )
    return findings


def find_env_violations(source: str, *, filename: str = "<memory>") -> list[Violation]:
    """Report real-environment literal shapes in one Python source text.

    Sources without a real-environment marker are out of scope (no
    findings); unparsable sources yield no findings (syntax errors are the
    tests' own collection failures, not discipline findings).
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    if not has_real_env_marker(source):
        return []

    lines = source.splitlines()
    docstrings = _docstring_nodes(tree)
    findings: list[Violation] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            findings.extend(_comparison_findings(node, lines, docstrings, filename))
        elif _is_string_constant(node) and id(node) not in docstrings:
            # Drive-letter paths are pins in any context: scripted fixtures
            # live in tmp_path, so an absolute drive path in test text is
            # never a sanctioned construction site.
            if DRIVE_PATH_RE.search(node.value) and not _waived(lines, node):
                findings.append(
                    Violation(filename, node.lineno, RULE_ENV_DRIVE_PATH_LITERAL, node.value[:60])
                )

    findings.sort(key=lambda violation: (violation.line, violation.rule))
    return findings


def scan_tree(root: Path, *, skip_support: bool = True) -> list[Violation]:
    """Scan ``*.py`` files under ``root`` (the tests tree for the CI gate).

    With ``skip_support`` (default), ``tests/_support/`` is excluded — the
    sanctioned constructor zone, whose own correctness is constrained by the
    unit layer (tests/README.md §5 discipline). Files are read with explicit
    ``encoding="utf-8"`` (Windows-first).
    """
    violations: list[Violation] = []
    for path in sorted(Path(root).rglob("*.py")):
        if skip_support and SUPPORT_DIR_NAME in path.parts:
            continue
        source = path.read_text(encoding="utf-8")
        violations.extend(find_env_violations(source, filename=str(path)))
    return violations
