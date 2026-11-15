"""Fault execution errors (SPEC-204 §11, ticket #44).

``faults`` cannot import ``simulation`` (import contract), so the
run-stage failure code is declared here.  A transform raising
:class:`FaultExecutionError` surfaces through the SPEC-203 run semantics
(the TSRuntime wraps worker exceptions as ``SIM_TS_GENERATION_FAILED``
with the root cause attached) — the message carries
``SIM_FAULT_EXEC_FAILED`` so the fault lands in the FAILED state per
SPEC-204 §8.1.
"""

from __future__ import annotations

__all__ = [
    "SIM_FAULT_EXEC_FAILED",
    "FaultExecutionError",
]

#: SPEC-204 §11 — a fault transformation raised during the run.
SIM_FAULT_EXEC_FAILED = "SIM_FAULT_EXEC_FAILED"


class FaultExecutionError(Exception):
    """``SIM_FAULT_EXEC_FAILED``: run-stage transform failure.

    Raised by a fault transform when the stream shape makes the declared
    transformation impossible (e.g. a PAT section fragmenting across
    packets, which the MVP slot-preserving rewriter cannot repack in
    place).  The TSRuntime treats it as a generation failure; the fault
    state is FAILED (SPEC-204 §8.1).
    """

    code = SIM_FAULT_EXEC_FAILED
