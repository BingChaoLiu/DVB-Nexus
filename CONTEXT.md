# DVB-Nexus（DVB Sandbox）

DVB 数字沙盘与码流可视化分析平台：集"实时码流排查"与"交互式协议演练"于一体的单机工程平台。本词汇表是领域术语的权威来源；规格底稿见 `docs/spec/`（ChatGPT v0.4 包归档）。

## Language

### 运行模式与保真

**沙盘（Sandbox）**:
脱离真实硬件/直播源、由仿真引擎自主产生链路状态的运行模式。
_Avoid_: 仿真模式、Mock 模式、模拟器

**实况模式（Live Mode）**:
接入真实 DVB 硬件或 TS 文件流的运行模式（远期，MVP 不含）。
_Avoid_: 生产模式

**保真级（Fidelity）**:
同一拓扑下数据产生方式的两档：`SIM_STATE`（状态级，只算状态不产字节）与 `SIM_TS`（真实级，产出二进制 TS）。两者是同一业务系统的两种 Runtime，不是两套系统。
_Avoid_: L0/L1 作为架构层编号使用（L1 同时是架构层级名，代码命名禁混用）

**L0（State Runtime）**:
`SIM_STATE` 保真级的实现：拓扑参数传播与因果状态求值，不生成真实码流。

**L1（TS Runtime）**:
`SIM_TS` 保真级的实现：真正生成 188-byte MPEG-TS 二进制码流。

### 生成与验证

**TS Core**:
项目自研的 MPEG-TS 语义层核心（Packet、Section、PSI、PCR、Packetizer、Mux、Generator），是平台的核心技术资产。自研范围已复核冻结为语义层：PES 打包、多节目 MPTS 复杂调度、T2MI 推迟（ADR-0005）。
_Avoid_: TS Generator（仅指 TS Core 中的端到端装配模块）

**TSDuck**:
外部 TS 处理工具链，CLI 子进程集成，承担三重角色：**外部验证器**、**传输层故障注入器**、**生成兜底**（MVP 期）。自研 TS Core 仍是核心技术资产，TSDuck 不取代语义层。
_Avoid_: 把 TSDuck 结果当作绝对真值、让 TSDuck 取代自研语义层、把 TSDuck 输出标为 measured

**analysis_only**:
MVP 唯一验收的生成 Profile：TS 结构合规、可解析可分析，但负载为确定性合成数据，不承诺可播放。
_Avoid_: playback_ready（MVP 不承诺）

**双解析器对照（Cross Validation）**:
自研轻量解析器与 TSDuck 对同一 TS 分别分析并比对；不一致时产生 `ANALYZER_DISAGREEMENT` 而非采信单方。

### 实验

**故障靶场（Fault Lab）**:
预置故障场景的实验体系：注入真实码流/状态级故障，学员修复后重新生成并验证。
_Avoid_: 故障注入（Fault Injection 仅指注入机制本身，不含场景/评测）

**通关（Recovery Verification）**:
以**新的观测结果**判定实验通过——修复动作本身、UI 变绿都不算证据。判定为 PASS / FAIL / INCONCLUSIVE 三态。
_Avoid_: 用 UI 状态判定通关、把"无告警"等同于"干净"

**八步闭环（Closed Loop）**:
MVP 核心验收链路：Create → Generate → Inject → Analyze → Diagnose → Inspect → Recover → Verify，全程有真实数据和可追溯证据。

### 观察与证据

**观测（Observation）**:
某一时刻实际检测到的事实记录，必带来源（generator / internal_parser / tsduck / hardware / rule_engine）与置信度（simulated / parsed / measured / inferred），禁止混标。
_Avoid_: 把 SIM_STATE 产物标为 parsed、把 TSDuck 输出标为 measured

**证据（Evidence）**:
可下钻的原始数据关联：观测 → PID + packet index + Artifact，从诊断结果可直达原始码流。
_Avoid_: 无 Artifact 指引的裸日志

**Artifact**:
带元数据的资产文件（生成 TS / 故障 TS / 报告 / 日志），以 SHA-256、配置哈希、故障档案 ID 保证可复现与可追溯。
_Avoid_: 把 TS 文件当作无元数据的临时文件

**确定性复现（Deterministic Reproduction）**:
相同配置 + 种子 + 生成器版本 + 初始时钟 ⇒ 字节级相同的 TS（SHA-256 一致）。墙钟、随机 ID、路径禁入 TS 字节。
