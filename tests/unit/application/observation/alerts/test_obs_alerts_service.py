"""AlertService face (SPEC-300 §12 7th required interface, ticket #52).

The frozen required interface is ``AlertService.list(request) -> AlertPage``;
the service owns the record-authority write path (engine transitions →
store), the WS hint emission seam (R1 ruling: an INJECTED hint-emitter port —
the production hub binding is ticket #53's face) and the suppression
modifier (SPEC-304 §9: suppressed records stay query-visible, keep
lifecycle-evolving, and their hints are withheld while suppressed).

REQ-OBS-304-003 (MVP 零 observation.* 信封事件): the service's only
notification vocabulary is the ``observation.alert_changed`` HINT TOPIC — a
plain string that is NOT a registered event type; the whole
``observation.*`` namespace is withdrawn at the registry (SPEC-301 §4) and
every WS theme must be refused by ``validate_event_type``. The service
constructs no envelopes at all.
"""

import pytest

from application.errors import NotFoundError
from application.observation.alerts.engine import AlertEngine, AlertEngineConfig
from application.observation.alerts.rollup import ROLLUP_POLICY
from application.observation.alerts.rules import HealthRuleSet, default_rule_set
from application.observation.alerts.service import (
    ALERT_CHANGED_TOPIC,
    WS_HINT_TOPICS,
    AlertHint,
    AlertHintEmitter,
    AlertListRequest,
    AlertService,
)
from domain.observation import (
    AlertSeverity,
    AlertState,
    EnvelopeError,
    REGISTERED_EVENT_TYPES,
    validate_event_type,
)

from tests._support.sqlite_support import apply_sql_migrations, default_migrations_dir
from tests.unit.application.observation.alerts._alerts_fixtures import (
    CannedReader,
    DOMAIN,
    RecordingHintEmitter,
    deterministic_alert_id,
    make_rule,
    sample_at,
)

from adapters.storage.alerts import SqliteAlertStore
from adapters.storage.db import connect as db_connect


def _store():
    connection = db_connect(":memory:")
    migrations_dir = default_migrations_dir()
    if migrations_dir is not None:
        apply_sql_migrations(connection, migrations_dir)
    return SqliteAlertStore(connection)


def _service(reader=None, emitter=None, rule_set=None):
    emitter = emitter if emitter is not None else RecordingHintEmitter()
    config = AlertEngineConfig(alert_id_factory=deterministic_alert_id())
    rules = rule_set.rules if rule_set is not None else make_rule()
    service = AlertService(
        _store(),
        rule_set or HealthRuleSet(
            ruleset_id="svc-test",
            version="1.0.0",
            profile="mvp-sandbox",
            rules=(make_rule(),),
        ),
        hint_emitter=emitter,
        engine=AlertEngine(rules, config=config),
    )
    return service, reader or CannedReader(), emitter


def _drive_to_firing(service, reader) -> None:
    reader.add(sample_at(900, 200.0))
    service.evaluate_session("sess-1", reader=reader, now_ns=1_000, clock_domain=DOMAIN)
    service.evaluate_session("sess-1", reader=reader, now_ns=2_000, clock_domain=DOMAIN)


class TestRecordAuthorityWritePath:
    """REQ-304-002/003: transitions persist as alert records."""

    def test_transitions_persist_records_with_full_provenance(self) -> None:
        service, reader, _ = _service()
        _drive_to_firing(service, reader)
        page = service.list(AlertListRequest(session_id="sess-1"))
        assert page.total == 1
        record = page.items[0]
        assert record.state is AlertState.FIRING
        assert record.rule_id == "TEST_RULE"
        assert record.rule_version == "1.2.0"
        assert record.scope.tenant_id == "local"
        assert record.scope.session_id == "sess-1"
        assert record.time.clock_domain == DOMAIN
        assert record.time.semantics.value == "derived"
        assert record.evidence_refs  # evidence captured on migration
        assert "200" in record.summary  # the measured fact

    def test_state_transitions_update_the_same_record(self) -> None:
        service, reader, _ = _service()
        _drive_to_firing(service, reader)
        reader.add(sample_at(3_000, 10.0))
        service.evaluate_session("sess-1", reader=reader, now_ns=3_100, clock_domain=DOMAIN)
        record = service.list(AlertListRequest(session_id="sess-1")).items[0]
        assert record.state is AlertState.RESOLVING
        assert service.list(AlertListRequest(session_id="sess-1")).total == 1


class TestHintEmissionSeam:
    """R1 ruling: hints go through the INJECTED emitter port; #53 binds it."""

    def test_every_transition_emits_one_hint(self) -> None:
        service, reader, emitter = _service()
        _drive_to_firing(service, reader)
        assert len(emitter.hints) == 2  # pending + firing
        first = emitter.hints[0]
        assert isinstance(first, AlertHint)
        assert first.topic == ALERT_CHANGED_TOPIC == "observation.alert_changed"
        assert first.session_id == "sess-1"
        assert first.state in (AlertState.PENDING.value, AlertState.FIRING.value)

    def test_suppressed_records_keep_evolving_without_hints(self) -> None:
        service, reader, emitter = _service()
        _drive_to_firing(service, reader)
        alert_id = service.list(AlertListRequest(session_id="sess-1")).items[0].alert_id
        service.suppress(alert_id, reason="maintenance", suppressed_by="op")
        emitted_before = len(emitter.hints)
        reader.add(sample_at(3_000, 10.0))
        service.evaluate_session("sess-1", reader=reader, now_ns=3_100, clock_domain=DOMAIN)
        # The lifecycle still moved (record authority), the hint did not fire.
        record = service.get(alert_id)
        assert record.state is AlertState.RESOLVING
        assert len(emitter.hints) == emitted_before

    def test_emitter_failures_never_break_evaluation(self) -> None:
        emitter = RecordingHintEmitter()
        emitter.fail_after = 1  # second emit raises
        service, reader, _ = _service(emitter=emitter)
        reader.add(sample_at(900, 200.0))
        service.evaluate_session("sess-1", reader=reader, now_ns=1_000, clock_domain=DOMAIN)
        result = service.evaluate_session(
            "sess-1", reader=reader, now_ns=2_000, clock_domain=DOMAIN
        )
        # Best-effort: the firing transition still persisted.
        states = {record.state for record in result.records}
        assert AlertState.FIRING in states

    def test_no_emitter_is_a_valid_composition(self) -> None:
        service = AlertService(
            _store(),
            HealthRuleSet(
                ruleset_id="s", version="1", profile="p", rules=(make_rule(),)
            ),
        )
        reader = CannedReader((sample_at(900, 200.0),))
        result = service.evaluate_session(
            "sess-1", reader=reader, now_ns=1_000, clock_domain=DOMAIN
        )
        assert result.records


class TestSuppressionModifier:
    """SPEC-304 §5/§9: modifier, not a migration state."""

    def test_suppress_and_unsuppress_keep_the_lifecycle_state(self) -> None:
        service, reader, _ = _service()
        _drive_to_firing(service, reader)
        alert_id = service.list(AlertListRequest(session_id="sess-1")).items[0].alert_id
        suppressed = service.suppress(alert_id, reason="window", suppressed_by="op")
        assert suppressed.is_suppressed
        assert suppressed.state is AlertState.FIRING
        restored = service.unsuppress(alert_id)
        assert not restored.is_suppressed
        assert restored.state is AlertState.FIRING

    def test_unknown_alert_suppress_answers_none(self) -> None:
        # No unregistered OBS_* 404 code is invented at the service seam —
        # the unknown-record HTTP row and its code are the #53 plane (R1).
        service, _, _ = _service()
        assert service.suppress("nope", reason="x") is None
        assert service.unsuppress("nope") is None

    def test_suppression_filter_via_list(self) -> None:
        service, reader, _ = _service()
        _drive_to_firing(service, reader)
        alert_id = service.list(AlertListRequest(session_id="sess-1")).items[0].alert_id
        service.suppress(alert_id, reason="window")
        only_suppressed = service.list(
            AlertListRequest(session_id="sess-1", suppressed=True)
        )
        assert only_suppressed.total == 1
        assert only_suppressed.items[0].is_suppressed


class TestListFace:
    """SPEC-300 §12: the frozen ``AlertService.list`` name/shape."""

    def test_list_returns_an_alert_page(self) -> None:
        service, reader, _ = _service()
        assert service.list(AlertListRequest(session_id="sess-1")).total == 0
        _drive_to_firing(service, reader)
        page = service.list(AlertListRequest(session_id="sess-1"))
        assert page.total == 1
        assert not page.truncated

    def test_active_count_excludes_settled_states(self) -> None:
        service, reader, _ = _service()
        _drive_to_firing(service, reader)
        assert service.active_count("sess-1") == 1
        assert service.active_count("sess-9") == 0


class TestHealthFace:
    """§7 roll-up through the service (the #53 GET /health backend)."""

    def test_health_returns_policy_and_version(self) -> None:
        service, reader, _ = _service()
        health = service.health(
            "sess-1", reader=reader, now_ns=1_000, clock_domain=DOMAIN
        )
        assert health.rule_set_id == "svc-test"
        assert health.policy.name == ROLLUP_POLICY.name
        # Missing input ⇒ unknown (never a false healthy).
        assert health.overall.value == "unknown"

    def test_health_critical_on_firing_critical_rule(self) -> None:
        rule = make_rule(severity=AlertSeverity.CRITICAL)
        rule_set = HealthRuleSet(
            ruleset_id="s", version="1", profile="p", rules=(rule,)
        )
        service = AlertService(
            _store(),
            rule_set,
            engine=AlertEngine(rule, config=AlertEngineConfig(
                alert_id_factory=deterministic_alert_id()
            )),
        )
        reader = CannedReader((sample_at(900, 200.0),))
        service.evaluate_session("sess-1", reader=reader, now_ns=1_000, clock_domain=DOMAIN)
        service.evaluate_session("sess-1", reader=reader, now_ns=2_000, clock_domain=DOMAIN)
        health = service.health(
            "sess-1", reader=reader, now_ns=2_100, clock_domain=DOMAIN
        )
        assert health.overall.value == "critical"


class TestZeroEnvelopeEvents:
    """REQ-304-003: MVP 零 observation.* 信封事件 (SPEC-301 §4 撤出清单)."""

    def test_every_ws_hint_theme_is_withdrawn_at_the_registry(self) -> None:
        assert ALERT_CHANGED_TOPIC == "observation.alert_changed"
        assert "observation.alert_changed" in WS_HINT_TOPICS
        for topic in WS_HINT_TOPICS:
            with pytest.raises(EnvelopeError):
                validate_event_type(topic)

    def test_alert_changed_topic_is_not_a_registered_event_type(self) -> None:
        assert ALERT_CHANGED_TOPIC not in REGISTERED_EVENT_TYPES

    def test_hint_is_a_plain_topic_payload_never_an_envelope(self) -> None:
        # The hint projection carries record fields only — no envelope
        # structure (no event_id/producer/time.source), no payload schema.
        hint = AlertHint(
            topic=ALERT_CHANGED_TOPIC,
            session_id="sess-1",
            alert_id="alert-1",
            fingerprint="fp",
            rule_id="R",
            state=AlertState.FIRING.value,
            severity=AlertSeverity.WARNING.value,
        )
        dump = hint.model_dump(mode="json")
        assert set(dump) == {
            "topic",
            "session_id",
            "alert_id",
            "fingerprint",
            "rule_id",
            "state",
            "severity",
        }
        assert "event_id" not in dump and "payload" not in dump
