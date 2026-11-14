"""FastAPI test-client harness (SPEC-505 §4 ``api_client`` → SPEC-500).

Factory-shaped on purpose: the src ``api`` package has no app factory in the
M0 skeleton, so the fixture yields a harness and **tests pass the ASGI app**
— fixture initialization never fabricates an app (SPEC-505 §7: fixture init
failure = test failure, no silent degradation). When the SPEC-500 ticket
lands and ``api`` exports its app factory, a default ``client`` fixture
derivation wraps the real app; the harness code below stays unchanged.

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

    def build(self, app: Any) -> ApiClient:
        """Build an ``ApiClient`` around any ASGI app (real or in-test)."""
        from fastapi.testclient import TestClient

        return ApiClient(TestClient(app))
