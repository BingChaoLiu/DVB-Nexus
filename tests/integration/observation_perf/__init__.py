"""Ticket #57 (OBS-G) — cross-module observation integration & performance.

Integration-layer subpackage: read-only consumption of every prior-ticket
face (SPEC-300 §7 data flow, OBSERVATION-INTEGRATION-CONTRACT §8 order);
the load profile lives in ``test_obs_perf_profile.py`` under the ``slow``
marker (CI-green combination excludes it, ADR-0008 §5).
"""
