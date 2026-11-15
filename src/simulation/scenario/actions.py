"""SPEC-205 §4 — learner action whitelist and policy (SIM-F, ticket #45).

场景是内容不是代码（SPEC-205 §1）；学习者只能做白名单内的动作：

- 查看拓扑 / 查看证据（只读面）；
- 修改**批准的** config 字段；
- 更换**允许的**故障（本场景 fault_plan 内声明的故障）；
- 重新生成 / 分析；
- 提交验证。

白名单之外的任何动作拒绝（``SIM_SCENARIO_ACTION_FORBIDDEN``，错误稳定：
同输入同消息）；禁止任意 shell 命令与任意文件系统路径——它们不是动作类，
不在白名单内，天然拒绝。拒绝消息不回显动作载荷（错误是读取路径，
REQ-SIM-205-003 同源纪律）。

``approved_config_fields`` 由编排方按场景授予（SPEC-205 §4 "修改批准的
config 字段"的批准面在引擎编排层，不在场景文档 schema 里新增字段）；
默认为空集 = 不授予任何 config 修改。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable

from simulation.scenario.schema import (
    SIM_SCENARIO_ACTION_FORBIDDEN,
    ScenarioActionForbiddenError,
    ScenarioDocument,
)

__all__ = [
    "LEARNER_ACTION_WHITELIST",
    "LearnerAction",
    "LearnerActionPolicy",
]


class LearnerAction(str, Enum):
    """The five whitelist action classes of SPEC-205 §4 (``str``-mixin enum,
    values are the wire vocabulary)."""

    VIEW_TOPOLOGY = "view_topology"
    VIEW_EVIDENCE = "view_evidence"
    MODIFY_CONFIG = "modify_config"
    SWAP_FAULT = "swap_fault"
    REGENERATE = "regenerate"
    ANALYZE = "analyze"
    SUBMIT_VERIFICATION = "submit_verification"


#: The closed whitelist (SPEC-205 §4): 白名单之外的任何动作拒绝.
LEARNER_ACTION_WHITELIST = frozenset(LearnerAction)


@dataclass(frozen=True)
class LearnerActionPolicy:
    """The per-scenario action policy (SPEC-205 §4 enforcement face)."""

    document: ScenarioDocument
    approved_config_fields: frozenset[str] = field(default_factory=frozenset)

    def __init__(
        self,
        document: ScenarioDocument,
        *,
        approved_config_fields: Iterable[str] = (),
    ) -> None:
        object.__setattr__(
            self,
            "document",
            document,
        )
        object.__setattr__(
            self,
            "approved_config_fields",
            frozenset(approved_config_fields),
        )

    def allowed_fault_ids(self) -> tuple[str, ...]:
        """The fault ids a learner may swap in (this scenario's plan)."""
        return self.document.fault_ids()

    def check(
        self,
        action: LearnerAction | str,
        *,
        config_field: str | None = None,
        fault_id: str | None = None,
    ) -> None:
        """Raise :class:`ScenarioActionForbiddenError` for any non-whitelisted
        action; whitelisted actions return silently.

        ``modify_config`` additionally requires ``config_field`` to be in
        the approved field set; ``swap_fault`` requires ``fault_id`` to be
        declared in this scenario's fault_plan.
        """
        action_value = (
            action.value if isinstance(action, LearnerAction) else action
        )
        try:
            action_kind = LearnerAction(action_value)
        except ValueError:
            raise ScenarioActionForbiddenError(
                "learner action is not in the SPEC-205 §4 whitelist "
                f"({sorted(member.value for member in LEARNER_ACTION_WHITELIST)}); "
                "arbitrary shell commands and filesystem paths are never "
                "learner actions"
        ) from None
        if action_kind not in LEARNER_ACTION_WHITELIST:  # defensive
            raise ScenarioActionForbiddenError(
                "learner action is not in the SPEC-205 §4 whitelist"
            )
        if action_kind is LearnerAction.MODIFY_CONFIG:
            if config_field is None:
                raise ScenarioActionForbiddenError(
                    "modify_config requires the config field to modify; the "
                    "field must be in the approved field set (SPEC-205 §4)"
                )
            if config_field not in self.approved_config_fields:
                raise ScenarioActionForbiddenError(
                    "config field is not in the approved field set "
                    "(SPEC-205 §4 修改批准的 config 字段)"
                )
        if action_kind is LearnerAction.SWAP_FAULT:
            if fault_id is None:
                raise ScenarioActionForbiddenError(
                    "swap_fault requires the fault_id to swap in; the fault "
                    "must be declared in this scenario's fault_plan "
                    "(SPEC-205 §4 更换允许的故障)"
                )
            if fault_id not in self.document.fault_ids():
                raise ScenarioActionForbiddenError(
                    "fault is not declared in this scenario's fault_plan "
                    "(SPEC-205 §4 更换允许的故障)"
                )
