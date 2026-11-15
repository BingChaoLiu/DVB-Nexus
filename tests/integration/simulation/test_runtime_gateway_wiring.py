"""Ticket #41 — runtime event emission wired to the REAL #47 gateway face.

SPEC-200 §7.4 obliges the runtime to publish lifecycle/run events through
the SPEC-301 envelope; the composition root injects the
``application.observation`` gateway/publisher face as the
``SessionEventSink``. This test consumes the #47 surface **without
modifying it** (boundary discipline): after commands, a drain stamps
``journal_seq`` and the committed envelopes round-trip through the frozen
#46 parse surface — proving REQ-SIM-200-007 end to end, producers never
fill ``journal_seq``, and the gateway's coalescing/delivery policy accepts
every simulation family event.

Integration layer: in-memory journal double (no disk), per SPEC-505 §1.
"""

from __future__ import annotations

import asyncio

import pytest

pytestmark = pytest.mark.integration

from application.observation import EventGateway, GatewayConfig
from domain.observation import parse_envelope
from simulation.runtime import SimulationRuntime

from tests.unit.simulation.runtime import _sim_c_builders as b


class MemoryJournal:
    """Minimal EventJournal double: appends get monotonic per-session seqs."""

    def __init__(self) -> None:
        self.appended: list[dict] = []
        self._seq = 0

    def append(self, envelope: dict) -> tuple[int, bool]:
        self._seq += 1
        self.appended.append(dict(envelope))
        return self._seq, False

    def query(self, session_id: str, *, after_seq: int = 0, limit: int = 100):
        return []

    def max_seq(self, session_id: str) -> int:
        return self._seq


def test_runtime_events_flow_through_real_gateway() -> None:
    async def main() -> None:
        journal = MemoryJournal()
        gateway = EventGateway(journal, GatewayConfig())
        runtime = SimulationRuntime(event_sink=gateway)  # publisher face

        await runtime.create_session(b.session_spec(session_id="gw-1"))
        await runtime.validate_session("gw-1")
        await runtime.start("gw-1")
        await runtime.start_run("gw-1", run_id="r-1")
        await runtime.report_run_progress("gw-1", "r-1", {"packets": 10})
        await runtime.complete_run("gw-1", "r-1")
        await runtime.stop("gw-1")

        stamped: list[dict] = []
        gateway.subscribe(lambda event: stamped.append(dict(event)))
        committed = gateway.drain()
        assert committed == 6  # session x3 (created/started/stopped) + run x3

        # Producer discipline: the append-time document carries no
        # journal_seq — the stamp happens in the journal adapter.
        for raw in journal.appended:
            assert raw.get("journal_seq") is None
            envelope = parse_envelope(raw)
            envelope.ensure_publishable()  # publish view: no journal_seq
        assert [event["journal_seq"] for event in stamped] == list(
            range(1, 7)
        )  # gateway-stamped per-session monotonic total order

        types = [raw["event_type"] for raw in journal.appended]
        assert types == [
            "simulation.session_created",
            "simulation.session_started",
            "simulation.run_started",
            "simulation.run_progress",
            "simulation.run_completed",
            "simulation.session_stopped",
        ]
        # run_progress is the registered coalescable type (SPEC-301 §5).
        from domain.observation.registry import is_coalescable

        assert is_coalescable("simulation.run_progress")

    asyncio.run(main())
