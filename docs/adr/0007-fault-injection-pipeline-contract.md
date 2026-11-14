---
status: accepted
date: 2026-11-14
---

# 故障注入管线联合契约：语义流式过滤器、prepare 绑定 fault plan、等位替换保 CBR 与共用包序

裁决 SPEC-203/204 的结构洞（ChatGPT 包最大的设计空白）：SPEC-108 §13 与 TS-CORE-INTEGRATION-CONTRACT §9 规定 Generator 只出干净基线流、故障注入器是独立管线环节，但 SPEC-203 的 `TSRuntimeAdapter.prepare/run/cancel` 没有任何故障钩子——注入点、packet index 参照系、双 artifact 表达、四类故障参数语义均未定义。裁决过程见 [#9](https://github.com/BingChaoLiu/DVB-Nexus/issues/9)。本 ADR 只定契约语义；SPEC-203/204 文件重写随 [simulation + observation 缝合批准](https://github.com/BingChaoLiu/DVB-Nexus/issues/12) 落地，SPEC-108 §13 措辞微调随 [ts-core 规格逐份修订批准](https://github.com/BingChaoLiu/DVB-Nexus/issues/11) 落地，不静默改归档底稿。

## 决定（逐条）

### 1. 注入架构 = 语义流式过滤器（FaultDefinition 双路由落地）

四类 MVP 故障（PAT_MISSING / PMT_INVALID_CRC / CC_DISCONTINUITY / PMT_PID_MISMATCH）全是 PSI/语义级故障；[#4 调研](https://github.com/BingChaoLiu/DVB-Nexus/issues/4)确认语义级故障是 TSDuck 插件链硬边界。注入机制 = **Generator→sink 之间的语义包流过滤器**：操作 TSPacket/Section 对象、序列化前，位于 `faults` 包（[ADR-0005](0005-architecture-baseline.md) 决策 4 依赖方向 `faults → ts`），SPEC-107 Mux 零改动零感知。**双路由定形：语义级 = 自研流式过滤器；传输级 = TSDuck inject**（外部工具本就面向文件，MVP 不启用传输级）。TS Core 正常生成链路无故障分支（IC §9 维持）。

### 2. fault plan 在 prepare 绑定 + TSRunResult.artifacts 列表化

`prepare(session, config, fault_plan=())`：plan 在 prepare 校验（AC-204-01 "session 变异前拒绝"）并绑定进 PreparedTSRun 确定性指纹（SPEC-203 确定性条款本就把 fault plan 列入指纹）；`run()` 签名不变。`TSRunResult.artifacts` 由单字段改列表，kind 标注（generated_ts / faulted_ts / log）。带 plan 的 run **tee 双写**：过滤器前流 → baseline sink（kind=generated_ts），过滤器后流 → faulted sink（kind=faulted_ts）+ mutation log artifact（kind=log，含 AC-204-04 的 evidence locator：fault_id、target、注入点、before/after 包摘要、共用 index）；重复 baseline 按 SHA-256 内容寻址去重。plan 为空 = 仅出 baseline（Generate 步形态不变）。

### 3. activation MVP 收窄为 packet_index + session_start

SPEC-204 原文四种 activation 收窄：MVP 只支持 **packet_index**（含"从某 index 起持续到 run 结束"）+ **session_start**（全程生效）。virtual time 推迟（CBR 下 virtual time ↔ packet index 可确定性换算，留作 additive 扩展）；manual trigger 随交互式运行推迟（MVP 生成是离线批处理，ADR-0005 决策 4 已删 `workers/`，无触发时机）。

### 4. 等位替换不变式 = CBR 与共用包序的基石

四类 MVP 故障全部**等位（slot-preserving）**：不插入、不删除包——

- PAT_MISSING = Null 包（PID 0x1FFF）顶替原 slot（TS 是连续包序列，"删除"唯一保 CBR 的表示就是 Null 顶替）；
- PMT_INVALID_CRC 仅改 CRC 4 字节（节长不变）；
- PMT_PID_MISMATCH 仅改 PAT 内 13-bit 字段（等长重打包）；
- CC_DISCONTINUITY 仅改 header CC 半字节。

由此：**`byte_count == packet_count × 188` 与 CBR 恒定在 faulted 流上维持；baseline 与 faulted 共用同一包序 frame（packet_index 0..N-1 同槽位）**。AC-204-07 的"packet-index injection is stable"定义为：index 同时指向两条流的同一槽位；`activation.packet_index` 即此共用 frame。未来引入插入/删除型故障必须破坏此不变式，届时 mutation log 须携带 index 映射表（MVP 不含，作为对后续故障类型的准入约束）。

### 5. 四类故障语义（单一可归因症状原则）

靶场原则：每个故障产生**单一可归因症状**，不携带次生症状污染 Diagnose 归因。

- **PAT_MISSING**：窗口内 PID 0 包替换为 Null 包；窗口后 PID 0 后续 PAT 包 **CC 重盖**（用 SPEC-100 §5.4 CCAllocator 显式 `reset(pid, next)` 语义闭合计数断层——否则窗口后首个 PAT 触发次生 PID 0 CC 错误，与 CC_DISCONTINUITY 场景重叠）。MVP 配置约束 PCR_PID ∈ ES PID（≠ PID 0，SPEC-108 §5），顶替不丢 PCR。
- **CC_DISCONTINUITY**：**相对偏移**语义——落点 = activation index 后目标 PID 的**首个 payload 包**（adaptation-only 包按 SPEC-100 §5.4 重用规则跳过，不作为落点）；该包 CC = `(expected_next + delta) mod 16`，delta ∈ 1..15 非零；偏移**持续**（后续 payload 包从改写值继续 +1，模拟真实丢包后计数不复位）；adaptation-only 包在断点后仍按重用规则。绝对值语义废弃（依赖上游调度细节，生成器版本一变即失效）。观测：`ts.continuity_error`，evidence 定位到共用 index。
- **PMT_INVALID_CRC**：参数 `mode`（once = 首个 PMT 实例 | persistent = 激活后全部实例，**默认 persistent**——一次性 CRC 错会被后续正确表"冲掉"，persistent 症状稳定）+ `corruption`（invert = 全反，默认 | zero = 清零）；仅改 CRC 4 字节。观测：PMT CRC 校验失败。
- **PMT_PID_MISMATCH**：PAT 内 `program_map_PID` 改写为 `wrong_pmt_pid`（13-bit、非保留、≠ 实际 pmt_pid、≠ 0，prepare 时校验），**PAT CRC 重算**——PAT 本身合法，症状是"指向错"而非"CRC 坏"，与 PMT_INVALID_CRC 症状分离；PMT 原样留在真实 PID。观测：PAT 指向 wrong_pid、wrong_pid 上无 PMT、真实 PID 存在孤儿 PMT。

每类 FaultDefinition **必填 `expected_observations`**（事件码 + evidence 定位）；`examples/scenario-cc-discontinuity.json` 同步补全该字段（现缺失）。

### 6. 故障事件走 ADR-0006 信封（引用，不另立）

`fault.injected`（SCHEDULED，prepare 校验通过）/ `fault.activated`（ACTIVE，窗口起点）/ `fault.applied`（APPLIED，故障字节进入产物流的确认）/ `fault.cleared`（REMOVED，窗口终点或 run 结束），scope.run_id 归属、correlation `node_id + pid` 寻址，均按 [ADR-0006](0006-canonical-event-envelope.md) 第 5 条；本 ADR 不新增事件类型。

## Consequences

- **[缝合批准](https://github.com/BingChaoLiu/DVB-Nexus/issues/12) 补丁清单追加**：SPEC-203 重写 Interface（prepare 加 fault_plan 参数）/ Result（artifacts 列表 + mutation log）/ 确定性条款（plan 指纹显式化）；SPEC-204 重写 Fault model（activation 收窄为两种）/ MVP types（四类语义 + 版本化参数表）/ Lifecycle（等位替换不变式 + mutation log 结构）；scenario JSON 示例补 expected_observations。
- **[ts-core 修订批准](https://github.com/BingChaoLiu/DVB-Nexus/issues/11) 追加**：SPEC-108 §13 "Fault Injector 接收正常 Packet 流/Artifact" 补注"MVP 语义级故障走流式过滤器（ADR-0007）；Artifact 通道保留给 TSDuck 传输级路由"。
- **[golden streams 与 conformance 策略](https://github.com/BingChaoLiu/DVB-Nexus/issues/14)**：等位替换不变式使 faulted golden 流可与 baseline golden 流共用包序 frame，golden 策略可直接引用本 ADR 第 4 条。
- **fog 毕业**："v03 故障案例库 → MVP 靶场映射"从 map 的 Not yet specified 毕业为新 ticket（四类故障原语已定，映射问题可精确表述），blocked by 缝合批准。
- CONTEXT.md 增词条：故障双路由（Fault Dual-Route）、等位替换（Slot-Preserving Substitution）。
