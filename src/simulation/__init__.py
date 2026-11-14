"""Simulation runtime layer (SPEC-001 section 3.4).

MVP scope: the unified ``SimulationRuntime`` interface plus the TS runtime
implementation (ADR-0005 decisions 2 and 4). Depends on ``ts``, ``faults``
and ``adapters``; long tasks must be cancellable and must never block the API
event loop.
"""
