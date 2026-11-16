---
spec_id: SPEC-204
title: Fault Injection Framework
version: 0.6.0
status: APPROVED
phase: MVP
owner: Simulation Engine
priority: P0
depends_on: [SPEC-003, SPEC-100, SPEC-102, SPEC-103, SPEC-106]
requirements: [REQ-SIM-204-001, REQ-SIM-204-002, REQ-SIM-204-003, REQ-SIM-204-004, REQ-SIM-204-005, REQ-SIM-204-006, REQ-SIM-204-007, REQ-SIM-204-008]
---

# SPEC-204 — 故障注入框架（语义流式过滤器）

## 1. 目标

为合成沙盘码流提供**类型化、确定性**的故障注入：每个故障改变真实码流/状态证据，绝不只把 UI 涂红（CONTEXT.md 故障靶场）。注入架构为 **Generator→sink 之间的语义包流过滤器**（[ADR-0007](../../../../adr/0007-fault-injection-pipeline-contract.md) 第 1 条）：操作 TSPacket/Section 对象、序列化之前，位于 `faults` 包（依赖方向 `faults → ts`，ADR-0005 决策 4），SPEC-107 Mux 零改动零感知。

## 2. 范围

### 2.1 In Scope

- `FaultDefinition` 数据模型与版本化参数 schema。
- MVP 四类故障的逐类语义（第 6 节，单一可归因症状原则）。
- activation 模型（MVP 收窄为 packet_index + session_start）。
- 等位替换不变式（第 7 节）与 mutation log 结构（第 8 节）。
- 故障生命周期四态与 `fault.*` 事件引用（ADR-0006 第 5 条）。
- 故障双路由中的**语义级**通路；传输级通路仅保留接口位。

### 2.2 Out of Scope

- 传输级故障的 TSDuck inject 执行（SPEC-308 TSDuck Adapter，文本随 #13；MVP 不启用传输级注入）。
- virtual time activation 与 manual trigger（第 5 节推迟项）。
- 插入/删除型故障（破坏等位替换不变式，准入约束见第 7 节）。
- 真实硬件/直播流注入（安全边界，第 10 节）。
- 诊断归因本身（SPEC-306/307，文本随 #13）。

## 3. 数据模型

```python
@dataclass(frozen=True)
class FaultDefinition:
    fault_id: str                       # uuid4，opaque（ADR-0006 第 3 条）
    fault_type: str                     # 注册表内的类型枚举，见第 6 节
    target_id: str                      # 拓扑内语义寻址 slug（如 "demux-0:pid:0x0100"）
    parameters: Mapping[str, object]    # 按 fault_type 的版本化参数 schema 校验
    activation: FaultActivation
    expected_observations: tuple[str, ...]   # 必填：事件码 + evidence 定位说明

@dataclass(frozen=True)
class FaultActivation:
    kind: Literal["packet_index", "session_start"]
    packet_index: int | None            # kind=packet_index 时必填，0 起算
```

- **expected_observations 必填**（ADR-0007 第 5 条）：声明该故障应产生的观测事件码（如 `("ts.continuity_error",)`）及其 evidence 定位方式；缺失即 prepare 校验失败。SPEC-206 通关判定与 SPEC-205 pass_criteria 消费该字段。
- **activation MVP 收窄**（ADR-0007 第 3 条）：仅 `packet_index`（含"起于某 index 持续到 run 结束"语义）+ `session_start`（全程生效）。virtual time 推迟——CBR 下 virtual time ↔ packet index 可确定性换算，留作 additive 扩展；manual trigger 随交互式运行推迟（MVP 生成是离线批处理，ADR-0005 已删 `workers/`）。**禁止**用墙钟 sleep 调度任何故障。
- target 寻址遵循 ADR-0006 第 3 条双形式：节点级（状态面）`node_id` 单独、流级 `node_id + pid`；故障事件 correlation 按此寻址。

## 4. 参数 schema 版本化

- 每类 fault_type 有版本化参数 schema（`parameters_schema_version`）；未知 fault_type、未知参数键、越界值、缺失必填键一律拒绝（prepare 阶段，AC-204-01）。
- schema 演进遵循 SPEC-301 §8 兼容规则：新增可选参数 = minor；删除/改名/改语义 = major + 迁移说明。

## 5. 注入架构与管线接入

- 过滤器挂接点由 SPEC-203 管：prepare 绑定 plan → run 期 Generator 输出流经过滤器 → tee 双写（过滤器前流 = baseline sink，过滤器后流 = faulted sink，SPEC-203 §5.2）。
- 过滤器是**纯流变换**：输入 TSPacket/Section 对象流，输出等长对象流；无 IO、无墙钟、无随机数。
- 故障双路由（CONTEXT.md）：语义级 = 本过滤器；传输级 = TSDuck inject（文件级工具，MVP 不启用）。同一 FaultDefinition 按层级路由；用 TSDuck 注入语义级故障、在 TS Core 生成链路内置故障分支均被禁止。

## 6. MVP 四类故障语义（单一可归因症状原则）

靶场原则：每个故障产生**单一可归因症状**，不携带次生症状污染 Diagnose 归因（ADR-0007 第 5 条）。

### 6.1 PAT_MISSING

- **变换**：窗口内（activation 起至 run 结束）PID 0 的 PAT 包顶替为 **Null 包**（PID 0x1FFF）——TS 是连续包序列，"删除"唯一保 CBR 的表示就是 Null 顶替。
- **CC 重盖**：窗口后 PID 0 后续 PAT 包按 SPEC-100 §5.4 `CCAllocator.reset(pid, next)` 语义闭合计数断层——否则窗口后首个 PAT 触发次生 PID 0 CC 错误，与 CC_DISCONTINUITY 场景重叠。
- **配置约束**：PCR_PID ∈ ES PID（≠ PID 0，SPEC-108 §5 项目收紧规则），顶替不丢 PCR。
- **参数 schema v1**：`{}`（无额外参数；窗口由 activation 决定）。
- **观测**：`ts.psi_section_observed` 缺失 / PAT 超时类规则告警；evidence 定位到窗口起点 index。

### 6.2 PMT_INVALID_CRC

- **变换**：仅改选中 PMT Section 的 CRC 4 字节（节长不变）。
- **参数 schema v1**：`mode: "once" | "persistent"`（once = 首个 PMT 实例；persistent = 激活后全部实例，**默认 persistent**——一次性 CRC 错会被后续正确表"冲掉"，症状不稳）、`corruption: "invert" | "zero"`（全反 | 清零，默认 invert）。
- **观测**：PMT CRC 校验失败（`ts.psi_section_observed` 携带 CRC error）。

### 6.3 CC_DISCONTINUITY

- **变换（相对偏移语义）**：落点 = activation index 之后目标 PID 的**首个 payload 包**（adaptation-only 包按 SPEC-100 §5.4 重用规则跳过，不作为落点）；该包 CC = `(expected_next + delta) mod 16`，`delta ∈ 1..15` 且非零；偏移**持续**——后续 payload 包从改写值继续 +1（模拟真实丢包后计数不复位）；断点后 adaptation-only 包仍按重用规则。
- 绝对值语义**废弃**（依赖上游调度细节，生成器版本一变即失效）。
- **参数 schema v1**：`delta: int`（1..15）。
- **观测**：`ts.continuity_error`，evidence 定位到共用 frame 的落点 index。

### 6.4 PMT_PID_MISMATCH

- **变换**：PAT 内 `program_map_PID` 改写为 `wrong_pmt_pid`（13-bit、非保留 PID、≠ 实际 pmt_pid、≠ 0，prepare 时校验），**PAT CRC 重算**——PAT 本身合法，症状是"指向错"而非"CRC 坏"，与 PMT_INVALID_CRC 症状分离；PMT 原样留在真实 PID。
- **参数 schema v1**：`wrong_pmt_pid: int`（0x0001..0x1FFE，排除保留与实际值）。
- **观测**：PAT 指向 wrong_pid、wrong_pid 上无 PMT、真实 PID 存在孤儿 PMT（三症状同源，属同一根因）。

## 7. 等位替换不变式（Slot-Preserving Substitution）

四类 MVP 故障全部**等位**：不插入、不删除包——

| 故障 | 等位操作 |
|---|---|
| PAT_MISSING | Null 包顶替原 slot |
| PMT_INVALID_CRC | 原位改 CRC 4 字节 |
| PMT_PID_MISMATCH | 原位改 PAT 内 13-bit 字段（等长重打包） |
| CC_DISCONTINUITY | 原位改 header CC 半字节 |

由此冻结：

1. `byte_count == packet_count × 188` 与 CBR 恒定在 **faulted 流上维持**；
2. **baseline 与 faulted 共用同一包序 frame**：packet_index 0..N-1 在两条流中指向同一槽位；`activation.packet_index` 即此共用 frame 的 index；
3. AC-204-07 "packet-index injection is stable" 的定义 = index 同时指向两条流的同一槽位；
4. **准入约束**：未来引入插入/删除型故障必须破坏此不变式，届时 mutation log 必须携带 index 映射表——未携带映射表前，此类故障不得进入 MVP 靶场。

## 8. 生命周期与 mutation log

### 8.1 故障生命周期

```text
DEFINED -> SCHEDULED -> ACTIVE -> APPLIED -> REMOVED
                 \-----------------------------------------> FAILED
```

- DEFINED = prepare 校验通过（`fault.injected`，ADR-0006 第 5 条 = SCHEDULED 语义锚点）；ACTIVE = 窗口起点（`fault.activated`）；APPLIED = 故障字节已进入产物流的确认（**L1 专用** `fault.applied`；状态级场景与 activated 同时发生，applied 可省略）；REMOVED = 窗口终点或 run 结束（`fault.cleared`）。
- 故障应用在**确定的包边界/config 边界原子生效**：一个包槽位要么完全是故障后形态、要么完全是 baseline 形态，不存在半个故障的包。
- `FAILED` 覆盖 prepare 后至 run 结束间的故障执行失败。

### 8.2 mutation log（evidence locator）

每次实际变换写一条 mutation log 记录（kind=log artifact，SPEC-203 §5.2）：

- `fault_id` / `fault_type` / `target`（node_id+pid 寻址）；
- 注入点：共用 frame 的 packet index；
- before/after 包摘要：变换前后该槽位包的字节摘要（如 header 关键字段 + CRC/CC 差异描述），足以离线复核；
- run_id / artifact 引用（generated_ts 与 faulted_ts 双引用）；
- 生效参数快照与 `parameters_schema_version`。

该记录即 AC-204-04 的 evidence locator：从 fault 事件可直达 log，从 log 可直达两条流的同一槽位。

## 9. 事件引用

`fault.*` 四事件走 ADR-0006 信封（引用，不另立新类型）：scope.run_id 归属、correlation `node_id + pid` 寻址、payload 携带 fault_id/fault_type/注入 index/before-after 摘要指针。payload schema 随实现按 SPEC-301 §7 注册。

## 10. 安全边界

**MVP 故障只应用于本地生成的合成码流**，不应用于直播流、真实 DVB 硬件或用户上传的非沙盘来源（传输级 TSDuck 路由未来启用时同样受此约束）。payload/日志/mutation log 禁含密钥（BISS 等，roadmap 域）。

## 11. 错误与诊断码

| Code | 条件 | 处理 |
|---|---|---|
| `SIM_FAULT_UNKNOWN_TYPE` | fault_type 不在注册表 | prepare 拒绝 |
| `SIM_FAULT_PARAM_INVALID` | 参数越界/缺键/未知键 | prepare 拒绝，附 schema path |
| `SIM_FAULT_EXPECTED_OBS_MISSING` | expected_observations 缺失/空 | prepare 拒绝 |
| `SIM_FAULT_TARGET_INVALID` | target_id 无法解析 / wrong_pmt_pid 非法 | prepare 拒绝 |
| `SIM_FAULT_ACTIVATION_OUT_OF_RANGE` | packet_index 超出产物 frame | prepare 拒绝（长度在 prepare 可预算时）或 run 期诊断 |
| `SIM_FAULT_EXEC_FAILED` | run 期变换异常 | 故障态 FAILED，Run 按 SPEC-203 语义处理 |

## 12. 测试规格

- 四类故障逐一：faulted 流 `packet_count == baseline packet_count` 且逐槽位 diff 仅含声明的变换。
- PAT_MISSING：窗口内 PID 0 无 PAT、Null 包占位、窗口后 CC 重盖无次生 CC 错误、PCR 不丢。
- CC_DISCONTINUITY：落点跳过 adaptation-only、delta 回绕（(15+3) mod 16 类）、偏移持续性。
- PMT_PID_MISMATCH：PAT CRC 重算合法、三症状齐备、wrong_pmt_pid 非法值全部拒绝。
- 确定性：同 seed/config/plan 复现逐字节一致（含 mutation log）。
- 等位替换：baseline 与 faulted 的 index 对齐扫描（全流逐槽位）。
- 生命周期事件序：injected → activated → applied → cleared 与 mutation log 记录一一对应。
- 安全：prepare 拒绝的全部负向样例（第 11 节逐码）。

## 13. 验收标准

- `REQ-SIM-204-001`：prepare 阶段完成全部校验（类型/参数/target/activation/expected_observations），session 变异前拒绝。
- `REQ-SIM-204-002`：同 seed/config/schedule 复现逐字节一致。
- `REQ-SIM-204-003`：L1 故障改变 faulted artifact 哈希且与 baseline 不同。
- `REQ-SIM-204-004`：每个已应用故障都有 fault 事件 + mutation log evidence locator。
- `REQ-SIM-204-005`：等位替换不变式成立（CBR、188、共用包序 frame）。
- `REQ-SIM-204-006`：无 UI-only 故障——每个故障都有字节/状态级可验证效应。
- `REQ-SIM-204-007`：packet-index 注入在共用 frame 上稳定（AC-204-07 冻结定义）。
- `REQ-SIM-204-008`：四类故障语义与版本化参数表按第 6 节实现，单一可归因症状经诊断复归测试（与 SPEC-306 联测时验证）。

## 14. 非目标与风险

- 不含插入/删除型故障（准入约束第 7 节第 4 条）。
- 不承诺传输级路由的 MVP 可用性。
- 风险：PMT_INVALID_CRC 的 persistent 默认值在长流中会持续产生 CRC 事件——靶场场景以窗口/activation 控制；观测风暴由 SPEC-301 §5 合并限流兜底。
- 风险：expected_observations 的"事件码 + 定位"目前是字符串契约，结构化 schema 随 SPEC-306/307（#13）细化时不得破坏本 spec 的必填语义。

## 15. 交付要求

建议文件：`app/faults/`（registry.py / filters/ 每类一个过滤器 / mutation_log.py）；测试置于 `tests/unit/faults/` 与 `tests/integration/faults/`。golden 故障向量归 [golden streams 与 conformance 策略](https://github.com/BingChaoLiu/DVB-Nexus/issues/14)。

## 16. 参考

- ADR-0007（全部条款）、ADR-0006 第 3/5 条（寻址、事件注册表）。
- SPEC-100 §5.4 CCAllocator（reset 语义）、SPEC-103 PAT/PMT、SPEC-106 Packetizer。
- CONTEXT.md「故障双路由」「等位替换」词条。

## Phase 2 定点修订（随落笔票 #117，DRAFT_FOR_REVIEW 0.6.0；依据：细裁 [#111](https://github.com/BingChaoLiu/DVB-Nexus/issues/111)，[ADR-0010](../../../../../docs/adr/0010-phase2-t2mi-integration-path.md)/[ADR-0011](../../../../../docs/adr/0011-biss-scramble-path.md)）

- **FaultDefinition 增 `layer` 属性**：{TS, BBFRAME, T2MI, BISS}，默认 "TS"（MVP 四原语全为 TS，序列化/指纹 additive 兼容）；runtime 据此路由到对应层过滤器实例（分层流水线）。
- **注册表新增四原语**（MVP「基线冻结不扩容」纪律的 Phase 2 显式扩容口）：
  1. `T2MI_PLP_MISMATCH`（T2MI 层）：expected_plp/actual_plp 错位对 + plp_version_switch；activation session_start（默认）| packet_index。
  2. `BBHEADER_SYNC_FAULT`（BBFRAME 层）：field（MATYPE/UPL/DFL/SYNC/SYNCD/CRC-8）+ mode（corrupt|shift）；activation packet_index。
  3. `BISS_KEY_MISMATCH`（BISS 层）：wrong_session_word | wrong_esw/injected_id 变体 + pid_scope；activation session_start。
  4. `PMT_PID_DRIFT`（TS/PMT 层）：new_pid_map + pmt_version_bump；activation packet_index——C2 的 TS 层等价（CA 全貌属 SPEC-612，诚实标注）。
- **等位替换不变式逐层保持**：每层过滤器长度/包序不变，CBR 在 TS 层与 Inner TS 层各自成立；tee 双写 artifact 面维持最外层，中间层证据走 mutation log（含密钥指纹——密钥本体不落）。
- **加扰器过滤器类型**：filters 族新增 scrambler（构造特性与 fault 注入共用，密钥来源不同——[ADR-0011](../../../../../docs/adr/0011-biss-scramble-path.md)）。
- 四原语的 expected_observations 符号名引用观测注册表（事件定义见 SPEC-303/304 与 ADR-0006 关联面同批修订）。
