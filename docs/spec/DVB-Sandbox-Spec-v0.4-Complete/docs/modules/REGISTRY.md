# Module Spec Registry — 后续模块规格注册表

**状态说明：** 本表只定义未来 Spec 的编号、范围、建议依赖和优先级，不等于这些模块规格已经完整编写或批准。每项实现前必须生成对应 Module Spec。

优先级：`P0` = MVP 必须；`P1` = MVP 后段/近期增强；`P2` = 后续阶段；`P3` = 远期。

## A. TS Core

TS Core 的完整模块级规格已收录于 [`ts-core/`](ts-core/SPEC-INDEX-TS-CORE.md)。该目录中的 SPEC-100～SPEC-108 当前为 DRAFT，注册不代表批准。


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
| SPEC-206 | Recovery Verification | 恢复验证、通关规则、前后结果对比 | SPEC-205/303/305 | P0 |

## C. Observation / Diagnosis / TSDuck

| Spec ID | 名称 | 范围 | 建议依赖 | 优先级 |
|---|---|---|---|---|
| SPEC-300 | Observation Model | Observation/Event schema、来源和置信类型 | SPEC-003 | P0 |
| SPEC-301 | Metrics Engine | PID/Bitrate/CC/PCR 统计、窗口、聚合 | SPEC-100/105/300 | P0 |
| SPEC-302 | Evidence Manager | Artifact、Packet 定位、报告和日志关联 | SPEC-003/503 | P0 |
| SPEC-303 | Diagnosis Engine | 观察关联、根因候选、严重度和建议 | SPEC-300/301/302 | P0 |
| SPEC-304 | Diagnostic Rules | 规则定义、注册、匹配、抑制和版本 | SPEC-303 | P0 |
| SPEC-305 | TSDuck Adapter | Worker、命令构建、超时、报告和日志 | SPEC-302/500 | P0 |
| SPEC-306 | Analyzer Comparator | 自研解析器与 TSDuck 结果对比和分歧记录 | SPEC-300/305 | P1 |

## D. Frontend

| Spec ID | 名称 | 范围 | 建议依赖 | 优先级 |
|---|---|---|---|---|
| SPEC-400 | Frontend Architecture | 页面结构、状态、DTO、路由和构建 | SPEC-001/003 | P0 |
| SPEC-401 | Topology Editor | 节点/端口/连线/拖拽/校验展示 | SPEC-003/500 | P0 |
| SPEC-402 | Node Inspector | 节点属性、配置表单和校验提示 | SPEC-401/500 | P0 |
| SPEC-403 | Stream Monitor | 概览、PID、Bitrate、CC/PCR 聚合指标 | SPEC-301/501 | P0 |
| SPEC-404 | Packet Inspector | Packet 列表、Header/Hex/字段下钻 | SPEC-100/302/503 | P1 |
| SPEC-405 | CLI Console | 真实 TSDuck 输出、模拟日志的来源标识 | SPEC-305/501 | P0 |
| SPEC-406 | Training Lab UI | 实验目标、提示、步骤、通关结果 | SPEC-205/206 | P0 |
| SPEC-407 | Timeline & Replay UI | 时间轴、冻结证据、回放控制 | SPEC-640/501 | P2 |

## E. API / Storage / Quality

| Spec ID | 名称 | 范围 | 建议依赖 | 优先级 |
|---|---|---|---|---|
| SPEC-500 | REST API | 路由、DTO、错误响应、版本策略 | SPEC-001/003 | P0 |
| SPEC-501 | WebSocket | Event envelope、重连、序号、背压 | SPEC-003/300 | P0 |
| SPEC-502 | Persistence | SQLite Schema、Repository、迁移 | SPEC-003 | P0 |
| SPEC-503 | Artifact Storage | TS/报告/证据文件、哈希、路径安全 | SPEC-003/502 | P0 |
| SPEC-504 | Session Persistence | Session/Run 保存、恢复和过期 | SPEC-200/502 | P1 |
| SPEC-505 | Test Architecture | Pytest 分层、Fixture、测试数据组织 | SPEC-004 | P0 |
| SPEC-506 | Conformance Suite | MPEG-TS 标准测试向量、Golden Streams | SPEC-100～108 | P0 |
| SPEC-507 | Performance & Resource Limits | 码率、文件大小、内存、任务并发和背压 | SPEC-107/200/305 | P1 |

## F. Future DVB Domains

| Spec ID | 名称 | 范围 | 优先级 |
|---|---|---|---|
| SPEC-600 | T2MI Parser | T2-MI Packet 基础解析 | P2 |
| SPEC-601 | BBFrame Parser | BBHEADER、BBFrame 边界和 CRC | P2 |
| SPEC-602 | PLP Extractor | T2-MI PLP ID 过滤与提取 | P2 |
| SPEC-603 | Inner TS Reconstruction | BBFrame 解封装和 Inner TS 输出 | P2 |
| SPEC-610 | BISS Mode 1 | BISS-1 参数、解扰接口和证据 | P2 |
| SPEC-611 | BISS Mode E | ESW/Injected ID 计算和验证 | P2 |
| SPEC-612 | DVB-CA | PMT CA Descriptor、ECM/EMM 关系 | P3 |
| SPEC-620 | RF Simulation | RF 参数和质量状态模型 | P2 |
| SPEC-621 | LNB Model | 本振、极化、电压和频段状态 | P2 |
| SPEC-622 | DiSEqC Controller | 命令模型、端口和控制状态 | P2 |
| SPEC-623 | Unicable | EN 50494/EN 50607 槽位与调谐模型 | P2 |
| SPEC-630 | Linux DVB Frontend Adapter | Linux DVB API 接入 | P3 |
| SPEC-631 | Live TS Input | 文件/网络/硬件输入统一接口 | P2 |
| SPEC-632 | Live Monitoring | 实况指标与告警 | P2 |
| SPEC-640 | Time Machine | Ring Buffer、事件触发、冻结与回放 | P2 |
| SPEC-641 | TS Differential Analyzer | 双码流结构与指标差异分析 | P2 |

## G. 模块 Spec 完成条件

每个 Module Spec 至少必须包含：目标、范围、术语、架构、数据模型、公开接口、处理算法、错误处理、资源约束、依赖、测试向量、验收标准、非目标、兼容性与交付要求。
