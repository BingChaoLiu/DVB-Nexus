---
spec_id: SPEC-600
title: T2MI Parser（T2-MI 包解析与封装）
version: 0.5.1
status: APPROVED
phase: P2
owner: T2MI
priority: P2
depends_on: [SPEC-100, SPEC-107, SPEC-301, SPEC-003]
requirements: [REQ-T2MI-600-001, REQ-T2MI-600-002, REQ-T2MI-600-003, REQ-T2MI-600-004, REQ-T2MI-600-005]
---

# SPEC-600 — T2MI Parser（T2-MI 包解析与封装）

## 1. 目标

定义 T2-MI（DVB-T2 Modulator Interface，TS 102 773 §5.1）**包级解析与封装的双向接口**：Phase 2 分层流水线（[细裁 #108](https://github.com/BingChaoLiu/DVB-Nexus/issues/108) 裁决）的 T2MI 层基础件。**解析（parser）与封装（builder）双向均为必修**（开图既裁：靶场 B1/B2 案例要求构造 T2-MI 形态故障流；[#104](https://github.com/BingChaoLiu/DVB-Nexus/issues/104) 实测证实 TSDuck 无封装能力）。消费方 = SPEC-601/602/603（同链上层/下层）、SPEC-204 故障原语（T2MI 层）、SPEC-403/404 证据呈现。

依据：roadmap §3/§5；[#104](https://github.com/BingChaoLiu/DVB-Nexus/issues/104) TSDuck 实测（解封装 HEM 逐字节确定/封装不能/失败路径全静默）、[#105](https://github.com/BingChaoLiu/DVB-Nexus/issues/105) FFmpeg 证伪与多 UP 尾包坑、[#107](https://github.com/BingChaoLiu/DVB-Nexus/issues/107) crate 复核（不进运行时，开发期 oracle）、[#108](https://github.com/BingChaoLiu/DVB-Nexus/issues/108) 集成路径裁决、[#110](https://github.com/BingChaoLiu/DVB-Nexus/issues/110) 拓扑节点、[#113](https://github.com/BingChaoLiu/DVB-Nexus/issues/113) 观测事件。

## 2. 范围

### 2.1 In Scope

- T2-MI 包结构模型：包头 6 字节 + CRC-32（TS 102 773 §5.1）；packet_type 值域 MVP 子集 = BBFRAME 与 padding 两类（其余类型按标准表注册渐进）。
- 解析接口：字节流 → T2-MI 包序列（确定性、CRC-32 校验结果逐包保留）。
- 封装接口：BBFrame 序列 → T2-MI 包流（确定性、背靠背紧排纪律）。
- `t2mi_encapsulator` / `t2mi_demux` 两类拓扑节点类型的 config schema（[#110](https://github.com/BingChaoLiu/DVB-Nexus/issues/110) 裁决结构）。
- `t2mi.stage_summary` 事件 payload（[#113](https://github.com/BingChaoLiu/DVB-Nexus/issues/113) 裁决命名空间）。
- 与 fault 管线的挂钩点（作用层 = T2MI，[#108](https://github.com/BingChaoLiu/DVB-Nexus/issues/108) 分层流水线）。

### 2.2 Out of Scope

- BBFrame 内部结构（SPEC-601）；PLP 过滤/分配语义（SPEC-602）；Inner TS 重建（SPEC-603）。
- DVB-T2 物理层（OFDM/ FEC）——沙盘全程不到射频（Phase 3 才涉 RF 面）。
- TSDuck/外部工具的运行时集成（TSDuck 仅第二意见验证器角色，归 SPEC-603 验证协议）。

## 3. 术语

| 术语 | 定义 |
|---|---|
| T2-MI 包 | TS 102 773 §5.1 定义的封装单元：包头（6 字节）+ payload + CRC-32 |
| 分层流水线 | Inner TS → BBFrame → T2-MI → 外层 mux 的逐层「生成→过滤→封装」管线（#108 裁决） |
| 背靠背紧排 | T2-MI 包连续排布、不在 BBFRAME 序列间插入 padding 包的封装纪律（#104 实测：padding 分隔使下游 demux 永久停摆） |
| 作用层（layer） | FaultDefinition 新增属性 {TS, BBFRAME, T2MI, BISS}，路由到对应层过滤器（#111 裁决） |
| 第二意见验证器 | TSDuck `tsp -P t2mi` 降级角色：交叉验证自研输出，不承担主路径（#108 Q1 裁决） |

## 4. 架构

- 落位语义层包族（#108 Q2：与 TS Core 同族、位级工具复用 SPEC-100 既有 bytesutil/crc）；依赖方向遵守 ADR-0005（不反向依赖 simulation/faults）。
- fault 过滤器按层实例化（#108 Q3）：T2MI 层过滤器操作 T2-MI 包流，接口对齐 ADR-0007 `apply(index, packet)` 契约；封装器在过滤器下游。
- 观测事件经进程内桥进信封（SPEC-301 权威，ADR-0006 注册表 additive）。
- 节点类型经 NodeType 注册表机制接入拓扑（SPEC-003 §6），前端零特制（#110）。

## 5. 数据模型

- `T2miPacketDTO`（wire snake_case，生成链权威 SPEC-500）：`packet_type / packet_counter / payload_kind / payload_bytes_len / crc32_valid`；字节内容不进 DTO（artifact 寻址）。
- `T2miDemuxConfigDTO`（t2mi_demux 节点 config）：`expected_plp / plp_mode / strict_crc`。
- `T2miEncapsulatorConfigDTO`（t2mi_encapsulator 节点 config）：`plp_assignment`（SPEC-602）+ `bbframe_params`（SPEC-601：MATYPE/UPL/N_UPS 等）。
- 字段级位布局（包头逐字段）由 golden 向量钉扎（§11），规格文本不重复标准原文。

## 6. 公开接口（接口级契约）

- `t2mi.parse(stream) -> Sequence[T2miPacket]`：CRC-32 逐包校验、结果保留不截断（坏包显式标记，§8）。
- `t2mi.build(bbframes, config) -> Sequence[T2miPacket]`：确定性输出；同 config 同输入必同输出。
- 事件发射：`t2mi.stage_summary`（per Run 完成时：包数/padding 数/包类型分布/PLP 分布摘要，[#113](https://github.com/BingChaoLiu/DVB-Nexus/issues/113)）。
- REST/WS 面无新增端点（事件走既有 journal；artifact 走既有存储）。

## 7. 处理算法（接口级行为义务）

- 解析确定性：同输入字节流 → 同包序列（含坏包标记位置）。
- 封装确定性：同 BBFrame 序列 + 同 config → 同 T2-MI 包流（packet_counter 连续、背靠背紧排、padding 仅限流尾补齐）。
- fault 挂钩：T2MI 层 FaultDefinition 在本层过滤器实例化；等位替换不变式逐层保持（同 index 同包数，[#111](https://github.com/BingChaoLiu/DVB-Nexus/issues/111)）。

## 8. 错误处理

| 场景 | 处理 |
|---|---|
| CRC-32 校验失败 | 显式标记坏包（crc32_valid=false）继续解析；不静默丢弃——对照 TSDuck 3.45 静默失败教训（#104） |
| packet_type 未知值 | 显式未知类型态（非报错堆栈），注册表渐进支持 |
| 流截断/非整包尾 | 显式 truncation 态 |
| 封装入参 BBFrame 序列含非 188 倍数段 | prepare 前拒绝（对齐 AC-204-01 session 变异前拒绝纪律） |
| stuffing 纪律违反（构造侧试图插入段间 padding） | 构造期拒绝——背靠背紧排是正确性要求不是优化 |

## 9. 资源约束

- 纯 Python 自研（#108 Q1 裁决）；性能预算：外层 T2-MI 处理吞吐 ≥ 场景码流上限（MVP envelope 1~100Mbps 量级，Python 余量 164 倍先例 #5）；实现期以 benchmark 验收（§11.3）。
- 无新增运行时依赖；dvb-t2mi crate 不进运行时/CI（#107 裁决，开发期 oracle）。
- 内存上限沿用 SPEC-107/200 既有 artifact 预算。

## 10. 依赖

| 依赖 | 性质 | 消费点 |
|---|---|---|
| SPEC-100（TS Core 语义层） | 位级工具/包模型先例 | bytesutil/crc 复用 |
| SPEC-107（Generator）/SPEC-200（仿真运行时） | 管线契约 | prepare/run/sink、分层流水线（#108） |
| SPEC-301（事件信封）+ ADR-0006 | 事件注册表 | t2mi.* 命名空间 additive |
| SPEC-003 §6（NodeType 注册表） | 拓扑机制 | 两类节点接入 |
| SPEC-204（故障契约，#111 修订后） | 作用层路由 | T2MI 层原语 |
| TS 102 773 §5.1 | 标准权威 | 包结构/字段值域 |
| #104/#105 样流底座（research 分支） | 向量素材 | §11 golden 输入 |

## 11. 测试向量

### 11.1 golden 计划（L1 优先，照 SPEC-506 三层来源）

- 正向：最小合法 T2-MI 流（#104 `gen_t2mi.py` 底座）→ 解析 round-trip；封装确定性对拍（同 config 双跑逐字节一致）。
- 负向：CRC-32 位翻转（#104 `corrupt_patch.py`）、packet_type 未知值、截断流。
- 多 UP 尾包用例（#105 发现的 TSDuck 3.45 缺陷形态）进负向集。

### 11.2 对拍协议（L2 独立验证）

- TSDuck 第二意见：`tsp -P t2mi --extract` 对拍——**前置条件 = 升级到含 master 147deab3 修复的发布版并复测 NM/ISSY/NPD 与多 UP 尾包**（#104/#105 裁决输入）；未升级前 TSDuck 对拍结果标注「验证器版本已知缺陷，NOT TRUSTED」。
- dvb-t2mi crate：开发期本地 golden diff（cargo 构建产物 stdout），不进 CI（#107）。

### 11.3 性能基准

- 外层封装+解析吞吐 benchmark 进实现票验收（不钉环境字面值，tests/README §6 纪律）。

## 12. 验收标准

- **AC-600-01**（REQ-001/002）：解析/封装双向接口在位，确定性义务有测试钉扎。
- **AC-600-02**（REQ-003）：CRC-32 显式校验与坏包标记；静默丢弃为零（代码审查项）。
- **AC-600-03**（REQ-004）：两类节点 config schema 经注册表接入，E2E 从场景开局到 T2-MI 流产出全链绿。
- **AC-600-04**（REQ-005）：t2mi.stage_summary 事件入注册表并 per Run 发射。
- **AC-600-05**（全门）：后端三门（pytest 必绿组合/lint-imports/check_specs）+ dto 漂移锁绿。

## 13. 非目标

- BBFrame/PLP/Inner TS（同链其他 SPEC）；DVB-T2 物理层与射频面（Phase 3）。
- TSDuck 运行时依赖（第二意见验证器角色，前置复测未过不得信任）。
- BISSL/CA 面（SPEC-610/611/612）。
- 全量 packet 级构造事件流（#112 已关闭）。

## 14. 兼容性与交付要求

- additive-only：信封注册表新增 t2mi.* 命名空间；NodeType 注册表两新条目；`SignalPlane.T2MI` 平面启用（#110）。
- 批准流：DRAFT_FOR_REVIEW → repo 主通读确认 → APPROVED（Phase 2 地图既裁）。
- 验证层证据：#104/#105/#107 research 分支为本规格依据底档；样流底座转正为 golden 素材随实现票落 docs/test-vectors/（SPEC-506 机制）。
