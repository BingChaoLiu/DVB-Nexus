"""Metric registry — definition registration and lookup (SPEC-302 §3/§5).

Startup face: definitions validate themselves on construction (dimension
whitelist, aggregation legality, histogram bucket config — SPEC-302 §13);
the registry owns name uniqueness and the query-time structured refusals
(``OBS_METRIC_NOT_FOUND`` / ``OBS_METRIC_DIMENSION_REJECTED``).
"""

from typing import Any, Mapping, Optional

from domain.observation import MetricDefinition

from application.observation.metrics.errors import (
    OBS_METRIC_DIMENSION_REJECTED,
    OBS_METRIC_NOT_FOUND,
    MetricError,
)


class MetricRegistry:
    """Immutable-after-registration metric definition registry."""

    def __init__(self, definitions: tuple[MetricDefinition, ...] = ()) -> None:
        self._definitions: dict[str, MetricDefinition] = {}
        for definition in definitions:
            self.register(definition)

    def register(self, definition: MetricDefinition) -> None:
        """Register one validated definition; duplicate names fail fast."""
        if definition.metric_name in self._definitions:
            raise ValueError(
                f"metric {definition.metric_name!r} is already registered "
                "(duplicate catalog entries fail fast at startup)"
            )
        self._definitions[definition.metric_name] = definition

    def get(self, metric_name: str) -> Optional[MetricDefinition]:
        return self._definitions.get(metric_name)

    def require(
        self, metric_name: str, *, allow_unknown: bool = False
    ) -> Optional[MetricDefinition]:
        """Lookup or refuse with ``OBS_METRIC_NOT_FOUND`` (SPEC-302 §8).

        ``allow_unknown=True`` answers ``None`` instead — the caller skips
        the name (unknown names never silently fabricate empty series).
        """
        definition = self._definitions.get(metric_name)
        if definition is None and not allow_unknown:
            raise MetricError(
                OBS_METRIC_NOT_FOUND,
                f"unknown metric {metric_name!r} "
                "(SPEC-302 §8: 未知指标拒绝，除非 allow_unknown=true)",
                details={"metric_name": metric_name},
            )
        return definition

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._definitions))

    def validate_dimension_filters(
        self, definition: MetricDefinition, filters: Mapping[str, Any]
    ) -> None:
        """Refuse filters on non-allowed dimensions (SPEC-302 §8; §10 code).

        Strict default: unknown dimensions are rejected, never dropped.
        """
        for dim in filters:
            if dim not in definition.allowed_dimensions:
                raise MetricError(
                    OBS_METRIC_DIMENSION_REJECTED,
                    f"dimension {dim!r} is not an allowed dimension of "
                    f"{definition.metric_name!r} "
                    f"(allowed: {list(definition.allowed_dimensions)}; "
                    "SPEC-302 §5/§8 strict default)",
                    details={
                        "metric_name": definition.metric_name,
                        "dimension": dim,
                        "allowed_dimensions": list(definition.allowed_dimensions),
                    },
                )


__all__ = ["MetricRegistry"]
