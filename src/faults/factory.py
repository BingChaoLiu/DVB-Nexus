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
"""

from __future__ import annotations

from typing import Callable

from ts.generator.config import GeneratorConfig

from faults.definition import FaultDefinition
from faults.filters.semantic import SemanticFaultFilter

__all__ = [
    "FilterFactoryWithRunId",
    "build_semantic_filter_factory",
    "create_fault_filter",
]

#: Production factory shape: plan + config + optional run binding.
FilterFactoryWithRunId = Callable[
    [tuple[FaultDefinition, ...], GeneratorConfig], SemanticFaultFilter
]


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
