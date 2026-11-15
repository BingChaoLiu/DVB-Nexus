"""Eight-step fault lab: CC_DISCONTINUITY (ticket #58, AC 1-3 for this
fault).

The relative-offset lab (golden: delta 3, landing slot 50): the
internal-parser analysis sees ONE continuity error at the shared-frame
landing slot — ``expected_cc=1 / actual_cc=4`` per the golden
expectations — the shift then persists contiguously (no further errors).
The warning-severity rule (SPEC-307 §6) raises the single attributable
candidate; the recovery run restarts its own CC schedule from the
recovery point and verifies SPEC-206 PASS over the CC criteria family.
"""

from __future__ import annotations

import pytest
from ts.packet import TSPacket

from tests.e2e._fault_lab import FaultLab, fault_plan_wire, load_scenario

pytestmark = pytest.mark.e2e

FAULT = "cc-discontinuity"
PAIRING_CODE = "DIAG_CC_DISCONTINUITY"
RULE_ID = "DIA-CC-DISCONTINUITY"
GOLDEN_LANDING = 50
GOLDEN_PID = 256
GOLDEN_EXPECTED_CC = 1
GOLDEN_ACTUAL_CC = 4
GOLDEN_DELTA = 3


def test_cc_discontinuity_eight_step_loop(golden_loader, tmp_path):
    baseline_vector = golden_loader.load(f"{FAULT}-baseline")
    faulted_vector = golden_loader.load(FAULT)
    raw, document = load_scenario(FAULT)

    with FaultLab(tmp_path / "fault-lab-cc.sqlite3") as lab:
        # --- Create ---------------------------------------------------------
        session_id = lab.create_session(raw)
        lab.start_session(session_id)

        # --- Generate ---------------------------------------------------------
        generate_run_id = lab.submit_run(session_id, [])
        generate_run = lab.await_run(session_id, generate_run_id)
        lab.drain()
        assert (
            lab.artifacts_of_kind(generate_run, "generated_ts")[0]["sha256"]
            == baseline_vector.sha256
        )

        # --- Inject -----------------------------------------------------------
        inject_run_id = lab.submit_run(session_id, fault_plan_wire(document))
        inject_run = lab.await_run(session_id, inject_run_id)
        lab.drain()
        faulted_artifacts = lab.artifacts_of_kind(inject_run, "faulted_ts")
        assert faulted_artifacts[0]["sha256"] == faulted_vector.sha256
        faulted_artifact_id = faulted_artifacts[0]["artifact_id"]
        assert lab.artifact_content(faulted_artifact_id) == faulted_vector.ts_bytes

        # --- Analyze ----------------------------------------------------------
        analysis = lab.analyze_artifact(session_id, inject_run_id, faulted_artifact_id)
        assert analysis.event_counts["ts.continuity_error"] == 1

        # --- Diagnose ---------------------------------------------------------
        report = lab.diagnose(session_id, inject_run_id)
        lab.drain()
        candidates = report["candidates"]
        assert len(candidates) == 1, [c["code"] for c in candidates]
        candidate = candidates[0]
        assert candidate["code"] == PAIRING_CODE
        assert candidate["rule_id"] == RULE_ID
        assert candidate["severity"] == "warning"  # SPEC-307 §6 table
        assert candidate["confidence"] == "high"
        assert candidate["evidence"]["artifact_id"] == faulted_artifact_id

        # --- Inspect: the landing slot carries the golden offset -------------
        first_ref = candidate["observation_refs"][0]
        chain_event = next(
            item
            for item in lab.events(session_id)
            if item["journal_seq"] == first_ref["journal_seq"]
        )
        payload = chain_event["payload"]
        assert payload["pid"] == GOLDEN_PID
        assert payload["packet_index"] == GOLDEN_LANDING
        assert payload["expected_cc"] == GOLDEN_EXPECTED_CC
        assert payload["actual_cc"] == GOLDEN_ACTUAL_CC
        assert payload["delta"] == GOLDEN_DELTA
        assert payload["artifact_id"] == faulted_artifact_id
        # The slot re-parses from the download: CC shifted by the delta
        # against the baseline twin (ADR-0007 第 4 条 shared frame).
        content = lab.artifact_content(faulted_artifact_id)
        slot_packet = TSPacket.from_bytes(
            content[GOLDEN_LANDING * 188 : (GOLDEN_LANDING + 1) * 188]
        )
        assert slot_packet.pid == GOLDEN_PID
        assert slot_packet.continuity_counter == GOLDEN_ACTUAL_CC
        baseline_content = golden_loader.load(f"{FAULT}-baseline").ts_bytes
        baseline_packet = TSPacket.from_bytes(
            baseline_content[GOLDEN_LANDING * 188 : (GOLDEN_LANDING + 1) * 188]
        )
        assert (
            slot_packet.continuity_counter
            == (baseline_packet.continuity_counter + GOLDEN_DELTA) % 16
        )

        # --- Recover -----------------------------------------------------------
        recover_run_id = lab.submit_run(session_id, [])
        recover_run = lab.await_run(session_id, recover_run_id)
        recover_artifacts = lab.artifacts_of_kind(recover_run, "generated_ts")
        recovery_analysis = lab.analyze_artifact(
            session_id, recover_run_id, recover_artifacts[0]["artifact_id"]
        )
        # The recovery stream restarts its own CC schedule: zero errors,
        # with the coverage facts the cc criteria need (not an absence).
        assert recovery_analysis.event_counts.get("ts.continuity_error") is None
        assert recovery_analysis.event_counts["ts.packet_batch_observed"] == 1

        # --- Verify -------------------------------------------------------------
        verdict = lab.verify(session_id, recover_run_id, inject_run_id, document)
        assert verdict["verdict"] == "PASS", verdict
        results = {
            criterion["criterion_id"]: criterion["result"]
            for criterion in verdict["criteria"]
        }
        assert set(results.values()) == {"PASS"}
        assert results["cc-continuous"] == "PASS"
        assert results["no-unexpected-cc"] == "PASS"
        assert results["fault-cleared"] == "PASS"
        assert verdict["evidence_refs"]
