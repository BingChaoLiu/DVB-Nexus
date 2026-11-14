# Diagnosis Spec Index

**Package version:** 0.5.0
**Status:** MVP_BASELINE_APPROVED
**Normative parent:** DVB Sandbox SPEC-003 §2.6（Diagnosis 实体与 confidence 禁令）；事件信封归 SPEC-301 权威（ADR-0006）

[ticket #13 补写批准](https://github.com/BingChaoLiu/DVB-Nexus/issues/13)（2026-11-14）：两份规格接口级成文并批准为 MVP 基线（APPROVED 0.5.0）。SPEC-309（Analyzer Comparator，P1）不在本包，随 roadmap。

| Spec ID | Document | Depends on | MVP priority | Primary output |
|---|---|---|---|---|
| SPEC-306 | [Diagnosis Engine](SPEC-306-diagnosis-engine.md) | SPEC-300/301/302 | P0 | 评估触发模型、evidence 定位义务、diagnosis.* payload schema |
| SPEC-307 | [Diagnostic Rules](SPEC-307-diagnostic-rules.md) | SPEC-306 | P0 | 规则模型、声明式匹配原语、优先级/抑制 MVP 语义、内置四规则 |

## 批准要点（详见各 spec 与 ticket #13 决议）

- **置信度三档裁决**（ticket #13 Q3-ii）：Diagnosis.confidence = 规则静态声明 `low/medium/high`，引擎不计算连续分；无校准依据不得宣称统计概率（SPEC-003 §2.6 同步枚举化）。与观测侧 ConfidenceKind（simulated/parsed/measured/inferred）是**两条不同的轴**。
- Diagnosis ≠ Observation（ADR-0006 第 5 条命名纠偏）：本包是 diagnostic rule + diagnosis；SPEC-304 是 health rule + alert record——两套规则系统不共用注册表。
- 评估时机 MVP = run 结束批处理；只消费 observation 事件，不碰 TSDuck 进程、不解析原始 TS（ADR-0005）。
- 内置四条规则与四类 MVP 故障一一对应（靶场单一可归因症状原则，ADR-0007 第 5 条）；`expected_evidence` 与 `expected_observations` 同构互证。
- suppression MVP = per (code, node_id) per run 一条 raised，后续 updated 累积 evidence。
