"""The state-snapshot anchor state of the SPEC-306 §6 evidence gate
(ticket #172, ruling A21 — the #138 点亮 path applied to Phase 3).

#168 delivered the two Phase 3 rules loadable-but-unfired: the anchor
gate had no state for the state-snapshot family, and the production feed
(``application/diagnosis/service.py``) filtered ``rf.*``/``sec.*`` out.
#172 lights the face with ZERO rule-declaration changes (the #130 → #138
precedent form):

- the APPLICATION stamps every state-snapshot record's
  ``evidence_artifact_id`` with the snapshot event's own ``event_id``
  (the journal row IS the evidence terminus — a SIM_STATE run lands no
  TS artifact; the row is resolvable through the journal events face via
  the candidate's ``observation_refs`` journal_seq);
- the gate's THIRD state consumes the stamp plus the namespace-mapped
  locator — the payload's state-discriminator fields verbatim, so the
  CauseRef conflict pair / lnb reference rides the candidate evidence
  (无对应定位字段不虚填);
- an UNSTAMPED state-snapshot record still produces no candidate — the
  #168 honesty face (``test_dia_rules_phase3_candidates.py::
  _evaluator_stays_candidate_free``) stays byte-identical in meaning:
  no anchor, no candidate (the tests-layer record constructor does not
  stamp; only the production feed does).

Pure logic: in-memory records only — no I/O, no wall clock.
"""

import pytest

from domain.diagnosis.rules import load_builtin_rules
from domain.diagnosis.rules.model import DiagnosticRule
from domain.observation.registry import (
    RF_TUNER_SNAPSHOT_KEYS,
    validate_payload,
)

pytestmark = pytest.mark.unit

RULE_UB = "DIA-UB-CONFLICT-SUSPECT"
RULE_TON = "DIA-TONE-RESIDUE-SUSPECT"
RF_STATE = "rf.state_observed"

#: The real faulted UB-conflict tuner snapshot (the #168 integration
#: suite's measured face): tuner-b unlocked + severe, the conflict peer
#: in the CauseRef chain. Registry-exact key set.
UB_CONFLICT_SNAPSHOT = {
    "node_id": "tuner-b",
    "health": "error",
    "causes": [{"node_id": "tuner-a", "port_id": None}],
    "source": "state_evaluator",
    "confidence": "simulated",
    "lock_state": "unlocked",
    "if_frequency_khz": 1210000,
    "ber_state": "severe",
    "locked_transponder_id": None,
    "stale": True,
}


def _rule(rule_id: str) -> DiagnosticRule:
    return next(rule for rule in load_builtin_rules() if rule.rule_id == rule_id)


def _record(seq: int, payload: dict, *, stamped: bool) -> "object":
    from domain.diagnosis.engine import ObservationRecord

    return ObservationRecord(
        journal_seq=seq,
        event_type=RF_STATE,
        event_id=f"obs-rf-{seq}",
        payload=dict(payload),
        node_id=str(payload["node_id"]),
        evidence_artifact_id=f"obs-rf-{seq}" if stamped else None,
    )


class TestStateAnchorThirdState:
    """The gate's third state: stamped state snapshot → candidate with a
    locator-form evidence ref; unstamped → no candidate (honest face)."""

    def test_faulted_snapshot_payload_is_registry_exact(self):
        # The anchor face is asserted on a REAL producer shape: the
        # snapshot must satisfy the registered payload schema before any
        # gate behaviour is pinned on it.
        validate_payload(RF_STATE, UB_CONFLICT_SNAPSHOT)
        assert set(UB_CONFLICT_SNAPSHOT) == set(RF_TUNER_SNAPSHOT_KEYS)

    def test_stamped_state_snapshot_fires_the_rule(self):
        hits = _rule(RULE_UB).matches([_record(1, UB_CONFLICT_SNAPSHOT, stamped=True)])
        assert len(hits) == 1
        hit = hits[0]
        assert hit.event_type == RF_STATE
        assert hit.journal_seq == 1
        assert hit.affected_node_ids == ["tuner-b"]

    def test_unstamped_state_snapshot_stays_candidate_free(self):
        # The #168 honesty face, now pinned at the unit layer too: the
        # tests-layer constructor does not stamp, so the rule must not
        # fire (no anchor, no candidate — never a bypassed gate).
        assert _rule(RULE_UB).matches(
            [_record(1, UB_CONFLICT_SNAPSHOT, stamped=False)]
        ) == ()

    def test_evidence_is_locator_form_with_the_state_face(self):
        hits = _rule(RULE_UB).matches([_record(1, UB_CONFLICT_SNAPSHOT, stamped=True)])
        evidence = hits[0].evidence
        # The locator form (no fabricated pid/packet_index — the state
        # snapshot carries neither): the artifact anchor is the stamped
        # journal row identity, the locator is the state-discriminator
        # face verbatim (causes included — the conflict pair rides the
        # candidate evidence, the #168 deviation-3 consumption).
        assert evidence.pid is None
        assert evidence.packet_index is None
        assert evidence.artifact_id == "obs-rf-1"
        assert evidence.locator == {
            "node_id": "tuner-b",
            "lock_state": "unlocked",
            "ber_state": "severe",
            "locked_transponder_id": None,
            "causes": [{"node_id": "tuner-a", "port_id": None}],
        }

    def test_tone_rule_reads_the_same_anchor_form(self):
        # Both Phase 3 rules share the third state (declaration-identical
        # mechanism — the overlap faces are the rules' predicate business,
        # not the gate's).
        hits = _rule(RULE_TON).matches([_record(1, UB_CONFLICT_SNAPSHOT, stamped=True)])
        assert len(hits) == 1
        assert hits[0].evidence.artifact_id == "obs-rf-1"

    def test_baseline_snapshot_with_stamp_still_produces_no_hit(self):
        # The stamp admits the record to the gate; the RULE's predicates
        # still decide (缺失 ≠ 候选): a clean locked-normal snapshot with
        # a stamp yields no hit for either rule.
        baseline = dict(UB_CONFLICT_SNAPSHOT)
        baseline.update(
            {
                "node_id": "tuner-b",
                "health": "ok",
                "causes": [],
                "lock_state": "locked",
                "ber_state": "normal",
                "locked_transponder_id": "ub:1:1420",
                "stale": False,
            }
        )
        validate_payload(RF_STATE, baseline)
        assert _rule(RULE_UB).matches([_record(1, baseline, stamped=True)]) == ()
        assert _rule(RULE_TON).matches([_record(1, baseline, stamped=True)]) == ()
