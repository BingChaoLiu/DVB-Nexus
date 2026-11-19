"""REST structure face — the json_map chain endpoint (#128, additive).

GET /artifacts/{id}/structure over the real stack: a REST-submitted
layered run (T2MI_PLP_MISMATCH — the wire DTO carries no layer; the
composition derives it from the registry) lands the transmitted T2-MI
faces, and the structure views read them through the application
assembly.  The honest refusal faces: unknown artifact → 404, unknown
view / plain MPEG-TS artifact → 400.
"""

from __future__ import annotations

from typing import Any

import pytest

from rest_stack import build_rest_stack, make_generator_config, wire_generator_config

pytestmark = pytest.mark.integration

_POLL_BOUND = 2000

_T2MI_FAULT_PLAN = [
    {
        "fault_type": "T2MI_PLP_MISMATCH",
        "target_id": "enc-0",
        "parameters": {"expected_plp": 0, "actual_plp": 1},
        "activation": {"kind": "session_start", "packet_index": None},
        "expected_observations": ["t2mi.plp_mismatch"],
    }
]

_MVP_FAULT_PLAN = [
    {
        "fault_type": "CC_DISCONTINUITY",
        "target_id": "demux-0:pid:0x0100",
        "parameters": {"delta": 3},
        "activation": {"kind": "packet_index", "packet_index": 10},
        "expected_observations": ["ts.continuity_error"],
    }
]


@pytest.fixture
def stacked(api_client, tmp_path) -> tuple[Any, Any]:
    rest = build_rest_stack(tmp_path)
    client = api_client.build(rest.app)
    with client.client:
        yield rest, client


def _submit_run(client, plan: list[dict]) -> tuple[str, dict]:
    response = client.post(
        "/api/v1/sessions",
        json={"topology_id": "topo-1", "seed": 20260101},
    )
    session_id = response.json()["session_id"]
    client.post(f"/api/v1/sessions/{session_id}/validate")
    client.post(f"/api/v1/sessions/{session_id}/start")
    accepted = client.post(
        f"/api/v1/sessions/{session_id}/runs",
        json={
            "config": wire_generator_config(make_generator_config()),
            "fault_plan": plan,
        },
    ).json()
    for _ in range(_POLL_BOUND):
        body = client.get(
            f"/api/v1/sessions/{session_id}/runs/{accepted['run_id']}"
        ).json()
        if body["status"] != "running":
            return session_id, body
        client.get("/api/v1/version")  # event-driven yield point
    pytest.fail("run did not reach a terminal state")


class TestArtifactStructureEndpoint:
    def test_layered_run_serves_all_three_views(self, stacked) -> None:
        _, client = stacked
        _, run_body = _submit_run(client, _T2MI_FAULT_PLAN)
        assert run_body["status"] == "completed"
        faulted = next(
            artifact
            for artifact in run_body["artifacts"]
            if artifact["kind"] == "faulted_ts"
        )
        artifact_id = faulted["artifact_id"]

        t2mi = client.get(
            f"/api/v1/artifacts/{artifact_id}/structure",
            params={"view": "t2mi"},
        )
        assert t2mi.status_code == 200
        document = t2mi.json()
        assert document["view"] == "t2mi"
        assert document["packet_count"] >= 1
        assert set(document["packets"][0]) == {
            "packet_index",
            "packet_type",
            "packet_counter",
            "superframe_index",
            "reserved",
            "payload_kind",
            "payload_bytes_len",
            "crc32_valid",
            "frame_index",
            "interleaving_frame_start",
            "plp_id",
        }

        bbframe = client.get(
            f"/api/v1/artifacts/{artifact_id}/structure",
            params={"view": "bbframe"},
        )
        assert bbframe.status_code == 200
        frame_row = bbframe.json()["frames"][0]
        assert set(frame_row) == {
            "frame_index",
            "matype",
            "upl",
            "dfl",
            "sync",
            "syncd",
            "crc8_valid",
            "up_count",
            "up_indices",
            "state",
        }

        inner = client.get(
            f"/api/v1/artifacts/{artifact_id}/structure",
            params={"view": "ts"},
        )
        assert inner.status_code == 200
        inner_document = inner.json()
        assert inner_document["view"] == "ts"
        assert set(inner_document) == {
            "view",
            "artifact_ref",
            "packet_count",
            "up_assembled",
            "stuffing_bytes",
            "reconstruction_status",
            "first_failure_ref",
            "anomalies",
        }

    def test_expected_plp_param_drives_the_b1_face(self, stacked) -> None:
        _, client = stacked
        _, run_body = _submit_run(client, _T2MI_FAULT_PLAN)
        faulted = next(
            artifact
            for artifact in run_body["artifacts"]
            if artifact["kind"] == "faulted_ts"
        )
        response = client.get(
            f"/api/v1/artifacts/{faulted['artifact_id']}/structure",
            params={"view": "ts", "expected_plp": 0},
        )
        assert response.status_code == 200
        # 缺失 ≠ 零: the explicit empty failed face for the drifted PLP.
        assert response.json()["reconstruction_status"] == "failed"

    def test_unknown_view_is_a_bad_request(self, stacked) -> None:
        _, client = stacked
        _, run_body = _submit_run(client, _T2MI_FAULT_PLAN)
        artifact_id = run_body["artifacts"][0]["artifact_id"]
        response = client.get(
            f"/api/v1/artifacts/{artifact_id}/structure",
            params={"view": "rf"},
        )
        assert response.status_code == 400

    def test_unknown_artifact_is_not_found(self, stacked) -> None:
        _, client = stacked
        response = client.get(
            "/api/v1/artifacts/does-not-exist/structure",
            params={"view": "t2mi"},
        )
        assert response.status_code == 404

    def test_plain_ts_artifact_is_refused_honestly(self, stacked) -> None:
        _, client = stacked
        _, run_body = _submit_run(client, _MVP_FAULT_PLAN)
        assert run_body["status"] == "completed"
        faulted = next(
            artifact
            for artifact in run_body["artifacts"]
            if artifact["kind"] == "faulted_ts"
        )
        response = client.get(
            f"/api/v1/artifacts/{faulted['artifact_id']}/structure",
            params={"view": "t2mi"},
        )
        assert response.status_code == 400
        assert (
            response.json()["error"]["error_code"] == "SIM_STRUCTURE_NOT_T2MI"
        )
