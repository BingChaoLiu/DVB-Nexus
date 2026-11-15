"""WS five-topic hint → REST pull closure (ticket #53, SPEC-305 §8,
REQ-OBS-305-006, 裁定 C/J).

Each SPEC-305 §8 topic is exercised over the PRODUCTION composition
(``build_production_app`` — one app serving both REST and the SPEC-501
route): the real emission point fires, the WS client receives the hint
frame, and the client's recovery action is the REST pull (the record
authority). Hints are droppable pointers; the journal frames and the REST
surfaces are the durable truth:

| topic                        | emitted by                  | REST pull                  |
|------------------------------|-----------------------------|----------------------------|
| observation.event_appended   | gateway commit subscriber   | GET  .../events            |
| observation.metric_updated   | consumer tick (watermark)   | POST .../metrics/query     |
| observation.alert_changed    | #52 AlertHint port → hub    | GET  .../alerts            |
| observation.health_changed   | query-plane roll-up change  | GET  .../health            |
| observation.export_progress  | export task completion      | GET  .../exports/{id}      |

The reconnect protocol (snapshot + journal_seq cursor + REST pull) is
pinned on the last test: journal frames replay hole-free across a
reconnect and the REST pull delivers the same gap.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from bootstrap import build_production_app

from tests.unit.application.observation.alerts._alerts_fixtures import (
    CannedReader,
    make_rule,
    sample_at,
)
from tests.unit.application.observation.test_gateway_accept import _raw_envelope

SESSION = "sess-ws"
DOMAIN = f"sim:{SESSION}"
WS_PATH = f"/ws/v1/sessions/{SESSION}"


def _subscribe(ws, last_journal_seq=None) -> None:
    msg = {"type": "subscribe", "session_id": SESSION}
    if last_journal_seq is not None:
        msg["last_journal_seq"] = last_journal_seq
    ws.send_json(msg)


def _receive_hint(ws, topic, *, max_frames=50) -> dict:
    """Collect frames until the wanted hint arrives (journal frames may
    interleave — the pump's combined stream)."""
    for _ in range(max_frames):
        frame = ws.receive_json()
        if frame["type"] == "hint" and frame["topic"] == topic:
            return frame
    raise AssertionError(f"hint {topic!r} never arrived")


def _make_stack(tmp_path, rule_set=None):
    stack = build_production_app(
        db_path=tmp_path / "ws.sqlite3",
        alert_rule_set=rule_set,
        export_id_factory=lambda: "export-ws-1",
    )
    return stack


def _emit(stack, **overrides) -> None:
    envelope = _raw_envelope(
        event_type=overrides.pop("event_type", "simulation.run_started"),
        session_id=overrides.pop("session_id", SESSION),
    )
    envelope["severity"] = overrides.pop("severity", "info")
    envelope["time"]["source"]["value_ns"] = overrides.pop("value_ns", 1)
    envelope["time"]["source"]["clock_domain"] = DOMAIN
    envelope["scope"]["run_id"] = overrides.pop("run_id", "run-1")
    result = stack.gateway.accept(envelope)
    assert result.outcome.value == "accepted", result


def test_event_appended_hint_pulls_the_journal(tmp_path):
    stack = _make_stack(tmp_path)
    try:
        with TestClient(stack.app) as client:
            with client.websocket_connect(WS_PATH) as ws:
                _subscribe(ws)
                ws.receive_json()  # ready (live from now)
                _emit(stack, value_ns=1)
                assert stack.drain_gateway() == 1
                frame = _receive_hint(ws, "observation.event_appended")
                assert frame["data"]["journal_seq"] == 1
                # The client's recovery action: the REST pull.
                page = client.get(f"/api/v1/sessions/{SESSION}/events")
                items = page.json()["data"]["items"]
                assert [i["journal_seq"] for i in items] == [1]
    finally:
        stack.close()


def test_metric_updated_hint_pulls_the_metric_query(tmp_path):
    stack = _make_stack(tmp_path)
    try:
        stack.attach_session(SESSION)
        with TestClient(stack.app) as client:
            with client.websocket_connect(WS_PATH) as ws:
                _subscribe(ws)
                ws.receive_json()  # ready
                for index in range(2):
                    _emit(
                        stack,
                        value_ns=index,
                        event_type="simulation.run_progress",
                        run_id=f"run-{index}",
                    )
                stack.drain_gateway()
                stack.process_observation(SESSION)
                frame = _receive_hint(ws, "observation.metric_updated")
                assert frame["data"]["journal_seq_watermark"] == 2
                # The pull: the metrics query answers over the consumed
                # watermark (the derived series may still be empty — the
                # honest contract is the query face, not fabricated points).
                pulled = client.post(
                    f"/api/v1/sessions/{SESSION}/metrics/query",
                    json={
                        "metric_names": ["simulation.virtual_time_ns"],
                        "start_ns": 0,
                        "end_ns": 1_000,
                        "step_ns": 500,
                        "clock_domain": DOMAIN,
                    },
                )
                assert pulled.status_code == 200, pulled.text
                assert pulled.json()["data"]["clock_domain"] == DOMAIN
    finally:
        stack.close()


def test_alert_changed_hint_pulls_the_alert_list(tmp_path):
    rule_set = _AlertRuleSet()
    stack = _make_stack(tmp_path, rule_set=rule_set)
    try:
        _emit(stack, value_ns=0)  # register the session (journal-known)
        stack.drain_gateway()
        with TestClient(stack.app) as client:
            with client.websocket_connect(WS_PATH) as ws:
                _subscribe(ws)
                ws.receive_json()  # ready
                reader = CannedReader()
                # The #52 firing cadence: a fresh threshold-met sample per
                # evaluation, for_duration elapsed across the two ticks.
                reader.add(sample_at(900, 200.0, session_id=SESSION, clock_domain=DOMAIN))
                stack.evaluate_alerts(
                    SESSION, now_ns=1_000, clock_domain=DOMAIN, reader=reader
                )
                reader.add(sample_at(900, 200.0, session_id=SESSION, clock_domain=DOMAIN))
                outcome = stack.evaluate_alerts(
                    SESSION, now_ns=2_000, clock_domain=DOMAIN, reader=reader
                )
                assert outcome.records, "the firing transition persists a record"
                pending_frame = _receive_hint(ws, "observation.alert_changed")
                assert pending_frame["data"]["state"] == "pending"
                frame = _receive_hint(ws, "observation.alert_changed")
                assert frame["data"]["state"] == "firing"
                # The pull: the alert list (record authority, #52).
                pulled = client.get(f"/api/v1/sessions/{SESSION}/alerts")
                body = pulled.json()["data"]
                assert body["total"] == 1
                assert body["items"][0]["state"] == "firing"
    finally:
        stack.close()


def test_health_changed_hint_pulls_the_health_face(tmp_path):
    rule_set = _AlertRuleSet()
    stack = _make_stack(tmp_path, rule_set=rule_set)
    try:
        _emit(stack, value_ns=0)  # register the session (journal-known)
        stack.drain_gateway()
        with TestClient(stack.app) as client:
            with client.websocket_connect(WS_PATH) as ws:
                _subscribe(ws)
                ws.receive_json()  # ready
                reader = CannedReader()
                # First evaluation: unknown (no input). Second: the rule
                # fires — the overall moves and ONE hint goes out.
                stack.query_service.health(
                    SESSION, clock_domain=DOMAIN, now_ns=1_000, reader=reader
                )
                reader.add(sample_at(900, 200.0, session_id=SESSION, clock_domain=DOMAIN))
                stack.query_service.health(
                    SESSION, clock_domain=DOMAIN, now_ns=1_000, reader=reader
                )
                reader.add(sample_at(900, 200.0, session_id=SESSION, clock_domain=DOMAIN))
                stack.query_service.health(
                    SESSION, clock_domain=DOMAIN, now_ns=2_000, reader=reader
                )
                baseline = _receive_hint(ws, "observation.health_changed")
                frame = _receive_hint(ws, "observation.health_changed")
                assert frame["data"]["overall"] != "unknown"
                pulled = client.get(
                    f"/api/v1/sessions/{SESSION}/health",
                    params={"clock_domain": DOMAIN, "now_ns": 3_000},
                )
                assert pulled.status_code == 200, pulled.text
    finally:
        stack.close()


def test_export_progress_hint_pulls_the_export_manifest(tmp_path):
    stack = _make_stack(tmp_path)
    try:
        _emit(stack, value_ns=3)
        stack.drain_gateway()
        with TestClient(stack.app) as client:
            with client.websocket_connect(WS_PATH) as ws:
                _subscribe(ws)
                ws.receive_json()  # ready
                created = client.post(f"/api/v1/sessions/{SESSION}/exports", json={})
                assert created.status_code == 200, created.text
                frame = _receive_hint(ws, "observation.export_progress")
                assert frame["data"]["status"] == "completed"
                export_id = frame["data"]["export_id"]
                pulled = client.get(
                    f"/api/v1/sessions/{SESSION}/exports/{export_id}"
                )
                assert pulled.status_code == 200, pulled.text
                assert pulled.json()["data"]["manifest"]["total_records"] == 1
    finally:
        stack.close()


def test_reconnect_recovery_is_cursor_replay_plus_rest_pull(tmp_path):
    """SPEC-305 §6 / SPEC-301 §5: hints lost ≠ data lost — the client
    reconnects with its journal_seq cursor (journal frames replay
    hole-free) and the REST pull serves the same gap."""
    stack = _make_stack(tmp_path)
    try:
        for index in range(5):
            _emit(stack, value_ns=index, run_id=f"run-{index}")
        stack.drain_gateway()

        with TestClient(stack.app) as client:
            # First connection: full replay 1..5.
            with client.websocket_connect(WS_PATH) as ws:
                _subscribe(ws, last_journal_seq=0)
                seqs = []
                while True:
                    frame = ws.receive_json()
                    if frame["type"] == "ready":
                        break
                    seqs.append(frame["envelope"]["journal_seq"])
                assert seqs == [1, 2, 3, 4, 5]

            # Three more events commit "while disconnected" (the hints a
            # disconnected client would have missed).
            for index in range(5, 8):
                _emit(stack, value_ns=index, run_id=f"run-{index}")
            stack.drain_gateway()

            # Reconnect with the cursor: the gap replays hole-free.
            with client.websocket_connect(WS_PATH) as ws:
                _subscribe(ws, last_journal_seq=5)
                seqs = []
                while True:
                    frame = ws.receive_json()
                    if frame["type"] == "ready":
                        break
                    seqs.append(frame["envelope"]["journal_seq"])
                assert seqs == [6, 7, 8]

            # The REST pull serves the same gap from the same cursor.
            pulled = client.get(
                f"/api/v1/sessions/{SESSION}/events", params={"limit": 100}
            )
            all_items = pulled.json()["data"]["items"]
            gap = [i["journal_seq"] for i in all_items if i["journal_seq"] > 5]
            assert gap == [6, 7, 8]
    finally:
        stack.close()


class _AlertRuleSet:
    """Delegates to the fixtures' single-rule set (the firing path)."""

    def __new__(cls):
        from application.observation.alerts.rules import HealthRuleSet

        return HealthRuleSet(ruleset_id="ws", version="1", profile="p", rules=(make_rule(),))
