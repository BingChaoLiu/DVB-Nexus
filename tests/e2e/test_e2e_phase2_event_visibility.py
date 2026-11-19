"""Phase 2 event visibility end-to-end — the ruling §10-7 endpoint
(ticket #129 AC: 事件经 WS journal 端到端可见).

The layered pipeline's four encapsulation namespaces (SPEC-303 §Phase2)
travel the ONE canonical delivery chain (ADR-0006 / §2bis): emitter →
``parse_envelope`` (the #128 guard passes registered types through) →
SPEC-502 journal rows → SPEC-501 WS journal frames → the REST pull face
the frontend ``useSessionStream`` closure reads. This test drives the
PRODUCTION composition (``build_production_app``, the #57/#58 e2e
posture) through a REST-submitted BBFRAME-layer fault (B2) and asserts:

- the journal replay over WS carries the new-namespace envelopes with
  their registered payload shapes (the #128 REPORT §1.2 key sets);
- the envelopes are ordinary SPEC-301 envelopes (run_id correlation +
  per-session contiguous ``journal_seq`` stamps — no fourth envelope);
- the SPEC-305 events pull face serves the same journal rows.

Determinism: the run is awaited to its terminal state and the gateway is
drained BEFORE the subscription, so the socket consumes pure REPLAY
(no live-delivery race). The BISS face's scramble/descramble payloads
are shape-pinned at the registry unit layer and delivered through the
same emitter/journal machinery (the #128 integration stub path); the
production BISS run needs the CSA backend DLL — honestly out of the CI
environment's reach (§5-11 NOT RUN discipline), so this e2e anchors the
mechanism on the gen.*/t2mi.*/bbframe. faces.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.e2e

from tests.e2e._fault_lab import FaultLab, load_scenario

#: The B2 injection as the run-request wire body — the fault-plan DTO
#: carries no ``layer`` field (语义不入 wire, #128): the backend derives
#: the layer from the fault-type registry (LAYER_BY_FAULT_TYPE).
BBHEADER_SYNC_FAULT_WIRE: dict[str, Any] = {
    "fault_id": "fd000000-0000-4000-8000-00000000b2001",
    "fault_type": "BBHEADER_SYNC_FAULT",
    "target_id": "mux-0",
    "parameters": {"field": "SYNCD", "mode": "corrupt"},
    "activation": {"kind": "packet_index", "packet_index": 3},
    "expected_observations": ["bbframe.recovery_failed"],
}

#: The new-namespace types this scenario's chain must deliver.
EXPECTED_PHASE2_TYPES = (
    "gen.stage_started",
    "gen.stage_completed",
    "gen.packet_sampled",
    "bbframe.stage_summary",
    "bbframe.recovery_failed",
    "t2mi.stage_summary",
)


def _replay_journal(ws, *, max_frames: int = 4000) -> list[dict[str, Any]]:
    """Collect the replayed journal envelopes until the ready frame."""
    envelopes: list[dict[str, Any]] = []
    for _ in range(max_frames):
        frame = ws.receive_json()
        if frame["type"] == "ready":
            return envelopes
        assert frame["type"] == "journal", frame
        envelopes.append(frame["envelope"])
    raise AssertionError(f"journal replay never ended within {max_frames} frames")


def _payloads(envelopes, event_type: str) -> list[dict[str, Any]]:
    return [e["payload"] for e in envelopes if e["event_type"] == event_type]


class TestPhase2EventVisibility:
    """分层 run 事件 → journal 落库 → WS journal 帧 → REST pull 可见."""

    def test_layered_run_events_are_visible_end_to_end(self, tmp_path) -> None:
        raw, _document = load_scenario("cc-discontinuity")
        with FaultLab(db_path=tmp_path / "phase2-visibility.sqlite") as lab:
            session_id = lab.create_session(raw)
            lab.start_session(session_id)

            inject_run_id = lab.submit_run(
                session_id, [BBHEADER_SYNC_FAULT_WIRE]
            )
            lab.await_run(session_id, inject_run_id)
            # Commit every queued event before subscribing — the socket
            # then consumes a deterministic replay (no live race).
            lab.drain()

            with TestClient(lab.stack.app) as client:
                with client.websocket_connect(
                    f"/ws/v1/sessions/{session_id}"
                ) as ws:
                    ws.send_json(
                        {
                            "type": "subscribe",
                            "session_id": session_id,
                            "last_journal_seq": 0,
                        }
                    )
                    envelopes = _replay_journal(ws)

            types = {envelope["event_type"] for envelope in envelopes}
            for expected in EXPECTED_PHASE2_TYPES:
                assert expected in types, (
                    f"{expected} never reached the WS journal frames; "
                    f"delivered types: {sorted(types)}"
                )

            # Ordinary SPEC-301 envelopes: per-session contiguous stamps,
            # run-scope correlation (no fourth envelope, ADR-0006).
            seqs = [envelope["journal_seq"] for envelope in envelopes]
            assert seqs == list(range(1, len(seqs) + 1))
            for envelope in envelopes:
                if envelope["event_type"].startswith(
                    ("gen.", "t2mi.", "bbframe.", "fault.")
                ):
                    assert envelope["scope"]["run_id"] == inject_run_id
                    assert envelope["scope"]["session_id"] == session_id

            # The registered payload shapes (the #128 REPORT §1.2 key
            # sets — the registry validators' contract, mirrored in
            # tests/unit/domain/observation/test_phase2_payload_registry.py).
            started = _payloads(envelopes, "gen.stage_started")
            assert started
            assert all(set(p) == {"layer"} for p in started)
            assert {p["layer"] for p in started} == {"TS", "BBFRAME", "T2MI"}

            completed = _payloads(envelopes, "gen.stage_completed")
            assert completed
            assert all(
                set(p) == {"layer", "item_count"} and p["item_count"] >= 1
                for p in completed
            )

            sampled = _payloads(envelopes, "gen.packet_sampled")
            assert sampled  # the injection point slot is always sampled
            assert all(
                set(p) == {"layer", "packet_index", "byte_size", "sha256"}
                and p["byte_size"] > 0
                for p in sampled
            )
            assert any(
                p["layer"] == "BBFRAME" and p["packet_index"] == 3
                for p in sampled
            ), "the injection-point slot must be sampled (票面 hard rule)"

            summary = _payloads(envelopes, "bbframe.stage_summary")
            assert summary and set(summary[0]) == {
                "frame_count",
                "n_ups_distribution",
                "stuffing_ratio",
            }

            recovery = _payloads(envelopes, "bbframe.recovery_failed")
            assert recovery and set(recovery[0]) == {
                "failure_count",
                "first_failed_frame_index",
            }
            assert recovery[0]["failure_count"] >= 1
            assert isinstance(recovery[0]["first_failed_frame_index"], int)

            t2mi_summary = _payloads(envelopes, "t2mi.stage_summary")
            assert t2mi_summary and set(t2mi_summary[0]) == {
                "packet_count",
                "padding_count",
                "packet_type_distribution",
                "plp_distribution",
            }
            assert t2mi_summary[0]["packet_count"] >= 1

            applied = _payloads(envelopes, "fault.applied")
            assert applied and applied[0]["layer"] == "BBFRAME"

            # --- the REST pull face (the useSessionStream closure) ------
            pulled = lab.events(session_id)
            pulled_types = {item["event_type"] for item in pulled}
            for expected in EXPECTED_PHASE2_TYPES:
                assert expected in pulled_types
            pulled_recovery = [
                item
                for item in pulled
                if item["event_type"] == "bbframe.recovery_failed"
            ]
            assert pulled_recovery[0]["scope"]["run_id"] == inject_run_id
            ws_frame = next(
                envelope
                for envelope in envelopes
                if envelope["event_type"] == "bbframe.recovery_failed"
            )
            assert (
                pulled_recovery[0]["journal_seq"] == ws_frame["journal_seq"]
            ), "WS frame and REST pull read the same journal row"


class TestPhase2DiagnoseFace:
    """The #138 diagnose-face 点亮 on the PRODUCTION composition
    (SPEC-306 §Phase2 补丁修订): the layered run's evidence events enter
    the engine's expanded input family, the run-completion trigger
    evaluates, and the diagnose endpoint serves the Phase 2 candidate —
    its anchor chain resolvable end to end (candidate → journal_seq →
    locator → artifact content)."""

    def test_layered_evidence_run_lights_the_diagnose_face(self, tmp_path) -> None:
        raw, _document = load_scenario("cc-discontinuity")
        with FaultLab(db_path=tmp_path / "phase2-diagnose.sqlite") as lab:
            session_id = lab.create_session(raw)
            lab.start_session(session_id)

            inject_run_id = lab.submit_run(
                session_id, [BBHEADER_SYNC_FAULT_WIRE]
            )
            lab.await_run(session_id, inject_run_id)
            lab.drain()

            # The run-completion trigger evaluated on the committed
            # terminal event; the idempotent endpoint re-serves it.
            report = lab.diagnose(session_id, inject_run_id)
            # The trigger's lifecycle events (raised) were published
            # during the drain's commit fan-out — one more sweep commits
            # them (publish-then-drain discipline).
            lab.drain()
            candidates = report["candidates"]
            assert [c["code"] for c in candidates] == ["DIAG_BBHEADER_SYNC_FAULT"]
            candidate = candidates[0]
            assert candidate["rule_id"] == "DIA-BBHEADER-SYNC-FAULT"
            assert candidate["confidence"] == "medium"
            # The Phase 2 anchor state — exact key set, no fabricated
            # pid/packet_index (无对应定位字段不虚填).
            evidence = candidate["evidence"]
            assert set(evidence) == {"artifact_id", "locator"}
            assert set(evidence["locator"]) == {
                "failure_count",
                "first_failed_frame_index",
            }
            assert evidence["locator"]["failure_count"] >= 1
            assert isinstance(evidence["locator"]["first_failed_frame_index"], int)

            # The anchor chain resolves end to end: the Inner TS artifact
            # the evidence points at serves its content.
            content = lab.artifact_content(evidence["artifact_id"])
            assert len(content) > 0 and len(content) % 188 == 0

            # The stored row + the raised event agree (the lifecycle
            # committed through the two-state registry gate).
            rows = lab.diagnoses(session_id)
            assert [row["code"] for row in rows] == ["DIAG_BBHEADER_SYNC_FAULT"]
            raised = [
                item
                for item in lab.events(session_id)
                if item["event_type"] == "diagnosis.raised"
            ]
            assert raised and raised[0]["payload"]["evidence"]["locator"] == {
                "first_failed_frame_index": evidence["locator"][
                    "first_failed_frame_index"
                ],
                "failure_count": evidence["locator"]["failure_count"],
            }
            assert "pid" not in raised[0]["payload"]["evidence"]
