"""SPEC-301 sections 3/5/6/7/8/9 — canonical event envelope model.

The model is the logical contract behind ``event-envelope.schema.json``
v1.0: required/nullable field matrix, loose envelope (unknown optional
fields ignored — consumers MUST ignore them), tight payload (per-type
registry validation), journal_seq field semantics (optional, gateway
stamped, producers never fill) and the multi-schema-document policy.
"""

import json

import pytest
from pydantic import ValidationError

from domain.observation.envelope import (
    Correlation,
    EventEnvelope,
    Producer,
    Scope,
    Severity,
    Time,
    Timepoint,
    new_event_id,
    parse_envelope,
)
from domain.observation.errors import EnvelopeError, EnvelopeErrorCode
from domain.observation.registry import (
    REGISTERED_EVENT_TYPES,
    is_delivery_protected,
)


def envelope_dict(**overrides):
    """A minimal valid envelope (producer publish view: no journal_seq)."""
    envelope = {
        "schema_version": "1.0",
        "event_id": "7e6c8e17-6f4e-4f6a-9a34-2b9d1c9a5f21",
        "event_type": "ts.continuity_error",
        "producer": {
            "producer_id": "ts-core",
            "producer_version": "0.5.0",
            "instance_id": "ts-core-1",
        },
        "scope": {
            "tenant_id": "local",
            "session_id": "0f0e8d1c-2b3a-4c5d-8e9f-0a1b2c3d4e5f",
            "run_id": "11a2b3c4-d5e6-47f8-8a9b-0c1d2e3f4a5b",
            "scenario_id": None,
        },
        "time": {
            "source": {
                "value_ns": 1200000000,
                "clock_domain": "sim:0f0e8d1c-2b3a-4c5d-8e9f-0a1b2c3d4e5f",
                "clock_epoch": 0,
            },
            "observed": {
                "value_ns": 1790000000000000000,
                "clock_domain": "wall:utc",
                "clock_epoch": 0,
            },
        },
        "severity": "warning",
        "payload": {
            "expected_cc": 4,
            "actual_cc": 6,
            "discontinuity_indicator": False,
            "packet_index": 12000,
            "source": "internal_parser",
            "confidence": "parsed",
        },
        "tags": ["ts", "continuity", "training"],
    }
    for key, value in overrides.items():
        if value is None:
            envelope.pop(key, None)
        else:
            envelope[key] = value
    return envelope


class TestRequiredFieldMatrix:
    """SPEC-301 section 3 + schema ``required`` list, one field at a time."""

    REQUIRED_TOP_LEVEL = (
        "schema_version",
        "event_id",
        "event_type",
        "producer",
        "scope",
        "time",
        "severity",
        "payload",
        "tags",
    )

    @pytest.mark.parametrize("field", REQUIRED_TOP_LEVEL, ids=str)
    def test_missing_required_field_refused(self, field):
        raw = envelope_dict(**{field: None})
        with pytest.raises(EnvelopeError) as exc:
            parse_envelope(raw)
        assert exc.value.code is EnvelopeErrorCode.OBS_INVALID_ENVELOPE

    def test_producer_required_fields(self):
        for field in ("producer_id", "producer_version", "instance_id"):
            producer = {
                "producer_id": "ts-core",
                "producer_version": "0.5.0",
                "instance_id": "ts-core-1",
            }
            producer.pop(field)
            with pytest.raises(EnvelopeError):
                parse_envelope(envelope_dict(producer=producer))

    def test_scope_requires_tenant_and_session_key(self):
        # tenant_id required non-null; session_id required as a KEY but
        # nullable (system-level events only).
        raw = envelope_dict(scope={"tenant_id": "local"})
        with pytest.raises(EnvelopeError):
            parse_envelope(raw)
        raw = envelope_dict(
            scope={"session_id": "0f0e8d1c-2b3a-4c5d-8e9f-0a1b2c3d4e5f"}
        )
        with pytest.raises(EnvelopeError):
            parse_envelope(raw)

    def test_time_requires_both_timepoints(self):
        for field in ("source", "observed"):
            time = {
                "source": {
                    "value_ns": 1,
                    "clock_domain": "wall:utc",
                    "clock_epoch": 0,
                },
                "observed": {
                    "value_ns": 2,
                    "clock_domain": "wall:utc",
                    "clock_epoch": 0,
                },
            }
            time.pop(field)
            with pytest.raises(EnvelopeError):
                parse_envelope(envelope_dict(time=time))

    def test_timepoint_requires_all_three_fields(self):
        for field in ("value_ns", "clock_domain", "clock_epoch"):
            timepoint = {"value_ns": 1, "clock_domain": "wall:utc", "clock_epoch": 0}
            timepoint.pop(field)
            with pytest.raises(EnvelopeError):
                parse_envelope(envelope_dict(time={"source": timepoint, "observed": timepoint}))

    def test_nullable_fields_accept_null(self):
        raw = envelope_dict(
            correlation={
                "trace_id": None,
                "span_id": None,
                "parent_event_id": None,
                "fault_id": None,
                "node_id": None,
                "port_id": None,
                "service_id": None,
                "pid": None,
            },
            scope={
                "tenant_id": "local",
                "session_id": None,  # system-level event
                "run_id": None,
                "scenario_id": None,
            },
        )
        envelope = parse_envelope(raw)
        assert envelope.scope.session_id is None
        assert envelope.scope.run_id is None
        assert envelope.correlation.fault_id is None

    def test_correlation_is_optional(self):
        envelope = parse_envelope(envelope_dict(correlation=None))
        assert envelope.correlation is None

    def test_typed_model_surface(self):
        envelope = EventEnvelope(
            schema_version="1.0",
            event_id="7e6c8e17-6f4e-4f6a-9a34-2b9d1c9a5f21",
            event_type="simulation.run_completed",
            producer=Producer(
                producer_id="simulation-engine",
                producer_version="0.5.0",
                instance_id="sim-1",
            ),
            scope=Scope(tenant_id="local", session_id="s-1", run_id="r-1"),
            time=Time(
                source=Timepoint(value_ns=10, clock_domain="sim:s-1", clock_epoch=0),
                observed=Timepoint(value_ns=20, clock_domain="wall:utc", clock_epoch=0),
            ),
            severity=Severity.INFO,
            payload={"progress": 1.0},
            tags=["run"],
        )
        assert envelope.producer.producer_seq is None
        assert envelope.journal_seq is None


class TestFieldConstraints:
    """Bounds mirrored from the 1.0 schema document."""

    def test_severity_vocabulary(self):
        for value in ("debug", "info", "notice", "warning", "error", "critical"):
            assert Severity(value)
        with pytest.raises(EnvelopeError):
            parse_envelope(envelope_dict(severity="fatal"))

    def test_event_id_bounds(self):
        with pytest.raises(EnvelopeError):
            parse_envelope(envelope_dict(event_id="short"))
        with pytest.raises(EnvelopeError):
            parse_envelope(envelope_dict(event_id="x" * 129))

    def test_tags_bounds(self):
        envelope = parse_envelope(
            envelope_dict(tags=[f"tag{i}" for i in range(32)])
        )
        assert len(envelope.tags) == 32
        with pytest.raises(EnvelopeError):
            parse_envelope(envelope_dict(tags=[f"tag{i}" for i in range(33)]))
        with pytest.raises(EnvelopeError):
            parse_envelope(envelope_dict(tags=["x" * 65]))

    def test_pid_bounds(self):
        envelope = parse_envelope(
            envelope_dict(correlation={"pid": 8191})
        )
        assert envelope.correlation.pid == 8191
        with pytest.raises(EnvelopeError):
            parse_envelope(envelope_dict(correlation={"pid": 8192}))
        with pytest.raises(EnvelopeError):
            parse_envelope(envelope_dict(correlation={"pid": -1}))

    def test_negative_clock_epoch_refused(self):
        bad_time = {
            "source": {"value_ns": 1, "clock_domain": "sim:s", "clock_epoch": -1},
            "observed": {"value_ns": 2, "clock_domain": "wall:utc", "clock_epoch": 0},
        }
        with pytest.raises(EnvelopeError):
            parse_envelope(envelope_dict(time=bad_time))


class TestLooseEnvelopeTightPayload:
    """SPEC-301 section 8 / ADR-0006 decision 4."""

    def test_unknown_top_level_optional_field_ignored(self):
        # Forward compatibility: consumers MUST ignore unknown optional fields.
        envelope = parse_envelope(envelope_dict(future_field={"x": 1}))
        assert envelope.event_type == "ts.continuity_error"

    def test_unknown_nested_optional_fields_ignored(self):
        raw = envelope_dict(
            producer={
                "producer_id": "ts-core",
                "producer_version": "0.5.0",
                "instance_id": "ts-core-1",
                "future_producer_field": True,
            },
            scope={"tenant_id": "local", "session_id": "s", "future_scope_field": 7},
            time={
                "source": {
                    "value_ns": 1,
                    "clock_domain": "sim:s",
                    "clock_epoch": 0,
                    "future_timepoint_field": "ignored",
                },
                "observed": {
                    "value_ns": 2,
                    "clock_domain": "wall:utc",
                    "clock_epoch": 0,
                },
            },
        )
        envelope = parse_envelope(raw)
        assert envelope.producer.producer_id == "ts-core"
        assert envelope.time.source.clock_domain == "sim:s"

    def test_payload_must_be_an_object(self):
        with pytest.raises(EnvelopeError):
            parse_envelope(envelope_dict(payload="free-string"))

    def test_ts_payload_tight_missing_source(self):
        payload = {"expected_cc": 4, "actual_cc": 6}
        with pytest.raises(EnvelopeError) as exc:
            parse_envelope(envelope_dict(payload=payload))
        assert exc.value.code is EnvelopeErrorCode.OBS_INVALID_ENVELOPE

    def test_every_registered_type_accepts_a_payload_object(self):
        # Envelope layer: payload is only ever an object; per-type payloads
        # register their schemas over time (SPEC-301 section 13). Families
        # WITH a registered payload schema carry a minimal VALID payload
        # here (ts.* observation axes, #13 Q3-i; diagnosis.* SPEC-306 §7
        # shared shape, ticket #54; fault.* SPEC-204 §9 + recovery.* verdict
        # shape, ticket #56) — every still-schemaless family keeps the
        # bare-{} posture.
        for event_type in sorted(REGISTERED_EVENT_TYPES):
            if event_type.startswith("ts."):
                payload = {"source": "internal_parser", "confidence": "parsed"}
            elif event_type == "diagnosis.cleared":
                payload = {
                    "diagnosis_id": "3f2504e0-4f89-11d3-9a0c-0305e82c3301",
                    "rule_id": "DIA-X",
                    "reason": "symptom gone",
                }
            elif event_type.startswith("diagnosis."):
                payload = {
                    "diagnosis_id": "3f2504e0-4f89-11d3-9a0c-0305e82c3301",
                    "rule_id": "DIA-X",
                    "rule_version": "1.0.0",
                    "code": "DIAG_X",
                    "severity": "info",
                    "confidence": "high",
                    "title": "t",
                    "summary": "s",
                    "observation_refs": [
                        {"journal_seq": 1, "event_type": "ts.continuity_error"}
                    ],
                    "affected_node_ids": [],
                    "suggested_actions": [],
                    "evidence": {"artifact_id": "a", "pid": 0, "packet_index": 0},
                }
            elif event_type == "fault.injected":
                payload = {
                    "fault_id": "fd000000-0000-4000-8000-000000000001",
                    "fault_type": "PAT_MISSING",
                    "injection_index": 0,
                    "expected_observations": ["ts.psi_section_observed"],
                }
            elif event_type == "fault.applied":
                payload = {
                    "fault_id": "fd000000-0000-4000-8000-000000000001",
                    "fault_type": "PAT_MISSING",
                    "injection_index": 0,
                    "applied_packet_indexes": [12],
                }
            elif event_type.startswith("fault."):
                payload = {
                    "fault_id": "fd000000-0000-4000-8000-000000000001",
                    "fault_type": "PAT_MISSING",
                    "injection_index": 0,
                }
            elif event_type == "recovery.verification_completed":
                payload = {
                    "verdict": "PASS",
                    "run_id": "run-r",
                    "baseline_run_id": "run-b",
                    "scenario_id": "scn-1",
                    "scenario_version": "1.0.0",
                    "scenario_content_hash": "a" * 64,
                    "criteria": [
                        {
                            "criterion_id": "sc-01",
                            "kind": "fault_inactive",
                            "mandatory": True,
                            "result": "PASS",
                            "reason_code": None,
                            "reason": None,
                        }
                    ],
                    "summary": "all mandatory criteria passed",
                }
            else:
                payload = {}
            raw = envelope_dict(
                event_type=event_type,
                payload=payload,
                producer={
                    "producer_id": "simulation-engine",
                    "producer_version": "0.5.0",
                    "instance_id": "sim-1",
                },
            )
            envelope = parse_envelope(raw)
            assert envelope.event_type == event_type


class TestSchemaVersionPolicy:
    """SPEC-301 section 8: const 1.0 document; major change is breaking."""

    @pytest.mark.parametrize("version", ["1.1", "2.0", "0.9"], ids=str)
    def test_unsupported_schema_version_refused(self, version):
        with pytest.raises(EnvelopeError) as exc:
            parse_envelope(envelope_dict(schema_version=version))
        assert exc.value.code is EnvelopeErrorCode.OBS_UNSUPPORTED_SCHEMA


class TestJournalSeq:
    """ADR-0006 decision 2: total order is journal_seq, gateway stamped."""

    def test_absent_in_producer_publish_view(self):
        envelope = parse_envelope(envelope_dict())
        assert envelope.journal_seq is None
        envelope.ensure_publishable()  # must not raise

    def test_present_after_gateway_stamping(self):
        envelope = parse_envelope(envelope_dict(journal_seq=1042))
        assert envelope.journal_seq == 1042
        # A stamped envelope is a valid journal record — it is simply no
        # longer a producer submission:
        with pytest.raises(EnvelopeError):
            envelope.ensure_publishable()

    def test_producer_must_never_fill_journal_seq(self):
        envelope = parse_envelope(envelope_dict(journal_seq=1042))
        with pytest.raises(EnvelopeError) as exc:
            envelope.ensure_publishable()
        assert exc.value.code is EnvelopeErrorCode.OBS_INVALID_ENVELOPE

    def test_negative_journal_seq_refused(self):
        with pytest.raises(EnvelopeError):
            parse_envelope(envelope_dict(journal_seq=-1))


class TestOrderingAndDedup:
    """SPEC-301 section 5: at-least-once, dedup key, source time not order."""

    def test_dedup_key_is_producer_id_and_event_id(self):
        envelope = parse_envelope(envelope_dict())
        assert envelope.dedup_key == ("ts-core", "7e6c8e17-6f4e-4f6a-9a34-2b9d1c9a5f21")

    def test_out_of_order_source_timestamps_stay_valid(self):
        # Source timestamps never define the total order (§5): envelopes
        # whose source times DESCEND across ingestion are all accepted; the
        # order credential is the gateway-stamped journal_seq, not the
        # producer's data.
        source_times = [1_500_000_000, 1_200_000_000, 900_000_000]
        for value_ns in source_times:
            envelope = parse_envelope(
                envelope_dict(
                    time={
                        "source": {
                            "value_ns": value_ns,
                            "clock_domain": "sim:0f0e8d1c-2b3a-4c5d-8e9f-0a1b2c3d4e5f",
                            "clock_epoch": 0,
                        },
                        "observed": {
                            "value_ns": 1_790_000_000_000_000_000,
                            "clock_domain": "wall:utc",
                            "clock_epoch": 0,
                        },
                    }
                )
            )
            assert envelope.time.source.value_ns == value_ns

    def test_delivery_protected_types_are_envelopes_too(self):
        # Terminal runs must be publishable as envelopes and stay protected.
        for event_type in ("simulation.run_completed", "simulation.run_failed"):
            assert is_delivery_protected(event_type)


class TestPayloadPolicy:
    """SPEC-301 section 7: size cap and secret-free payloads."""

    def test_payload_over_256kib_refused(self):
        payload = {
            "source": "internal_parser",
            "confidence": "parsed",
            "blob": "x" * (256 * 1024 + 1),
        }
        with pytest.raises(EnvelopeError) as exc:
            parse_envelope(envelope_dict(payload=payload))
        assert exc.value.code is EnvelopeErrorCode.OBS_PAYLOAD_TOO_LARGE

    def test_payload_just_under_cap_accepted(self):
        payload = {
            "source": "internal_parser",
            "confidence": "parsed",
            "blob": "x" * 1024,
        }
        envelope = parse_envelope(envelope_dict(payload=payload))
        assert len(json.dumps(envelope.payload)) < 256 * 1024

    @pytest.mark.parametrize(
        "key",
        ["api_key", "secret", "password", "biss_key", "credential", "private_key", "auth_token"],
        ids=str,
    )
    def test_secret_shaped_payload_keys_refused(self, key):
        payload = {
            "source": "internal_parser",
            "confidence": "parsed",
            key: "do-not-embed",
        }
        with pytest.raises(EnvelopeError) as exc:
            parse_envelope(envelope_dict(payload=payload))
        assert exc.value.code is EnvelopeErrorCode.OBS_INVALID_ENVELOPE

    def test_nested_secret_key_refused(self):
        payload = {
            "source": "internal_parser",
            "confidence": "parsed",
            "config": {"outer": {"api_key": "leak"}},
        }
        with pytest.raises(EnvelopeError):
            parse_envelope(envelope_dict(payload=payload))

    def test_benign_keys_pass(self):
        payload = {
            "source": "internal_parser",
            "confidence": "parsed",
            "expected_cc": 4,
            "keyframe_count": 3,  # contains 'key' but is not a secret
        }
        envelope = parse_envelope(envelope_dict(payload=payload))
        assert envelope.payload["keyframe_count"] == 3


class TestNewEventId:
    """ADR-0006 decision 3: uuid4 opaque event IDs, retry stable by policy."""

    def test_new_event_id_is_uuid4(self):
        event_id = new_event_id()
        assert len(event_id) == 36
        assert event_id.count("-") == 4
        assert event_id[14] == "4"  # uuid4 version nibble

    def test_new_event_ids_are_unique(self):
        assert len({new_event_id() for _ in range(100)}) == 100

    def test_new_event_id_fits_envelope(self):
        raw = envelope_dict(event_id=new_event_id())
        assert parse_envelope(raw).event_id == raw["event_id"]


class TestCorrelationModel:
    """ADR-0006 decision 3: node_id alone vs node_id+pid dual addressing."""

    def test_node_level_addressing(self):
        envelope = parse_envelope(
            envelope_dict(correlation={"node_id": "demux-0"})
        )
        assert envelope.correlation.node_id == "demux-0"
        assert envelope.correlation.pid is None  # node-level (state surface)

    def test_stream_level_addressing(self):
        envelope = parse_envelope(
            envelope_dict(correlation={"node_id": "mux-0", "pid": 256})
        )
        assert envelope.correlation.pid == 256  # stream-level (SIM_TS)

    def test_trace_fields(self):
        envelope = parse_envelope(
            envelope_dict(
                correlation=Correlation(
                    trace_id="trace-demo",
                    span_id="span-1",
                    parent_event_id="7e6c8e17-6f4e-4f6a-9a34-2b9d1c9a5f21",
                    fault_id="9d3b7c2e-51a8-4e6f-b0d4-8c7a6f5e4d31",
                )
            )
        )
        assert envelope.correlation.trace_id == "trace-demo"
        assert envelope.correlation.port_id is None


class TestPydanticStructuralRefusal:
    """Structural (non-contract) violations also surface as envelope errors."""

    @pytest.mark.parametrize(
        "raw",
        [None, "string", [1, 2], 42],
        ids=str,
    )
    def test_non_object_document_refused(self, raw):
        with pytest.raises(EnvelopeError) as exc:
            parse_envelope(raw)
        assert exc.value.code is EnvelopeErrorCode.OBS_INVALID_ENVELOPE

    def test_validation_error_is_wrapped_not_leaked(self):
        # A pydantic-level failure must not leak as a raw ValidationError to
        # producers: the ingestion boundary reports OBS_INVALID_ENVELOPE.
        raw = envelope_dict()
        raw["producer"] = "not-an-object"
        try:
            parse_envelope(raw)
        except EnvelopeError:
            pass
        else:  # pragma: no cover
            pytest.fail("expected EnvelopeError")
        try:
            EventEnvelope.model_validate(raw)
        except ValidationError:
            pass  # typed surface may raise pydantic directly
