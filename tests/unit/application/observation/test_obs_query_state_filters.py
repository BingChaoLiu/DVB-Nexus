"""State-snapshot query filters — SPEC-305 §Phase3 three dimensions (ticket #167).

The ``rf.*``/``sec.*`` snapshot query face over the SPEC-305 §5 flat
baseline: the events whitelist gains the ``namespace`` dimension (the
registered namespace prefixes), the ``event_types`` dimension accepts the
newly registered ``rf.state_observed``/``sec.state_observed`` values (#164),
and the new ``node_type`` dimension resolves the observed node's type from
the payload shape (the #164 REPORT discriminator: payload does not carry
``node_type`` — ``rf.*`` archives by main plane to the tuner, ``sec.*``
splits lnb/switch by the metric-key signature). The journal_seq cursor
binding covers the new filters (SPEC-305 §5: cursor 绑定过滤器哈希).

Unit layer: pure in-memory (``:memory:`` SQLite journal — the house-legal
form), no wall clock, no threads. HTTP envelope shapes are pinned at the
integration layer (``tests/integration/api/test_obs_query_endpoints.py``).
"""

from __future__ import annotations

import pytest

from adapters.storage import db
from adapters.storage.journal import SqliteEventJournal
from application.errors import REQUEST_BODY_INVALID, BadRequestError
from application.observation.query import EventsQueryRequest, ObservationQueryService
from application.observation.query.cursor import CursorExpiredError
from application.observation.query.service import resolve_snapshot_node_type
from domain.observation.registry import (
    RF_TUNER_SNAPSHOT_KEYS,
    SEC_LNB_SNAPSHOT_KEYS,
    SEC_SWITCH_SNAPSHOT_KEYS,
)

from tests.unit.application.observation.metrics._metrics_fixtures import raw_envelope

SESSION = "sess-state-filters"

TUNER_NODE = "tuner-a"
LNB_NODE = "lnb-0"
SWITCH_NODE = "sw-0"


def _journal() -> SqliteEventJournal:
    conn = db.connect(":memory:")
    db.migrate(conn)
    return SqliteEventJournal(conn)


def _tuner_payload(node_id: str = TUNER_NODE, **overrides) -> dict:
    """The exact ``rf.state_observed`` shape (``RF_TUNER_SNAPSHOT_KEYS``)."""
    payload = {
        "node_id": node_id,
        "health": "ok",
        "causes": [],
        "source": "state_evaluator",
        "confidence": "simulated",
        "lock_state": "locked",
        "if_frequency_khz": 1_420_000,
        "ber_state": "normal",
        "locked_transponder_id": "tp-1",
        "stale": False,
    }
    payload.update(overrides)
    assert set(payload) == set(RF_TUNER_SNAPSHOT_KEYS)
    return payload


def _lnb_payload(node_id: str = LNB_NODE, legacy: bool = False, **overrides) -> dict:
    """The exact ``sec.state_observed`` lnb shape (+ legacy ``sat_selected``)."""
    payload = {
        "node_id": node_id,
        "health": "ok",
        "causes": [],
        "source": "state_evaluator",
        "confidence": "simulated",
        "voltage": "13V",
        "tone_commanded": "none",
        "tone_actual": "none",
        "tone_composite": "none",
        "band_selected": "low",
        "lo_frequency_khz": 9750,
        "polarization_delivered": "vertical",
        "short_circuit_state": "normal",
        "ub_assignments": [],
    }
    if legacy:
        payload["sat_selected"] = "A"
    payload.update(overrides)
    return payload


def _switch_payload(node_id: str = SWITCH_NODE, **overrides) -> dict:
    """The exact ``sec.state_observed`` switch shape."""
    payload = {
        "node_id": node_id,
        "health": "ok",
        "causes": [],
        "source": "state_evaluator",
        "confidence": "simulated",
        "committed_switch_state": 0b0010,
        "uncommitted_switch_state": 0b0000,
        "port_selected": 2,
        "power_pass": "on",
    }
    payload.update(overrides)
    return payload


def _append(
    journal: SqliteEventJournal,
    event_type: str,
    payload: dict | None = None,
    *,
    value_ns: int = 1,
) -> int:
    envelope = raw_envelope(
        event_type=event_type,
        session_id=SESSION,
        source_ns=value_ns,
        payload=payload,
    )
    seq, duplicate = journal.append(envelope)
    assert duplicate is False
    return seq


def _service_with(*documents: tuple[str, dict | None, int]) -> ObservationQueryService:
    journal = _journal()
    for event_type, payload, value_ns in documents:
        _append(journal, event_type, payload, value_ns=value_ns)
    return ObservationQueryService(journal=journal)


def _query(service: ObservationQueryService, **kwargs):
    return service.query_events(EventsQueryRequest(session_id=SESSION, **kwargs))


class TestSnapshotNodeTypeResolution:
    """The declared node_type resolution semantic (registry 主平面映射).

    ``rf.*`` archives by main plane to the tuner; ``sec.*`` splits lnb /
    switch by the metric-key signature (payload does not carry node_type —
    the #164 REPORT contract). Everything else resolves to None.
    """

    def test_rf_state_observed_resolves_to_the_tuner(self) -> None:
        assert resolve_snapshot_node_type("rf.state_observed", _tuner_payload()) == "tuner"

    def test_sec_lnb_shape_resolves_to_lnb(self) -> None:
        assert resolve_snapshot_node_type("sec.state_observed", _lnb_payload()) == "lnb"

    def test_sec_legacy_cascade_shape_still_resolves_to_lnb(self) -> None:
        legacy = _lnb_payload(legacy=True)
        assert "sat_selected" in legacy
        assert resolve_snapshot_node_type("sec.state_observed", legacy) == "lnb"

    def test_sec_switch_shape_resolves_to_diseqc_switch(self) -> None:
        assert (
            resolve_snapshot_node_type("sec.state_observed", _switch_payload())
            == "diseqc_switch"
        )

    def test_non_snapshot_event_types_resolve_to_none(self) -> None:
        assert resolve_snapshot_node_type("simulation.run_started", {}) is None
        assert resolve_snapshot_node_type("gen.stage_started", {"layer": "TS"}) is None

    def test_sec_unresolvable_payload_resolves_to_none(self) -> None:
        assert resolve_snapshot_node_type("sec.state_observed", {"health": "ok"}) is None

    def test_shape_signatures_derive_disjoint_from_the_registry_constants(self) -> None:
        """The discriminator reuses the registry key constants (single
        source): base keys cancel, metric signatures stay disjoint."""
        from application.observation.query.service import (  # noqa: F401
            _LNB_SHAPE_KEYS,
            _SWITCH_SHAPE_KEYS,
        )

        assert not (_SWITCH_SHAPE_KEYS & _LNB_SHAPE_KEYS)
        assert _SWITCH_SHAPE_KEYS == SEC_SWITCH_SNAPSHOT_KEYS - SEC_LNB_SNAPSHOT_KEYS
        assert _LNB_SHAPE_KEYS == SEC_LNB_SNAPSHOT_KEYS - SEC_SWITCH_SNAPSHOT_KEYS


class TestNamespaceDimension:
    """``namespace`` filters by the registered namespace prefix."""

    def test_namespace_rf_returns_only_rf_snapshots(self) -> None:
        service = _service_with(
            ("rf.state_observed", _tuner_payload(), 1),
            ("sec.state_observed", _lnb_payload(), 2),
            ("simulation.run_started", None, 3),
        )

        page = _query(service, namespaces=("rf",))

        assert [item["event_type"] for item in page.items] == ["rf.state_observed"]

    def test_namespace_sec_returns_only_sec_snapshots(self) -> None:
        service = _service_with(
            ("rf.state_observed", _tuner_payload(), 1),
            ("sec.state_observed", _lnb_payload(), 2),
            ("simulation.run_started", None, 3),
        )

        page = _query(service, namespaces=("sec",))

        assert [item["event_type"] for item in page.items] == ["sec.state_observed"]

    def test_namespace_union_returns_both_state_families_in_journal_order(self) -> None:
        service = _service_with(
            ("simulation.run_started", None, 1),
            ("sec.state_observed", _lnb_payload(), 2),
            ("rf.state_observed", _tuner_payload(), 3),
        )

        page = _query(service, namespaces=("rf", "sec"))

        assert [item["event_type"] for item in page.items] == [
            "sec.state_observed",
            "rf.state_observed",
        ]

    def test_namespace_without_matches_is_an_honest_empty_page(self) -> None:
        service = _service_with(("rf.state_observed", _tuner_payload(), 1))

        page = _query(service, namespaces=("ts",))

        assert page.items == ()
        assert page.next_cursor is None

    def test_unknown_namespace_value_is_the_400_row(self) -> None:
        service = _service_with(("rf.state_observed", _tuner_payload(), 1))

        with pytest.raises(BadRequestError) as excinfo:
            _query(service, namespaces=("nope",))
        assert excinfo.value.error_code == REQUEST_BODY_INVALID
        assert excinfo.value.details.get("param") == "namespaces"

    def test_namespace_matches_only_its_own_family(self) -> None:
        """A registered namespace answers only its own dotted family; the
        whitelist (registry-derived) blocks substring confusion up front."""
        service = _service_with(
            ("rf.state_observed", _tuner_payload(), 1),
            ("simulation.run_started", None, 2),
        )

        assert _query(service, namespaces=("fault",)).items == ()
        assert _query(service, namespaces=("simulation",)).items != ()
        with pytest.raises(BadRequestError):
            _query(service, namespaces=("r",))


class TestEventTypeDimensionAcceptsRfSec:
    """``event_types`` membership with the newly registered #164 values."""

    def test_event_types_filters_rf_state_observed(self) -> None:
        service = _service_with(
            ("rf.state_observed", _tuner_payload(), 1),
            ("sec.state_observed", _lnb_payload(), 2),
        )

        page = _query(service, event_types=("rf.state_observed",))

        assert [item["event_type"] for item in page.items] == ["rf.state_observed"]

    def test_event_types_union_answers_both_state_families(self) -> None:
        service = _service_with(
            ("rf.state_observed", _tuner_payload(), 1),
            ("sec.state_observed", _lnb_payload(), 2),
            ("simulation.run_started", None, 3),
        )

        page = _query(
            service,
            event_types=("rf.state_observed", "sec.state_observed"),
        )

        assert [item["event_type"] for item in page.items] == [
            "rf.state_observed",
            "sec.state_observed",
        ]

    def test_namespace_and_event_types_compose(self) -> None:
        service = _service_with(
            ("rf.state_observed", _tuner_payload(), 1),
            ("sec.state_observed", _lnb_payload(), 2),
        )

        page = _query(
            service, namespaces=("sec",), event_types=("rf.state_observed",)
        )

        assert page.items == ()


class TestNodeTypeDimension:
    """``node_type`` filters snapshots by the resolved observed-node type."""

    def test_node_type_tuner_answers_only_rf_snapshots(self) -> None:
        service = _service_with(
            ("rf.state_observed", _tuner_payload(), 1),
            ("sec.state_observed", _lnb_payload(), 2),
        )

        page = _query(service, node_types=("tuner",))

        assert [item["event_type"] for item in page.items] == ["rf.state_observed"]

    def test_node_type_lnb_answers_only_the_lnb_shape(self) -> None:
        service = _service_with(
            ("rf.state_observed", _tuner_payload(), 1),
            ("sec.state_observed", _lnb_payload(), 2),
            ("sec.state_observed", _switch_payload(), 3),
        )

        page = _query(service, node_types=("lnb",))

        payloads = [item["payload"] for item in page.items]
        assert len(payloads) == 1
        assert "voltage" in payloads[0]

    def test_node_type_lnb_covers_the_legacy_cascade_shape(self) -> None:
        service = _service_with(
            ("sec.state_observed", _lnb_payload(legacy=True), 1),
            ("sec.state_observed", _switch_payload(), 2),
        )

        page = _query(service, node_types=("lnb",))

        assert len(page.items) == 1
        assert "sat_selected" in page.items[0]["payload"]

    def test_node_type_diseqc_switch_answers_only_the_switch_shape(self) -> None:
        service = _service_with(
            ("sec.state_observed", _lnb_payload(), 1),
            ("sec.state_observed", _switch_payload(), 2),
        )

        page = _query(service, node_types=("diseqc_switch",))

        payloads = [item["payload"] for item in page.items]
        assert len(payloads) == 1
        assert "committed_switch_state" in payloads[0]

    def test_node_type_union_answers_tuner_and_lnb(self) -> None:
        service = _service_with(
            ("rf.state_observed", _tuner_payload(), 1),
            ("sec.state_observed", _lnb_payload(), 2),
            ("sec.state_observed", _switch_payload(), 3),
        )

        page = _query(service, node_types=("tuner", "lnb"))

        assert [item["journal_seq"] for item in page.items] == [1, 2]

    def test_registered_node_type_without_snapshots_is_an_honest_empty_page(self) -> None:
        service = _service_with(("rf.state_observed", _tuner_payload(), 1))

        page = _query(service, node_types=("ts_mux",))

        assert page.items == ()

    def test_non_snapshot_events_are_excluded_under_node_type_filter(self) -> None:
        service = _service_with(
            ("simulation.run_started", None, 1),
            ("rf.state_observed", _tuner_payload(), 2),
        )

        page = _query(service, node_types=("tuner",))

        assert [item["event_type"] for item in page.items] == ["rf.state_observed"]

    def test_unknown_node_type_value_is_the_400_row(self) -> None:
        service = _service_with(("rf.state_observed", _tuner_payload(), 1))

        with pytest.raises(BadRequestError) as excinfo:
            _query(service, node_types=("not_a_node_type",))
        assert excinfo.value.error_code == REQUEST_BODY_INVALID
        assert excinfo.value.details.get("param") == "node_types"


class TestCursorBindingCoversNewFilters:
    """The cursor binds the new filter dimensions (SPEC-305 §5 binding)."""

    def _two_rf_two_sec(self) -> ObservationQueryService:
        return _service_with(
            ("rf.state_observed", _tuner_payload(TUNER_NODE, lock_state="unlocked",
                                                if_frequency_khz=None,
                                                ber_state=None,
                                                locked_transponder_id=None,
                                                stale=True), 1),
            ("sec.state_observed", _lnb_payload(), 2),
            ("rf.state_observed", _tuner_payload(), 3),
            ("sec.state_observed", _switch_payload(), 4),
        )

    def test_cursor_walks_the_filtered_page(self) -> None:
        service = self._two_rf_two_sec()

        first = _query(service, namespaces=("rf",), limit=1)
        assert [item["journal_seq"] for item in first.items] == [1]
        assert first.truncated is True

        second = _query(
            service, namespaces=("rf",), limit=1, cursor=first.next_cursor
        )
        assert [item["journal_seq"] for item in second.items] == [3]
        assert second.next_cursor is None

    def test_cursor_replayed_under_a_changed_namespace_is_expired(self) -> None:
        service = self._two_rf_two_sec()

        first = _query(service, namespaces=("rf",), limit=1)
        with pytest.raises(CursorExpiredError):
            _query(
                service, namespaces=("sec",), limit=1, cursor=first.next_cursor
            )

    def test_cursor_replayed_under_a_changed_node_type_is_expired(self) -> None:
        service = self._two_rf_two_sec()

        first = _query(service, node_types=("tuner",), limit=1)
        with pytest.raises(CursorExpiredError):
            _query(
                service,
                node_types=("diseqc_switch",),
                limit=1,
                cursor=first.next_cursor,
            )

    def test_journal_sort_desc_cursor_walks_the_sec_filter(self) -> None:
        service = self._two_rf_two_sec()

        first = _query(service, namespaces=("sec",), sort="journal_desc", limit=1)
        assert [item["journal_seq"] for item in first.items] == [4]

        second = _query(
            service,
            namespaces=("sec",),
            sort="journal_desc",
            limit=1,
            cursor=first.next_cursor,
        )
        assert [item["journal_seq"] for item in second.items] == [2]
        assert second.next_cursor is None
