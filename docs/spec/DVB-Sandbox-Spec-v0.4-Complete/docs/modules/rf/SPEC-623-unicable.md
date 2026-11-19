---
spec_id: SPEC-623
title: Unicable（EN 50494/EN 50607 槽位与调谐模型）
version: 0.6.0
status: APPROVED
phase: P3
owner: RF
priority: P2
depends_on: [SPEC-622, SPEC-620, SPEC-003, SPEC-202, SPEC-301]
requirements: [REQ-UNI-623-001, REQ-UNI-623-002, REQ-UNI-623-003, REQ-UNI-623-004, REQ-UNI-623-005]
---

# SPEC-623 — Unicable（EN 50494/EN 50607 槽位与调谐模型）

## 1. 目标

定义 SCR/dCSS（Unicable I/II）的**调谐消息位布局、UB 分配结构语义与 UB 冲突判定**（Phase 3 RF/SEC 沙盘，roadmap §2）：A1 靶场（UB 槽位冲突 → SCR 堆叠互扰 → 无法锁定）的域模型。**条款号纪律**：EN 50494:2007 / EN 50607:2015 正文付费（roadmap §5 既记）——本规格位布局/公式标注「四实现源码级共识」（[#145](https://github.com/BingChaoLiu/DVB-Nexus/issues/145)：tvheadend/VDR/MuMuDVB/minisatip 交叉验证一致），**条款号归属一律不写、缺口清单诚实留档**。消费方 = SPEC-620（ub_slot 有效性/冲突判定的 lock 求值输入）、SPEC-204（SEC 层原语 `UB_SLOT_CONFLICT`）、SPEC-307（UB_CONFLICT_SUSPECT 输入面）、SPEC-305（查询面）。

依据：roadmap §2/§5；[细裁 #150](https://github.com/BingChaoLiu/DVB-Nexus/issues/150)（切分与最小面）、[#148](https://github.com/BingChaoLiu/DVB-Nexus/issues/148)（ub_assignments/ub_slot config 词汇、SIM_TOPO_UB_*）、[#147](https://github.com/BingChaoLiu/DVB-Nexus/issues/147)（L0 形态）、[#151](https://github.com/BingChaoLiu/DVB-Nexus/issues/151)（原语）、[#152](https://github.com/BingChaoLiu/DVB-Nexus/issues/152)（事件面）；研究证据 research/unicable-scr-dcss 分支（#145）（#145：kernel 无 SCR 属性 → 用户态消息构造层、四实现位级共识、UB 冲突 = 堆叠层共享资源冲突）。

## 2. 范围

### 2.1 In Scope

- **协议变体**：`protocol` ∈ {EN50494, EN50607}——EN 50494（Unicable I / SCR，UB 3bit→8 槽，Position 1bit A/B，t 10bit）；EN 50607（dCSS/Unicable II，UB 5bit→32 槽，Position 6bit→64，t 11bit）。
- **调谐消息位布局**（normative，§6 表：标注「四实现源码级共识」，条款号待原文核对）：EN 50494 帧 `[0xE0,0x10,0x5A,d1,d2]`（复用 SPEC-622 DiSEqC 框架，PIN/multihome 变体命令字节 0x5C + PIN 字节）；EN 50607 帧 `[0x70,d1,d2,d3]`（独立帧字节 0x70/0x71，不经 DiSEqC 框架，PIN 变体帧字节 0x71）。
- **频率公式**（normative）：EN 50494 `t = round((f_IF + f_UB + 2)/4) − 350`（接收端前端调 (t+350)×4 − f_IF ≈ f_UB + 2 MHz）；EN 50607 `t = f_IF − 100`（前端精确调 f_UB）。
- **UB 分配结构语义**：`ub_assignments`（#148 config 词汇的结构定义落此）——lnb（内置 SCR）config 携 {tuner → {ub_slot, ub_center_freq_mhz, position, pin?}}；tuner config `ub_slot` 引用。
- **UB 冲突判定语义**：同一 UB 同一时间只堆叠一路 transponder（SCR 动作 = 选择 transponder 并变频到 UB 中心堆叠，[#145](https://github.com/BingChaoLiu/DVB-Nexus/issues/145) Inverto 引文）；双 tuner 同 UB = 堆叠互扰 → tuner lock 失败 + CauseRef 冲突对。
- `protocol` 参数面（[#145](https://github.com/BingChaoLiu/DVB-Nexus/issues/145) §7 建议）：ub_slot（I 0–7 / II 0–31）、position（I {A,B} / II 0–63）、polarization、band、ub_center_freq_mhz、ub_bandwidth_mhz（默认 46，可编程 10–80，Inverto 手册）、pin（multihome 变体）。

### 2.2 Out of Scope

- DiSEqC 1.x 命令帧词汇本身（SPEC-622；本规格复用不重定义）。
- 静态 UB 一致性校验的实现（validator 规则 `SIM_TOPO_UB_*` 归 SPEC-003 修订，[#148]；成文归 #156）。
- 运行期 UB 错配注入（`UB_SLOT_CONFLICT` 原语语义归 SPEC-204 / [#151](https://github.com/BingChaoLiu/DVB-Nexus/issues/151)）。
- 硬件调谐/时序过程仿真（时序界仅参考表）；SAT>IP（网络域出界，[#150](https://github.com/BingChaoLiu/DVB-Nexus/issues/150) Q6）；JESS 命名展开（「EN 50607 aka JESS」口径以 VDR 实现注释为最强证据，[#145]）。
- LNB 本振/供电域（SPEC-621）。

## 3. 术语

| 术语 | 定义 |
|---|---|
| SCR | Satellite Channel Router（EN 50494；**非**"Subscriber Channel Radio"，roadmap §4 订正口径）——按接收端命令将 transponder 变频到 UB 频率堆叠的设备侧路由器 |
| dCSS | Digital Channel Stacking Service（EN 50607 / Unicable II），32 UB / 64 position |
| User Band（UB） | SCR 分配给单个接收端的频率槽位；带宽默认 46 MHz、可编程 10–80 MHz（Inverto 手册，[#145](https://github.com/BingChaoLiu/DVB-Nexus/issues/145)） |
| UB 冲突（堆叠互扰） | 双接收端请求同一 UB → SCR 在同一频槽堆叠两路信号互扰 → 无法锁定；冲突发生在 SCR 堆叠层，与 LNB 本振无关（A1 订正口径，roadmap §4） |
| f_IF / f_UB / t | transponder 变频后中频 / UB 槽位中心频率 / 消息频率字段（记号随 [#145](https://github.com/BingChaoLiu/DVB-Nexus/issues/145) §2） |
| 四实现源码级共识 | tvheadend `linuxdvb_en50494.c` / VDR `diseqc.c` / MuMuDVB `tune.c` / minisatip `dvb.cpp` 逐行核对一致的位布局与公式——**非标准正文断言**，条款号待原文核对 |
| 实现分歧 | EN 50494 接收端调谐频率：三家 `(t+350)×4 − f_IF ≈ f_UB + 2 MHz`，minisatip 直接调 f_UB（[#145](https://github.com/BingChaoLiu/DVB-Nexus/issues/145) §2.4 诚实记录）——本规格取多数派并标注分歧 |

## 4. 架构

- 语义层用户态消息构造（[#145](https://github.com/BingChaoLiu/DVB-Nexus/issues/145) 结论 1：kernel 无任何 Unicable/SCR 属性——Unicable 是用户态消息构造层，为 SPEC-622（原语层）/623（消息+UB 管理层）分层提供生态既成依据）。
- `ub_assignments` 为 lnb（内置 SCR）config 结构段（#148 词汇归 SPEC-003 修订，结构定义落本规格 §5）；tuner 经 `ub_slot` 引用。
- UB 冲突判定为 **L0 求值语义**（SPEC-620 tuner_evaluator 消费）：冲突 = 可判定结构事实（双 tuner 指向同 ub_slot），非数值仿真；CauseRef 冲突对复用 SPEC-202 既有因果链。
- 事件面：UB 表与调谐状态经 `sec.state_observed` payload 携带（[#152](https://github.com/BingChaoLiu/DVB-Nexus/issues/152)）；来源 = `state_evaluator`、置信度 = simulated。
- fault 挂钩：`UB_SLOT_CONFLICT`（SPEC-204，[#151](https://github.com/BingChaoLiu/DVB-Nexus/issues/151)）经求值前纯变换改写 tuner 的 ub_slot——基线拓扑静态合法（SIM_TOPO_UB_*），错配仅 fault plan 期生效。
- `SPEC-623 depends_on SPEC-622`（[#150](https://github.com/BingChaoLiu/DVB-Nexus/issues/150) Q5：调谐消息复用 framing 族）；依赖方向遵守 ADR-0005。

## 5. 数据模型

- `UbAssignmentDTO`（wire snake_case，lnb.scr 子段结构）：`tuner_node` / `ub_slot`（I 0–7 / II 0–31）/ `ub_center_freq_mhz` / `position`（I {A,B} / II 0–63）/ `pin`（可选，multihome 变体）/ `ub_bandwidth_mhz`（默认 46）。
- `ScrConfigDTO`（lnb config `scr` 子段）：`protocol` ∈ {EN50494, EN50607} / `ub_assignments`（列表）/ 默认 UB 频率组参考值（厂商常见 1210/1420/1680/2040 MHz——Inverto 手册，非 normative）。
- `TunerConfigDTO.ub_slot`（SPEC-620 引用）：本规格定义其引用语义 = 必须命中本拓扑 SCR 的 ub_assignments 表项。
- metrics 键（`sec.state_observed`，[#152](https://github.com/BingChaoLiu/DVB-Nexus/issues/152)）：`ub_assignments`（表快照）、`tuning_message`（{protocol, frame_bytes, t}——终态构造产物）。
- **时序界参考表**（不进求值）：powerup 4–22 ms / settle 2–60 ms / 重复退避 68–118 ms（[#145](https://github.com/BingChaoLiu/DVB-Nexus/issues/145)：tvheadend「standard:」注释 + MuMuDVB AN2056 引注，条款号待原文核对）。

## 6. 公开接口（接口级契约）

- **调谐消息位布局表**（normative，四实现源码级共识；条款号待原文核对）：
  - EN 50494（ODU_channel_change）：`[0xE0, 0x10, 0x5A, data1, data2]`——data1 含 UB 3bit（0–7）/ Position 1bit（A/B）/ 极化 1bit / 频段 1bit，data1 剩余位 + data2 = t 10bit；PIN（multihome）变体 = 6 字节、命令字节 0x5C、追加 PIN（0–255）。
  - EN 50607（dCSS）：`[0x70, data1, data2, data3]`——data1 bit7–3 = UB 5bit（0–31→32 UB）、data1 bit2–0 + data2 bit7–0 = t 11bit（1 MHz 分辨率）、data3 bit7–2 = position 6bit（0–63）；PIN 变体帧字节 0x71、5 字节。
- **频率公式**（normative）：EN 50494 `t = round((f_IF + f_UB + 2)/4) − 350`；EN 50607 `t = f_IF − 100`；接收端前端调谐频率语义随 [#145](https://github.com/BingChaoLiu/DVB-Nexus/issues/145) §2.4 分歧记录取多数派（≈ f_UB + 2 MHz / 精确 f_UB）。
- **冲突判定纯函数**：`ub_conflicts(ub_assignments, tuner_configs) -> [(tuner_a, tuner_b, ub_slot)]`——同 protocol 同 SCR 内双 tuner 同 ub_slot = 冲突对；供 SPEC-620 lock 求值与 `SIM_TOPO_UB_*` 静态校验共用。
- **调谐消息构造纯函数**：`(protocol, ub_assignment, tuning_request) -> tuning_message`（终态构造产物，确定性）。
- REST/WS 无新增端点（SPEC-305 查询面承载）。

## 7. 处理算法（接口级行为义务）

- **消息构造确定性**：同 (protocol, assignment, tuning_request) → 同 frame_bytes（§6 位布局逐字段）。
- **冲突判定确定性**：结构事实判定，零数值仿真；EN 50494 与 EN 50607 的 UB 空间独立（同 lnb 混两协议 = prepare 拒绝）。
- **静态/运行期分层**：配置期冲突 = `SIM_TOPO_UB_*` violation（prepare 拒绝，[#148](https://github.com/BingChaoLiu/DVB-Nexus/issues/148)）；运行期错配 = `UB_SLOT_CONFLICT` fault 变换（[#151](https://github.com/BingChaoLiu/DVB-Nexus/issues/151)）——基线永远合法。
- **framing 复用**：EN 50494 帧复用 SPEC-622 DiSEqC 框架词汇（0xE0/0xE1/0x10）；EN 50607 帧字节 0x70/0x71 不属 DiSEqC 1.x/2.x 框架——发送面（kernel `FE_DISEQC_SEND_MASTER_CMD` 3–6 字节上限兼容两者）记为参考，沙盘内仅消息构造。

## 8. 错误处理

| 场景 | 处理 |
|---|---|
| ub_assignments 引用不存在的 tuner 节点 / tuner.ub_slot 未命中表 | prepare 拒绝（SIM_TOPO_UB_* 族） |
| 双 tuner 同 ub_slot（配置期静态） | prepare 拒绝（A1 的错配走 fault plan，不走基线） |
| 同 lnb 混用 EN50494/EN50607 | prepare 拒绝 |
| ub_slot 超出 protocol 位宽（I >7 / II >31） | prepare 拒绝 |
| t 字段溢出（I >1023 / II >2047） | prepare 拒绝（频率字段超域） |
| 求值器内部异常 | `SIM_EVAL_NODE_FAILED` 节点级隔离（SPEC-202 §8） |

## 9. 资源约束

- L0 求值复杂度上界：单节点 O(UB 数)；全拓扑（≤100 节点）单遍 ≤1ms 量级（[#147](https://github.com/BingChaoLiu/DVB-Nexus/issues/147) Q7）。
- 无新增运行时依赖；TSDuck `dvb --unicable` 参数面仅第三意见参照（[#145](https://github.com/BingChaoLiu/DVB-Nexus/issues/145) 结论 5），不进运行时/验证链。

## 10. 依赖

| 依赖 | 性质 | 消费点 |
|---|---|---|
| SPEC-622 | framing/命令词汇 | EN 50494 帧复用 DiSEqC 框架 |
| SPEC-620 | 下游消费 | ub_slot 有效性/冲突判定的 lock 求值输入 |
| SPEC-003 §2.4 / §6 + 修订 | config 词汇/来源枚举/平面启用/SIM_TOPO_UB_* | 结构接线（成文归 #156） |
| SPEC-202 §6 | 冻结求值接口 | 消息构造/冲突判定纯函数挂载 |
| SPEC-301 + ADR-0006 | 事件信封 | sec.* payload 携带（[#152](https://github.com/BingChaoLiu/DVB-Nexus/issues/152)） |
| SPEC-204（#151 修订后） | 作用层路由 | UB_SLOT_CONFLICT 求值前变换 |
| #145 findings 分支 | 向量素材 | 位布局/公式/时序界/UB 带宽（四实现共识 + Inverto 手册） |
| EN 50494:2007 / EN 50607:2015 | 标准权威 | **正文付费未得**——条款号缺口清单见 [#145](https://github.com/BingChaoLiu/DVB-Nexus/issues/145) §6（11 项），全部「待原文核对」 |

## 11. 测试向量

### 11.1 golden 计划（状态域）

- 位布局逐字段用例：EN 50494 / EN 50607 各 1 组（UB/Position/极化/频段/t 逐位断言）+ PIN 变体（0x5C/0x71）。
- 频率公式用例：EN 50494（含 +2/−350 常数路径）、EN 50607（f_IF − 100）；数值示例随向量钉扎。
- 冲突判定：双 tuner 同 UB → 冲突对；异 UB → 空；跨 protocol → prepare 拒绝。
- A1 症状链：`UB_SLOT_CONFLICT` 注入 → tuner unlocked + CauseRef 冲突对（与 SPEC-620 AC-620-05 端到端串联）。
- UB 带宽/默认频率组参考值用例（非 normative 断言，形状断言）。

### 11.2 独立验证

- 位布局/公式的独立基准 = #145 四实现源码级共识（先于实现钉扎）；同输入双跑逐字节一致（确定性复现纪律）。

### 11.3 性能基准

- 全拓扑求值耗时进实现票验收（tests/README §6 纪律）。

## 12. 验收标准

- AC-623-01：两协议位布局逐字段断言全绿（含 PIN 变体）。
- AC-623-02：频率公式逐条断言（数值示例随向量钉扎，不钉环境字面值）。
- AC-623-03：冲突判定三支路（冲突/无冲突/跨协议拒绝）。
- AC-623-04：静态/运行期分层——基线拓扑冲突 prepare 拒绝；fault 错配仅 plan 期生效。
- AC-623-05：条款号缺口清单随规格留档（无任何编造条款号）。
- AC-623-06：确定性复现——同 config + fault plan 双跑逐字节一致。

## 13. 非目标与风险

- 付费标准正文未核：位布局/公式为四实现共识（高置信但**非标准正文断言**）——若未来获得原文且发现分歧，按原文修订本规格（版本递增）。
- SAT>IP `uni` 参数（v1.4+）出界待原文核对；「GSet」品牌无法核实（[#145](https://github.com/BingChaoLiu/DVB-Nexus/issues/145) §0.7 诚实记录）。

## 14. 交付要求

- 实现落位 src/simulation/state/evaluators/（消息构造/冲突判定纯函数与 SPEC-620 同包族）；DTO 生成链权威 SPEC-500。
- 本规格 APPROVED 为 M7 开工前置。

## 15. 参考

- roadmap §2/§4（A1 订正口径）/§5（付费标准既记）；#145 findings（research/unicable-scr-dcss 分支，含 §6 条款号缺口清单 11 项）；#147/#148/#150/#151/#152 决议；SPEC-622（framing 词汇）。
- tvheadend / VDR / MuMuDVB / minisatip（四实现源码级共识基准）；Inverto Unicable II 手册（UB 带宽/默认频率组/堆叠动作）；SAT>IP v1.2.2（免费规范文本）。
