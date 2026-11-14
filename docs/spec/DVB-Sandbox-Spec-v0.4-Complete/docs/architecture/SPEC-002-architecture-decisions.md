---
spec_id: SPEC-002
title: Architecture Decision Records
version: 0.4.0
status: DRAFT
phase: BASELINE
owner: Architecture
depends_on:
  - SPEC-000
  - SPEC-001
---

# SPEC-002 — 架构决策记录（ADR）

## 1. 决策状态说明

- **CONFIRMED_DIRECTION**：项目负责人在讨论中明确选择的方向。
- **PROPOSED**：当前架构建议，仍需项目负责人批准。
- **OPEN**：尚无结论，需要后续评审。
- **SUPERSEDED**：已被新决策替代。

## 2. ADR 列表

| ADR | 决策 | 状态 |
|---|---|---|
| ADR-001 | Hybrid 仿真：状态级 + 真实 TS 级 | CONFIRMED_DIRECTION |
| ADR-002 | MPEG-TS 为第一优先级 | CONFIRMED_DIRECTION |
| ADR-003 | Python 为后端主语言 | CONFIRMED_DIRECTION |
| ADR-004 | Modular Monolith + 独立 Worker | PROPOSED |
| ADR-005 | TSDuck 作为外部分析/交叉验证工具 | PROPOSED |
| ADR-006 | MVP 自研 Python TS Core | PROPOSED |
| ADR-007 | REST + WebSocket | PROPOSED |
| ADR-008 | React + TypeScript / React Flow | PROPOSED |
| ADR-009 | SQLite + 文件系统 | PROPOSED |
| ADR-010 | 188-byte TS 作为 MVP 唯一生成格式 | PROPOSED |

## 3. ADR-001：Hybrid 仿真

**状态：CONFIRMED_DIRECTION**

### 背景

单纯状态 Mock 无法证明协议结构正确；只做真实码流又难以快速表达 RF/设备层因果和教学状态。

### 决策

保留两种 Fidelity：

- `SIM_STATE`：状态和因果模型；不生成真实 TS。
- `SIM_TS`：生成真实二进制 MPEG-TS，供分析器验证。

### 后果

- 共用 Run、Observation、Diagnosis 和 UI 呈现模型。
- 明确每条 Observation 的来源/置信类型。
- 两种 Runtime 内部实现可以不同，但公开事件契约统一。

## 4. ADR-002：MPEG-TS First

**状态：CONFIRMED_DIRECTION**

第一阶段优先实现 MPEG-TS，不同时推进 T2MI、BISS、RF/SEC 的真实协议栈。

MVP 重点是 188-byte TS Packet、PAT/PMT、PES、PCR、CC、Packetizer、Mux 和故障注入。204-byte RS204 输入/输出、T2MI 和其他封装留待后续专项 Spec。

## 5. ADR-003：Python Backend

**状态：CONFIRMED_DIRECTION**

Python 是后端主语言，用于 API、拓扑、Runtime 编排、诊断、实验管理和主要 TS Core 初始实现。

如经性能测试证明瓶颈，可把局部热点迁移到 C/C++/Rust，但必须保持稳定接口并提交 ADR 变更。不得为了未经测量的性能担忧提前引入多语言复杂度。

## 6. ADR-004：Modular Monolith + Worker

**状态：PROPOSED**

建议一个 Python 主服务按领域模块组织，TSDuck 和长时间 TS 生成在独立 Worker/子进程执行。首版不采用微服务和分布式消息队列。

需项目负责人批准后冻结。

## 7. ADR-005：TSDuck 集成方式

**状态：PROPOSED**

MVP 建议通过受控 CLI 子进程集成，而不是直接依赖完整 C++ ABI 或 Python Binding 覆盖范围。保留未来评估 Python Binding/C++ API 的可能。

TSDuck 用作独立分析和交叉验证工具，不取代项目自研 TS Core。

## 8. ADR-006：自研 Python TS Core

**状态：PROPOSED**

MVP 建议自行实现 Packet/Section/PES/PCR/Packetizer/Mux 核心，以便支持字段级故障注入、教学下钻和测试控制。TSDuck 用于外部分析，不负责成为唯一的生成器。

## 9. ADR-007：通信方式

**状态：PROPOSED**

建议 REST 承担配置和控制，WebSocket 承担事件与聚合状态推送。原始 TS 文件、报告和 Packet 数据通过 Artifact/按需接口读取。

## 10. ADR-008：前端技术

**状态：PROPOSED**

建议 React + TypeScript，拓扑图评估 React Flow。具体版本、状态管理、UI 组件库须在 SPEC-400 评审时确定。

## 11. ADR-009：本地存储

**状态：PROPOSED**

建议 SQLite 存储结构化元数据，文件系统保存 TS Artifact 和证据文件。不得将大体积 TS 二进制直接存入普通关系表，除非有明确理由。

## 12. ADR-010：MVP Packet Size

**状态：PROPOSED**

建议 MVP 先生成标准 188-byte TS；204-byte RS204、192-byte M2TS 等封装由后续输入/输出 Spec 决定。

## 13. 待决问题

| ID | 问题 | 建议解决时点 |
|---|---|---|
| OPEN-001 | FastAPI 是否正式定为 API 框架 | SPEC-001 批准前 |
| OPEN-002 | 前端 React Flow 是否采用 | SPEC-400 编写时 |
| OPEN-003 | TS 生成首版是否需要多 Service | SPEC-108 评审时 |
| OPEN-004 | `analysis_only` 是否使用固定测试 PES 负载格式 | SPEC-104/108 评审时 |
| OPEN-005 | SQLite 迁移工具与 Artifact 保留策略 | SPEC-502/503 评审时 |
| OPEN-006 | MVP 性能目标和最大 TS 文件大小 | SPEC-507 评审时 |

## 14. 变更要求

每个 ADR 需记录背景、候选方案、决策、理由、后果、状态、日期和受影响 Spec。已确认的 ADR 不得由 Agent 擅自修改。
