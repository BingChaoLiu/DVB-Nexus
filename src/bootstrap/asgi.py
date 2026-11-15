"""Real-HTTP ASGI entry over the production composition (SPEC-400 §4.5).

``bootstrap.build_production_app`` builds the full REST+WS application but
deliberately starts no server and no threads — its driver faces
(``drain_gateway`` / ``process_observation``) are the embedder's pump duty.
This module is the embedder for real-HTTP serving: it binds the env-var
contract, starts a single asyncio pump task alongside the ASGI lifespan so
journal commits / WS fan-out / hint emission actually flow in server mode,
and exposes ``app`` for ``uvicorn bootstrap.asgi:app``.

Environment contract
--------------------
``DVBNEXUS_DB_PATH`` (required, no default): the SQLite database path; the
artifact store derives ``<db>.parent/artifacts``. Missing → refuse to start
(RuntimeError) — an explicit contract beats silently creating a database.

``DVBNEXUS_HOST`` / ``DVBNEXUS_PORT`` (optional): bind posture for the
``python -m bootstrap.asgi`` convenience entry (defaults 127.0.0.1:8765, the
SPEC-500 §3 single-machine posture; the port matches the Vite proxy default).

``DVBNEXUS_PUMP_INTERVAL_MS`` (optional): pump tick interval (default 50ms).

Import-linter safety: ``bootstrap`` is the composition-root leaf — imports
point downward only (never ``knowledge``), and no project package imports
back into ``bootstrap``; uvicorn loads this module by string reference,
which is not a project-internal import edge.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from pathlib import Path
from typing import Any, Callable

from bootstrap.app import ProductionStack, build_production_app

logger = logging.getLogger(__name__)

ENV_DB_PATH = "DVBNEXUS_DB_PATH"
ENV_HOST = "DVBNEXUS_HOST"
ENV_PORT = "DVBNEXUS_PORT"
ENV_PUMP_INTERVAL_MS = "DVBNEXUS_PUMP_INTERVAL_MS"

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
DEFAULT_PUMP_INTERVAL_S = 0.05


def require_db_path(env: dict[str, str] | None = None) -> Path:
    """The env-var contract: no DB path, no server (SPEC-400 §4.5)."""
    source = os.environ if env is None else env
    value = source.get(ENV_DB_PATH, "").strip()
    if not value:
        raise RuntimeError(
            f"{ENV_DB_PATH} is required to serve the DVB-Nexus API "
            "(SQLite database path; artifacts land in its parent directory)"
        )
    return Path(value)


def pump_interval_s(env: dict[str, str] | None = None) -> float:
    source = os.environ if env is None else env
    raw = source.get(ENV_PUMP_INTERVAL_MS, "").strip()
    if not raw:
        return DEFAULT_PUMP_INTERVAL_S
    try:
        ms = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{ENV_PUMP_INTERVAL_MS} must be an integer of milliseconds") from exc
    if ms <= 0:
        raise RuntimeError(f"{ENV_PUMP_INTERVAL_MS} must be positive")
    return ms / 1000.0


class Pump:
    """The server-side driver loop (SPEC-400 §4.5): commit queued events
    (journal → hub/WS fan-out, timeline, diagnosis trigger, hints) and tick
    the checkpointed observation consumers. One asyncio task, no threads —
    the embedder-pump discipline in its serving form. Tick errors are logged
    and swallowed so the loop can never die silently mid-service."""

    def __init__(self, stack: ProductionStack, interval_s: float = DEFAULT_PUMP_INTERVAL_S) -> None:
        self._stack = stack
        self._interval_s = interval_s
        self._ticks = 0

    @property
    def ticks(self) -> int:
        return self._ticks

    def tick(self) -> int:
        """One pump pass: drain the gateway, then the observation consumers.
        Returns the combined processed count (drained events + consumed records)."""
        drained = self._stack.drain_gateway()
        processed = self._stack.process_observation()
        self._ticks += 1
        return drained + processed

    async def run_forever(self) -> None:
        while True:
            await asyncio.sleep(self._interval_s)
            try:
                self.tick()
            except Exception:  # noqa: BLE001 — the pump must survive tick failures
                logger.exception("observation pump tick failed; continuing")


class PumpedASGI:
    """ASGI wrapper: pass-through for http/lifecycle scopes, with the pump
    running concurrently for the lifespan of the server."""

    def __init__(self, inner: Any, pump: Pump) -> None:
        self._inner = inner
        self.pump = pump  # public: the embedder/test observation face

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] != "lifespan":
            await self._inner(scope, receive, send)
            return
        pump_task = asyncio.create_task(self.pump.run_forever())
        try:
            await self._inner(scope, receive, send)
        finally:
            pump_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await pump_task


def create_app() -> PumpedASGI:
    """Build the served application: production stack + pump, from the env
    contract. Also importable as ``bootstrap.asgi:app`` (module-level)."""
    db_path = require_db_path()
    stack = build_production_app(db_path=db_path)
    return PumpedASGI(stack.app, Pump(stack, pump_interval_s()))


app = create_app()


if __name__ == "__main__":  # pragma: no cover — dev convenience entry
    import uvicorn

    uvicorn.run(
        "bootstrap.asgi:app",
        host=os.environ.get(ENV_HOST, DEFAULT_HOST),
        port=int(os.environ.get(ENV_PORT, str(DEFAULT_PORT))),
    )
