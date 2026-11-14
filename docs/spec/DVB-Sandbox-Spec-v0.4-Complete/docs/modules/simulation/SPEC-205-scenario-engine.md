---
spec_id: SPEC-205
title: Scenario and Training Lab Engine
version: 0.5.0
status: APPROVED
phase: MVP
owner: Simulation Engine
priority: P0
depends_on: [SPEC-003, SPEC-200, SPEC-204]
requirements: [REQ-SIM-205-001, REQ-SIM-205-002, REQ-SIM-205-003, REQ-SIM-205-004, REQ-SIM-205-005, REQ-SIM-205-006]
---

# SPEC-205 — 场景与训练实验引擎

## 1. 目标

定义故障靶场（Fault Lab，CONTEXT.md）的场景文档格式与执行引擎：声明式实验包（初始拓扑、配置、故障计划、目标、提示、通关标准）的校验、加载、执行隔离与安全边界。场景是**内容**，不是代码。

## 2. 范围

### 2.1 In Scope

- 场景文档（scenario document）的声明式格式与 schema 校验。
- 场景加载 = 新建 session + 版本/内容哈希钉扎。
- 学习者动作白名单与执行安全边界。
- 提示（hints）结构与引用纪律。
- fault plan 与 expected_observations 的场景级校验（衔接 SPEC-204）。

### 2.2 Out of Scope

- 通关判定逻辑（SPEC-206）。
- 生成编排与故障变换（SPEC-203/204）。
- 实验 UI（SPEC-406 Training Lab UI）。
- 场景市场/分发机制（roadmap）。

## 3. 场景文档格式

版本化声明式文档（JSON；YAML 允许作为编辑态、加载前规范化为 JSON），字段：

- `schema_version`：场景格式版本（本 spec 对应 `"1"`，演进遵循 SPEC-301 §8 兼容规则）。
- `scenario_id`：uuid4 opaque（ADR-0006 第 3 条）；人类可读性由 `title` 承担。
- `version` / `title` / `difficulty`。
- `required_engine_versions`：场景要求的引擎/生成器版本约束。
- `initial_topology`：SPEC-003 §2.1 配置模型。
- `simulation_config`：mode/seed/clock（SPEC-201 config 形态）。
- `fault_plan`：SPEC-204 `FaultDefinition` 数组；**每项必含 expected_observations**（ADR-0007 第 5 条），缺失即场景校验失败。
- `objectives`、分阶段 `hints`、`pass_criteria`（SPEC-206 消费）、可选 `hidden_reference_solution`。
- 参考样例：`examples/scenario-cc-discontinuity.json`。

## 4. 安全与校验

- **schema 校验强制**：不通过 schema 的场景文档拒绝加载，错误 path-addressed。
- **pass_criteria 引用完整性（加载期）**：判据 kind 须在 MVP 判据 kind 集合（SPEC-206 §7 closed enum）内；`fault_inactive` 引用的 `fault_id` 须在本场景 `fault_plan` 中。违规拒绝加载，path-addressed（`SIM_SCENARIO_CRITERION_INVALID`）。
- **永不执行场景包中的 Python 或任意代码**；导入/导出内容不得含可执行体（脚本、宏、动态表达式）。
- **学习者动作白名单**：查看拓扑/证据、修改批准的 config 字段、更换允许的故障、重新生成/分析、提交验证。白名单之外的任何动作拒绝。
- 禁止任意 shell 命令与任意文件系统路径；场景引用的 artifact 经 SPEC-503 受控访问。
- `hidden_reference_solution` 在 reveal 政策允许前不得通过任何 API 泄露（含错误消息、日志、导出）。

## 5. 执行模型

- **加载即新建**：加载场景创建**新 session**（SPEC-200）并钉扎 scenario 版本与内容哈希（SHA-256）；**不突变运行中的 session**。
- **重跑 = 新 Run 记录**：同场景重复执行产生可区分的 run 记录（run_id uuid4），各自保留证据链。
- **初始 Run 可复现**：同场景版本 + 同引擎版本 → 确定性初始 Run（字节一致，SPEC-203 确定性条款）。
- fault plan 经 SPEC-203 prepare 绑定进 Run 指纹；场景修订（内容哈希变化）= 新场景版本，旧版本不可变。
- 场景进度经包级契约发射 `scenario.step_started/step_completed`（ADR-0006 信封）。

## 6. 提示（Hints）

- 每条提示含：ID、触发条件（trigger）、级别（level）、内容、关联需求 ID、可选的标准条款引用。
- **禁止编造 ETSI/ITU 条款号**：标准引用必须是经核查的条款（引用纪律同 [标准条款引用核查](https://github.com/BingChaoLiu/DVB-Nexus/issues/6) 结论）；无法核实就不写条款号。

## 7. 错误与诊断码

| Code | 条件 | 处理 |
|---|---|---|
| `SIM_SCENARIO_SCHEMA_INVALID` | 场景文档不过 schema | 拒绝，附 path |
| `SIM_SCENARIO_CRITERION_INVALID` | pass_criteria 引用完整性失败（kind 不在 SPEC-206 §7 集合 / `fault_inactive` 的 `fault_id` 不在本场景 fault_plan） | 拒绝加载，path-addressed |
| `SIM_SCENARIO_FAULT_PLAN_INVALID` | fault plan/expected_observations 校验失败 | 拒绝（SPEC-204 错误码透传） |
| `SIM_SCENARIO_ACTION_FORBIDDEN` | 学习者动作不在白名单 | 拒绝 |
| `SIM_SCENARIO_VERSION_CONFLICT` | 对运行中 session 应用新版本 | 拒绝，要求新 session |
| `SIM_SCENARIO_SOLUTION_LEAK` | 参考解暴露路径被触发 | 拒绝并审计 |

## 8. 测试规格

- 畸形 schema 负向样例全拒绝（缺字段/类型错/未知 fault_type/缺 expected_observations）。
- pass_criteria 引用完整性负向样例全拒绝（kind 不在 SPEC-206 §7 集合 / `fault_inactive` 引用不在 fault_plan 的 `fault_id`）。
- 场景不可变：加载后对文档对象的任何修改不影响已建 session。
- 参考解保护：reveal 政策外的全部读取路径（API/导出/日志）断言为空。
- 确定性初始 Run：同版本场景重复加载生成 SHA-256 一致的 baseline。
- 白名单：每个白名单外动作样例拒绝且错误稳定。
- 导入/导出无可执行内容（静态扫描 + fuzz）。

## 9. 验收标准

- `REQ-SIM-205-001`：schema 校验强制，畸形文档拒绝并 path 定位。
- `REQ-SIM-205-002`：场景在 session 创建后不可变；重跑产生独立 run 记录。
- `REQ-SIM-205-003`：参考解在 reveal 政策前受保护。
- `REQ-SIM-205-004`：确定性初始 Run 可复现。
- `REQ-SIM-205-005`：学习者动作白名单强制。
- `REQ-SIM-205-006`：导入/导出不含可执行内容；fault plan 必含 expected_observations。

## 10. 非目标与风险

- 不做场景评分/积分体系（roadmap）。
- 不承诺场景热更新；版本钉扎即唯一演进方式。
- 风险：pass_criteria 表达力不足会倒逼实现者塞逻辑进场景文档——判定语义归 SPEC-206，场景只声明判据引用，禁止内嵌表达式。

## 11. 交付要求

建议文件：`app/simulation/scenario/`（schema.py / loader.py / actions.py）；示例与测试场景置于 `examples/` 与 `tests/fixtures/scenarios/`。

## 12. 参考

- SPEC-204（FaultDefinition/expected_observations）、SPEC-206（pass criteria 判定）。
- ADR-0006 第 3 条（ID 策略）、ADR-0002（八步闭环中 Create/Recover 步的场景角色）。
- CONTEXT.md「故障靶场」词条。
