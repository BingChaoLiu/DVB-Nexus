"""Eight-step fault lab: PMT_PID_MISMATCH (ticket #58, AC 1-3 for this
fault).

The repointing lab (golden: program_map_pid 4096 → 4100 with a
recomputed CRC — the PAT stays valid, the real PMT is orphaned): the
analysis bridge's contradiction pair
(``expected_program_map_pid``/``actual_program_map_pid``, present ONLY
on contradiction per the payload contract) drives the medium-confidence
rule (SPEC-307 §6) to the single attributable candidate; the evidence
slot re-parses from the downloaded artifact to a PAT that declares the
wrong PID; the recovery run verifies SPEC-206 PASS over the mapping
criterion.
"""

from __future__ import annotations

import pytest
from ts.packet import TSPacket
from ts.section_assembler import SectionAssembler
from ts.tables.pat import PAT_SECTION_POLICY, parse_pat_sections

from tests.e2e._fault_lab import FaultLab, fault_plan_wire, load_scenario

pytestmark = pytest.mark.e2e

FAULT = "pmt-pid-mismatch"
PAIRING_CODE = "DIAG_PMT_PID_MISMATCH"
RULE_ID = "DIA-PMT-PID-MISMATCH"
GOLDEN_PAT_SLOTS = (0, 202, 404)
DECLARED_PMT_PID = 4096
WRONG_PMT_PID = 4100


def _pat_declaration(content: bytes) -> tuple[tuple[int, int], ...]:
    """Re-parse the downloaded artifact's PAT table (PID 0 sections) —
    the (program_number, program_map_pid) pairs as the wire declares."""
    assembler = SectionAssembler(
        0, lambda table_id: PAT_SECTION_POLICY if table_id == 0x00 else None
    )
    sections = []
    for offset in range(0, len(content), 188):
        packet = TSPacket.from_bytes(content[offset : offset + 188])
        sections.extend(assembler.push(packet))
    assembler.flush()
    table = parse_pat_sections(sections[:1])  # identical retransmissions
    return tuple(
        (entry.program_number, entry.program_map_pid)
        for entry in table.programs
    )


def test_pmt_pid_mismatch_eight_step_loop(golden_loader, tmp_path):
    baseline_vector = golden_loader.load(f"{FAULT}-baseline")
    faulted_vector = golden_loader.load(FAULT)
    raw, document = load_scenario(FAULT)

    with FaultLab(tmp_path / "fault-lab-mismatch.sqlite3") as lab:
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
        # Three PAT instances, each carrying the contradiction pair.
        assert analysis.event_counts["ts.psi_section_observed"] >= 6

        # --- Diagnose ---------------------------------------------------------
        report = lab.diagnose(session_id, inject_run_id)
        lab.drain()
        candidates = report["candidates"]
        assert len(candidates) == 1, [c["code"] for c in candidates]
        candidate = candidates[0]
        assert candidate["code"] == PAIRING_CODE
        assert candidate["rule_id"] == RULE_ID
        assert candidate["severity"] == "error"
        assert candidate["confidence"] == "medium"  # SPEC-307 §6 table
        assert candidate["evidence"]["artifact_id"] == faulted_artifact_id

        # --- Inspect: the evidence slot re-declares the wrong PID -----------
        first_ref = candidate["observation_refs"][0]
        chain_event = next(
            item
            for item in lab.events(session_id)
            if item["journal_seq"] == first_ref["journal_seq"]
        )
        payload = chain_event["payload"]
        assert payload["section"] == "PAT"
        assert payload["actual_program_map_pid"] == WRONG_PMT_PID
        assert payload["expected_program_map_pid"] == DECLARED_PMT_PID
        assert payload["artifact_id"] == faulted_artifact_id
        assert payload["packet_index"] in GOLDEN_PAT_SLOTS
        # End-to-end artifact parse: the downloaded bytes' PAT itself
        # declares the wrong PID (with its recomputed, verifying CRC).
        declaration = _pat_declaration(lab.artifact_content(faulted_artifact_id))
        assert declaration == ((1, WRONG_PMT_PID),)

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
        assert results["mapping-valid"] == "PASS"
        assert results["pat-valid"] == "PASS"
        assert results["fault-cleared"] == "PASS"
        assert verdict["evidence_refs"]
