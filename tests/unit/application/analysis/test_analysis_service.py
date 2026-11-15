"""The analysis-bridge service — facts normalized into ``ts.*``
observation events (ticket #58, 裁定 A + 裁定 B in-process anchor).

The service is the orchestration half of the bridge: artifact bytes →
parser facts → SPEC-301 envelopes → the SPEC-300 §12 producer face.
Unit layer: pure doubles only (no filesystem, no gateway). The payload
key contract is the one registered in
``tests/_support/diagnosis_fixtures.py`` (the diagnosis-side fixture
contract): every rule-relevant record carries the evidence triple
``artifact_id`` / ``pid`` / ``packet_index``; the PMT-PID-MISMATCH
contradiction pair (``expected_program_map_pid`` /
``actual_program_map_pid``) appears ONLY on contradicting PAT records —
so the builtin rules fire on symptoms and never on clean streams
(proven here against the real four Python-form rules,
``domain.diagnosis.rules.declarations``).
"""

from __future__ import annotations

from typing import Any

import pytest

from domain.diagnosis.engine import ObservationRecord
from domain.diagnosis.rules.declarations import python_builtin_rules
from domain.observation import parse_envelope
from faults.definition import FaultActivation, FaultDefinition
from faults.factory import create_fault_filter
from ts.packet import TSPacket

from application.analysis.service import (
    CONFIDENCE,
    PRODUCER_ID,
    SOURCE,
    AnalysisService,
)
from tests._support.fault_lab_materials import (
    FAULT_LAB_NODE_ID,
    generate_golden_geometry_bytes,
    golden_geometry_config,
)

pytestmark = pytest.mark.unit

SESSION_ID = "sess-analysis"
RUN_ID = "run-analysis"
ARTIFACT_ID = "3f2b4a1c-0000-4000-8000-00000000ab01"
DOMAIN = f"sim:{SESSION_ID}"


class RecordingPublisher:
    """SPEC-300 §12 producer-face double: records published documents."""

    def __init__(self) -> None:
        self.documents: list[dict[str, Any]] = []

    def publish(self, document: Any) -> Any:
        self.documents.append(document)
        return document


class InlineStore:
    """ArtifactStore read-face double over in-memory bytes."""

    def __init__(self, contents: dict[str, bytes]) -> None:
        self._contents = contents

    def read_by_artifact(self, artifact_id: str) -> bytes:
        return self._contents[artifact_id]


def _fault(
    fault_type: str, pid: int, parameters: dict, packet_index: int
) -> FaultDefinition:
    return FaultDefinition(
        fault_id="fd000000-0000-4000-8000-000000000001",
        fault_type=fault_type,
        target_id=f"{FAULT_LAB_NODE_ID}:pid:0x{pid:04x}",
        parameters=parameters,
        activation=FaultActivation(
            kind="packet_index", packet_index=packet_index
        ),
        expected_observations=("ts.psi_section_observed",),
    )


def _faulted_bytes(fault: FaultDefinition) -> bytes:
    config = golden_geometry_config()
    baseline = generate_golden_geometry_bytes()
    packets = [
        TSPacket.from_bytes(baseline[offset : offset + 188])
        for offset in range(0, len(baseline), 188)
    ]
    filt = create_fault_filter((fault,), config, run_id=RUN_ID)
    return b"".join(
        filt.apply(index, packet).to_bytes()
        for index, packet in enumerate(packets)
    )


def _service(publisher: RecordingPublisher, store: InlineStore) -> AnalysisService:
    return AnalysisService(
        publisher,
        store=store,
        now_wall_ns=lambda: 1_000_000_000,  # deterministic observed axis
    )


def _records_of(published: list[dict[str, Any]]) -> list[ObservationRecord]:
    """Journal-shaped records for the rule interlock (the engine's view)."""
    records = []
    for seq, document in enumerate(published, start=1):
        correlation = document["correlation"]
        records.append(
            ObservationRecord(
                journal_seq=seq,
                event_type=document["event_type"],
                event_id=str(document["event_id"]),
                payload=dict(document["payload"]),
                node_id=correlation.get("node_id"),
                pid=correlation.get("pid"),
            )
        )
    return records


# --- envelope conformance --------------------------------------------------------


class TestEnvelopeConformance:
    def test_every_published_document_passes_the_envelope_schema(self):
        publisher = RecordingPublisher()
        store = InlineStore({ARTIFACT_ID: generate_golden_geometry_bytes()})
        _service(publisher, store).analyze_artifact(
            session_id=SESSION_ID,
            run_id=RUN_ID,
            artifact_id=ARTIFACT_ID,
            config=golden_geometry_config(),
            node_id=FAULT_LAB_NODE_ID,
        )
        assert publisher.documents
        for document in publisher.documents:
            envelope = parse_envelope(document)  # raises on violation
            assert envelope.producer.producer_id == PRODUCER_ID
            assert envelope.scope.session_id == SESSION_ID
            assert envelope.scope.run_id == RUN_ID
            assert envelope.scope.tenant_id == "local"

    def test_observation_axes_declare_internal_parser_provenance(self):
        publisher = RecordingPublisher()
        store = InlineStore({ARTIFACT_ID: generate_golden_geometry_bytes()})
        _service(publisher, store).analyze_artifact(
            session_id=SESSION_ID,
            run_id=RUN_ID,
            artifact_id=ARTIFACT_ID,
            config=golden_geometry_config(),
        )
        for document in publisher.documents:
            assert document["payload"]["source"] == SOURCE
            assert document["payload"]["confidence"] == CONFIDENCE

    def test_event_types_are_registered_ts_family_members(self):
        from domain.observation.registry import TS_EVENT_TYPES, validate_event_type

        publisher = RecordingPublisher()
        store = InlineStore({ARTIFACT_ID: generate_golden_geometry_bytes()})
        _service(publisher, store).analyze_artifact(
            session_id=SESSION_ID,
            run_id=RUN_ID,
            artifact_id=ARTIFACT_ID,
            config=golden_geometry_config(),
        )
        for document in publisher.documents:
            validate_event_type(document["event_type"])
            assert document["event_type"] in TS_EVENT_TYPES

    def test_virtual_time_source_anchors_to_the_shared_frame(self):
        publisher = RecordingPublisher()
        store = InlineStore({ARTIFACT_ID: generate_golden_geometry_bytes()})
        _service(publisher, store).analyze_artifact(
            session_id=SESSION_ID,
            run_id=RUN_ID,
            artifact_id=ARTIFACT_ID,
            config=golden_geometry_config(),
        )
        slot_ns = 500_000  # frozen geometry: 0.5 ms slots
        for document in publisher.documents:
            source = document["time"]["source"]
            assert source["clock_domain"] == DOMAIN
            assert source["clock_epoch"] == 0
            assert source["value_ns"] % slot_ns == 0
        observed = publisher.documents[0]["time"]["observed"]
        assert observed["clock_domain"] == "wall:utc"
        assert observed["value_ns"] == 1_000_000_000


# --- payload key contract -------------------------------------------------------


class TestPayloadKeyContract:
    def _analyze(self, ts_bytes: bytes) -> RecordingPublisher:
        publisher = RecordingPublisher()
        store = InlineStore({ARTIFACT_ID: ts_bytes})
        _service(publisher, store).analyze_artifact(
            session_id=SESSION_ID,
            run_id=RUN_ID,
            artifact_id=ARTIFACT_ID,
            config=golden_geometry_config(),
            node_id=FAULT_LAB_NODE_ID,
        )
        return publisher

    def test_clean_pat_records_carry_declaration_without_contradiction(self):
        publisher = self._analyze(generate_golden_geometry_bytes())
        pat = [
            d
            for d in publisher.documents
            if d["payload"].get("section") == "PAT"
            and d["payload"].get("present") is True
        ]
        assert len(pat) == 3
        for document in pat:
            payload = document["payload"]
            assert payload["actual_program_map_pid"] == 4096
            assert "expected_program_map_pid" not in payload
            # The evidence triple (diagnosis-side payload contract).
            assert payload["artifact_id"] == ARTIFACT_ID
            assert payload["pid"] == 0
            assert isinstance(payload["packet_index"], int)
        assert pat[0]["correlation"]["node_id"] == FAULT_LAB_NODE_ID
        assert pat[0]["correlation"]["pid"] == 0

    def test_pat_missing_records_declare_absence_with_the_triple(self):
        ts_bytes = _faulted_bytes(_fault("PAT_MISSING", 0x0000, {}, 202))
        publisher = self._analyze(ts_bytes)
        missing = [
            d
            for d in publisher.documents
            if d["payload"].get("present") is False
        ]
        assert [d["payload"]["packet_index"] for d in missing] == [202, 404]
        for document in missing:
            payload = document["payload"]
            assert payload["section"] == "PAT"
            assert payload["pid"] == 0
            assert payload["artifact_id"] == ARTIFACT_ID

    def test_crc_fault_records_declare_the_corruption_instances(self):
        ts_bytes = _faulted_bytes(
            _fault(
                "PMT_INVALID_CRC", 0x1000,
                {"mode": "persistent", "corruption": "invert"}, 1,
            )
        )
        publisher = self._analyze(ts_bytes)
        bad = [
            d
            for d in publisher.documents
            if d["payload"].get("crc_valid") is False
        ]
        assert [d["payload"]["packet_index"] for d in bad] == [1, 206, 412]
        for document in bad:
            payload = document["payload"]
            assert payload["section"] == "PMT"
            assert payload["present"] is True
            assert payload["pid"] == 4096
            assert payload["artifact_id"] == ARTIFACT_ID

    def test_contradiction_pair_appears_only_on_repointed_pat(self):
        ts_bytes = _faulted_bytes(
            _fault("PMT_PID_MISMATCH", 0x0000, {"wrong_pmt_pid": 4100}, 0)
        )
        publisher = self._analyze(ts_bytes)
        contradictions = [
            d
            for d in publisher.documents
            if "expected_program_map_pid" in d["payload"]
        ]
        assert [d["payload"]["packet_index"] for d in contradictions] == [
            0, 202, 404,
        ]
        for document in contradictions:
            payload = document["payload"]
            assert payload["actual_program_map_pid"] == 4100
            assert payload["expected_program_map_pid"] == 4096
        # No OTHER document carries either key.
        others = [
            d
            for d in publisher.documents
            if d not in contradictions
            and (
                "actual_program_map_pid" in d["payload"]
                or "expected_program_map_pid" in d["payload"]
            )
        ]
        assert others == []

    def test_cc_error_record_carries_the_relative_offset_detail(self):
        ts_bytes = _faulted_bytes(
            _fault("CC_DISCONTINUITY", 0x0100, {"delta": 3}, 30)
        )
        publisher = self._analyze(ts_bytes)
        errors = [
            d
            for d in publisher.documents
            if d["event_type"] == "ts.continuity_error"
        ]
        assert len(errors) == 1
        payload = errors[0]["payload"]
        assert payload["pid"] == 256
        assert payload["packet_index"] == 50
        assert payload["expected_cc"] == 1
        assert payload["actual_cc"] == 4
        assert payload["delta"] == 3
        assert payload["artifact_id"] == ARTIFACT_ID

    def test_batch_record_reports_coverage(self):
        publisher = self._analyze(generate_golden_geometry_bytes())
        batches = [
            d
            for d in publisher.documents
            if d["event_type"] == "ts.packet_batch_observed"
        ]
        assert len(batches) == 1
        payload = batches[0]["payload"]
        assert payload["packet_count"] == 600
        assert payload["byte_count"] == 600 * 188
        assert payload["duration_ns"] > 0
        assert payload["continuity_error_count"] == 0
        assert payload["artifact_id"] == ARTIFACT_ID


# --- rule interlock over the bridge payloads -------------------------------------


class TestRuleInterlockOverBridgePayloads:
    """The real four rules must fire on symptom payloads and NEVER on
    the clean stream (the false-fire guard of the payload contract)."""

    RULES = python_builtin_rules()

    def _codes(self, records):
        found = set()
        for rule in self.RULES:
            if rule.matches(records):
                found.add(rule.code)
        return found

    def test_clean_stream_fires_no_rule(self):
        publisher = RecordingPublisher()
        store = InlineStore({ARTIFACT_ID: generate_golden_geometry_bytes()})
        _service(publisher, store).analyze_artifact(
            session_id=SESSION_ID,
            run_id=RUN_ID,
            artifact_id=ARTIFACT_ID,
            config=golden_geometry_config(),
            node_id=FAULT_LAB_NODE_ID,
        )
        assert self._codes(_records_of(publisher.documents)) == set()

    def test_each_faulted_stream_fires_exactly_its_pairing_rule(self):
        pairing = {
            "DIAG_PAT_MISSING": _fault("PAT_MISSING", 0x0000, {}, 202),
            "DIAG_PMT_CRC_BAD": _fault(
                "PMT_INVALID_CRC", 0x1000,
                {"mode": "persistent", "corruption": "invert"}, 1,
            ),
            "DIAG_CC_DISCONTINUITY": _fault(
                "CC_DISCONTINUITY", 0x0100, {"delta": 3}, 30
            ),
            "DIAG_PMT_PID_MISMATCH": _fault(
                "PMT_PID_MISMATCH", 0x0000, {"wrong_pmt_pid": 4100}, 0
            ),
        }
        for expected_code, fault in pairing.items():
            publisher = RecordingPublisher()
            store = InlineStore({ARTIFACT_ID: _faulted_bytes(fault)})
            _service(publisher, store).analyze_artifact(
                session_id=SESSION_ID,
                run_id=RUN_ID,
                artifact_id=ARTIFACT_ID,
                config=golden_geometry_config(),
                node_id=FAULT_LAB_NODE_ID,
            )
            fired = self._codes(_records_of(publisher.documents))
            assert fired == {expected_code}, (fault.fault_type, fired)


# --- the report face --------------------------------------------------------------


class TestAnalysisReport:
    def test_report_counts_published_events_per_type(self):
        publisher = RecordingPublisher()
        store = InlineStore({ARTIFACT_ID: generate_golden_geometry_bytes()})
        report = _service(publisher, store).analyze_artifact(
            session_id=SESSION_ID,
            run_id=RUN_ID,
            artifact_id=ARTIFACT_ID,
            config=golden_geometry_config(),
        )
        assert report.session_id == SESSION_ID
        assert report.run_id == RUN_ID
        assert report.artifact_id == ARTIFACT_ID
        assert report.packet_count == 600
        expected = {"ts.psi_section_observed": 6, "ts.packet_batch_observed": 1}
        assert dict(report.event_counts) == expected
        assert sum(report.event_counts.values()) == len(publisher.documents)

    def test_unknown_artifact_is_a_key_error_from_the_store_face(self):
        store = InlineStore({})
        with pytest.raises(KeyError):
            _service(RecordingPublisher(), store).analyze_artifact(
                session_id=SESSION_ID,
                run_id=RUN_ID,
                artifact_id="missing",
                config=golden_geometry_config(),
            )
