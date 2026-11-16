---
spec_id: SPEC-603
title: Inner TS Reconstruction（Inner TS 重建）
version: 0.5.1
status: APPROVED
phase: P2
owner: T2MI
priority: P2
depends_on: [SPEC-600, SPEC-601, SPEC-602, SPEC-100]
requirements: [REQ-603-001, REQ-603-002, REQ-603-003, REQ-603-004]
---

# SPEC-603 — Inner TS Reconstruction（Inner TS 重建）

## 1. 目标

定义 **BBFrame UP 拼装 → Inner TS 字节流重建**的接口与验证协议：三级解封装链（外层 TS Packet → BBFrame → Inner TS，roadmap §4 B1 已核实形态）的输出端。输出对齐 SPEC-100 PacketSource 消费面（analyze/inspect 既有管线），并提供与 TSDuck 第二意见对拍的验证协议（#108 裁决）。

依据：[#104](https://github.com/BingChaoLiu/DVB-Nexus/issues/104)（HEM 逐字节确定 + 背靠背纪律 + Worker 内容校验义务）、[#105](https://github.com/BingChaoLiu/DVB-Nexus/issues/105)（多 UP 尾包缺陷 + expected_inner.ts 基准）、[#107](https://github.com/BingChaoLiu/DVB-Nexus/issues/107)（SYNCD carry-over 语义佐证）。

## 2. 范围

### 2.1 In Scope

- UP 拼装：SYNCD 位距跨帧 carry-over、UP 序列重组、stuffing 处理。
- Inner TS 输出：188 对齐字节流，接 SPEC-100 既有 analyze/inspect 消费面（artifact kind 语义延伸）。
- 重建失败证据面：`bbframe.recovery_failed`（SPEC-601）与 Inner TS 层缺失证据的关联定位。
- TSDuck 第二意见对拍协议（升级复测前置）与 crate 开发期 oracle 用法。
- fault 链接：TS 层原语在重建输出段实例化（#108 分层流水线的 Inner TS 段）。

### 2.2 Out of Scope

- T2-MI 包解析/BBFrame 解析本体（SPEC-600/601）；PLP 过滤（SPEC-602）；加扰面（SPEC-610/611）；前端渲染（SPEC-404 修订面，#119）。

## 3. 术语

| 术语 | 定义 |
|---|---|
| Inner TS | 三级封装的最内层 MPEG-TS 流（八步闭环的既有语义层域） |
| SYNCD carry-over | UP 边界跨 BBFrame 的位距累计（重建正确性核心） |
| 重建失败 | CRC-8/SYNCD/DFL 级联导致的 UP 边界不可定——显式证据态，非静默截断 |
| 第二意见验证器 | TSDuck `tsp -P t2mi --extract`（#108 Q1 收窄角色；前置 = 版本复测通过） |

## 4. 架构

- 解封装方向完整链：外层 TS（mux 输出 artifact）→ SPEC-600 解析 → SPEC-601 解析 → SPEC-602 过滤 → **本规格重建** → Inner TS（PacketSource）。
- Inner TS 段 fault 过滤器：TS 层原语（layer="TS"，#111 默认）作用于重建输出，等位替换不变式在此层成立（CBR/同 index 同包数）。
- 事件：复用 bbframe.*/t2mi.*（#113）；Inner TS 层无新命名空间（回到既有 TS 语义域）。

## 5. 数据模型

- `InnerTsResultDTO`：`artifact_ref / packet_count / up_assembled / stuffing_bytes / reconstruction_status（ok | partial | failed） / first_failure_ref`。
- artifact kind 语义延伸：`inner_ts`（新增 kind，外层 `faulted_ts`/`generated_ts` 语义不变）——content-addressed 归 SPEC-503 机制。

## 6. 公开接口（接口级契约）

- `reconstruct(frames, plp_filter) -> InnerTsResultDTO`：确定性；partial/failed 显式态（§8）。
- artifact 落地：重建输出入 SPEC-503 内容寻址存储（kind=inner_ts）。
- 对拍协议：`verify_against_tsduck(inner_artifact, tsduck_extract_output)`——逐字节 diff，结果进 L2 独立验证记录（SPEC-506 机制）。

## 7. 处理算法（接口级行为义务）

- 拼装确定性：同 BBFrame 序列 → 同 Inner TS 字节流。
- 背靠背纪律消费端镜像：解析侧遇段间 padding T2-MI 包 → 显式异常证据（构造侧禁止，#104 实测 demux 停摆形态）。
- 部分重建：失败点之后的 UP 显式 partial（first_failure_ref 定位），不静默截断——Worker/消费方必须内容校验（#104 教训的契约化）。
- fault 注入语义：重建输出段 = TS 层过滤器挂载点；faulted run 双写维持外层 artifact（#108）。

## 8. 错误处理

| 场景 | 处理 |
|---|---|
| UP 边界不可定（SYNCD 越界/CRC-8 连锁失败） | reconstruction_status=partial/failed + first_failure_ref；bbframe.recovery_failed 计数（#113） |
| PLP 过滤后业务缺失（B1 形态） | 显式空输出 + t2mi.plp_mismatch 候选（SPEC-602 承接） |
| 段间 padding 发现 | 显式异常证据（纪律违反态） |
| TSDuck 对拍前置未满足 | L2 记录标注 NOT TRUSTED（版本已知缺陷，#104/#105） |

## 9. 资源约束

- 纯 Python；重建吞吐预算并入 SPEC-600 面同口径；artifact 内存预算沿用 SPEC-503/107。

## 10. 依赖

| 依赖 | 性质 | 消费点 |
|---|---|---|
| SPEC-600/601/602 | 解封装链上游 | 输入 |
| SPEC-100 | Inner TS 消费面 | PacketSource/analyze/inspect |
| SPEC-503 | artifact 存储 | kind=inner_ts 内容寻址 |
| SPEC-506 | conformance 机制 | L2 对拍记录 |
| SPEC-305/302 | 观测消费 | 重建证据进指标/诊断 |

## 11. 测试向量

- 正向：完整三级链 round-trip（外层 TS → Inner TS 与原始生成流逐字节一致；#105 expected_inner.ts 基准入册）。
- 负向：CRC-8 连锁失败 partial 态、PLP 缺失空态、padding 纪律违反态、多 UP 尾包形态（#105）。
- 对拍：TSDuck 升级复测通过前全部标注 NOT TRUSTED；通过后进 L2 记录。

## 12. 验收标准

- **AC-603-01**（REQ-001/002）：重建接口在位；确定性 + partial/failed 显式态测试钉扎。
- **AC-603-02**（REQ-003）：完整三级链 round-trip 绿（golden 入 docs/test-vectors/）；artifact kind=inner_ts 落 SPEC-503 机制。
- **AC-603-03**（REQ-004）：B1/B2 场景故障链证据可达包检查器（view=t2mi/bbframe，#114）；对拍协议在位（含 NOT TRUSTED 标注逻辑）。
- **AC-603-04**（全门）：后端三门 + dto 漂移锁绿。

## 13. 非目标

- 外层 TS 传输面（mux/分布网）；物理层；TSDuck 运行时依赖；连续指标流（ts.* 申报 1 口径维持，#113）。

## 14. 兼容性与交付要求

- additive-only（artifact kind 增量、事件零新增）；批准流 DRAFT_FOR_REVIEW → repo 主通读确认 → APPROVED。
- Lab Pack v2（#118）B1/B2 场景与包检查器视图（#119）为本规格的教学消费面；实测性能预算与 golden 入册随实现票。
