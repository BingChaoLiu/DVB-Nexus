"""FastAPI test-client harness (SPEC-505 §4 ``api_client`` → SPEC-500).

Factory-shaped on purpose: the fixture yields a harness and **tests pass
the ASGI app** — fixture initialization never fabricates an app (SPEC-505
§7: fixture init failure = test failure, no silent degradation). The src
``api`` package exports its app factory since the SPEC-500 skeleton ticket
(#24: ``api.app.create_app``); the derived ``client`` fixture in the root
conftest wraps that factory through this harness, while factory-shaped
tests (probe routers, in-test apps) keep calling ``.build(app)`` directly.

DTO round-trip (SPEC-500: Pydantic DTO 权威, snake_case JSON): payload →
``model_validate`` → ``model_dump(mode="json")`` → JSON boundary →
``model_validate`` → value equality. Assertion failures raise ``AssertionError``;
invalid payloads surface ``pydantic.ValidationError`` — both loud.
"""

from __future__ import annotations

import json
from typing import Any, Mapping, TypeVar

from pydantic import BaseModel

ModelT = TypeVar("ModelT", bound=BaseModel)


class ApiClient:
    """TestClient wrapper: passthrough verbs + DTO round-trip assertions."""

    def __init__(self, test_client: Any) -> None:
        self._client = test_client

    @property
    def client(self) -> Any:
        """The underlying ``fastapi.testclient.TestClient`` (full surface)."""
        return self._client

    def get(self, path: str, **kwargs: Any) -> Any:
        return self._client.get(path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> Any:
        return self._client.post(path, **kwargs)

    def put(self, path: str, **kwargs: Any) -> Any:
        return self._client.put(path, **kwargs)

    def delete(self, path: str, **kwargs: Any) -> Any:
        return self._client.delete(path, **kwargs)

    def assert_roundtrip(self, model: type[ModelT], payload: Mapping[str, Any]) -> ModelT:
        """Assert the payload survives the DTO JSON round-trip losslessly.

        Returns the re-parsed model instance for further assertions.
        """
        instance = model.model_validate(dict(payload))
        serialized = instance.model_dump(mode="json")
        through_json = json.loads(json.dumps(serialized, ensure_ascii=False))
        reloaded = model.model_validate(through_json)
        assert reloaded == instance, (
            f"DTO round-trip is lossy for {model.__name__}: "
            f"{serialized!r} revalidated to {reloaded!r}"
        )
        return reloaded


class ApiClientHarness:
    """Yielded by the ``api_client`` fixture: builds per-test clients."""

    def build(self, app: Any, *, raise_server_exceptions: bool = True) -> ApiClient:
        """Build an ``ApiClient`` around any ASGI app (real or in-test).

        ``raise_server_exceptions`` passes through to
        :class:`fastapi.testclient.TestClient`: ``False`` lets the app's
        registered Exception-level handler render the 500 envelope instead
        of Starlette re-raising (SPEC-500 §6 ``INTERNAL_UNCLASSIFIED`` shape;
        scaffold extension approved in ticket #24's report, landed in
        review-fix #4).
        """
        from fastapi.testclient import TestClient

        return ApiClient(
            TestClient(app, raise_server_exceptions=raise_server_exceptions)
        )
