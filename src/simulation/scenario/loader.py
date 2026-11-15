"""SPEC-205 §5 — scenario loading, pinning and session binding (SIM-F #45).

加载即新建（SPEC-205 §5）: loading a scenario creates a **new session**
(SPEC-200) and pins the scenario version + content hash (SHA-256); it
**never mutates a running session**. This module owns:

- :func:`load_scenario_text` / :func:`load_scenario_file` — text / file
  loading (file reads are the integration-tested IO face; the parse core
  is :func:`simulation.scenario.schema.parse_scenario_document`, pure),
- :func:`scenario_session_spec` — the SPEC-200 :class:`SimulationSessionSpec`
  built from the document with a fresh uuid4 session id per call
  (ADR-0006 item 3; REQ-SIM-205-002 重跑 = 可区分记录),
- :func:`validate_scenario_fault_plan` — the scenario-level **VALIDATING
  gate**: fault-plan content validation via the canonical
  :mod:`faults.registry` rule set (SPEC-204 §11 details 透传,
  ``SIM_SCENARIO_FAULT_PLAN_INVALID`` carrying ``SIM_FAULT_*`` codes —
  ADR-0007 item 5 makes ``expected_observations`` mandatory here). This is
  the acceptance core of ticket #45: 缺 expected_observations 的 scenario
  在 SPEC-200 VALIDATING 态被拒绝（``VALIDATING -> FAILED``，#12 裁决边）.
- :func:`install_scenario_validation_gate` — idempotent registration of
  the gate into :data:`simulation.runtime.VALIDATION_GATES` (an appended,
  default-empty face on the #41 runtime; see that module's appended block),
- :func:`open_scenario_session` — the orchestration: parse (schema gate) →
  new session (CREATED) → ``validate_session`` (VALIDATING: topology +
  scenario gate → READY/FAILED) → :class:`ScenarioSession` binding,
- :func:`apply_scenario_update` — the ``SIM_SCENARIO_VERSION_CONFLICT``
  rejection: a modified scenario means a NEW session, never an in-place
  mutation of a live one.

Purity note: everything except ``load_scenario_file`` is filesystem-free;
unit tests cover the pure faces, ``tests/integration/simulation/`` covers
the file face (SPEC-505 layer discipline).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

from faults.registry import (
    SIM_FAULT_ACTIVATION_OUT_OF_RANGE,
    SIM_FAULT_EXPECTED_OBS_MISSING,
    SIM_FAULT_PARAM_INVALID,
    SIM_FAULT_TARGET_INVALID,
    SIM_FAULT_UNKNOWN_TYPE,
    validate_fault_definition,
)
from simulation.errors import SimulationIOError
from simulation.runtime import (
    SimulationRuntime,
    SimulationSessionSpec,
    SimulationSnapshot,
    VALIDATION_GATES,
)
from simulation.scenario.schema import (
    SIM_SCENARIO_FAULT_PLAN_INVALID,
    SIM_SCENARIO_SCHEMA_INVALID,
    SIM_SCENARIO_VERSION_CONFLICT,
    ScenarioDocument,
    ScenarioFaultPlanInvalidError,
    ScenarioSchemaInvalidError,
    ScenarioVersionConflictError,
    parse_scenario_document,
)

__all__ = [
    "SCENARIO_GATE_DETAIL_PREFIX",
    "ScenarioSession",
    "apply_scenario_update",
    "install_scenario_validation_gate",
    "load_scenario_file",
    "load_scenario_text",
    "open_scenario_session",
    "scenario_session_spec",
    "scenario_validation_gate",
    "validate_scenario_fault_plan",
    "uninstall_scenario_validation_gate",
]

#: Prefix every scenario-gate violation carries, so a mixed
#: :class:`simulation.runtime.ValidationReport` stays code-addressable
#: (topology violations keep their ``SIM_TOPO_*`` codes).
SCENARIO_GATE_DETAIL_PREFIX = SIM_SCENARIO_FAULT_PLAN_INVALID

# session_id -> document for sessions opened through this module. The
# VALIDATING gate is a module-level callable receiving the session spec, so
# the binding records the document here before ``create_session`` runs.
_BOUND_DOCUMENTS: dict[str, ScenarioDocument] = {}
_GATE_INSTALLED = False


# --- loading -------------------------------------------------------------------


def load_scenario_text(text: str) -> ScenarioDocument:
    """Parse a scenario document from JSON text (path-addressed errors)."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        raise ScenarioSchemaInvalidError(
            "scenario document rejected: the text is not valid JSON "
            f"(line {error.lineno} column {error.colno})",
            details=("$: invalid JSON syntax",),
        ) from error
    return parse_scenario_document(data)


def load_scenario_file(path: str | Path) -> ScenarioDocument:
    """Load a scenario document from a UTF-8 JSON file.

    Read failures surface as :class:`simulation.errors.SimulationIOError`
    (``SIM_IO_ERROR``); malformed content as the path-addressed scenario
    schema errors. Encoding is explicit UTF-8 (ADR-0004 Windows-first).
    """
    location = Path(path)
    try:
        text = location.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise SimulationIOError(
            f"scenario document could not be read from {location.name!r}: "
            f"{type(error).__name__}"
        ) from error
    return load_scenario_text(text)


# --- session binding ------------------------------------------------------------


def scenario_session_spec(document: ScenarioDocument) -> SimulationSessionSpec:
    """Build the SPEC-200 session spec for a fresh scenario session.

    A **new** uuid4 ``session_id`` per call (SPEC-205 §5 加载即新建; 重跑
    产生可区分的 run/session 记录), topology and clock riding the existing
    #40/#39 contracts, deterministic flag from the declared mode.
    """
    import uuid

    return SimulationSessionSpec(
        session_id=str(uuid.uuid4()),
        topology=document.topology,
        seed=document.seed,
        deterministic=document.deterministic,
        clock_config=document.clock_config,
    )


def validate_scenario_fault_plan(
    document: ScenarioDocument,
) -> tuple[str, ...]:
    """Scenario-level VALIDATING-gate violations (path-addressed, pure).

    Runs the canonical SPEC-204 §11 rule set
    (:func:`faults.registry.validate_fault_definition`) over every declared
    fault — parameters, activation, target shape and the mandatory
    ``expected_observations`` (``SIM_FAULT_EXPECTED_OBS_MISSING``). The
    plan-level budget checks that need prepared knowledge
    (``actual_pmt_pid`` / ``expected_packet_count``) stay with SPEC-203
    prepare binding (#43). Empty tuple = the gate passes.
    """
    # Detail code -> the JSON path segment the violation addresses, so the
    # gate output stays path-addressed like the schema face (SPEC-205 §4).
    _FIELD_BY_CODE = {
        SIM_FAULT_EXPECTED_OBS_MISSING: "expected_observations",
        SIM_FAULT_PARAM_INVALID: "parameters",
        SIM_FAULT_TARGET_INVALID: "target_id",
        SIM_FAULT_ACTIVATION_OUT_OF_RANGE: "activation",
        SIM_FAULT_UNKNOWN_TYPE: "fault_type",
    }
    violations: list[str] = []
    for index, fault in enumerate(document.fault_plan):
        details = validate_fault_definition(fault)
        for detail in details:
            field_name = next(
                (
                    segment
                    for code, segment in _FIELD_BY_CODE.items()
                    if detail.startswith(code)
                ),
                "fault",
            )
            violations.append(
                f"{SCENARIO_GATE_DETAIL_PREFIX}: "
                f"fault_plan[{index}].{field_name}: {detail} "
                "(SPEC-205 §7: fault plan/expected_observations 校验失败，"
                "SPEC-204 错误码透传)"
            )
    return tuple(violations)


def scenario_validation_gate(spec: SimulationSessionSpec) -> tuple[str, ...]:
    """The :data:`simulation.runtime.VALIDATION_GATES` callable.

    Returns the scenario fault-plan violations for scenario-bound sessions;
    sessions not opened through this module pass untouched (empty tuple).
    """
    document = _BOUND_DOCUMENTS.get(spec.session_id)
    if document is None:
        return ()
    return validate_scenario_fault_plan(document)


def install_scenario_validation_gate() -> None:
    """Register the scenario gate into the #41 runtime (idempotent).

    The gate is default-empty on :data:`VALIDATION_GATES` — installing it
    changes nothing for non-scenario sessions and preserves every #41
    behavior for existing callers (appended-face discipline, ticket #45).
    """
    global _GATE_INSTALLED
    if not _GATE_INSTALLED:
        VALIDATION_GATES.append(scenario_validation_gate)
        _GATE_INSTALLED = True


def uninstall_scenario_validation_gate() -> None:
    """Remove the gate again (test/teardown convenience; idempotent)."""
    global _GATE_INSTALLED
    if scenario_validation_gate in VALIDATION_GATES:
        VALIDATION_GATES.remove(scenario_validation_gate)
    _GATE_INSTALLED = False


@dataclass(frozen=True)
class ScenarioSession:
    """A scenario bound to its newly created session (SPEC-205 §5).

    ``content_hash`` is the pinned SHA-256 of the scenario version — the
    identity every run record of this session carries. ``snapshot`` is the
    post-validation pull-API view (lifecycle READY on success).
    """

    document: ScenarioDocument
    session_id: str
    content_hash: str
    snapshot: SimulationSnapshot


async def open_scenario_session(
    runtime: SimulationRuntime,
    source: str | Path | Mapping,
) -> ScenarioSession:
    """Load a scenario and open a fresh session for it.

    Orchestration (SPEC-205 §4/§5):

    1. load + schema gate (path-addressed ``SIM_SCENARIO_SCHEMA_INVALID`` /
       ``SIM_SCENARIO_CRITERION_INVALID`` / executable-content rejection)
       — nothing exists yet, nothing was mutated;
    2. install the scenario VALIDATING gate (idempotent) and record the
       document under the new session id;
    3. ``runtime.create_session`` (CREATED, new uuid4 identity);
    4. ``runtime.validate_session`` — the session is now in **VALIDATING**;
       the #41 topology gate and the scenario fault-plan gate both run
       there. Any violation drives ``VALIDATING -> FAILED`` and surfaces as
       ``SIM_VALIDATION_FAILED`` carrying the mixed path-addressed report
       (the acceptance core: 缺 expected_observations 在 VALIDATING 被拒绝).

    ``source`` is JSON text (``str``), a file path (``Path`` — loaded with
    :func:`load_scenario_file`) or an already-parsed mapping (not mutated).
    """
    install_scenario_validation_gate()
    if isinstance(source, Path):
        document = load_scenario_file(source)
    elif isinstance(source, str):
        document = load_scenario_text(source)
    else:
        document = parse_scenario_document(source)
    spec = scenario_session_spec(document)
    _BOUND_DOCUMENTS[spec.session_id] = document
    await runtime.create_session(spec)
    # CREATED -> VALIDATING -> READY/FAILED: both the #41 topology gate and
    # the scenario fault-plan gate run inside the VALIDATING phase.
    await runtime.validate_session(spec.session_id)
    snapshot = await runtime.get_snapshot(spec.session_id)
    return ScenarioSession(
        document=document,
        session_id=spec.session_id,
        content_hash=document.content_hash,
        snapshot=snapshot,
    )


def apply_scenario_update(
    binding: ScenarioSession, new_document: ScenarioDocument
) -> None:
    """Refuse to apply a new scenario version to a live session.

    SPEC-205 §5/§7: 场景修订（内容哈希变化）= 新场景版本，对运行中
    session 应用新版本被拒绝（``SIM_SCENARIO_VERSION_CONFLICT``）——演进
    的唯一方式是加载新 session（版本钉扎）.
    """
    raise ScenarioVersionConflictError(
        "scenario version conflict: a modified scenario (different content "
        "hash) is a new scenario version and must be loaded into a NEW "
        "session; running sessions stay pinned to their loaded version "
        "(SPEC-205 §5 版本钉扎)"
    )
