"""SPEC-205 §3/§4/§7 — scenario document schema (SIM-F, ticket #45).

The scenario document is **content, not code** (SPEC-205 §1): a versioned
declarative JSON document (YAML is an editing-time convenience and is
normalized to JSON *before* this module sees it — nothing here parses
YAML). This module owns the pure schema face:

- wire-format parsing with path-addressed rejection (``$``-rooted JSON
  paths — SPEC-205 §4 "错误 path-addressed"),
- the mandatory-field matrix of SPEC-205 §3 (``scenario_id`` uuid4 opaque
  per ADR-0006 item 3, ``initial_topology`` per SPEC-003 §2.1,
  ``simulation_config`` per SPEC-201 §4, ``fault_plan`` as SPEC-204
  ``FaultDefinition`` entries, ``objectives`` / ``hints`` / ``pass_criteria``
  / optional ``hidden_reference_solution``),
- criterion-reference integrity at load time (SPEC-205 §4: the kind must be
  in the SPEC-206 §7 closed enum; a ``fault_inactive`` criterion declaring a
  ``fault_id`` must reference a fault of *this* scenario's plan),
- the executable-content static scan (SPEC-205 §4/§8: scenario packages
  never carry scripts, macros or dynamic expressions),
- the export / reveal faces for the hidden reference solution (SPEC-205 §4:
  no API, log or export path may surface it before the reveal policy
  grants).

Layering (boundary discipline, ticket #45):

- The wire vocabulary of ``initial_topology`` is the camelCase form of the
  canonical example (issue #12 authority); parsing maps it 1:1 onto the
  SPEC-202 graph contract (:mod:`simulation.state.graph` — the local
  mirror of ``domain.topology``; the direct import edge
  ``simulation -> domain.topology`` is forbidden, ADR-0005 D4-4).
- ``fault_plan`` entries are built as the canonical
  :class:`faults.definition.FaultDefinition` objects (ADR-0007 item 5
  owner); **content** validation of the plan (parameters / activation /
  target / ``expected_observations`` presence) is the SPEC-204 §11 rule
  set and is enforced at the SPEC-200 VALIDATING gate
  (:mod:`simulation.scenario.loader`), not at parse time — parse checks
  structure, types and the MVP fault-type vocabulary only (SPEC-205 §8
  lists ``未知 fault_type`` among the schema negatives).
- Every error is a :class:`ScenarioError` carrying its SPEC-205 §7 code
  plus ``details`` — path-addressed, value-free messages (errors are a
  read path of the document, so they never echo field values; REQ-SIM-205-
  003).

Purity: no I/O, no wall clock, no randomness — the schema face is
importable and testable without the filesystem (file loading lives in
:mod:`simulation.scenario.loader`).
"""

from __future__ import annotations

import copy
import hashlib
import re
import uuid
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping

from faults.definition import FaultActivation, FaultDefinition
from faults.registry import MVP_FAULT_TYPES
from simulation.clock import SimulationClockConfig
from simulation.errors import SimulationError
from simulation.state.graph import (
    Connection,
    NodeConfig,
    PortSpec,
    TopologyGraph,
)
from ts.canonical_json import canonical_json

__all__ = [
    "SCENARIO_CRITERION_KINDS",
    "SCENARIO_SCHEMA_VERSION",
    "SIM_SCENARIO_ACTION_FORBIDDEN",
    "SIM_SCENARIO_CRITERION_INVALID",
    "SIM_SCENARIO_FAULT_PLAN_INVALID",
    "SIM_SCENARIO_SCHEMA_INVALID",
    "SIM_SCENARIO_SOLUTION_LEAK",
    "SIM_SCENARIO_VERSION_CONFLICT",
    "ScenarioActionForbiddenError",
    "ScenarioCriterion",
    "ScenarioCriterionInvalidError",
    "ScenarioError",
    "ScenarioFaultPlanInvalidError",
    "ScenarioHint",
    "ScenarioDocument",
    "ScenarioSchemaInvalidError",
    "ScenarioSolutionLeakError",
    "ScenarioVersionConflictError",
    "export_scenario_document",
    "parse_scenario_document",
    "reveal_hidden_solution",
    "scan_executable_content",
    "scenario_content_hash",
]

# --- SPEC-205 §7 error codes ---------------------------------------------------

#: 场景文档不过 schema → 拒绝，附 path（SPEC-205 §7 row 1）.
SIM_SCENARIO_SCHEMA_INVALID = "SIM_SCENARIO_SCHEMA_INVALID"

#: pass_criteria 引用完整性失败 → 拒绝加载，path-addressed（§7 row 2）.
SIM_SCENARIO_CRITERION_INVALID = "SIM_SCENARIO_CRITERION_INVALID"

#: fault plan/expected_observations 校验失败 → 拒绝（§7 row 3；SPEC-204
#: 错误码透传，挂 SPEC-200 VALIDATING 门，见 loader 模块）.
SIM_SCENARIO_FAULT_PLAN_INVALID = "SIM_SCENARIO_FAULT_PLAN_INVALID"

#: 学习者动作不在白名单 → 拒绝（§7 row 4）.
SIM_SCENARIO_ACTION_FORBIDDEN = "SIM_SCENARIO_ACTION_FORBIDDEN"

#: 对运行中 session 应用新版本 → 拒绝，要求新 session（§7 row 5）.
SIM_SCENARIO_VERSION_CONFLICT = "SIM_SCENARIO_VERSION_CONFLICT"

#: 参考解暴露路径被触发 → 拒绝并审计（§7 row 6）.
SIM_SCENARIO_SOLUTION_LEAK = "SIM_SCENARIO_SOLUTION_LEAK"

#: The scenario format version this spec corresponds to (SPEC-205 §3; the
#: wire accepts the number ``1`` or the string ``"1"`` — both normalize to
#: the string form, SPEC-301 §8 additive-compat vocabulary).
SCENARIO_SCHEMA_VERSION = "1"

#: MVP 判据 kind 闭集（SPEC-206 §7 冻结；新增 kind 走 spec 修订）.
SCENARIO_CRITERION_KINDS = frozenset(
    {
        "fault_inactive",
        "psi_pat_valid",
        "psi_pmt_valid",
        "pat_pmt_mapping_valid",
        "cc_continuous",
        "no_unexpected_cc_error",
    }
)

_ACTIVATION_KINDS = frozenset({"packet_index", "session_start"})
_SIMULATION_MODES = frozenset({"deterministic", "realtime"})

#: BISS Mode 1 session word wire shape (SPEC-610 §5: 12 hex = 48 bit).
_BISS_SW_WIRE_PATTERN = re.compile(r"^[0-9A-Fa-f]{12}$")

# Static executable-content markers (SPEC-205 §4: 导入/导出内容不得含可执行
# 体——脚本、宏、动态表达式). Conservative denylist over string keys/values,
# matched case-insensitively as substrings.
_EXECUTABLE_MARKERS: tuple[str, ...] = (
    "<script",
    "javascript:",
    "vbscript:",
    "eval(",
    "exec(",
    "compile(",
    "__import__",
    "importlib",
    "subprocess",
    "os.system",
    "popen(",
    "function(",
    "${",
    "{{",
    "`",
    "#!",
    "onload=",
    "onerror=",
    "document.cookie",
    "file://",
)


# --- error family --------------------------------------------------------------


class ScenarioError(SimulationError):
    """Base class for SPEC-205 §7 errors; carries path-addressed details.

    ``details`` entries are ``$``-rooted paths plus a rule description and
    **never** contain document field values (errors are a read path;
    REQ-SIM-205-003).
    """

    details: tuple[str, ...] = ()

    def __init__(self, message: str, details: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.details = details


class ScenarioSchemaInvalidError(ScenarioError):
    """``SIM_SCENARIO_SCHEMA_INVALID``: 场景文档不过 schema（附 path）."""

    code = SIM_SCENARIO_SCHEMA_INVALID


class ScenarioCriterionInvalidError(ScenarioError):
    """``SIM_SCENARIO_CRITERION_INVALID``: 判据引用完整性失败（附 path）."""

    code = SIM_SCENARIO_CRITERION_INVALID


class ScenarioFaultPlanInvalidError(ScenarioError):
    """``SIM_SCENARIO_FAULT_PLAN_INVALID``: fault plan 校验失败（透传）."""

    code = SIM_SCENARIO_FAULT_PLAN_INVALID


class ScenarioActionForbiddenError(ScenarioError):
    """``SIM_SCENARIO_ACTION_FORBIDDEN``: 学习者动作不在白名单."""

    code = SIM_SCENARIO_ACTION_FORBIDDEN


class ScenarioVersionConflictError(ScenarioError):
    """``SIM_SCENARIO_VERSION_CONFLICT``: 对运行中 session 应用新版本."""

    code = SIM_SCENARIO_VERSION_CONFLICT


class ScenarioSolutionLeakError(ScenarioError):
    """``SIM_SCENARIO_SOLUTION_LEAK``: 参考解暴露路径被触发（拒绝并审计）."""

    code = SIM_SCENARIO_SOLUTION_LEAK


# --- document model ------------------------------------------------------------


@dataclass(frozen=True)
class BissMode1Config:
    """The scenario document's optional ``biss`` section (SPEC-610 §5).

    Construction-side BISS Mode 1 key declaration (camelCase wire
    document; the biss keys themselves follow the SPEC-610 §5 names):
    ``mode: "1" / session_word: string(12 hex) / pid_scope: [int] /
    ca_pid: 0x1FFF``.  ``ca_pid`` is constant-semantics (BISS carries no
    ECM, Tech 3292) and defaults to 8191 when the wire key is absent.

    Mode E sections (``mode: "E"`` — encrypted_sw / injected_id) are the
    SPEC-611 wire face and are explicitly rejected here until #127 lands
    their parse (additive extension point, never a silent pass).

    Key discipline: the session word lives in the frozen config only —
    error details are value-free (REQ-SIM-205-003) and the wire mapping
    round-trips verbatim through ``raw``.
    """

    mode: str
    session_word: str
    pid_scope: tuple[int, ...]
    ca_pid: int = 8191  # 0x1FFF, Tech 3292 constant semantics


@dataclass(frozen=True)
class ScenarioHint:
    """One hint (SPEC-205 §6): ID / trigger / level / content / linked
    requirement ids / optional standard-clause reference.

    引用纪律：``standard_ref`` 由场景作者声明，引擎原样承载——禁止编造
    ETSI/ITU 条款号是内容纪律（SPEC-205 §6），无法核实的引用不得写入，
    schema 层不做真伪判定。
    """

    hint_id: str
    trigger: str
    level: str
    content: str
    requirement_ids: tuple[str, ...] = ()
    standard_ref: str | None = None


@dataclass(frozen=True)
class ScenarioCriterion:
    """One pass-criterion declaration (SPEC-205 §3; SPEC-206 consumes).

    ``fault_id`` is only meaningful for ``fault_inactive`` (SPEC-206 §7:
    the criterion references a FaultDefinition of this scenario's plan);
    load-time integrity is enforced by :func:`parse_scenario_document`.
    """

    criterion_id: str
    kind: str
    mandatory: bool
    fault_id: str | None = None


@dataclass(frozen=True)
class ScenarioDocument:
    """The loaded scenario document (SPEC-205 §3) — frozen content.

    Fields are normalized onto the existing simulation contracts: the
    topology rides the SPEC-202 :class:`TopologyGraph` mirror, the clock
    rides :class:`SimulationClockConfig` (SPEC-201) and the fault plan
    rides the canonical :class:`faults.definition.FaultDefinition`.

    ``raw`` is the normalized wire mapping (schema_version normalized to
    the string form); ``content_hash`` is the SHA-256 of its canonical
    JSON serialization — the version-pinning identity (SPEC-205 §5: 加载
    即钉扎 scenario 版本与内容哈希). Key order and ``1`` vs ``"1"`` do
    not change the hash; any content change does.
    """

    schema_version: str
    scenario_id: str
    version: str
    title: str
    difficulty: str
    required_engine_versions: Mapping[str, str]
    topology: TopologyGraph
    seed: int
    deterministic: bool
    clock_config: SimulationClockConfig
    fault_plan: tuple[FaultDefinition, ...]
    objectives: tuple[str, ...]
    hints: tuple[ScenarioHint, ...]
    pass_criteria: tuple[ScenarioCriterion, ...]
    hidden_reference_solution: str | None
    raw: Mapping[str, Any] = field(repr=False, compare=False)
    biss: "BissMode1Config | None" = None
    content_hash: str = ""

    def fault_ids(self) -> tuple[str, ...]:
        """The declared fault ids of this scenario's plan (plan order)."""
        return tuple(fault.fault_id for fault in self.fault_plan)


# --- helpers -------------------------------------------------------------------


def _is_str(value: object) -> bool:
    return isinstance(value, str)


def _is_int(value: object) -> bool:
    # bools are not ints for schema purposes
    return isinstance(value, int) and not isinstance(value, bool)


def _require_non_empty_str(
    container: Mapping[str, Any],
    key: str,
    path: str,
    errors: list[str],
    *,
    required: bool = True,
) -> str | None:
    if key not in container:
        if required:
            errors.append(f"{path}.{key}: required field is missing")
        return None
    value = container[key]
    if not _is_str(value) or not value:
        errors.append(
            f"{path}.{key}: must be a non-empty string, got type "
            f"{type(value).__name__}"
        )
        return None
    return value


def _require_uuid4(
    container: Mapping[str, Any], key: str, path: str, errors: list[str]
) -> str | None:
    value = _require_non_empty_str(container, key, path, errors)
    if value is None:
        return None
    try:
        parsed = uuid.UUID(value)
    except ValueError:
        errors.append(
            f"{path}.{key}: must be a uuid4 opaque identity "
            f"(ADR-0006 item 3), got a non-UUID string"
        )
        return None
    if parsed.version != 4:
        errors.append(
            f"{path}.{key}: must be a uuid4 opaque identity "
            f"(ADR-0006 item 3), got UUID version {parsed.version}"
        )
        return None
    return value


def _require_bool(
    container: Mapping[str, Any], key: str, path: str, errors: list[str]
) -> bool | None:
    if key not in container:
        errors.append(f"{path}.{key}: required field is missing")
        return None
    value = container[key]
    if not isinstance(value, bool):
        errors.append(
            f"{path}.{key}: must be a bool, got type "
            f"{type(value).__name__}"
        )
        return None
    return value


def _require_int_value(
    container: Mapping[str, Any],
    key: str,
    path: str,
    errors: list[str],
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int | None:
    if key not in container:
        errors.append(f"{path}.{key}: required field is missing")
        return None
    value = container[key]
    if not _is_int(value):
        errors.append(
            f"{path}.{key}: must be an int, got type "
            f"{type(value).__name__}"
        )
        return None
    if minimum is not None and value < minimum:
        errors.append(f"{path}.{key}: must be >= {minimum}, got shape violation")
    if maximum is not None and value > maximum:
        errors.append(
            f"{path}.{key}: must be <= {maximum}, got shape violation"
        )
    return value


def _require_mapping(
    container: Mapping[str, Any], key: str, path: str, errors: list[str]
) -> Mapping[str, Any] | None:
    if key not in container:
        errors.append(f"{path}.{key}: required field is missing")
        return None
    value = container[key]
    if not isinstance(value, Mapping):
        errors.append(
            f"{path}.{key}: must be a JSON object, got type "
            f"{type(value).__name__}"
        )
        return None
    return value


def _require_string_list(
    container: Mapping[str, Any],
    key: str,
    path: str,
    errors: list[str],
    *,
    required: bool = True,
    allow_empty: bool = True,
) -> tuple[str, ...] | None:
    if key not in container:
        if required:
            errors.append(f"{path}.{key}: required field is missing")
        return None
    value = container[key]
    if not isinstance(value, list):
        errors.append(
            f"{path}.{key}: must be a JSON array, got type "
            f"{type(value).__name__}"
        )
        return None
    if not allow_empty and not value:
        errors.append(f"{path}.{key}: must not be empty")
        return None
    for index, item in enumerate(value):
        if not _is_str(item) or not item:
            errors.append(
                f"{path}.{key}[{index}]: must be a non-empty string"
            )
    return None if errors else tuple(str(item) for item in value)


# --- topology wire mapping (camelCase per the canonical example) ---------------


def _parse_topology(
    raw_topology: Mapping[str, Any], errors: list[str]
) -> TopologyGraph | None:
    base = "$.initial_topology"
    topology_id = _require_non_empty_str(raw_topology, "topology_id", base, errors)
    revision = _require_int_value(
        raw_topology, "revision", base, errors, minimum=0
    )
    raw_nodes = raw_topology.get("nodes")
    nodes: list[NodeConfig] = []
    if not isinstance(raw_nodes, list) or not raw_nodes:
        errors.append(f"{base}.nodes: must be a non-empty JSON array")
    else:
        for node_index, raw_node in enumerate(raw_nodes):
            nodes.extend(
                _parse_node(raw_node, f"{base}.nodes[{node_index}]", errors)
            )
    raw_connections = raw_topology.get("connections")
    connections: list[Connection] = []
    if isinstance(raw_connections, list):
        for conn_index, raw_conn in enumerate(raw_connections):
            connections.extend(
                _parse_connection(
                    raw_conn, f"{base}.connections[{conn_index}]", errors
                )
            )
    elif raw_connections is not None:
        errors.append(
            f"{base}.connections: must be a JSON array, got type "
            f"{type(raw_connections).__name__}"
        )
    if errors or topology_id is None or revision is None:
        return None
    try:
        return TopologyGraph(
            topology_id=topology_id,
            revision=revision,
            nodes=nodes,
            connections=connections,
        )
    except (TypeError, ValueError) as error:
        errors.append(f"{base}: graph contract rejected the document: {error}")
        return None


def _parse_node(
    raw_node: Mapping[str, Any], path: str, errors: list[str]
) -> list[NodeConfig]:
    if not isinstance(raw_node, Mapping):
        errors.append(f"{path}: must be a JSON object")
        return []
    node_id = _require_non_empty_str(raw_node, "nodeId", path, errors)
    node_type = _require_non_empty_str(raw_node, "nodeType", path, errors)
    config = _require_mapping(raw_node, "config", path, errors)
    raw_ports = raw_node.get("ports")
    ports: list[PortSpec] = []
    if not isinstance(raw_ports, list) or not raw_ports:
        errors.append(f"{path}.ports: must be a non-empty JSON array")
    else:
        for port_index, raw_port in enumerate(raw_ports):
            if not isinstance(raw_port, Mapping):
                errors.append(f"{path}.ports[{port_index}]: must be a JSON object")
                continue
            ports.extend(
                _parse_port(raw_port, f"{path}.ports[{port_index}]", errors)
            )
    if node_id is None or node_type is None or config is None:
        return []
    try:
        return [
            NodeConfig(
                node_id=node_id,
                node_type=node_type,
                config=dict(config),
                ports=ports,
            )
        ]
    except (TypeError, ValueError) as error:
        errors.append(f"{path}: node contract rejected the document: {error}")
        return []


def _parse_port(
    raw_port: Mapping[str, Any], path: str, errors: list[str]
) -> list[PortSpec]:
    port_id = _require_non_empty_str(raw_port, "portId", path, errors)
    direction = _require_non_empty_str(raw_port, "direction", path, errors)
    plane = _require_non_empty_str(raw_port, "plane", path, errors)
    max_connections: int | None = None
    if "maxConnections" in raw_port and raw_port["maxConnections"] is not None:
        max_connections = _require_int_value(
            raw_port, "maxConnections", path, errors, minimum=1
        )
    if port_id is None or direction is None or plane is None:
        return []
    try:
        return [
            PortSpec(
                port_id=port_id,
                direction=direction,
                plane=plane,
                max_connections=max_connections,
            )
        ]
    except (TypeError, ValueError) as error:
        errors.append(f"{path}: port contract rejected the document: {error}")
        return []


def _parse_connection(
    raw_conn: Mapping[str, Any], path: str, errors: list[str]
) -> list[Connection]:
    if not isinstance(raw_conn, Mapping):
        errors.append(f"{path}: must be a JSON object")
        return []
    connection_id = _require_non_empty_str(raw_conn, "connectionId", path, errors)
    plane = _require_non_empty_str(raw_conn, "plane", path, errors)
    endpoint_pairs: list[tuple[str, str, str]] = []
    for endpoint_key, attr_prefix in (("from", "from"), ("to", "to")):
        endpoint = raw_conn.get(endpoint_key)
        if not isinstance(endpoint, Mapping):
            errors.append(f"{path}.{endpoint_key}: must be a JSON object")
            endpoint_pairs.append((attr_prefix, "", ""))
            continue
        node_id = _require_non_empty_str(
            endpoint, "nodeId", f"{path}.{endpoint_key}", errors
        )
        port_id = _require_non_empty_str(
            endpoint, "portId", f"{path}.{endpoint_key}", errors
        )
        endpoint_pairs.append(
            (attr_prefix, node_id or "", port_id or "")
        )
    if connection_id is None or plane is None:
        return []
    (_, from_node, from_port), (_, to_node, to_port) = endpoint_pairs
    if not from_node or not from_port or not to_node or not to_port:
        return []
    try:
        return [
            Connection(
                connection_id=connection_id,
                from_node=from_node,
                from_port=from_port,
                to_node=to_node,
                to_port=to_port,
                plane=plane,
            )
        ]
    except (TypeError, ValueError) as error:
        errors.append(
            f"{path}: connection contract rejected the document: {error}"
        )
        return []


# --- fault plan (structure only; content = VALIDATING gate) ---------------------


def _parse_fault_plan(
    raw_plan: Any, errors: list[str]
) -> tuple[FaultDefinition, ...]:
    base = "$.fault_plan"
    if not isinstance(raw_plan, list):
        errors.append(
            f"{base}: must be a JSON array, got type "
            f"{type(raw_plan).__name__}"
        )
        return ()
    faults: list[FaultDefinition] = []
    seen_ids: set[str] = set()
    for index, raw_fault in enumerate(raw_plan):
        path = f"{base}[{index}]"
        if not isinstance(raw_fault, Mapping):
            errors.append(f"{path}: must be a JSON object")
            continue
        fault_id = _require_uuid4(raw_fault, "fault_id", path, errors)
        fault_type = _require_non_empty_str(raw_fault, "fault_type", path, errors)
        target_id = _require_non_empty_str(raw_fault, "target_id", path, errors)
        parameters = raw_fault.get("parameters", {})
        if not isinstance(parameters, Mapping):
            errors.append(f"{path}.parameters: must be a JSON object")
            parameters = {}
        activation = _parse_activation(raw_fault.get("activation"), path, errors)
        expected: tuple[str, ...] = ()
        if "expected_observations" in raw_fault:
            parsed = _require_string_list(
                raw_fault, "expected_observations", path, errors
            )
            if parsed is not None:
                expected = parsed
        if fault_id is not None:
            if fault_id in seen_ids:
                errors.append(
                    f"{path}.fault_id: duplicate fault_id within the plan"
                )
            seen_ids.add(fault_id)
        if fault_type is not None and fault_type not in MVP_FAULT_TYPES:
            errors.append(
                f"{path}.fault_type: {fault_type!r}-shaped value is not in "
                "the MVP fault-type registry (SPEC-204 §6)"
            )
        if errors and any(detail.startswith(path) for detail in errors):
            continue
        faults.append(
            FaultDefinition(
                fault_id=fault_id or "",
                fault_type=fault_type or "",
                target_id=target_id or "",
                parameters=dict(parameters),
                activation=activation,
                expected_observations=expected,
            )
        )
    return tuple(faults)


def _parse_activation(
    raw_activation: Any, path: str, errors: list[str]
) -> FaultActivation:
    # MVP narrow (ADR-0007 item 3): packet_index + session_start only.
    sub = f"{path}.activation"
    if not isinstance(raw_activation, Mapping):
        errors.append(f"{sub}: must be a JSON object")
        return FaultActivation(kind="session_start", packet_index=None)
    kind = raw_activation.get("kind")
    if kind not in _ACTIVATION_KINDS:
        errors.append(
            f"{sub}.kind: must be one of {sorted(_ACTIVATION_KINDS)} "
            "(MVP activation narrow, ADR-0007 item 3)"
        )
        return FaultActivation(kind="session_start", packet_index=None)
    packet_index: int | None = None
    if kind == "packet_index":
        packet_index = _require_int_value(
            raw_activation, "packet_index", sub, errors, minimum=0
        )
    elif "packet_index" in raw_activation:
        errors.append(
            f"{sub}.packet_index: session_start activation carries no "
            "packet_index (ADR-0007 item 3)"
        )
    return FaultActivation(kind=str(kind), packet_index=packet_index)


# --- hints / criteria -----------------------------------------------------------


def _parse_hints(raw_hints: Any, errors: list[str]) -> tuple[ScenarioHint, ...]:
    base = "$.hints"
    if raw_hints is None:
        return ()
    if not isinstance(raw_hints, list):
        errors.append(
            f"{base}: must be a JSON array, got type "
            f"{type(raw_hints).__name__}"
        )
        return ()
    hints: list[ScenarioHint] = []
    seen_ids: set[str] = set()
    for index, raw_hint in enumerate(raw_hints):
        path = f"{base}[{index}]"
        if not isinstance(raw_hint, Mapping):
            errors.append(f"{path}: must be a JSON object")
            continue
        hint_id = _require_non_empty_str(raw_hint, "hint_id", path, errors)
        trigger = _require_non_empty_str(raw_hint, "trigger", path, errors)
        level = _require_non_empty_str(raw_hint, "level", path, errors)
        content = _require_non_empty_str(raw_hint, "content", path, errors)
        requirement_ids = _require_string_list(
            raw_hint, "requirement_ids", path, errors
        )
        standard_ref = raw_hint.get("standard_ref")
        if standard_ref is not None and (
            not _is_str(standard_ref) or not standard_ref
        ):
            errors.append(
                f"{path}.standard_ref: must be a non-empty string or null"
            )
        if hint_id is not None:
            if hint_id in seen_ids:
                errors.append(f"{path}.hint_id: duplicate hint_id")
            seen_ids.add(hint_id)
        if any(detail.startswith(path) for detail in errors):
            continue
        hints.append(
            ScenarioHint(
                hint_id=hint_id or "",
                trigger=trigger or "",
                level=level or "",
                content=content or "",
                requirement_ids=requirement_ids or (),
                standard_ref=standard_ref,
            )
        )
    return tuple(hints)


def _parse_pass_criteria(
    raw_criteria: Any,
    plan_fault_ids: frozenset[str],
    schema_errors: list[str],
    integrity_errors: list[str],
) -> tuple[ScenarioCriterion, ...]:
    base = "$.pass_criteria"
    if not isinstance(raw_criteria, list):
        schema_errors.append(
            f"{base}: must be a JSON array, got type "
            f"{type(raw_criteria).__name__}"
        )
        return ()
    criteria: list[ScenarioCriterion] = []
    seen_ids: set[str] = set()
    for index, raw_criterion in enumerate(raw_criteria):
        path = f"{base}[{index}]"
        if not isinstance(raw_criterion, Mapping):
            errors.append(f"{path}: must be a JSON object")
            continue
        criterion_id = _require_non_empty_str(
            raw_criterion, "criterion_id", path, schema_errors
        )
        kind = _require_non_empty_str(raw_criterion, "kind", path, schema_errors)
        mandatory = _require_bool(raw_criterion, "mandatory", path, schema_errors)
        fault_id = raw_criterion.get("fault_id")
        if fault_id is not None and (
            not _is_str(fault_id) or not fault_id
        ):
            schema_errors.append(
                f"{path}.fault_id: must be a non-empty string or absent"
            )
            fault_id = None
        if criterion_id is not None:
            if criterion_id in seen_ids:
                schema_errors.append(
                    f"{path}.criterion_id: duplicate criterion_id"
                )
            seen_ids.add(criterion_id)
        if kind is not None and kind not in SCENARIO_CRITERION_KINDS:
            integrity_errors.append(
                f"{path}.kind: {kind}-shaped value is not in the SPEC-206 "
                "§7 MVP criterion closed enum"
            )
        if (
            fault_id is not None
            and fault_id not in plan_fault_ids
        ):
            integrity_errors.append(
                f"{path}.fault_id: references a fault_id that is not in "
                "this scenario's fault_plan (SPEC-205 §4 引用完整性)"
            )
        if any(detail.startswith(path) for detail in schema_errors) or any(
            detail.startswith(path) for detail in integrity_errors
        ):
            continue
        criteria.append(
            ScenarioCriterion(
                criterion_id=criterion_id or "",
                kind=kind or "",
                mandatory=bool(mandatory),
                fault_id=fault_id,
            )
        )
    return tuple(criteria)


# --- executable-content scan (SPEC-205 §4 / §8) ---------------------------------


def scan_executable_content(value: Any) -> tuple[str, ...]:
    """Statically scan a JSON-shaped value for executable bodies.

    Returns path-addressed findings (``$``-rooted); empty tuple = clean.
    Pure: conservative substring denylist over every string key and value,
    case-insensitive (SPEC-205 §8 "静态扫描 + fuzz" 的静态半部).
    """
    findings: list[str] = []

    def walk(node: Any, path: str) -> None:
        if isinstance(node, Mapping):
            for key, item in node.items():
                key_path = f"{path}.{key}" if _is_str(key) else path
                if _is_str(key):
                    _check(key, key_path + " (key)")
                walk(item, key_path)
        elif isinstance(node, list):
            for index, item in enumerate(node):
                walk(item, f"{path}[{index}]")
        elif _is_str(node):
            _check(node, path)

    def _check(text: str, path: str) -> None:
        lowered = text.lower()
        for marker in _EXECUTABLE_MARKERS:
            if marker in lowered:
                findings.append(
                    f"{path}: executable-content marker detected "
                    "(SPEC-205 §4: scripts / macros / dynamic expressions "
                    "are forbidden in scenario content)"
                )
                return

    walk(value, "$")
    return tuple(findings)


# --- parse ----------------------------------------------------------------------


def scenario_content_hash(data: Mapping[str, Any]) -> str:
    """SHA-256 (hex) of the canonical JSON serialization of ``data``.

    Canonical form: the shared ``ts.canonical_json`` contract —
    ``sort_keys`` + compact separators + ASCII escaping (locale-independent
    byte determinism, unified with the plan-fingerprint and mutation-log
    serializations) — the version-pinning identity (SPEC-205 §5). Pure.
    """
    canonical = canonical_json(data)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def parse_scenario_document(data: Mapping[str, Any]) -> ScenarioDocument:
    """Validate and build the frozen :class:`ScenarioDocument`.

    Raises :class:`ScenarioSchemaInvalidError` (structure / types /
    vocabulary / executable content) or
    :class:`ScenarioCriterionInvalidError` (criterion-reference integrity)
    with path-addressed, value-free ``details``. Pure: the input mapping is
    never mutated and the built document holds no mutable alias to it
    (REQ-SIM-205-002 immutability).
    """
    if not isinstance(data, Mapping):
        raise ScenarioSchemaInvalidError(
            "scenario document rejected: top level must be a JSON object",
            details=("$: top level must be a JSON object",),
        )

    findings = scan_executable_content(data)
    if findings:
        raise ScenarioSchemaInvalidError(
            "scenario document rejected: executable content detected "
            f"({len(findings)} finding(s)); scenario packages never carry "
            "scripts, macros or dynamic expressions (SPEC-205 §4)",
            details=findings,
        )

    schema_errors: list[str] = []
    root = "$"

    schema_version_raw = data.get("schema_version")
    if schema_version_raw is None:
        schema_errors.append(f"{root}.schema_version: required field is missing")
    elif isinstance(schema_version_raw, bool) or not (
        schema_version_raw == 1 or schema_version_raw == SCENARIO_SCHEMA_VERSION
    ):
        schema_errors.append(
            f"{root}.schema_version: unsupported scenario format version "
            "(this spec corresponds to \"1\", SPEC-205 §3)"
        )

    scenario_id = _require_uuid4(data, "scenario_id", root, schema_errors)
    version = _require_non_empty_str(data, "version", root, schema_errors)
    title = _require_non_empty_str(data, "title", root, schema_errors)
    difficulty = _require_non_empty_str(data, "difficulty", root, schema_errors)

    required_engine_versions: dict[str, str] = {}
    raw_engines = data.get("required_engine_versions", {})
    if not isinstance(raw_engines, Mapping):
        schema_errors.append(
            f"{root}.required_engine_versions: must be a JSON object"
        )
    else:
        for key, value in raw_engines.items():
            if not _is_str(value) or not value:
                schema_errors.append(
                    f"{root}.required_engine_versions.{key}: must be a "
                    "non-empty string version constraint"
                )
            else:
                required_engine_versions[str(key)] = str(value)

    raw_topology = _require_mapping(
        data, "initial_topology", root, schema_errors
    )
    topology: TopologyGraph | None = None
    if raw_topology is not None:
        topology = _parse_topology(raw_topology, schema_errors)

    seed: int | None = None
    deterministic = False
    clock_config: SimulationClockConfig | None = None
    raw_sim_config = _require_mapping(
        data, "simulation_config", root, schema_errors
    )
    if raw_sim_config is not None:
        seed = _require_int_value(
            raw_sim_config, "seed", f"{root}.simulation_config", schema_errors,
            minimum=0,
            maximum=2**64 - 1,
        )
        mode = _require_non_empty_str(
            raw_sim_config, "mode", f"{root}.simulation_config", schema_errors
        )
        if mode is not None and mode not in _SIMULATION_MODES:
            schema_errors.append(
                f"{root}.simulation_config.mode: must be one of "
                f"{sorted(_SIMULATION_MODES)}"
            )
        else:
            deterministic = mode == "deterministic"
        raw_clock = _require_mapping(
            raw_sim_config, "clock", f"{root}.simulation_config", schema_errors
        )
        if raw_clock is not None:
            clock_config = _parse_clock(raw_clock, schema_errors)

    raw_fault_plan = data.get("fault_plan")
    if raw_fault_plan is None:
        schema_errors.append(f"{root}.fault_plan: required field is missing")
        fault_plan: tuple[FaultDefinition, ...] = ()
    else:
        fault_plan = _parse_fault_plan(raw_fault_plan, schema_errors)

    objectives = _require_string_list(
        data, "objectives", root, schema_errors, allow_empty=True
    )

    hints = _parse_hints(data.get("hints"), schema_errors)

    plan_fault_ids = frozenset(fault.fault_id for fault in fault_plan)
    criterion_integrity_errors: list[str] = []
    raw_criteria = data.get("pass_criteria")
    if raw_criteria is None:
        schema_errors.append(
            f"{root}.pass_criteria: required field is missing"
        )
        pass_criteria: tuple[ScenarioCriterion, ...] = ()
    else:
        pass_criteria = _parse_pass_criteria(
            raw_criteria, plan_fault_ids, schema_errors,
            criterion_integrity_errors,
        )

    biss_config = _parse_biss(data.get("biss"), schema_errors)

    hidden = data.get("hidden_reference_solution")
    if hidden is not None and (not _is_str(hidden) or not hidden):
        schema_errors.append(
            f"{root}.hidden_reference_solution: must be a non-empty string "
            "or absent"
        )
        hidden = None

    if criterion_integrity_errors:
        raise ScenarioCriterionInvalidError(
            "scenario document rejected: pass_criteria reference "
            f"integrity failed with {len(criterion_integrity_errors)} "
            "error(s) (SPEC-205 §4)",
            details=tuple(criterion_integrity_errors),
        )

    if schema_errors:
        raise ScenarioSchemaInvalidError(
            "scenario document rejected: schema validation failed with "
            f"{len(schema_errors)} path-addressed error(s) (SPEC-205 §4 "
            "schema 校验强制)",
            details=tuple(schema_errors),
        )

    # Normalized wire mapping (schema_version normalized to the string form)
    # — the pinning-hash source and the export round-trip base.
    normalized = copy.deepcopy(dict(data))
    normalized["schema_version"] = SCENARIO_SCHEMA_VERSION

    return ScenarioDocument(
        schema_version=SCENARIO_SCHEMA_VERSION,
        scenario_id=str(scenario_id),
        version=str(version),
        title=str(title),
        difficulty=str(difficulty),
        required_engine_versions=MappingProxyType(
            dict(required_engine_versions)
        ),
        topology=topology,  # type: ignore[arg-type]
        seed=int(seed),  # type: ignore[arg-type]
        deterministic=bool(deterministic),
        clock_config=clock_config,  # type: ignore[arg-type]
        fault_plan=fault_plan,
        objectives=objectives or (),
        hints=hints,
        pass_criteria=pass_criteria,
        hidden_reference_solution=hidden,
        biss=biss_config,
        raw=MappingProxyType(normalized),
        content_hash=scenario_content_hash(normalized),
    )


def _parse_biss(raw_biss: Any, errors: list[str]) -> BissMode1Config | None:
    """Parse the optional scenario ``biss`` section (SPEC-610 §5, #126).

    Value-free path-addressed errors (REQ-SIM-205-003): the session word
    never appears in the rejection details — key discipline extends to
    the error face (SPEC-610 §9).
    """
    base = "$.biss"
    if raw_biss is None:
        return None
    if not isinstance(raw_biss, Mapping):
        errors.append(f"{base}: must be a JSON object, got type "
                      f"{type(raw_biss).__name__}")
        return None
    allowed_keys = {"mode", "session_word", "pid_scope", "ca_pid"}
    unknown = sorted(set(raw_biss) - allowed_keys)
    if unknown:
        errors.append(
            f"{base}: unknown key(s) {unknown} — SPEC-610 §5 declares "
            "mode/session_word/pid_scope/ca_pid only (Mode E fields are "
            "the SPEC-611 extension face)"
        )
    mode = _require_non_empty_str(raw_biss, "mode", base, errors)
    if mode is not None and mode != "1":
        errors.append(
            f"{base}.mode: unsupported biss mode — this schema carries "
            'Mode 1 ("1"); Mode E ("E") is the SPEC-611 wire face'
        )
    session_word = raw_biss.get("session_word")
    if not _is_str(session_word) or not _BISS_SW_WIRE_PATTERN.match(
        session_word
    ):
        errors.append(
            f"{base}.session_word: must be a 12-hex-character string "
            "(48-bit session word, SPEC-610 §5)"
        )
        session_word = None
    raw_pid_scope = raw_biss.get("pid_scope")
    pid_scope: tuple[int, ...] | None = None
    if not isinstance(raw_pid_scope, list) or not raw_pid_scope:
        errors.append(
            f"{base}.pid_scope: must be a non-empty list of 13-bit PIDs"
        )
    else:
        scope_errors: list[str] = []
        parsed_pids: list[int] = []
        for position, pid in enumerate(raw_pid_scope):
            if not _is_int(pid) or not 0 <= pid <= 0x1FFF:
                scope_errors.append(
                    f"{base}.pid_scope[{position}]: must be a 13-bit int "
                    "(0..0x1FFF)"
                )
            else:
                parsed_pids.append(pid)
        if scope_errors:
            errors.extend(scope_errors)
        else:
            pid_scope = tuple(parsed_pids)
    ca_pid = 8191
    if "ca_pid" in raw_biss:
        parsed_ca_pid = _require_int_value(raw_biss, "ca_pid", base, errors)
        if parsed_ca_pid is not None and parsed_ca_pid != 8191:
            errors.append(
                f"{base}.ca_pid: constant-semantics field — BISS carries "
                "no ECM and the CA_PID is fixed at 0x1FFF (Tech 3292)"
            )
    if errors:
        return None
    return BissMode1Config(
        mode=str(mode),
        session_word=str(session_word),
        pid_scope=pid_scope,  # type: ignore[arg-type]
        ca_pid=ca_pid,
    )


def _parse_clock(raw_clock: Mapping[str, Any], errors: list[str]) -> SimulationClockConfig | None:
    base = "$.simulation_config.clock"
    mode = _require_non_empty_str(raw_clock, "mode", base, errors)
    start_time_ns = _require_int_value(
        raw_clock, "start_time_ns", base, errors, minimum=0
    )
    speed_num = _require_int_value(
        raw_clock, "speed_num", base, errors, minimum=1
    )
    speed_den = _require_int_value(
        raw_clock, "speed_den", base, errors, minimum=1
    )
    tick_quantum_ns: int = 1_000_000
    if "tick_quantum_ns" in raw_clock:
        parsed = _require_int_value(
            raw_clock, "tick_quantum_ns", base, errors, minimum=1
        )
        if parsed is not None:
            tick_quantum_ns = parsed
    if errors:
        return None
    try:
        return SimulationClockConfig(
            mode=mode,  # type: ignore[arg-type]
            start_time_ns=start_time_ns,  # type: ignore[arg-type]
            speed_num=speed_num,  # type: ignore[arg-type]
            speed_den=speed_den,  # type: ignore[arg-type]
            tick_quantum_ns=tick_quantum_ns,
        )
    except Exception as error:  # SimulationConfigError / TypeError
        errors.append(
            f"{base}: clock contract rejected the document ({error})"
        )
        return None


# --- export / reveal faces (REQ-SIM-205-003 / 006) ------------------------------


def export_scenario_document(
    document: ScenarioDocument, *, include_hidden_solution: bool = False
) -> dict[str, Any]:
    """Re-serialize the document for export (SPEC-205 §4 import/export face).

    The hidden reference solution is dropped unless the caller passes
    ``include_hidden_solution=True`` (the reveal-policy grant; SPEC-205 §4:
    reveal 政策外不得通过任何 API 泄露，含导出). The exported mapping is
    executable-content clean by construction (it was scanned at parse and
    the scan runs again below as a defense-in-depth guarantee).
    """
    exported = copy.deepcopy(dict(document.raw))
    if not include_hidden_solution:
        exported.pop("hidden_reference_solution", None)
    findings = scan_executable_content(exported)
    if findings:
        # Unreachable via the public faces (parse already scanned); kept as
        # the export-side guarantee (SPEC-205 §8).
        raise ScenarioSchemaInvalidError(
            "export refused: executable content detected in the document",
            details=findings,
        )
    return exported


def reveal_hidden_solution(
    document: ScenarioDocument, *, reveal_granted: bool
) -> str:
    """Return the hidden reference solution under an explicit reveal grant.

    Without the grant this is the ``SIM_SCENARIO_SOLUTION_LEAK`` rejection
    path (SPEC-205 §7 row 6): refuse AND audit — callers should record the
    refusal; this module raises with a value-free message so the refusal
    itself never carries the solution.
    """
    solution = document.hidden_reference_solution
    if not reveal_granted:
        raise ScenarioSolutionLeakError(
            "hidden reference solution reveal refused: the reveal policy "
            "has not granted access (SPEC-205 §4; the refusal is audited)"
        )
    if solution is None:
        raise ScenarioSolutionLeakError(
            "hidden reference solution reveal refused: this scenario "
            "declares no hidden reference solution"
        )
    return solution
