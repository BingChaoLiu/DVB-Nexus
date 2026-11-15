"""Eight-step fault lab: PMT_INVALID_CRC (ticket #58, AC 1-3 for this
fault).

The persistent-corruption lab: three PMT instances fail the MPEG-2 CRC
in the frozen frame (slots 1/206/412) — the SPEC-307 count window
(min_count 2) fires, producing one ``diagnosis.raised`` plus two
``diagnosis.updated`` accumulations on the injected run; the evidence
slot re-parses from the downloaded artifact to the CRC-invalid section;
the recovery run verifies SPEC-206 PASS.
"""

from __future__ import annotations

import pytest
from ts.crc import verify_mpeg2_crc32
from ts.packet import TSPacket
from ts.section_assembler import SectionAssembler
from ts.tables.pmt import PMT_SECTION_POLICY, PMT_TABLE_ID

from tests.e2e._fault_lab import FaultLab, fault_plan_wire, load_scenario

pytestmark = pytest.mark.e2e

FAULT = "pmt-invalid-crc"
PAIRING_CODE = "DIAG_PMT_CRC_BAD"
RULE_ID = "DIA-PMT-CRC-BAD"
GOLDEN_CRC_SLOTS = (1, 206, 412)
PMT_PID = 0x1000


def _section_bytes_at(content: bytes, index: int) -> bytes:
    """The whole single-packet PMT section at the slot (SPEC-102 framing
    via the public slice arithmetic)."""
    packet = TSPacket.from_bytes(content[index * 188 : (index + 1) * 188])
    assert packet.pid == PMT_PID and packet.payload_unit_start_indicator
    payload = packet.payload
    start = 1 + payload[0]
    total = 3 + ((payload[start + 1] & 0x0F) << 8 | payload[start + 2])
    return payload[start : start + total]


def test_pmt_invalid_crc_eight_step_loop(golden_loader, tmp_path):
    baseline_vector = golden_loader.load(f"{FAULT}-baseline")
    faulted_vector = golden_loader.load(FAULT)
    raw, document = load_scenario(FAULT)

    with FaultLab(tmp_path / "fault-lab-crc.sqlite3") as lab:
        # --- Create ---------------------------------------------------------
        session_id = lab.create_session(raw)
        lab.start_session(session_id)

        # --- Generate ---------------------------------------------------------
        generate_run_id = lab.submit_run(session_id, [])
        generate_run = lab.await_run(session_id, generate_run_id)
        lab.drain()
        baseline_artifact = lab.artifacts_of_kind(generate_run, "generated_ts")[0]
        assert baseline_artifact["sha256"] == baseline_vector.sha256

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
        assert analysis.event_counts["ts.psi_section_observed"] >= 6

        # --- Diagnose: the persistent symptom is ONE candidate ---------------
        report = lab.diagnose(session_id, inject_run_id)
        lab.drain()  # the diagnosis lifecycle events ride the gateway queue
        candidates = report["candidates"]
        assert len(candidates) == 1, [c["code"] for c in candidates]
        candidate = candidates[0]
        assert candidate["code"] == PAIRING_CODE
        assert candidate["rule_id"] == RULE_ID
        assert candidate["severity"] == "error"
        assert candidate["confidence"] == "high"
        assert candidate["evidence"]["artifact_id"] == faulted_artifact_id

        # The count window: golden persistent gives 3 instances ≥ 2 —
        # one raised plus two updated accumulations in the journal.
        lifecycle = [
            item["event_type"]
            for item in lab.events(session_id, event_type="diagnosis.raised")
            if item["scope"]["run_id"] == inject_run_id
        ]
        updates = [
            item
            for item in lab.events(session_id, event_type="diagnosis.updated")
            if item["scope"]["run_id"] == inject_run_id
        ]
        assert lifecycle == ["diagnosis.raised"]
        assert len(updates) == 2

        # --- Inspect: evidence chain resolves to a CRC-invalid section ------
        first_ref = candidate["observation_refs"][0]
        chain_event = next(
            item
            for item in lab.events(session_id)
            if item["journal_seq"] == first_ref["journal_seq"]
        )
        payload = chain_event["payload"]
        assert payload["section"] == "PMT"
        assert payload["crc_valid"] is False
        assert payload["artifact_id"] == faulted_artifact_id
        assert payload["packet_index"] in GOLDEN_CRC_SLOTS
        # The slot re-parses from the download: the section bytes FAIL
        # the MPEG-2 CRC (the corruption, verified independently).
        section = _section_bytes_at(
            lab.artifact_content(payload["artifact_id"]),
            payload["packet_index"],
        )
        assert section[0] == PMT_TABLE_ID
        assert not verify_mpeg2_crc32(section)

        # --- Recover -----------------------------------------------------------
        recover_run_id = lab.submit_run(session_id, [])
        recover_run = lab.await_run(session_id, recover_run_id)
        recover_artifacts = lab.artifacts_of_kind(recover_run, "generated_ts")
        lab.analyze_artifact(
            session_id, recover_run_id, recover_artifacts[0]["artifact_id"]
        )

        # --- Verify -------------------------------------------------------------
        verdict = lab.verify(session_id, recover_run_id, inject_run_id, document)
        assert verdict["verdict"] == "PASS", verdict
        results = {
            criterion["criterion_id"]: criterion["result"]
            for criterion in verdict["criteria"]
        }
        assert set(results.values()) == {"PASS"}
        # The recovery PMT verifies: the psi_pmt_valid criterion saw the
        # clean crc_valid facts (无观测 ≠ 干净 — the facts are positive).
        assert results["pmt-valid"] == "PASS"
        assert results["fault-cleared"] == "PASS"
        assert verdict["evidence_refs"]

        # The recovery run carries no fault lifecycle at all (empty plan).
        recovery_fault_events = [
            item
            for item in lab.events(session_id)
            if item["event_type"].startswith("fault.")
            and item["scope"]["run_id"] == recover_run_id
        ]
        assert recovery_fault_events == []
