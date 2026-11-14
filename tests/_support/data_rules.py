"""Executable 禁手拼字节 rule engine (SPEC-505 §6, #14 裁决延伸).

Static test bytes may only come from registered golden assets, the fixed-seed
deterministic constructors (:mod:`tests._support.deterministic`), or
checked-in files under ``tests/data/`` — never from hand-assembled byte
material inside test code. This module makes that rule enforceable: it
parses Python sources with :mod:`ast` (exact, no regex guessing) and reports

- ``bytes_literal``   — bytes constants longer than ``MAX_BYTES_LITERAL``,
  including ``b"x" * n`` multiplications exceeding the limit;
- ``bytes_int_list``  — ``bytes([...])`` / ``bytearray([...])`` built from
  all-constant int lists (``[0x47] * n`` counted via the product);
- ``bytes_fromhex``   — ``bytes.fromhex("…")`` / ``binascii.unhexlify("…")``
  with at least ``MIN_HEX_CHARS`` hex characters.

Line-level waiver: a trailing/adjacent comment containing ``testdata-ok:``
suppresses findings whose source span covers that line. Waivers must state a
reason; they are grep-visible review focus points.

``scan_tree`` applies the rules to a real tree; it skips ``_support/`` — the
sanctioned constructor zone — and is wired into the CI 必绿组合 via
``tests/integration/test_test_data_tree_rules.py``. Thresholds are
conservative heuristics; raising them requires justification in review.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

#: Bytes literals strictly longer than this are hand-assembly (16 bytes
#: covers sync/PID/short markers; a 188-byte packet is 188).
MAX_BYTES_LITERAL: int = 16

#: All-constant int lists passed to bytes()/bytearray() from this size on
#: are hand-assembly.
MIN_INT_LIST: int = 16

#: Hex-string constructions from this many hex chars on are hand-assembly
#: (32 hex chars = 16 bytes).
MIN_HEX_CHARS: int = 32

#: Waiver comment token (must be followed by ": " + reason in practice).
WAIVER_MARK: str = "testdata-ok"

#: Directory name exempt from scanning (sanctioned constructor zone).
SUPPORT_DIRNAME: str = "_support"

RULE_BYTES_LITERAL = "bytes_literal"
RULE_BYTES_INT_LIST = "bytes_int_list"
RULE_BYTES_FROMHEX = "bytes_fromhex"


@dataclass(frozen=True)
class Violation:
    """One hand-assembled-bytes finding."""

    filename: str
    line: int
    rule: str
    snippet: str

    def __str__(self) -> str:  # pragma: no cover - display helper
        return f"{self.filename}:{self.line}: {self.rule}: {self.snippet}"


def _waived(lines: list[str], node: ast.AST) -> bool:
    """True if a waiver comment covers the node's span or the line right
    after it (parenthesized literals carry their waiver on the next line)."""
    start = getattr(node, "lineno", None)
    end = getattr(node, "end_lineno", None) or start
    if start is None:
        return False
    first = start - 1
    last = min(end, len(lines))  # end (1-based) inclusive == index end
    window = range(first, last + 1)
    return any(0 <= offset < len(lines) and WAIVER_MARK in lines[offset] for offset in window)


def _static_int_count(node: ast.AST) -> int | None:
    """Element count of an all-constant int list expression, else None.

    Handles literal lists/tuples and constant multiplies like ``[0x47] * n``.
    """
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
        left = _static_int_count(node.left)
        if isinstance(node.right, ast.Constant) and isinstance(node.right.value, int):
            multiplier = node.right.value
        else:
            multiplier = None
        if left is not None and multiplier is not None:
            return left * multiplier
        return None
    if isinstance(node, (ast.List, ast.Tuple)):
        values: list[int] = []
        for element in node.elts:
            if isinstance(element, ast.Constant) and isinstance(element.value, int):
                values.append(element.value)
            else:
                return None
        return len(values)
    return None


def _classify_call(node: ast.Call) -> str | None:
    func = node.func
    name: str | None = None
    if isinstance(func, ast.Name):
        name = func.id
    elif isinstance(func, ast.Attribute):
        name = func.attr

    if name in ("bytes", "bytearray"):
        if node.args and node.args[0] is not None:
            count = _static_int_count(node.args[0])
            if count is not None and count >= MIN_INT_LIST:
                return RULE_BYTES_INT_LIST
        return None
    if name == "fromhex" or name == "unhexlify":
        if node.args and isinstance(node.args[0], ast.Constant):
            value = node.args[0].value
            if isinstance(value, str) and len(value) >= MIN_HEX_CHARS:
                return RULE_BYTES_FROMHEX
    return None


def find_hand_assembled_bytes(
    source: str, *, filename: str = "<memory>"
) -> list[Violation]:
    """Report hand-assembled byte material in one Python source text.

    Unparsable sources yield no findings (syntax errors are the tests'
    own collection failures, not data-discipline findings).
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    lines = source.splitlines()
    findings: list[Violation] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, bytes):
            if len(node.value) > MAX_BYTES_LITERAL and not _waived(lines, node):
                findings.append(
                    Violation(filename, node.lineno, RULE_BYTES_LITERAL, repr(node.value)[:60])
                )
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
            left, right = node.left, node.right
            bytes_side = None
            int_side = None
            for a, b in ((left, right), (right, left)):
                if (
                    isinstance(a, ast.Constant)
                    and isinstance(a.value, bytes)
                    and isinstance(b, ast.Constant)
                    and isinstance(b.value, int)
                ):
                    bytes_side, int_side = a, b
                    break
            if (
                bytes_side is not None
                and len(bytes_side.value) * int_side.value > MAX_BYTES_LITERAL
                and not _waived(lines, node)
            ):
                findings.append(
                    Violation(filename, node.lineno, RULE_BYTES_LITERAL, "bytes literal * int")
                )
        elif isinstance(node, ast.Call):
            rule = _classify_call(node)
            if rule and not _waived(lines, node):
                findings.append(
                    Violation(filename, node.lineno, rule, ast.dump(node)[:60])
                )

    findings.sort(key=lambda violation: (violation.line, violation.rule))
    return findings


def scan_tree(
    root: Path,
    *,
    skip_dir_names: frozenset[str] = frozenset({SUPPORT_DIRNAME}),
) -> list[Violation]:
    """Scan ``*.py`` files under ``root`` (skipping exempt directory names).

    Files are read with explicit ``encoding="utf-8"`` (Windows-first).
    """
    violations: list[Violation] = []
    for path in sorted(Path(root).rglob("*.py")):
        if any(part in skip_dir_names for part in path.parts):
            continue
        source = path.read_text(encoding="utf-8")
        violations.extend(find_hand_assembled_bytes(source, filename=str(path)))
    return violations
