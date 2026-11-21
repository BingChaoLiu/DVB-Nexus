"""Python dual form of the builtin rule set (SPEC-307 §7, ticket #55).

The builtin four rules exist in TWO forms — Python definitions (this
module) and JSON declarations (``builtin/*.json``) — and the loader
fails the startup when the two diverge (§7 load-time consistency check;
``load_builtin_rules`` proves it on every start). Keep every value here
byte-identical to its JSON counterpart; a rule-set change is a NEW
``rule_version`` (§7), never an in-place semantic edit.

Predicate parameters pin the ADR-0007 item 5 single-symptom signatures
of the four MVP fault types at the signal level (SPEC-307 §6: 具体谓词
参数随实现细化，信号语义以 ADR-0007 §5 为权威).

The Phase 2 four (ticket #130, SPEC-307 §Phase2 revision chapter) extend
the same one-rule-per-principle pairing to the encapsulation primitives
(#121): each rule's ``expected_evidence`` mirrors its primitive's
``expected_observations`` symbol set (the 互证), and the match consumes
the candidate event whose strict payload key set #129 froze. Mechanical
honesty (候选 ≠ 事实): the three Phase 2 evidence events carry no
diagnosis anchor triple (SPEC-306 §6), so those rules stay
loadable-but-unfired under the frozen engine until a Phase 2
evidence-anchor path lands — the declaration pins WHICH event and WHICH
locator keys constitute the candidate, never a verified fact.

The Phase 3 two (ticket #168, SPEC-307 §Phase3 revision chapter) extend
the same pairing to the state-layer primitives (#163): both consume the
tuner snapshot ``rf.state_observed`` (#164's NodeEvalResult-shape
projection) and mirror the primitives' ``expected_observations`` symbol
set {``rf.state_observed``, ``sec.state_observed``}. The same mechanical
honesty applies: the registered tuner snapshot carries no SPEC-306 §6
anchor state (exact-key shape, not the Phase 2 evidence family), so the
rules stay loadable-but-unfired under the frozen engine until a Phase 3
evidence-anchor path lands (the #130 → #138 precedent posture). Within
the frozen §4 op set ({eq, gt, lt, exists}) the declarable faces are the
constant observation axes (``state_evaluator``/``simulated`` — the
SPEC-303 §Phase3 恒定配对), the unlocked discriminator and the graded
BER face (the #161 frozen producer semantics put every fault-chain
tuner snapshot at ``severe``; the SPEC-307 §Phase3 "elevated/severe"
OR-face and the CauseRef-array / cross-event ``sec.state_observed``
faces are outside the finite predicate set — ticket #168 REPORT
deviation, no mechanism extension under the 零改 discipline).
"""

from __future__ import annotations

from domain.diagnosis.rules.model import (
    DiagnosticRule,
    FieldPredicate,
    MatchSpec,
    SuppressionSpec,
    WindowAggregate,
)

__all__ = ["python_builtin_rules"]


def python_builtin_rules() -> tuple[DiagnosticRule, ...]:
    """The four SPEC-307 §6 rules in the §5 output ordering."""
    return (
        DiagnosticRule(
            rule_id="DIA-PAT-MISSING",
            rule_version="1.0.0",
            code="DIAG_PAT_MISSING",
            priority=10,
            severity="error",
            confidence="high",
            title="PAT missing in window",
            summary_template=(
                "No PAT observed on PID {pid} (null substitution at packet"
                " {packet_index}); window artefact {artifact_id}"
            ),
            match=MatchSpec(
                event_type="ts.psi_section_observed",
                predicates=(
                    FieldPredicate(field="correlation.pid", op="eq", value=0),
                    FieldPredicate(field="payload.section", op="eq", value="PAT"),
                    FieldPredicate(field="payload.present", op="eq", value=False),
                ),
                group_by=("node_id", "pid"),
            ),
            suppression=SuppressionSpec(),
            suggested_actions=("Restore PAT emission on PID 0",),
            expected_evidence=("ts.psi_section_observed",),
        ),
        DiagnosticRule(
            rule_id="DIA-PMT-CRC-BAD",
            rule_version="1.0.0",
            code="DIAG_PMT_CRC_BAD",
            priority=20,
            severity="error",
            confidence="high",
            title="PMT CRC verification failed",
            summary_template=(
                "PMT CRC check failed (persistent symptom) at packet"
                " {packet_index}; window artefact {artifact_id}"
            ),
            match=MatchSpec(
                event_type="ts.psi_section_observed",
                predicates=(
                    FieldPredicate(field="payload.section", op="eq", value="PMT"),
                    FieldPredicate(field="payload.crc_valid", op="eq", value=False),
                ),
                group_by=("node_id", "pid"),
                window=WindowAggregate(
                    aggregation="count", scope="run", min_count=2
                ),
            ),
            suppression=SuppressionSpec(),
            suggested_actions=("Re-mux the PMT with correct CRC",),
            expected_evidence=("ts.psi_section_observed",),
        ),
        DiagnosticRule(
            rule_id="DIA-CC-DISCONTINUITY",
            rule_version="1.0.0",
            code="DIAG_CC_DISCONTINUITY",
            priority=30,
            severity="warning",
            confidence="high",
            title="Continuity counter discontinuity",
            summary_template=(
                "CC discontinuity on PID {pid}: expected {expected_cc},"
                " got {actual_cc} at packet {packet_index} (relative"
                " offset persists); artefact {artifact_id}"
            ),
            match=MatchSpec(
                event_type="ts.continuity_error",
                predicates=(
                    FieldPredicate(field="payload.expected_cc", op="exists"),
                    FieldPredicate(field="payload.actual_cc", op="exists"),
                ),
                group_by=("node_id", "pid"),
            ),
            suppression=SuppressionSpec(),
            suggested_actions=(
                "Inspect the upstream multiplex for packet loss",
            ),
            expected_evidence=("ts.continuity_error",),
        ),
        DiagnosticRule(
            rule_id="DIA-PMT-PID-MISMATCH",
            rule_version="1.0.0",
            code="DIAG_PMT_PID_MISMATCH",
            priority=40,
            severity="error",
            confidence="medium",
            title="PAT points at a PMT PID with no PMT",
            summary_template=(
                "PAT declares program_map_pid {actual_program_map_pid} but"
                " the PMT sits on {expected_program_map_pid} (orphan PMT)"
                " at packet {packet_index}; artefact {artifact_id}"
            ),
            match=MatchSpec(
                event_type="ts.psi_section_observed",
                predicates=(
                    FieldPredicate(field="payload.section", op="eq", value="PAT"),
                    FieldPredicate(
                        field="payload.expected_program_map_pid", op="exists"
                    ),
                    FieldPredicate(
                        field="payload.actual_program_map_pid", op="exists"
                    ),
                ),
                group_by=("node_id", "pid"),
            ),
            suppression=SuppressionSpec(),
            suggested_actions=("Correct the PAT program_map_pid entry",),
            expected_evidence=("ts.psi_section_observed",),
        ),
        # --- Phase 2 four (ticket #130, SPEC-307 §Phase2) ------------------
        # 1. T2MI_PLP_MISMATCH → 「PLP 映射错位」: the B1 candidate event +
        #    the Inner TS business-absence locator keys (SPEC-602 §5).
        DiagnosticRule(
            rule_id="DIA-T2MI-PLP-MISMATCH",
            rule_version="1.0.0",
            code="DIAG_T2MI_PLP_MISMATCH",
            priority=50,
            severity="error",
            confidence="medium",
            title=(
                "PLP mapping mismatch leaves the demux-expected PLP"
                " without business"
            ),
            summary_template=(
                "Demux expects PLP {expected_plp}, stream carries PLP"
                " {actual_plp}; the filtered Inner TS carries no business"
            ),
            match=MatchSpec(
                event_type="t2mi.plp_mismatch",
                predicates=(
                    FieldPredicate(field="payload.expected_plp", op="exists"),
                    FieldPredicate(field="payload.actual_plp", op="exists"),
                    FieldPredicate(
                        field="payload.business_absent_evidence", op="exists"
                    ),
                ),
                group_by=("node_id",),
            ),
            suppression=SuppressionSpec(),
            suggested_actions=(
                "Align the encapsulator PLP assignment with the demux"
                " expected PLP",
            ),
            expected_evidence=("t2mi.plp_mismatch",),
        ),
        # 2. BBHEADER_SYNC_FAULT → 「BBHEADER 同步错位」: the B2 recovery
        #    evidence + the first-failed-frame locator (SPEC-601 §5; SYNCD
        #    is the bit distance of the first UP, EN 302 755 §5.1.7).
        DiagnosticRule(
            rule_id="DIA-BBHEADER-SYNC-FAULT",
            rule_version="1.0.0",
            code="DIAG_BBHEADER_SYNC_FAULT",
            priority=60,
            severity="error",
            confidence="medium",
            title="BBFRAME header recovery failed on the received frames",
            summary_template=(
                "BBFRAME header recovery failed on {failure_count} frame(s);"
                " first failed frame index {first_failed_frame_index}"
            ),
            match=MatchSpec(
                event_type="bbframe.recovery_failed",
                predicates=(
                    FieldPredicate(field="payload.failure_count", op="gt", value=0),
                    FieldPredicate(
                        field="payload.first_failed_frame_index", op="exists"
                    ),
                ),
                group_by=("node_id",),
            ),
            suppression=SuppressionSpec(),
            suggested_actions=(
                "Inspect the BBHEADER of the first failed frame (EN 302 755"
                " §5.1.7)",
            ),
            expected_evidence=("bbframe.recovery_failed",),
        ),
        # 3. BISS_KEY_MISMATCH → 「BISS 密钥错位」: the descramble
        #    structural self-check candidate + the key-fingerprint
        #    reference interlock (SPEC-610 §5; 解扰失败 ≠ 码流损坏 —
        #    the self_check_kind + fingerprint REF distinguish a key
        #    mismatch from stream corruption; fingerprints only, never
        #    key material).
        DiagnosticRule(
            rule_id="DIA-BISS-KEY-MISMATCH",
            rule_version="1.0.0",
            code="DIAG_BISS_KEY_MISMATCH",
            priority=70,
            severity="error",
            confidence="medium",
            title="BISS descramble structural self-check failed",
            summary_template=(
                "Descramble self-check {self_check_kind} failed on the"
                " scoped PIDs (key fingerprint ref {key_fingerprint_ref});"
                " a key-mismatch candidate, not by itself a corrupted"
                " stream"
            ),
            match=MatchSpec(
                event_type="biss.descramble_failed",
                predicates=(
                    FieldPredicate(field="payload.pid_scope", op="exists"),
                    FieldPredicate(
                        field="payload.failed_indices_sample", op="exists"
                    ),
                    FieldPredicate(field="payload.self_check_kind", op="exists"),
                    FieldPredicate(
                        field="payload.key_fingerprint_ref", op="exists"
                    ),
                    FieldPredicate(field="payload.mode", op="exists"),
                ),
                group_by=("node_id",),
            ),
            suppression=SuppressionSpec(),
            suggested_actions=(
                "Verify the session word derivation chain against the"
                " declared key fingerprint reference",
            ),
            expected_evidence=("biss.descramble_failed",),
        ),
        # 4. PMT_PID_DRIFT → 「PMT/Demux 过滤不同步」: the ts.* observation
        #    face per ruling §10-16-③ (ts.pmt_pid_drift is NOT a
        #    registered envelope event; SPEC-303 §Phase2). The match pins
        #    the PSI version-contrast contradiction in the house style —
        #    the declared expectation rides ONLY on a contradiction (the
        #    expected_program_map_pid precedent) — so the rule fires on a
        #    version drift, never on a clean PMT face. Honest LOW
        #    confidence: the MVP analyzer does not emit the contradiction
        #    fields yet (registered-but-inert posture).
        DiagnosticRule(
            rule_id="DIA-PMT-PID-DRIFT",
            rule_version="1.0.0",
            code="DIAG_PMT_PID_DRIFT",
            priority=80,
            severity="error",
            confidence="low",
            title="PMT version drifts from the declared expectation",
            summary_template=(
                "PMT version {pmt_version} observed against declared"
                " expectation {expected_pmt_version}; the demux declared"
                " PID map is out of sync"
            ),
            match=MatchSpec(
                event_type="ts.psi_section_observed",
                predicates=(
                    FieldPredicate(field="payload.section", op="eq", value="PMT"),
                    FieldPredicate(field="payload.pmt_version", op="exists"),
                    FieldPredicate(
                        field="payload.expected_pmt_version", op="exists"
                    ),
                ),
                group_by=("node_id", "pid"),
            ),
            suppression=SuppressionSpec(),
            suggested_actions=(
                "Re-align the demux declared-PID map with the drifted PMT"
                " version",
            ),
            expected_evidence=("ts.psi_section_observed", "fault.applied"),
        ),
        # --- Phase 3 two (ticket #168, SPEC-307 §Phase3) --------------------
        # Both consume the tuner snapshot rf.state_observed (#164's
        # NodeEvalResult-shape projection) and interlock with the #163
        # state-layer primitives' expected_observations symbol set
        # {sec.state_observed, rf.state_observed}.  The predicate set pins
        # exactly the registered tuner snapshot keys (the interlock
        # posture): the eq faces are the scenario-invariant facts — the
        # SPEC-303 §Phase3 恒定配对 and the graded/unlocked discriminators
        # — the remaining keys ride the exists key-face pin.  The
        # CauseRef-array face (causes[*].node_id → lnb / conflict peer)
        # and the cross-event sec.state_observed faces (tone 双字段 /
        # ub_assignments 表) are outside the frozen finite predicate set:
        # they ride the expected_evidence 互证 and the #171 判据互锁, not
        # the match predicates (ticket #168 REPORT deviation).
        # 1. TONE_RESIDUE → 「LNB tone 残留 / 供电异常」: the tuner grades
        #    severe against the commanded tone plan (the #161 frozen
        #    producer semantics: any anomaly field ⇒ severe; the elevated
        #    arm of the SPEC-307 §Phase3 "elevated/severe" OR-face is the
        #    no-fault protection-band grade — unreachable for the chain,
        #    and a string-valued OR is inexpressible in the frozen op
        #    set).  失锁与错锁 both qualify (SPEC-620 §7: 失锁或错锁) —
        #    lock_state stays an exists key-face pin.
        DiagnosticRule(
            rule_id="DIA-TONE-RESIDUE-SUSPECT",
            rule_version="1.0.0",
            code="DIAG_TONE_RESIDUE_SUSPECT",
            priority=90,
            severity="error",
            confidence="medium",
            title="LNB tone residue / power anomaly suspected from the tuner state",
            summary_template=(
                "Tuner {node_id} graded ber_state={ber_state} against the"
                " commanded tone plan; the cause chain references the"
                " feeder — suspected LNB tone residue / power-supply"
                " anomaly"
            ),
            match=MatchSpec(
                event_type="rf.state_observed",
                predicates=(
                    FieldPredicate(field="payload.node_id", op="exists"),
                    FieldPredicate(field="payload.health", op="exists"),
                    FieldPredicate(field="payload.causes", op="exists"),
                    FieldPredicate(
                        field="payload.source", op="eq", value="state_evaluator"
                    ),
                    FieldPredicate(
                        field="payload.confidence", op="eq", value="simulated"
                    ),
                    FieldPredicate(field="payload.lock_state", op="exists"),
                    FieldPredicate(field="payload.if_frequency_khz", op="exists"),
                    FieldPredicate(
                        field="payload.ber_state", op="eq", value="severe"
                    ),
                    FieldPredicate(
                        field="payload.locked_transponder_id", op="exists"
                    ),
                    FieldPredicate(field="payload.stale", op="exists"),
                ),
                group_by=("node_id",),
            ),
            suppression=SuppressionSpec(),
            suggested_actions=(
                "Check the cause-referenced lnb tone_commanded/tone_actual"
                " pair and its supply path (tone residue / power anomaly)",
            ),
            expected_evidence=("rf.state_observed", "sec.state_observed"),
        ),
        # 2. UB_SLOT_CONFLICT → 「UB 槽位冲突 / SCR 堆叠互扰」: the
        #    conflict-claimed tuner sits unlocked (the SPEC-307 §Phase3
        #    discriminator) on a graded face — the runtime conflict branch
        #    is anomaly ⇒ severe (#161), so a plain ungraded unlocked face
        #    (e.g. the polarization-mismatch unlock, SPEC-620 §8) is NOT a
        #    conflict candidate (缺失 ≠ 候选).
        DiagnosticRule(
            rule_id="DIA-UB-CONFLICT-SUSPECT",
            rule_version="1.0.0",
            code="DIAG_UB_CONFLICT_SUSPECT",
            priority=100,
            severity="error",
            confidence="high",
            title="UB slot conflict / SCR stacking interference suspected on the tuner",
            summary_template=(
                "Tuner {node_id} unlocked on a {ber_state}-graded face with"
                " conflict references in the cause chain — suspected UB"
                " slot conflict / SCR stacking interference"
            ),
            match=MatchSpec(
                event_type="rf.state_observed",
                predicates=(
                    FieldPredicate(field="payload.node_id", op="exists"),
                    FieldPredicate(field="payload.health", op="exists"),
                    FieldPredicate(field="payload.causes", op="exists"),
                    FieldPredicate(
                        field="payload.source", op="eq", value="state_evaluator"
                    ),
                    FieldPredicate(
                        field="payload.confidence", op="eq", value="simulated"
                    ),
                    FieldPredicate(
                        field="payload.lock_state", op="eq", value="unlocked"
                    ),
                    FieldPredicate(field="payload.if_frequency_khz", op="exists"),
                    FieldPredicate(
                        field="payload.ber_state", op="eq", value="severe"
                    ),
                    FieldPredicate(
                        field="payload.locked_transponder_id", op="exists"
                    ),
                    FieldPredicate(field="payload.stale", op="exists"),
                ),
                group_by=("node_id",),
            ),
            suppression=SuppressionSpec(),
            suggested_actions=(
                "Re-assign the tuner ub_slot claim against the SCR"
                " ub_assignments table (conflict peer in the cause chain)",
            ),
            expected_evidence=("rf.state_observed", "sec.state_observed"),
        ),
    )
