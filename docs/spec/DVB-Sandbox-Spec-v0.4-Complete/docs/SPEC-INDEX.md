# SPEC-INDEX — DVB Sandbox Specification Registry

**Baseline:** v0.4.0-draft  
**Last updated:** 2026-11-13  
**Owner:** Project Owner  
**Authority:** 本文件用于索引，不替代各 Spec 正文。

## 1. 状态定义

| 状态 | 含义 | 是否允许进入实现 |
|---|---|---|
| `DRAFT` | 正在编写，内容可能不完整 | 否 |
| `REVIEW` | 已提交评审，等待意见或批准 | 否 |
| `APPROVED` | 项目负责人批准，作为实现基线 | 是，仅限对应版本 |
| `IMPLEMENTING` | 已有 Agent 按批准规格开发 | 是 |
| `IMPLEMENTED` | 代码已合并且验收证据齐全 | 不适用 |
| `DEPRECATED` | 已废弃，由新 Spec/版本替代 | 否 |

## 2. 项目级规格

| ID | 文档 | 初始状态 | 说明 |
|---|---|---|---|
| SPEC-000 | [Product Requirements](product/SPEC-000-product-requirements.md) | `DRAFT` | 产品目标、范围、阶段验收 |
| SPEC-001 | [System Architecture](architecture/SPEC-001-system-architecture.md) | `DRAFT` | 系统分层、部署、模块边界 |
| SPEC-002 | [Architecture Decisions](architecture/SPEC-002-architecture-decisions.md) | `DRAFT` | 决策状态、ADR 与待确认项 |
| SPEC-003 | [Domain Model](architecture/SPEC-003-domain-model.md) | `DRAFT` | 核心实体、事件和跨模块契约 |
| SPEC-004 | [Engineering Standards](engineering/SPEC-004-engineering-standards.md) | `DRAFT` | 代码、测试、质量门禁 |
| SPEC-005 | [Agent Development Protocol](engineering/SPEC-005-agent-development-protocol.md) | `DRAFT` | Agent 工作边界和交付规则 |

## 3. 模块规格注册表

详见 [modules/REGISTRY.md](modules/REGISTRY.md)。已批准包的完整规格：TS Core [SPEC-INDEX-TS-CORE.md](modules/ts-core/SPEC-INDEX-TS-CORE.md)、Simulation [SPEC-INDEX-SIMULATION.md](modules/simulation/SPEC-INDEX-SIMULATION.md)、Observation [SPEC-INDEX-OBSERVATION-METRICS.md](modules/Observation-Metrics/SPEC-INDEX-OBSERVATION-METRICS.md)。登记不代表规格已批准；已批准包（ts-core / simulation / observation 300~305）权威状态以各文件 front-matter 为准。

| 范围 | ID 区间 | 内容 |
|---|---|---|
| TS Core | SPEC-100～108 | Packet、CRC、Section、PAT/PMT、PES、PCR、Packetizer、Mux、Generator |
| Simulation / Fault Lab | SPEC-200～206 | Runtime、Clock、State、TS Runtime、Fault、Scenario、Recovery |
| Observation / Diagnosis / TSDuck | SPEC-300～309 | Observation 架构、事件信封、Metrics、Timeline、Health/Alerts、Query API、Diagnosis、Rules、TSDuck Adapter、Comparator（Evidence Manager 分摊至 503/305/303/206，见 REGISTRY §C） |
| Frontend | SPEC-400～407 | 前端架构、Topology、Inspector、Monitor、Packet、CLI、Lab、Replay |
| API / Storage / Quality | SPEC-500～507 | REST、WebSocket、Persistence、Artifact、Session、测试、Conformance、性能 |
| Future DVB domains | SPEC-600+ | T2MI、BBFrame、PLP、BISS、CA、RF、DiSEqC、Unicable、Live DVB |

## 4. 基线依赖关系

```text
SPEC-000 Product Requirements
    └── SPEC-001 System Architecture
          ├── SPEC-002 Architecture Decisions
          ├── SPEC-003 Domain Model
          ├── SPEC-004 Engineering Standards
          └── SPEC-005 Agent Development Protocol

TS Core:
SPEC-100 Packet ──┬── SPEC-102 PSI Section ── SPEC-103 PAT/PMT
                  ├── SPEC-104 PES
                  └── SPEC-105 PCR/Clock
                       ↓
                 SPEC-106 Packetizer
                       ↓
                 SPEC-107 Mux
                       ↓
                 SPEC-108 Generator

Simulation / Observation（[缝合批准 #12] 统一依赖方向，详见 REGISTRY §B/§C 与各包索引）:
SPEC-200 Runtime ──┬── SPEC-201 Clock ── SPEC-105（PCR 换算）
                   ├── SPEC-202 L0 State Engine
                   └── SPEC-203 TS Runtime ── SPEC-100..108
                         └── SPEC-204 Fault Injection（faults → ts）
SPEC-205 Scenario Engine ── SPEC-206 Recovery Verification ── SPEC-205/306/308
SPEC-300 Observation ── SPEC-301 Event Contract（权威信封）── SPEC-302 Metrics ── SPEC-304 Health & Alerts
SPEC-303 Timeline / SPEC-305 Query API ← 事件流水与工件
SPEC-306 Diagnosis ── SPEC-307 Rules（事件走 SPEC-301 信封）
SPEC-503 Artifact Storage ← TS artifacts / analyzer reports
```

详细依赖以各模块 Spec 的 `depends_on` 为准。

## 5. 发布与变更规则

- 项目级基线版本与单份 Spec 版本分别管理。
- 已批准 Spec 的接口不允许被 Agent 静默修改。
- 发生不兼容变化，必须提升该 Spec 的主版本，并更新所有依赖模块。
- `IMPLEMENTED` 必须附带测试报告、验收项结果、修改文件清单和未解决问题。
- 若需求没有对应 Requirement ID，先登记需求，再进入模块 Spec。
