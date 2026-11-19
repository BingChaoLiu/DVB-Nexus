---
spec_id: SPEC-307
title: Diagnostic Rules
version: 0.8.0
status: APPROVED
phase: MVP
owner: Diagnosis
priority: P0
depends_on: [SPEC-306]
requirements: [REQ-DIA-307-001, REQ-DIA-307-002, REQ-DIA-307-003, REQ-DIA-307-004, REQ-DIA-307-005]
---

# SPEC-307 — Diagnostic Rules

## 1. 目标

定义诊断规则的模型与注册语义：定义、注册、匹配、抑制和版本（REGISTRY §C）。本规格兑现 SPEC-003 §6 遗留项"Diagnosis 规则优先级、抑制、关联和置信度语义"的 MVP 裁决（ticket #13 Q3）。

## 2. 范围

### 2.1 In Scope

- DiagnosticRule 模型与字段语义。
- 声明式匹配原语（MatchSpec）。
- 优先级排序与抑制语义（MVP 收窄）。
- 内置规则集与版本化。

### 2.2 Out of Scope

- 评估触发与事件发布（SPEC-306）。
- 健康告警规则（SPEC-304 的 health rule 是独立系统，不共用注册表）。
- 用户自定义规则、热加载、规则市场（roadmap）。

## 3. 规则模型

```python
@dataclass(frozen=True)
class DiagnosticRule:
    rule_id: str            # 语义 slug，如 "DIA-PAT-MISSING"
    rule_version: str       # semver
    code: str               # 诊断码，如 "DIAG_PAT_MISSING"
    priority: int           # 小者先
    severity: Literal["info", "warning", "error", "critical"]
    confidence: Literal["low", "medium", "high"]   # 静态三档（Q3-ii）
    title: str
    summary_template: str   # 解释模板，可引用 knowledge 静态标准引用数据
    match: MatchSpec        # 声明式谓词
    suppression: SuppressionSpec
    suggested_actions: tuple[str, ...]
    expected_evidence: tuple[str, ...]   # 观测事件码，对 ADR-0007 expected_observations
```

- **confidence 是规则的静态声明**，引擎不计算连续分；无校准依据不得宣称统计概率（SPEC-003 §2.6）。
- `severity` 四档沿 SPEC-003 §2.6；`priority` 与 `severity` 正交：priority 管排序，severity 管展示等级。

## 4. 匹配原语（MatchSpec）

MVP 有限声明式集合（ticket #13 Q-B-②）：

- `event_type`：观测类事件类型（SPEC-301 §4 注册表）。
- 字段谓词：`eq / gt / lt / exists`（作用于 payload 与 correlation 字段）。
- 窗口聚合：`count / rate`（窗口按 run 或虚拟时间区间）。
- 分组键：`pid` / `node_id`（correlation 寻址，ADR-0006 第 3 条双形式）。

**禁用户自定义 Python/表达式字符串**（对齐 SPEC-305 §9 既有禁令）；新增原语属 additive 评审。

## 5. 优先级与抑制（MVP 收窄）

- **排序**：`priority` 升序 → `severity` 降序 → `code` 字典序；不做优先级抢占（规则全评估，排序输出）。
- **抑制**（Q3-iii MVP 语义）：per `(code, node_id)` 每 run 只产一条 `diagnosis.raised`，后续命中走 `diagnosis.updated` 累积 evidence——**不做** SPEC-304 式五态告警生命周期。
- `SuppressionSpec`：`key: tuple["code", "node_id"]`（MVP 固定）+ `window: "per_run"`（MVP 固定）；扩展位留给未来 window/维度。

## 6. 内置规则集（首发四条，ticket #13 Q-B-④）

| rule_id | 对应故障（ADR-0007 §5） | 主观测信号 | priority | severity | confidence |
|---|---|---|---|---|---|
| `DIA-PAT-MISSING` | PAT_MISSING | PID 0 PAT 窗口缺失（Null 包顶替） | 10 | error | high |
| `DIA-PMT-CRC-BAD` | PMT_INVALID_CRC | PMT CRC 校验失败（persistent 模式症状稳定） | 20 | error | high |
| `DIA-CC-DISCONTINUITY` | CC_DISCONTINUITY | `ts.continuity_error`（相对偏移持续语义） | 30 | warning | high |
| `DIA-PMT-PID-MISMATCH` | PMT_PID_MISMATCH | PAT 指向 wrong_pid + wrong_pid 无 PMT + 孤儿 PMT | 40 | error | medium |

- 四条规则与四类故障**一一对应**（靶场单一可归因症状原则）；`expected_evidence` 与各 FaultDefinition 的 `expected_observations` 字段互证。
- 具体谓词参数随实现细化，但信号语义以 ADR-0007 §5 为权威。

## 7. 注册与版本

- **内置静态注册**（ticket #13 Q-B-③）：Python 定义 + JSON 声明（`rules/*.json`），启动时加载校验（`rule_id`/`code` 唯一性、match 引用的事件类型必须在 SPEC-301 §4 注册表内）。
- 运行时可禁用（配置开关），**无热加载**；规则集变更 = 新 `rule_version`，不改既有版本语义。
- `rule_version` 进 SPEC-502 `diagnoses` 表与 `diagnosis.*` 事件 payload（可追溯）。

## 8. 错误处理

| 场景 | 语义 |
|---|---|
| 规则 JSON 校验失败 | 启动失败（fail-fast），不静默跳过 |
| match 引用未注册事件类型 | 启动失败（fail-fast） |
| 规则被禁用 | 评估时跳过（非错误） |
| 单规则运行时异常 | 规则隔离（SPEC-306 §8） |

## 9. 测试规格

- 规则 JSON schema 校验 + 唯一性校验。
- 排序矩阵：priority/severity/code 三级排序。
- 抑制：同 (code, node_id) 同 run 多次命中 → 一 raised + N updated。
- 四条内置规则 × 四类故障注入向量 → 各产生对应候选（与 SPEC-306 §9 共享 fixture）。
- 禁用规则不产生候选。

## 10. 验收标准

- `REQ-DIA-307-001`：DiagnosticRule 模型与 MatchSpec 原语落地，禁任意代码。
- `REQ-DIA-307-002`：四级排序 + MVP 抑制语义生效。
- `REQ-DIA-307-003`：首发四条规则与四类故障一一对应，expected_evidence 与 expected_observations 互证。
- `REQ-DIA-307-004`：静态注册 fail-fast 校验（唯一性 + 事件类型引用）。
- `REQ-DIA-307-005`：rule_version 可追溯（记录 + 事件 payload）。

## 11. 非目标与风险

- 不做用户自定义规则、热加载、规则间因果链、机器学习推断。
- 不做 304 式告警生命周期。
- 风险：规则误报污染通关判定（SPEC-206 依赖 diagnosis）——抑制语义 + 单一可归因症状原则控制；规则调优随靶场实战迭代（bump rule_version）。

## 12. 交付要求

建议文件：`app/domain/diagnosis/`（`rules/`（模型 + loader）+ `rules/builtin/*.json`）。规则声明 JSON schema 随实现落地。

## 13. 参考

- SPEC-003 §2.6/§6（Diagnosis 实体与遗留项）、SPEC-301 §4（事件类型引用合法性）。
- [ADR-0007](../../../../adr/0007-fault-injection-pipeline-contract.md) 第 4/5 条（共用包序 frame、四类故障语义与 expected_observations）。
- SPEC-306（消费本规则集）、SPEC-304（健康告警——独立系统对照）。

## Phase 2 定点修订（随落笔票 #117，DRAFT_FOR_REVIEW 0.6.0；依据：细裁 [#111](https://github.com/BingChaoLiu/DVB-Nexus/issues/111)）

- **内置诊断规则新增四条候选声明**（declarations 机制不变，与四新原语一一对应，靶场单一可归因症状原则延续）：
  1. T2MI_PLP_MISMATCH → 「PLP 映射错位」候选：证据 = t2mi.plp_mismatch 事件 + Inner TS 业务缺失定位；
  2. BBHEADER_SYNC_FAULT → 「BBHEADER 同步错位」候选：证据 = bbframe.recovery_failed + 首失败帧定位；
  3. BISS_KEY_MISMATCH → 「BISS 密钥错位」候选：证据 = biss.descramble_failed + 密钥指纹互链（区分解扰失败 vs 码流损坏）；
  4. PMT_PID_DRIFT → 「PMT/Demux 过滤不同步」候选：证据 = PSI 版本对比 + 声明 PID 无数据漂移。
- 诊断规则与故障原语同批落库；confidence 三档静态声明机制不变（候选 ≠ 事实纪律不变）。

## Phase 2 补丁定点修订（随补丁票 [#138](https://github.com/BingChaoLiu/DVB-Nexus/issues/138)，DRAFT_FOR_REVIEW 0.7.0；依据：#136 补丁票评估 D-1）

- **diagnose 面点亮**：四条候选规则声明**两态通用**（match `event_type` 与 payload 谓词零改动，#130 已钉）。引擎输入族扩容至 Phase 2 证据族（`t2mi.plp_mismatch` / `bbframe.recovery_failed` / `biss.descramble_failed`；MVP `ts.*` 观测族不动，锚定链与 EvidenceRef 两态语义见 SPEC-306 §6/§7 Phase 2 补丁修订）后，三条构造候选规则在各自证据事件上产生候选，diagnose 面全部点亮——SC-06/07/08 E2E 升级为 diagnose 候选断言（与既有 journal 证据断言双轨并存）。规则注册与校验面（§7 启动 fail-fast、match 引用事件类型必须在注册表内）语义不变：证据族三类型已在 SPEC-301 §4 注册表内。
- **`DIA-PMT-PID-DRIFT` 点亮路径**：match 事件 `ts.psi_section_observed` 本就在观测族内，点亮依赖故障原语 `PMT_PID_DRIFT` 的 transform 实现与注入链贯通（补丁票 #139，纯实现缺口——SPEC-204 §Phase2 已定义原语语义，无规格修订）。

## Phase 3 定点修订（随落笔票 #156，DRAFT_FOR_REVIEW 0.8.0；依据：细裁 [#151](https://github.com/BingChaoLiu/DVB-Nexus/issues/151) Q4）

- **规则候选扩容两条**（静态声明置信度三档，照 Phase 2 四候选先例）：
  - `TONE_RESIDUE_SUSPECT`（medium）：消费 `rf.state_observed`（tone_actual ≠ tone_commanded）+ tuner ber_state=elevated/severe + CauseRef 指向 lnb → 根因候选「LNB tone 残留 / 供电异常」；
  - `UB_CONFLICT_SUSPECT`（high）：消费 tuner lock_state=unlocked + CauseRef 冲突对 + ub_assignments 表 → 根因候选「UB 槽位冲突 / SCR 堆叠互扰」。
- **证据族依赖**：rf.*/sec.* 事件类型须先入 SPEC-301 §4 注册表（SPEC-303 Phase 3 修订同批）；match/payload 谓词机制与启动 fail-fast 校验语义不变（Phase 2 补丁修订「两态通用」口径延续）。
- 规则输入观测均为 state_evaluator 来源 + simulated 置信度；Diagnosis/Observation 两轴纪律不变（CONTEXT.md）。
