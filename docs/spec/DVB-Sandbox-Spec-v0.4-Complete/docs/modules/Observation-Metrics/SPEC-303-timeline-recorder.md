---
spec_id: SPEC-303
title: Timeline Recorder
version: 0.5.0
status: APPROVED
phase: MVP
owner: Observation
priority: P0
depends_on: [SPEC-300, SPEC-301]
requirements: [REQ-OBS-303-001, REQ-OBS-303-002, REQ-OBS-303-003, REQ-OBS-303-004, REQ-OBS-303-005]
---

# SPEC-303 — Timeline Recorder

## 1. 目标

持久化统一、可审计的时间轴：session 事件、拓扑变化、TS 观测、故障生命周期、场景进度、通关结果、指标注记与检查点。时间轴是证据导航的骨架（CONTEXT.md「证据」：从诊断结果可直达原始码流）。

## 2. 范围

### 2.1 In Scope

- 时间轴记录类型与来源追溯。
- 排序纪律（journal_seq 优先、多时钟域分道）。
- 检查点（checkpoint）记录契约。
- 查询、游标分页与导出（JSONL/CSV/ZIP）。
- 保留与删除语义。

### 2.2 Out of Scope

- 事件摄入与校验（SPEC-300 Gateway/Journal）。
- 仿真重放执行（时间轴只支持查询与导出）。
- Artifact 文件本体管理（SPEC-503）。
- 前端时间轴交互（SPEC-407 已移 roadmap §3）。

## 3. 记录类型

- `event`：SPEC-301 规范事件（含 journal_seq）。
- `snapshot`：带来源归属与版本的状态快照。
- `annotation`：操作者或系统注记。
- `checkpoint`：录制器/消费者进度标记。
- `bookmark`：训练或诊断用的命名位置。
- `export_manifest`：导出产物元数据。

时间轴记录必须保留原始 `event_id` 与 `journal_seq`（凡派生自事件者）——证据链不断。

## 4. 排序纪律

- 默认排序：源自事件 journal 的记录按 `journal_seq`。
- 跨来源（无 journal_seq 的快照等）：按 `(clock_domain, timestamp, source_id, source_seq)` 显式排序，且查询输出必须标明所用排序。
- **不得宣称跨不相容时钟域的单一时间序**：调用方必须指定时钟域或请求分道（lanes）返回——虚拟时间与墙钟永不混排（SPEC-300 §6 时钟模型）。

## 5. 检查点

checkpoint 包含：`checkpoint_id`、`session_id`、`journal_seq`、`clock_domain`、适用时的 `virtual_time_ns`、`schema_version`、`producer_state_versions`、`created_at`、可选完整性摘要。

- 检查点是**观测行为**：绝不暂停或突变仿真；权威仿真快照归 SPEC-200。
- checkpoint 的 timepoint 字段按 SPEC-300 §6 独立记录规则携带显式语义（字段名即语义：`virtual_time_ns` vs `created_at`）。

## 6. 查询与分页

过滤器：session、scenario、事件类型、severity、producer、node、service、PID、fault ID、时间范围、无文本 tags。

- 分页用 opaque cursor token，绑定过滤器哈希与 scope。
- 页大小默认 500，硬上限 2000。
- cursor 过期返回 `OBS_CURSOR_EXPIRED`。
- 查询参数形状遵循 SPEC-305 §4 扁平标量基准（[缝合批准 #12] 裁决）。

## 7. 导出

初始格式：

- **JSONL**：规范机器可读导出。
- **CSV**：事件索引表；嵌套 payload 压缩为 JSON 字符串。
- **ZIP 包**：JSONL + 元数据，可选指标序列与脱敏报告。

导出 manifest 必含：export ID、创建时间、请求 scope 与过滤器、时钟域与起止、按类型记录数、schema 版本、脱敏策略/版本、每文件 SHA-256。

同一不可变 journal 区间 + 相同导出选项 ⇒ 导出**可复现**（创建时间/ID 等生成元数据除外）。

## 8. 保留与删除

- 时间轴数据遵循配置保留期。
- 法律/管理删除必须限定范围并审计。
- 删除不得留下看似有效记录的悬垂引用：按策略返回显式 tombstone 或脱敏元数据。

## 9. 错误与诊断码

复用 SPEC-300 §13：`OBS_CURSOR_EXPIRED`、`OBS_QUERY_RANGE_TOO_LARGE`、`OBS_SCOPE_FORBIDDEN`、`OBS_STORAGE_UNAVAILABLE`。

## 10. 测试规格

- journal_seq 排序正确性（含乱序摄入）。
- 多时钟域分道查询行为（混域请求被拒或分道）。
- cursor 与过滤器/scope 绑定（换过滤器重放旧 cursor 必须失效）。
- cursor 过期路径。
- JSONL/CSV/ZIP round-trip 与逐文件摘要校验。
- 脱敏与密钥扫描。
- 检查点不突变仿真（检查点前后仿真状态零变化断言）。
- 导出可复现性（同区间同选项重复导出，除生成元数据外逐字节一致）。

## 11. 验收标准

- `REQ-OBS-303-001`：记录保留原始 event_id/journal_seq，证据链完整。
- `REQ-OBS-303-002`：排序纪律实现（journal_seq 优先、跨域分道、排序来源显式）。
- `REQ-OBS-303-003`：检查点观测语义（不暂停/突变仿真）。
- `REQ-OBS-303-004`：cursor 分页绑定与过期语义正确。
- `REQ-OBS-303-005`：三种导出格式 round-trip、摘要校验、可复现且脱敏感知。

## 12. 非目标与风险

- 不做时间轴上的仿真回放执行（回放 UI 已移 roadmap §3）。
- 不承诺无限历史（保留期配置化）。
- 风险：导出大区间时的 IO 峰值——导出任务限流（SPEC-305 §8），分块流式产出。

## 13. 交付要求

建议文件：`app/observation/timeline/`（recorder.py / export.py）；测试置于 `tests/unit/observation/` 与 `tests/integration/observation/`。

## 14. 参考

- SPEC-300（数据流与组件）、SPEC-301（事件来源与 journal_seq）。
- 原 Evidence Manager 职责分摊裁决：timeline/evidence 导出由本 spec 承载（[规格编号体系重建 #10]）。
