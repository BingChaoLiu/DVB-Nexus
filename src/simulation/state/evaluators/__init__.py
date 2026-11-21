"""L0 node-semantics evaluators (SPEC-620/621/622, ticket #161).

The three Phase 3 RF/SEC evaluators — :class:`LnbEvaluator` /
:class:`TunerEvaluator` / :class:`DiseqcSwitchEvaluator` — implement the
ADR-0012 decision-1 form: SPEC-202 ``NodeEvaluator`` protocol shapes
(interface zero-change), state semantics carried in JSON-safe
``NodeEvalResult.metrics``, evaluators fault-blind (the fault plan
transforms node configs before evaluation, #163's face).

Registration posture (ADR-0012 decision 1 / the #165 composition root):
pass :data:`DEFAULT_EVALUATORS` (or a superset) to
``simulation.state.evaluate.evaluate_topology``'s ``evaluators`` injection
mapping::

    from simulation.state.evaluators import DEFAULT_EVALUATORS
    result = evaluate_topology(graph, evaluators=DEFAULT_EVALUATORS)

The evaluators are deliberately NOT re-exported from the
``simulation.state`` package root — the frozen export surface
(``tests/unit/simulation/state/test_interface_freeze.py``) stays
untouched; consumers import from this subpackage directly.

Upstream-fact channel (orchestrator ruling A2): the walk threads each
feeding node's evaluation facts through ``PortState.metrics`` (the
additive ``PortState`` field).  The lnb publishes its signal facts plus
plumbing keys (``lnb_kind`` / LO plan / ``scr_protocol``) on its output
port; the switch merges its upstream's facts with its own register state;
the tuner consumes the merged mapping.  The runtime UB-conflict judgement
goes exclusively through ``simulation.state.unicable.ub_conflicts``
(ruling A13).  The config-key/vocabulary mirrors live in
:mod:`simulation.state.evaluators._vocab` and are three-way drift-locked
against the domain DTOs, the #160 validator and the #162 unicable module
from the tests layer (rulings A1/A14).
"""

from __future__ import annotations

from simulation.state.evaluators._vocab import (
    DISEQC_SWITCH_NODE_TYPE,
    LNB_NODE_TYPE,
    TUNER_NODE_TYPE,
)
from simulation.state.evaluators.diseqc_switch_evaluator import (
    DiseqcSwitchEvaluator,
)
from simulation.state.evaluators.lnb_evaluator import LnbEvaluator
from simulation.state.evaluators.tuner_evaluator import TunerEvaluator

__all__ = [
    "DEFAULT_EVALUATORS",
    "DiseqcSwitchEvaluator",
    "LnbEvaluator",
    "TunerEvaluator",
]

#: The default L0 evaluator registry for the Phase 3 node types — inject
#: into :func:`simulation.state.evaluate.evaluate_topology` (composition
#: roots may extend the mapping; unregistered node types stay idle).
DEFAULT_EVALUATORS: dict[str, object] = {
    LNB_NODE_TYPE: LnbEvaluator(),
    TUNER_NODE_TYPE: TunerEvaluator(),
    DISEQC_SWITCH_NODE_TYPE: DiseqcSwitchEvaluator(),
}
