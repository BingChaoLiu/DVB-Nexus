"""Whitelist argv builder — SPEC-308 §3 ``command_builder.py`` (§5 discipline).

Single argv construction surface of the adapter:

- **Argument arrays only** (ADR-0003 第 4 条, ADR-0005 decision 6): every
  builder returns ``list[str]`` for ``create_subprocess_exec``-style spawn;
  no shell joining, no ``shell=True``, no string commands. Paths with
  spaces stay single elements — command visibility (the nine-field call
  record) shows exactly these elements.
- **MVP whitelist** (SPEC-308 §5, #4 measured plugin set + #3 generate
  chain): user configuration may never name an arbitrary CLI plugin;
  anything outside the whitelist raises ``TSDUCK_PLUGIN_NOT_ALLOWED``
  (§9 row 7, HTTP 422 at the API layer).
- The analyze builder is the only argv MVP actually constructs (analyze is
  the only enabled operation). The reserved inject/generate operations
  (MVP 显式拒绝, SPEC-308 §4) must route any future plugin argv through
  :func:`require_allowed_plugin` — the gate is the whitelist's enforcement
  point, so a future builder cannot silently bypass it.
"""

from __future__ import annotations

import sys
from pathlib import Path

from adapters.tsduck.errors import TSDuckPluginNotAllowedError

__all__ = [
    "PLUGIN_WHITELIST",
    "ANALYZE_TOOL",
    "ANALYZE_EXECUTABLE",
    "ANALYZE_JSON_FLAG",
    "build_analyze_argv",
    "require_allowed_plugin",
]

#: SPEC-308 §5 MVP whitelist (frozenset: configuration cannot widen it).
#: fuzz/craft/filter/slice/pcredit/inject/null/file = #4 实测插件集;
#: tsxml/tstabcomp/tsp = #3 golden 生成链. tsanalyze is not a plugin —
#: it is the analyze entry tool and needs no whitelist entry (the MVP
#: analyze argv is fully builder-controlled, no user-named components).
PLUGIN_WHITELIST = frozenset(
    {
        "fuzz",
        "craft",
        "filter",
        "slice",
        "pcredit",
        "inject",
        "null",
        "file",
        "tsxml",
        "tstabcomp",
        "tsp",
    }
)

#: The analyze entry tool (tsduck-env.md §6.2: ``tsanalyze --json <file>``).
ANALYZE_TOOL = "tsanalyze"

#: The on-disk analyze executable name — derived from the single tool-name
#: source above (review fix B3), never a second hardcoded "tsanalyze".
#: Windows installs ship ``tsanalyze.exe``; POSIX installs ship ``tsanalyze``
#: (tsduck-env.md §2.1, #35 ts_e2e seam-3 layout).
ANALYZE_EXECUTABLE = ANALYZE_TOOL + (".exe" if sys.platform == "win32" else "")

#: JSON report flag — stdout is the only JSON channel (tsduck-env.md §4.3).
ANALYZE_JSON_FLAG = "--json"


def build_analyze_argv(ts_file: str | Path) -> list[str]:
    """Build the MVP analyze argv: ``["tsanalyze", "--json", <file>]``.

    The path is one argv element, passed through ``str()`` verbatim —
    no quoting, no escaping, no shell interpretation anywhere downstream
    (spawn is ``asyncio.create_subprocess_exec``-shaped argument arrays).
    """
    return [ANALYZE_TOOL, ANALYZE_JSON_FLAG, str(ts_file)]


def require_allowed_plugin(plugin: str) -> str:
    """Whitelist gate for any user-named CLI plugin (SPEC-308 §5).

    Returns the stripped plugin name when allowed; raises
    ``TSDUCK_PLUGIN_NOT_ALLOWED`` otherwise. Exact-match (case-sensitive):
    plugin names are identifiers, and a case-insensitive shortcut would
    silently pass look-alikes.
    """
    name = plugin.strip()
    if name not in PLUGIN_WHITELIST:
        raise TSDuckPluginNotAllowedError(
            f"plugin {plugin!r} is outside the SPEC-308 §5 MVP whitelist "
            f"(allowed: {', '.join(sorted(PLUGIN_WHITELIST))})"
        )
    return name
