"""Fault pipeline: fault definitions, triggering, transformation and recording.

Applies ``FaultDefinition`` to the TS packet model (semantic route) and routes
transport-level faults through the ``adapters.tsduck`` interface (dual route,
ADR-0005 decision 4). MVP only uses slot-preserving substitution: equal-slot
rewrites, no packet insertion or removal.

Module map (#44, SPEC-204):

- :mod:`faults.definition` - canonical ``FaultDefinition`` /
  ``FaultActivation`` data models (SPEC-204 section 3).
- :mod:`faults.targets` - target slug parsing (node_id + pid dual form,
  ADR-0006 item 3).
- :mod:`faults.registry` - the MVP fault-type registry, versioned
  parameter schemas (section 4/6) and the section 11 prepare-half
  validation codes.
- :mod:`faults.filters` - the slot-preserving semantic transforms
  (section 5/6) and the composed
  :class:`faults.filters.semantic.SemanticFaultFilter`.
- :mod:`faults.mutation_log` - the section 8.2 mutation log document
  (AC-204-04 evidence locator).
- :mod:`faults.factory` - the production ``FaultFilter`` factory for the
  composition root (``TSRuntime(filter_factory=...)``).
- :mod:`faults.errors` - ``SIM_FAULT_EXEC_FAILED`` run-stage failures.

Import contract (ADR-0005 D4-4): ``faults`` imports ``ts`` and the
``adapters.tsduck`` interface only - never ``simulation`` (the prepare
exception face stays on the simulation side of the edge),
``adapters.storage``, ``domain``, ``application`` or ``api``.
"""
