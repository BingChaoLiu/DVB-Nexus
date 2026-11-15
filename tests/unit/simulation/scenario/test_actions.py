"""SPEC-205 action-policy tests (SIM-F #45) — REQ-SIM-205-005.

SPEC-205 §4: the learner action whitelist is mandatory — 查看拓扑/证据、
修改批准的 config 字段、更换允许的故障、重新生成/分析、提交验证；白名单
之外的任何动作拒绝，错误稳定。禁止任意 shell 命令与任意文件系统路径。
"""

from __future__ import annotations

import pytest

from simulation.scenario.actions import (
    LEARNER_ACTION_WHITELIST,
    LearnerAction,
    LearnerActionPolicy,
)
from simulation.scenario.schema import (
    SIM_SCENARIO_ACTION_FORBIDDEN,
    ScenarioActionForbiddenError,
)

from ._scenario_builders import FAULT_ID, raw_scenario


@pytest.fixture()
def policy() -> LearnerActionPolicy:
    document = parse_scenario_document(raw_scenario())
    return LearnerActionPolicy(
        document, approved_config_fields=frozenset({"cbr_bps"})
    )


from simulation.scenario.schema import parse_scenario_document  # noqa: E402


def test_whitelist_covers_the_spec205_section4_classes():
    assert LEARNER_ACTION_WHITELIST == frozenset(
        {
            LearnerAction.VIEW_TOPOLOGY,
            LearnerAction.VIEW_EVIDENCE,
            LearnerAction.MODIFY_CONFIG,
            LearnerAction.SWAP_FAULT,
            LearnerAction.REGENERATE,
            LearnerAction.ANALYZE,
            LearnerAction.SUBMIT_VERIFICATION,
        }
    )


def test_every_whitelisted_action_passes(policy):
    for action in LearnerAction:
        if action is LearnerAction.MODIFY_CONFIG:
            policy.check(action, config_field="cbr_bps")
        elif action is LearnerAction.SWAP_FAULT:
            policy.check(action, fault_id=FAULT_ID)
        else:
            policy.check(action)


def test_action_accepts_wire_string_form(policy):
    policy.check("view_topology")
    policy.check("submit_verification")


@pytest.mark.parametrize(
    "forbidden",
    [
        "run_shell_command",
        "read_filesystem_path",
        "install_plugin",
        "export_hidden_solution",
        "edit_fault_parameters",
        "",
        "VIEW_TOPOLOGY; rm -rf /",
    ],
)
def test_every_non_whitelisted_action_is_rejected_stably(policy, forbidden):
    with pytest.raises(ScenarioActionForbiddenError) as first:
        policy.check(forbidden)
    with pytest.raises(ScenarioActionForbiddenError) as second:
        policy.check(forbidden)
    assert first.value.code == SIM_SCENARIO_ACTION_FORBIDDEN
    # 错误稳定：同输入同消息（SPEC-205 §8 白名单行）
    assert str(first.value) == str(second.value)


def test_modify_config_requires_an_approved_field(policy):
    with pytest.raises(ScenarioActionForbiddenError):
        policy.check(LearnerAction.MODIFY_CONFIG)
    with pytest.raises(ScenarioActionForbiddenError):
        policy.check(LearnerAction.MODIFY_CONFIG, config_field="secret_key")
    policy.check(LearnerAction.MODIFY_CONFIG, config_field="cbr_bps")


def test_policy_without_approved_config_fields_denies_config_edit():
    document = parse_scenario_document(raw_scenario())
    strict = LearnerActionPolicy(document)
    with pytest.raises(ScenarioActionForbiddenError):
        strict.check(LearnerAction.MODIFY_CONFIG, config_field="cbr_bps")


def test_swap_fault_only_within_scenario_plan(policy):
    policy.check(LearnerAction.SWAP_FAULT, fault_id=FAULT_ID)
    with pytest.raises(ScenarioActionForbiddenError):
        policy.check(
            LearnerAction.SWAP_FAULT,
            fault_id="0f0f8e10-1111-4222-8333-444455556666",
        )


def test_forbidden_action_errors_never_echo_action_payload(policy):
    payload = "arbitrary-injected-text-42"
    with pytest.raises(ScenarioActionForbiddenError) as excinfo:
        policy.check(LearnerAction.SWAP_FAULT, fault_id=payload)
    # The refusal names the action class and the rule, not the payload.
    assert payload not in str(excinfo.value)
