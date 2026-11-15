"""SPEC-200 section 4 — Snapshot as a pull API (ticket #41).

Snapshot semantics (SPEC-200 section 4, ADR-0006 decision 5):

- A snapshot is a **full replacement view**: session ID, monotonic
  revision, virtual time, lifecycle state, topology revision, node and
  connection states, active faults and the latest artifact references.
- It is a **pull** state API with a ``journal_seq`` cursor parameter — the
  full-state object never travels the event stream (``snapshot.updated``
  is withdrawn from the registry, ADR-0006 decision 5). The consumer's
  reconnect protocol is: pull snapshot + tail the journal from the cursor
  (SPEC-301 section 5). The runtime accepts and echoes the caller's
  cursor; the journal tail position itself is observation-plane state
  (gateway/journal, #47) and is deliberately not duplicated here.
- The snapshot is read-only and mirrors authoritative state — it is never
  the authority itself (data-ownership table, SPEC-300 section 5).

The value object itself lives beside the rest of the runtime's public data
model in :mod:`simulation.runtime` (SPEC-200 section 12 allows merging the
suggested files); this module is the documented pull-API home of the name.
"""

from __future__ import annotations

from simulation.runtime import SimulationSnapshot

__all__ = ["SimulationSnapshot"]
