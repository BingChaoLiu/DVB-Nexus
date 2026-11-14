---
spec_id: SPEC-000
title: Product Requirements — DVB Sandbox
version: 0.4.0
status: DRAFT
phase: BASELINE
owner: Project Owner
depends_on: []
---

# SPEC-000 — 产品需求规格

## 1. 产品概述

DVB Sandbox 是面向 DVB/广播传输工程师的本地数字实验与码流分析平台。产品由两类能力组成：

1. **工程分析（Live / Offline Analysis）**：对真实 TS 文件或后续接入的 DVB 实时流进行解析、监控、证据保存和故障定位。
2. **数字沙盘（Sandbox）**：在无真实接收硬件、无直播信号源的情况下，构建虚拟链路，生成协议数据，注入故障并验证修复。

平台不仅展示节点红黄绿状态，还要能够从诊断结论下钻到原始数据、Packet Index、PID、分析日志和对应运行上下文。

## 2. 产品原则

- **Evidence first**：诊断必须有可追溯证据；不能仅凭 UI 状态推断故障。
- **Protocol fidelity**：区分状态模拟、真实协议数据生成、真实硬件测量和规则推断。
- **One observation model**：Live、Sandbox、TSDuck 和自研解析器产生的数据，映射到统一 Observation 模型。
- **Reproducibility**：同一生成器版本、配置、种子和虚拟时钟条件，应能重现相同输出。
- **Incremental extensibility**：先完成 MPEG-TS 闭环，再扩展 T2MI、BISS、RF/SEC 和 Live DVB。
- **No fake evidence**：模拟 CLI 输出必须标明 simulated；不得伪装成真实 TSDuck 执行结果。

## 3. 目标用户

- DVB/数字电视/广播链路资深工程师：分析 TS、定位传输问题、保存证据。
- 初级工程师和新员工：通过交互实验理解 MPEG-TS、SI/PSI、时钟和故障传播。
- 核心开发与测试人员：使用确定性样本和故障注入验证解析器、复用器和集成接口。

## 4. 核心能力

### 4.1 双模式与仿真等级

- `LIVE`：输入真实 TS 文件或未来接入真实 DVB Frontend/网络流。
- `SANDBOX`：使用虚拟状态或协议生成器运行实验。
- `SIM_STATE`：状态级仿真，不承诺生成真实码流。
- `SIM_TS`：生成真实二进制 MPEG-TS，供解析器和 TSDuck 分析。

不得将 `SIM_STATE` 的推断结果标记为真实测量或真实解析结果。

### 4.2 MPEG-TS First

MVP 首先支持 188-byte TS Packet，包含基础 Packet Header、Adaptation Field、PAT、PMT、PES 封装、PCR、PID、PUSI、CC、Null Packet 和基础 Mux 调度。

MVP 输出 Profile：

- `analysis_only`：结构可解析、适合分析器和故障实验的 TS；PES 可以携带测试负载，不保证存在可播放的音视频 ES。
- `playback_ready`：包含合法可解码音视频 Elementary Stream 的输出，属于后续增强，不作为首个 MVP 的承诺。

TS 结构有效不等于视频可播放。PMT 声明某种 Stream Type，也不代表 ES 负载本身可解码。

### 4.3 故障靶场

MVP 故障场景至少覆盖：

- PAT 缺失或 PAT CRC 错误。
- PMT PID 映射错误或 PMT CRC 错误。
- 指定 PID 的 CC discontinuity / duplicate / drop。

每个故障应定义触发点、注入动作、预期观测、诊断要求、恢复步骤和通关条件。恢复必须通过重新生成/分析数据验证，不得只改变 UI 节点颜色。

### 4.4 TSDuck 联合验证

MVP 将 TSDuck 作为独立分析/处理工具集成。平台需记录工具版本、执行参数、退出码、stdout/stderr、分析报告和输入 Artifact 标识。

TSDuck 是重要的独立交叉验证来源，但不能被描述为对所有协议实现的绝对真值。自研解析器与 TSDuck 结果不一致时，应生成分析器分歧记录并保留原始证据。

### 4.5 可视化与教学

- 拓扑视图和节点配置。
- TS/PID/码率/CC/PCR 等基础分析。
- TSDuck CLI/日志视图，明确区分真实执行与模拟输出。
- 故障说明、证据定位和修复提示。
- Packet Inspector 属于 MVP 后段或 P1，具体交付以模块 Spec 为准。

## 5. MVP 范围

### In Scope

1. Python 后端基础工程和模块化结构。
2. TS Core：Packet、CRC、PSI Section、PAT/PMT、PES、PCR/Clock、Packetizer、Mux、Generator。
3. SIM_STATE 与 SIM_TS 两种 Runtime 接口。
4. 确定性 TS 生成与 Artifact 元数据。
5. 基础 Fault Injector 和至少三个 TS 故障实验。
6. TSDuck Worker / Adapter 与分析结果归一化。
7. Observation、Diagnosis 和证据关联。
8. 最小可用前端：拓扑、运行状态、分析结果、日志/CLI 展示。
9. Pytest 单元、集成和 Conformance 测试。

### Out of Scope（MVP）

- 完整 DVB-S/S2/S2X、DVB-T/T2 物理层或 RF 波形仿真。
- 真实射频调制解调和硬件锁定控制。
- 完整音视频编码器或 `playback_ready` 生产级生成。
- T2MI/BBFrame/PLP 完整生成和解析。
- BISS Mode 1/Mode E/BISS2 与通用 DVB-CA 完整实现。
- LNB、DiSEqC、Unicable 的真实设备控制。
- 多用户云端隔离、分布式集群、高可用部署。
- AI 视频质量评估。

可以在 `SIM_STATE` 中保留未来 RF/SEC 设备状态模型的扩展点，但不能因此宣称实现了真实 RF 仿真。

## 6. 产品路线图

| 阶段 | 目标 | 主要交付 |
|---|---|---|
| Phase 1 / MVP | TS-first Sandbox | TS 生成、故障注入、TSDuck 分析、证据、修复验证 |
| Phase 2 | T2MI / PLP / BISS | T2MI 解析、BBFrame/PLP 下钻、BISS 相关分析 |
| Phase 3 | RF / SEC Sandbox | LNB、DiSEqC、Unicable 状态和约束模型 |
| Phase 4 | Live Engineering | 真实 TS/DVB 输入、滚动缓存、回放、设备适配 |
| Later | Advanced Analysis | Time Machine、TS Differential Analyzer、更多靶场 |

路线图顺序可因评审调整，但不得在没有变更记录的情况下改变已批准 MVP 验收范围。

## 7. MVP 验收原则

MVP 必须演示完整闭环：

1. 创建拓扑与 TS 配置。
2. 生成真实二进制 TS 文件。
3. 对输出流注入至少一种真实 Packet/Section 级故障。
4. 用独立分析路径检测故障。
5. 从 Observation/Diagnosis 定位到 PID 和 Packet Index（适用时）。
6. 保存原始 TS、配置、Fault Profile、工具报告和运行日志。
7. 修复参数并重新生成、重新分析。
8. 证明故障已消失，并保留前后对照证据。

详细量化阈值和每个协议字段的验收条件由 SPEC-100～SPEC-108、SPEC-204、SPEC-308、SPEC-506 的批准版本定义。

## 8. 非功能目标

- 本地单机可运行，安装和启动方式可重复。
- API Event Loop 不执行长时间同步码流生成或 TSDuck 分析。
- 有界内存、队列背压、任务超时和子进程清理。
- 所有运行结果可关联 `run_id`、配置版本和 Artifact。
- 错误、测量、解析、推断和模拟的来源必须可区分。
- 关键测试可在 CI 或开发机重复执行。

具体性能指标在 SPEC-507 中定义；未定义之前不得对外承诺吞吐量。

## 9. 产品成功指标

- 至少三个基础故障场景能够稳定复现、检测和恢复。
- 生成的 TS 可被独立工具读取和分析。
- 每个诊断结论都能追溯到 Observation 或原始 Artifact。
- Agent 可依据独立模块 Spec 实施，不需要重新解释产品愿景。
