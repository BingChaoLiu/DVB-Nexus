"""Simulation Engine error hierarchy (SPEC-201 section 8 and successors).

Code ownership follows the module-owned convention used across the repo
(TS-CORE-INTEGRATION-CONTRACT section 7 归属约定): each spec's error codes
live with the module that owns the spec — here, the simulation package.
Every :class:`SimulationError` carries its SPEC table code on ``code`` and
renders it as the ``"<CODE>: <message>"`` message prefix, matching the
``ts.errors`` / ``adapters.*`` message style.

SPEC-201 section 8 codes (ticket #39):

- ``SIM_CLOCK_TIME_BACKWARDS``  advance target <= current virtual time.
- ``SIM_CLOCK_CONFIG_INVALID``  config out of range (negative start,
  non-positive quantum/speed) — rejected at construction.
- ``SIM_CLOCK_PAUSED``          advance requested while frozen.
- ``SIM_SCHEDULER_OVERLOAD``    work budget persistently exceeded
  (report-only: the scheduler surfaces diagnostics, never interrupts the
  session — SPEC-201 section 8 row 4).

SPEC-202 section 8 codes (ticket #40, appended — SPEC-202 §5/§8):

- ``SIM_TOPO_DUPLICATE_ID``       nodeId / portId / connectionId conflict.
- ``SIM_TOPO_ENDPOINT_MISSING``   connection references a nonexistent
  node/port.
- ``SIM_TOPO_DIRECTION_INVALID``  output->output, input->input (or any
  from-side without output capability / to-side without input capability).
- ``SIM_TOPO_MEDIA_INCOMPATIBLE`` plane mismatch on a link.
- ``SIM_TOPO_CARDINALITY``        maxConnections exceeded on a port.
- ``SIM_TOPO_SELF_LOOP``          from == to (same node, same port).
- ``SIM_TOPO_CYCLE``              topology contains a cycle (MVP rejects;
  a DAG is required for deterministic evaluation).
- ``SIM_EVAL_NODE_FAILED``        evaluator-internal exception — the node
  is isolated as error health and the report is surfaced; the whole-graph
  evaluation never crashes (report path in ``simulation.state.evaluate``).

SPEC-003 §Phase3 codes (ticket #160, appended — the ``SIM_TOPO_UB_*``
family; SPEC-623 §7/§8 layering: config-period violations only, the
baseline topology is always legal and misassignment is fault-plan
territory):

- ``SIM_TOPO_UB_SLOT_UNMATCHED``    tuner ``ub_slot`` hits no
  ``ub_assignments`` entry of any path-reachable SCR (rule 1).
- ``SIM_TOPO_UB_SLOT_CONFLICT``     two tuners claim the same UB slot in
  one SCR table — config-period static conflict (rule 2).
- ``SIM_TOPO_UB_SLOT_OUT_OF_RANGE`` ``ub_slot`` beyond the protocol bit
  width (EN 50494 > 7 / EN 50607 > 31) — table entries and tuner
  configs (rule 3).
- ``SIM_TOPO_UB_PROTOCOL_MIXED``    one tuner's reachable SCR set mixes
  EN 50494 and EN 50607 (rule 4; the two UB spaces are independent).

SPEC-204 §Phase3 codes (ticket #163, appended — the state-layer prepare
gate; ADR-0012 decision 3 routes RF/SEC faults through pre-evaluation pure
config transforms, so "layer routing reachable" = a transform is
registered for the fault type):

- ``SIM_FAULT_STATE_TRANSFORM_UNREGISTERED``  a fault declares a state
  layer (RF/SEC) but no pre-evaluation transform exists for its type in
  ``simulation.state.fault_transforms.STATE_TRANSFORM_BY_FAULT_TYPE``
  (e.g. a prematurely used candidate-pool primitive; the SIM_FAULT_* code
  family is SPEC-204 §11 — the constant lives here because the state
  transform face is simulation-owned, while the faults package keeps its
  own §11 codes).

SPEC-200 section 8 codes (ticket #41, appended — SPEC-200 §5/§6/§8):

- ``SIM_SESSION_NOT_FOUND``            unknown session_id (404 semantics).
- ``SIM_INVALID_LIFECYCLE_TRANSITION`` violates the section 5 exhaustive
  transition table; the error carries the current legal transition set.
- ``SIM_VALIDATION_FAILED``            session validation did not pass; the
  SPEC-202 path-addressed ``ValidationReport`` rides on ``report``.
- ``SIM_RESOURCE_LIMIT``               resource_limits exceeded (structure
  frozen here; numeric values await the OPEN-006 ruling, #16).
- ``SIM_ENGINE_ERROR``                 L0/L1/TS Core internal error with the
  root cause attached; the session migrates to FAILED.
- ``SIM_IO_ERROR``                     artifact/storage IO failure.
- ``SIM_CANCELLED``                    command cancelled/timed out.
- ``SIM_INTERNAL``                     unclassified internal error.

SPEC-203 section 8 codes (ticket #43, appended — SPEC-203 §8):

- ``SIM_TS_PLAN_INVALID``          fault plan validation failed (prepare).
- ``SIM_TS_CONFIG_INVALID``        TSGeneratorConfig illegal (prepare).
- ``SIM_TS_WORKER_UNAVAILABLE``    worker pool exhausted/crashed (retryable).
- ``SIM_TS_CANCELLED``             run cancelled (partial artifacts returned).
- ``SIM_TS_GENERATION_FAILED``     TS Core raised (root error code attached).
- ``SIM_TS_SINK_IO_ERROR``         ArtifactSink write failed (run failed).
"""

from __future__ import annotations

#: SPEC-201 section 8 — advance target <= current virtual time.
SIM_CLOCK_TIME_BACKWARDS = "SIM_CLOCK_TIME_BACKWARDS"

#: SPEC-201 section 8 — config out of range, rejected at construction.
SIM_CLOCK_CONFIG_INVALID = "SIM_CLOCK_CONFIG_INVALID"

#: SPEC-201 section 8 — advance requested while the clock is frozen.
SIM_CLOCK_PAUSED = "SIM_CLOCK_PAUSED"

#: SPEC-201 section 8 — work budget persistently exceeded (report-only).
SIM_SCHEDULER_OVERLOAD = "SIM_SCHEDULER_OVERLOAD"

# --- SPEC-202 section 8 (ticket #40) -----------------------------------------

#: SPEC-202 section 8 — nodeId / portId / connectionId conflict.
SIM_TOPO_DUPLICATE_ID = "SIM_TOPO_DUPLICATE_ID"

#: SPEC-202 section 8 — connection references a nonexistent node/port.
SIM_TOPO_ENDPOINT_MISSING = "SIM_TOPO_ENDPOINT_MISSING"

#: SPEC-202 section 8 — illegal direction pairing on a link.
SIM_TOPO_DIRECTION_INVALID = "SIM_TOPO_DIRECTION_INVALID"

#: SPEC-202 section 8 — plane mismatch on a link.
SIM_TOPO_MEDIA_INCOMPATIBLE = "SIM_TOPO_MEDIA_INCOMPATIBLE"

#: SPEC-202 section 8 — maxConnections exceeded on a port.
SIM_TOPO_CARDINALITY = "SIM_TOPO_CARDINALITY"

#: SPEC-202 section 8 — self loop (same node, same port).
SIM_TOPO_SELF_LOOP = "SIM_TOPO_SELF_LOOP"

#: SPEC-202 section 8 — topology contains a cycle (MVP rejects).
SIM_TOPO_CYCLE = "SIM_TOPO_CYCLE"

#: SPEC-202 section 8 — evaluator-internal exception; the node is isolated
#: as error health and the failure reported (never crashes the whole graph).
SIM_EVAL_NODE_FAILED = "SIM_EVAL_NODE_FAILED"

# --- SPEC-003 §Phase3 (ticket #160 — the SIM_TOPO_UB_* family) ------------------

#: SPEC-003 §Phase3 — tuner ``ub_slot`` hits no ``ub_assignments`` entry
#: of any path-reachable SCR (rule 1).
SIM_TOPO_UB_SLOT_UNMATCHED = "SIM_TOPO_UB_SLOT_UNMATCHED"

#: SPEC-003 §Phase3 — two tuners claim the same UB slot in one SCR table:
#: config-period static conflict (rule 2; SPEC-623 §6 ``ub_conflicts``).
SIM_TOPO_UB_SLOT_CONFLICT = "SIM_TOPO_UB_SLOT_CONFLICT"

#: SPEC-003 §Phase3 — ``ub_slot`` beyond the protocol bit width
#: (EN 50494 > 7 / EN 50607 > 31): checked on SCR table entries and tuner
#: configs (rule 3).
SIM_TOPO_UB_SLOT_OUT_OF_RANGE = "SIM_TOPO_UB_SLOT_OUT_OF_RANGE"

#: SPEC-003 §Phase3 — one tuner's reachable SCR set mixes EN 50494 and
#: EN 50607; the two UB spaces are independent (rule 4; SPEC-623 §7).
SIM_TOPO_UB_PROTOCOL_MIXED = "SIM_TOPO_UB_PROTOCOL_MIXED"

# --- SPEC-204 §Phase3 (ticket #163 — the state-layer prepare gate) ---------------

#: SPEC-204 §Phase3 — a fault routes to a state layer (RF/SEC) but no
#: pre-evaluation transform is registered for its type in
#: ``simulation.state.fault_transforms.STATE_TRANSFORM_BY_FAULT_TYPE``
#: (the "layer routing reachable" prepare clause; e.g. a prematurely used
#: candidate-pool primitive — LNB_SHORT_CIRCUIT / SWITCH_MISCONFIG /
#: THERMAL_FAULT stay unregistered in the first version).
SIM_FAULT_STATE_TRANSFORM_UNREGISTERED = "SIM_FAULT_STATE_TRANSFORM_UNREGISTERED"

# --- SPEC-200 section 8 (ticket #41) ------------------------------------------

#: SPEC-200 section 8 — session_id does not exist (404 semantics).
SIM_SESSION_NOT_FOUND = "SIM_SESSION_NOT_FOUND"

#: SPEC-200 section 8 — violates the section 5 exhaustive transition table.
SIM_INVALID_LIFECYCLE_TRANSITION = "SIM_INVALID_LIFECYCLE_TRANSITION"

#: SPEC-200 section 8 — session validation did not pass (report attached).
SIM_VALIDATION_FAILED = "SIM_VALIDATION_FAILED"

#: SPEC-200 section 8 — resource_limits exceeded (structure only; #16).
SIM_RESOURCE_LIMIT = "SIM_RESOURCE_LIMIT"

#: SPEC-200 section 8 — L0/L1/TS Core internal error; session -> FAILED.
SIM_ENGINE_ERROR = "SIM_ENGINE_ERROR"

#: SPEC-200 section 8 — artifact/storage IO failure (retryable flag set).
SIM_IO_ERROR = "SIM_IO_ERROR"

#: SPEC-200 section 8 — command cancelled or timed out (idempotent retry).
SIM_CANCELLED = "SIM_CANCELLED"

#: SPEC-200 section 8 — unclassified internal error (no stack leakage).
SIM_INTERNAL = "SIM_INTERNAL"

# --- SPEC-203 section 8 (ticket #43, appended — SPEC-203 §8) -------------------

#: SPEC-203 section 8 — fault plan validation failed (prepare stage).
SIM_TS_PLAN_INVALID = "SIM_TS_PLAN_INVALID"

#: SPEC-203 section 8 — TSGeneratorConfig illegal (prepare rejection).
SIM_TS_CONFIG_INVALID = "SIM_TS_CONFIG_INVALID"

#: SPEC-203 section 8 — worker pool exhausted/crashed (retryable).
SIM_TS_WORKER_UNAVAILABLE = "SIM_TS_WORKER_UNAVAILABLE"

#: SPEC-203 section 8 — run cancelled (returns partial artifacts).
SIM_TS_CANCELLED = "SIM_TS_CANCELLED"

#: SPEC-203 section 8 — TS Core raised during generation (root cause
#: error code attached as ``root_code``).
SIM_TS_GENERATION_FAILED = "SIM_TS_GENERATION_FAILED"

#: SPEC-203 section 8 — ArtifactSink write failed (run failed).
SIM_TS_SINK_IO_ERROR = "SIM_TS_SINK_IO_ERROR"

# --- SPEC-206 section 8 (ticket #56) -------------------------------------------

#: SPEC-206 §8 — pass criteria reference an unknown criterion kind
#: (outside the §7 MVP closed enum) or a malformed criterion declaration.
SIM_VERIF_CRITERION_INVALID = "SIM_VERIF_CRITERION_INVALID"

#: SPEC-206 §8 — mandatory evidence missing: per-criterion NOT_EVALUATED
#: → overall INCONCLUSIVE ("没证据" is its own conclusion, §4).
SIM_VERIF_EVIDENCE_MISSING = "SIM_VERIF_EVIDENCE_MISSING"

#: SPEC-206 §8 — candidate run cannot be attributed to the scenario context
#: (no journal events for the run in the targeted session) → 拒绝.
SIM_VERIF_RUN_MISMATCH = "SIM_VERIF_RUN_MISMATCH"

#: SPEC-206 §8 — candidate run IS the baseline → INCONCLUSIVE (§5 item 4).
SIM_VERIF_BASELINE_REUSED = "SIM_VERIF_BASELINE_REUSED"


class SimulationError(Exception):
    """Base class for every error owned by the simulation package.

    Subclasses own exactly one SPEC table row via the ``code`` class
    attribute (SPEC-201 section 8 for this ticket).
    """

    code: str = "SIMULATION_ERROR"

    def __init__(self, message: str) -> None:
        super().__init__(f"{self.code}: {message}")


class SimulationClockError(SimulationError):
    """Base class for simulation clock failures (SPEC-201 section 8)."""


class SimulationConfigError(SimulationClockError):
    """``SIM_CLOCK_CONFIG_INVALID``: config 越界（负 start、非正量子/倍速）."""

    code = SIM_CLOCK_CONFIG_INVALID


class SimulationTimeBackwardsError(SimulationClockError):
    """``SIM_CLOCK_TIME_BACKWARDS``: advance 目标 <= 当前虚拟时间."""

    code = SIM_CLOCK_TIME_BACKWARDS


class SimulationPausedError(SimulationClockError):
    """``SIM_CLOCK_PAUSED``: 冻结期间请求 advance（拒绝，编排方可见）."""

    code = SIM_CLOCK_PAUSED


class SimulationSchedulerError(SimulationError):
    """Base class for deterministic scheduler failures (SPEC-201 section 7)."""


class SimulationTopologyError(SimulationError):
    """Base class for state-engine topology failures (SPEC-202 section 8)."""


class TopologyCycleError(SimulationTopologyError):
    """``SIM_TOPO_CYCLE``: 拓扑含环，MVP 拒绝（确定性求值需要 DAG）."""

    code = SIM_TOPO_CYCLE


# --- SPEC-200 section 8 exceptions (ticket #41) -------------------------------


class SessionNotFoundError(SimulationError):
    """``SIM_SESSION_NOT_FOUND``: session_id 不存在（404 语义）."""

    code = SIM_SESSION_NOT_FOUND


class InvalidLifecycleTransitionError(SimulationError):
    """``SIM_INVALID_LIFECYCLE_TRANSITION``: 违反 SPEC-200 §5 迁移表.

    Carries the offending pair (``current`` / ``target``); the message lists
    the current legal transition set (SPEC-200 §8 拒绝，返回当前合法迁移集).
    """

    code = SIM_INVALID_LIFECYCLE_TRANSITION

    def __init__(
        self,
        current: object,
        target: object,
        allowed: object = None,
    ) -> None:
        allowed_values = (
            sorted(
                str(getattr(item, "value", item)) for item in allowed
            )
            if allowed
            else []
        )
        super().__init__(
            f"illegal lifecycle transition {current} -> {target}; allowed "
            f"targets from {current}: {allowed_values} (SPEC-200 section 5 "
            "exhaustive table)"
        )
        self.current = current
        self.target = target
        self.allowed = allowed


class SimulationValidationError(SimulationError):
    """``SIM_VALIDATION_FAILED``: 会话验证不通过（附 ValidationReport）."""

    code = SIM_VALIDATION_FAILED

    def __init__(self, message: str, report: object = None) -> None:
        super().__init__(message)
        self.report = report


class SimulationResourceLimitError(SimulationError):
    """``SIM_RESOURCE_LIMIT``: 超出 resource_limits（取值口径随 #16）."""

    code = SIM_RESOURCE_LIMIT


class SimulationEngineError(SimulationError):
    """``SIM_ENGINE_ERROR``: L0/L1/TS Core 内部错误（附根因，迁移 FAILED）."""

    code = SIM_ENGINE_ERROR


class SimulationIOError(SimulationError):
    """``SIM_IO_ERROR``: Artifact/存储 IO 失败（区分 retryable）."""

    code = SIM_IO_ERROR


class SimulationCancelledError(SimulationError):
    """``SIM_CANCELLED``: 命令被取消/超时（幂等可重试）."""

    code = SIM_CANCELLED


class SimulationInternalError(SimulationError):
    """``SIM_INTERNAL``: 未分类内部错误（记录诊断，不外泄堆栈细节）."""

    code = SIM_INTERNAL


# --- SPEC-203 section 8 exceptions (ticket #43, appended) -----------------------


class TSPlanInvalidError(SimulationError):
    """``SIM_TS_PLAN_INVALID``: fault plan 校验失败（prepare 阶段拒绝）.

    Carries ``details`` — the SPEC-204 per-element validation error list
    (SPEC-203 §8: "拒绝，附 SPEC-204 校验错误明细").
    """

    code = SIM_TS_PLAN_INVALID

    def __init__(self, message: str, details: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.details = details


class TSConfigInvalidError(SimulationError):
    """``SIM_TS_CONFIG_INVALID``: TSGeneratorConfig 非法（prepare 拒绝）."""

    code = SIM_TS_CONFIG_INVALID


class TSWorkerUnavailableError(SimulationError):
    """``SIM_TS_WORKER_UNAVAILABLE``: worker 池耗尽/崩溃（retryable 语义）."""

    code = SIM_TS_WORKER_UNAVAILABLE


class TSGenerationFailedError(SimulationError):
    """``SIM_TS_GENERATION_FAILED``: TS Core 抛错（透传根因错误码）."""

    code = SIM_TS_GENERATION_FAILED

    def __init__(self, message: str, root_code: str | None = None) -> None:
        super().__init__(message)
        self.root_code = root_code


class TSSinkIOError(SimulationError):
    """``SIM_TS_SINK_IO_ERROR``: ArtifactSink 写失败（Run failed）."""

    code = SIM_TS_SINK_IO_ERROR


# --- SPEC-206 section 8 exceptions (ticket #56) --------------------------------


class VerificationError(SimulationError):
    """Base class for the recovery-verification error family (SPEC-206 §8)."""


class VerificationCriterionInvalidError(VerificationError):
    """``SIM_VERIF_CRITERION_INVALID``: 判据 kind 不在 §7 闭集（拒绝判定）."""

    code = SIM_VERIF_CRITERION_INVALID


class VerificationRunMismatchError(VerificationError):
    """``SIM_VERIF_RUN_MISMATCH``: 候选 Run 与场景上下文不匹配（拒绝）."""

    code = SIM_VERIF_RUN_MISMATCH
