"""Marker-discipline pure logic (SPEC-505 §3/§8, ticket #22).

Directory is the layer source of truth: a test file under
``tests/<layer>/`` belongs to that layer. This module is deliberately free
of pytest imports so the unit layer can test it without I/O; the root
conftest turns its verdicts into collection behavior:

- ``inject``  — no explicit layer marker present: conftest adds the derived
  layer marker (keeps parallel tickets' unmarked tests collectible).
- ``ok``      — explicit layer marker matches the directory.
- ``fail``    — explicit layer marker contradicts the directory: structural
  violation (SPEC-505 §8 分层互斥), hard collection failure.
- ``passthrough`` — path outside any layer directory (root conftest,
  _support): no layer semantics apply.
"""

from __future__ import annotations

from pathlib import Path

from tests._support.paths import TESTS_DIR

#: The four SPEC-505 §3 layers; marker name equals directory name.
LAYER_NAMES: tuple[str, ...] = ("unit", "integration", "conformance", "e2e")

_LAYER_BY_DIR: frozenset[str] = frozenset(LAYER_NAMES)

#: Verdict actions returned by :func:`check_layer_markers`.
ACTIONS: tuple[str, ...] = ("inject", "ok", "fail", "passthrough")


def layer_for_path(path: Path, tests_dir: Path = TESTS_DIR) -> str | None:
    """Layer name for a path under ``tests/<layer>/...``, else ``None``.

    The top-level directory component below ``tests/`` decides, so nested
    files still resolve to their layer. Paths outside ``tests_dir`` (or
    directly in ``tests/``, e.g. the root conftest and ``_support``) return
    ``None``.
    """
    resolved = Path(path).resolve()
    base = Path(tests_dir).resolve()
    try:
        rel = resolved.relative_to(base)
    except ValueError:
        return None
    if not rel.parts:
        return None
    head = rel.parts[0]
    return head if head in _LAYER_BY_DIR else None


def check_layer_markers(
    derived_layer: str | None, explicit_markers: frozenset[str] | set[str]
) -> tuple[str, str | None]:
    """Decide conftest action for one collected item.

    Returns ``(action, detail)`` where ``detail`` is the layer for
    ``inject``/``ok`` or a contradiction message for ``fail`` (``None`` for
    ``passthrough``).
    """
    if derived_layer is None:
        return ("passthrough", None)
    if derived_layer in explicit_markers:
        return ("ok", derived_layer)
    contradictions = sorted(set(LAYER_NAMES) & set(explicit_markers))
    if contradictions:
        return (
            "fail",
            "layer marker(s) {} contradict directory layer {!r} "
            "(SPEC-505 §8 分层互斥: directory is the layer source of truth)".format(
                contradictions, derived_layer
            ),
        )
    return ("inject", derived_layer)
