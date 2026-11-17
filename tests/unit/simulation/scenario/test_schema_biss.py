"""Scenario ``biss`` section parse (SPEC-610 §2.1/§5, SPEC-205 §4 additive,
ticket #126 — schema.py biss 段归属裁定 §10-6).

The biss section is an optional top-level scenario-document section
declaring the construction-side BISS key (camelCase wire document, biss
keys per SPEC-610 §5)::

    "biss": {"mode": "1", "session_word": <12 hex>,
             "pid_scope": [int], "ca_pid": 8191}

Seam: :func:`parse_scenario_document` — the wire-validation boundary.
Errors follow the house error pattern: :class:`ScenarioSchemaInvalidError`
with ``$``-rooted, value-free details (errors are a read path,
REQ-SIM-205-003 — the offending key material never appears in the error
text).
"""

from __future__ import annotations

import pytest

from simulation.scenario.schema import (
    BissMode1Config,
    ScenarioSchemaInvalidError,
    parse_scenario_document,
)
from tests.unit.simulation.scenario._scenario_builders import raw_scenario

pytestmark = pytest.mark.unit

J96_SESSION_WORD = "A13DBC42908F"  # the J.96 §8 published example constant


def _with_biss(**overrides) -> dict:
    """A raw scenario whose ``biss`` section carries the given overrides.

    ``drop="ca_pid"`` removes that wire key (defaults exist only for
    ca_pid; mode/session_word/pid_scope are required).
    """
    document = raw_scenario()
    biss = {
        "mode": "1",
        "session_word": J96_SESSION_WORD,
        "pid_scope": [0x0100],
        "ca_pid": 8191,
    }
    drop = overrides.pop("drop", None)
    if drop:
        for key in drop if isinstance(drop, (list, tuple)) else (drop,):
            biss.pop(key, None)
    biss.update(overrides)
    document["biss"] = biss
    return document


class TestBissSectionAbsent:
    def test_absent_section_parses_to_none(self) -> None:
        parsed = parse_scenario_document(raw_scenario())
        assert parsed.biss is None


class TestBissSectionHappyPath:
    def test_valid_biss_section_parses_to_frozen_config(self) -> None:
        parsed = parse_scenario_document(_with_biss())
        assert parsed.biss == BissMode1Config(
            mode="1",
            session_word=J96_SESSION_WORD,
            pid_scope=(0x0100,),
            ca_pid=8191,
        )
        with pytest.raises(AttributeError):
            parsed.biss.mode = "2"  # frozen content (immutability contract)

    def test_ca_pid_optional_defaults_to_constant(self) -> None:
        parsed = parse_scenario_document(_with_biss(drop="ca_pid"))
        assert parsed.biss.ca_pid == 8191  # 0x1FFF (Tech 3292)

    def test_lowercase_session_word_accepted(self) -> None:
        parsed = parse_scenario_document(
            _with_biss(session_word=J96_SESSION_WORD.lower())
        )
        assert parsed.biss.session_word == J96_SESSION_WORD.lower()

    def test_multiple_pid_scope_entries(self) -> None:
        parsed = parse_scenario_document(
            _with_biss(pid_scope=[0x0100, 0x0101])
        )
        assert parsed.biss.pid_scope == (0x0100, 0x0101)


class TestBissSectionRejections:
    def test_unsupported_mode_rejected(self) -> None:
        """Unsupported biss modes are an explicit rejection (never a
        silent pass).  The Mode E face ("E") parses since #127 (SPEC-611
        — see test_schema_biss_mode_e.py); "2" and friends stay outside
        the scenario wire face."""
        with pytest.raises(ScenarioSchemaInvalidError) as excinfo:
            parse_scenario_document(_with_biss(mode="2"))
        assert "$.biss.mode" in excinfo.value.details[0]

    def test_session_word_wrong_length_rejected(self) -> None:
        with pytest.raises(ScenarioSchemaInvalidError) as excinfo:
            parse_scenario_document(_with_biss(session_word="A13DBC42908"))
        assert "$.biss.session_word" in excinfo.value.details[0]

    def test_session_word_non_hex_rejected(self) -> None:
        with pytest.raises(ScenarioSchemaInvalidError) as excinfo:
            parse_scenario_document(_with_biss(session_word="Z13DBC42908F"))
        assert "$.biss.session_word" in excinfo.value.details[0]

    def test_session_word_wrong_type_rejected(self) -> None:
        with pytest.raises(ScenarioSchemaInvalidError) as excinfo:
            parse_scenario_document(_with_biss(session_word=123456789012))
        assert "$.biss.session_word" in excinfo.value.details[0]

    def test_empty_pid_scope_rejected(self) -> None:
        with pytest.raises(ScenarioSchemaInvalidError) as excinfo:
            parse_scenario_document(_with_biss(pid_scope=[]))
        assert "$.biss.pid_scope" in excinfo.value.details[0]

    def test_pid_scope_out_of_range_rejected(self) -> None:
        with pytest.raises(ScenarioSchemaInvalidError) as excinfo:
            parse_scenario_document(_with_biss(pid_scope=[0x2000]))
        assert "$.biss.pid_scope" in excinfo.value.details[0]

    def test_pid_scope_non_int_rejected(self) -> None:
        with pytest.raises(ScenarioSchemaInvalidError) as excinfo:
            parse_scenario_document(_with_biss(pid_scope=["0x0100"]))
        assert "$.biss.pid_scope" in excinfo.value.details[0]

    def test_ca_pid_other_than_constant_rejected(self) -> None:
        """ca_pid is a constant-semantics field (0x1FFF, Tech 3292) — any
        other value is a schema violation, not a config choice."""
        with pytest.raises(ScenarioSchemaInvalidError) as excinfo:
            parse_scenario_document(_with_biss(ca_pid=100))
        assert "$.biss.ca_pid" in excinfo.value.details[0]

    def test_non_object_biss_section_rejected(self) -> None:
        document = raw_scenario()
        document["biss"] = "scramble-everything"
        with pytest.raises(ScenarioSchemaInvalidError) as excinfo:
            parse_scenario_document(document)
        assert "$.biss" in excinfo.value.details[0]

    def test_unknown_biss_key_rejected(self) -> None:
        with pytest.raises(ScenarioSchemaInvalidError) as excinfo:
            parse_scenario_document(
                _with_biss(encrypted_sw="0123456789ABCDEF")
            )
        assert any("encrypted_sw" in detail for detail in excinfo.value.details)

    def test_error_details_never_carry_key_material(self) -> None:
        """REQ-SIM-205-003: errors are value-free — the offending session
        word must not leak into the rejection details (key discipline,
        SPEC-610 §9)."""
        bad_word = "QQQQQQQQQQQQ"
        with pytest.raises(ScenarioSchemaInvalidError) as excinfo:
            parse_scenario_document(_with_biss(session_word=bad_word))
        assert bad_word.lower() not in " ".join(
            excinfo.value.details
        ).lower()
