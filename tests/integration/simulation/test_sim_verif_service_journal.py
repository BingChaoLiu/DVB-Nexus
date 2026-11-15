"""Verification service over the real journal chain (ticket #56, R2 posture).

Directly wires the REAL chain — production ``SemanticFaultFilter`` tee run
→ #41 emitter fault.* emission → #47 gateway → SQLite journal (the
``journal`` fixture, migrations applied) → the SPEC-206 service reads that
journal back and renders the three-state verdict. No fabricated fault
facts: the fault lifecycle the verdict consumes was emitted by the
execution hooks at the real SPEC-204 §8.1 points.

Normalized ``ts.*`` observations ride the sanctioned fixture posture
(裁定 A — the G3 analysis bridge is not eventized yet; #58 replaces the
fixture events with real analysis events and the engine is unchanged,
SPEC-206 §11 解耦条款). The R2 replay-equivalence obligation is exercised
by ``test_replay_same_journal_same_verdict`` (same journal ⇒ identical
verdict content) plus the route-level real-chain test.

The §9 CC_DISCONTINUITY 修复前后样例: pre-fix re-injection ⇒ FAIL; the
clean recovery run ⇒ PASS; the baseline itself as candidate ⇒
INCONCLUSIVE (SIM_VERIF_BASELINE_REUSED).
"""

from __future__ import annotations

import asyncio

import pytest

pytestmark = pytest.mark.integration

from adapters.storage.journal import SqliteEventJournal
from adapters.storage.repositories import SqliteVerificationRepository
from application.observation import EventGateway, GatewayConfig
from domain.observation import parse_envelope
from domain.observation.registry import FAULT_EVENT_TYPES
from faults.factory import build_semantic_filter_factory
from simulation.fault_plan import FaultActivation, FaultDefinition
from simulation.runtime import SimulationRuntime
from simulation.ts_runtime import TSRuntime
from simulation.verification.service import VerificationService

from tests._support.diagnosis_fixtures import observation_envelope
from tests.unit.simulation._ts_runtime_builders import (
    make_generator_config,
    make_session_spec,
)

SESSION_ID = "sess-verif-chain"
NODE = "demux-0"
FAULT_ID = "fd000000-0000-4000-8000-0000000000c1"


def _cc_plan() -> tuple[FaultDefinition, ...]:
    return (
        FaultDefinition(
            fault_id=FAULT_ID,
            fault_type="CC_DISCONTINUITY",
            target_id=f"{NODE}:pid:0x0100",
            parameters={"delta": 3},
            activation=FaultActivation(kind="packet_index", packet_index=10),
            expected_observations=("ts.continuity_error",),
        ),
    )


PASS_CRITERIA = [
    {"criterion_id": "sc-01", "kind": "fault_inactive", "mandatory": True, "fault_id": FAULT_ID},
    {"criterion_id": "sc-02", "kind": "cc_continuous", "mandatory": True, "fault_id": None},
    {"criterion_id": "sc-03", "kind": "psi_pat_valid", "mandatory": True, "fault_id": None},
    {"criterion_id": "sc-04", "kind": "psi_pmt_valid", "mandatory": True, "fault_id": None},
    {
        "criterion_id": "sc-05",
        "kind": "pat_pmt_mapping_valid",
        "mandatory": True,
        "fault_id": None,
    },
    {
        "criterion_id": "sc-06",
        "kind": "no_unexpected_cc_error",
        "mandatory": True,
        "fault_id": None,
    },
]


def _recovery_observations(session_id: str, run_id: str) -> list[dict]:
    """The normalized-observation fixture program for the recovery run
    (source/confidence axes mandatory on every ts.* payload): stream
    coverage, PAT/PMT mapping, zero CC errors."""
    def _axes(payload: dict) -> dict:
        return {"source": "internal_parser", "confidence": "parsed", **payload}

    return [
        observation_envelope(
            event_type="ts.packet_batch_observed",
            payload=_axes({"packet_count": 500, "continuity_error_count": 0}),
            session_id=session_id,
            run_id=run_id,
            pid=None,
            source_ns=1_000,
        ),
        observation_envelope(
            event_type="ts.psi_section_observed",
            payload=_axes(
                {
                    "section": "PAT",
                    "present": True,
                    "crc_valid": True,
                    "actual_program_map_pid": 0x1000,
                    "packet_index": 100,
                }
            ),
            session_id=session_id,
            run_id=run_id,
            pid=0,
            source_ns=2_000,
        ),
        observation_envelope(
            event_type="ts.psi_section_observed",
            payload=_axes(
                {
                    "section": "PMT",
                    "present": True,
                    "crc_valid": True,
                    "packet_index": 140,
                }
            ),
            session_id=session_id,
            run_id=run_id,
            pid=0x1000,
            source_ns=3_000,
        ),
    ]


class VerifStack:
    """Runtime + TS runtime + gateway + journal + the service under test."""

    def __init__(self, journal) -> None:
        from adapters.storage.db import connect

        # check_same_thread posture (ticket #47): the TS worker pool writes
        # while the test thread drives the gateway; the production connect
        # carries the sqlite3.Row factory the journal adapter needs.
        connection = connect(journal.db_path, check_same_thread=False)
        # check_same_thread posture (ticket #47): the TS worker pool writes
        # while the test thread drives the gateway.
        self.journal_adapter = SqliteEventJournal(connection)
        self.gateway = EventGateway(
            self.journal_adapter, GatewayConfig()
        )
        self.runtime = SimulationRuntime(event_sink=self.gateway)
        self.ts_runtime = TSRuntime(
            runtime=self.runtime,
            filter_factory=build_semantic_filter_factory(),
        )
        self.repository = SqliteVerificationRepository(connection)
        self.service = VerificationService(
            self.journal_adapter,
            self.gateway,
            self.repository,
            now_utc_ms=lambda: 1_700_000_000_000,
        )
        self.spec = make_session_spec(session_id=SESSION_ID)

    def bootstrap_session(self) -> None:
        async def main() -> None:
            await self.runtime.create_session(self.spec)
            await self.runtime.validate_session(SESSION_ID)
            await self.runtime.start(SESSION_ID)

        asyncio.run(main())

    def run(self, fault_plan=()) -> str:
        prepared = self.ts_runtime.prepare(
            self.spec, make_generator_config(), fault_plan
        )

        async def main() -> str:
            result = await self.ts_runtime.run(prepared, _MemorySink())
            self.gateway.drain()
            return result.run_id

        return asyncio.run(main())

    def publish_observations(self, run_id: str) -> None:
        for document in _recovery_observations(SESSION_ID, run_id):
            assert self.gateway.publish(document).accepted
        self.gateway.drain()


class _MemorySink:
    """Minimal ArtifactSink over in-memory legs (unit-builder reuse)."""

    def __init__(self) -> None:
        from tests.unit.simulation._ts_runtime_builders import FakeArtifactSink

        self._fake = FakeArtifactSink()

    def __getattr__(self, name: str):
        return getattr(self._fake, name)


@pytest.fixture
def stack(journal):
    harness = VerifStack(journal)
    harness.bootstrap_session()
    return harness


class TestRealChainVerdict:
    """The full loop: real faulted run → real recovery run → verify PASS."""

    def test_repaired_recovery_run_passes_all_six_criteria(self, stack):
        baseline_run_id = stack.run(_cc_plan())
        recovery_run_id = stack.run()  # the repair: an empty fault plan
        stack.publish_observations(recovery_run_id)

        result = stack.service.verify(
            SESSION_ID,
            recovery_run_id,
            baseline_run_id=baseline_run_id,
            scenario_id="9c0f0000-0000-4000-8000-0000000000a1",
            scenario_version="1.0.0",
            scenario_content_hash="cc" * 32,
            pass_criteria=PASS_CRITERIA,
        )

        assert result.verdict == "PASS"
        for entry in result.criteria:
            assert entry.result == "PASS", (
                f"{entry.criterion_id} ({entry.kind}): {entry.reason}"
            )
        # The fault_inactive chain consumed the REAL emitted lifecycle.
        inactive = next(
            entry for entry in result.criteria if entry.kind == "fault_inactive"
        )
        journal_refs = [
            ref for ref in inactive.evidence_refs if ref["kind"] == "journal"
        ]
        assert {ref["event_type"] for ref in journal_refs} >= {
            "fault.injected",
            "fault.activated",
            "fault.cleared",
        }

    def test_verdict_is_persisted_and_event_consistent(self, stack, journal):
        baseline_run_id = stack.run(_cc_plan())
        recovery_run_id = stack.run()
        stack.publish_observations(recovery_run_id)

        result = stack.service.verify(
            SESSION_ID,
            recovery_run_id,
            baseline_run_id=baseline_run_id,
            scenario_id="9c0f0000-0000-4000-8000-0000000000a1",
            scenario_version="1.0.0",
            scenario_content_hash="cc" * 32,
            pass_criteria=PASS_CRITERIA,
        )

        # Persisted verdict (verdict 随 run/scenario 版本持久化, REQ-206-006).
        rows = stack.repository.query(SESSION_ID)
        assert len(rows) == 1
        row = rows[0]
        assert row.verdict == result.verdict == "PASS"
        assert row.run_id == recovery_run_id
        assert row.baseline_run_id == baseline_run_id
        assert row.scenario_content_hash == "cc" * 32
        assert row.verified_at_utc_ms == 1_700_000_000_000

        # The committed event exists, is the authoritative protected name,
        # and its payload mirrors the persisted row (§9 一致性). The drain
        # is the ingestion pump (composition-root concern) — the service
        # published through the gateway face.
        stack.gateway.drain()
        committed = [
            row_envelope
            for row_envelope in stack.journal_adapter.query(SESSION_ID, after_seq=0, limit=2_000)
            if row_envelope.event_type == "recovery.verification_completed"
        ]
        assert len(committed) == 1
        # The committed record view carries the gateway stamp; parse the
        # producer view (stamp stripped) for the conformance check.
        producer_view = dict(committed[0].envelope)
        producer_view.pop("journal_seq", None)
        envelope = parse_envelope(producer_view)
        envelope.ensure_publishable()
        assert envelope.scope.run_id == recovery_run_id
        payload = committed[0].envelope["payload"]
        assert payload["verdict"] == row.verdict
        assert payload["run_id"] == row.run_id
        assert payload["baseline_run_id"] == row.baseline_run_id
        assert payload["scenario_content_hash"] == row.scenario_content_hash
        assert payload["criteria"] == row.criteria

    def test_fault_events_really_flew_through_the_journal(self, stack, journal):
        """裁定 2 的直接证据: the baseline tee run emitted all four fault.*
        events into the REAL journal, in lifecycle order."""
        baseline_run_id = stack.run(_cc_plan())
        stack.gateway.drain()
        events = [
            row
            for row in stack.journal_adapter.query(SESSION_ID, after_seq=0, limit=2_000)
            if row.event_type in FAULT_EVENT_TYPES
        ]
        assert [row.event_type for row in events] == [
            "fault.injected",
            "fault.activated",
            "fault.applied",
            "fault.cleared",
        ]
        for row in events:
            assert row.envelope["scope"]["run_id"] == baseline_run_id
            assert row.envelope["correlation"]["fault_id"] == FAULT_ID
            assert row.envelope["correlation"]["node_id"] == NODE
            assert row.envelope["correlation"]["pid"] == 0x0100

    def test_replay_same_journal_same_verdict(self, stack):
        """R2 重放等价性: the same journal replays to the identical verdict
        content (only the operational timestamp is exempt)."""
        baseline_run_id = stack.run(_cc_plan())
        recovery_run_id = stack.run()
        stack.publish_observations(recovery_run_id)

        def _verify():
            return stack.service.verify(
                SESSION_ID,
                recovery_run_id,
                baseline_run_id=baseline_run_id,
                scenario_id="9c0f0000-0000-4000-8000-0000000000a1",
                scenario_version="1.0.0",
                scenario_content_hash="cc" * 32,
                pass_criteria=PASS_CRITERIA,
            )

        first = _verify()
        second = _verify()
        assert first.verdict == second.verdict
        assert first.criteria == second.criteria
        assert first.evidence_refs == second.evidence_refs
        assert first.summary == second.summary
        # Only the operational timestamp moves (and here it is injected to
        # a constant, so even that matches — the discipline is the engine's
        # purity, not the injection).
        assert first.verified_at_utc_ms == second.verified_at_utc_ms


class TestPreAndPostFixSample:
    """§9: CC_DISCONTINUITY 修复前后端到端样例."""

    def test_prefix_refix_postfix_arc(self, stack):
        baseline_run_id = stack.run(_cc_plan())

        # 修复前（重投同故障的新 Run，learner 未做任何修复）→ FAIL:
        # the recovery journal carries fault.injected for the same fault.
        refaulted_run_id = stack.run(_cc_plan())
        refaulted = stack.service.verify(
            SESSION_ID,
            refaulted_run_id,
            baseline_run_id=baseline_run_id,
            scenario_id="9c0f0000-0000-4000-8000-0000000000a1",
            scenario_version="1.0.0",
            scenario_content_hash="cc" * 32,
            pass_criteria=PASS_CRITERIA,
        )
        assert refaulted.verdict == "FAIL"
        inactive = next(
            entry for entry in refaulted.criteria if entry.kind == "fault_inactive"
        )
        assert inactive.result == "FAIL"

        # The baseline itself as candidate → INCONCLUSIVE (BASELINE_REUSED).
        reused = stack.service.verify(
            SESSION_ID,
            baseline_run_id,
            baseline_run_id=baseline_run_id,
            scenario_id="9c0f0000-0000-4000-8000-0000000000a1",
            scenario_version="1.0.0",
            scenario_content_hash="cc" * 32,
            pass_criteria=PASS_CRITERIA,
        )
        assert reused.verdict == "INCONCLUSIVE"

        # 修复后（空 plan 的恢复 Run + 干净观测）→ PASS.
        recovery_run_id = stack.run()
        stack.publish_observations(recovery_run_id)
        recovered = stack.service.verify(
            SESSION_ID,
            recovery_run_id,
            baseline_run_id=baseline_run_id,
            scenario_id="9c0f0000-0000-4000-8000-0000000000a1",
            scenario_version="1.0.0",
            scenario_content_hash="cc" * 32,
            pass_criteria=PASS_CRITERIA,
        )
        assert recovered.verdict == "PASS"

    def test_incomplete_recovery_run_is_inconclusive(self, stack):
        baseline_run_id = stack.run(_cc_plan())
        # The recovery "run" never happened — no journal events at all.
        from simulation.errors import (
            SIM_VERIF_RUN_MISMATCH,
            VerificationRunMismatchError,
        )

        with pytest.raises(VerificationRunMismatchError) as excinfo:
            stack.service.verify(
                SESSION_ID,
                "run-ghost",
                baseline_run_id=baseline_run_id,
                scenario_id="scn",
                scenario_version="1.0.0",
                scenario_content_hash="aa",
                pass_criteria=PASS_CRITERIA,
            )
        assert excinfo.value.code == SIM_VERIF_RUN_MISMATCH

    def test_unknown_criterion_kind_is_rejected(self, stack):
        from simulation.errors import (
            SIM_VERIF_CRITERION_INVALID,
            VerificationCriterionInvalidError,
        )

        recovery_run_id = stack.run()
        with pytest.raises(VerificationCriterionInvalidError) as excinfo:
            stack.service.verify(
                SESSION_ID,
                recovery_run_id,
                baseline_run_id="run-x",
                scenario_id="scn",
                scenario_version="1.0.0",
                scenario_content_hash="aa",
                pass_criteria=[
                    {
                        "criterion_id": "sc-99",
                        "kind": "ui_state_green",
                        "mandatory": True,
                        "fault_id": None,
                    }
                ],
            )
        assert excinfo.value.code == SIM_VERIF_CRITERION_INVALID
