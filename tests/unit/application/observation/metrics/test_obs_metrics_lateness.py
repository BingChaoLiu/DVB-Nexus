"""SPEC-302 §6.2 late samples / revision / finalization (ticket #50).

REQ-OBS-302-003: late arrivals never silently rewrite a finalized
aggregate; with backfill enabled the rewritten aggregate increments
``revision`` and stays ``is_final=false`` until re-finalization. Sample
schema fields ``revision``/``is_final`` (#12 ruling) surface on every
response point.

Finalization rule (journal-order deterministic, SPEC-302 §9): a bucket
``[b0, b1)`` is final once the series' arrival watermark reaches
``b1 + lateness_window``; a sample is late when the series watermark has
already passed its timestamp by more than the lateness window. All
decisions derive from journal arrival order only — replaying the same
journal reproduces them exactly.

Unit layer: pure in-memory; gauge ``simulation.virtual_time_ns`` samples
are laid on a 100 ns step grid.
"""

from application.observation.metrics.engine import (
    MetricsEngine,
    MetricsEngineConfig,
)
from application.observation.metrics.service import (
    MetricQueryRequest,
    MetricsService,
)
from domain.observation import SeriesQuality

from tests.unit.application.observation.metrics._metrics_fixtures import (
    raw_envelope,
    record,
)

DOMAIN = "sim:sess-1"
METRIC = "simulation.virtual_time_ns"


def _engine(backfill: bool) -> MetricsEngine:
    return MetricsEngine(
        config=MetricsEngineConfig(backfill_enabled=backfill)
    )


def _feed(engine: MetricsEngine, *source_ns_list: int) -> None:
    for seq, source_ns in enumerate(source_ns_list, start=1):
        engine.handle_record(
            record(
                raw_envelope(
                    event_type="simulation.run_started", source_ns=source_ns
                ),
                journal_seq=seq,
            )
        )


def _bucket(view, start_ns: int):
    for point in view.points:
        if point.start_ns == start_ns:
            return point
    raise AssertionError(f"no bucket starting at {start_ns}")  # pragma: no cover


def _query(engine: MetricsEngine, *, end_ns: int = 400):
    return MetricsService(engine).query(
        MetricQueryRequest(
            metric_names=(METRIC,),
            start_ns=0,
            end_ns=end_ns,
            step_ns=100,
            clock_domain=DOMAIN,
        )
    ).series[0]


# --- finalization is a pure function of the arrival watermark --------------------


def test_buckets_finalize_once_the_watermark_passes_their_end() -> None:
    engine = _engine(backfill=False)
    _feed(engine, 100, 300)
    view = _query(engine)
    # watermark=300: the sampled bucket [100,200) is final; [300,400) is
    # still open; the empty [200,300) answers missing (its is_final stays
    # False — an empty bucket never published an aggregate to freeze).
    assert _bucket(view, 100).is_final is True
    assert _bucket(view, 100).value == 100
    assert _bucket(view, 200).quality == ("missing",)
    assert _bucket(view, 300).is_final is False
    assert _bucket(view, 300).revision == 1
    assert _bucket(view, 300).value == 300


def test_open_bucket_accumulates_at_the_same_revision_until_finalized() -> None:
    engine = _engine(backfill=False)
    _feed(engine, 320)
    view = _query(engine)
    assert _bucket(view, 300).value == 320

    _feed_seq(engine, 350, seq=2)
    view = _query(engine)
    # Still open (watermark 350 < 400): same revision, new value.
    assert _bucket(view, 300).value == 350
    assert _bucket(view, 300).revision == 1
    assert _bucket(view, 300).is_final is False


def _feed_seq(engine: MetricsEngine, source_ns: int, *, seq: int) -> None:
    engine.handle_record(
        record(
            raw_envelope(
                event_type="simulation.run_started", source_ns=source_ns
            ),
            journal_seq=seq,
        )
    )


# --- backfill OFF: 定稿后到达不静默改写 (REQ-OBS-302-003 core) -------------------


def test_late_sample_never_rewrites_the_frozen_aggregate() -> None:
    engine = _engine(backfill=False)
    _feed(engine, 100, 300)
    # First publication freezes [100,200) at value 100 / revision 1.
    first = _query(engine)
    assert _bucket(first, 100).value == 100
    assert _bucket(first, 100).is_final is True

    # A late sample (watermark 300 already past 150) arrives.
    _feed_seq(engine, 150, seq=3)
    second = _query(engine)

    frozen = _bucket(second, 100)
    assert frozen.value == 100  # unchanged — 无静默改写
    assert frozen.revision == 1
    assert frozen.is_final is True
    assert frozen.quality == ("good",)
    # The late sample is preserved in the raw store with its late flag —
    # it stays in the journal truth, it just never rewrote the aggregate.
    late_samples = [
        s
        for s in engine.samples(METRIC, clock_domain=DOMAIN)
        if s.time.value_ns == 150
    ]
    assert late_samples and SeriesQuality.LATE in late_samples[0].quality


def test_backfill_off_repeated_late_arrivals_stay_frozen() -> None:
    engine = _engine(backfill=False)
    _feed(engine, 100, 300)
    _query(engine)
    _feed_seq(engine, 150, seq=3)
    _query(engine)
    _feed_seq(engine, 180, seq=4)
    third = _query(engine)
    frozen = _bucket(third, 100)
    assert frozen.value == 100
    assert frozen.revision == 1
    assert frozen.is_final is True


# --- backfill ON: revision++ 并保持 is_final=false 直至重新定稿 -------------------


def test_backfill_revision_increments_and_stays_unfinal_until_refinalized() -> None:
    engine = _engine(backfill=True)
    _feed(engine, 100, 300)
    first = _query(engine)
    assert _bucket(first, 100).revision == 1
    assert _bucket(first, 100).is_final is True

    _feed_seq(engine, 150, seq=3)  # late arrival
    revised = _query(engine)
    rewritten = _bucket(revised, 100)
    assert rewritten.value == 150  # recomputed with the late sample
    assert rewritten.revision == 2  # 修订聚合必须递增 revision (§6.2)
    assert rewritten.is_final is False  # 保持 is_final=false 直至重新定稿
    assert SeriesQuality.REVISED in rewritten.quality
    assert SeriesQuality.LATE in rewritten.quality

    # Re-finalization: the next materialization with no new arrivals sees
    # the watermark rule satisfied and freezes the revised aggregate.
    refinal = _query(engine)
    refrozen = _bucket(refinal, 100)
    assert refrozen.value == 150
    assert refrozen.revision == 2
    assert refrozen.is_final is True


def test_late_sample_before_first_publication_needs_no_revision() -> None:
    # Nothing was ever published for the bucket — the late sample simply
    # aggregates at revision 1 (no rewrite, no revision increment).
    engine = _engine(backfill=True)
    _feed(engine, 300, 150)
    view = _query(engine)
    bucket = _bucket(view, 100)
    assert bucket.value == 150  # last sample in [100,200)
    assert bucket.revision == 1
    assert bucket.is_final is True  # watermark 300 ≥ 200
    assert SeriesQuality.LATE in bucket.quality  # arrival order visible


# --- determinism of the finalization state machine ---------------------------------


def test_same_journal_and_queries_reproduce_identical_revisions() -> None:
    program = (100, 300)

    def replay(backfill: bool) -> list:
        engine = _engine(backfill=backfill)
        _feed(engine, *program)
        _query(engine)
        _feed_seq(engine, 150, seq=len(program) + 1)
        view = _query(engine)
        return [
            (p.start_ns, p.value, p.revision, p.is_final, p.quality)
            for p in view.points
        ]

    assert replay(False) == replay(False)
    assert replay(True) == replay(True)
