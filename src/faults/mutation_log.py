"""SPEC-204 §8.2 — mutation log document (AC-204-04 evidence locator).

One record per actual transformation, plus the per-fault lifecycle
summary (§8.1 four states mapped to the ADR-0006 item 5 ``fault.*`` event
codes).  The document is the ``log`` tee leg artifact of a tee run
(SPEC-203 §5.2).  Serialization is deterministic JSON (key-sorted, UTF-8,
compact separators) so REQ-SIM-204-002's byte-identical reproduction
covers the log too.

Evidence-locator discipline: from a fault event the reader reaches the
log record via ``fault_id``; from the record the reader reaches the same
slot in BOTH streams via ``packet_index`` on the shared packet frame
(ADR-0007 item 4: baseline and faulted share one packet sequence, so the
index addresses one slot in generated_ts and faulted_ts alike).  The
``run_id`` and the tee artifact kinds bind the log to its run — the
TSRuntime registers the log artifact under the run in the SPEC-502/503
index, which is the ``generated_ts``/``faulted_ts`` double reference.
"""

from __future__ import annotations

from typing import Any, Mapping

from faults.registry import PARAMETERS_SCHEMA_VERSION
from ts.canonical_json import canonical_json

__all__ = [
    "MUTATION_LOG_SCHEMA_VERSION",
    "build_mutation_log_document",
    "serialize_mutation_log",
]

#: Mutation log document schema generation (SPEC-301 §7-style versioning:
#: additive optional fields = minor; removals/rename = major).
MUTATION_LOG_SCHEMA_VERSION = 1

_LIFECYCLE_STATE_FOR_EVENT = {
    "fault.injected": "SCHEDULED",
    "fault.activated": "ACTIVE",
    "fault.applied": "APPLIED",
    "fault.cleared": "REMOVED",
}


def build_mutation_log_document(
    faults: tuple[Mapping[str, Any], ...],
    mutations: tuple[Mapping[str, Any], ...],
    *,
    run_id: str | None,
) -> dict[str, Any]:
    """Assemble the §8.2 document from per-fault summaries + records.

    ``faults`` entries (one per plan fault, plan order) carry the fault
    identity, target addressing, activation, effective parameter snapshot
    with ``parameters_schema_version``, ``expected_observations`` and the
    §8.1 lifecycle mapping.  ``mutations`` entries are the per-slot
    records (packet order).  Pure and deterministic.
    """
    return {
        "schema": "dvb-nexus-mutation-log/1.0 (SPEC-204 §8.2)",
        "schema_version": MUTATION_LOG_SCHEMA_VERSION,
        "parameters_schema_version": PARAMETERS_SCHEMA_VERSION,
        "run_id": run_id,
        "artifact_refs": {
            "generated_ts": (
                "kind=generated_ts baseline tee leg of this run — located "
                "by run_id in the artifact index (SPEC-203 §5.2)"
            ),
            "faulted_ts": (
                "kind=faulted_ts faulted tee leg of this run — located "
                "by run_id in the artifact index (SPEC-203 §5.2)"
            ),
            "shared_frame": (
                "packet_index addresses the SAME slot in both streams "
                "(ADR-0007 item 4 slot-preserving substitution)"
            ),
        },
        "faults": [dict(entry) for entry in faults],
        "mutations": [dict(entry) for entry in mutations],
    }


def serialize_mutation_log(document: Mapping[str, Any]) -> bytes:
    """Deterministic UTF-8 JSON serialization (key-sorted, compact)."""
    return canonical_json(document).encode("utf-8")


def lifecycle_summary(
    *,
    injected: bool,
    activated_packet_index: int,
    applied_packet_indexes: tuple[int, ...],
    cleared: bool,
) -> dict[str, Any]:
    """§8.1 four-state lifecycle mapped to the ``fault.*`` event codes."""
    return {
        "events": _LIFECYCLE_STATE_FOR_EVENT,
        "fault.injected": injected,
        "fault.activated": activated_packet_index,
        "fault.applied": list(applied_packet_indexes),
        "fault.cleared": cleared,
    }
