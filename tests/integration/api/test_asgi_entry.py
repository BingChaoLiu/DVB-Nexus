"""ASGI entry contract (SPEC-400 §4.5; ticket #61 / 裁定 F).

The entry is the ONLY Python-side addition of the frontend shell ticket:
env-var contract (DB path required — refuse to start without it), a served
app that keeps the SPEC-500 canary observable, and the pump that drives
journal/hint flow in server mode.

Integration layer by the repo's own definitions: the module-level
``app = create_app()`` builds the whole production stack (SQLite migrate
included) at import time, so these tests import the module freshly under a
tmp database (the env contract itself is part of what is exercised) and use
the sanctioned sys.modules snapshot-restore shape (``# sysmodules-ok:``).
The pump rides the serving portal's loop thread — real-server mode is
wall-clock driven, so drain assertions keep bounded wall-time polling
(tests/README §6: real-environment assertions keep shapes and generous
bounds).
"""

from __future__ import annotations

import importlib
import os
import sys
import time

import pytest
from fastapi.testclient import TestClient

MODULE = "bootstrap.asgi"

SESSION_BODY = {
    "topology_id": "topo-1",
    "topology_revision": 1,
    "seed": 1,
    "deterministic": True,
    "clock_config": {
        "mode": "deterministic",
        "start_time_ns": 0,
        "speed_num": 1,
        "speed_den": 1,
        "tick_quantum_ns": 1000000,
    },
}


def _fresh_import(monkeypatch: pytest.MonkeyPatch, db_path: str):
    """Fresh-import ``bootstrap.asgi`` under the env contract, restoring both
    module state and environ afterwards. The fresh import IS the behavior
    under test: the module-level ``app = create_app()`` runs the env contract
    at import time."""
    monkeypatch.setenv("DVBNEXUS_DB_PATH", db_path)
    monkeypatch.delenv("DVBNEXUS_PUMP_INTERVAL_MS", raising=False)
    saved = {
        name: sys.modules[name]
        for name in list(sys.modules)
        if name == MODULE or name.startswith(MODULE + ".")
    }
    for name in list(saved):
        sys.modules.pop(name, None)  # sysmodules-ok: snapshot-restore pair
    try:
        return importlib.import_module(MODULE)
    finally:
        for name in [
            name
            for name in list(sys.modules)
            if name == MODULE or name.startswith(MODULE + ".")
        ]:
            sys.modules.pop(name, None)  # sysmodules-ok: snapshot-restore pair
        sys.modules.update(saved)  # sysmodules-ok: restore pre-test modules


class TestEnvContract:
    def test_module_import_without_db_path_refuses_to_start(self, monkeypatch: pytest.MonkeyPatch):
        """``DVBNEXUS_DB_PATH`` is required: module import itself fails loudly
        (the module-level app runs the contract at import time)."""
        monkeypatch.delenv("DVBNEXUS_DB_PATH", raising=False)
        saved = {
            name: sys.modules[name]
            for name in list(sys.modules)
            if name == MODULE or name.startswith(MODULE + ".")
        }
        for name in list(saved):
            sys.modules.pop(name, None)  # sysmodules-ok: snapshot-restore pair
        try:
            with pytest.raises(RuntimeError, match="DVBNEXUS_DB_PATH"):
                importlib.import_module(MODULE)
        finally:
            for name in [
                name
                for name in list(sys.modules)
                if name == MODULE or name.startswith(MODULE + ".")
            ]:
                sys.modules.pop(name, None)  # sysmodules-ok: snapshot-restore pair
            sys.modules.update(saved)  # sysmodules-ok: restore pre-test modules

    def test_pump_interval_env_parsing(self, monkeypatch: pytest.MonkeyPatch, tmp_path):
        module = _fresh_import(monkeypatch, str(tmp_path / "dvbnexus.db"))
        monkeypatch.setenv("DVBNEXUS_PUMP_INTERVAL_MS", "120")
        assert module.pump_interval_s() == 0.12
        monkeypatch.delenv("DVBNEXUS_PUMP_INTERVAL_MS")
        assert module.pump_interval_s() == module.DEFAULT_PUMP_INTERVAL_S
        monkeypatch.setenv("DVBNEXUS_PUMP_INTERVAL_MS", "bogus")
        with pytest.raises(RuntimeError, match="integer"):
            module.pump_interval_s()
        monkeypatch.setenv("DVBNEXUS_PUMP_INTERVAL_MS", "0")
        with pytest.raises(RuntimeError, match="positive"):
            module.pump_interval_s()

    def test_pump_tick_is_zero_on_a_fresh_stack(self, monkeypatch: pytest.MonkeyPatch, tmp_path):
        """A fresh database has nothing queued: one tick drains nothing and
        the tick counter advances (the Pump is the public embedder face)."""
        module = _fresh_import(monkeypatch, str(tmp_path / "dvbnexus.db"))
        assert module.app.pump.tick() == 0
        assert module.app.pump.ticks == 1


class TestServedApp:
    def test_served_app_keeps_version_canary_observable(self, monkeypatch, tmp_path):
        """The served app is a full production stack: the SPEC-500 canary
        (version policy + tenant posture) answers over the frozen prefix."""
        module = _fresh_import(monkeypatch, str(tmp_path / "dvbnexus.db"))
        served = module.app
        with TestClient(served) as client:
            response = client.get("/api/v1/version")
            assert response.status_code == 200
            body = response.json()
            assert set(body) == {"api_version", "version_policy", "tenant_id"}
            assert body["tenant_id"] == "local"

    def test_pump_runs_and_drains_with_the_lifespan(self, monkeypatch, tmp_path):
        """Lifespan start/stop runs the pump cleanly; a created session's
        queued events are drained by the pump (tick counter advances, journal
        becomes queryable through the REST face — no manual drain)."""
        module = _fresh_import(monkeypatch, str(tmp_path / "dvbnexus.db"))
        served = module.app
        with TestClient(served) as client:
            response = client.post("/api/v1/sessions", json=SESSION_BODY)
            assert response.status_code == 201, response.text
            session_id = response.json()["session_id"]
            items: list = []
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                events = client.get(f"/api/v1/sessions/{session_id}/events", params={"limit": 10})
                if events.status_code == 200:
                    # 200 only once the pump has drained (the journal watermark
                    # is the session-existence authority for the query face);
                    # 404 = not yet drained — keep yielding.
                    items = events.json()["data"]["items"]
                    if items:
                        break
                time.sleep(0.02)
            assert items, "pump did not drain session events into the journal"
            assert served.pump.ticks >= 1
