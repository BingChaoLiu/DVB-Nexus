"""Eight-step fault lab: PMT_PID_DRIFT (ticket #139 — the SC-09 injection
chain closed, the #136 收口 patch ticket D-2).

The drift lab (no golden pair — the Phase 2 patch primitive asserts its
oracle structurally, SC-06/07/08 posture): from the activation slot the
PAT's declared ``program_map_PID`` drifts to ``new_pid_map`` and the PMT
version bumps (both CRC-valid — a legal declaration update), while the
data keeps flowing on the real PIDs, so the newly declared PID carries no
data (声明 PID 无数据漂移).  The analysis bridge's PSI version comparison
(``pmt_version`` always + ``expected_pmt_version`` on contradiction only)
drives the low-confidence rule to the single attributable candidate; the
evidence chain re-parses from the downloaded artifact; the recovery run
verifies SPEC-206 PASS over the structural fault_inactive criterion.
"""

from __future__ import annotations

import json

import pytest
from ts.packet import TSPacket
from ts.section_assembler import SectionAssembler
from ts.tables.pat import PAT_SECTION_POLICY, parse_pat_sections
from ts.tables.pmt import PMT_SECTION_POLICY, parse_pmt

from simulation.scenario.schema import parse_scenario_document
from tests.e2e._fault_lab import FaultLab, fault_plan_wire
from tests._support.paths import REPO_ROOT

pytestmark = pytest.mark.e2e

PAIRING_CODE = "DIAG_PMT_PID_DRIFT"
RULE_ID = "DIA-PMT-PID-DRIFT"
DECLARED_PMT_PID = 4096  # 0x1000 — the golden geometry's PMT stream
DRIFTED_PID = 4608  # the SC-09 wire value (new_pid_map {"1": 4608})
ACTIVATION = 400  # mid-stream drift point (the lab pack's declaration)
PAT_PID = 0x0000


def _load_sc09() -> tuple[dict, object]:
    raw = json.loads(
        (REPO_ROOT / "scenarios" / "SC-09-pmt_pid_drift.json").read_text(
            encoding="utf-8"
        )
    )
    return raw, parse_scenario_document(raw)


def _pat_declarations(content: bytes) -> set[int]:
    """The distinct ``program_map_PID`` values the artifact's PAT declares
    (the drift splits the retransmission set at the activation slot)."""
    assembler = SectionAssembler(
        PAT_PID, lambda tid: PAT_SECTION_POLICY if tid == 0x00 else None
    )
    declared: set[int] = set()
    for offset in range(0, len(content), 188):
        packet = TSPacket.from_bytes(content[offset : offset + 188])
        for section in assembler.push(packet):
            table = parse_pat_sections([section])
            declared.update(
                entry.program_map_pid for entry in table.programs
            )
    assembler.flush()
    return declared


def _pmt_versions(content: bytes) -> set[int]:
    """The distinct PMT ``version_number`` values the artifact declares
    (the bump splits the retransmission set at the activation slot)."""
    assembler = SectionAssembler(
        DECLARED_PMT_PID, lambda tid: PMT_SECTION_POLICY if tid == 0x02 else None
    )
    versions: set[int] = set()
    for offset in range(0, len(content), 188):
        packet = TSPacket.from_bytes(content[offset : offset + 188])
        for section in assembler.push(packet):
            versions.add(parse_pmt(section).version_number)
    assembler.flush()
    return versions


def test_pmt_pid_drift_eight_step_loop(tmp_path):
    raw, document = _load_sc09()

    with FaultLab(tmp_path / "fault-lab-sc09-drift.sqlite3") as lab:
        # --- Create (加载即建: the scenario_id branch governs, the Lab UI's
        # 开局 body shape — the v2 scenario's topology_id is registry-
        # foreign, the document's own initial_topology wins; the branch
        # lands the session directly READY — the run face needs RUNNING, so
        # the start transition is the only explicit step) -------------------
        session_id = lab.create_session(raw, scenario_id=document.scenario_id)
        view = lab._client.get(f"/api/v1/sessions/{session_id}").json()
        assert view["lifecycle"] == "ready", view["lifecycle"]
        assert (
            lab._client.post(f"/api/v1/sessions/{session_id}/start").status_code
            == 200
        )

        # --- Generate (clean baseline) ---------------------------------------
        generate_run_id = lab.submit_run(session_id, [])
        generate_run = lab.await_run(session_id, generate_run_id)
        lab.drain()
        baseline_content = lab.artifact_content(
            lab.artifacts_of_kind(generate_run, "generated_ts")[0]["artifact_id"]
        )

        # --- Inject (the drift chain — previously the #121 skeleton raise) ---
        inject_run_id = lab.submit_run(session_id, fault_plan_wire(document))
        inject_run = lab.await_run(session_id, inject_run_id)
        lab.drain()
        faulted_artifacts = lab.artifacts_of_kind(inject_run, "faulted_ts")
        assert len(faulted_artifacts) == 1
        faulted_artifact_id = faulted_artifacts[0]["artifact_id"]
        faulted_content = lab.artifact_content(faulted_artifact_id)
        # 等位替换: same shared frame, byte count untouched
        assert len(faulted_content) == len(baseline_content)

        # The wire oracle, re-parsed independently of the production filter:
        # the declared PID set splits at the activation slot (4096 before,
        # 4608 after) and the PMT version set splits the same way (0 → 1).
        assert _pat_declarations(faulted_content) == {DECLARED_PMT_PID, DRIFTED_PID}
        assert _pmt_versions(faulted_content) == {0, 1}
        # 声明 PID 无数据: nothing ever rides the drifted PID itself
        assert not any(
            TSPacket.from_bytes(faulted_content[offset : offset + 188]).pid
            == DRIFTED_PID
            for offset in range(0, len(faulted_content), 188)
        )
        # and the baseline carries none of the drift
        assert _pat_declarations(baseline_content) == {DECLARED_PMT_PID}
        assert _pmt_versions(baseline_content) == {0}

        # --- Analyze ----------------------------------------------------------
        analysis = lab.analyze_artifact(session_id, inject_run_id, faulted_artifact_id)
        assert analysis.event_counts["ts.psi_section_observed"] >= 2

        # --- Diagnose (rule 4 lights up on the version comparison) -----------
        report = lab.diagnose(session_id, inject_run_id)
        lab.drain()
        candidates = report["candidates"]
        # TWO honest candidates: the drift's declaration face IS a
        # PMT_PID_MISMATCH symptom by construction (the PAT points to a
        # PID with no PMT — orphan PMT), and the version face is the
        # drift's own comparison.  Both rule declarations fire unchanged
        # (#130 two-state); SPEC-307 §5 ordering pins the sequence.
        assert [c["code"] for c in candidates] == [
            "DIAG_PMT_PID_MISMATCH",
            PAIRING_CODE,
        ]
        candidate = next(
            c for c in candidates if c["code"] == PAIRING_CODE
        )
        assert candidate["rule_id"] == RULE_ID
        assert candidate["severity"] == "error"
        assert candidate["confidence"] == "low"  # SPEC-307 §Phase2 table
        assert candidate["evidence"]["artifact_id"] == faulted_artifact_id

        # --- Inspect: the evidence chain re-parses to the version drift -----
        first_ref = candidate["observation_refs"][0]
        chain_event = next(
            item
            for item in lab.events(session_id)
            if item["journal_seq"] == first_ref["journal_seq"]
        )
        payload = chain_event["payload"]
        assert payload["section"] == "PMT"
        assert payload["pid"] == DECLARED_PMT_PID
        assert payload["pmt_version"] == 1
        assert payload["expected_pmt_version"] == 0
        assert payload["crc_valid"] is True
        assert payload["artifact_id"] == faulted_artifact_id
        assert payload["packet_index"] > ACTIVATION

        # --- Recover (empty-plan rerun) ----------------------------------------
        recover_run_id = lab.submit_run(session_id, [])
        recover_run = lab.await_run(session_id, recover_run_id)
        lab.drain()
        recover_content = lab.artifact_content(
            lab.artifacts_of_kind(recover_run, "generated_ts")[0]["artifact_id"]
        )
        assert _pat_declarations(recover_content) == {DECLARED_PMT_PID}
        assert _pmt_versions(recover_content) == {0}

        # --- Verify -------------------------------------------------------------
        verdict = lab.verify(session_id, recover_run_id, inject_run_id, document)
        assert verdict["verdict"] == "PASS", verdict
        results = {
            criterion["criterion_id"]: criterion["result"]
            for criterion in verdict["criteria"]
        }
        assert results["fault-cleared"] == "PASS"
        assert verdict["evidence_refs"]
