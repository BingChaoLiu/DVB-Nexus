"""Initial metric catalog — the 15 SPEC-302 §4 metrics (ticket #50) plus
the two Phase 3 alert-input gauges (``tuner.lock_state``/``tuner.ber_state``,
SPEC-304 §Phase3, ticket #166).

Every catalog metric registers with: explicit unit (§3), provenance
declaration (§3: source_event_types 和/或快照来源), legal aggregation ops
(§6.1), the mandatory ``session_id`` dimension (§5) and — for the one
histogram — startup-validated bucket edges (§13).

Derivation contract for ``ts.*``/``psi.*`` payloads (G3 brief note: the TS
Core analysis path is not eventized yet, so these payload keys are pinned by
THIS module as the fixture contract until the analysis bridge lands — the
catalog registration itself is REQ-OBS-302-001 and unconditional):

- ``ts.packet_batch_observed`` → ``packet_count``/``byte_count``/
  ``duration_ns`` (>0)/optional ``null_packet_count``/
  ``scrambled_packet_count`` (+ optional ``stream_id`` dimension);
- ``ts.continuity_error`` → one cumulative increment (+1); optional ``pid``;
- ``ts.pcr_jitter_observed`` → ``jitter_ns`` (histogram input) and optional
  ``gap_ns`` (repetition-gap gauge input); optional ``pid``;
- ``ts.psi_section_observed`` → ``gap_ms``; optional ``service_id``/``pid``;
- ``topology.state_changed`` → ``degraded_node_count`` (int).

Metrics without an MVP producer are still registered (catalog integrity):
``simulation.event_lag_ns`` needs explicit clock-mapping metadata (SPEC-300
§6 rule 3 — none exists in MVP envelopes), ``observation.alerts_active``
awaits the SPEC-304 alert store, and the ``observation.*`` family is sampled
operationally from the gateway/consumer faces (never from ``observation.*``
envelope events — that namespace is MVP-empty, SPEC-301 §4).
"""

from domain.observation import (
    AggregationOperation,
    HistogramSpec,
    MetricDefinition,
    MetricTemporality,
    MetricValueType,
)
from domain.observation.registry import (
    SIMULATION_CLOCK_EVENT_TYPES,
    SIMULATION_RUN_EVENT_TYPES,
    SIMULATION_SESSION_EVENT_TYPES,
)

from application.observation.metrics.registry import MetricRegistry

#: PCR jitter histogram edges (ns) — startup-validated, strictly increasing
#: (SPEC-302 §13: bucket config is a cardinality-explosion guard).
_PCR_JITTER_EDGES_NS = (
    0.0,
    100_000.0,
    500_000.0,
    1_000_000.0,
    5_000_000.0,
    10_000_000.0,
    50_000_000.0,
)

_SIMULATION_FAMILIES = (
    SIMULATION_SESSION_EVENT_TYPES
    | SIMULATION_RUN_EVENT_TYPES
    | SIMULATION_CLOCK_EVENT_TYPES
)

#: The 15 catalog names (SPEC-302 §4 table order) + the two Phase 3 alert
#: inputs (SPEC-304 §Phase3, ticket #166): the state_evaluator tuner-state
#: gauges derived from ``rf.state_observed`` snapshots.
CATALOG_METRIC_NAMES: tuple[str, ...] = (
    "ts.packet_rate",
    "ts.bitrate",
    "ts.continuity_error_total",
    "ts.pcr_jitter_ns",
    "ts.pcr_repetition_gap_ns",
    "ts.null_packet_ratio",
    "ts.scrambled_packet_ratio",
    "psi.section_repetition_gap_ms",
    "simulation.virtual_time_ns",
    "simulation.event_lag_ns",
    "topology.degraded_node_count",
    "observation.ingest_events_total",
    "observation.duplicate_events_total",
    "observation.consumer_lag_events",
    "observation.alerts_active",
    "tuner.lock_state",
    "tuner.ber_state",
)

_DEFINITIONS: tuple[MetricDefinition, ...] = (
    MetricDefinition(
        metric_name="ts.packet_rate",
        value_type=MetricValueType.GAUGE,
        unit="packets/s",
        description="packet rate derived from batch counts over source time",
        allowed_dimensions=("session_id", "stream_id"),
        source_event_types=("ts.packet_batch_observed",),
        aggregation=(
            AggregationOperation.LAST,
            AggregationOperation.AVG,
            AggregationOperation.MAX,
        ),
        temporality=MetricTemporality.INSTANT,
    ),
    MetricDefinition(
        metric_name="ts.bitrate",
        value_type=MetricValueType.GAUGE,
        unit="bit/s",
        description="bitrate derived from batch bytes over source time",
        allowed_dimensions=("session_id", "stream_id"),
        source_event_types=("ts.packet_batch_observed",),
        aggregation=(
            AggregationOperation.LAST,
            AggregationOperation.AVG,
            AggregationOperation.MAX,
        ),
        temporality=MetricTemporality.INSTANT,
    ),
    MetricDefinition(
        metric_name="ts.continuity_error_total",
        value_type=MetricValueType.COUNTER,
        unit="errors",
        description="cumulative continuity errors (ts.continuity_error events)",
        allowed_dimensions=("session_id", "pid"),
        source_event_types=("ts.continuity_error",),
        aggregation=(
            AggregationOperation.LAST,
            AggregationOperation.INCREASE,
            AggregationOperation.RATE,
        ),
        temporality=MetricTemporality.CUMULATIVE,
    ),
    MetricDefinition(
        metric_name="ts.pcr_jitter_ns",
        value_type=MetricValueType.HISTOGRAM,
        unit="ns",
        description="PCR jitter observations histogram",
        allowed_dimensions=("session_id", "pid"),
        source_event_types=("ts.pcr_jitter_observed",),
        aggregation=(
            AggregationOperation.COUNT,
            AggregationOperation.SUM,
            AggregationOperation.QUANTILE,
        ),
        temporality=MetricTemporality.INSTANT,
        histogram=HistogramSpec(bucket_edges=_PCR_JITTER_EDGES_NS),
    ),
    MetricDefinition(
        metric_name="ts.pcr_repetition_gap_ns",
        value_type=MetricValueType.GAUGE,
        unit="ns",
        description="PCR repetition gap observations",
        allowed_dimensions=("session_id", "pid"),
        source_event_types=("ts.pcr_jitter_observed",),
        aggregation=(
            AggregationOperation.LAST,
            AggregationOperation.AVG,
            AggregationOperation.MAX,
        ),
        temporality=MetricTemporality.INSTANT,
    ),
    MetricDefinition(
        metric_name="ts.null_packet_ratio",
        value_type=MetricValueType.GAUGE,
        unit="ratio",
        description="null-packet share of an observed batch (PID 0x1FFF)",
        allowed_dimensions=("session_id", "stream_id"),
        source_event_types=("ts.packet_batch_observed",),
        aggregation=(AggregationOperation.LAST, AggregationOperation.AVG),
        temporality=MetricTemporality.INSTANT,
    ),
    MetricDefinition(
        metric_name="ts.scrambled_packet_ratio",
        value_type=MetricValueType.GAUGE,
        unit="ratio",
        description="scrambled-packet share of an observed batch",
        allowed_dimensions=("session_id", "stream_id"),
        source_event_types=("ts.packet_batch_observed",),
        aggregation=(AggregationOperation.LAST, AggregationOperation.AVG),
        temporality=MetricTemporality.INSTANT,
    ),
    MetricDefinition(
        metric_name="psi.section_repetition_gap_ms",
        value_type=MetricValueType.GAUGE,
        unit="ms",
        description="PSI section repetition gap observations",
        allowed_dimensions=("session_id", "service_id", "pid"),
        source_event_types=("ts.psi_section_observed",),
        aggregation=(
            AggregationOperation.LAST,
            AggregationOperation.AVG,
            AggregationOperation.MAX,
        ),
        temporality=MetricTemporality.INSTANT,
    ),
    MetricDefinition(
        metric_name="simulation.virtual_time_ns",
        value_type=MetricValueType.GAUGE,
        unit="ns",
        description="virtual clock reading carried by simulation events",
        allowed_dimensions=("session_id",),
        source_event_types=tuple(sorted(_SIMULATION_FAMILIES)),
        aggregation=(
            AggregationOperation.LAST,
            AggregationOperation.MAX,
        ),
        temporality=MetricTemporality.INSTANT,
    ),
    MetricDefinition(
        metric_name="simulation.event_lag_ns",
        value_type=MetricValueType.GAUGE,
        unit="ns",
        description=(
            "observed/source clock mapping difference; derived only when an "
            "explicit clock mapping exists (SPEC-300 §6 rule 3 — none in MVP)"
        ),
        allowed_dimensions=("session_id",),
        source_event_types=tuple(sorted(_SIMULATION_FAMILIES)),
        aggregation=(AggregationOperation.LAST, AggregationOperation.AVG),
        temporality=MetricTemporality.INSTANT,
    ),
    MetricDefinition(
        metric_name="topology.degraded_node_count",
        value_type=MetricValueType.GAUGE,
        unit="nodes",
        description="degraded node count of the session topology",
        allowed_dimensions=("session_id",),
        source_event_types=("topology.state_changed",),
        snapshot_source="topology snapshot",
        aggregation=(AggregationOperation.LAST, AggregationOperation.MAX),
        temporality=MetricTemporality.INSTANT,
    ),
    MetricDefinition(
        metric_name="observation.ingest_events_total",
        value_type=MetricValueType.COUNTER,
        unit="events",
        description="gateway accepted-event counter (EventGateway.metrics)",
        allowed_dimensions=("session_id",),
        snapshot_source="EventGateway.metrics().accepted",
        aggregation=(
            AggregationOperation.LAST,
            AggregationOperation.INCREASE,
            AggregationOperation.RATE,
        ),
        temporality=MetricTemporality.CUMULATIVE,
    ),
    MetricDefinition(
        metric_name="observation.duplicate_events_total",
        value_type=MetricValueType.COUNTER,
        unit="events",
        description=(
            "duplicate events across both dedup layers "
            "(gateway cache + journal backstop, EventGateway.metrics)"
        ),
        allowed_dimensions=("session_id",),
        snapshot_source="EventGateway.metrics().duplicate + journal_duplicates",
        aggregation=(
            AggregationOperation.LAST,
            AggregationOperation.INCREASE,
            AggregationOperation.RATE,
        ),
        temporality=MetricTemporality.CUMULATIVE,
    ),
    MetricDefinition(
        metric_name="observation.consumer_lag_events",
        value_type=MetricValueType.GAUGE,
        unit="events",
        description="journal watermark minus consumer checkpoint (SPEC-300 §8)",
        allowed_dimensions=("session_id",),
        snapshot_source="JournalTailingConsumer.lag() (watermark − checkpoint)",
        aggregation=(AggregationOperation.LAST, AggregationOperation.MAX),
        temporality=MetricTemporality.INSTANT,
    ),
    MetricDefinition(
        metric_name="observation.alerts_active",
        value_type=MetricValueType.GAUGE,
        unit="alerts",
        description="active alert records (SPEC-304 store; producer lands with #52)",
        allowed_dimensions=("session_id",),
        snapshot_source="alert records (SPEC-304)",
        aggregation=(AggregationOperation.LAST, AggregationOperation.MAX),
        temporality=MetricTemporality.INSTANT,
    ),
    # --- Phase 3 alert inputs (SPEC-304 §Phase3, ticket #166) ---------------
    # Discrete tuner-state gauges derived from ``rf.state_observed``
    # (state_evaluator source, simulated confidence — the constant pairing,
    # SPEC-303 §Phase3).  Comparison semantics (frozen, ticket #166 REPORT):
    # lock_state locked=0.0 / unlocked=1.0 (alarm=1 boolean-style gauge);
    # ber_state normal=0.0 / elevated=1.0 / severe=2.0 (ordinal ladder —
    # elevated=1 satisfies no alert open condition, SPEC-304 §Phase3
    # elevated 不告警).  ``ber_state=null`` (unlocked keeps no grade) and
    # out-of-vocabulary strings yield no sample (缺失 ≠ 零).
    MetricDefinition(
        metric_name="tuner.lock_state",
        value_type=MetricValueType.GAUGE,
        unit="1",
        description=(
            "tuner lock state as a numeric code (locked=0, unlocked=1) "
            "derived from rf.state_observed snapshots"
        ),
        allowed_dimensions=("session_id", "node_id"),
        source_event_types=("rf.state_observed",),
        aggregation=(AggregationOperation.LAST, AggregationOperation.MAX),
        temporality=MetricTemporality.INSTANT,
    ),
    MetricDefinition(
        metric_name="tuner.ber_state",
        value_type=MetricValueType.GAUGE,
        unit="1",
        description=(
            "tuner BER state as a numeric code (normal=0, elevated=1, "
            "severe=2) derived from rf.state_observed snapshots"
        ),
        allowed_dimensions=("session_id", "node_id"),
        source_event_types=("rf.state_observed",),
        aggregation=(AggregationOperation.LAST, AggregationOperation.MAX),
        temporality=MetricTemporality.INSTANT,
    ),
)


def default_catalog() -> MetricRegistry:
    """The registry preloaded with the 15 SPEC-302 §4 catalog metrics."""
    return MetricRegistry(_DEFINITIONS)


__all__ = ["CATALOG_METRIC_NAMES", "default_catalog"]
