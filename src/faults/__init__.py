"""Fault pipeline: fault definitions, triggering, transformation and recording.

Applies ``FaultDefinition`` to the TS packet model (semantic route) and routes
transport-level faults through the ``adapters.tsduck`` interface (dual route,
ADR-0005 decision 4). MVP only uses slot-preserving substitution: equal-slot
rewrites, no packet insertion or removal.
"""
