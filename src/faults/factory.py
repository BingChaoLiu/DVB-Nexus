"""Production fault filter factory — the composition-root wiring (#44).

The composition root constructs the SPEC-203 runtime with the production
semantic filter::

    from faults.factory import build_semantic_filter_factory
    from simulation.ts_runtime import TSRuntime

    ts_runtime = TSRuntime(filter_factory=build_semantic_filter_factory())

With this wiring, a prepared run whose fault plan is non-empty tees
double-writes through the real slot-preserving filter (baseline leg =
Generator bytes, faulted leg = filtered bytes, log leg = the SPEC-204
§8.2 mutation log); an empty plan stays baseline-only.  This closes the
#43 deviation 4 gap ("non-empty plan without a wired filter raises
ValueError"): the ValueError remains the guard for a runtime constructed
without a factory — the composition root is expected to always pass the
production factory.

The factory accepts the optional keyword-only ``run_id`` the TSRuntime
injects when the factory signature supports it, so the mutation log can
carry the run binding (SPEC-204 §8.2).

Phase 2 (#121, orchestrator ruling §10-4) adds the pluggable
transform registration:

- :func:`register_transform` lets downstream tickets (#123 / #124 /
  #126 / #127) bind their real filter builders from their OWN modules
  via import side effects — ``factory.py`` is never edited again.
- :func:`transform_builder_for` is the public resolution wrapper (override
  table first, then the MVP built-in table in :mod:`faults.registry`).
- The module-level wiring at the bottom registers #121's four Phase 2
  skeleton builders (:mod:`faults.filters.phase2_skeletons`); downstream
  tickets replace them with ``allow_replace=True``.

Registration semantics (frozen; pinned by
``tests/unit/faults/test_factory_pluggable.py``):

- same ``(fault_type, builder)`` pair again → idempotent no-op;
- same ``fault_type`` with a different builder → ``ValueError`` unless
  ``allow_replace=True``;
- unknown ``fault_type`` (not in ``KNOWN_FAULT_TYPES``) → ``ValueError``.
"""

from __future__ import annotations

from typing import Callable

from ts.generator.config import GeneratorConfig

from faults.definition import FaultDefinition
from faults.filters.semantic import SemanticFaultFilter
from faults.registry import (
    FAULT_TYPE_BBHEADER_SYNC_FAULT,
    FAULT_TYPE_BISS_KEY_MISMATCH,
    FAULT_TYPE_PMT_PID_DRIFT,
    FAULT_TYPE_T2MI_PLP_MISMATCH,
    KNOWN_FAULT_TYPES,
)

__all__ = [
    "FilterFactoryWithRunId",
    "build_semantic_filter_factory",
    "create_fault_filter",
    "override_builder_for",
    "register_transform",
    "transform_builder_for",
]

#: Production factory shape: plan + config + optional run binding.
FilterFactoryWithRunId = Callable[
    [tuple[FaultDefinition, ...], GeneratorConfig], SemanticFaultFilter
]

#: Transform builder shape: canonical definition → slot-preserving transform.
TransformBuilder = Callable[[FaultDefinition], object]

# --- pluggable transform registration (ticket #121, ruling §10-4) ----------------

#: Process-global downstream registration table consulted by
#: :func:`faults.registry.transform_builder_for` before the skeleton and
#: MVP built-in tables.  Tests isolate it via monkeypatch (never mutate
#: it in place).
_EXTRA_BUILDERS: dict[str, TransformBuilder] = {}

#: #121 skeleton wiring (placeholders, explicit NotImplementedError):
#: a separate fallback tier so downstream self-registration never
#: collides with a placeholder — duplicate detection applies only within
#: ``_EXTRA_BUILDERS``.
_SKELETON_BUILDERS: dict[str, TransformBuilder] = {}


def register_transform(
    fault_type: str,
    builder: TransformBuilder,
    *,
    allow_replace: bool = False,
) -> None:
    """Register the transform ``builder`` for ``fault_type`` (Phase 2 API).

    Downstream tickets call this at their own module import time:

        # faults/filters/bbheader_sync.py  (owned by #123)
        from faults.factory import register_transform
        register_transform(
            "BBHEADER_SYNC_FAULT", BBHeaderSyncFaultTransform
        )

    Semantics: re-registering the *same* builder object for a type is an
    idempotent no-op; a *different* builder for an already-registered
    type raises ``ValueError`` unless ``allow_replace=True`` (this guards
    only downstream-vs-downstream conflicts — registering over one of
    #121's ``_SKELETON_BUILDERS`` placeholders is always free); an unknown
    fault type (not in ``KNOWN_FAULT_TYPES``) raises ``ValueError`` so
    typo'd registrations fail loudly.  Importing this module (or any
    module that resolves transforms) establishes the #121 skeleton wiring;
    importing ``register_transform`` from here guarantees that ordering.
    """
    if fault_type not in KNOWN_FAULT_TYPES:
        raise ValueError(
            f"register_transform: fault_type {fault_type!r} is not in the "
            f"registry {sorted(KNOWN_FAULT_TYPES)} — unknown registrations "
            "are rejected (typo guard)"
        )
    existing = _EXTRA_BUILDERS.get(fault_type)
    if existing is builder:
        return  # idempotent re-registration
    if existing is not None and not allow_replace:
        raise ValueError(
            f"register_transform: fault_type {fault_type!r} already has a "
            f"registered builder ({existing!r}); pass allow_replace=True to "
            "replace it (Phase 2 self-registration contract, ruling §10-4)"
        )
    _EXTRA_BUILDERS[fault_type] = builder


def override_builder_for(fault_type: str) -> TransformBuilder | None:
    """The registered builder override for ``fault_type``, or ``None``.

    Resolution order: downstream registrations (``_EXTRA_BUILDERS``),
    then the #121 skeletons (``_SKELETON_BUILDERS``).
    """
    override = _EXTRA_BUILDERS.get(fault_type)
    if override is not None:
        return override
    return _SKELETON_BUILDERS.get(fault_type)


def transform_builder_for(
    fault_type: str,
) -> Callable[[FaultDefinition], object]:
    """Public resolution wrapper: overrides first, then MVP built-ins.

    Delegates to :func:`faults.registry.transform_builder_for` (which
    consults :func:`override_builder_for` first).  Unknown types raise
    ``KeyError``.
    """
    from faults.registry import transform_builder_for as _resolve

    return _resolve(fault_type)


def create_fault_filter(
    plan: tuple[FaultDefinition, ...],
    config: GeneratorConfig,
    *,
    run_id: str | None = None,
) -> SemanticFaultFilter:
    """Build one run's semantic filter (the ``FaultFilter`` production impl).

    ``config`` participates in the signature for parity with the
    ``simulation.ts_runtime.FilterFactory`` protocol (per-fault parameters
    travel inside the plan; the config keys the packet geometry that the
    activation indexes address).
    """
    del config  # the fault semantics are config-independent (plan-carried)
    return SemanticFaultFilter(plan, run_id=run_id)


def build_semantic_filter_factory() -> FilterFactoryWithRunId:
    """Return the production filter factory for ``TSRuntime(filter_factory=…)``."""
    return create_fault_filter


# --- #121 skeleton wiring (orchestrator ruling §10-4) -----------------------------
#
# The four Phase 2 primitives resolve to the explicit-NotImplementedError
# skeletons so the registry → factory → semantic-filter plumbing is
# testable before the owning tickets land.  Downstream tickets (#124 /
# #123 / #126 / #128's TS wiring) replace these via
# ``register_transform(..., allow_replace=True)`` from their own modules.

from faults.filters import phase2_skeletons as _phase2_skeletons  # noqa: E402

_SKELETON_BUILDERS.update(
    {
        FAULT_TYPE_T2MI_PLP_MISMATCH: (
            _phase2_skeletons.T2miPlpMismatchSkeletonTransform
        ),
        FAULT_TYPE_BBHEADER_SYNC_FAULT: (
            _phase2_skeletons.BBHeaderSyncFaultSkeletonTransform
        ),
        FAULT_TYPE_BISS_KEY_MISMATCH: (
            _phase2_skeletons.BissKeyMismatchSkeletonTransform
        ),
        FAULT_TYPE_PMT_PID_DRIFT: (
            _phase2_skeletons.PmtPidDriftSkeletonTransform
        ),
    }
)
