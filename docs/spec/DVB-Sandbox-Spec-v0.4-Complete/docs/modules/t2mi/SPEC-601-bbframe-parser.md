---
spec_id: SPEC-601
title: BBFrame Parser（BBFrame 解析与封装）
version: 0.5.1
status: APPROVED
phase: P2
owner: T2MI
priority: P2
depends_on: [SPEC-600, SPEC-100]
requirements: [REQ-601-001, REQ-601-002, REQ-601-003, REQ-601-004]
---

# SPEC-601 — BBFrame Parser（BBFrame 解析与封装）

## 1. 目标

定义 BBFrame（BaseBand Frame，EN 302 755 §5.1.7）**解析与封装的双向接口**：T2-MI 包的载荷层次（roadmap §4 B2 订正：BBHEADER 定义在 EN 302 755，TS 102 773 全文不含 BBHEADER）。消费方 = SPEC-600（T2-MI 包化载荷）、SPEC-603（Inner TS 重建）、SPEC-204（B2 原语 BBHEADER_SYNC_FAULT 注入点）。

依据：[#104](https://github.com/BingChaoLiu/DVB-Nexus/issues/104)（TSDuck BBFrame 能力为零且 3.45 连 CRC-8 都不校验——自研实现必须超越该基线）、[#105](https://github.com/BingChaoLiu/DVB-Nexus/issues/105)（多 UP BBFrame N_UPS 尾包缺陷形态）、[#108](https://github.com/BingChaoLiu/DVB-Nexus/issues/108)、[#111](https://github.com/BingChaoLiu/DVB-Nexus/issues/111)。

## 2. 范围

### 2.1 In Scope

- BBHEADER 结构模型：10 字节 = MATYPE(2) / UPL(1) / DFL(2) / SYNC(1) / SYNCD(2) / CRC-8(1)（EN 302 755 §5.1.7）。
- 解析：CRC-8 校验、DFL 数据字段长度、SYNCD 位距定位首 UP、UP 边界切分。
- 封装：HEM（High Efficiency Mode）Normal Mode 子集的 BBFrame 构造（UP 拼装 + stuffing + CRC-8 计算），含多 UP（N_UPS > 1）批量封装。
- ISSY/NPD 支持面（MATYPE ISSYI 位语义照标准；ISSY 字段构造随 golden 渐进钉扎）。
- `bbframe.stage_summary` / `bbframe.recovery_failed` 事件 payload（[#113](https://github.com/BingChaoLiu/DVB-Nexus/issues/113)）。
- BBHEADER_SYNC_FAULT 原语的本层过滤器挂钩（[#111](https://github.com/BingChaoLiu/DVB-Nexus/issues/111)：五字段 corrupt/shift 两模式）。

### 2.2 Out of Scope

- L1 后信令/物理层 FEC/星座映射（不到射频）；SPEC-600 T2-MI 包化；SPEC-602 PLP；SPEC-603 UP 拼装后的 Inner TS 输出。
- FEFC/VCM/ACM 全模式面（golden 渐进，MVP 钉 HEM/NM 常规子集）。

## 3. 术语

| 术语 | 定义 |
|---|---|
| BBHEADER | BBFrame 头，10 字节：MATYPE/UPL/DFL/SYNC/SYNCD/CRC-8（EN 302 755 §5.1.7） |
| SYNCD | 数据字段内首个 UP 的**位距离**——不是同步字节（B2 教学点，包检查器文案直接体现，[#113](https://github.com/BingChaoLiu/DVB-Nexus/issues/113)） |
| UP（User Packet） | 用户包：NM 模式下 188 字节 TS 包 |
| HEM/NM | High Efficiency Mode / Normal Mode（MATYPE 语义） |
| N_UPS | 单 BBFrame 内 UP 数（多 UP 批量；#105 实测 TSDuck 3.45 对 N_UPS=3 尾包丢失） |
| 作用层 BBFRAME | FaultDefinition.layer 取值之一（#111）；连线平面无 BBFrame（#110：节点内部层次） |

## 4. 架构

- 落位同 SPEC-600 包族；上游 = SPEC-603 供给 UP 流（封装方向）或 SPEC-600 供给 T2-MI 包 payload（解析方向）。
- 解析方向链：T2-MI 包（payload=BBFrame）→ 本规格解析 → UP 序列 → SPEC-603 重建 Inner TS。
- 封装方向链：Inner TS 包流（SPEC-100）→ 本规格 BBFrame 构造 → SPEC-600 T2-MI 包化。
- B2 原语注入点在封装段（corrupt/shift BBHEADER 字段），faulted run tee 双写维持外层（#108）。

## 5. 数据模型

- `BBFrameDTO`（wire snake_case）：`matype / upl / dfl / sync / syncd / crc8_valid / up_count / up_indices`。
- `BBFrameBuildConfigDTO`：`matype_value / upl / n_ups / issy_mode / npd_enabled`。
- 事件 payload：`bbframe.stage_summary`（帧数/N_UPS 分布/ stuffing 比例）、`bbframe.recovery_failed`（失败计数 + 首失败帧 index）。

## 6. 公开接口（接口级契约）

- `bbframe.parse(frames) -> Sequence[BBFrameDTO]`：CRC-8 逐帧校验显式保留；SYNCD 位距换算 UP 边界；畸形帧显式标记不静默。
- `bbframe.build(up_stream, config) -> Sequence[BBFrame]`：确定性；CRC-8 按标准多项式计算；多 UP 批量（N_UPS > 1）与尾帧不足 UP 的填充语义确定性定义。
- 事件发射：`bbframe.*` 两事件（#113 命名空间）。

## 7. 处理算法（接口级行为义务）

- CRC-8 校验在解析路径**强制执行**（对照优势：TSDuck 3.45 不校验——#104 实测位翻转静默传播，本实现禁止该形态）。
- SYNCD carry-over 语义：UP 边界跨 BBFrame 连续（位距累计），归 SPEC-603 消费。
- 多 UP 尾包：末帧 UP 不足 N_UPS 时的 padding 规则确定性（ golden 向量钉扎）。
- 等位替换不变式：BBFrame 层 faulted/baseline 同 index 同帧数（#111）。

## 8. 错误处理

| 场景 | 处理 |
|---|---|
| CRC-8 校验失败 | 显式标记（crc8_valid=false）+ recovery_failed 计数；不静默传播 |
| DFL 与实际数据不符 | 显式畸形帧态 |
| SYNCD 位距越界（超出数据字段） | 显式越界态（B2 场景 symptom 入口） |
| 未支持 MATYPE 模式（VCM/ACM 等） | 显式未支持态 + 注册表渐进 |
| 封装入参非 188 倍数 UP 流 | prepare 前拒绝 |

## 9. 资源约束

- 纯 Python 自研（#108）；预算同 SPEC-600（BBFrame 层处理 ≥ 场景码流上限）。
- 无新增运行时依赖；golden 渐进策略（HEM/NM 子集先钉，其余模式按向量增长）。

## 10. 依赖

| 依赖 | 性质 | 消费点 |
|---|---|---|
| SPEC-600 | 同链下层/上层 | T2-MI 载荷接口 |
| SPEC-100 | 包模型 | UP = 188B TS 包 |
| SPEC-204（#111 修订后） | 作用层路由 | BBFRAME 层原语 BBHEADER_SYNC_FAULT |
| SPEC-301/ADR-0006 | 事件注册表 | bbframe.* additive |
| EN 302 755 §5.1.7 | 标准权威 | BBHEADER 字段面 |
| #104/#105 样流底座 | 向量素材 | 多 UP 用例 |

## 11. 测试向量

- 正向：单 UP 与多 UP（N_UPS=3）BBFrame 封装/解析 round-trip（#105 尾包坑形态为必测集）。
- 负向：CRC-8 位翻转、SYNCD 越界、DFL 不符、ISSY/NPD 边界。
- B2 场景向量：五字段 corrupt/shift 模式各一条（faulted 形态，#111）。

## 12. 验收标准

- **AC-601-01**（REQ-001/002）：双向接口在位；CRC-8 强制校验有测试钉扎；静默传播为零。
- **AC-601-02**（REQ-003）：多 UP 尾包语义确定性（N_UPS=3 用例逐字节钉扎）。
- **AC-601-03**（REQ-004）：bbframe.* 两事件入注册表并发射；B2 原语全链（注入 → 观测 → 诊断候选）绿。
- **AC-601-04**（全门）：后端三门 + dto 漂移锁绿。

## 13. 非目标

- 物理层 FEC/星座/OFDM；FEFC/VCM/ACM 全模式；PLP 过滤（SPEC-602）；Inner TS 输出（SPEC-603）。
- TSDuck BBFrame 对拍（无能力，#104 留证）；crate oracle 面（T2-MI 层级，#107）。

## 14. 兼容性与交付要求

- additive-only（同 SPEC-600）；批准流 DRAFT_FOR_REVIEW → repo 主通读确认 → APPROVED。
- 自研实现相对 TSDuck 3.45 的两个强制超越点（CRC-8 校验、多 UP 尾包正确性）写进实现票验收。
