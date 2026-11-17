"""Scenario ``biss`` section, Mode E face (SPEC-611 §5/§8, ticket #127).

Seam: :func:`parse_scenario_document`'s ``mode: "E"`` dispatch — the
``encrypted_sw`` / ``injected_id`` wire keys land in a frozen
:class:`BissModeEConfig`; constant-semantics fields (``ca_pid`` /
``ca_system_id``) reject other values; errors stay value-free (the ESW /
Injected ID bodies never leak into rejection details — key discipline,
SPEC-610 §9 inherited).

The 32-hex Injected ID constant comes from the deterministic generator
(sanctioned source — 32-hex literals are a data-rule violation); the ESW
(16 hex) is under the literal threshold.
"""

from __future__ import annotations

import pytest

from simulation.scenario.schema import (
    BissModeEConfig,
    ScenarioSchemaInvalidError,
    parse_scenario_document,
)
from tests._support.deterministic import seeded_bytes
from tests.unit.simulation.scenario._scenario_builders import raw_scenario

pytestmark = pytest.mark.unit

ENCRYPTED_SW = "0123456789ABCDEF"
INJECTED_ID = seeded_bytes(0x5CE7A, 16).hex().upper()


def _with_biss_mode_e(**overrides) -> dict:
    document = raw_scenario()
    biss = {
        "mode": "E",
        "encrypted_sw": ENCRYPTED_SW,
        "injected_id": INJECTED_ID,
        "pid_scope": [0x0100],
    }
    drop = overrides.pop("drop", None)
    if drop:
        for key in drop if isinstance(drop, (list, tuple)) else (drop,):
            biss.pop(key, None)
    biss.update(overrides)
    document["biss"] = biss
    return document


class TestBissModeEHappyPath:
    def test_valid_mode_e_section_parses_to_frozen_config(self) -> None:
        parsed = parse_scenario_document(_with_biss_mode_e())
        assert parsed.biss == BissModeEConfig(
            mode="E",
            encrypted_sw=ENCRYPTED_SW,
            injected_id=INJECTED_ID,
            pid_scope=(0x0100,),
            ca_pid=8191,
            ca_system_id=9730,
        )
        with pytest.raises(AttributeError):
            parsed.biss.mode = "1"  # frozen content (immutability contract)

    def test_constant_semantics_fields_default_when_absent(self) -> None:
        parsed = parse_scenario_document(
            _with_biss_mode_e(drop=("ca_pid", "ca_system_id"))
        )
        assert parsed.biss.ca_pid == 8191  # 0x1FFF (Tech 3292)
        assert parsed.biss.ca_system_id == 9730  # 0x2602 (BISS2, SPEC-611)

    def test_lowercase_key_material_accepted_verbatim(self) -> None:
        parsed = parse_scenario_document(
            _with_biss_mode_e(
                encrypted_sw=ENCRYPTED_SW.lower(),
                injected_id=INJECTED_ID.lower(),
            )
        )
        assert parsed.biss.encrypted_sw == ENCRYPTED_SW.lower()
        assert parsed.biss.injected_id == INJECTED_ID.lower()


class TestBissModeERejections:
    def test_encrypted_sw_wrong_length_rejected(self) -> None:
        with pytest.raises(ScenarioSchemaInvalidError) as excinfo:
            parse_scenario_document(
                _with_biss_mode_e(encrypted_sw="0123456789ABCDE")
            )
        assert "$.biss.encrypted_sw" in excinfo.value.details[0]

    def test_encrypted_sw_non_hex_rejected(self) -> None:
        with pytest.raises(ScenarioSchemaInvalidError) as excinfo:
            parse_scenario_document(
                _with_biss_mode_e(encrypted_sw="Z123456789ABCDEF")
            )
        assert "$.biss.encrypted_sw" in excinfo.value.details[0]

    def test_injected_id_wrong_length_rejected(self) -> None:
        with pytest.raises(ScenarioSchemaInvalidError) as excinfo:
            parse_scenario_document(
                _with_biss_mode_e(injected_id=INJECTED_ID[:-1])
            )
        assert "$.biss.injected_id" in excinfo.value.details[0]

    def test_injected_id_non_hex_rejected(self) -> None:
        with pytest.raises(ScenarioSchemaInvalidError) as excinfo:
            parse_scenario_document(
                _with_biss_mode_e(injected_id="Z" + INJECTED_ID[1:])
            )
        assert "$.biss.injected_id" in excinfo.value.details[0]

    def test_ca_pid_other_than_constant_rejected(self) -> None:
        with pytest.raises(ScenarioSchemaInvalidError) as excinfo:
            parse_scenario_document(_with_biss_mode_e(ca_pid=100))
        assert "$.biss.ca_pid" in excinfo.value.details[0]

    def test_ca_system_id_other_than_constant_rejected(self) -> None:
        """``ca_system_id`` is constant-semantics (0x2602, BISS2 — the
        Mode 1 face's 0x2600 is a different mode's constant)."""
        with pytest.raises(ScenarioSchemaInvalidError) as excinfo:
            parse_scenario_document(_with_biss_mode_e(ca_system_id=0x2600))
        assert "$.biss.ca_system_id" in excinfo.value.details[0]

    def test_mode_1_key_rejected_on_the_mode_e_face(self) -> None:
        with pytest.raises(ScenarioSchemaInvalidError) as excinfo:
            parse_scenario_document(
                _with_biss_mode_e(session_word="A13DBC42908F")
            )
        assert any(
            "session_word" in detail for detail in excinfo.value.details
        )

    def test_mode_e_keys_rejected_on_the_mode_1_face(self) -> None:
        """Mode discipline stays per-face: the encrypted_sw key under
        ``mode: "1"`` is an unknown key (SPEC-610 §5 face)."""
        document = raw_scenario()
        document["biss"] = {
            "mode": "1",
            "session_word": "A13DBC42908F",
            "pid_scope": [0x0100],
            "encrypted_sw": ENCRYPTED_SW,
        }
        with pytest.raises(ScenarioSchemaInvalidError) as excinfo:
            parse_scenario_document(document)
        assert any(
            "encrypted_sw" in detail for detail in excinfo.value.details
        )

    def test_empty_pid_scope_rejected(self) -> None:
        with pytest.raises(ScenarioSchemaInvalidError) as excinfo:
            parse_scenario_document(_with_biss_mode_e(pid_scope=[]))
        assert "$.biss.pid_scope" in excinfo.value.details[0]

    def test_error_details_never_carry_key_material(self) -> None:
        """REQ-SIM-205-003 + key discipline: the offending ESW / Injected
        ID bodies must not leak into the rejection details."""
        with pytest.raises(ScenarioSchemaInvalidError) as excinfo:
            parse_scenario_document(
                _with_biss_mode_e(
                    encrypted_sw="QQQQQQQQQQQQQQQQ",
                    injected_id="Z" + INJECTED_ID[1:],
                )
            )
        blob = " ".join(excinfo.value.details).lower()
        assert ENCRYPTED_SW.lower() not in blob
        assert INJECTED_ID.lower() not in blob

    def test_wire_mapping_round_trips_verbatim_through_raw(self) -> None:
        parsed = parse_scenario_document(_with_biss_mode_e())
        assert parsed.raw["biss"]["encrypted_sw"] == ENCRYPTED_SW
        assert parsed.raw["biss"]["injected_id"] == INJECTED_ID
        assert parsed.content_hash.startswith("sha256:") or len(
            parsed.content_hash
        ) == 64


class TestKeyBodyReprSuppression:
    """The ESW / Injected ID bodies never leak through ``repr()``
    (SPEC-611 §5 key discipline — M6 code-review fix round; mirrors the
    ``ScenarioDocument.raw`` ``repr=False`` precedent)."""

    @staticmethod
    def _assert_key_absent(repr_text: str, *secrets: str) -> None:
        """Case-insensitive containment plus a hex-token guard: the repr
        must not carry the key bodies in any case spelling."""
        lowered = repr_text.lower()
        for secret in secrets:
            assert secret.lower() not in lowered

    def test_config_repr_omits_key_bodies(self) -> None:
        config = BissModeEConfig(
            mode="E",
            encrypted_sw=ENCRYPTED_SW,
            injected_id=INJECTED_ID,
            pid_scope=(0x0100,),
        )
        self._assert_key_absent(repr(config), ENCRYPTED_SW, INJECTED_ID)

    def test_parsed_document_repr_omits_key_bodies(self) -> None:
        parsed = parse_scenario_document(_with_biss_mode_e())
        self._assert_key_absent(repr(parsed), ENCRYPTED_SW, INJECTED_ID)
        # The fields are still readable and equality-visible — repr
        # suppression hides the value from logs, nothing else.
        assert parsed.biss is not None
        assert parsed.biss.encrypted_sw == ENCRYPTED_SW
        assert parsed.biss.injected_id == INJECTED_ID
        assert parsed.biss == BissModeEConfig(
            mode="E",
            encrypted_sw=ENCRYPTED_SW,
            injected_id=INJECTED_ID,
            pid_scope=(0x0100,),
            ca_pid=8191,
            ca_system_id=9730,
        )
