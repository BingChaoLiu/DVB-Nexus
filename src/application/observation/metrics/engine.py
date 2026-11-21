"""Metrics engine — journal-derived sample ingestion (SPEC-302, ticket #50).

The engine consumes committed journal records through the SPEC-300 §7
consumer posture (a :class:`JournalTailingConsumer` with consumer_id
``metrics-engine`` — :func:`build_metrics_consumer` wires it) and derives
catalog-metric samples from them:

- ``simulation.virtual_time_ns`` from every simulation-family event's
  ``time.source`` (sim domain only — the sim/wall separation of §9);
- the ``ts.*``/``psi.*`` family from the derivation contract documented in
  :mod:`application.observation.metrics.catalog` (G3: fixture contract until
  the analysis bridge lands — the engine never fabricates values);
- the ``observation.*`` operational family via :meth:`MetricsEngine.
  poll_operational` reading ``EventGateway.metrics()`` and the consumer lag
  (watermark − checkpoint) — stamped ``wall:utc``, an independent series
  universe (§9).

Derivation NEVER mutates source events (OBS-C must-not) and never attaches
diagnostic semantics (brief §6 axis discipline). Time-domain discipline: the
comparison entry points bind to :func:`ensure_same_time_domain` (SPEC-300
§6 rules 1/3/5 — the ``OBS_INVALID_TIME_DOMAIN`` guard).

Late-sample semantics (§6.2) live in the bucket ledgers — see
:meth:`MetricsEngine.compute_bucket` and :mod:`.service` for the query face.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable, Optional, Union

from application.observation.consumer import ConsumerConfig, JournalTailingConsumer
from application.observation.gateway import GatewayMetrics
from domain.observation import (
    MetricDefinition,
    MetricProvenance,
    MetricSample,
    MetricSampleTimepoint,
    SeriesQuality,
    ensure_same_time_domain,
)
from domain.observation.metric_series import SampleSemantics

from application.observation.metrics.catalog import default_catalog
from application.observation.metrics.registry import MetricRegistry
from application.observation.metrics.errors import (
    OBS_METRIC_CARDINALITY_EXCEEDED,
    OBS_METRIC_DIMENSION_REJECTED,
    OBS_METRIC_NOT_FOUND,
    MetricError,
)
from application.observation.metrics.store import (
    MetricSeriesStore,
    QuarantinedSample,
    RejectionEntry,
    canonical_series_key,
)

Number = Union[int, float]

# Discrete tuner-state sample codes (ticket #166, frozen comparison
# semantics — see the catalog Phase 3 note): the alarm-worthy state is the
# higher value, so a rule's open/close band never overlaps the neutral grade.
_STATE_CODE_LOCK_STATE = {"locked": 0.0, "unlocked": 1.0}
_STATE_CODE_BER_STATE = {"normal": 0.0, "elevated": 1.0, "severe": 2.0}

_REJECT_MODE = "reject"
_QUARANTINE_MODE = "quarantine"
_SIM_DOMAIN_PREFIX = "sim:"
_WALL_DOMAIN = "wall:utc"


@dataclass(frozen=True)
class MetricsEngineConfig:
    """Engine policies (SPEC-302 §6.2/§7)."""

    #: Backfill off (default): late samples never rewrite finalized
    #: aggregates. On: rewrites increment ``revision`` and stay
    #: ``is_final=false`` until re-finalization (§6.2).
    backfill_enabled: bool = False
    #: §7: 拒绝或隔离. ``reject`` refuses over-limit samples (recorded in
    #: the rejection stream on the consumer path, raised on the programmatic
    #: path); ``quarantine`` isolates them, observable and retrievable.
    cardinality_mode: str = _REJECT_MODE
    #: §7 每指标活跃序列数上限. Per-metric overrides ride on the definition
    #: quality policy in later tiers; one default keeps MVP uniform.
    default_max_series_per_metric: int = 1_000

    def __post_init__(self) -> None:
        if self.cardinality_mode not in (_REJECT_MODE, _QUARANTINE_MODE):
            raise ValueError(
                "cardinality_mode must be 'reject' or 'quarantine' "
                f"(SPEC-302 §7), got {self.cardinality_mode!r}"
            )
        if self.default_max_series_per_metric < 1:
            raise ValueError("default_max_series_per_metric must be >= 1")


class MetricsEngine:
    """Derives, admits and stores metric samples (SPEC-302 §1: 可解释派生).

    Every aggregate value stays traceable: samples carry the source event id
    and the journal watermark as provenance (§1 provenance duty).
    """

    def __init__(
        self,
        registry: MetricRegistry | None = None,
        config: MetricsEngineConfig | None = None,
    ) -> None:
        self._registry = registry if registry is not None else default_catalog()
        self._config = config or MetricsEngineConfig()
        self._store = MetricSeriesStore()
        self._rejections: list[RejectionEntry] = []
        self._counter_state: dict[tuple, Number] = {}
        self._watermark = 0
        self._lock = threading.Lock()

    # --- consumer face (SPEC-300 §7 posture) ---------------------------------

    @property
    def journal_watermark(self) -> int:
        """Max consumed ``journal_seq`` (provenance, SPEC-302 §1/§8)."""
        return self._watermark

    @property
    def rejections(self) -> tuple[RejectionEntry, ...]:
        """Recorded ingestion refusals (§7 reject mode; never silent)."""
        return tuple(self._rejections)

    def quarantined(self) -> tuple[QuarantinedSample, ...]:
        """§7 quarantine stream (isolated samples, observable/retrievable)."""
        return self._store.quarantined()

    def handle_record(self, record) -> None:
        """Consume one committed journal record (consumer handler face).

        Derives catalog samples and admits them. Policy violations are
        recorded (reject mode) or isolated (quarantine mode) — a handler
        that raises would crash-loop the tailing consumer's batch.
        """
        seq = getattr(record, "journal_seq", None)
        if seq is not None and seq > self._watermark:
            self._watermark = seq
        envelope = record.envelope
        event_type = record.event_type
        for sample in self._derive_samples(event_type, envelope):
            try:
                self._admit(sample, raise_on_policy=False)
            except MetricError as exc:
                self._rejections.append(
                    RejectionEntry(
                        code=exc.error_code,
                        message=str(exc),
                        journal_seq=seq,
                        detail=f"metric={sample.metric_name}",
                    )
                )

    # --- programmatic ingest ---------------------------------------------------

    def ingest_sample(self, sample: MetricSample) -> None:
        """Admit one already-built sample (programmatic path).

        Raises :class:`MetricError` for unknown metrics, dimension
        violations and (reject-mode) cardinality overflow — the structured
        contract for API-level callers.
        """
        self._admit(sample, raise_on_policy=True)

    # --- operational family (SPEC-302 §4 observation.*) ------------------------

    def poll_operational(
        self,
        session_id: str,
        *,
        gateway_metrics: GatewayMetrics,
        consumer_lag: int,
        wall_ns: int,
        alerts_active: Optional[int] = None,
    ) -> tuple[MetricSample, ...]:
        """Sample the ``observation.*`` family from the live faces.

        ``ingest_events_total`` ← ``GatewayMetrics.accepted``;
        ``duplicate_events_total`` ← gateway cache duplicates + journal
        backstop duplicates (the two dedup layers, both visible on
        ``GatewayMetrics``); ``consumer_lag_events`` ← watermark −
        checkpoint (the caller passes ``consumer.lag()``). Stamped
        ``wall:utc`` — wall-clock operational series never merge into
        virtual-time series (SPEC-302 §9).
        """
        samples = (
            self._operational_sample(
                "observation.ingest_events_total",
                session_id,
                gateway_metrics.accepted,
                wall_ns,
            ),
            self._operational_sample(
                "observation.duplicate_events_total",
                session_id,
                gateway_metrics.duplicate + gateway_metrics.journal_duplicates,
                wall_ns,
            ),
            self._operational_sample(
                "observation.consumer_lag_events",
                session_id,
                consumer_lag,
                wall_ns,
            ),
        )
        for sample in samples:
            self._admit(sample, raise_on_policy=False)
        if alerts_active is not None:
            alert_sample = self._operational_sample(
                "observation.alerts_active", session_id, alerts_active, wall_ns
            )
            self._admit(alert_sample, raise_on_policy=False)
            return samples + (alert_sample,)
        return samples

    # --- read face -------------------------------------------------------------

    def samples(
        self,
        metric_name: str,
        *,
        clock_domain: str,
        dimensions: Optional[dict] = None,
    ) -> tuple[MetricSample, ...]:
        """Recorded samples of the matching series, in arrival order."""
        matched = []
        for state in self._store.series_matching(
            metric_name, clock_domain, dimensions
        ):
            matched.extend(state.samples)
        return tuple(matched)

    def registry(self) -> MetricRegistry:
        """The engine's metric registry (catalog face)."""
        return self._registry

    @property
    def config(self) -> MetricsEngineConfig:
        """The engine's policies (§6.2 backfill / §7 cardinality)."""
        return self._config

    @property
    def store(self) -> MetricSeriesStore:
        """The derived-series store (read face for the query service)."""
        return self._store

    # --- internals: admission ----------------------------------------------------

    def _admit(self, sample: MetricSample, *, raise_on_policy: bool) -> None:
        definition = self._registry.get(sample.metric_name)
        if definition is None:
            raise MetricError(
                OBS_METRIC_NOT_FOUND,
                f"metric {sample.metric_name!r} is not registered; samples "
                "for unregistered metrics are refused (SPEC-302 §3)",
                details={"metric_name": sample.metric_name},
            )
        for dim in sample.dimensions:
            if dim not in definition.allowed_dimensions:
                raise MetricError(
                    OBS_METRIC_DIMENSION_REJECTED,
                    f"dimension {dim!r} is not allowed for "
                    f"{sample.metric_name!r} "
                    f"(allowed: {list(definition.allowed_dimensions)}; "
                    "SPEC-302 §5 strict default)",
                    details={"metric_name": sample.metric_name, "dimension": dim},
                )
        key = canonical_series_key(sample)
        with self._lock:
            is_new = self._store.is_new_series(key)
            if is_new and self._store.active_series_count(
                sample.metric_name
            ) >= self._config.default_max_series_per_metric:
                if self._config.cardinality_mode == _QUARANTINE_MODE:
                    self._store.quarantine(
                        QuarantinedSample(
                            code=OBS_METRIC_CARDINALITY_EXCEEDED,
                            message=(
                                f"active-series limit "
                                f"{self._config.default_max_series_per_metric} "
                                f"reached for {sample.metric_name!r} — "
                                "sample quarantined (SPEC-302 §7)"
                            ),
                            sample=sample,
                        )
                    )
                    return
                raise MetricError(
                    OBS_METRIC_CARDINALITY_EXCEEDED,
                    f"active-series limit "
                    f"{self._config.default_max_series_per_metric} reached "
                    f"for {sample.metric_name!r} (SPEC-302 §7)",
                    details={
                        "metric_name": sample.metric_name,
                        "limit": self._config.default_max_series_per_metric,
                    },
                )
            state = (
                self._store.create(key)
                if is_new
                else self._store.get(key)
            )
            sample = self._flag_late(definition, state, sample)
            if state.samples:
                # Time-domain binding (SPEC-300 §6): comparisons inside a
                # series refuse cross-(domain, epoch) mixing explicitly.
                ensure_same_time_domain(state.samples[-1].time, sample.time)
            state.append(sample)

    def _flag_late(
        self,
        definition: MetricDefinition,
        state,
        sample: MetricSample,
    ) -> MetricSample:
        """Mark arrivals past the series' lateness horizon (§6.2)."""
        lateness = definition.quality_policy.lateness_window_ns
        if state.high_ns is not None and state.high_ns > (
            sample.time.value_ns + lateness
        ):
            quality = sample.quality
            if SeriesQuality.LATE not in quality:
                sample = sample.model_copy(
                    update={"quality": tuple(quality) + (SeriesQuality.LATE,)}
                )
        return sample

    def _operational_sample(
        self,
        metric_name: str,
        session_id: str,
        value: Number,
        wall_ns: int,
    ) -> MetricSample:
        return MetricSample(
            metric_name=metric_name,
            time=MetricSampleTimepoint(
                value_ns=wall_ns,
                clock_domain=_WALL_DOMAIN,
                clock_epoch=0,
                semantics=SampleSemantics.OBSERVED,
            ),
            value=value,
            dimensions={"session_id": session_id},
            quality=(SeriesQuality.GOOD,),
            provenance=MetricProvenance(journal_watermark=self._watermark),
        )

    # --- internals: derivation ----------------------------------------------------

    def _derive_samples(self, event_type: str, envelope: dict) -> list:
        scope = envelope.get("scope") or {}
        session_id = scope.get("session_id")
        time_block = envelope.get("time") or {}
        source = time_block.get("source") or {}
        payload = envelope.get("payload") or {}
        correlation = envelope.get("correlation") or {}

        sourced = self._sources_for(event_type)
        if sourced and not session_id:
            # Session-domain metrics carry the session in dimensions (§5);
            # a system-level record has no session to attribute — one
            # rejection per record, never a silent attribution to "".
            self._rejections.append(
                RejectionEntry(
                    code=OBS_METRIC_DIMENSION_REJECTED,
                    message=(
                        "session-domain metrics cannot be derived from a "
                        "record without scope.session_id (SPEC-302 §5)"
                    ),
                    journal_seq=self._watermark,
                    detail=f"event_type={event_type}",
                )
            )
            return []

        derived: list[MetricSample] = []
        for name in sourced:
            definition = self._registry.require(name)
            derived.extend(
                self._derive_one(
                    name, definition, session_id, source, payload, correlation
                )
            )
        if not derived:
            return []
        # §1 provenance duty: every derived sample traces to its source
        # event id and the journal watermark.
        event_id = envelope.get("event_id")
        stamped = []
        for sample in derived:
            stamped.append(
                sample.model_copy(
                    update={
                        "provenance": MetricProvenance(
                            source_event_ids=(event_id,) if event_id else (),
                            journal_watermark=self._watermark,
                        )
                    }
                )
            )
        return stamped

    def _sources_for(self, event_type: str) -> tuple[str, ...]:
        return tuple(
            definition.metric_name
            for definition in self._registry_names()
            if event_type in definition.source_event_types
        )

    def _registry_names(self) -> list[MetricDefinition]:
        return [
            self._registry.get(name)  # type: ignore[arg-type]
            for name in self._registry.names()
            if self._registry.get(name) is not None
        ]

    def _derive_one(
        self,
        metric_name: str,
        definition: MetricDefinition,
        session_id: str,
        source: dict,
        payload: dict,
        correlation: dict,
    ) -> list[MetricSample]:
        builder = self._BUILDERS.get(metric_name)
        if builder is None:
            # Registered but without an MVP derivation (e.g.
            # simulation.event_lag_ns — needs explicit clock-mapping
            # metadata, SPEC-300 §6 rule 3). Registered ≠ derived: skip
            # until its data source lands, never fabricate.
            return []
        return builder(self, definition, session_id, source, payload, correlation)

    # Each builder returns 0..n samples; a payload missing its derivation key
    # yields none (the engine never fabricates values, SPEC-302 §6.3).

    def _build_simulation_virtual_time_ns(
        self, definition, session_id, source, payload, correlation
    ) -> list:
        domain = source.get("clock_domain") or ""
        if not domain.startswith(_SIM_DOMAIN_PREFIX):
            return []  # §9: only the virtual clock feeds this series
        value = _number(source, "value_ns")
        if value is None:
            return []
        return [
            self._sample_from_source(
                definition,
                session_id,
                source,
                value,
                {"session_id": session_id},
                None,
            )
        ]

    def _build_ts_continuity_error_total(
        self, definition, session_id, source, payload, correlation
    ) -> list:
        dims = self._dimensions(
            definition, session_id, payload, correlation
        )
        key = (definition.metric_name, source.get("clock_domain"), dims_tuple_of(dims))
        state = self._counter_state.get(key, 0)
        self._counter_state[key] = state + 1
        return [
            self._sample_from_source(
                definition, session_id, source, state + 1, dims, None
            )
        ]

    def _build_ts_pcr_jitter_ns(
        self, definition, session_id, source, payload, correlation
    ) -> list:
        value = _number(payload, "jitter_ns")
        if value is None:
            return []
        dims = self._dimensions(definition, session_id, payload, correlation)
        return [
            self._sample_from_source(
                definition, session_id, source, value, dims, None
            )
        ]

    def _build_ts_pcr_repetition_gap_ns(
        self, definition, session_id, source, payload, correlation
    ) -> list:
        value = _number(payload, "gap_ns")
        if value is None:
            return []
        dims = self._dimensions(definition, session_id, payload, correlation)
        return [
            self._sample_from_source(
                definition, session_id, source, value, dims, None
            )
        ]

    def _build_ts_packet_rate(
        self, definition, session_id, source, payload, correlation
    ) -> list:
        return self._packet_batch_metric(
            definition, session_id, source, payload, correlation, "rate"
        )

    def _build_ts_bitrate(
        self, definition, session_id, source, payload, correlation
    ) -> list:
        return self._packet_batch_metric(
            definition, session_id, source, payload, correlation, "bitrate"
        )

    def _build_ts_null_packet_ratio(
        self, definition, session_id, source, payload, correlation
    ) -> list:
        return self._packet_batch_metric(
            definition, session_id, source, payload, correlation, "null"
        )

    def _build_ts_scrambled_packet_ratio(
        self, definition, session_id, source, payload, correlation
    ) -> list:
        return self._packet_batch_metric(
            definition, session_id, source, payload, correlation, "scrambled"
        )

    def _packet_batch_metric(
        self,
        definition,
        session_id,
        source,
        payload,
        correlation,
        kind: str,
    ) -> list:
        packet_count = _number(payload, "packet_count")
        byte_count = _number(payload, "byte_count")
        duration_ns = _number(payload, "duration_ns")
        if packet_count is None or byte_count is None:
            return []
        if duration_ns is None or duration_ns <= 0:
            return []
        if kind == "rate":
            value = packet_count * 1_000_000_000 / duration_ns
        elif kind == "bitrate":
            value = byte_count * 8 * 1_000_000_000 / duration_ns
        else:
            if packet_count <= 0:
                return []
            count_key = (
                "null_packet_count" if kind == "null" else "scrambled_packet_count"
            )
            counted = _number(payload, count_key)
            if counted is None:
                counted = 0
            value = counted / packet_count
        dims = self._dimensions(definition, session_id, payload, correlation)
        return [
            self._sample_from_source(
                definition, session_id, source, value, dims, None
            )
        ]

    def _build_psi_section_repetition_gap_ms(
        self, definition, session_id, source, payload, correlation
    ) -> list:
        value = _number(payload, "gap_ms")
        if value is None:
            return []
        dims = self._dimensions(definition, session_id, payload, correlation)
        return [
            self._sample_from_source(
                definition, session_id, source, value, dims, None
            )
        ]

    def _build_topology_degraded_node_count(
        self, definition, session_id, source, payload, correlation
    ) -> list:
        value = _number(payload, "degraded_node_count")
        if value is None:
            return []
        return [
            self._sample_from_source(
                definition, session_id, source, value, {"session_id": session_id}, None
            )
        ]

    def _build_tuner_lock_state(
        self, definition, session_id, source, payload, correlation
    ) -> list:
        # Discrete-state gauge (ticket #166): locked=0.0 / unlocked=1.0
        # (alarm=1).  Unknown strings yield no sample (缺失 ≠ 零) — the
        # payload registry is the first line of defence, this is the second.
        value = _STATE_CODE_LOCK_STATE.get(payload.get("lock_state"))
        if value is None:
            return []
        dims = self._dimensions(definition, session_id, payload, correlation)
        return [
            self._sample_from_source(definition, session_id, source, value, dims, None)
        ]

    def _build_tuner_ber_state(
        self, definition, session_id, source, payload, correlation
    ) -> list:
        # Ordinal ladder (ticket #166): normal=0.0 / elevated=1.0 / severe=2.0.
        # ``ber_state=null`` (unlocked keeps no grade — the #164 registry face)
        # and unknown strings yield no sample; the retired grade is never
        # re-fabricated as a fresh reading (SPEC-620 §8 honesty).
        value = _STATE_CODE_BER_STATE.get(payload.get("ber_state"))
        if value is None:
            return []
        dims = self._dimensions(definition, session_id, payload, correlation)
        return [
            self._sample_from_source(definition, session_id, source, value, dims, None)
        ]

    def _dimensions(
        self,
        definition: MetricDefinition,
        session_id: str,
        payload: dict,
        correlation: dict,
    ) -> dict:
        dims = {"session_id": session_id}
        candidates = {
            "pid": _first_not_none(payload.get("pid"), correlation.get("pid")),
            "service_id": _first_not_none(
                payload.get("service_id"), correlation.get("service_id")
            ),
            "stream_id": payload.get("stream_id"),
            "node_id": _first_not_none(
                payload.get("node_id"), correlation.get("node_id")
            ),
            "fault_type": payload.get("fault_type"),
        }
        for dim, value in candidates.items():
            if dim not in definition.allowed_dimensions or value is None:
                continue
            if dim == "pid":
                try:
                    value = int(value)
                except (TypeError, ValueError):
                    continue  # untrustworthy pid: skip the dimension
            dims[dim] = value
        return dims

    def _sample_from_source(
        self,
        definition: MetricDefinition,
        session_id: str,
        source: dict,
        value: Number,
        dims: dict,
        event_id: Optional[str],
    ) -> MetricSample:
        return MetricSample(
            metric_name=definition.metric_name,
            time=MetricSampleTimepoint(
                value_ns=int(source["value_ns"]),
                clock_domain=source["clock_domain"],
                clock_epoch=int(source.get("clock_epoch", 0)),
                semantics=SampleSemantics.SOURCE,
            ),
            value=value,
            dimensions=dict(dims),
            quality=(SeriesQuality.GOOD,),
            provenance=MetricProvenance(
                source_event_ids=(event_id,) if event_id else (),
                journal_watermark=self._watermark,
            ),
        )

    _BUILDERS: dict[str, Callable] = {
        "simulation.virtual_time_ns": _build_simulation_virtual_time_ns,
        "ts.continuity_error_total": _build_ts_continuity_error_total,
        "ts.pcr_jitter_ns": _build_ts_pcr_jitter_ns,
        "ts.pcr_repetition_gap_ns": _build_ts_pcr_repetition_gap_ns,
        "ts.packet_rate": _build_ts_packet_rate,
        "ts.bitrate": _build_ts_bitrate,
        "ts.null_packet_ratio": _build_ts_null_packet_ratio,
        "ts.scrambled_packet_ratio": _build_ts_scrambled_packet_ratio,
        "psi.section_repetition_gap_ms": _build_psi_section_repetition_gap_ms,
        "topology.degraded_node_count": _build_topology_degraded_node_count,
        "tuner.lock_state": _build_tuner_lock_state,
        "tuner.ber_state": _build_tuner_ber_state,
    }


def _number(mapping: dict, key: str) -> Optional[Number]:
    """A finite JSON number that is not a bool — else None (never fabricate)."""
    value = mapping.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


def _first_not_none(*values):
    for value in values:
        if value is not None:
            return value
    return None


def dims_tuple_of(dimensions: dict) -> tuple:
    return tuple(sorted(dimensions.items()))


def build_metrics_consumer(
    journal,
    checkpoints,
    session_id: str,
    engine: MetricsEngine,
    *,
    batch_size: int = 100,
) -> JournalTailingConsumer:
    """The SPEC-300 §7 consumption posture of the metrics engine.

    A :class:`JournalTailingConsumer` with consumer_id ``metrics-engine``
    tailing the committed journal into :meth:`MetricsEngine.handle_record`.
    """
    return JournalTailingConsumer(
        journal=journal,
        checkpoints=checkpoints,
        session_id=session_id,
        consumer_id="metrics-engine",
        handler=engine.handle_record,
        config=ConsumerConfig(batch_size=batch_size),
    )


__all__ = [
    "MetricsEngine",
    "MetricsEngineConfig",
    "build_metrics_consumer",
]
