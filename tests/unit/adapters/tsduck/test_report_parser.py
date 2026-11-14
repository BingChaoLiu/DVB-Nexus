"""Report parser tests (SPEC-308 §7/§8/§10, REQ-TSK-308-003/004).

Four gate states of SPEC-308 §10 (legal JSON / empty bytes / zero services /
non-JSON output) plus normalization round-trip and the observation marking
duties (source=tsduck, confidence=parsed, unmapped findings never emitted).
Synthetic documents here are anchored to the measured tsanalyze JSON shape
(docs/research/tsduck-env.md §4.2, ticket #3) — ordinary test text, not TS
byte streams (禁手拼字节 rule governs TS byte payloads only).
"""

from __future__ import annotations

import json
from dataclasses import fields as dataclass_fields

import pytest
from domain.observation import ConfidenceKind, ObservationSource

from adapters.tsduck.errors import TSDuckJsonGateError
from adapters.tsduck.report_parser import (
    REGISTERED_EVENT_TYPES,
    AnalysisReport,
    parse_report,
    report_findings,
)


def make_document(
    *,
    ts_bytes: int = 188_000,
    packets_total: int = 1_000,
    services_total: int = 1,
    pid_discontinuities: int = 0,
    pid_duplicated: int = 0,
) -> dict:
    """A tsanalyze --json document with the measured top-level shape
    (tsduck-env.md §4.2: pids / services / tables / time / ts)."""
    return {
        "pids": [
            {
                "id": 0,
                "description": "PAT",
                "global": True,
                "is-scrambled": False,
                "services": [1],
                "packets": {
                    "total": 10,
                    "clear": 10,
                    "scrambled": 0,
                    "discontinuities": pid_discontinuities,
                    "duplicated": pid_duplicated,
                    "pcr": 0,
                    "pts": 0,
                },
            },
            {
                "id": 4096,
                "description": "PMT",
                "pmt": True,
                "is-scrambled": False,
                "services": [1],
                "packets": {
                    "total": 10,
                    "clear": 10,
                    "scrambled": 0,
                    "discontinuities": 0,
                    "duplicated": 0,
                    "pcr": 0,
                    "pts": 0,
                },
            },
        ],
        "services": [
            {
                "id": 1,
                "tsid": 1,
                "pmt-pid": 4096,
                "pcr-pid": 256,
                "name": "(unknown)",
                # Measured shape (3.40-4165 real output): services[].packets
                # is a plain int, unlike pids[].packets (an object).
                "packets": 900,
                "components": {"total": 2, "clear": 2, "scrambled": 0},
            }
        ],
        "tables": [
            {
                "pid": 0,
                "tid": 0,
                "tid-ext": 1,
                "tables": 5,
                "sections": 5,
                "versions": [0],
            }
        ],
        "time": {"utc": {"system": {"first": {"seconds-since-2000": 0}}}},
        "ts": {
            "bitrate": 3_008_000,
            "bytes": ts_bytes,
            "packets": {
                "total": packets_total,
                "invalid-syncs": 0,
                "transport-errors": 0,
                "suspect-ignored": 0,
            },
            "pids": {
                "total": 5,
                "clear": 5,
                "scrambled": 0,
                "pcr": 1,
                "unreferenced": 1,
            },
            "services": {"total": services_total, "clear": services_total, "scrambled": 0},
            "id": 1,
        },
    }


VALID_DOCUMENT = make_document()


class TestJsonContentGate:
    """SPEC-308 §7: exit 0 ≠ valid — the gate is the validity arbiter (#3)."""

    def test_gate_constants_match_ticket_3_discipline(self):
        from adapters.tsduck.report_parser import (
            GATE_SERVICES_TOTAL_AT_LEAST_ONE,
            GATE_TS_BYTES_POSITIVE,
        )

        assert GATE_TS_BYTES_POSITIVE == "ts_bytes_positive"
        assert GATE_SERVICES_TOTAL_AT_LEAST_ONE == "services_total_at_least_one"

    def test_legal_json_passes(self):
        report = parse_report(json.dumps(VALID_DOCUMENT))
        assert report.ts.bytes == 188_000
        assert report.ts.services_total == 1

    def test_bytes_input_accepted(self):
        report = parse_report(json.dumps(VALID_DOCUMENT).encode("utf-8"))
        assert report.ts.bytes == 188_000

    def test_empty_bytes_fails_the_gate(self):
        document = make_document(ts_bytes=0, packets_total=0, services_total=0)
        with pytest.raises(TSDuckJsonGateError) as excinfo:
            parse_report(json.dumps(document))
        assert excinfo.value.code == "TSDUCK_JSON_GATE_FAILED"
        assert "ts_bytes_positive" in str(excinfo.value)

    def test_zero_services_fail_the_gate(self):
        document = make_document(services_total=0)
        with pytest.raises(TSDuckJsonGateError) as excinfo:
            parse_report(json.dumps(document))
        assert "services_total_at_least_one" in str(excinfo.value)

    def test_non_json_output_fails_the_gate(self):
        with pytest.raises(TSDuckJsonGateError):
            parse_report("this is not json")

    def test_missing_ts_section_fails_the_gate(self):
        with pytest.raises(TSDuckJsonGateError):
            parse_report(json.dumps({"pids": [], "services": []}))

    def test_missing_bytes_key_fails_the_gate(self):
        document = make_document()
        del document["ts"]["bytes"]
        with pytest.raises(TSDuckJsonGateError):
            parse_report(json.dumps(document))

    def test_gate_failure_detail_carries_exit_code_when_given(self):
        with pytest.raises(TSDuckJsonGateError) as excinfo:
            parse_report("not json", exit_code=0)
        # Ticket #3: even the measured "exit 0" case names its exit code in
        # the diagnostic — the gate, not the code, decided the failure.
        assert "exit_code=0" in str(excinfo.value)

    def test_gate_failure_detail_hides_nothing_on_nonzero_exit(self):
        with pytest.raises(TSDuckJsonGateError) as excinfo:
            parse_report("", exit_code=1)
        assert "exit_code=1" in str(excinfo.value)


class TestNormalization:
    def test_ts_summary_normalized_snake_case(self):
        report = parse_report(json.dumps(VALID_DOCUMENT))
        assert report.ts.bytes == 188_000
        assert report.ts.packets_total == 1_000
        assert report.ts.invalid_syncs == 0
        assert report.ts.transport_errors == 0
        assert report.ts.services_total == 1
        assert report.ts.pids_total == 5
        assert report.ts.transport_stream_id == 1
        assert report.ts.bitrate == 3_008_000

    def test_pids_services_tables_normalized(self):
        report = parse_report(json.dumps(VALID_DOCUMENT))
        assert [p.pid for p in report.pids] == [0, 4096]
        assert report.pids[0].description == "PAT"
        assert report.pids[0].packets_total == 10
        service = report.services[0]
        assert service.service_id == 1
        assert service.pmt_pid == 4096
        assert service.pcr_pid == 256
        table = report.tables[0]
        assert table.pid == 0
        assert table.section_count == 5

    def test_service_packets_count_tolerates_both_measured_shapes(self):
        """§12 defense: services[].packets is an int on 3.40-4165 but the
        nested {total: …} object shape is also normalized."""
        document = make_document()
        document["services"][0]["packets"] = {"total": 900}  # alternate shape
        report = parse_report(json.dumps(document))
        assert report.services[0].packets_total == 900

    def test_source_document_preserved_verbatim(self):
        report = parse_report(json.dumps(VALID_DOCUMENT))
        assert report.source_document == VALID_DOCUMENT

    def test_defensive_against_absent_optional_fields(self):
        """Schema drift defense (SPEC-308 §12): absent optional keys default,
        the gate still governs, raw document stays untouched."""
        document = make_document()
        document["ts"].pop("id")  # transport_stream_id absent
        document["ts"].pop("bitrate")
        document["pids"][0]["packets"].pop("duplicated")
        report = parse_report(json.dumps(document))
        assert report.ts.transport_stream_id is None
        assert report.ts.bitrate is None
        assert report.pids[0].duplicated == 0

    def test_round_trip_normalized_form(self):
        """SPEC-308 §10 round-trip: document → report → normalized dict →
        report is lossless on the normalized fields."""
        report = parse_report(json.dumps(VALID_DOCUMENT))
        reparsed = AnalysisReport.from_document(report.to_dict())
        assert reparsed == report
        # source_document is provenance, not part of normalized identity.
        assert reparsed.source_document == report.to_dict()


class TestObservationMarking:
    """REQ-TSK-308-004: source=tsduck, confidence=parsed; only registered
    ts.* event types (SPEC-301 §4 family) are mapped; unmapped findings stay
    in the report artifact."""

    def test_every_finding_carries_tsduck_parsed_marking(self):
        document = make_document(pid_discontinuities=2)
        report = parse_report(json.dumps(document))
        findings = report_findings(report)
        assert findings, "a discontinuity count must surface as a finding"
        for finding in findings:
            assert finding.source is ObservationSource.TSDUCK
            assert finding.confidence is ConfidenceKind.PARSED

    def test_continuity_error_mapped_with_pid(self):
        document = make_document(pid_discontinuities=2)
        report = parse_report(json.dumps(document))
        findings = report_findings(report)
        continuity = [f for f in findings if f.event_type == "ts.continuity_error"]
        assert len(continuity) == 1
        assert continuity[0].pid == 0
        assert continuity[0].value["count"] == 2

    def test_unmapped_anomalies_never_become_findings(self):
        """duplicates / invalid-syncs have no registered mapping (SPEC-308 §8:
        未映射发现只留在 report artifact，不造新事件类型)."""
        document = make_document(pid_duplicated=7)
        document["ts"]["packets"]["invalid-syncs"] = 3
        report = parse_report(json.dumps(document))
        assert report.pids[0].duplicated == 7  # visible in the report
        assert report.ts.invalid_syncs == 3
        assert report_findings(report) == ()

    def test_clean_report_yields_no_findings(self):
        report = parse_report(json.dumps(VALID_DOCUMENT))
        assert report_findings(report) == ()

    def test_mapped_event_types_are_within_spec_301_registered_family(self):
        registered = {
            "ts.packet_batch_observed",
            "ts.continuity_error",
            "ts.pcr_jitter_observed",
            "ts.psi_section_observed",
            "ts.service_state_changed",
        }
        assert REGISTERED_EVENT_TYPES <= registered

    def test_finding_marking_enums_are_the_domain_vocabulary(self):
        """The marking types ARE domain.observation's (no parallel copies)."""
        from adapters.tsduck.report_parser import TsduckFinding

        marking_fields = {f.name for f in dataclass_fields(TsduckFinding)}
        assert {"event_type", "source", "confidence", "pid", "value"} <= marking_fields
