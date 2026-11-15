"""Production composition-root wiring conformance (M4 retro finding A1).

``test_route_table_conformance.py`` pins that routes **exist**; this gate
pins that routes **are wired in the production stack**: through
``bootstrap.build_production_app`` every SPEC-500 §4 route responds with
anything except 501 — 501 is reserved for use-cases with no
implementation anywhere (the SPEC-500 §3 additive-only stub posture).

Why a mechanical gate: the M4 integration shipped a composition root
whose report claimed "fully bound" while ``verification_port`` and the
``SimulationRuntime`` event sink were not wired (#53 偏差 11 vs code,
fixed by #58, 挂账 3). The same agent that wires the stack also writes
its wiring test — a self-verified blind spot. This gate derives the
route inventory from the composed app itself, so flipping a pending
route to a real implementation automatically tightens the contract, and
``ALLOWED_501`` may only shrink by deleting a row.

The 501-legal inventory (SPEC-500 §4.1 topology ×5, §4.7 scenario ×2,
§4.6 ``POST /artifacts/{id}/analyze`` — SPEC-308 un-ticketed, M4 裁定 B:
the e2e drives analysis in-process while this route stays 501) is
asserted **exactly**: a new stub appearing, an allowed stub vanishing,
or an allowed stub silently gaining a real handler all fail.
"""

from __future__ import annotations

import re

from fastapi.testclient import TestClient

from api.versioning import API_V1_PREFIX
from bootstrap import build_production_app

import pytest

pytestmark = pytest.mark.integration

#: Route shapes permitted to answer 501 through the production stack:
#: no backing use-case exists anywhere yet. Rows are (method, shape) with
#: path parameters normalized to ``{}``. Adding a row here = declaring a
#: use-case unimplemented platform-wide; removing one = the wiring gate
#: now demands a real handler.
ALLOWED_501: frozenset[tuple[str, str]] = frozenset(
    {
        # SPEC-500 §4.1 topology — pending.py stubs (topology engine未派票)
        ("POST", "/api/v1/topologies"),
        ("GET", "/api/v1/topologies"),
        ("GET", "/api/v1/topologies/{}"),
        ("PUT", "/api/v1/topologies/{}"),
        ("POST", "/api/v1/topologies/{}/validate"),
        # SPEC-500 §4.7 scenario — pending.py stubs (#45 loader 有,REST 面未挂)
        ("GET", "/api/v1/scenarios"),
        ("GET", "/api/v1/scenarios/{}"),
        # SPEC-500 §4.6 analyze — SPEC-308 un-ticketed (M4 裁定 B: e2e 走
        # 进程内分析桥,本路由保持 501)
        ("POST", "/api/v1/artifacts/{}/analyze"),
    }
)

_PLACEHOLDER = "00000000-0000-0000-0000-000000000000"


def _normalize(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "{}", path)


class TestProductionStackWiringConformance:
    """Every composed §4 route is either wired or exactly an ALLOWED_501
    stub — through the production composition root, not a test stack."""

    def test_every_route_is_wired_or_declared_stub(self, tmp_path) -> None:
        stack = build_production_app(db_path=tmp_path / "prod.sqlite3")
        try:
            client = TestClient(stack.app, raise_server_exceptions=False)
            schema = stack.app.openapi()

            composed: set[tuple[str, str]] = set()
            unexpected_501: list[tuple[str, str]] = []
            stub_missing: list[tuple[str, str]] = []
            for path, methods in schema["paths"].items():
                if not path.startswith(API_V1_PREFIX):
                    continue
                for method in methods:
                    if method.upper() in ("HEAD", "OPTIONS"):
                        continue
                    shape = (method.upper(), _normalize(path))
                    composed.add(shape)
                    concrete = re.sub(r"\{[^}]+\}", _PLACEHOLDER, path)
                    kwargs = {} if method.upper() in ("GET", "HEAD") else {"json": {}}
                    status = client.request(method.upper(), concrete, **kwargs).status_code
                    if status == 501:
                        if shape not in ALLOWED_501:
                            unexpected_501.append(shape)
                    elif shape in ALLOWED_501:
                        stub_missing.append(shape)

            assert unexpected_501 == [], (
                "routes answering 501 through build_production_app without "
                "an ALLOWED_501 row — wire the backing use-case or declare "
                "it unimplemented platform-wide (add an ALLOWED_501 row):\n"
                + "\n".join(f"{method} {path}" for method, path in unexpected_501)
            )
            assert stub_missing == [], (
                "ALLOWED_501 rows that no longer answer 501 — the stub "
                "gained a real handler; shrink ALLOWED_501:\n"
                + "\n".join(f"{method} {path}" for method, path in stub_missing)
            )
            absent = ALLOWED_501 - composed
            assert absent == set(), (
                f"ALLOWED_501 rows missing from the composed app: {absent}"
            )
        finally:
            stack.close()
