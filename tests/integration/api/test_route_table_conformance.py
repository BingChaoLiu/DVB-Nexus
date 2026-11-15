"""Route-table conformance: the SPEC-500 §4 frozen inventory, ticket #13
resolution (ticket #48, REQ-API-500-001).

The authoritative freeze is the SPEC-500 §4 route table (ticket #13
"Resolution" lists SPEC-500 as 路由权威冻结). This test pins **every**
(method, path) pair of the composed §4 app against that table, verbatim:

- §4.1 topology ×5 and §4.7 scenario ×2 went LIVE with ticket #80
  (SPEC-502 persistence / SPEC-205 registry); §4.4 diagnosis ×3 answers
  501 in the unbound test composition (presence is the freeze
  obligation);
- §4.2 sessions ×8, §4.3 runs ×2 and §4.6 artifacts ×3 are wired;
- §4.5 observation ×8 (SPEC-305 logical endpoints, verbatim);
- the #80 additive §4.7/§4.8 rows (solution reveal + TSDuck call records);
- plus the #24 skeleton canary ``GET /api/v1/version`` — the only route
  outside the §4 inventory, grandfathered by the app-factory ticket.

Path parameter names are normalized before comparison: the freeze governs
methods and path shapes, and FastAPI renders the concrete parameter names
in the OpenAPI document.

The additive-only policy is asserted structurally: every OpenAPI path of
the composed app lives under the frozen prefix, and the composed path set
is a superset of the skeleton's (only-addition evolution).
"""

from __future__ import annotations

import pytest

from api.app import create_app
from api.versioning import API_V1_PREFIX

from rest_stack import build_rest_stack

pytestmark = pytest.mark.integration

#: The SPEC-500 §4 frozen route inventory (verbatim, spec order). Every
#: row is (method, path) with parameter placeholders normalized.
FROZEN_ROUTE_TABLE: tuple[tuple[str, str], ...] = (
    # §4.1 Topology
    ("POST", "/topologies"),
    ("GET", "/topologies"),
    ("GET", "/topologies/{id}"),
    ("PUT", "/topologies/{id}"),
    ("POST", "/topologies/{id}/validate"),
    # §4.2 Session (SPEC-200 lifecycle exhaustive mapping)
    ("POST", "/sessions"),
    ("POST", "/sessions/{id}/validate"),
    ("POST", "/sessions/{id}/start"),
    ("POST", "/sessions/{id}/pause"),
    ("POST", "/sessions/{id}/resume"),
    ("POST", "/sessions/{id}/stop"),
    ("DELETE", "/sessions/{id}"),
    ("GET", "/sessions/{id}/snapshot"),
    # §4.3 Run (ticket #13 Q-C-①: async job 202, fault_plan in body)
    ("POST", "/sessions/{id}/runs"),
    ("GET", "/sessions/{id}/runs/{run_id}"),
    # §4.4 Diagnosis / Recovery
    ("GET", "/sessions/{id}/diagnoses"),
    ("POST", "/sessions/{id}/runs/{run_id}/diagnose"),
    ("POST", "/sessions/{id}/runs/{run_id}/verify"),
    # §4.5 Observation (SPEC-305 §4 logical endpoints, verbatim)
    ("GET", "/sessions/{id}/observation/summary"),
    ("GET", "/sessions/{id}/events"),
    ("GET", "/sessions/{id}/timeline"),
    ("POST", "/sessions/{id}/metrics/query"),
    ("GET", "/sessions/{id}/alerts"),
    ("GET", "/sessions/{id}/health"),
    ("GET", "/sessions/{id}/exports/{export_id}"),
    ("POST", "/sessions/{id}/exports"),
    # §4.6 Artifact
    ("GET", "/artifacts/{id}"),
    ("GET", "/artifacts/{id}/content"),
    ("POST", "/artifacts/{id}/analyze"),
    # §4.7 Scenario
    ("GET", "/scenarios"),
    ("GET", "/scenarios/{id}"),
    # §4.7 Scenario — the ticket #80 additive solution-reveal gate
    # (SPEC-500 §4.7 approved amendment; 裁定 F)
    ("GET", "/scenarios/{id}/solution"),
    # §4.8 TSDuck call records — the ticket #80 additive read face
    # (SPEC-500 §4.8 approved amendment; SPEC-308 §7 nine fields)
    ("GET", "/sessions/{id}/tsduck/calls"),
)

#: The #24 skeleton canary — the only route outside the §4 inventory.
SKELETON_ROUTE = ("GET", "/version")

#: Prefix the freeze governs (SPEC-500 §3); canary + ws namespace excluded.
API_ROUTES = {SKELETON_ROUTE, *FROZEN_ROUTE_TABLE}


def _normalize(path: str) -> str:
    """Strip the frozen prefix and collapse parameter names to ``{...}``."""
    assert path.startswith(API_V1_PREFIX)
    body = path[len(API_V1_PREFIX) :]
    # Normalize {session_id} → {id} etc.: freeze governs shapes, not names.
    import re

    return re.sub(r"\{[^}]+\}", "{param}", body)


def _normalize_expected(path: str) -> str:
    import re

    return re.sub(r"\{[^}]+\}", "{param}", path)


@pytest.fixture
def composed_app(tmp_path):
    """A composed §4 app over the real backends on the test tmp root."""
    return build_rest_stack(tmp_path).app


class TestFrozenRouteTable:
    def test_route_table_matches_spec500_section4_verbatim(self, composed_app):
        app = composed_app
        openapi = app.openapi()
        actual: set[tuple[str, str]] = set()
        for path, methods in openapi["paths"].items():
            for method, operation in methods.items():
                if method in {"parameters", "description", "summary"}:
                    continue
                actual.add((method.upper(), _normalize(path)))
        expected = {
            (method, _normalize_expected(path))
            for method, path in API_ROUTES
        }
        missing = expected - actual
        extra = actual - expected
        assert not missing, f"§4 routes missing from the mount: {sorted(missing)}"
        assert not extra, f"routes outside the frozen table: {sorted(extra)}"

    def test_every_frozen_table_row_is_present_individually(self, composed_app):
        # Row-by-row walk of the §4 tables in spec order — the "逐条一致"
        # acceptance: each spec row must be independently discoverable.
        app = composed_app
        openapi = app.openapi()
        for method, path in FROZEN_ROUTE_TABLE:
            with_path = [
                p for p in openapi["paths"] if _normalize(p) == _normalize_expected(path)
            ]
            assert with_path, f"§4 row {method} {path} is not mounted"
            mounted_methods = {
                m.upper()
                for m in openapi["paths"][with_path[0]]
                if m not in {"parameters", "description", "summary"}
            }
            assert method in mounted_methods, (
                f"§4 row {method} {path}: method missing "
                f"(mounted: {sorted(mounted_methods)})"
            )

    def test_every_openapi_path_lives_under_frozen_prefix(self, composed_app):
        # Additive-only structural invariant (SPEC-500 §3), on the composed
        # app: no §4 route may escape /api/v1.
        app = composed_app
        openapi = app.openapi()
        assert openapi["paths"], "the composed app must generate OpenAPI"
        for path in openapi["paths"]:
            assert path.startswith(API_V1_PREFIX), (
                f"route {path!r} escapes the frozen /api/v1 prefix"
            )

    def test_composed_paths_extend_the_skeleton_additively(self, composed_app):
        skeleton = create_app().openapi()["paths"]
        composed = composed_app.openapi()["paths"]
        skeleton_normalized = {_normalize(p) for p in skeleton}
        composed_normalized = {_normalize(p) for p in composed}
        assert skeleton_normalized <= composed_normalized, (
            "route evolution removed a skeleton path — additive-only "
            "forbids removals inside /api/v1 (SPEC-500 §3)"
        )
