"""Load profile — ticket #57 (OBS-G) five-item performance evidence.

The SPEC-300 §10 engineering targets vs ADR-0008 MVP envelope, measured
on the REAL production pipeline (``build_production_app`` faces):

| item        | SPEC-300 §10 target            | measured by |
|-------------|--------------------------------|-------------|
| throughput  | 20k ev/s sustained; 50k burst  | ``TestThroughputProfile`` |
| latency     | append p95 ≤20ms; metrics page ≤300ms; timeline page ≤250ms | ``TestLatencyProfile`` |
| lag         | ``observation.consumer_lag_events`` = watermark − checkpoint | ``TestLagProfile`` |
| memory      | bounded; ADR-0008 ≤512 MB      | ``TestMemoryProfile`` |
| retention   | tiered deletion observable     | ``TestRetentionObservability`` |

DISCIPLINE (ADR-0008 §5, tests/README §4.1/§6):
- everything here is ``slow`` — the CI-green combination excludes it;
- NO absolute wall-clock assertion at target values: the asserts are
  order-of-magnitude smoke guards (≥10× headroom vs the §10 target) so a
  catastrophic regression fails while normal cross-machine noise passes;
- the precise measured values are PRINTED as ``PERF-RESULT`` lines and
  recorded in the ticket report (bench posture: docs/research/
  python-perf.md §8 — best-of-runs, ±10% desktop noise, software/hardware
  detail recorded);
- no sleep-based pacing anywhere: walls are measured, never waited on.

Retention scoping note (recorded honestly): metric-tier / journal-day
DELETION is not implemented in M4 (SPEC-502 storage-backend territory —
``metrics/store.py`` MVP scoping); this module measures the retention
substrate that DOES exist (durable restart + query-time downsampling
consistency) and the report declares the deletion tier NOT RUN with the
gap pointer.
"""

from __future__ import annotations

import ctypes
import os
import platform
import sys
import time
from uuid import uuid4

import pytest

from bootstrap import build_production_app

from tests.integration.observation_perf.test_obs_crossmodule_integration_chain import (
    DOMAIN,
    SESSION,
    _emit,
)

pytestmark = pytest.mark.slow


@pytest.fixture(autouse=True)
def _print_bench_env():
    """One environment evidence line per test (bench posture: software/
    hardware detail recorded with every measurement)."""
    _env_line()
    yield


def _perf_line(item: str, **fields) -> None:
    """One greppable evidence line (the report quotes these verbatim)."""
    rendered = " ".join(f"{key}={value}" for key, value in fields.items())
    print(f"PERF-RESULT item={item} {rendered}", flush=True)


def _env_line() -> None:
    print(
        "PERF-ENV "
        f"os={platform.system()}-{platform.release()} "
        f"python={sys.version.split()[0]} "
        f"cpu={platform.processor() or platform.machine()}",
        flush=True,
    )


def _peak_rss_bytes() -> int:
    """Process PEAK working set (Windows psapi; POSIX ru_maxrss fallback).

    Peak — not instantaneous — is the honest figure against the ADR-0008
    512 MB envelope: it captures whatever the pipeline ever touched.
    """
    if sys.platform == "win32":

        class _ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.c_ulong),
                ("PageFaultCount", ctypes.c_ulong),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        pmc = _ProcessMemoryCounters()
        pmc.cb = ctypes.sizeof(pmc)
        handle = ctypes.windll.kernel32.GetCurrentProcess()
        psapi = ctypes.windll.psapi
        psapi.GetProcessMemoryInfo.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(_ProcessMemoryCounters),
            ctypes.c_ulong,
        ]
        psapi.GetProcessMemoryInfo.restype = ctypes.c_int
        if psapi.GetProcessMemoryInfo(handle, ctypes.byref(pmc), pmc.cb):
            return int(pmc.PeakWorkingSetSize)
        return 0
    import resource

    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024


def _current_rss_bytes() -> int:
    """Instantaneous working set (Windows psapi; POSIX /proc fallback)."""
    if sys.platform == "win32":

        class _Counters(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.c_ulong),
                ("PageFaultCount", ctypes.c_ulong),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        pmc = _Counters()
        pmc.cb = ctypes.sizeof(pmc)
        handle = ctypes.windll.kernel32.GetCurrentProcess()
        psapi = ctypes.windll.psapi
        psapi.GetProcessMemoryInfo.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(_Counters),
            ctypes.c_ulong,
        ]
        psapi.GetProcessMemoryInfo.restype = ctypes.c_int
        if psapi.GetProcessMemoryInfo(handle, ctypes.byref(pmc), pmc.cb):
            return int(pmc.WorkingSetSize)
        return 0
    with open("/proc/self/statm", "rb") as handle:
        pages = int(handle.read().split()[1])
    return pages * os.sysconf("SC_PAGE_SIZE")


def _percentile(sorted_samples: list[float], fraction: float) -> float:
    if not sorted_samples:
        return 0.0
    index = min(len(sorted_samples) - 1, int(round(fraction * (len(sorted_samples) - 1))))
    return sorted_samples[index]


# ============================================================================
# item 1 — throughput (SPEC-300 §10 rows 1-2)
# ============================================================================


class TestThroughputProfile:
    """Gateway sustained + burst ingest through accept → journal append →
    commit fan-out (the full §7 pipeline, not an isolated queue)."""

    _WAVE = 4_000  # accept waves; default queue capacity is 10_000

    def test_sustained_ingest_throughput(self, tmp_path):
        """Target 20,000 events/s per process (SPEC-300 §10 row 1)."""
        total = 20_000
        stack = build_production_app(db_path=tmp_path / "thr.sqlite3")
        try:
            stack.attach_session(SESSION)
            started = time.perf_counter_ns()
            accept_ns = 0
            committed = 0
            while committed < total:
                wave = min(self._WAVE, total - committed)
                phase = time.perf_counter_ns()
                for index in range(wave):
                    _emit(
                        stack,
                        "simulation.run_progress",
                        value_ns=committed + index,
                        run_id=f"run-{committed + index}",
                    )
                accept_ns += time.perf_counter_ns() - phase
                committed += stack.drain_gateway()
            elapsed_s = (time.perf_counter_ns() - started) / 1e9
            rate = committed / elapsed_s
            accept_only_rate = committed / (accept_ns / 1e9)
        finally:
            stack.close()

        _perf_line(
            "throughput_sustained",
            committed=committed,
            elapsed_s=round(elapsed_s, 3),
            events_per_s=round(rate),
            accept_only_events_per_s=round(accept_only_rate),
            target_events_per_s=20_000,
        )
        # Order-of-magnitude smoke guard ONLY (ADR-0008 §5): set an order
        # of magnitude under the MEASURED pipeline reality (~10²-10³ ev/s
        # per-event-commit SQLite on this bench, see the ticket report for
        # the §10 deviation record) — catches catastrophic collapse without
        # cross-machine flake. NOT the §10 target; that gap is reported,
        # never threshold-tuned here (裁定 3).
        assert rate > 100, f"sustained ingest collapsed to {rate:.0f} ev/s"

    def test_burst_ingest_profile(self, tmp_path):
        """Target: 50,000 events/s sustained for 10 s (SPEC-300 §10 row 2).

        The 10 s window is the measurement envelope, not a wait: the loop
        works flat out for the whole window and the achieved rate is what
        it is (honest measurement, no pacing).
        """
        window_s = 10.0
        stack = build_production_app(db_path=tmp_path / "burst.sqlite3")
        try:
            stack.attach_session(SESSION)
            started = time.perf_counter_ns()
            committed = 0
            rejected = 0
            while True:
                now = time.perf_counter_ns()
                if (now - started) / 1e9 >= window_s:
                    break
                for index in range(self._WAVE):
                    result = stack.gateway.accept(
                        _make_envelope(committed + index)
                    )
                    if result.outcome.value != "accepted":
                        rejected += 1
                committed += stack.drain_gateway()
            elapsed_s = (time.perf_counter_ns() - started) / 1e9
            rate = committed / elapsed_s
        finally:
            stack.close()

        _perf_line(
            "throughput_burst_10s",
            window_s=window_s,
            committed=committed,
            rejected=rejected,
            events_per_s=round(rate),
            target_events_per_s=50_000,
        )
        assert rate > 100, f"burst ingest collapsed to {rate:.0f} ev/s"
        assert rejected == 0, "burst must not drop events (protected/queue)"


def _make_envelope(index: int) -> dict:
    from tests.unit.application.observation.test_gateway_accept import (
        _raw_envelope,
    )

    envelope = _raw_envelope(
        event_id=str(uuid4()),
        event_type="simulation.run_progress",
        producer_id="sim-engine",
        session_id=SESSION,
    )
    envelope["severity"] = "info"
    envelope["time"]["source"] = {
        "value_ns": index,
        "clock_domain": DOMAIN,
        "clock_epoch": 0,
    }
    envelope["scope"]["run_id"] = f"run-{index}"
    return envelope


# ============================================================================
# item 2 — latency (SPEC-300 §10 rows 3-5)
# ============================================================================


class TestLatencyProfile:
    """Append p95 + query page latencies; precise values are recorded,
    asserts are 10×-headroom guards."""

    def test_append_p95_latency(self, tmp_path):
        """Target: accepted-event append p95 ≤ 20 ms (§10 row 3). One
        accept+drain per event = the worst-case synchronous producer
        posture (no batching benefit)."""
        count = 1_000
        stack = build_production_app(db_path=tmp_path / "lat.sqlite3")
        try:
            stack.attach_session(SESSION)
            latencies_ms: list[float] = []
            for index in range(count):
                envelope = _make_envelope(index)
                started = time.perf_counter_ns()
                result = stack.gateway.accept(envelope)
                assert result.outcome.value == "accepted"
                stack.drain_gateway()
                latencies_ms.append((time.perf_counter_ns() - started) / 1e6)
        finally:
            stack.close()

        ordered = sorted(latencies_ms)
        p50 = _percentile(ordered, 0.50)
        p95 = _percentile(ordered, 0.95)
        _perf_line(
            "latency_append_p95",
            n=count,
            p50_ms=round(p50, 3),
            p95_ms=round(p95, 3),
            max_ms=round(ordered[-1], 3),
            target_p95_ms=20,
        )
        assert p95 < 200, f"append p95 {p95:.1f} ms — 10× target blown"

    def test_metrics_query_page_latency_1h(self, tmp_path):
        """Target: metrics query over a 1 h window / ≤ 20 series ≤ 300 ms
        (§10 row 4). 20 series × 3600 one-second samples ingested through
        the #50 programmatic face; queried via the service page face."""
        from application.observation.metrics.engine import MetricsEngine
        from application.observation.metrics.service import (
            MetricQueryRequest,
            MetricsService,
        )
        from domain.observation import (
            MetricProvenance,
            MetricSample,
            MetricSampleTimepoint,
            SampleSemantics,
        )

        # One shared clock domain, 20 series differentiated by the
        # session_id dimension — the §10 scenario is ONE query answer
        # carrying up to 20 sequences.
        shared_domain = "sim:sess-lat-shared"

        def _sample(series: int, second: int) -> MetricSample:
            session_id = f"sess-lat-{series:02d}"
            return MetricSample(
                metric_name="simulation.virtual_time_ns",
                time=MetricSampleTimepoint(
                    value_ns=second * 1_000_000_000,
                    clock_domain=shared_domain,
                    clock_epoch=0,
                    semantics=SampleSemantics.OBSERVED,
                ),
                value=second * 1_000_000_000,
                dimensions={"session_id": session_id},
                provenance=MetricProvenance(journal_watermark=second),
            )

        engine = MetricsEngine()
        series_count = 20
        points_per_series = 3_600
        hour_ns = 3_600 * 1_000_000_000
        for series in range(series_count):
            for second in range(points_per_series):
                engine.ingest_sample(_sample(series, second))
        service = MetricsService(engine)

        started = time.perf_counter_ns()
        result = service.query(
            MetricQueryRequest(
                metric_names=("simulation.virtual_time_ns",),
                start_ns=0,
                end_ns=hour_ns,
                step_ns=60 * 1_000_000_000,  # 60 buckets per series
                clock_domain=shared_domain,
            )
        )
        elapsed_ms = (time.perf_counter_ns() - started) / 1e6
        _perf_line(
            "latency_metrics_query_1h",
            series=len(result.series),
            series_target_max=series_count,
            buckets=len(result.series[0].points) if result.series else 0,
            elapsed_ms=round(elapsed_ms, 3),
            target_ms=300,
        )
        assert len(result.series) == series_count
        assert elapsed_ms < 3_000, f"metrics page {elapsed_ms:.0f} ms — 10× target blown"

    def test_timeline_page_latency_500_records(self, tmp_path):
        """Target: timeline page (≤ 500 records) ≤ 250 ms (§10 row 5).
        2,000 committed events; a 500-record page query over the pinned
        sim domain."""
        from application.observation.timeline.service import TimelineFilter

        stack = build_production_app(db_path=tmp_path / "tl.sqlite3")
        try:
            stack.attach_session(SESSION)
            for index in range(2_000):
                envelope = _make_envelope(index)
                assert stack.gateway.accept(envelope).outcome.value == "accepted"
            stack.drain_gateway()
            assert stack.process_observation(SESSION) == 2_000

            started = time.perf_counter_ns()
            page = stack.timeline_service.query(
                TimelineFilter(session_id=SESSION, clock_domain=DOMAIN),
                page_size=500,
            )
            elapsed_ms = (time.perf_counter_ns() - started) / 1e6
            records = len(page.records)
        finally:
            stack.close()

        _perf_line(
            "latency_timeline_page_500",
            records=records,
            elapsed_ms=round(elapsed_ms, 3),
            target_ms=250,
        )
        assert records == 500
        assert elapsed_ms < 2_500, f"timeline page {elapsed_ms:.0f} ms — 10× blown"


# ============================================================================
# item 3 — lag (observation.consumer_lag_events = watermark − checkpoint)
# ============================================================================


class TestLagProfile:
    """The lag gauge under load: committed-but-unconsumed depth grows with
    unprocessed commits and returns to exactly zero after catch-up
    (SPEC-300 §8 消费者滞后; the metric feeds ``poll_operational``)."""

    def test_lag_growth_and_zero_recovery_under_load(self, tmp_path):
        stack = build_production_app(db_path=tmp_path / "lag.sqlite3")
        try:
            stack.attach_session(SESSION)
            consumer = stack.consumers[SESSION]
            total = 10_000
            for index in range(total):
                envelope = _make_envelope(index)
                assert stack.gateway.accept(envelope).outcome.value == "accepted"
            stack.drain_gateway()

            watermark = stack.journal.max_seq(SESSION)
            assert watermark == total
            peak_lag = consumer.lag()
            assert peak_lag == total  # watermark − checkpoint(0), exact

            rounds: list[int] = []
            while consumer.lag() > 0:
                rounds.append(stack.process_observation(SESSION))
            assert consumer.lag() == 0
            assert consumer.checkpoint_seq() == total

            # The operational metric face mirrors the same numbers.
            stack.metrics_engine.poll_operational(
                SESSION,
                gateway_metrics=stack.gateway.metrics(),
                consumer_lag=consumer.lag(),
                wall_ns=1,
            )
            samples = stack.metrics_engine.samples(
                "observation.consumer_lag_events",
                clock_domain="wall:utc",
                dimensions={"session_id": SESSION},
            )
            assert samples and samples[-1].value == 0
        finally:
            stack.close()

        _perf_line(
            "lag_profile",
            committed=total,
            peak_lag=peak_lag,
            catchup_rounds=len(rounds),
            final_lag=0,
        )


# ============================================================================
# item 4 — memory (SPEC-300 §10 row 7 + ADR-0008 512 MB)
# ============================================================================


class TestMemoryProfile:
    """Streaming the pipeline must not accumulate unbounded in-memory
    history (SPEC-300 §10 row 7): the journal is on-disk SQLite, so the
    observable is the memory the PIPELINE ADDS for an MVP-scale workload
    — measured as the working-set growth across the stream (robust to
    whatever else shares the harness process), recorded against the
    ADR-0008 512 MB envelope (evidence figure, not a CI pin — same
    discipline as the wall-clock rows)."""

    def test_memory_growth_bounded_under_streaming(self, tmp_path):
        total = 20_000
        rss_before = _current_rss_bytes()
        stack = build_production_app(db_path=tmp_path / "mem.sqlite3")
        try:
            stack.attach_session(SESSION)
            samples: list[int] = []
            for index in range(total):
                envelope = _make_envelope(index)
                assert stack.gateway.accept(envelope).outcome.value == "accepted"
                if (index + 1) % 4_000 == 0:
                    stack.drain_gateway()
                    stack.process_observation(SESSION)
                    samples.append(_current_rss_bytes())
            stack.drain_gateway()
            stack.process_observation(SESSION)
            samples.append(_current_rss_bytes())
            peak = _peak_rss_bytes()
            db_bytes = os.path.getsize(tmp_path / "mem.sqlite3")
        finally:
            stack.close()

        growth = max(samples) - rss_before
        envelope_bytes = 512 * 1024 * 1024
        _perf_line(
            "memory_peak_streaming",
            committed=total,
            rss_before_mb=round(rss_before / (1024 * 1024), 1),
            pipeline_growth_mb=round(growth / (1024 * 1024), 1),
            rss_samples_mb=[round(s / (1024 * 1024), 1) for s in samples],
            process_peak_rss_mb=round(peak / (1024 * 1024), 1),
            journal_on_disk_mb=round(db_bytes / (1024 * 1024), 2),
            envelope_mb=512,
        )
        # Boundedness guard: an MVP-scale stream adds envelope-scale
        # memory at most (per-event residue of the in-memory MVP
        # components is reported, never threshold-tuned — 裁定 3).
        assert growth < envelope_bytes, (
            f"pipeline growth {growth / (1024 * 1024):.0f} MB for {total} "
            "events — unbounded in-memory event history"
        )


# ============================================================================
# item 5 — retention (SPEC-302 §7 + SPEC-300 §11 config)
# ============================================================================


class TestRetentionObservability:
    """What M4 can observably measure about retention; the deletion tiers
    themselves are NOT implemented in M4 (metrics/store.py MVP scoping —
    durable retention is SPEC-502 storage-backend territory). This module
    measures the substrate: durability across restart and query-time
    downsampling consistency. The report records the deletion tier as
    NOT RUN with the gap pointer (OPEN-006/#16 linkage: CONTRACT §7 last
    unchecked box)."""

    def test_journal_durability_across_restart(self, tmp_path):
        """Committed rows survive a full close/reopen cycle: the journal —
        not process memory — is the fact source (SPEC-300 §8), which is
        the precondition any future deletion tier administers."""
        db_path = tmp_path / "ret.sqlite3"
        total = 2_000
        stack = build_production_app(db_path=db_path)
        stack.attach_session(SESSION)
        for index in range(total):
            envelope = _make_envelope(index)
            assert stack.gateway.accept(envelope).outcome.value == "accepted"
        stack.drain_gateway()
        stack.process_observation(SESSION)
        stack.close()

        stack2 = build_production_app(db_path=db_path)
        try:
            stack2.attach_session(SESSION)
            rows = stack2.journal.query(SESSION, after_seq=0, limit=100)
            assert len(rows) == 100  # bounded page reads the durable store
            assert stack2.journal.max_seq(SESSION) == total
            # Checkpointed consumer resumes with zero reprocessing.
            assert stack2.process_observation(SESSION) == 0
        finally:
            stack2.close()

    def test_query_time_downsampling_consistency(self, tmp_path):
        """The retention-tier SUBSTITUTE M4 actually has: downsampling is
        query-time aggregation over the same raw samples (store.py §6/§7
        MVP scoping) — coarse and fine windows over one series agree on
        the underlying data (no data loss between tier views)."""
        from application.observation.metrics.engine import MetricsEngine
        from application.observation.metrics.service import (
            MetricQueryRequest,
            MetricsService,
        )
        from domain.observation import (
            MetricProvenance,
            MetricSample,
            MetricSampleTimepoint,
            SampleSemantics,
        )

        session_id = "sess-ret"
        domain = f"sim:{session_id}"
        engine = MetricsEngine()
        for second in range(3_600):
            engine.ingest_sample(
                MetricSample(
                    metric_name="simulation.virtual_time_ns",
                    time=MetricSampleTimepoint(
                        value_ns=second * 1_000_000_000,
                        clock_domain=domain,
                        clock_epoch=0,
                        semantics=SampleSemantics.OBSERVED,
                    ),
                    value=second * 1_000_000_000,
                    dimensions={"session_id": session_id},
                    provenance=MetricProvenance(journal_watermark=second),
                )
            )
        service = MetricsService(engine)
        fine = service.query(
            MetricQueryRequest(
                metric_names=("simulation.virtual_time_ns",),
                start_ns=0,
                end_ns=3_600 * 1_000_000_000,
                step_ns=60 * 1_000_000_000,
                clock_domain=domain,
            )
        )
        coarse = service.query(
            MetricQueryRequest(
                metric_names=("simulation.virtual_time_ns",),
                start_ns=0,
                end_ns=3_600 * 1_000_000_000,
                step_ns=600 * 1_000_000_000,
                clock_domain=domain,
            )
        )
        fine_filled = [
            p for p in fine.series[0].points if p.value is not None
        ]
        coarse_filled = [
            p for p in coarse.series[0].points if p.value is not None
        ]
        _perf_line(
            "retention_query_time_tiers",
            raw_samples=3_600,
            fine_buckets=len(fine.series[0].points),
            fine_filled=len(fine_filled),
            coarse_buckets=len(coarse.series[0].points),
            coarse_filled=len(coarse_filled),
        )
        assert len(fine_filled) == 60
        assert len(coarse_filled) == 6
        # With LAST aggregation a coarse bucket's value IS the last fine
        # bucket it subsumes — the two tier views never disagree about the
        # underlying data (same raw samples, coarser view).
        for coarse_index, point in enumerate(coarse_filled):
            subsumed = fine_filled[coarse_index * 10 + 9]
            assert point.value == subsumed.value
