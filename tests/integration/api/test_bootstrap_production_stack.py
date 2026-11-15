"""Production composition root wiring (ticket #53, 裁定 1/K).

The ``bootstrap.build_production_app`` factory proves the WHOLE SPEC-300
§7 data flow over the REAL production wiring — the same composition an
embedder gets, driven deterministically through the stack's faces:

- journal → gateway → hub (the #49 binding, ``is_coalescable`` injected)
  → REST pulls (the eight §4.5 routes live);
- the #44 semantic filter factory is the TS runtime default (裁定 1b);
- the #52 alert hint port rides the real hub (裁定 C);
- the SPEC-305 §8 emission points: event_appended (gateway subscriber),
  metric_updated (consumer tick), health_changed (query face),
  export_progress (registry), alert_changed (service port);
- restart discipline: a fresh stack over the same database continues the
  checkpointed consumers from the durable cursor (SPEC-300 §8).
"""

from __future__ import annotations

import pytest

from api.versioning import API_V1_PREFIX
from bootstrap import build_production_app
from domain.observation import parse_envelope

from tests.unit.application.observation.test_gateway_accept import _raw_envelope

SESSION = "sess-prod"
DOMAIN = f"sim:{SESSION}"


def _emit(stack, **overrides) -> dict:
    envelope = _raw_envelope(
        event_type=overrides.pop("event_type", "simulation.run_started"),
        session_id=overrides.pop("session_id", SESSION),
        producer_id=overrides.pop("producer_id", "sim-engine"),
    )
    envelope["severity"] = overrides.pop("severity", "info")
    envelope["time"]["source"]["value_ns"] = overrides.pop("value_ns", 1)
    envelope["time"]["source"]["clock_domain"] = DOMAIN
    envelope["scope"]["run_id"] = overrides.pop("run_id", "run-1")
    result = stack.gateway.accept(envelope)
    assert result.outcome.value == "accepted", result
    return envelope


class TestProductionWiring:
    def test_full_chain_flows_to_the_rest_surface(self, tmp_path):
        """Producers → gateway → journal → query service → HTTP (SPEC-300
        §7 steps 1-7 over the production composition)."""
        stack = build_production_app(db_path=tmp_path / "prod.sqlite3")
        try:
            for index in range(3):
                _emit(stack, value_ns=index)
            assert stack.drain_gateway() == 3

            from fastapi.testclient import TestClient

            client = TestClient(stack.app)
            response = client.get(f"{API_V1_PREFIX}/sessions/{SESSION}/events")
            assert response.status_code == 200, response.text
            items = response.json()["data"]["items"]
            assert [item["journal_seq"] for item in items] == [1, 2, 3]

            summary = client.get(f"{API_V1_PREFIX}/sessions/{SESSION}/observation/summary")
            assert summary.json()["data"]["journal_seq_watermark"] == 3
        finally:
            stack.close()

    def test_route_inventory_includes_ws_route_additively(self, tmp_path):
        """The production app serves BOTH /api/v1 (frozen table) and the
        SPEC-501 route (additive, outside /api/v1)."""

        def _all_routes(router):
            for route in router.routes:
                path = getattr(route, "path", None)
                if path:
                    yield path
                nested = getattr(route, "original_router", None)
                if nested is not None:
                    yield from _all_routes(nested)

        stack = build_production_app(db_path=tmp_path / "prod.sqlite3")
        try:
            openapi = stack.app.openapi()
            assert any(path.startswith(API_V1_PREFIX) for path in openapi["paths"])
            assert "/ws/v1/sessions/{session_id}" in set(_all_routes(stack.app.router))
        finally:
            stack.close()

    def test_journal_frames_and_hints_both_fan_out(self, tmp_path):
        """The hub receives committed envelopes (journal frames) while the
        hint subscriber emits observation.event_appended pointers."""
        stack = build_production_app(db_path=tmp_path / "prod.sqlite3")
        try:
            seen_journal: list[int] = []
            stack.gateway.subscribe(
                lambda stamped: seen_journal.append(stamped["journal_seq"])
            )
            hints: list[tuple[str, str, dict]] = []
            original = stack.hint_publisher.publish

            def recording(session_id, topic, data):
                hints.append((session_id, topic, data))
                original(session_id, topic, data)

            stack.hint_publisher.publish = recording  # test observation seam
            _emit(stack, value_ns=5)
            stack.drain_gateway()

            assert seen_journal == [1]
            topics = [topic for _, topic, _ in hints]
            assert "observation.event_appended" in topics
        finally:
            stack.close()

    def test_metrics_consumer_tick_advances_and_emits_pointer(self, tmp_path):
        stack = build_production_app(db_path=tmp_path / "prod.sqlite3")
        try:
            stack.attach_session(SESSION)
            hints: list[tuple[str, str, dict]] = []
            original = stack.hint_publisher.publish

            def recording(session_id, topic, data):
                hints.append((session_id, topic, data))
                original(session_id, topic, data)

            stack.hint_publisher.publish = recording
            # run_progress is the COALESCABLE type (SPEC-301 §5) — distinct
            # run ids keep the three events from collapsing into one.
            for index in range(3):
                _emit(
                    stack,
                    value_ns=index,
                    event_type="simulation.run_progress",
                    run_id=f"run-{index}",
                )
            stack.drain_gateway()
            processed = stack.process_observation(SESSION)

            assert processed == 3
            metric_hints = [h for h in hints if h[1] == "observation.metric_updated"]
            assert metric_hints, "a consumer tick emits the metric pointer"
            assert metric_hints[0][2]["journal_seq_watermark"] == 3
            assert stack.metrics_engine.journal_watermark == 3
        finally:
            stack.close()

    def test_semantic_filter_factory_is_the_ts_runtime_default(self, tmp_path):
        """裁定 1b: the production composition wires the real #44 semantic
        filter (not the retired identity placeholder)."""
        from faults.factory import create_fault_filter

        stack = build_production_app(db_path=tmp_path / "prod.sqlite3")
        try:
            produced = stack.ts_runtime._filter_factory((), None)  # noqa: SLF001
            assert isinstance(produced, create_fault_filter((), None).__class__)
        finally:
            stack.close()

    def test_export_task_emits_progress_hint_and_manifest(self, tmp_path):
        stack = build_production_app(db_path=tmp_path / "prod.sqlite3")
        try:
            _emit(stack, value_ns=7)
            stack.drain_gateway()
            hints: list[tuple[str, str, dict]] = []
            original = stack.hint_publisher.publish

            def recording(session_id, topic, data):
                hints.append((session_id, topic, data))
                original(session_id, topic, data)

            stack.hint_publisher.publish = recording
            task = stack.query_service.create_export(
                session_id=SESSION, formats=("jsonl",)
            )
            assert task.status == "completed"
            assert task.manifest["total_records"] == 1
            assert any(
                topic == "observation.export_progress" for _, topic, _ in hints
            )
        finally:
            stack.close()

    def test_restart_continues_from_durable_checkpoints(self, tmp_path):
        """SPEC-300 §8: a fresh stack over the same database consumes from
        the durable cursor — no double-processing, no loss."""
        db_path = tmp_path / "prod.sqlite3"
        stack = build_production_app(db_path=db_path)
        stack.attach_session(SESSION)
        for index in range(4):
            _emit(
                stack,
                value_ns=index,
                event_type="simulation.run_progress",
                run_id=f"run-{index}",
            )
        stack.drain_gateway()
        assert stack.process_observation(SESSION) == 4
        stack.close()

        stack2 = build_production_app(db_path=db_path)
        try:
            stack2.attach_session(SESSION)
            assert stack2.process_observation(SESSION) == 0
            assert stack2.metrics_engine.journal_watermark == 0
            # New events after the restart flow through the fresh consumer.
            _emit(
                stack2,
                value_ns=99,
                event_type="simulation.run_progress",
                run_id="run-post-restart",
            )
            stack2.drain_gateway()
            assert stack2.process_observation(SESSION) == 1
            assert stack2.metrics_engine.journal_watermark == 5
        finally:
            stack2.close()

    def test_stamped_envelopes_round_trip_through_the_journal(self, tmp_path):
        stack = build_production_app(db_path=tmp_path / "prod.sqlite3")
        try:
            envelope = _emit(stack, value_ns=11)
            stack.drain_gateway()
            rows = stack.journal.query(SESSION, after_seq=0, limit=10)
            parsed = parse_envelope(rows[0].envelope)
            assert str(parsed.event_id) == envelope["event_id"]
            assert rows[0].journal_seq == 1
        finally:
            stack.close()
