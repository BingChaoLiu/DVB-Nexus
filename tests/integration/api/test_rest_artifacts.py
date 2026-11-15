"""REST artifact routes over the #42 store (SPEC-500 §4.6 / SPEC-503 §5,
ticket #48).

The full path runs through the real stack: a REST-submitted run lands tee
artifacts via the #43 sink, and the REST read boundary (metadata /
download with Range) consumes the #42 ``read_by_artifact`` + index row —
404 for unknown ids, **503** for corrupt content (SPEC-503 §7 row 4,
``OBS_STORAGE_WRITE_FAILURE`` family), 206 single-range downloads.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

import pytest

from rest_stack import RestStack, build_rest_stack, make_generator_config, wire_generator_config

pytestmark = pytest.mark.integration

_POLL_BOUND = 2000


@pytest.fixture
def stacked(api_client, tmp_path) -> tuple[RestStack, Any]:
    """One composed REST stack behind a single-portal TestClient."""
    rest = build_rest_stack(tmp_path)
    client = api_client.build(rest.app)
    with client.client:
        yield rest, client


def _wait_terminal(client, session_id: str, run_id: str) -> dict:
    for _ in range(_POLL_BOUND):
        body = client.get(f"/api/v1/sessions/{session_id}/runs/{run_id}").json()
        if body["status"] != "running":
            return body
        client.get("/api/v1/version")  # event-driven yield point
    pytest.fail("run did not reach a terminal state")


def _completed_run_artifacts(client) -> dict:
    """Drive one REST run to completion and return the GET run body."""
    response = client.post(
        "/api/v1/sessions",
        json={"topology_id": "topo-1", "seed": 20260101},
    )
    session_id = response.json()["session_id"]
    client.post(f"/api/v1/sessions/{session_id}/validate")
    client.post(f"/api/v1/sessions/{session_id}/start")
    plan = [
        {
            "fault_type": "CC_DISCONTINUITY",
            "target_id": "demux-0:pid:0x0100",
            "parameters": {"delta": 3},
            "activation": {"kind": "packet_index", "packet_index": 10},
            "expected_observations": ["ts.continuity_error"],
        }
    ]
    accepted = client.post(
        f"/api/v1/sessions/{session_id}/runs",
        json={
            "config": wire_generator_config(make_generator_config()),
            "fault_plan": plan,
        },
    ).json()
    return _wait_terminal(client, session_id, accepted["run_id"])


def _artifact(client, result: dict, kind: str) -> dict:
    return next(a for a in result["artifacts"] if a["kind"] == kind)


class TestArtifactMetadata:
    def test_metadata_route_serves_index_row(self, stacked):
        rest, client = stacked
        result = _completed_run_artifacts(client)
        baseline = _artifact(client, result, "generated_ts")
        response = client.get(f"/api/v1/artifacts/{baseline['artifact_id']}")
        assert response.status_code == 200, response.text
        meta = response.json()
        assert meta["artifact_id"] == baseline["artifact_id"]
        assert meta["kind"] == "generated_ts"
        assert meta["sha256"] == baseline["sha256"]
        assert meta["byte_size"] == baseline["byte_size"]
        assert meta["packet_count"] == result["packet_count"]
        assert meta["packet_size"] == 188
        assert meta["config_hash"] == result["config_hash"]
        assert meta["generator_version"] == result["generator_version"]
        assert meta["run_id"] == result["run_id"]
        assert meta["session_id"]
        assert meta["created_at_utc_ms"] > 0

    def test_relative_path_never_leaks_an_absolute_location(self, stacked):
        # SPEC-003 §2.7 / SPEC-503 §6: metadata carries the layout-relative
        # path only — no drive letters, no store root, no backslashes.
        _, client = stacked
        result = _completed_run_artifacts(client)
        baseline = _artifact(client, result, "generated_ts")
        meta = client.get(f"/api/v1/artifacts/{baseline['artifact_id']}").json()
        relative = meta["relative_path"]
        assert not relative.startswith("/")
        assert not re.match(r"^[A-Za-z]:", relative)
        assert "\\" not in relative
        assert relative.startswith("artifacts/")

    def test_unknown_artifact_is_404_envelope(self, stacked):
        _, client = stacked
        response = client.get("/api/v1/artifacts/no-such-id")
        assert response.status_code == 404
        body = response.json()
        assert body["error"]["error_code"] == "PLT_ARTIFACT_NOT_FOUND"
        assert body["request_id"]


class TestArtifactDownload:
    def test_full_download_matches_registered_digest(self, stacked):
        _, client = stacked
        result = _completed_run_artifacts(client)
        baseline = _artifact(client, result, "generated_ts")
        response = client.get(
            f"/api/v1/artifacts/{baseline['artifact_id']}/content"
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/octet-stream")
        assert response.headers["accept-ranges"] == "bytes"
        assert len(response.content) == baseline["byte_size"]
        assert hashlib.sha256(response.content).hexdigest() == baseline["sha256"]

    def test_range_request_answers_206_with_content_range(self, stacked):
        _, client = stacked
        result = _completed_run_artifacts(client)
        baseline = _artifact(client, result, "generated_ts")
        response = client.get(
            f"/api/v1/artifacts/{baseline['artifact_id']}/content",
            headers={"range": "bytes=0-99"},
        )
        assert response.status_code == 206
        assert len(response.content) == 100
        assert response.headers["content-range"] == (
            f"bytes 0-99/{baseline['byte_size']}"
        )

    def test_open_ended_range_runs_to_the_end(self, stacked):
        _, client = stacked
        result = _completed_run_artifacts(client)
        baseline = _artifact(client, result, "generated_ts")
        response = client.get(
            f"/api/v1/artifacts/{baseline['artifact_id']}/content",
            headers={"range": "bytes=188-"},
        )
        assert response.status_code == 206
        assert len(response.content) == baseline["byte_size"] - 188

    def test_suffix_range_returns_the_tail(self, stacked):
        _, client = stacked
        result = _completed_run_artifacts(client)
        baseline = _artifact(client, result, "generated_ts")
        response = client.get(
            f"/api/v1/artifacts/{baseline['artifact_id']}/content",
            headers={"range": "bytes=-188"},
        )
        assert response.status_code == 206
        assert len(response.content) == 188

    def test_malformed_range_is_400_envelope(self, stacked):
        _, client = stacked
        result = _completed_run_artifacts(client)
        baseline = _artifact(client, result, "generated_ts")
        response = client.get(
            f"/api/v1/artifacts/{baseline['artifact_id']}/content",
            headers={"range": "bytes=1-2, 5-9"},
        )
        assert response.status_code == 400
        body = response.json()
        assert body["error"]["error_code"] == "HTTP_RANGE_MALFORMED"

    def test_unsatisfiable_range_is_416_with_content_range(self, stacked):
        _, client = stacked
        result = _completed_run_artifacts(client)
        baseline = _artifact(client, result, "generated_ts")
        response = client.get(
            f"/api/v1/artifacts/{baseline['artifact_id']}/content",
            headers={"range": f"bytes={baseline['byte_size'] + 1}-"},
        )
        assert response.status_code == 416
        assert response.headers["content-range"] == (
            f"bytes */{baseline['byte_size']}"
        )
        # 416 renders through the unified envelope (framework fallback).
        assert response.json()["error"]["error_code"] == "HTTP_416"

    def test_unknown_artifact_download_is_404(self, stacked):
        _, client = stacked
        response = client.get("/api/v1/artifacts/no-such-id/content")
        assert response.status_code == 404
        assert response.json()["error"]["error_code"] == "PLT_ARTIFACT_NOT_FOUND"

    def test_corrupted_content_is_503_write_failure_family(self, stacked):
        # SPEC-503 §7 row 4 through the REST boundary: a tampered stored
        # file fails the digest gate at download → 503 OBS_STORAGE_WRITE_...
        rest, client = stacked
        result = _completed_run_artifacts(client)
        baseline = _artifact(client, result, "faulted_ts")
        physical = (
            rest.store.root
            / "artifacts"
            / baseline["sha256"][:2]
            / f"{baseline['sha256']}.ts"
        )
        physical.write_bytes(b"\x00" * baseline["byte_size"])
        response = client.get(
            f"/api/v1/artifacts/{baseline['artifact_id']}/content"
        )
        assert response.status_code == 503, response.text
        body = response.json()
        assert body["error"]["error_code"] == "OBS_STORAGE_WRITE_FAILURE"
        assert body["error"]["retryable"] is False


class TestAnalyzeRoute:
    def test_analyze_route_is_a_501_mount_point(self, stacked):
        _, client = stacked
        result = _completed_run_artifacts(client)
        baseline = _artifact(client, result, "generated_ts")
        response = client.post(
            f"/api/v1/artifacts/{baseline['artifact_id']}/analyze"
        )
        assert response.status_code == 501
        assert response.json()["error"]["error_code"] == "HTTP_501"
