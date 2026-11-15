"""Eight-step fault lab: PAT_MISSING (ticket #58, AC 1-3 for this fault).

scenario → run(inject) → observe(分析桥真事件) → diagnose(唯一主候选)
→ recover(新 Run 修复) → verify(SPEC-206 三态 PASS), over the
PRODUCTION composition with the real REST/WS surfaces:

- byte-level oracle: the run's baseline leg and faulted leg must equal
  the registered golden pair (the faulted bytes come from the
  INDEPENDENT transform script — the production filter output is
  asserted against that independent baseline, never against a self
  round-trip; SPEC-506 §5);
- diagnosis: the SPEC-307 builtin rule produces the single attributable
  primary candidate (REQ-204-008 诊断复归联测, 裁定 3);
- evidence chain: diagnosis → journal_seq → payload
  artifact_id/pid/packet_index → artifact bytes end-to-end (ADR-0007
  第 4 条: the evidence slot re-parses to the null-substitution
  symptom);
- structured evidence: the fault.* lifecycle events (ticket #56 real
  emission) ride the injected run;
- hint→REST pull closure: observation.event_appended → GET events
  (SPEC-305 §8, 裁定 3).
"""

from __future__ import annotations

import pytest
from ts.packet import TSPacket

from tests.e2e._fault_lab import FaultLab, fault_plan_wire, load_scenario, receive_hint

pytestmark = pytest.mark.e2e

FAULT = "pat-missing"
PAIRING_CODE = "DIAG_PAT_MISSING"
RULE_ID = "DIA-PAT-MISSING"
GOLDEN_MISSING_SLOTS = (202, 404)


def _packet_at(content: bytes, index: int) -> TSPacket:
    return TSPacket.from_bytes(content[index * 188 : (index + 1) * 188])


def test_pat_missing_eight_step_loop(golden_loader, tmp_path):
    baseline_vector = golden_loader.load(f"{FAULT}-baseline")
    faulted_vector = golden_loader.load(FAULT)
    raw, document = load_scenario(FAULT)

    with FaultLab(tmp_path / "fault-lab-pat.sqlite3") as lab:
        # --- Create ---------------------------------------------------------
        session_id = lab.create_session(raw)
        lab.start_session(session_id)

        # --- Generate (clean baseline run) ----------------------------------
        generate_run_id = lab.submit_run(session_id, [])
        generate_run = lab.await_run(session_id, generate_run_id)
        lab.drain()
        baseline_artifact = lab.artifacts_of_kind(generate_run, "generated_ts")
        assert len(baseline_artifact) == 1
        assert baseline_artifact[0]["sha256"] == baseline_vector.sha256
        # Inspect already here: the download path round-trips the oracle
        # bytes (SPEC-506: sha256 即身份).
        assert (
            lab.artifact_content(baseline_artifact[0]["artifact_id"])
            == baseline_vector.ts_bytes
        )

        # --- Inject (the scenario's single-fault plan) ----------------------
        inject_run_id = lab.submit_run(session_id, fault_plan_wire(document))
        assert inject_run_id != generate_run_id
        inject_run = lab.await_run(session_id, inject_run_id)
        lab.drain()

        faulted_artifacts = lab.artifacts_of_kind(inject_run, "faulted_ts")
        assert len(faulted_artifacts) == 1
        # THE byte-level oracle: production filter output == the
        # independently transformed golden faulted bytes.
        assert faulted_artifacts[0]["sha256"] == faulted_vector.sha256
        assert (
            lab.artifact_content(faulted_artifacts[0]["artifact_id"])
            == faulted_vector.ts_bytes
        )
        # The tee twin: the baseline leg is slot-preserving equal too.
        baseline_leg = lab.artifacts_of_kind(inject_run, "generated_ts")
        assert baseline_leg[0]["sha256"] == baseline_vector.sha256

        # Structured evidence: the fault.* lifecycle rode the injected run.
        fault_states = {
            item["event_type"]
            for item in lab.events(session_id)
            if item["event_type"].startswith("fault.")
            and item["scope"]["run_id"] == inject_run_id
        }
        assert {"fault.injected", "fault.activated", "fault.cleared"} <= (
            fault_states
        )

        # --- Analyze (in-process bridge) ------------------------------------
        faulted_artifact_id = faulted_artifacts[0]["artifact_id"]
        analysis = lab.analyze_artifact(session_id, inject_run_id, faulted_artifact_id)
        assert analysis.event_counts["ts.psi_section_observed"] >= 3

        # --- Diagnose (unique attributable primary candidate) ---------------
        report = lab.diagnose(session_id, inject_run_id)
        assert report["run_id"] == inject_run_id
        candidates = report["candidates"]
        assert len(candidates) == 1, [c["code"] for c in candidates]
        candidate = candidates[0]
        assert candidate["code"] == PAIRING_CODE
        assert candidate["rule_id"] == RULE_ID
        assert candidate["severity"] == "error"  # SPEC-307 §6 table
        assert candidate["confidence"] == "high"  # SPEC-307 §6 table
        assert candidate["evidence"]["artifact_id"] == faulted_artifact_id

        # --- Inspect: the evidence chain resolves to a packet slot ---------
        first_ref = candidate["observation_refs"][0]
        chain_event = next(
            item
            for item in lab.events(session_id)
            if item["journal_seq"] == first_ref["journal_seq"]
        )
        assert chain_event["event_type"] == first_ref["event_type"]
        payload = chain_event["payload"]
        assert payload["section"] == "PAT"
        assert payload["present"] is False
        assert payload["artifact_id"] == faulted_artifact_id
        assert payload["packet_index"] in GOLDEN_MISSING_SLOTS
        # End-to-end artifact parse at the evidence slot (ADR-0007 第 4 条):
        # the slot IS the null substitution — re-parsed from the download.
        slot_packet = _packet_at(
            lab.artifact_content(payload["artifact_id"]),
            payload["packet_index"],
        )
        assert slot_packet.pid == 0x1FFF

        # The diagnoses table view (SPEC-500 §4.4 list endpoint).
        rows = lab.diagnoses(session_id)
        assert any(
            row["code"] == PAIRING_CODE
            and row["state"] == "raised"
            and row["run_id"] == inject_run_id
            for row in rows
        )

        # --- Recover (new Run, the fault removed) ----------------------------
        recover_run_id = lab.submit_run(session_id, [])
        recover_run = lab.await_run(session_id, recover_run_id)
        recover_artifacts = lab.artifacts_of_kind(recover_run, "generated_ts")
        # Run terminal events commit BEFORE the subscription; the analysis
        # facts commit AFTER it (the live hint source for the closure).
        lab.drain()

        # --- hint → REST pull closure (SPEC-305 §8) --------------------------
        with lab.websocket(session_id) as ws:
            # Analyze publishes into the gateway; the drain commits make
            # the live hints flow while this socket is subscribed.
            lab.analyze_artifact(
                session_id, recover_run_id, recover_artifacts[0]["artifact_id"]
            )
            hint = receive_hint(ws, "observation.event_appended")
            assert hint["data"]["event_type"] == "ts.psi_section_observed"
        pulled = lab.events(session_id, event_type="ts.psi_section_observed")
        recovery_facts = [
            item
            for item in pulled
            if item["scope"]["run_id"] == recover_run_id
            and item["payload"].get("present") is True
        ]
        assert recovery_facts, "the REST pull must carry the recovery facts"

        # --- Verify (SPEC-206 three-state PASS) ------------------------------
        verdict = lab.verify(session_id, recover_run_id, inject_run_id, document)
        assert verdict["verdict"] == "PASS", verdict
        assert verdict["recovery_run_id"] == recover_run_id
        assert verdict["baseline_run_id"] == inject_run_id
        assert verdict["scenario"]["scenario_id"] == document.scenario_id
        assert verdict["scenario"]["content_hash"] == document.content_hash
        results = {
            criterion["criterion_id"]: criterion["result"]
            for criterion in verdict["criteria"]
        }
        assert set(results.values()) == {"PASS"}
        assert verdict["evidence_refs"], "every PASS criterion carries evidence"

        # The recovery run stayed clean: no fault.* recurrence and no
        # new diagnosis candidates (the lab loop closed).
        recovery_fault_events = [
            item
            for item in lab.events(session_id)
            if item["event_type"].startswith("fault.")
            and item["scope"]["run_id"] == recover_run_id
        ]
        assert recovery_fault_events == []
