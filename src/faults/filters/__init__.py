"""Semantic fault transforms (SPEC-204 §5/§6 — one module per fault type).

Each transform is a slot-preserving rewriter over the ``ts.packet``
object model (ADR-0007 item 1/4); :mod:`faults.filters.semantic` composes
a plan's transforms into the :class:`simulation.ts_runtime.FaultFilter`
stream filter.
"""
