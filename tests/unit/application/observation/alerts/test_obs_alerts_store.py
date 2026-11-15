"""Alert store semantics (ticket #52) — the ``alerts`` table authority.

Unit layer over the production SQLite store via the documented ``:memory:``
slice posture (production ``adapters.storage.db.connect`` + the production
migrate runner — the SPEC-502 §4 ``alerts`` table, ticket #23 R8: the 11
frozen columns). The store is the alert-record authority's persistence:
upsert on ``alert_id``, deterministic listing order, active-count semantics
for the SPEC-302 ``observation.alerts_active`` metric, and the suppression
modifier staying query-visible (SPEC-304 §9).

No parallel machinery: the table comes from the frozen migration 0001 and
the connection discipline is the production one (WAL/foreign_keys via
``apply_pragma_policy`` on file-backed stores — ``:memory:`` here).
"""

from domain.observation import (
    AlertRecord,
    AlertScope,
    AlertSeverity,
    AlertState,
    AlertSuppression,
    MetricSampleTimepoint,
    SampleSemantics,
)

from adapters.storage.alerts import SqliteAlertStore
from adapters.storage.db import connect as db_connect
from tests._support.sqlite_support import apply_sql_migrations, default_migrations_dir
from application.observation.alerts.store import (
    ACTIVE_STATES,
    LIST_LIMIT_DEFAULT,
    LIST_LIMIT_HARD_CAP,
    AlertListRequest,
)


def _connection():
    connection = db_connect(":memory:")
    migrations_dir = default_migrations_dir()
    if migrations_dir is not None:
        apply_sql_migrations(connection, migrations_dir)
    return connection


def _record(
    alert_id: str = "alert-0001",
    *,
    rule_id: str = "PCR_JITTER_HIGH",
    fingerprint: str = "fp-1",
    state: AlertState = AlertState.FIRING,
    severity: AlertSeverity = AlertSeverity.WARNING,
    session_id: str = "sess-1",
    suppression: AlertSuppression | None = None,
    evidence: tuple[str, ...] = ("journal:1002",),
    summary: str | None = "PCR jitter p95 = 200000 ns satisfies open gt 100000 ns",
) -> AlertRecord:
    return AlertRecord(
        alert_id=alert_id,
        fingerprint=fingerprint,
        rule_id=rule_id,
        rule_version="1.0.0",
        state=state,
        severity=severity,
        scope=AlertScope(tenant_id="local", session_id=session_id),
        time=MetricSampleTimepoint(
            value_ns=8_000_000_000,
            clock_domain=f"sim:{session_id}",
            clock_epoch=0,
            semantics=SampleSemantics.DERIVED,
        ),
        summary=summary,
        evidence_refs=evidence,
        suppression=suppression,
    )


class TestUpsertAndGet:
    def test_save_then_get_round_trips_the_full_record(self) -> None:
        store = SqliteAlertStore(_connection())
        record = _record(suppression=AlertSuppression(reason="maintenance"))
        store.save(record)
        loaded = store.get(record.alert_id)
        assert loaded == record
        assert loaded.is_suppressed
        assert loaded.suppression.reason == "maintenance"

    def test_upsert_overwrites_the_previous_state(self) -> None:
        store = SqliteAlertStore(_connection())
        store.save(_record(state=AlertState.PENDING))
        store.save(_record(state=AlertState.FIRING))
        loaded = store.get("alert-0001")
        assert loaded.state is AlertState.FIRING

    def test_unknown_id_returns_none(self) -> None:
        store = SqliteAlertStore(_connection())
        assert store.get("nope") is None

    def test_null_summary_and_empty_evidence_survive_the_round_trip(self) -> None:
        store = SqliteAlertStore(_connection())
        record = _record(summary=None, evidence=())
        store.save(record)
        assert store.get(record.alert_id) == record


class TestFingerprintLookup:
    def test_find_by_fingerprint_scopes_by_session(self) -> None:
        store = SqliteAlertStore(_connection())
        store.save(_record(session_id="sess-1"))
        store.save(_record("alert-0002", session_id="sess-2"))
        found = store.find_by_fingerprint("sess-1", "fp-1")
        assert found is not None
        assert found.alert_id == "alert-0001"
        assert store.find_by_fingerprint("sess-3", "fp-1") is None

    def test_active_only_limits_to_unsettled_states(self) -> None:
        store = SqliteAlertStore(_connection())
        store.save(_record("alert-0001", state=AlertState.RESOLVED))
        assert store.find_by_fingerprint("sess-1", "fp-1", active_only=True) is None
        store.save(_record("alert-0001", state=AlertState.PENDING))
        assert store.find_by_fingerprint("sess-1", "fp-1", active_only=True) is not None


class TestListSemantics:
    def test_order_is_deterministic_by_rule_fingerprint_id(self) -> None:
        store = SqliteAlertStore(_connection())
        store.save(_record("alert-0003", rule_id="TS_CC_ERROR_RATE_HIGH", fingerprint="fp-c"))
        store.save(_record("alert-0002", rule_id="PCR_JITTER_HIGH", fingerprint="fp-b"))
        store.save(_record("alert-0001", rule_id="PCR_JITTER_HIGH", fingerprint="fp-a"))
        page = store.list(AlertListRequest(session_id="sess-1"))
        assert [item.alert_id for item in page.items] == [
            "alert-0001",
            "alert-0002",
            "alert-0003",
        ]
        assert page.total == 3
        assert not page.truncated

    def test_filters_narrow_the_page(self) -> None:
        store = SqliteAlertStore(_connection())
        store.save(_record("alert-0001", state=AlertState.FIRING))
        store.save(
            _record(
                "alert-0002",
                rule_id="PSI_STALE",
                fingerprint="fp-2",
                state=AlertState.RESOLVED,
                severity=AlertSeverity.INFO,
            )
        )
        firing = store.list(AlertListRequest(session_id="sess-1", state=AlertState.FIRING))
        assert [item.alert_id for item in firing.items] == ["alert-0001"]
        by_severity = store.list(
            AlertListRequest(session_id="sess-1", severity=AlertSeverity.INFO)
        )
        assert [item.alert_id for item in by_severity.items] == ["alert-0002"]
        by_rule = store.list(AlertListRequest(session_id="sess-1", rule_id="PSI_STALE"))
        assert [item.alert_id for item in by_rule.items] == ["alert-0002"]

    def test_suppression_modifier_is_query_visible_and_filterable(self) -> None:
        store = SqliteAlertStore(_connection())
        store.save(_record("alert-0001"))
        store.save(
            _record(
                "alert-0002",
                fingerprint="fp-2",
                suppression=AlertSuppression(reason="window", suppressed_by="op"),
            )
        )
        suppressed = store.list(AlertListRequest(session_id="sess-1", suppressed=True))
        assert [item.alert_id for item in suppressed.items] == ["alert-0002"]
        visible = store.list(AlertListRequest(session_id="sess-1"))
        # SPEC-304 §9: 抑制告警保持可查询 — both stay in the default page.
        assert [item.alert_id for item in visible.items] == ["alert-0001", "alert-0002"]

    def test_limit_truncation_and_total(self) -> None:
        store = SqliteAlertStore(_connection())
        for index in range(5):
            store.save(_record(f"alert-{index:04d}", fingerprint=f"fp-{index}"))
        page = store.list(AlertListRequest(session_id="sess-1", limit=3))
        assert len(page.items) == 3
        assert page.total == 5
        assert page.truncated

    def test_limit_cap_and_default_constants(self) -> None:
        # SPEC-305 §5 同源: default 100, hard cap 2000 (journal constants).
        assert LIST_LIMIT_DEFAULT == 100
        assert LIST_LIMIT_HARD_CAP == 2000
        store = SqliteAlertStore(_connection())
        request = AlertListRequest(session_id="sess-1", limit=10_000)
        assert request.limit == 10_000  # request carries the raw ask...
        page = store.list(request)
        assert len(page.items) == 0  # ...the store clamps when applying


class TestActiveCount:
    def test_active_counts_only_pending_firing_resolving(self) -> None:
        assert ACTIVE_STATES == frozenset(
            {AlertState.PENDING, AlertState.FIRING, AlertState.RESOLVING}
        )
        store = SqliteAlertStore(_connection())
        store.save(_record("alert-0001", state=AlertState.FIRING))
        store.save(_record("alert-0002", fingerprint="fp-2", state=AlertState.PENDING))
        store.save(_record("alert-0003", fingerprint="fp-3", state=AlertState.RESOLVING))
        store.save(_record("alert-0004", fingerprint="fp-4", state=AlertState.RESOLVED))
        store.save(_record("alert-0005", fingerprint="fp-5", state=AlertState.INACTIVE))
        assert store.count_active("sess-1") == 3
        assert store.count_active("sess-9") == 0
