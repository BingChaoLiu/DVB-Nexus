---
spec_id: SPEC-005
title: Agent Development Protocol
version: 0.4.0
status: DRAFT
phase: BASELINE
owner: Project Owner
depends_on:
  - SPEC-001
  - SPEC-003
  - SPEC-004
---

# SPEC-005 — Agent 开发协议

## 1. 目标

定义 AI Agent 或外部开发者参与项目时的统一流程，确保并行开发不会导致架构漂移、接口冲突、重复实现或验收失真。

## 2. 权威来源

优先级由高到低：

1. 项目负责人批准的 Product/Architecture/Module Spec。
2. 已批准的 ADR 与跨模块契约。
3. 当前代码中已批准并登记的接口实现（仅当 Spec 未覆盖且经项目负责人认可时）。
4. Agent 的推断或临时建议。

Agent 的推断不得覆盖已批准 Spec。Spec 与代码不一致时，必须报告差异，不得自行选择一方静默修改。

## 3. 开发准入门禁

- 没有 `APPROVED` 的 Module Spec，不得开始正式编码。
- 每项编码任务必须有唯一 `TASK-ID`，引用一个或多个 Approved Spec 和 Requirement ID。
- 每个 Task 必须明确修改文件 Allowlist、只读依赖、禁止修改范围、测试命令和验收标准。
- 对大任务，Agent 先提交 Implementation Plan；经项目负责人或任务委派者批准后开始编码。
- 仅做方案探索的任务必须明确标记 `SPIKE`，不得将探索代码直接视为正式实现。

## 4. Agent 实施前必须输出的计划

1. 对目标 Spec 的理解和范围摘要。
2. 需求 ID 与验收项列表。
3. 预计新增/修改文件。
4. 依赖接口和外部库。
5. 实现步骤和风险。
6. 单元/集成/边界测试计划。
7. 发现的 Spec 歧义或冲突。

存在会改变接口、架构、二进制格式或兼容性的歧义时，暂停相关实现并提交问题，不得自行定案。

## 5. 修改边界

- 只能修改 Task Allowlist 中的文件；确有必要时先申请扩展 Allowlist。
- 不得修改其他模块的公共接口、全局数据模型、依赖版本、构建脚本和 CI 配置，除非 Task 明确授权。
- 不得擅自增加运行时依赖或复制其他模块的已有功能。
- 不得为了通过测试删除/弱化测试断言或更改验收标准。
- 不得将模拟结果伪装成真实解析、真实测量或 TSDuck 输出。
- 不得把未完成、未测试或跳过的功能报告为完成。

## 6. 变更申请

发现已批准 Spec 不完整或有错误时，提交 `SPEC_CHANGE_REQUEST`，内容包括：

- 受影响 Spec ID 和版本。
- 具体问题、复现条件和证据。
- 建议改动及替代方案。
- 对依赖模块、公共 API、数据模型和测试的影响。
- 兼容性说明和迁移方案。

未获批准前，Agent 可在独立分支做可丢弃的探索，但不得合并改变架构的代码。

## 7. 并行开发规则

- 并行任务不得同时修改同一个公共接口或相同文件集合，除非明确指定接口负责人。
- 先完成共享数据模型和接口 Spec，再并行实现消费者/提供者。
- 跨模块接口由指定 Integration Owner 管理。
- 合并顺序按依赖图执行；上游契约未稳定时，下游只能使用经批准的 Stub/Fake。
- 每个 Agent 必须声明分支、Task ID、负责文件和依赖版本。

## 8. 实施报告

Agent 交付时必须提供 `IMPLEMENTATION_REPORT.md`，至少包含：

- Task ID、Spec ID/版本、提交或分支标识。
- 实现的 Requirement ID。
- 新增/修改文件。
- 执行过的命令和测试结果（通过/失败/跳过及原因）。
- 每条 Acceptance Criteria 的 PASS/FAIL/BLOCKED。
- Spec Deviations（必须明确写 None 或逐项列出）。
- 已知问题、安全/性能限制和未完成工作。
- 是否需要数据库迁移、配置变化或其他模块配合。

## 9. 验收门禁

任务只有满足以下条件才能通过：

1. 修改范围符合 Allowlist，或扩展已获批准。
2. 代码与 Approved Spec 一致。
3. 相关单元、集成和 Conformance 测试通过。
4. 没有未批准的公共接口或依赖变化。
5. 所有 Acceptance Criteria 有证据。
6. 实施报告完整。
7. 代码已由项目负责人/指定 Reviewer 审查并合并。

`IMPLEMENTED` 状态只能由项目负责人或指定维护者更新，不能由执行 Agent 自行宣布。

## 10. 推荐 Agent Task 规模

优先将任务拆成可独立测试、改动面有限的交付单元。例如：

- 实现 MPEG-2 CRC32 与测试向量。
- 实现 TSPacket 编解码及边界检查。
- 实现 PSI Section 解析/序列化。

避免一次性分配“完成整个 TS Core”或“完成完整前端”这类无法有效审查的大任务。

## 11. Agent 输出约束

Agent 输出必须明确区分：已实现、未实现、假设、阻塞、测试证据和建议。不得编造测试通过结果、TSDuck 输出、标准符合性或性能数据。若执行环境缺少 TSDuck，应标为 BLOCKED/NOT RUN，而不是 PASS。
