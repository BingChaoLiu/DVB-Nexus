"""Whitelist argv builder tests (SPEC-308 §5, REQ-TSK-308-002).

The builder is the adapter's single argv construction surface: argument
arrays only (禁 shell=True, ADR-0003 第 4 条), MVP whitelist per SPEC-308
§5, and the reserved inject/generate operations must route plugin names
through the same gate. Command visibility: the produced argv is exactly
what lands in the nine-field call record.
"""

from __future__ import annotations

import pytest

from adapters.tsduck.command_builder import (
    PLUGIN_WHITELIST,
    build_analyze_argv,
    require_allowed_plugin,
)
from adapters.tsduck.errors import TSDuckPluginNotAllowedError

#: SPEC-308 §5 MVP whitelist, transcribed (票面 + #4 实测插件集 + #3 生成链).
SPEC_308_SECTION_5_WHITELIST = {
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


class TestWhitelistContent:
    def test_whitelist_matches_section_5(self):
        assert set(PLUGIN_WHITELIST) == SPEC_308_SECTION_5_WHITELIST

    def test_whitelist_is_frozen(self):
        # Mutable module state would let configuration widen the gate.
        assert isinstance(PLUGIN_WHITELIST, frozenset)


class TestAnalyzeArgv:
    def test_analyze_argv_is_argument_array_with_json_flag_and_path(self):
        argv = build_analyze_argv(r"D:\data\golden.ts")
        assert argv == ["tsanalyze", "--json", r"D:\data\golden.ts"]

    def test_pathlib_input_accepted_and_stringified(self):
        from pathlib import Path

        argv = build_analyze_argv(Path("docs") / "x.ts")
        assert argv == ["tsanalyze", "--json", str(Path("docs") / "x.ts")]

    def test_spaces_stay_inside_one_argument_no_shell_joining(self):
        """A path with spaces is ONE argv element — never a shell-joined
        command string (ADR-0003 第 4 条 argument-array discipline)."""
        spaced = r"D:\Program Files\TSDuck\data\my stream.ts"
        argv = build_analyze_argv(spaced)
        assert isinstance(argv, list)
        assert len(argv) == 3
        assert argv[-1] == spaced
        assert " " in argv[-1]
        joined = " ".join(argv)
        # The joined form adds exactly the two separator spaces; all other
        # spaces live inside the single path element.
        assert joined.count(" ") == spaced.count(" ") + 2

    def test_no_shell_metacharacters_introduced_by_builder(self):
        argv = build_analyze_argv("in.ts")
        for element in argv:
            assert not element.startswith("-c")
            assert "&&" not in element
            assert "|" not in element


class TestPluginGate:
    @pytest.mark.parametrize("plugin", sorted(SPEC_308_SECTION_5_WHITELIST))
    def test_whitelisted_plugin_passes(self, plugin):
        assert require_allowed_plugin(plugin) == plugin

    def test_whitespace_insensitive(self):
        assert require_allowed_plugin(" null ") == "null"

    @pytest.mark.parametrize("plugin", ["nosuchplugin", "dektec", "dvb", "srt", ""])
    def test_outside_whitelist_rejected(self, plugin):
        with pytest.raises(TSDuckPluginNotAllowedError) as excinfo:
            require_allowed_plugin(plugin)
        assert excinfo.value.code == "TSDUCK_PLUGIN_NOT_ALLOWED"
        assert plugin.strip() in str(excinfo.value)

    def test_case_sensitive_exact_match(self):
        """Plugin names are exact identifiers ('File' is not the file plugin
        and must not silently pass a case-insensitive shortcut)."""
        with pytest.raises(TSDuckPluginNotAllowedError):
            require_allowed_plugin("File")
