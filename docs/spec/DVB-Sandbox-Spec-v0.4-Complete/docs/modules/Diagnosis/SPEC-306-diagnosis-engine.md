---
spec_id: SPEC-306
title: Diagnosis Engine
version: 0.6.0
status: DRAFT_FOR_REVIEW
phase: MVP
owner: Diagnosis
priority: P0
depends_on: [SPEC-300, SPEC-301, SPEC-302]
requirements: [REQ-DIA-306-001, REQ-DIA-306-002, REQ-DIA-306-003, REQ-DIA-306-004, REQ-DIA-306-005]
---

# SPEC-306 — Diagnosis Engine

## 1. 目标

把事件 journal 中的观测事实关联为**根因候选**：Diagnosis 表示规则产生的判断，不是原始事实（SPEC-003 §2.6；ADR-0006 第 5 条命名纠偏——诊断结果不挂 observation 命名空间）。消费方 = SPEC-206 通关判定（PASS/FAIL/INCONCLUSIVE 依据之一）与 SPEC-406 Training Lab UI。

## 2. 范围

### 2.1 In Scope

- 评估触发模型与公开接口。
- Evidence 定位义务（观测 → PID + packet index + Artifact）。
- `diagnosis.raised / updated / cleared` 三事件的 payload schema（SPEC-301 §4 预告项，随本票落地）。
- 与 SPEC-502 `diagnoses` 表的持久化边界。

### 2.2 Out of Scope

- 规则定义、匹配、抑制与版本（SPEC-307）。
- 健康告警（SPEC-304 是另一套规则系统：health rule + alert record；本模块是 diagnostic rule + diagnosis）。
- TSDuck 进程与原始 TS 解析（ADR-0005：diagnosis 只消费 observation）。
- 连续置信分与概率校准（roadmap；MVP 三档语义见 SPEC-307）。

## 3. 架构纪律

- **只消费 observation**：输入 = SPEC-502 EventJournal 按 run 取观测类事件（`ts.*` 家族等）；不碰 TSDuck 进程、不解析原始 TS、不读 SQLite 之外的存储（ADR-0005 决策 4 依赖方向）。
- 解释性文本可引用 `knowledge` 包静态标准引用数据（MVP：无独立交互面）。
- 单一可归因症状原则（[ADR-0007](../../../../adr/0007-fault-injection-pipeline-contract.md) 第 5 条）：规则间不做因果链推理，候选相互独立、以 evidence 关联。

## 4. 评估触发模型

MVP = **run 结束触发的批处理评估**（ticket #13 Q-B-①；与生成离线批处理一致，ADR-0005 决策 4 删 `workers/` 同理）：

- 触发点：`run_completed`（或 `run_failed`）事件后由 Application 层调用。
- 流式实时评估留接口扩展位（additive：新增 `subscribe` 方法不改既有签名）。

## 5. 公开接口

```python
class DiagnosisEngine(Protocol):
    def evaluate(self, session_id: str, run_id: str,
                 *, rules: RuleSet | None = None) -> DiagnosisReport: ...
```

- `rules=None` 时使用 SPEC-307 当前注册的规则集全量。
- `DiagnosisReport.candidates`：按 `priority` 升序（同序按 severity 降序、再按 code 字典序，SPEC-307 排序语义）。
- 命中候选即：upsert SPEC-502 `diagnoses` 表 + 发布 `diagnosis.*` 事件（SPEC-301 信封，scope.run_id 归属）。

## 6. Evidence 定位（义务）

每条 diagnosis **至少一条 evidence ref**（CONTEXT.md Evidence 词条：可下钻、可直达原始码流）：

```
diagnosis → event (journal_seq) → payload (pid / packet_index) → artifact_id
```

- `observation_refs` 存事件 `journal_seq`（per session 全序，SPEC-301）；`packet_index` 语义遵循等位替换共用包序 frame（ADR-0007 第 4 条——baseline 与 faulted 同 index 同槽位）。
- `artifact_id` 经 SPEC-502 `artifacts` 表解析到 SPEC-503 物理文件。

## 7. 事件 payload schema

`diagnosis.raised` / `diagnosis.updated` / `diagnosis.cleared`（注册表见 SPEC-301 §4）payload 共用形状：

```json
{
  "diagnosis_id": "uuid4",
  "rule_id": "DIA-PAT-MISSING",
  "rule_version": "1.0.0",
  "code": "DIAG_PAT_MISSING",
  "severity": "error",
  "confidence": "high",
  "title": "PAT missing in window",
  "summary": "No PAT observed on PID 0 between packet 12000 and 18000",
  "observation_refs": [{"journal_seq": 42, "event_type": "ts.psi_section_observed"}],
  "affected_node_ids": ["mux-0"],
  "suggested_actions": ["Restore PAT emission on PID 0"],
  "evidence": {"artifact_id": "uuid4", "pid": 0, "packet_index": 12000}
}
```

- `confidence` 三档枚举（SPEC-307 静态声明）；`cleared` 事件 payload 只需 `diagnosis_id` + `rule_id` + 清除原因。
- `raised` = 新候选；`updated` = 同 `diagnosis_id` 变更（evidence 累积/severity 调整）；`cleared` = 症状消除（如重新生成后无该症状）。

## 8. 错误处理

| 场景 | 语义 |
|---|---|
| 无规则注册 / 无匹配 | 空报告（非错误） |
| 单规则执行异常 | 规则隔离：记 warning、跳过该规则，其余照常评估 |
| journal 查询失败 | 存储不可用——HTTP 503 |
| 事件 payload 不满足观测类 schema | 跳过该事件（记 warning），不产生候选 |

## 9. 测试规格

- 四类 MVP 故障（ADR-0007 §5）各产生预期 diagnosis，与故障 `expected_observations` 字段互证（靶场单一可归因症状原则——一故障一主候选）。
- evidence 链路端到端：diagnosis → journal_seq → pid/packet_index → artifact 可解析。
- 规则隔离：注入抛异常的测试规则，整体评估不失败。
- 事件 payload 过 schema 校验；`raised/updated/cleared` 生命周期与 SPEC-502 表状态一致。

## 10. 验收标准

- `REQ-DIA-306-001`：批处理评估接口落地，`run_completed` 触发路径贯通。
- `REQ-DIA-306-002`：四类故障各产生预期 diagnosis 且与 expected_observations 互证。
- `REQ-DIA-306-003`：每条 diagnosis 至少一条 evidence ref 且链路可解析直达 artifact。
- `REQ-DIA-306-004`：`diagnosis.*` 三事件 payload 过 schema，与 SPEC-502 表一致。
- `REQ-DIA-306-005`：只消费 observation 事件（无 TSDuck/TS 解析依赖，import-linter 可验证）。

## 11. 非目标与风险

- 不做规则内容定义（SPEC-307）、不做健康告警（SPEC-304）、不做自动修复。
- 不承诺统计概率：三档 confidence 无校准依据不得解释为概率（SPEC-003 §2.6 既有禁令）。
- 风险：诊断时机在 run 后——运行中 UI 只见观测事件不见诊断（可接受：八步闭环 Diagnose 在 Analyze 之后）。

## 12. 交付要求

建议文件：`app/domain/diagnosis/`（`engine.py` / `report.py` / `events.py`）。payload schema 文件 `schemas/diagnosis-record.schema.json` 随实现落地。

## 13. 参考

- SPEC-003 §2.6（Diagnosis 实体与 confidence 禁令）、SPEC-301 §4（事件注册表）、SPEC-502 §4/§5（diagnoses 表与 EventJournal）。
- [ADR-0005](../../../../adr/0005-architecture-baseline.md) 决策 4（依赖方向与 knowledge 范围）、[ADR-0007](../../../../adr/0007-fault-injection-pipeline-contract.md) 第 4/5 条（共用包序 frame、单一可归因症状）。

## Phase 2 补丁定点修订（随补丁票 [#138](https://github.com/BingChaoLiu/DVB-Nexus/issues/138)，DRAFT_FOR_REVIEW 0.6.0；依据：#136 补丁票评估 D-1）

现状锚定链在 Phase 2 证据事件上无字段映射（三条构造候选规则的 match 事件进不了引擎，diagnose 面零 hit）——结构性扩容，非缺陷回归。本修订全部 additive，MVP 形态逐字保留。

- **引擎输入族扩容（§2.1 additive）**：evaluation feed 在 `ts.*` 观测族之外新增 Phase 2 证据族（离散证据面，三类型）：`t2mi.plp_mismatch`（SPEC-602 §6）、`bbframe.recovery_failed`（SPEC-601 §5）、`biss.descramble_failed`（SPEC-611 §5）。证据面无 source/confidence 轴（SPEC-303 §Phase2 既有裁定——`ts.*` 保持唯一 observation 轴载体）；引擎只消费其 payload 作证据记录。`observation.*` 撤回纪律、journal envelope 形状（journal_seq 全序 / run_id correlation，ADR-0006）与交付策略均不动。
- **锚定链两态（§6 additive）**：MVP 形态 `diagnosis → event (journal_seq) → payload (pid / packet_index) → artifact_id` 不变。Phase 2 证据事件的 payload 无 pid/packet_index 定位字段，锚定链走**证据形态——locator 字段按命名空间映射**：

  | match 事件 | payload locator 字段 | 锚定语义 |
  |---|---|---|
  | `t2mi.plp_mismatch` | `expected_plp` / `actual_plp` + `business_absent_evidence`（plps_seen / bbframe_packet_count / filtered_packet_count / total_packet_count） | PLP 映射错位 + Inner TS 业务缺失证据 |
  | `bbframe.recovery_failed` | `first_failed_frame_index` + `failure_count` | 首失败帧定位 |
  | `biss.descramble_failed` | `failed_indices_sample`（有界样本，#126）+ `pid_scope` | 解扰失败包定位（fingerprint 互链面——密钥材料不入 payload，SPEC-610 §9） |

  artifact 解析两态：MVP 经 SPEC-502 `artifacts` 表（pid/packet_index 直达）；Phase 2 经事件引用链解析——`biss.*` 经 `key_fingerprint_ref` / `mutation_log_ref` 解析到 mutation log artifact，`t2mi.*` / `bbframe.*` 解析到该 run 的 Inner TS artifact（gen 层落库产物，SPEC-303 §Phase2）。
- **EvidenceRef 两态（§7 additive）**：`evidence` 共用形状 `{artifact_id, locator}`；MVP `locator = {pid, packet_index}`（既有三元组 wire 不破坏）；Phase 2 `locator` = 上表 payload 定位字段 verbatim（无对应定位字段的事件不虚填 pid/packet_index）。`diagnosis.*` 三事件 payload schema 同步 additive 放宽（schema 文件随实现落地）。
- **规则声明零改动**：四条候选规则声明两态通用（match `event_type` + payload 谓词不变，#130 已钉）——点亮 = 馈送扩容 + EvidenceRef 锚定形态，规则 JSON 与 MatchSpec 原语不动（SPEC-307 §Phase2 同步句）。
- **测试规格 additive（§9）**：SC-06/07/08 E2E 升级为 diagnose 候选断言（四规则各自在其证据事件上产生预期候选，与既有 journal 证据断言 + 规则符号互锁双轨并存）；锚定链路端到端：Phase 2 候选 → journal_seq → locator → artifact 可解析。
- SPEC-206（通关判定消费方）、SPEC-406（Training Lab UI 消费方）。
