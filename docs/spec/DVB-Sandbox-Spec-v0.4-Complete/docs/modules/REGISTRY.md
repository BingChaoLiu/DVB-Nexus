# Module Spec Registry — 后续模块规格注册表

**状态说明：** 本表只定义未来 Spec 的编号、范围、建议依赖和优先级，不等于这些模块规格已经完整编写或批准。每项实现前必须生成对应 Module Spec。

优先级：`P0` = MVP 必须；`P1` = MVP 后段/近期增强；`P2` = 后续阶段；`P3` = 远期。

## A. TS Core

TS Core 的完整模块级规格已收录于 [`ts-core/`](ts-core/SPEC-INDEX-TS-CORE.md)。该目录中的 SPEC-100～SPEC-108 已于 2026-11-14 批准为 MVP 基线（APPROVED 0.5.0，[ticket #11](https://github.com/BingChaoLiu/DVB-Nexus/issues/11)）；权威状态以各文件 front-matter 为准，此处不重复。


| Spec ID | 名称 | 范围 | 建议依赖 | 优先级 |
|---|---|---|---|---|
| SPEC-100 | TS Packet | 188-byte Packet Header、Adaptation Field、Payload、编解码和校验 | SPEC-003/004 | P0 |
| SPEC-101 | MPEG-2 CRC32 | 多项式、初值、计算、校验、测试向量 | SPEC-004 | P0 |
| SPEC-102 | PSI Section | Section Header、长度、分片/重组、CRC 集成 | SPEC-100/101 | P0 |
| SPEC-103 | PAT / PMT | PAT/PMT 字段、PID 关联、版本、Section 序号 | SPEC-102 | P0 |
| SPEC-104 | PES | PES Header、PTS/DTS、Packet Length、测试负载 | SPEC-100/105 | P0 |
| SPEC-105 | PCR / Clock | 虚拟时钟、PCR 编码/解码、回绕、时基换算 | SPEC-003 | P0 |
| SPEC-106 | TS Packetizer | Section/PES 分片、PUSI、Adaptation Field、CC | SPEC-100/102/104/105 | P0 |
| SPEC-107 | TS Mux | PID 调度、CBR、PCR 插入、Null Packet、速率模型 | SPEC-106/105 | P0 |
| SPEC-108 | TS Generator | 配置模型、完整生成流程、确定性和 Artifact | SPEC-103/104/107 | P0 |

## B. Simulation / Fault Lab

| Spec ID | 名称 | 范围 | 建议依赖 | 优先级 |
|---|---|---|---|---|
| SPEC-200 | Simulation Runtime | Runtime 接口、生命周期、取消、错误状态 | SPEC-001/003 | P0 |
| SPEC-201 | Simulation Clock | 可控虚拟时间、暂停/步进/加速、确定性 | SPEC-105/200 | P0 |
| SPEC-202 | State Engine | 拓扑状态求值、依赖传播和 L0 结果 | SPEC-200/Topology | P0 |
| SPEC-203 | TS Runtime | SIM_TS 编排、Generator 与 Artifact 关联 | SPEC-108/200/201 | P0 |
| SPEC-204 | Fault Injection | 触发器、Mutation、注入记录、撤销/重建策略 | SPEC-100/102/106/203 | P0 |
| SPEC-205 | Scenario Engine | 实验包格式、初始状态、提示、步骤和任务 | SPEC-204/300 | P0 |
| SPEC-206 | Recovery Verification | 恢复验证、通关规则、前后结果对比 | SPEC-205/306/308 | P0 |

## C. Observation / Diagnosis / TSDuck

编号对齐实际文件（[#10 编号体系重建](https://github.com/BingChaoLiu/DVB-Nexus/issues/10) 裁决）；SPEC-306～309 为旧注册语义的重新分配，规格文本随 [补写 MVP P0 缺失契约](https://github.com/BingChaoLiu/DVB-Nexus/issues/13) 编写。

| Spec ID | 名称 | 范围 | 建议依赖 | 优先级 |
|---|---|---|---|---|
| SPEC-300 | Observation & Metrics Architecture | 模块边界、架构、生命周期、数据流、事件摄入 | SPEC-003 | P0 |
| SPEC-301 | Canonical Event Contract | 权威事件信封、journal_seq 全序、交付与去重（ADR-0006） | SPEC-003 | P0 |
| SPEC-302 | Metrics Engine | 指标定义、聚合、标签与保留 | SPEC-100/105/300/301 | P0 |
| SPEC-303 | Timeline Recorder | 时间轴、检查点、回放与导出 | SPEC-300/301 | P0 |
| SPEC-304 | Health & Alert Engine | 健康规则、告警生命周期与证据 | SPEC-302/303 | P0 |
| SPEC-305 | Observation Query API | 内部服务 API 与查询语义 | SPEC-300/303 | P0 |
| SPEC-306 | Diagnosis Engine | 观察关联、根因候选、严重度和建议 | SPEC-300/301/302 | P0 |
| SPEC-307 | Diagnostic Rules | 规则定义、注册、匹配、抑制和版本 | SPEC-306 | P0 |
| SPEC-308 | TSDuck Adapter | Worker、命令构建、超时、报告和日志（ADR-0005 三操作） | SPEC-503/500 | P0 |
| SPEC-309 | Analyzer Comparator | 自研解析器与 TSDuck 结果对比和分歧记录 | SPEC-300/308 | P1 |

> 旧注册的 Evidence Manager（原 SPEC-302）不设独立规格：Artifact/报告关联由 SPEC-503 Artifact Storage 承载，Packet 定位与查询由 SPEC-305 承载，timeline/evidence 导出由 SPEC-303 承载，通关证据引用由 SPEC-206 承载。

## D. Frontend

| Spec ID | 名称 | 范围 | 建议依赖 | 优先级 |
|---|---|---|---|---|
| SPEC-400 | Frontend Architecture | 页面结构、状态、DTO、路由和构建 | SPEC-001/003 | P0 |
| SPEC-401 | Topology Editor | 节点/端口/连线/拖拽/校验展示 | SPEC-003/500 | P0 |
| SPEC-402 | Node Inspector | 节点属性、配置表单和校验提示 | SPEC-401/500 | P0 |
| SPEC-403 | Stream Monitor | 概览、PID、Bitrate、CC/PCR 聚合指标 | SPEC-302/501 | P0 |
| SPEC-404 | Packet Inspector | Packet 列表、Header/Hex/字段下钻 | SPEC-100/305/503 | P1 |
| SPEC-405 | CLI Console | 真实 TSDuck 输出、模拟日志的来源标识 | SPEC-308/501 | P0 |
| SPEC-406 | Training Lab UI | 实验目标、提示、步骤、通关结果 | SPEC-205/206 | P0 |

## E. API / Storage / Quality

| Spec ID | 名称 | 范围 | 建议依赖 | 优先级 |
|---|---|---|---|---|
| SPEC-500 | REST API | 路由、DTO、错误响应、版本策略 | SPEC-001/003 | P0 |
| SPEC-501 | WebSocket | Event envelope、重连、序号、背压 | SPEC-003/301 | P0 |
| SPEC-502 | Persistence | SQLite Schema、Repository、迁移 | SPEC-003 | P0 |
| SPEC-503 | Artifact Storage | TS/报告/证据文件、哈希、路径安全 | SPEC-003/502 | P0 |
| SPEC-504 | Session Persistence | Session/Run 保存、恢复和过期 | SPEC-200/502 | P1 |
| SPEC-505 | Test Architecture | Pytest 分层、Fixture、测试数据组织 | SPEC-004 | P0 |
| SPEC-506 | Conformance Suite | MPEG-TS 标准测试向量、Golden Streams | SPEC-100～108 | P0 |
| SPEC-507 | Performance & Resource Limits | 码率、文件大小、内存、任务并发和背压 | SPEC-107/200/308 | P1 |

## F. Future DVB Domains

SPEC-600+ 未来模块目录不在本表维护：`docs/roadmap.md` §3 是唯一权威索引（ADR-0002）。原 §F 16 行（SPEC-600～641）已由 roadmap 承载，编号原样保留。前端远期行 SPEC-407 Timeline & Replay UI（P2）同步移入 roadmap。

## G. 模块 Spec 完成条件

每个 Module Spec 至少必须包含：目标、范围、术语、架构、数据模型、公开接口、处理算法、错误处理、资源约束、依赖、测试向量、验收标准、非目标、兼容性与交付要求。
