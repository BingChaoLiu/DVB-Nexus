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

**故障双路由（Fault Dual-Route）**:
故障注入的两条执行通路：语义级故障（PSI/CC 等）走自研包流过滤器，传输级故障走 TSDuck inject；同一 FaultDefinition 按层级路由，MVP 只启用语义级。
_Avoid_: 用 TSDuck 注入语义级故障、在 TS Core 生成链路内置故障分支

**analysis_only**:
MVP 唯一验收的生成 Profile：TS 结构合规、可解析可分析，但负载为确定性合成数据，不承诺可播放。
_Avoid_: playback_ready（MVP 不承诺）

**性能包络（Performance Envelope）**:
MVP 对性能与资源的承诺边界：支持的码率范围、默认生成档位、单 artifact 上限、生成耗时与内存上限；生成定位为离线批处理，不承诺实时。数值权威在 ADR-0008。
_Avoid_: 把包络上限当实时能力承诺、凭直觉调整阈值（须走 ADR 裁决）

**双解析器对照（Cross Validation）**:
自研轻量解析器与 TSDuck 对同一 TS 分别分析并比对；不一致时产生 `ANALYZER_DISAGREEMENT` 而非采信单方。

**独立验证（Independent Verification）**:
golden 向量的验收纪律：同源实现解析自身输出不构成验收证据，至少一条独立验证路径——外部位级向量（权威基准）或 TSDuck 双向交叉（合格独立验证）；自研 round-trip 仅作回归覆盖。
_Avoid_: 自生成自解析算验证、把回归通过当验收证据

### Phase 2 封装层

**T2-MI 封装器（T2-MI Encapsulator）**:
拓扑节点类型：把 Inner TS 经 BBFrame 封装段包化为 T2-MI 包流（in MPEG_TS / out T2MI）；BBFrame 参数与 PLP 分配表在其 config。
_Avoid_: 把 BBFrame 说成独立信号平面、把封装器与解封装器混称

**T2-MI 解封装器（T2-MI Demux）**:
拓扑节点类型：T2-MI 包流 → BBFrame 解析 → Inner TS 重建的观测侧链（in T2MI / out MPEG_TS）；期望 PLP 过滤在其 config。
_Avoid_: 用 TSDuck t2mi 插件指代本组件、把解封装失败说成静默丢弃

**三级封装（Three-level Encapsulation）**:
外层 TS Packet → BBFrame → Inner TS 的嵌套形态（B1/B2 教学结构）；封装方向反向对称。
_Avoid_: 把三级说成三个平面、漏掉 BBFrame 这一级

**分层流水线（Layered Pipeline）**:
每层「生成 → 本层 fault 过滤器 → 本层封装/传递」的执行模型；等位替换不变式逐层保持。
_Avoid_: 跨层混合过滤、把 tee 双写说成只在最内层

**作用层（Layer）**:
FaultDefinition 的层路由属性 {TS, BBFRAME, T2MI, BISS}，决定原语作用于哪层过滤器。
_Avoid_: 用平面名指代作用层、给 MVP 旧原语补写非 TS 层

**加扰器（Scrambler）**:
包级 payload 变换过滤器类型（包头 clear、包长不变、包序不变）；构造特性与 fault 注入共用，差别只是密钥来源。
_Avoid_: 把加扰说成故障注入的一种、跨包链式加扰破坏等位替换

**密钥指纹（Key Fingerprint）**:
密钥的哈希前缀，进 mutation log 与 biss.* 事件的唯一密钥痕迹；密钥本体永不落日志/artifact。
_Avoid_: 落密钥本体、把指纹当密钥用

**构造事件（Construction Event）**:
gen.* 命名空间的分级事件：阶段级（stage_started/completed）为主 + 抽样包级（packet_sampled，注入点必发射）；全量 packet 级流已裁决关闭。
_Avoid_: 发射逐包事件、把构造事件当通关证据

**解扰证据（Descramble Evidence）**:
按声明密钥解扰后的结构自检结果；解扰失败与码流损坏是两种显式区分的形态。
_Avoid_: 把解扰失败说成丢包、把无解扰记录说成码流干净

**PLP 分布（PLP Distribution）**:
per Run 的 PLP → 包数统计（t2mi.stage_summary 摘要）；B1 症状（期望/实际 PLP 漂移）的证据形态。
_Avoid_: 把期望 PLP 缺失说成零流量、把 PLP 分布当观测流

**多 UP BBFrame（N_UPS）**:
单 BBFrame 携带多个 UP 的封装形态；尾包不足 N_UPS 的填充语义须确定性。
_Avoid_: 静默丢尾包（TSDuck 3.45 缺陷形态）、跳过 CRC-8 校验

### 实验

**故障靶场（Fault Lab）**:
预置故障场景的实验体系：注入真实码流/状态级故障，学员修复后重新生成并验证。
_Avoid_: 故障注入（Fault Injection 仅指注入机制本身，不含场景/评测）

**等位替换（Slot-Preserving Substitution）**:
MVP 故障只做等位改写（顶替/原位改字段），不增删包：CBR 与 188 对齐在故障流上维持，baseline 与 faulted 码流共用同一包序，packet index 在两条流中指向同一槽位。
_Avoid_: 删包注入、把 faulted 流的 index 当独立参照系

**通关（Recovery Verification）**:
以**修复后的新 Run 证据**（码流观测与结构化声明）判定实验通过——修复动作本身、UI 变绿都不算证据。判定为 PASS / FAIL / INCONCLUSIVE 三态。
_Avoid_: 用 UI 状态判定通关、把"无告警"等同于"干净"

**八步闭环（Closed Loop）**:
MVP 核心验收链路：Create → Generate → Inject → Analyze → Diagnose → Inspect → Recover → Verify，全程有真实数据和可追溯证据。

**当前动作（Current Action）**:
八步闭环规范顺序（Analyze 为永久缺口，指针跳过）中第一个未完成步；乱序完成的步照常点亮（事实就是事实），指针不回退；全部点亮时指针落在 Verify。
_Avoid_: 把当前动作当通关进度、把指针位置当服务端事实

**已保存拓扑（Saved Topology）**:
拓扑库条目，拓扑编辑器的产物，snake_case wire 词汇；仅供拓扑模块载入与校验，主干旅程（Lab 场景）不读取。
_Avoid_: 与场景初始拓扑混称「拓扑」

**场景初始拓扑（Scenario Initial Topology）**:
`initial_topology`，场景文档的组成部分，camelCase wire 词汇；Lab 开局由文档治理，拓扑编辑器不消费它。两者 wire 词汇不同、语义同源。
_Avoid_: 与已保存拓扑混称「拓扑」

### 界面与引导

**空态三问（Three Empty-State Questions）**:
空态/引导文案的三问句式：这是什么 · 为什么空（空/失败 ≠ 干净）· 下一步去哪；一句话 + 单动作按钮可承载，按钮直接消除空态成因。
_Avoid_: 把空表渲染成「零问题/干净」、用弹窗 tour 替代静态路标

### 观察与证据

**观测（Observation）**:
某一时刻实际检测到的事实记录，必带来源（generator / internal_parser / tsduck / hardware / rule_engine）与置信度（simulated / parsed / measured / inferred），禁止混标。
_Avoid_: 把 SIM_STATE 产物标为 parsed、把 TSDuck 输出标为 measured

**证据（Evidence）**:
可下钻的原始数据关联：观测 → PID + packet index + Artifact，从诊断结果可直达原始码流。
_Avoid_: 无 Artifact 指引的裸日志

**结构化证据（Structured Evidence）**:
非观测类的合法通关证据种类：prepare 阶段绑定进 run 指纹的声明（如 prepared fault plan）与引擎生命周期事件（`fault.*`，无来源/置信度轴，故不是观测）。其"在/不在"是记录事实本身，不适用"无观测 ≠ 干净"的推断禁令。
_Avoid_: 把观测缺失当作结构化证据、把 `fault.*` 事件混标为观测

**Artifact**:
带元数据的资产文件（生成 TS / 故障 TS / 报告 / 日志），以 SHA-256、配置哈希、故障档案 ID 保证可复现与可追溯。
_Avoid_: 把 TS 文件当作无元数据的临时文件

**事件信封（Event Envelope）**:
全平台唯一的事件容器契约（SPEC-301 为权威）：所有跨模块事件走同一信封，生产者只标身份与双时钟（来源/观测），全序由流水号盖章。
_Avoid_: 三方信封混用、按模块自造信封格式、混合第四种信封

**诊断（Diagnosis）**:
规则或分析逻辑产生的**根因候选**，不是原始事实；由诊断规则（SPEC-307）静态声明置信度三档（low/medium/high），引擎不计算连续分，无校准依据不得宣称统计概率。与观测的置信度四值（simulated/parsed/measured/inferred）是两条不同的轴，禁止混用。
_Avoid_: 把 Diagnosis 当 Observation、把规则置信度说成概率、连续分宣称统计意义

**流水号（Journal Seq）**:
事件全序的唯一凭据：journal 落库时统一盖章，per session 单调；生产者不编全序号，来源时间戳不定序。
_Avoid_: 用墙钟排序、生产者自造全序号、per Run 重新编号

**确定性复现（Deterministic Reproduction）**:
相同配置 + 种子 + 生成器版本 + 初始时钟 ⇒ 字节级相同的 TS（SHA-256 一致）。墙钟、随机 ID、路径禁入 TS 字节。
