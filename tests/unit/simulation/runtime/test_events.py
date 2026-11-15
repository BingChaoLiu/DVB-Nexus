"""SPEC-200 §7.4 — event emission obligation through the #47 sink face.

Traceability (SPEC-200 section 10):

- REQ-SIM-200-007  lifecycle and run events are emitted per ADR-0006
  envelope and pass schema validation -> TestEnvelopeConformance /
  TestRunEventFamily

Discipline (CONTEXT.md 事件信封 / 流水号): producers mark identity and the
dual clock only; ``journal_seq`` is gateway-stamped downstream — an emitted
envelope must pass ``EventEnvelope.ensure_publishable``. Every emitted
document goes through ``domain.observation.parse_envelope`` at emission, so
a non-conforming event cannot leave the runtime (schema validation is a
construction guarantee, not a downstream hope). Event types are exactly the
#46 registry families — nothing invented.
"""

from __future__ import annotations

import asyncio

import pytest

pytestmark = pytest.mark.unit

from domain.observation import parse_envelope
from domain.observation.registry import is_registered
from simulation.lifecycle import LifecycleState
from simulation.runtime import SimulationRuntime

from tests.unit.simulation.runtime import _sim_c_builders as b


class RecordingSink:
    """Minimal SessionEventSink double (records validated envelope dicts)."""

    def __init__(self) -> None:
        self.events: list[dict] = []

    def publish(self, event) -> None:
        self.events.append(dict(event))

    def types(self) -> list[str]:
        return [event["event_type"] for event in self.events]


async def _running_session(runtime: SimulationRuntime, session_id: str) -> None:
    await runtime.create_session(b.session_spec(session_id=session_id))
    await runtime.validate_session(session_id)
    await runtime.start(session_id)


class TestEnvelopeConformance:
    """每次迁移发射对应 session_* 事件，且通过 SPEC-301 信封校验。"""

    def test_full_lifecycle_emits_one_event_per_command(self) -> None:
        async def main() -> None:
            sink = RecordingSink()
            runtime = SimulationRuntime(event_sink=sink)
            await runtime.create_session(b.session_spec(session_id="ev-1"))
            await runtime.validate_session("ev-1")
            await runtime.start("ev-1")
            await runtime.pause("ev-1")
            await runtime.resume("ev-1")
            await runtime.stop("ev-1")
            await runtime.dispose("ev-1")

            # The five registered session types, in command order. No
            # registered type exists for VALIDATING->READY/FAILED or
            # dispose (registry is authoritative — nothing invented).
            assert sink.types() == [
                "simulation.session_created",
                "simulation.session_started",
                "simulation.session_paused",
                "simulation.session_resumed",
                "simulation.session_stopped",
            ]

        asyncio.run(main())

    def test_every_event_passes_envelope_schema(self) -> None:
        async def main() -> None:
            sink = RecordingSink()
            runtime = SimulationRuntime(event_sink=sink)
            await runtime.create_session(b.session_spec(session_id="ev-2"))
            await runtime.validate_session("ev-2")
            await runtime.start("ev-2")
            await runtime.pause("ev-2")
            await runtime.stop("ev-2")

            assert sink.events
            for event in sink.events:
                envelope = parse_envelope(event)  # raises when non-conforming
                assert envelope.event_type == event["event_type"]
                envelope.ensure_publishable()  # producers never fill journal_seq

        asyncio.run(main())

    def test_envelope_identity_scope_dual_clock(self) -> None:
        async def main() -> None:
            sink = RecordingSink()
            runtime = SimulationRuntime(event_sink=sink)
            await runtime.create_session(b.session_spec(session_id="ev-3"))
            (event,) = sink.events

            producer = event["producer"]
            assert producer["producer_id"]
            assert producer["producer_version"]
            assert producer["instance_id"]

            scope = event["scope"]
            assert scope["tenant_id"] == "local"
            assert scope["session_id"] == "ev-3"
            assert scope.get("run_id") in (None, "")

            time_block = event["time"]
            source = time_block["source"]
            observed = time_block["observed"]
            # 双时钟：source = 会话虚拟时钟域，observed = 墙钟摄入域。
            assert source["clock_domain"] == "sim:ev-3"
            assert source["value_ns"] == 0  # deterministic clock at epoch
            assert source["clock_epoch"] == 0
            assert observed["clock_domain"] == "wall:utc"

            assert event["payload"]["lifecycle"] == "created"
            assert is_registered(event["event_type"])

        asyncio.run(main())

    def test_stop_event_carries_reason_and_forced_annotation(self) -> None:
        async def stubborn_runner(spec):
            # Suppresses only the graceful cancel; the forced escalation
            # (second cancel) terminates it.
            suppressed = False
            while True:
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    if suppressed:
                        raise
                    suppressed = True
                    continue

        async def main() -> None:
            sink = RecordingSink()
            runtime = SimulationRuntime(
                event_sink=sink,
                runner_factory=stubborn_runner,
                shutdown_timeout_s=0.0,
            )
            await runtime.create_session(b.session_spec(session_id="ev-4"))
            await runtime.validate_session("ev-4")
            await runtime.start("ev-4")
            await asyncio.sleep(0)  # worker reaches its await point
            await runtime.stop("ev-4", reason="operator")

            stopped = sink.events[-1]
            assert stopped["event_type"] == "simulation.session_stopped"
            assert stopped["payload"]["reason"] == "operator"
            assert stopped["payload"]["forced"] is True

        asyncio.run(main())

    def test_emission_failure_does_not_break_event_order_guarantee(self) -> None:
        """命令串行下事件序与迁移序一致（SPEC-200 §11 风险兜底）。"""
        async def main() -> None:
            sink = RecordingSink()
            runtime = SimulationRuntime(event_sink=sink)
            await runtime.create_session(b.session_spec(session_id="ev-5"))
            await runtime.validate_session("ev-5")
            await runtime.start("ev-5")
            await runtime.pause("ev-5")
            await runtime.stop("ev-5")

            lifecycle_payloads = [
                event["payload"]["lifecycle"] for event in sink.events
            ]
            assert lifecycle_payloads == [
                "created",
                "running",
                "paused",
                "stopped",
            ]

        asyncio.run(main())

    def test_runtime_without_sink_still_terminates_commands(self) -> None:
        async def main() -> None:
            runtime = SimulationRuntime()  # no sink wired: emission is opt-in
            await runtime.create_session(b.session_spec(session_id="ev-6"))
            await runtime.validate_session("ev-6")
            await runtime.start("ev-6")
            await runtime.stop("ev-6")
            view = await runtime.get_snapshot("ev-6")
            assert view.lifecycle is LifecycleState.STOPPED

        asyncio.run(main())


class TestRunEventFamily:
    """Run 维度 run_started/progress/completed/failed（注册表四事件）。"""

    def test_run_lifecycle_emits_registered_family(self) -> None:
        async def main() -> None:
            sink = RecordingSink()
            runtime = SimulationRuntime(event_sink=sink)
            await _running_session(runtime, "ev-7")

            await runtime.start_run("ev-7", run_id="run-1")
            await runtime.report_run_progress(
                "ev-7", "run-1", {"packets": 100}
            )
            await runtime.complete_run("ev-7", "run-1")

            types = [event["event_type"] for event in sink.events][-3:]
            assert types == [
                "simulation.run_started",
                "simulation.run_progress",
                "simulation.run_completed",
            ]
            for event in sink.events[-3:]:
                assert event["scope"]["run_id"] == "run-1"
                parse_envelope(event)  # schema conformance

        asyncio.run(main())

    def test_run_failure_emits_error_severity_event(self) -> None:
        async def main() -> None:
            sink = RecordingSink()
            runtime = SimulationRuntime(event_sink=sink)
            await _running_session(runtime, "ev-8")
            await runtime.start_run("ev-8", run_id="run-2")
            await runtime.fail_run("ev-8", "run-2", reason="encoder crash")

            failed = sink.events[-1]
            assert failed["event_type"] == "simulation.run_failed"
            assert failed["severity"] == "error"
            assert failed["payload"]["reason"] == "encoder crash"
            parse_envelope(failed)

        asyncio.run(main())

    def test_run_requires_running_session(self) -> None:
        async def main() -> None:
            runtime = SimulationRuntime()
            await runtime.create_session(b.session_spec(session_id="ev-9"))
            with pytest.raises(Exception):
                await runtime.start_run("ev-9")  # CREATED session: no runs

        asyncio.run(main())

    def test_duplicate_run_id_rejected(self) -> None:
        async def main() -> None:
            runtime = SimulationRuntime()
            await _running_session(runtime, "ev-10")
            await runtime.start_run("ev-10", run_id="dup")
            with pytest.raises(ValueError):
                await runtime.start_run("ev-10", run_id="dup")

        asyncio.run(main())

    def test_run_view_lifecycle_transitions(self) -> None:
        async def main() -> None:
            runtime = SimulationRuntime()
            await _running_session(runtime, "ev-11")
            run_view = await runtime.start_run("ev-11", run_id="r")
            assert run_view.state == "running"
            done = await runtime.complete_run("ev-11", "r")
            assert done.state == "completed"
            assert done.ended_virtual_ns is not None

        asyncio.run(main())

    def test_no_sink_run_commands_still_work(self) -> None:
        async def main() -> None:
            runtime = SimulationRuntime()
            await _running_session(runtime, "ev-12")
            view = await runtime.start_run("ev-12")
            assert view.state == "running"
