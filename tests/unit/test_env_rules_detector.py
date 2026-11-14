"""Unit-layer tests for the real-environment literal detector (ticket #70).

`find_env_violations` is a pure source-text analyzer: no I/O, no wall clock.
Tree-level application lives in the integration layer
(test_real_env_rules.py). This file is itself part of the scanned unit tree,
carries no real-environment marker, and therefore stays out of the gate's
scan surface — it exercises the detector on in-memory source strings only.

The three incident shapes from the #69 CI first run (version token pin,
drive-letter path pin, on-disk casing pin) are pinned here as flagged cases;
the documented §6 shape-assertion forms (`.lower()` normalization, named
constants, regex shape strings) are pinned as exempt.
"""

from __future__ import annotations

import re

from tests._support.env_rules import (
    EXECUTABLE_SUFFIXES,
    REAL_ENV_MARKERS,
    find_env_violations,
    has_real_env_marker,
)

#: The measured version token of the #69 incident (reference machine).
INCIDENT_VERSION = "3.40-4165"

#: The measured drive path shape of the #69 incident (drive letter pin).
INCIDENT_DRIVE_PATH = "D:\\Program Files\\TSDuck\\bin\\tsp.exe"

#: The measured UNC shape (escapes from the drive-path rule, conservative).
INCIDENT_UNC_PATH = "\\\\server\\share\\tsduck"

#: Measured token shape regex (tests/README.md §6) — pure framing text.
VERSION_SHAPE = re.compile(r"\d+\.\d+-\d+")


def py_escaped(value: str) -> str:
    """Escape a value for embedding as a string-literal body in generated
    source, so ast.parse sees the same value without invalid escapes.
    Split/join doubling instead of str.replace: the io_rules detector flags
    a ``.replace(...)`` attribute call as a Path-style I/O shape (unit-layer
    gate, conservative heuristic — no ``io-ok:`` waiver needed)."""
    return "\\\\".join(value.split("\\"))


def marked(body: str, marker: str = "tsduck") -> str:
    """Wrap a body in a module-level real-env pytestmark declaration."""
    return f"import pytest\npytestmark = [pytest.mark.{marker}]\n{body}\n"


def violations_of(source: str):
    return find_env_violations(source, filename="<test>")


def rules_of(source: str) -> list[str]:
    return [violation.rule for violation in violations_of(source)]


def lines_of(source: str) -> list[int]:
    return [violation.line for violation in violations_of(source)]


class TestScopeDetection:
    def test_module_pytestmark_puts_file_in_scope(self):
        source = marked(f'assert probe.version == "{INCIDENT_VERSION}"\n')
        assert rules_of(source) == ["env_version_literal"]

    def test_single_marker_pytestmark_in_scope(self):
        source = (
            "import pytest\n"
            "pytestmark = pytest.mark.windows_only\n"
            f'assert probe.version == "{INCIDENT_VERSION}"\n'
        )
        assert rules_of(source) == ["env_version_literal"]

    def test_function_level_decorator_puts_file_in_scope(self):
        source = (
            "import pytest\n\n"
            "@pytest.mark.tsduck\n"
            "def test_real_probe():\n"
            f'    assert probe.version == "{INCIDENT_VERSION}"\n'
        )
        assert rules_of(source) == ["env_version_literal"]

    def test_string_entry_in_pytestmark_in_scope(self):
        source = (
            "import pytest\n"
            'pytestmark = ["windows_only"]\n'
            f'assert probe.version == "{INCIDENT_VERSION}"\n'
        )
        assert rules_of(source) == ["env_version_literal"]

    def test_unmarked_file_with_identical_pin_is_ignored(self):
        source = f'assert probe.version == "{INCIDENT_VERSION}"\n'
        assert violations_of(source) == []

    def test_layer_only_markers_are_not_real_env(self):
        source = (
            "import pytest\n"
            "pytestmark = [pytest.mark.unit, pytest.mark.integration]\n"
            f'assert probe.version == "{INCIDENT_VERSION}"\n'
        )
        assert violations_of(source) == []

    def test_unrelated_list_assignment_is_out_of_scope(self):
        # The string-entry form requires the assignment target to be
        # ``pytestmark`` — an unrelated named list is a fixture constant
        # (review round #70: scope promise vs implementation).
        marker_name = next(iter(REAL_ENV_MARKERS))
        source = (
            f'EXPECTED = ["{marker_name}"]\n'
            f'assert probe.version == "{INCIDENT_VERSION}"\n'
        )
        assert violations_of(source) == []

    def test_has_real_env_marker_detection(self):
        assert has_real_env_marker(marked("x = 1\n")) is True
        assert has_real_env_marker(
            "import pytest\n\n@pytest.mark.windows_only\ndef test_a():\n    pass\n"
        ) is True
        assert has_real_env_marker("import pytest\npytestmark = [pytest.mark.unit]\n") is False

    def test_every_registered_real_env_marker_is_in_scope(self):
        for marker in REAL_ENV_MARKERS:
            source = marked(f'assert probe.version == "{INCIDENT_VERSION}"\n', marker)
            assert rules_of(source) == ["env_version_literal"]


class TestVersionLiteralRule:
    """#69 incident shape 1: the reference machine's version token pinned."""

    def test_direct_version_equality_pin_flagged(self):
        source = marked(f'assert probe.version == "{INCIDENT_VERSION}"\n')
        assert rules_of(source) == ["env_version_literal"]

    def test_version_literal_on_left_side_flagged(self):
        source = marked(f'assert "{INCIDENT_VERSION}" == probe.version\n')
        assert rules_of(source) == ["env_version_literal"]

    def test_version_containment_in_longer_text_flagged(self):
        # The #69 noise-line class: the update notification embeds a token.
        source = marked(
            'assert "yours is 3.40-4165" not in probe.raw_output\n'
        )
        assert rules_of(source) == ["env_version_literal"]

    def test_membership_comparison_flagged(self):
        source = marked(f'assert probe.token in ["{INCIDENT_VERSION}"]\n')
        assert rules_of(source) == ["env_version_literal"]

    def test_inequality_pin_flagged(self):
        source = marked(f'assert probe.version != "{INCIDENT_VERSION}"\n')
        assert rules_of(source) == ["env_version_literal"]

    def test_named_constant_comparison_escapes(self):
        # Conservative bound: a named constant is review-visible and may be a
        # scripted-fixture anchor (§6 字面钉扎只属于合成 fixture).
        source = marked(
            "EXPECTED = '3.40-4165'\nassert probe.version == EXPECTED\n"
        )
        assert violations_of(source) == []

    def test_regex_shape_string_escapes(self):
        # A shape pattern contains no digit characters — it is the §6
        # sanctioned assertion form, not a pin.
        source = marked('assert re.fullmatch(r"\\d+\\.\\d+-\\d+", probe.version)\n')
        assert violations_of(source) == []

    def test_integer_component_pins_escape(self):
        source = marked("assert (major, minor, build) == (3, 40, 4165)\n")
        assert violations_of(source) == []

    def test_version_in_docstring_escapes(self):
        source = marked(
            'def test_x():\n'
            f'    """Incident narrative cites {INCIDENT_VERSION} verbatim."""\n'
            "    assert probe.version is not None\n"
        )
        assert violations_of(source) == []

    def test_module_docstring_version_escapes(self):
        source = (
            f'"""Reference machine runs {INCIDENT_VERSION}; CI may differ."""\n'
            "import pytest\n"
            "pytestmark = [pytest.mark.tsduck]\n"
            "assert probe.available\n"
        )
        assert violations_of(source) == []


class TestDrivePathRule:
    """#69 incident shape 2: the reference machine's drive letter pinned."""

    def test_drive_path_equality_pin_flagged(self):
        source = marked(
            f'assert str(probe.path) == "{py_escaped(INCIDENT_DRIVE_PATH)}"\n'
        )
        assert rules_of(source) == ["env_drive_path_literal"]

    def test_drive_path_in_call_argument_flagged(self):
        # Fixtures live in tmp_path; an absolute drive path in test text is
        # a pin candidate in any context.
        source = marked(f'fallback = Path("{py_escaped(INCIDENT_DRIVE_PATH)}")\n')
        assert rules_of(source) == ["env_drive_path_literal"]

    def test_lowercase_drive_letter_flagged(self):
        tools_path = py_escaped("c:\\tools\\tsduck")
        source = marked(f'assert str(p).startswith("{tools_path}")\n')
        assert rules_of(source) == ["env_drive_path_literal"]

    def test_forward_slash_drive_path_flagged(self):
        source = marked('assert str(p) == "D:/TSDuck/bin"\n')
        assert rules_of(source) == ["env_drive_path_literal"]

    def test_relative_path_escapes(self):
        source = marked('expected = Path("bin") / "tsp.exe"\n')
        assert violations_of(source) == []

    def test_unc_path_escapes(self):
        # A UNC share is not a drive-letter pin (conservative bound).
        source = marked(f'assert str(p) == "{py_escaped(INCIDENT_UNC_PATH)}"\n')
        assert violations_of(source) == []

    def test_windows_sep_constant_escapes(self):
        # Platform-fixed semantics (windows_first assertions) are not pins.
        source = marked('assert os.sep == "\\\\"\n')
        assert violations_of(source) == []

    def test_drive_path_in_docstring_escapes(self):
        source = marked(
            'def test_x():\n'
            f'    """Fallback root is {py_escaped(INCIDENT_DRIVE_PATH)} on the box."""\n'
            "    assert probe.available\n"
        )
        assert violations_of(source) == []

    def test_drive_path_with_env_ok_waiver_escapes(self):
        source = marked(
            f'fallback = Path("{py_escaped(INCIDENT_DRIVE_PATH)}")'
            "  # env-ok: measured asset anchor\n"
        )
        assert violations_of(source) == []


class TestExecutableNameComparisonRule:
    """#69 incident shape 3: on-disk casing of the real pinned by comparison."""

    def test_case_sensitive_executable_name_equality_flagged(self):
        source = marked('assert probe.path.name == "tsp.exe"\n')
        assert rules_of(source) == ["env_executable_name_comparison"]

    def test_case_sensitive_membership_flagged(self):
        source = marked('assert "tsanalyze.exe" in str(probe.path)\n')
        assert rules_of(source) == ["env_executable_name_comparison"]

    def test_lower_normalized_comparison_escapes(self):
        # The documented §6 shape form: normalize casing explicitly.
        source = marked('assert probe.path.name.lower() == "tsp.exe"\n')
        assert violations_of(source) == []

    def test_upper_normalized_comparison_escapes(self):
        source = marked('assert probe.path.name.upper() == "TSP.EXE"\n')
        assert violations_of(source) == []

    def test_data_file_suffix_escapes(self):
        # Golden/asset filenames are synthetic-fixture anchors (§6); only
        # executable suffixes are machine-casing-sensitive.
        source = marked('assert vector.name == "pat-minimal.ts"\n')
        assert violations_of(source) == []

    def test_executable_name_in_path_construction_escapes(self):
        # Building a fixture path is not comparing on-disk casing.
        source = marked('script = bin_dir / "tsp.cmd"\n')
        assert violations_of(source) == []

    def test_executable_name_assignment_escapes(self):
        source = marked('FAKE_SUFFIX = ".cmd"\n')
        assert violations_of(source) == []

    def test_executable_name_in_dict_payload_escapes(self):
        # Report payload text is not an on-disk comparison.
        source = marked('evidence = {"command": ["tsanalyze.exe", "--json"]}\n')
        assert violations_of(source) == []

    def test_literal_to_literal_comparison_escapes(self):
        # Synthetic self-consistency (both sides frozen) cannot drift.
        source = marked('assert "tsp.exe" == "tsp.exe"\n')
        assert violations_of(source) == []

    def test_every_executable_suffix_is_flagged(self):
        for suffix in sorted(EXECUTABLE_SUFFIXES):
            name = f"tool{suffix}"
            source = marked(f'assert probe.path.name == "{name}"\n')
            assert rules_of(source) == ["env_executable_name_comparison"]


class TestWaiverMechanism:
    def test_same_line_env_ok_waives_version_pin(self):
        source = marked(
            f'assert probe.version == "{INCIDENT_VERSION}"  # env-ok: scripted fixture anchor\n'
        )
        assert violations_of(source) == []

    def test_adjacent_line_env_ok_waives_parenthesized_pin(self):
        source = marked(
            "assert (\n"
            f'    probe.version == "{INCIDENT_VERSION}"\n'
            "    # env-ok: scripted fixture anchor\n"
            ")\n"
        )
        assert violations_of(source) == []

    def test_waiver_on_unrelated_line_does_not_suppress(self):
        source = marked(
            "fallback = Path('x')  # env-ok: measured asset anchor\n"
            f'assert probe.version == "{INCIDENT_VERSION}"\n'
        )
        assert rules_of(source) == ["env_version_literal"]


class TestFindingShape:
    def test_findings_carry_filename_line_rule_snippet(self):
        source = marked(f'assert probe.version == "{INCIDENT_VERSION}"\n')
        finding = violations_of(source)[0]
        assert finding.filename == "<test>"
        assert finding.line == 3  # import, pytestmark, assert
        assert finding.rule == "env_version_literal"
        assert "3.40-4165" in finding.snippet

    def test_findings_sorted_by_line(self):
        source = marked(
            f'expected = Path("{py_escaped(INCIDENT_DRIVE_PATH)}")\n'
            f'assert probe.version == "{INCIDENT_VERSION}"\n'
        )
        assert lines_of(source) == [3, 4]
        assert rules_of(source) == ["env_drive_path_literal", "env_version_literal"]

    def test_unparsable_source_yields_no_findings(self):
        assert violations_of(marked("def broken(:\n")) == []

    def test_both_markers_can_yield_multiple_rules(self):
        source = marked(
            f'assert probe.version == "{INCIDENT_VERSION}"\n'
            f'assert str(probe.path) == "{py_escaped(INCIDENT_DRIVE_PATH)}"\n',
            marker="windows_only",
        )
        assert rules_of(source) == ["env_version_literal", "env_drive_path_literal"]
