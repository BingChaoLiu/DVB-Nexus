---
spec_id: SPEC-206
title: Recovery Verification
version: 0.5.0
status: APPROVED
phase: MVP
owner: Simulation Engine
priority: P0
depends_on: [SPEC-205, SPEC-306, SPEC-308]
requirements: [REQ-SIM-206-001, REQ-SIM-206-002, REQ-SIM-206-003, REQ-SIM-206-004, REQ-SIM-206-005, REQ-SIM-206-006]
---

# SPEC-206 — 恢复验证（Recovery Verification）

## 1. 目标

以**新的观测结果**判定学习者是否真正修复了故障（CONTEXT.md「通关」）：修复动作本身、UI 变绿都不是证据；只有修复后的新 Run 证据支持判定。判定三态 PASS / FAIL / INCONCLUSIVE。

## 2. 范围

### 2.1 In Scope

- 判定输入契约与三态 verdict 语义。
- per-criterion 判定（PASS/FAIL/NOT_EVALUATED）与证据引用。
- 观测语义区分纪律（无观测 ≠ 干净 等，第 6 节）。
- 判定的确定性与持久化。

### 2.2 Out of Scope

- 观测事实的产生（SPEC-300~302）与诊断归因（SPEC-306/307，文本随 #13）。
- TSDuck 对照分析的执行（SPEC-308/309）。
- UI 呈现（SPEC-406）。
- 评分/积分。

## 3. 判定输入

- 场景 revision 与 pass criteria（SPEC-205 场景文档声明，本模块消费）。
- baseline Run 与故障证据（fault plan、mutation log、faulted artifact 引用）。
- 候选恢复 Run（修复后新生成/分析的证据）。
- 规范化观测（normalized observations；观测来源与置信度纪律见 CONTEXT.md，禁止混标）。
- 拓扑/故障快照、artifact SHA-256 与引擎版本。

**解耦条款**：在 SPEC-306/308 规格文本落地（[补写 MVP P0 缺失契约](https://github.com/BingChaoLiu/DVB-Nexus/issues/13)）与实现前，本模块经**本地 adapter + fixture**获取观测输入，**不得**耦合其内部实现——adapter 接口即本 spec 的一部分，后续以该接口对接真实 Observation/Diagnosis 服务。

## 4. 判定结果

```text
verdict: PASS | FAIL | INCONCLUSIVE
per-criterion: PASS | FAIL | NOT_EVALUATED（附原因码）
evidence_refs: 判据 → 证据定位（journal_seq、artifact、mutation log、诊断记录引用）
summary、run_id / scenario 版本标识、operational 验证时间戳
```

- PASS 要求**全部 mandatory 判据通过**；任一 mandatory FAIL ⇒ 总体 FAIL。
- **mandatory 证据缺失 ⇒ INCONCLUSIVE**（不是 PASS 也不是 FAIL——"没证据"与"证据表明失败/通过"是不同结论）。
- 判定结果经信封发射 `recovery.verification_completed`（ADR-0006 权威名）并持久化（含 run/scenario 版本）。

## 5. 判定语义细则

1. 每条判据的评估确定性：相同输入必得相同 per-criterion 结果；判据评估不读墙钟、不用随机。
2. NOT_EVALUATED 必须显式给原因（证据缺失 / 分析器不支持 / 判据依赖的上游未完成），不得静默跳过。
3. verdict 与全部 per-criterion 结果持久化并关联 run/scenario 版本，支持事后审计与重放。
4. 恢复 Run 必须与 baseline Run 可区分（不同 run_id、修复动作可追溯）；对 baseline 自身的"验证"直接 INCONCLUSIVE。

## 6. 观测语义区分（冻结纪律）

判定必须区分以下对偶，混淆即实现缺陷：

| 对偶 | 区分要求 |
|---|---|
| 无观测 vs 干净观测 | "该 PID 无任何观测" ≠ "观测确认无错误"；前者在 mandatory 判据下是 INCONCLUSIVE |
| 分析器不支持 vs 协议违规 | 工具无该能力（如 TSDuck descrambler 不支持 BISS）≠ 码流违规 |
| 缺失值 vs 零值 | 字段缺失 ≠ 数值为 0（SPEC-302 §5 同源纪律） |
| 预期不连续 vs 意外 CC 错误 | 故障注入声明的不连续（expected_observations 覆盖）≠ 未声明的 CC 错误 |

## 7. 判据示例（非穷举）

- PAT 存在 / CRC 有效。
- PAT→PMT PID 映射有效（含 PMT_PID_MISMATCH 场景的 wrong_pid 消失复核）。
- PMT CRC 有效。
- 选中 PID 在定义的包语义下 CC 有效（注意 SPEC-204 相对偏移持续性——修复后须从恢复点重新计算期望 CC）。
- 故障非活跃（fault.cleared 已见且窗口后无复发）。

判据评估复用 Observation/诊断输出；本模块不重新解析码流。

## 8. 错误与诊断码

| Code | 条件 | 处理 |
|---|---|---|
| `SIM_VERIF_CRITERION_INVALID` | pass criteria 引用未知判据 kind | 拒绝判定 |
| `SIM_VERIF_EVIDENCE_MISSING` | mandatory 证据缺失 | per-criterion NOT_EVALUATED → 总体 INCONCLUSIVE |
| `SIM_VERIF_RUN_MISMATCH` | 候选 Run 与场景版本不匹配 | 拒绝 |
| `SIM_VERIF_BASELINE_REUSED` | 候选 Run 即 baseline | INCONCLUSIVE |

## 9. 测试规格

- 全 mandatory PASS ⇒ PASS；单 mandatory FAIL ⇒ FAIL；证据缺失 ⇒ INCONCLUSIVE（三态矩阵）。
- 第 6 节四个对偶逐一的区分测试（构造"无观测但判据 mandatory"等场景）。
- 确定性：同输入重放判定结果一致（排除 operational 时间戳）。
- UI 状态不可作为证据：仅注入 UI 状态、无观测证据的输入 ⇒ INCONCLUSIVE（AC-206-01）。
- verdict 持久化与 `recovery.verification_completed` 事件一致性。
- 本地 adapter 与 fixture 驱动的端到端样例（CC_DISCONTINUITY 修复前后）。

## 10. 验收标准

- `REQ-SIM-206-001`：UI 状态无证据不能 PASS。
- `REQ-SIM-206-002`：mandatory 证据缺失 ⇒ INCONCLUSIVE。
- `REQ-SIM-206-003`：每条判据有证据引用或显式 NOT_EVALUATED 原因。
- `REQ-SIM-206-004`：恢复 Run 与 baseline 可区分且被校验。
- `REQ-SIM-206-005`：判定确定性（重放一致）。
- `REQ-SIM-206-006`：verdict 随 run/scenario 版本持久化并发事件。

## 11. 非目标与风险

- 不定义置信度/概率语义（diagnosis 域，SPEC-306/307）。
- 不承诺自动修复建议（suggestedActions 属 Diagnosis 实体，SPEC-003 §2.6）。
- 风险：本地 adapter 是过渡形态——若实现期 Observation 未就绪，允许 fixture 判定先行，但 verdict 持久化与事件义务不得豁免；对接真实 Observation 后必须以重放等价性测试替换 fixture 测试。

## 12. 交付要求

建议文件：`app/simulation/verification.py`（或 `app/verification/`）；测试置于 `tests/unit/simulation/` 与 `tests/integration/verification/`。

## 13. 参考

- CONTEXT.md「通关」词条（Recovery Verification、PASS/FAIL/INCONCLUSIVE）。
- SPEC-205（pass criteria 来源）、SPEC-204（expected_observations、mutation log）。
- ADR-0006 第 5 条（recovery.verification_completed 权威名）。
