---
spec_id: SPEC-506
title: Conformance Suite
version: 0.5.0
status: APPROVED
phase: MVP
owner: Platform
priority: P0
depends_on: [SPEC-100, SPEC-101, SPEC-102, SPEC-103, SPEC-104, SPEC-105, SPEC-106, SPEC-107, SPEC-108]
requirements: [REQ-CNF-506-001, REQ-CNF-506-002, REQ-CNF-506-003, REQ-CNF-506-004]
---

# SPEC-506 — Conformance Suite

## 1. 目标

MPEG-TS 标准测试向量与 golden streams 的**管理机制**：目录结构、登记格式、独立验证规则、CI 门与批准/失效流程。按补写契约票据（ticket #13 Q6）裁决：本规格只定机制骨架；**向量内容与验收策略归 golden streams 与 conformance 策略票据（[#14](https://github.com/BingChaoLiu/DVB-Nexus/issues/14)）**（ts-core 修订批准 [#11](https://github.com/BingChaoLiu/DVB-Nexus/issues/11) 的"golden 向量补齐归 conformance ticket"裁决由此承接）。

## 2. 范围

### 2.1 In Scope

- golden 向量目录布局与三件套。
- 登记格式与索引。
- 独立验证红线。
- CI 门与向量生命周期（批准/变更/失效）。

### 2.2 Out of Scope

- 具体向量内容、数量与覆盖矩阵（#14）。
- generate/inject 兜底的使用策略（#14）。
- 性能基准（SPEC-507，P1）。

## 3. golden 目录布局（ticket #13 Q-E-②）

```
docs/spec/DVB-Sandbox-Spec-v0.4-Complete/docs/test-vectors/
├── TEST-VECTOR-INDEX.md              # 人工索引（指向各 golden 目录）
├── CRC32-MPEG2.md / PCR-PTS.md       # 既有位级向量文档
└── golden/<vector_id>/
    ├── <vector_id>.ts                # 字节（TS 流或位级样本）
    ├── manifest.json                 # 机器可读登记（§4）
    └── expectations.json             # 期望观测（§4）
```

- 三件套缺一不予登记。
- `vector_id` 语义 slug（如 `pat-minimal`、`cc-discontinuity-faulted`），全局唯一。

## 4. 登记格式

**manifest.json**（机器可读，conformance 测试与 golden_loader 消费）：

```json
{
  "vector_id": "pat-minimal",
  "kind": "generated_ts | faulted_ts | bit_level",
  "related_specs": ["SPEC-103", "SPEC-108"],
  "generator_version": "0.5.0",
  "config_hash": "sha256:...",
  "sha256": "文件内容 SHA-256",
  "packet_count": 1500,
  "fault_plan_ref": null
}
```

**expectations.json**（期望观测，与 FaultDefinition `expected_observations` **同构互证**——[ADR-0007](../../../../adr/0007-fault-injection-pipeline-contract.md) 第 5 条字段结构）：

```json
{
  "expectations": [
    {"event_type": "ts.psi_section_observed", "locator": {"pid": 0}},
    {"event_type": "ts.continuity_error", "locator": {"pid": 256, "packet_index": 12000}}
  ]
}
```

- 等位替换 golden：baseline 与 faulted 向量**共用包序 frame**（packet_index 同槽位，ADR-0007 第 4 条）；faulted 向量 `fault_plan_ref` 指向对应 baseline。
- `TEST-VECTOR-INDEX.md` 每行指向 golden 目录，标注 status（`registered / deprecated`）。

## 5. 独立验证红线（ticket #13 Q-E-③）

TEST-VECTOR-INDEX 既有规则**升格为规格条款**：

> golden 文件不得仅因同一实现解析自身输出而接受——至少一条**独立验证路径**（TSDuck 分析通过，或独立评审的位级向量）。

- 独立验证证据（TSDuck 报告要点或评审记录）登记进 manifest `verification` 字段（实现期细化）。
- 同源自证 = 登记拒绝。

## 6. CI 门与向量生命周期

- conformance 层测试（SPEC-505 §3）加载**全部已登记向量**：SHA-256 校验 + expectations 断言（经 SPEC-305 查询或 journal 重放取得观测）。
- **向量变更 = 重新登记 + 批准**：字节变了就是新 vector_id（或同 id bump 内容并重走批准），sha256/manifest/expectations 三者必须一致。
- 失效向量标 `deprecated`，不删除（provenance 纪律）；被依赖方迁移后由 #14 流程清理。
- 新向量提案流程（#14 细化）：提案 → 独立验证证据 → 三件套登记 → 批准入索引。

## 7. 错误处理

| 场景 | 语义 |
|---|---|
| 三件套缺一 | 登记拒绝（fail-fast，启动/CI 即报） |
| sha256 与文件不符 | CI 失败 |
| expectations 引用未注册事件类型 | 登记拒绝（SPEC-301 §4 合法性校验，对齐 SPEC-307 §8） |
| deprecated 向量被测试引用 | 显式失败（引用方须迁移） |

## 8. 测试规格

- 登记校验器：三件套完整性、SHA 一致性、事件类型合法性。
- golden_loader round-trip：manifest ↔ 文件 ↔ expectations 一致。
- 等位替换向量对：baseline/faulted packet_index 同槽位断言。
- 全量加载门：CI conformance 层零跳过（deprecated 引用除外须显式）。

## 9. 验收标准

- `REQ-CNF-506-001`：golden 三件套目录布局与登记格式落地，缺一拒绝。
- `REQ-CNF-506-002`：独立验证红线生效（同源自证拒绝）。
- `REQ-CNF-506-003`：CI 门加载全量向量（SHA + expectations 断言）。
- `REQ-CNF-506-004`：向量生命周期（变更重登记、deprecated 标记）可执行。

## 10. 非目标与风险

- 不定义向量内容清单、覆盖矩阵与 generate 兜底策略（#14）。
- 不做向量自动生成流水线（#14 评估）。
- 风险：向量与生成器版本耦合（generator_version 入 manifest）——生成器版本变更触发相关向量重验，成本随 #14 策略控制。

## 11. 交付要求

建议文件：`docs/test-vectors/`（既有）+ `golden/` 目录 + `app/adapters/` 之外的独立 loader（`tests/conformance/golden_loader.py`，归 SPEC-505 fixture 体系）；登记校验器入 `tools/`。

## 12. 参考

- TEST-VECTOR-INDEX.md（既有索引与独立验证规则原句）。
- SPEC-505（conformance 测试层与 golden_loader fixture）、SPEC-108（生成器版本与 config_hash）。
- [ADR-0007](../../../../adr/0007-fault-injection-pipeline-contract.md) 第 4/5 条（共用包序 frame、expected_observations 同构）。
- golden streams 与 conformance 策略票据（[#14](https://github.com/BingChaoLiu/DVB-Nexus/issues/14)）——内容与策略权威。
