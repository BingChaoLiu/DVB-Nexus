"""SPEC-205 Scenario Engine public face (SIM-F, ticket #45).

Freeze surface: ``simulation.scenario`` carries the scenario document
schema (:mod:`.schema`), the loader/session-binding face (:mod:`.loader`),
the learner action whitelist (:mod:`.actions`) and the scenario step
envelope emitter (:mod:`.events`). See the SPEC-205 module spec for the
requirement mapping (REQ-SIM-205-001~006).
"""

from simulation.scenario.actions import (
    LEARNER_ACTION_WHITELIST,
    LearnerAction,
    LearnerActionPolicy,
)
from simulation.scenario.events import (
    SCENARIO_PRODUCER_ID,
    SCENARIO_STEP_EVENT_TYPES,
    SCENARIO_STEP_PAYLOAD_KEY,
    ScenarioStepEmitter,
)
from simulation.scenario.loader import (
    ScenarioSession,
    apply_scenario_update,
    install_scenario_validation_gate,
    load_scenario_file,
    load_scenario_text,
    open_scenario_session,
    scenario_session_spec,
    scenario_validation_gate,
    uninstall_scenario_validation_gate,
    validate_scenario_fault_plan,
)
from simulation.scenario.schema import (
    SCENARIO_CRITERION_KINDS,
    SCENARIO_SCHEMA_VERSION,
    SIM_SCENARIO_ACTION_FORBIDDEN,
    SIM_SCENARIO_CRITERION_INVALID,
    SIM_SCENARIO_FAULT_PLAN_INVALID,
    SIM_SCENARIO_SCHEMA_INVALID,
    SIM_SCENARIO_SOLUTION_LEAK,
    SIM_SCENARIO_VERSION_CONFLICT,
    ScenarioActionForbiddenError,
    ScenarioCriterion,
    ScenarioCriterionInvalidError,
    ScenarioDocument,
    ScenarioError,
    ScenarioFaultPlanInvalidError,
    ScenarioHint,
    ScenarioSchemaInvalidError,
    ScenarioSolutionLeakError,
    ScenarioVersionConflictError,
    export_scenario_document,
    parse_scenario_document,
    reveal_hidden_solution,
    scan_executable_content,
    scenario_content_hash,
)

__all__ = [
    # codes (SPEC-205 §7)
    "SIM_SCENARIO_SCHEMA_INVALID",
    "SIM_SCENARIO_CRITERION_INVALID",
    "SIM_SCENARIO_FAULT_PLAN_INVALID",
    "SIM_SCENARIO_ACTION_FORBIDDEN",
    "SIM_SCENARIO_VERSION_CONFLICT",
    "SIM_SCENARIO_SOLUTION_LEAK",
    # schema face (§3/§4)
    "SCENARIO_CRITERION_KINDS",
    "SCENARIO_SCHEMA_VERSION",
    "ScenarioCriterion",
    "ScenarioDocument",
    "ScenarioError",
    "ScenarioHint",
    "ScenarioSchemaInvalidError",
    "ScenarioCriterionInvalidError",
    "ScenarioFaultPlanInvalidError",
    "ScenarioActionForbiddenError",
    "ScenarioVersionConflictError",
    "ScenarioSolutionLeakError",
    "parse_scenario_document",
    "scenario_content_hash",
    "scan_executable_content",
    "export_scenario_document",
    "reveal_hidden_solution",
    # loader face (§5)
    "ScenarioSession",
    "load_scenario_text",
    "load_scenario_file",
    "scenario_session_spec",
    "scenario_validation_gate",
    "install_scenario_validation_gate",
    "uninstall_scenario_validation_gate",
    "validate_scenario_fault_plan",
    "open_scenario_session",
    "apply_scenario_update",
    # action policy face (§4)
    "LEARNER_ACTION_WHITELIST",
    "LearnerAction",
    "LearnerActionPolicy",
    # step-event face (§5)
    "SCENARIO_PRODUCER_ID",
    "SCENARIO_STEP_EVENT_TYPES",
    "SCENARIO_STEP_PAYLOAD_KEY",
    "ScenarioStepEmitter",
]
