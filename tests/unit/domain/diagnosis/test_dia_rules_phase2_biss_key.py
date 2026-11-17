"""DIA-BISS-KEY-MISMATCH builtin-rule declaration tests (ticket #130,
SPEC-307 §Phase2 candidate 3 — 「BISS 密钥错位」).

The rule consumes the descramble-failure candidate event
``biss.descramble_failed`` (SPEC-610 §5; payload key set is the
#126/#127 producer contract frozen by #129's strict registry
validation; payloads carry key FINGERPRINT references only — key
material never enters a payload) and mirrors the ``BISS_KEY_MISMATCH``
primitive's ``expected_observations`` — the ADR-0007 item 5 互证.

Mechanical honesty (候选 ≠ 事实 discipline, asserted not hidden): the
registered ``biss.descramble_failed`` key set carries no diagnosis
anchor triple (SPEC-306 §6), so the rule stays loadable but unfired
under the frozen engine until a Phase 2 evidence-anchor path lands (the
ruling follow-up recorded on #130). The declaration keeps the ADR-0011
§4 honesty visible: a descramble structural self-check failure is a KEY
MISMATCH candidate, not stream-corruption evidence (解扰失败 ≠ 码流损坏).

Pure logic: in-memory records only — no I/O, no wall clock.
"""

import pytest

from domain.diagnosis.rules import load_builtin_rules
from domain.diagnosis.rules.model import DiagnosticRule
from domain.observation.registry import BISS_EVENT_TYPES, validate_payload
from faults.definition import FaultActivation, FaultDefinition
from faults.registry import (
    FAULT_TYPE_BISS_KEY_MISMATCH,
    LAYER_BY_FAULT_TYPE,
    validate_fault_definition,
)

from tests._support.diagnosis_fixtures import (
    FIXTURE_FAULT_TYPES,
    fault_observation_program,
)

RULE_ID = "DIA-BISS-KEY-MISMATCH"

#: The registered ``biss.descramble_failed`` payload shape (the #126
#: producer contract: scoped PIDs + the bounded failure sample + the
#: self-check kind + the key fingerprint REFERENCE + the mode). The
#: fingerprint is a hash-prefix reference, never key material
#: (SPEC-610 §9). Integration proves the REAL emitted payload.
DESCRAMBLE_FAILED_PAYLOAD = {
    "pid_scope": [256, 257],
    "failed_indices_sample": [3, 17],
    "self_check_kind": "ts_packet_188",
    "key_fingerprint_ref": "a" * 64,
    "mode": "1",
}


def _rule() -> DiagnosticRule:
    return next(rule for rule in load_builtin_rules() if rule.rule_id == RULE_ID)


def _primitive() -> FaultDefinition:
    """A real Mode 1 BISS_KEY_MISMATCH FaultDefinition interlocked with
    the rule (session_start activation per SPEC-204 §Phase2)."""
    return FaultDefinition(
        fault_id="fd000000-0000-4000-8000-00000000f008",
        fault_type=FAULT_TYPE_BISS_KEY_MISMATCH,
        target_id="scrambler-0",
        parameters={"wrong_session_word": "A13DBC42908F", "pid_scope": [256]},
        activation=FaultActivation(kind="session_start", packet_index=None),
        expected_observations=_rule().expected_evidence,
        layer=LAYER_BY_FAULT_TYPE[FAULT_TYPE_BISS_KEY_MISMATCH],
    )


class TestDeclarationIdentity:
    """Static SPEC-307 §3 declaration values of the Phase 2 candidate."""

    def test_rule_is_registered_by_the_production_loader(self):
        assert _rule() is not None

    def test_static_declaration_values(self):
        rule = _rule()
        assert rule.code == "DIAG_BISS_KEY_MISMATCH"
        assert rule.rule_version == "1.0.0"
        assert rule.priority == 70
        assert rule.severity.value == "error"
        # Pipeline candidate face (候选 ≠ 事实) — not an L1-confirmed
        # artifact observation.
        assert rule.confidence.value == "medium"
        assert rule.enabled is True

    def test_suppression_is_the_mvp_fixed_declaration(self):
        rule = _rule()
        assert rule.suppression.key == ("code", "node_id")
        assert rule.suppression.window == "per_run"


class TestPrimitiveInterlock:
    """expected_evidence ↔ the primitive's expected_observations,
    validated by the genuine faults registry."""

    def test_expected_evidence_names_the_descramble_candidate_event(self):
        assert _rule().expected_evidence == ("biss.descramble_failed",)
        assert "biss.descramble_failed" in BISS_EVENT_TYPES

    def test_fault_definition_interlocks_with_the_rule(self):
        fault = _primitive()
        assert fault.expected_observations == _rule().expected_evidence
        assert fault.fault_type == FAULT_TYPE_BISS_KEY_MISMATCH
        assert validate_fault_definition(fault) == ()

    def test_declared_layer_interlocks_with_the_registry(self):
        assert LAYER_BY_FAULT_TYPE[FAULT_TYPE_BISS_KEY_MISMATCH] == "BISS"


class TestMatchShape:
    """The match pins the descramble candidate and its key-fingerprint
    interlock keys (SPEC-307 §Phase2: 证据 = biss.descramble_failed +
    密钥指纹互链 — the distinction between a descramble failure and a
    corrupted stream lives in the self_check_kind + fingerprint
    reference, never in a stream verdict)."""

    def test_match_consumes_the_registered_event(self):
        assert _rule().match.event_type == "biss.descramble_failed"

    def test_predicates_pin_exactly_the_registered_payload_keys(self):
        rule = _rule()
        predicate_fields = {
            predicate.field for predicate in rule.match.predicates
        }
        payload = dict(DESCRAMBLE_FAILED_PAYLOAD)
        validate_payload(rule.match.event_type, payload)
        assert predicate_fields == {
            f"payload.{key}" for key in payload
        }

    def test_fingerprint_interlock_is_a_reference_predicate(self):
        """The 密钥指纹互链 predicate addresses the fingerprint
        REFERENCE (a hash chain link) — the rule never sees or matches
        key material."""
        holds = {
            predicate.field for predicate in _rule().match.predicates
        }
        assert "payload.key_fingerprint_ref" in holds
        assert "payload.key_fingerprint" not in holds

    def test_grouping_and_window_shape(self):
        match = _rule().match
        assert match.group_by == ("node_id",)
        assert match.window is None


class TestCandidateNotFactDiscipline:
    """The anchor-gate honesty and the single-attributable-symptom
    discipline."""

    def test_registry_conformant_record_without_anchor_yields_no_hit(self):
        """SPEC-306 §6: no anchor triple, no candidate — the honest
        inert-today posture under the frozen engine."""
        from domain.diagnosis.engine import ObservationRecord

        record = ObservationRecord(
            journal_seq=1,
            event_type="biss.descramble_failed",
            event_id="obs-biss-descramble-1",
            payload=dict(DESCRAMBLE_FAILED_PAYLOAD),
            node_id="demux-0",
        )
        assert _rule().matches([record]) == ()

    def test_mvp_fault_programs_do_not_trigger_the_rule(self):
        others = tuple(
            record
            for fault_type in FIXTURE_FAULT_TYPES
            for record in fault_observation_program(fault_type)
        )
        assert _rule().matches(others) == ()

    def test_summary_template_places_no_phantom_keys(self):
        from string import Formatter

        rule = _rule()
        placeholders = {
            field_name
            for _, field_name, _, _ in Formatter().parse(
                rule.summary_template
            )
            if field_name is not None
        }
        assert placeholders <= set(DESCRAMBLE_FAILED_PAYLOAD)
