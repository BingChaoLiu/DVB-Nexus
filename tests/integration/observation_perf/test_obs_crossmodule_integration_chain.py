"""Cross-module observation integration chain — ticket #57 (OBS-G).

The OBSERVATION-INTEGRATION-CONTRACT §8 integration order, walked over
the REAL production composition root (``bootstrap.build_production_app``,
ticket #53) and nothing else:

1. 与生产者共享契约测试          → ``test_obs_producer_contract_conformance.py``
2. Event Gateway + Journal       → this file, step 2 asserts
3. Simulation lifecycle events   → real ``SimulationRuntime`` publisher wiring
4. TS Core normalized events     → fixture producer slot (G3: analysis bridge
                                   in-flight, #58) through the same publisher face
5. Metrics + Timeline            → checkpointed metrics consumer + timeline recorder
6. Health/Alerts                 → alert evaluation over the wired metrics reader
7. Query API                     → the #53 observation query service faces
8. Load / replay / retention     → ``test_obs_perf_profile.py`` (``slow`` marker)

Every consumed face is a prior ticket's public surface — #57 changes no
production code (dispatch seam ownership); a failure here is a defect
report to the owning ticket.
"""

from __future__ import annotations

import uuid

import pytest

from adapters.storage.checkpoints import SqliteCheckpointStore
from adapters.storage.journal import QUERY_LIMIT_HARD_CAP
from bootstrap import build_production_app
from domain.observation import parse_envelope

from tests.unit.application.observation.test_gateway_accept import _raw_envelope
from tests.unit.simulation.runtime import _sim_c_builders as b

SESSION = "sess-obs-g-chain"
DOMAIN = f"sim:{SESSION}"


def _emit(stack, event_type: str, *, value_ns: int, run_id=None, payload=None,
          producer_id: str = "sim-engine", session_id: str = SESSION) -> dict:
    envelope = _raw_envelope(
        event_id=str(uuid.uuid4()),
        event_type=event_type,
        producer_id=producer_id,
        session_id=session_id,
        payload=payload,
    )
    envelope["severity"] = "info"
    envelope["time"]["source"] = {
        "value_ns": value_ns,
        "clock_domain": f"sim:{session_id}",
        "clock_epoch": 0,
    }
    envelope["scope"]["run_id"] = run_id
    result = stack.gateway.accept(envelope)
    assert result.outcome.value == "accepted", (event_type, result)
    return envelope


# ============================================================================
# CONTRACT §8 steps 2-7 — one ordered walk over the production composition
# ============================================================================


class TestIntegrationOrderWalk:
    """The §8 order as one deterministic scenario: each step's outputs are
    the next step's inputs, all over ``build_production_app``."""

    def test_steps_2_through_7_over_production_stack(self, tmp_path):
        from fastapi.testclient import TestClient

        stack = build_production_app(db_path=tmp_path / "chain.sqlite3")
        try:
            client = TestClient(stack.app)

            # --- step 3: simulation lifecycle events through the REAL
            # producer face: the #53/#58 composition root binds the
            # stack's runtime to the gateway, so the STACK's own runtime
            # emits into the journal (SPEC-200 §7 sink discipline).
            import asyncio

            async def produce_lifecycle():
                await stack.runtime.create_session(
                    b.session_spec(session_id=SESSION)
                )
                await stack.runtime.validate_session(SESSION)
                await stack.runtime.start(SESSION)
                await stack.runtime.start_run(SESSION, run_id="run-a")
                await stack.runtime.report_run_progress(
                    SESSION, "run-a", {"packets": 10}
                )
                await stack.runtime.complete_run(SESSION, "run-a")
                await stack.runtime.stop(SESSION)

            asyncio.run(produce_lifecycle())

            # --- step 4: TS Core normalized facts (G3 fixture producer
            # slot) — batch statistics with provenance axes, never
            # per-packet events (CONTRACT §4).
            _emit(
                stack,
                "ts.packet_batch_observed",
                value_ns=50_000_000,
                run_id="run-a",
                payload={
                    "packet_count": 10_000,
                    "byte_count": 1_880_000,
                    "duration_ns": 500_000_000,
                    "source": "internal_parser",
                    "confidence": "simulated",
                },
            )
            for index in range(3):
                _emit(
                    stack,
                    "ts.continuity_error",
                    value_ns=50_000_000 + index,
                    run_id="run-a",
                    payload={
                        "pid": 256,
                        "source": "internal_parser",
                        "confidence": "parsed",
                    },
                )

            # --- step 2 (checked at its observation point): gateway →
            # journal, everything committed in producer-submission order,
            # stamped by the journal alone.
            committed = stack.drain_gateway()
            rows = stack.journal.query(SESSION, after_seq=0, limit=100)
            # 6 lifecycle events (created/started/run_started/progress/
            # completed/stopped) + 4 TS facts = 10 committed in order.
            assert len(rows) == committed == 10
            assert [row.journal_seq for row in rows] == list(range(1, 11))
            for raw in rows:
                envelope = parse_envelope(raw.envelope)
                assert envelope.event_id  # round-trips the frozen face

            # --- step 5a: metrics consumption (checkpointed consumer).
            stack.attach_session(SESSION)
            assert stack.process_observation(SESSION) == 10
            consumer = stack.consumers[SESSION]
            assert consumer.lag() == 0
            assert consumer.checkpoint_seq() == 10
            assert stack.metrics_engine.journal_watermark == 10

            # --- step 5b: timeline records for every committed event,
            # evidence chain intact (event_id + journal_seq preserved).
            page = stack.timeline_service.query(
                _timeline_filter(SESSION, clock_domain=DOMAIN)
            )
            event_records = [r for r in page.records if r.record_kind == "event"]
            assert len(event_records) == 10
            assert sorted(r.journal_seq for r in event_records) == list(range(1, 11))

            # --- step 6: alert evaluation over the wired metrics reader —
            # the healthy ingest yields no firing alerts (deterministic
            # virtual-time tick; the lag rule stays quiet at lag 0).
            transitions = stack.evaluate_alerts(
                SESSION, now_ns=1_000, clock_domain=DOMAIN
            )
            alert_page = stack.alert_service.list(_alert_request(SESSION))
            assert all(item.state != "firing" for item in alert_page.items)

            # --- step 7: query API over committed records only.
            summary = client.get(
                f"/api/v1/sessions/{SESSION}/observation/summary"
            )
            assert summary.status_code == 200
            assert summary.json()["data"]["journal_seq_watermark"] == 10

            events_page = client.get(f"/api/v1/sessions/{SESSION}/events")
            assert events_page.status_code == 200
            items = events_page.json()["data"]["items"]
            assert [item["journal_seq"] for item in items] == list(range(1, 11))

            metrics_page = client.post(
                f"/api/v1/sessions/{SESSION}/metrics/query",
                json={
                    "metric_names": ["ts.continuity_error_total"],
                    "start_ns": 0,
                    "end_ns": 1_000_000_000,
                    "step_ns": 100_000_000,
                    "clock_domain": DOMAIN,
                    "filters": {"session_id": SESSION},
                },
            )
            assert metrics_page.status_code == 200
            series = metrics_page.json()["data"]["series"]
            assert series, "the ingested ts.* facts are queryable"

            # WS hint pointer (SPEC-305 §8): the consumer tick emitted the
            # metric_updated pull pointer through the production seam.
            hints: list[tuple[str, str]] = []
            original = stack.hint_publisher.publish

            def recording(session_id, topic, data):
                hints.append((session_id, topic))
                original(session_id, topic, data)

            stack.hint_publisher.publish = recording
            _emit(
                stack,
                "simulation.run_progress",
                value_ns=60_000_000,
                run_id="run-b",
            )
            stack.drain_gateway()
            stack.process_observation(SESSION)
            assert ("observation.event_appended" in [t for _, t in hints]) or (
                "observation.metric_updated" in [t for _, t in hints]
            )
        finally:
            stack.close()

    def test_step_3_production_composition_binds_the_runtime_sink(
        self, tmp_path
    ):
        """Producer-contract checklist row pinned behaviorally (SPEC-200
        §7 + IC §3): the production composition root wires the runtime's
        emitter to the gateway (``SimulationRuntime(event_sink=gateway)``
        — the #58 composition fix that landed during the #57 window;
        before it, the #53 stack shipped sink-unbound, emission opt-in).
        A runtime-driven session now reaches the journal end to end."""
        stack = build_production_app(db_path=tmp_path / "sinkbound.sqlite3")
        try:
            import asyncio

            async def produce():
                await stack.runtime.create_session(
                    b.session_spec(session_id="sess-sinkbound")
                )
                await stack.runtime.validate_session("sess-sinkbound")
                await stack.runtime.start("sess-sinkbound")

            asyncio.run(produce())
            committed = stack.drain_gateway()
            rows = stack.journal.query("sess-sinkbound", after_seq=0, limit=10)
            assert committed >= 2
            assert [row.journal_seq for row in rows] == list(
                range(1, committed + 1)
            )
            types = {row.event_type for row in rows}
            assert "simulation.session_created" in types
            assert "simulation.session_started" in types
            # Producer identity rides the SPEC-300 §12 publisher face.
            envelope = parse_envelope(rows[0].envelope)
            assert envelope.producer.producer_id == "simulation-runtime"
        finally:
            stack.close()


def _timeline_filter(session_id: str, *, clock_domain: str):
    from application.observation.timeline.service import TimelineFilter

    # A pinned domain (SPEC-303 §4: no mixed-domain single order claimed).
    return TimelineFilter(session_id=session_id, clock_domain=clock_domain)


def _alert_request(session_id: str):
    from application.observation.alerts.service import AlertListRequest

    return AlertListRequest(session_id=session_id)


# ============================================================================
# CONTRACT §8 step 5 — parallel consumers over ONE journal
# ============================================================================


class TestParallelConsumption:
    """Metrics consumer + timeline recorder + diagnosis trigger read the
    same committed stream without interfering: independent checkpoints,
    complete per-consumer views (SPEC-300 §7 steps 5-6)."""

    def test_two_consumers_progress_independently(self, tmp_path):
        stack = build_production_app(db_path=tmp_path / "parallel.sqlite3")
        try:
            # A second consumer tailing the same session with its own id.
            from application.observation.consumer import (
                ConsumerConfig,
                JournalTailingConsumer,
            )

            side_rows: list[int] = []
            side = JournalTailingConsumer(
                journal=stack.journal,
                checkpoints=SqliteCheckpointStore(stack.connection),
                session_id=SESSION,
                consumer_id="side-reader",
                handler=lambda record: side_rows.append(record.journal_seq),
                config=ConsumerConfig(batch_size=3),
            )

            stack.attach_session(SESSION)
            for index in range(7):
                _emit(
                    stack,
                    "simulation.run_progress",
                    value_ns=index,
                    run_id=f"run-{index}",  # distinct runs: no coalescing
                )
            stack.drain_gateway()

            assert stack.process_observation(SESSION) == 7
            assert side.catch_up() == 7
            assert stack.consumers[SESSION].checkpoint_seq() == 7
            assert side_rows == list(range(1, 8))
            # The metrics consumer's durable cursor is untouched by the
            # side reader (independent checkpoints — SPEC-300 §7).
            assert side.checkpoint_seq() == 7
            assert stack.metrics_engine.journal_watermark == 7
        finally:
            stack.close()

    def test_query_limit_constants_are_the_single_bound(self, tmp_path):
        """The journal QUERY_LIMIT_* constants bound the consumer and the
        query face alike (SPEC-305 §5 同源 — one authority, no parallel
        cap)."""
        stack = build_production_app(db_path=tmp_path / "bounds.sqlite3")
        try:
            stack.attach_session(SESSION)
            consumer = stack.consumers[SESSION]
            assert consumer._batch_size <= QUERY_LIMIT_HARD_CAP  # noqa: SLF001
        finally:
            stack.close()


# ============================================================================
# CONTRACT §6 — structured outcomes + §8 restart recovery
# ============================================================================


class TestStructuredOutcomesAndRecovery:
    """IC §6 (accepted/duplicate/rejected) + SPEC-300 §8 (checkpoint
    restart) over the production stack."""

    def test_duplicate_through_production_stack_is_idempotent(self, tmp_path):
        stack = build_production_app(db_path=tmp_path / "dedup.sqlite3")
        try:
            stack.attach_session(SESSION)
            envelope = _emit(stack, "simulation.session_created", value_ns=1)
            stack.drain_gateway()

            before = stack.gateway.metrics()
            again = stack.gateway.accept(dict(envelope))
            assert again.outcome.value == "duplicate"
            assert again.journal_seq == 1
            stack.drain_gateway()
            after = stack.gateway.metrics()
            assert after.duplicate == before.duplicate + 1
            assert stack.process_observation(SESSION) == 1  # no redelivery
        finally:
            stack.close()

    def test_restart_continues_and_total_order_is_stable(self, tmp_path):
        db_path = tmp_path / "restart.sqlite3"
        stack = build_production_app(db_path=db_path)
        stack.attach_session(SESSION)
        for index in range(5):
            _emit(
                stack,
                "simulation.run_progress",
                value_ns=index,
                run_id=f"run-{index}",
            )
        stack.drain_gateway()
        stack.process_observation(SESSION)
        rows_before = [
            row.journal_seq for row in stack.journal.query(SESSION, after_seq=0, limit=100)
        ]
        stack.close()

        stack2 = build_production_app(db_path=db_path)
        try:
            stack2.attach_session(SESSION)
            assert stack2.process_observation(SESSION) == 0  # checkpoint held
            rows_after = [
                row.journal_seq
                for row in stack2.journal.query(SESSION, after_seq=0, limit=100)
            ]
            assert rows_after == rows_before == [1, 2, 3, 4, 5]
        finally:
            stack2.close()
