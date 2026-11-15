"""The production semantic stream filter (ADR-0007 item 1, ticket #44).

:class:`SemanticFaultFilter` is the production :class:`simulation.
ts_runtime.FaultFilter`: for every packet of the Generator output stream
it applies each planned fault's slot-preserving transform in plan order
and returns the (possibly rewritten) packet for the faulted tee leg.  The
baseline leg receives the untouched packet, so the two legs share one
packet frame (§7 slot-preserving invariant) and tee stays index-aligned.

Pure stream transform: no I/O, no wall clock, no randomness — the same
(plan, stream) always yields the same faulted stream and the same
mutation log (REQ-SIM-204-002).
"""

from __future__ import annotations

from typing import Any, Mapping

from ts.packet import TSPacket

from faults.definition import FaultDefinition
from faults.filters.base import FaultTransform, MutationRecord
from faults.mutation_log import (
    build_mutation_log_document,
    lifecycle_summary,
    serialize_mutation_log,
)
from faults.registry import transform_builder_for, validate_fault_definition

__all__ = ["SemanticFaultFilter"]


class SemanticFaultFilter:
    """Compose one plan's fault transforms into a single packet filter."""

    def __init__(
        self,
        plan: tuple[FaultDefinition, ...],
        *,
        run_id: str | None = None,
    ) -> None:
        self._plan = tuple(plan)
        self._run_id = run_id
        self._transforms: list[FaultTransform] = []
        for definition in self._plan:
            # Defense in depth: prepare already validated (AC-204-01); the
            # filter refuses to run an unvalidated definition rather than
            # silently mis-transforming.
            details = validate_fault_definition(definition)
            if details:
                raise ValueError(
                    "SemanticFaultFilter received an invalid fault "
                    f"definition ({definition.fault_id!r}): "
                    + "; ".join(details)
                )
            builder = transform_builder_for(definition.fault_type)
            self._transforms.append(builder(definition))

    def apply(self, index: int, packet: Any) -> Any:
        """FaultFilter hook: one packet in, one packet out, same slot."""
        for transform in self._transforms:
            packet = transform.apply(index, packet)
        return packet

    def mutation_log(self) -> bytes:
        """The ``log`` tee leg bytes (SPEC-204 §8.2 evidence locator)."""
        faults: tuple[Mapping[str, Any], ...] = tuple(
            self._fault_summary(transform) for transform in self._transforms
        )
        mutations: tuple[Mapping[str, Any], ...] = tuple(
            self._mutation_entry(record) for record in self._all_records()
        )
        document = build_mutation_log_document(
            faults,
            mutations,
            run_id=self._run_id,
        )
        return serialize_mutation_log(document)

    # --- internals ------------------------------------------------------------------

    def _all_records(self) -> list[MutationRecord]:
        records: list[MutationRecord] = []
        for transform in self._transforms:
            records.extend(transform.records)
        records.sort(key=lambda record: record.packet_index)
        return records

    @staticmethod
    def _fault_summary(transform: FaultTransform) -> dict[str, Any]:
        definition = transform._definition
        target = transform.target
        activated = transform.activation_index
        return {
            "fault_id": definition.fault_id,
            "fault_type": definition.fault_type,
            "target": {
                "node_id": target.node_id,
                "pid": target.pid,
            },
            "activation": {
                "kind": definition.activation.kind,
                "packet_index": definition.activation.packet_index,
            },
            "parameters": dict(definition.parameters),
            "parameters_schema_version": 1,
            "expected_observations": list(definition.expected_observations),
            "lifecycle": lifecycle_summary(
                injected=True,
                # session_start is ACTIVE from the stream start (index 0).
                activated_packet_index=activated,
                applied_packet_indexes=transform.applied_packet_indexes,
                cleared=True,  # the MVP window always ends with the run
            ),
        }

    @staticmethod
    def _mutation_entry(record: MutationRecord) -> dict[str, Any]:
        return {
            "fault_id": record.fault_id,
            "fault_type": record.fault_type,
            "target": {
                "node_id": record.target_node_id,
                "pid": record.target_pid,
            },
            "packet_index": record.packet_index,
            "before": dict(record.before),
            "after": dict(record.after),
            "change": record.change,
            "parameters": dict(record.parameters),
            "parameters_schema_version": record.parameters_schema_version,
        }
