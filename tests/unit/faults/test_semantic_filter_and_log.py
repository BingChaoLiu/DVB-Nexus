"""SemanticFaultFilter composition + SPEC-204 §8.2 mutation log tests."""

from __future__ import annotations

import json

import pytest

from faults.factory import build_semantic_filter_factory, create_fault_filter
from faults.filters.semantic import SemanticFaultFilter
from ts.generator.config import GeneratorConfig, ProgramConfig

from tests.unit.faults._fault_builders import (
    GOLDEN_ES1_PID,
    GOLDEN_PAT_PID,
    golden_baseline_packets,
    cc_discontinuity_fault,
    pat_missing_fault,
    pmt_pid_mismatch_fault,
)

pytestmark = pytest.mark.unit


def _minimal_config() -> GeneratorConfig:
    return GeneratorConfig(
        schema_version=1,
        profile="analysis_only",
        deterministic=True,
        seed=1234567,
        initial_media_clock_27mhz=0,
        target_bitrate_bps=3_008_000,
        output_packet_count=600,
        program=ProgramConfig(
            transport_stream_id=1,
            program_number=1,
            pmt_pid=0x1000,
            pcr_pid=0x0100,
            version_number=0,
            streams=(),
        ),
    )


@pytest.fixture(scope="module")
def baseline() -> tuple:
    return golden_baseline_packets()


class TestComposition:
    def test_multiple_faults_compose_in_plan_order(self, baseline) -> None:
        plan = (pat_missing_fault(), cc_discontinuity_fault())
        single_pat = SemanticFaultFilter((pat_missing_fault(),))
        single_cc = SemanticFaultFilter((cc_discontinuity_fault(),))
        combined = SemanticFaultFilter(plan)
        pat_faulted = [single_pat.apply(i, p) for i, p in enumerate(baseline)]
        both = [
            combined.apply(i, p)
            for i, p in enumerate([single_pat.apply(i, p) for i, p in enumerate(baseline)])
        ]
        # CC writes the faulted half-byte last (plan order); the combined
        # output equals sequential single-fault application.
        assert [
            both[i].to_bytes() for i in range(len(baseline))
        ] == [
            single_cc.apply(i, pat_faulted[i]).to_bytes()
            for i in range(len(baseline))
        ]
        assert combined.mutation_log() != b""

    def test_empty_plan_filter_is_identity(self, baseline) -> None:
        empty = SemanticFaultFilter(())
        for index, packet in enumerate(baseline):
            assert empty.apply(index, packet).to_bytes() == packet.to_bytes()
        document = json.loads(empty.mutation_log().decode("utf-8"))
        assert document["mutations"] == []
        assert document["faults"] == []

    def test_unvalidated_definition_refused(self, baseline) -> None:
        from faults.definition import FaultDefinition

        bad = FaultDefinition(
            fault_id="f",
            fault_type="SOMETHING_ELSE",
            target_id="demux-0:pid:0x0000",
            expected_observations=("ts.x",),
        )
        with pytest.raises(ValueError):
            SemanticFaultFilter((bad,))


class TestMutationLogDocument:
    def test_document_carries_the_82_record_fields(self, baseline) -> None:
        plan = (pat_missing_fault(),)
        spec_filter = SemanticFaultFilter(plan, run_id="run-42")
        for index, packet in enumerate(baseline):
            spec_filter.apply(index, packet)
        document = json.loads(spec_filter.mutation_log().decode("utf-8"))
        assert document["run_id"] == "run-42"
        assert document["schema_version"] == 1
        assert document["parameters_schema_version"] == 1
        record = document["mutations"][0]
        for key in (
            "fault_id",
            "fault_type",
            "target",
            "packet_index",
            "before",
            "after",
            "change",
            "parameters",
            "parameters_schema_version",
        ):
            assert key in record
        assert record["packet_index"] == 202
        assert record["target"]["node_id"] == "demux-0"
        assert record["target"]["pid"] == GOLDEN_PAT_PID
        assert record["before"]["pid"] == GOLDEN_PAT_PID
        assert record["after"]["pid"] == 0x1FFF
        # offline recheck: the slot digests identify the same slot in both
        # artifacts (§8.2 足以离线复核).
        assert set(record["before"]) >= {
            "pid",
            "continuity_counter",
            "afc",
            "pusi",
            "slot_sha256",
        }

    def test_lifecycle_carries_injected_activated_applied_cleared(
        self, baseline
    ) -> None:
        plan = (cc_discontinuity_fault(),)
        spec_filter = SemanticFaultFilter(plan)
        for index, packet in enumerate(baseline):
            spec_filter.apply(index, packet)
        document = json.loads(spec_filter.mutation_log().decode("utf-8"))
        summary = document["faults"][0]
        lifecycle = summary["lifecycle"]
        assert lifecycle["fault.injected"] is True
        assert lifecycle["fault.activated"] == 30
        assert lifecycle["fault.applied"] and lifecycle["fault.applied"][0] == 50
        assert lifecycle["fault.cleared"] is True
        assert set(lifecycle["events"]) == {
            "fault.injected",
            "fault.activated",
            "fault.applied",
            "fault.cleared",
        }
        assert summary["expected_observations"] == ["ts.continuity_error"]
        assert summary["parameters"] == {"delta": 3}
        assert summary["parameters_schema_version"] == 1

    def test_log_is_deterministic_for_the_same_plan(self, baseline) -> None:
        def run_and_log() -> bytes:
            spec_filter = SemanticFaultFilter(
                (pat_missing_fault(), pmt_pid_mismatch_fault()),
                run_id="run-7",
            )
            for index, packet in enumerate(baseline):
                spec_filter.apply(index, packet)
            return spec_filter.mutation_log()

        assert run_and_log() == run_and_log()

    def test_slot_digests_match_the_actual_stream_bytes(self, baseline) -> None:
        import hashlib

        spec_filter = SemanticFaultFilter((pat_missing_fault(),))
        faulted = [spec_filter.apply(i, p) for i, p in enumerate(baseline)]
        document = json.loads(spec_filter.mutation_log().decode("utf-8"))
        record = document["mutations"][0]
        index = record["packet_index"]
        assert record["after"]["slot_sha256"] == hashlib.sha256(
            faulted[index].to_bytes()
        ).hexdigest()


class TestFactory:
    def test_factory_builds_a_protocol_conformant_filter(self, baseline) -> None:
        factory = build_semantic_filter_factory()
        spec_filter = factory((pat_missing_fault(),), _minimal_config())
        assert isinstance(spec_filter, SemanticFaultFilter)
        for index, packet in enumerate(baseline):
            result = spec_filter.apply(index, packet)
            assert result.to_bytes() == spec_filter.apply(index, packet).to_bytes()

    def test_factory_accepts_optional_run_id(self, baseline) -> None:
        spec_filter = create_fault_filter(
            (pat_missing_fault(),), _minimal_config(), run_id="run-9"
        )
        for index, packet in enumerate(baseline):
            spec_filter.apply(index, packet)
        document = json.loads(spec_filter.mutation_log().decode("utf-8"))
        assert document["run_id"] == "run-9"

    def test_filter_sees_the_target_pid_slots(self, baseline) -> None:
        spec_filter = create_fault_filter(
            (cc_discontinuity_fault(),), _minimal_config()
        )
        faulted = [spec_filter.apply(i, p) for i, p in enumerate(baseline)]
        changed = [
            i
            for i, (before, after) in enumerate(zip(baseline, faulted))
            if before.to_bytes() != after.to_bytes()
        ]
        assert changed and changed[0] == 50
        assert all(baseline[i].pid == GOLDEN_ES1_PID for i in changed)
