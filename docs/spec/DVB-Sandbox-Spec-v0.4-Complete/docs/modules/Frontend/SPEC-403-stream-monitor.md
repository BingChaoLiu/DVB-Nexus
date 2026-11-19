---
spec_id: SPEC-403
title: Stream Monitor
version: 0.7.0
status: APPROVED
phase: MVP
owner: Frontend
priority: P0
depends_on: [SPEC-200, SPEC-302, SPEC-305, SPEC-306, SPEC-307, SPEC-206]
requirements: [REQ-UI-403-001, REQ-UI-403-002, REQ-UI-403-003, REQ-UI-403-004, REQ-UI-403-005, REQ-UI-403-006, REQ-UI-403-007]
---

# SPEC-403 — Stream Monitor（运行监控与诊断页）

## 1. 目标

定义 `/monitor` 路由区的页面实体：运行控制条（SPEC-200 §5 穷举迁移表驱动的六动作 + 状态徽章）、概览卡（summary + session 全量视图 + Run 触发面）、PID/指标表（SPEC-305 §5 扁平标量查询 + SPEC-302 §4 指标目录）、诊断列表（SPEC-307 §5 排序语义 + SPEC-306 payload + confidence 三档 + evidence locator 呈现位）、verify 结果卡（SPEC-206 三态 + 判据六 kind 明细）、alerts 融入呈现（无独立告警页），以及实时性纪律：journal/hint 帧节流重取（复用 SPEC-400 §6.3 失效桥，非流式推送渲染）。

诊断列表与 verify 结果卡的呈现组件**定义在本规格、以可复用形态导出**（#18 Q5 裁决）：SPEC-404（evidence locator 点击导航）与 SPEC-406（叠加场景语境）复用本票导出面，禁重复建设。UI 判定禁令（CONTEXT.md「通关」词条 + SPEC-400 §8）全文适用：verdict 三态与判据明细只渲染服务端返回，「无告警」≠「干净」，confidence 三档禁渲染为概率/分数。

范围级预批准：ticket [#18](https://github.com/BingChaoLiu/DVB-Nexus/issues/18)；实现票 #64。消费契约：SPEC-500 §4（REST）、SPEC-501 §3/§4/§5（WS）、SPEC-305 §5/§8（查询与 hint→REST 矩阵）、SPEC-302 §4/§6（指标目录与缺失≠零）、SPEC-306 §5/§6（诊断 payload）、SPEC-307 §5（排序矩阵）、SPEC-206 §4/§7（判定结果与判据 kind 闭集）、SPEC-200 §5/§6（生命周期穷举表与公开接口）。

## 2. 范围

### 2.1 In Scope

- `/monitor` 路由区页面实体（`src/features/monitor/`，SPEC-400 §4.1 目录契约下本票 OWN）。
- 运行控制条：六动作（validate/start/pause/resume/stop/dispose）按钮 + 九状态徽章；禁用矩阵由 SPEC-200 §5 穷举迁移表**表驱动**（禁硬编码 if 链）；409 `SIM_INVALID_LIFECYCLE_TRANSITION` 分支渲染与状态回同步。
- 概览卡：`GET .../observation/summary` 五字段 + `GET .../snapshot` 全量视图字段（`virtual_time_ns`/`node_states`/`active_faults`/`latest_artifact_refs`）。
- Run 触发面（概览卡内、E2E 闭环 Generate/Recover 步的 UI 承载面）：empty-plan run 提交（`POST .../runs`）+ run 状态轮询呈现；fault-plan 编辑器不在本票（Inject 步归 SPEC-406 场景语境）。
- PID/指标表：`POST .../metrics/query` 扁平标量体 + 15 项 MVP 指标目录呈现；`value=null` + quality `missing` 禁渲染成 0。
- 诊断列表：`GET .../diagnoses`（DiagnosisDTO[]）+ `POST .../runs/{run_id}/diagnose` 触发（DiagnosisReportDTO.candidates[]）；SPEC-307 §5 排序呈现；confidence 三档徽章；evidence locator `{artifact_id, pid, packet_index}` 可点击呈现位（点击导航归 SPEC-404）。
- verify 结果卡：`POST .../runs/{run_id}/verify` 请求面（baseline/recovery run 选择 + scenario 标识 + pass_criteria 表单）+ `VerificationResultDTO` 只读渲染（三态 verdict + 判据六 kind 明细 + NOT_EVALUATED 原因显式）。
- alerts 融入呈现：`GET .../alerts` 列表 + `observation.alert_changed` hint 触发重拉；空态文案显式「无告警记录 ≠ 干净」。
- 实时性编排：页面级 SessionStream 挂载 + `applyJournalFrame` journal 并入 + `attachHintBridge` hint 节流失效（250ms 合帧，复用 SPEC-400 §6.3，禁第二通道）。
- 诊断/verify 呈现组件可复用导出（`src/features/monitor/components/` 公开 barrel，签名见 §6）。
- SPEC-403 实体文本（本文件）+ SPEC-INDEX-FRONTEND 行链接更新。

### 2.2 Out of Scope

- 时间轴图表（SPEC-407 Timeline & Replay UI，`docs/roadmap.md` §3，#18 既裁不做）。
- 独立告警中心页（alerts 融入本页；无 `/alerts` 路由）。
- 自定义 dashboard（用户自组布局/挂件体系）。
- 流式曲线图（WS 帧直驱的连续曲线渲染；本票实时性 = 节流重取）。
- fault-plan 编辑器与场景驱动开局（SPEC-406；E2E Inject 步 owner 归 #67）。
- evidence locator 点击后的 hex/解码导航（SPEC-404；本票只交付呈现位与回调签名）。
- 事件浏览页（`observation_refs` 渲染为静态引用 chip：`journal_seq` + `event_type` 文本；MVP 无 events 路由可导航，SPEC-407 归 roadmap）。
- Python 侧任何变更（泵循环不扩展，见 §10 依赖申报；alerts 评估 tick 维持 #61 申报的未入泵状态）。

## 3. 术语

| 术语 | 定义 |
|---|---|
| 穷举迁移表 | SPEC-200 §5 的九状态迁移表；未列出的迁移一律非法（服务端 409） |
| wire 生命周期串 | `SessionViewDTO.lifecycle` 的小写字符串值（`created/validating/ready/running/paused/stopping/stopped/failed/disposed`，域枚举 `LifecycleState` 的 str 值；与 SPEC-200 §5 表名一一对应） |
| 禁用矩阵 | 当前状态 × 六动作的 enabled/disabled 表；由穷举迁移表派生（§7.1），非逐按钮硬编码 |
| 缺失≠零 | `value=null` 或 quality 含 `missing` 的指标点必须渲染为显式缺失态，禁渲染为数值 0（SPEC-302 §6 / SPEC-206 §6 同源纪律） |
| locator | 诊断 evidence 三元组 `{artifact_id, pid, packet_index}`（`DiagnosisEvidenceDTO`）；本票呈现可点击位，点击导航归 SPEC-404 |
| 三档 confidence | `low/medium/high`（SPEC-307 §6 规则静态声明）；禁展示为概率、分数或百分比 |
| 三态 verdict | `PASS/FAIL/INCONCLUSIVE`（SPEC-206 §4）；UI 只渲染 `POST .../verify` 返回值，任何本地状态不得推导通关结论 |
| 判据六 kind 闭集 | `fault_inactive/psi_pat_valid/psi_pmt_valid/pat_pmt_mapping_valid/cc_continuous/no_unexpected_cc_error`（SPEC-206 §7 冻结枚举） |
| 节流重取 | hint 触发的 REST 失效经 `createThrottledInvalidator` 合帧（默认 250ms 窗口，每键前缀一次）；journal 帧经 `applyJournalFrame` 全序并入事件缓存（journal_seq 排序 + 去重）——两者均复用 SPEC-400 §6.3，禁第二通道 |
| Run 触发面 | 概览卡内 empty-plan run 的提交按钮 + run 状态呈现（E2E Generate/Recover 步的 UI 承载面）；不含 fault-plan 编辑 |

## 4. 页面架构

### 4.1 路由区与页面骨架

- 路由注册沿用 SPEC-400 §4.2：`/monitor` 条目已由 #61 注册（`appRoutes` → `features/monitor/Region` 惰性加载），本票**原地替换占位 Region**，不改 `routes.tsx` 共享壳。
- 页面以 session 为作用域：`/monitor?session=<session_id>` 深链 + 会话列表区（0.5.1 修订，SPEC-408 §4.3/§6.1：主位 = 最近会话列表 `GET /api/v1/sessions`，演示一键 + 手输 UUID 降级为列表覆盖不到时的兜底）；无 `session` 参数时渲染会话列表区；未知/失效 session（深链 404 / WS 4404）渲染显式「未知会话态」而非报错堆栈（SPEC-408 §4.6）。
- 页面骨架（单页分区，自上而下）：控制条 → 概览卡 → Run 触发面 → PID/指标表 → alerts 面板 → 诊断列表（含 diagnose 触发）→ verify 表单与结果卡 → journal 流水尾窗（REQ-UI-403-007 呈现面）。
- SessionStream 生命周期与页面挂载/卸载绑定（subscribe on mount、close on unmount）；多 session 并发跟踪不在 MVP（一次一个作用域 session）。

### 4.2 运行控制条（REQ-UI-403-001）

- 九状态徽章：渲染 wire 生命周期串原样（小写 snake_case，禁自造别名/大小写转换）；徽章色调按状态分组（终态/异常/运行族），语义映射表驱动。
- 六动作按钮：validate/start/pause/resume/stop/dispose；enabled 矩阵由 §7.1 表驱动（穷举迁移表 + 动作目标态派生），终态（stopped/disposed）全禁、disposed 为吸收态。
- 动作→路由（SPEC-200 §6 + SPEC-500 §4.2）：validate/start/pause/resume/stop = `POST /api/v1/sessions/{id}/{validate|start|pause|resume|stop}`；dispose = `DELETE /api/v1/sessions/{id}`（204）。
- stop 幂等语义是服务端容忍（对 stopping/stopped 重复调用返回当前视图）；按钮矩阵按迁移表渲染（stopping/stopped 下 stop 禁用）——幂等性作为双击竞态的安全网，不作为启用依据。
- 动作在途（busy）：触发后禁用全部动作按钮直至应答；应答成功以响应 `SessionViewDTO.lifecycle` 回填状态；应答 409 `SIM_INVALID_LIFECYCLE_TRANSITION` 时以 `details.current` 回同步徽章、以 `details.allowed` 渲染合法目标提示，并触发 `qk.snapshot(sessionId)` 失效重拉（§8）。
- 状态未知（首次加载/重拉中）时按钮全禁、徽章显示占位态，禁猜测状态。

### 4.3 概览卡与 Run 触发面（REQ-UI-403-002）

- 概览卡数据 = `GET .../observation/summary`（`SummaryDataDTO` 五字段：`tenant_id/session_id/journal_seq_watermark/event_count/active_alert_count/schema_version`）+ `GET .../snapshot`（`SnapshotDTO`：`lifecycle/virtual_time_ns/node_states[]{node_id,health,ports}/active_faults/latest_artifact_refs/journal_seq_cursor`）。
- `node_states` 逐节点渲染 `health` 枚举串原样；`active_faults` 渲染 `fault_id/fault_type` 引用列表；`latest_artifact_refs` 渲染 `artifact_id/kind` 引用（点击导航归 SPEC-404 范畴，本票呈现位）。
- Run 触发面：一个「提交 Run（empty plan）」动作 = `POST .../runs`（`RunSubmitRequest{config, fault_plan: []}`）；提交后 202 `run_id`，经 `GET .../runs/{run_id}` 轮询至终态（`completed/cancelled/failed`），呈现 `status/packet_count/byte_count/artifacts[]{artifact_id,kind}`。config 来源：页面提供 golden 缺省 config 表单（SPEC-108 §4 wire 形状，值可编辑），E2E 与手动操作共用同一表单；fault_plan 输入面不在本票（恒空数组，SPEC-406 叠加场景语境）。
- run 标识注册表：页面维护本页已触发 run 的 id 列表（内存态，非第二事实源——事实以 `getRun` 应答与 journal 为准），供诊断/verify 表单的 run 选择器取值；journal 中观测到的 `simulation.run_*` 事件 `scope.run_id` 一并并入选择器候选。
- summary 重取时机：挂载、控制条动作成功后、手动刷新；不在 hint 矩阵内（SPEC-305 §8 无 summary 行，禁自建重取通道）。

### 4.4 PID/指标表（REQ-UI-403-003）

- 查询 = `POST .../metrics/query`（`MetricsQueryBody` 扁平标量）：`metric_names[]`（§5 目录子集，默认全 15 项）、`start_ns/end_ns`（数值 ns）、`step_ns`、`clock_domain`（仿真查询恒 `sim:<session_id>`，必填——缺省/混形状由服务端 422 拒绝）、`allow_unknown=false`；窗口默认 `0..snapshot.virtual_time_ns`，step 页面常量缺省（可调输入）。
- 呈现 = `MetricsDataDTO.series[]` 逐序列行：`metric_name`（wire 名逐字）+ `unit` + `aggregation` + 点列；每点渲染 `value` + `quality` + `revision/is_final`（非终值显式标注）。
- 缺失≠零：`value === null` 或 `quality` 含 `"missing"` 的点渲染显式缺失徽记（「缺失」），禁渲染 0、禁跳过不标（§7.4）。
- PID 维度呈现：按 `dimensions.pid`（有界数值维度，SPEC-302 §5 白名单）分组/过滤；无 pid 维度的序列归「会话级」组。
- 重取 = `observation.metric_updated` hint → `qk.metrics(sessionId)` 失效（#61 桥既有映射，250ms 合帧）。
- 重取时机补充：查询参数变更（窗口/step/metric 集合）即时重拉（用户动作，非 hint 通道）。

### 4.5 诊断列表（REQ-UI-403-004）

- 数据 = `GET .../diagnoses`（`DiagnosisDTO[]`，含 `state: raised|cleared`）+ 触发 `POST .../runs/{run_id}/diagnose`（幂等，`DiagnosisReportDTO`：`candidates[]/warnings`，404-until-drained 语义由触发面重试承担，§7.5）。
- 排序呈现 = SPEC-307 §5 矩阵：**priority 升序 → severity 降序（critical 最前）→ code 字典序**；比较器为导出的纯函数（§6），列表与候选两组件共用；禁引入任何其他排序键（服务端已排序时结果一致）。
- severity 四档 `info/warning/error/critical`、confidence 三档 `low/medium/high` 皆渲染枚举串原样徽章；confidence 禁渲染为概率/分数/百分比（CONTEXT.md 诊断词条硬禁令）。
- 每行渲染字段（wire 名原样）：`code/severity/confidence/state/rule_id/rule_version/priority(候选)/raised_at/cleared_at`；`observation_refs[]{journal_seq,event_type}` 渲染为静态引用 chip；`affected_node_ids[]`/`suggested_actions[]` 渲染列表。
- evidence locator（`DiagnosisEvidenceDTO{artifact_id,pid,packet_index}`）渲染为可点击呈现位（按钮/链接语义），点击回调 `onEvidenceSelect(locator)` 对外导出——SPEC-404 在该回调上接导航；本票自身不导航、不解码。
- `state=cleared` 行视觉弱化但保留（不清除历史）；cleared_at 显式呈现。

### 4.6 verify 结果卡（REQ-UI-403-005）

- 请求面 = `POST .../runs/{run_id}/verify`（`VerifyRunRequest`）：`baseline_run_id` + `recovery_run_id`（路径参数）选择器（候选 = §4.3 run 标识注册表 + 手动输入）、`scenario{scenario_id,version,content_hash}` 文本输入、`pass_criteria[]` 表单（`criterion_id` 文本 + `kind` 六 kind 闭集下拉 + `mandatory` 布尔 + `fault_id` 可选，min 1 条由表单校验承担）。
- `ui_state` 请求字段**不使用**（引擎显式忽略且不持久；禁作证据通道）。
- 结果卡只读渲染 `VerificationResultDTO`：`verdict`（`PASS|FAIL|INCONCLUSIVE` 三态，枚举串原样）+ `criteria[]{criterion_id,kind,mandatory,result,reason_code,reason}`（`result: PASS|FAIL|NOT_EVALUATED` 三值；`NOT_EVALUATED` 必须显式渲染其 `reason_code/reason`，禁静默）+ `evidence_refs` + `summary` + `verified_at_utc_ms`。
- 禁止本地推断：卡片不推导 verdict、不聚合判据、不按本地规则改写服务端结论（含「mandatory 全 PASS ⇒ PASS」类聚合——那是引擎职责，UI 只显示返回值）；请求成功前不渲染任何卡片结论态。
- 判据 kind 下拉候选 = 六 kind 闭集逐字；服务端 `SIM_VERIF_CRITERION_INVALID` 拒绝时表单回显错误（§8）。

### 4.7 alerts 融入呈现（REQ-UI-403-007 数据面）

- 数据 = `GET .../alerts`（`AlertsDataDTO{items[],total}`；`AlertRecordDTO{alert_id,fingerprint,rule_id,rule_version,state,severity,summary,evidence_refs,suppressed}`）；渲染列：`state/severity/rule_id/summary/suppressed`。
- 重取 = `observation.alert_changed` hint → `qk.alerts(sessionId)` 失效（#61 桥既有映射）。
- 空态文案显式「无告警记录（≠ 干净）」——无记录不是「观测确认无错误」（SPEC-206 §6 对偶纪律的呈现面表达）；`suppressed` 记录显式标注不隐藏。

### 4.8 实时性编排（REQ-UI-403-007）

- 页面挂载 `SessionStream({sessionId, onJournal, onHint, onReady, onStatus})`（SPEC-400 §4.4 客户端，禁第二 WS 通道）；journal 帧 → `applyJournalFrame(queryClient, sessionId, envelope)` 全序并入 `qk.events(sessionId,'journal')`；hint 帧 → `attachHintBridge(queryClient, stream, {sessionId})` 五主题失效（`observation.event_appended` 不触发 REST 重取——journal 帧自带事实）。
- 节流参数复用 SPEC-400 既有常量 `HINT_THROTTLE_MS = 250`；禁另设第二套节流/合帧机制。
- 呈现面 = journal 流水尾窗（最近 N 条信封的 `journal_seq/event_type/severity/producer.producer_id` 表格，只读）；这是「非流式推送渲染」的可见表达：帧进缓存、组件经查询缓存读取，不做逐帧直驱 DOM、不做曲线/图表。
- 重连纪律沿用 SPEC-501 §5/§8（`SessionStream` 内建）；慢消费 1013 续传 cursor 由客户端处理，页面无感知。
- WS 状态（connecting/ready/reconnecting/closed）在页头以中性徽章呈现（best-effort 提示层的可见性，不承载判定语义）。

### 4.9 组件复用导出面（REQ-UI-403-006）

- 公开 barrel：`src/features/monitor/components/index.ts`；导出签名冻结于 §6。SPEC-404 消费 `onEvidenceSelect` 回调位；SPEC-406 复用 `DiagnosisList`/`DiagnosisCandidateList`/`VerifyResultCard` 并经 `context` 叠加场景语境（标题前缀、场景徽章、跳转入口等），叠加不得改变判据明细/三态/排序的服务端事实渲染。

## 5. 数据模型（消费 DTO 逐字段，wire snake_case 原样）

本票不定义新 wire 类型；全部响应类型取自 `src/api/schema.gen.ts`（SPEC-400 §7.1 生成权威，禁手改）。关键形状：

- `SessionViewDTO`/`SnapshotDTO`：`session_id/revision/lifecycle/virtual_time_ns/topology_revision/node_states?/active_faults?/latest_artifact_refs?`（Snapshot 另有 `connection_states?/journal_seq_cursor?`——cursor 仅回显）。
- `SummaryDataDTO`：`tenant_id/session_id/journal_seq_watermark/event_count/active_alert_count/schema_version`。
- `MetricsQueryBody`：`metric_names[]/start_ns/end_ns/step_ns/clock_domain/filters?/max_points?/aggregation_override?/allow_unknown`（扁平标量；仿真查询 `clock_domain="sim:<session_id>"` 必填；`*_ns` 数值与 ISO 串禁混形状）。
- `MetricPointDTO`：`start_ns/end_ns/value(number|object|null)/quality(string[])/revision/is_final`；`MetricSeriesDTO`：`metric_name/unit/value_type/aggregation/clock_domain/dimensions?/points?/provenance?`。
- 15 项 MVP 指标目录（SPEC-302 §4，名称逐字）：`ts.packet_rate`、`ts.bitrate`、`ts.continuity_error_total`、`ts.pcr_jitter_ns`、`ts.pcr_repetition_gap_ns`、`ts.null_packet_ratio`、`ts.scrambled_packet_ratio`、`psi.section_repetition_gap_ms`、`simulation.virtual_time_ns`、`simulation.event_lag_ns`、`topology.degraded_node_count`、`observation.ingest_events_total`、`observation.duplicate_events_total`、`observation.consumer_lag_events`、`observation.alerts_active`。
- `DiagnosisDTO`：`diagnosis_id/session_id/run_id/rule_id/rule_version/code/severity/confidence/observation_refs[]{journal_seq,event_type}/affected_node_ids[]/suggested_actions[]/state/raised_at/cleared_at?`；`DiagnosisCandidateDTO` 另有 `priority/title/summary/evidence{artifact_id,pid,packet_index}`；`DiagnosisReportDTO`：`session_id/run_id/candidates[]/warnings[]`。
- `VerificationResultDTO`：`session_id/recovery_run_id/baseline_run_id/scenario{scenario_id,version,content_hash}/verdict/criteria[]{criterion_id,kind,mandatory,result,reason_code?,reason?}/evidence_refs[]/summary/verified_at_utc_ms`。
- `AlertsDataDTO`/`AlertRecordDTO`：§4.7 字段面。
- `RunAcceptedDTO{run_id}`/`RunStatusDTO{run_id,status,packet_count?,byte_count?,artifacts?[]{artifact_id,kind,...},warnings?}`。

## 6. 公开接口（本票对下游的导出面，签名级冻结）

```ts
// src/features/monitor/components/index.ts —— SPEC-404/406 消费 barrel（additive 冻结面）
import type { DiagnosisDTO, DiagnosisEvidenceDTO, DiagnosisCandidateDTO,
              VerificationResultDTO } from "../../api/schema.gen";
import type { ReactNode } from "react";

/** SPEC-307 §5 排序矩阵的纯函数：priority 升序 → severity 降序 → code 字典序。 */
export function orderDiagnoses<T extends Pick<DiagnosisDTO, "code" | "severity" | "priority">>(
  rows: readonly T[],
): T[];
// 注：DiagnosisDTO 无 priority 字段（priority 在候选 DTO 上）——实现以
// 「有 priority 用之，无则视为 +∞（排在有值之后）」的宽容比较器落地，
// 列表与候选共用；精确签名随实现定稿，语义以本条为准。

export interface DiagnosisSharedProps {
  /** SPEC-404 点击入口：locator 三元组原样上抛，本组件不导航。 */
  onEvidenceSelect?: (locator: DiagnosisEvidenceDTO, row: DiagnosisDTO | DiagnosisCandidateDTO) => void;
  /** SPEC-406 场景语境叠加位（标题/徽章/脚注），渲染在组件头部，不触碰事实行。 */
  context?: ReactNode;
}

/** diagnoses 表行列表（GET .../diagnoses 的 DiagnosisDTO[]）。 */
export function DiagnosisList(props: DiagnosisSharedProps & {
  diagnoses: readonly DiagnosisDTO[];
}): ReactElement;

/** diagnoseRun 报告候选列表（DiagnosisReportDTO.candidates[]，含 priority/title/evidence）。 */
export function DiagnosisCandidateList(props: DiagnosisSharedProps & {
  candidates: readonly DiagnosisCandidateDTO[];
}): ReactElement;

/** verify 结果卡：只读渲染 VerificationResultDTO（禁本地推断；NOT_EVALUATED 显式原因）。 */
export function VerifyResultCard(props: {
  result: VerificationResultDTO;
  context?: ReactNode;
}): ReactElement;
```

- 组件为**受控纯呈现**（数据由调用方给入），内置查询与失效不进导出面（SPEC-406 在自己的查询编排里取数后传入）。
- 页面内部组件（ControlBar/OverviewCard/MetricsPanel/AlertsPanel/journal 尾窗/useSessionStream）**不在**导出面（SPEC-406 的复用点是上述三组件 + 比较器；SPEC-404 的消费点是 locator 回调位）。

## 7. 处理算法

### 7.1 生命周期禁用矩阵（表驱动，REQ-UI-403-001）

迁移表（SPEC-200 §5 逐字；wire 串小写）：

```text
created    -> validating
validating -> ready | failed | stopping      # 验证失败直达 failed；验证期可取消
ready      -> running | failed | stopping    # start 失败可直达 failed
running    -> paused | failed | stopping
paused     -> running | failed | stopping
failed     -> stopping | disposed            # failed 可直达 disposed
stopping   -> stopped
stopped    -> disposed
```

动作→目标态与启用集（由上表派生，实现为两张常量表 `LIFECYCLE_TRANSITIONS` / `STATE_ACTIONS`，单测对九状态 × 六动作穷举断言）：

| 动作 | 目标态 | 启用于 | 路由 |
|---|---|---|---|
| validate | validating | created | POST .../validate |
| start | running | ready | POST .../start |
| pause | paused | running | POST .../pause |
| resume | running | paused | POST .../resume |
| stop | stopping | validating, ready, running, paused, failed | POST .../stop（stopping/stopped 下服务端幂等，按钮禁用） |
| dispose | disposed | failed, stopped | DELETE .../{id}（204） |

- disposed 为吸收态：全动作禁用。created 无 dispose 边（迁移表无 `created -> disposed` 行），dispose 在 created 下禁用——以表为准，不做「方便性」例外。
- 实现为 `isActionEnabled(state, action)` 纯查询 + 常量表；组件渲染 `STATE_ACTIONS[state]` 的启用集，禁逐按钮 if 链。

### 7.2 动作编排与 409 回同步（REQ-UI-403-001）

1. 点击启用动作 → busy 锁（全按钮禁用）→ 调对应端点函数。
2. 2xx：以响应 `lifecycle` 回填徽章；`qk.snapshot(sessionId)` 失效重拉（概览卡同步）。
3. `ApiError` 且 `errorCode === "SIM_INVALID_LIFECYCLE_TRANSITION"`：以 `details.current` 回同步徽章（服务端视图权威）、以 `details.allowed` 渲染「当前状态 + 合法目标」提示行；不弹裸错误堆栈。
4. 其他错误码按 §8 通用分支；busy 锁在 any 分支上都释放。

### 7.3 诊断排序比较器（REQ-UI-403-004）

- 比较键序列：`priority`（缺省视为 `+∞`，稳定排在有值之后）升序 → `severity` 降序（档位权重 `info<warning<error<critical`，critical 最前）→ `code` 字典序升序；同键以原序稳定（`Array.prototype.sort` 稳定性）。
- 输入已按服务端排序时输出不变（幂等）；比较器导出供列表与候选组件共用（§6）。

### 7.4 缺失≠零渲染规则（REQ-UI-403-003）

- 点级判定：`value === null` ⇒ 缺失态；`quality` 数组含 `"missing"` ⇒ 缺失态（两者独立触发）；缺失态渲染徽记 + `start_ns`，数值列渲染占位「—」，禁 `0`、禁省略行。
- `is_final === false` 的点追加「非终值」标注；`revision > 1` 显式呈现修订号。

### 7.5 diagnose 触发重试（REQ-UI-403-004）

- `POST .../runs/{run_id}/diagnose` 对 404（run 观测尚未入账）在有限窗口内重试（复用 E2E helper 的 404-until-drained 姿态）；超窗显式失败态。端点幂等（SPEC-306 §5），重复触发安全。

### 7.6 节流重取编排（REQ-UI-403-007）

- journal 帧：`applyJournalFrame`（journal_seq 排序 + 按 seq 去重，重放容忍）→ `qk.events(sessionId,'journal')` 缓存更新 → 尾窗组件经 useQuery 读取渲染。
- hint 帧：`attachHintBridge` 既有映射（metric_updated→metrics / alert_changed→alerts / health_changed→health / export_progress→export）→ `createThrottledInvalidator` 250ms 合帧 → 每键前缀一次 `invalidateQueries`。
- 页面级行为测试义务（§11）：hint 风暴合帧为单失效、journal 并入有序去重、event_appended 不触发 REST 重取——三条都在页面挂载真实桥的条件下断言（复用 #61 桥测试之上的页面级断言，不复制桥实现测试）。

## 8. 错误处理

| 场景 | 处理 |
|---|---|
| 409 `SIM_INVALID_LIFECYCLE_TRANSITION` | §7.2 回同步 + `details{current,target,allowed}` 渲染 |
| 404（diagnose run 未入账） | §7.5 有界重试后显式失败 |
| 422（metrics 混形状 / verify 判据 kind 非法 `SIM_VERIF_CRITERION_INVALID`） | 表单内联回显 `ApiError.message` + `errorCode`，请求体不发送变更 |
| 4xx/5xx 通用 | `ApiError{status,errorCode,message,retryable,details,requestId}` 渲染错误条（requestId 显示供追溯）；`retryable` 决定是否呈现重试按钮 |
| 查询失败（RT network） | 查询缓存错误态渲染分区空态 + 重试；禁把失败渲染为「零值/干净」 |
| 指标点缺失 | §7.4；缺失态是数据事实的呈现，不是错误 |
| alerts 空 | 「无告警记录（≠ 干净）」显式空态 |
| WS 关闭（4404 session 未知/disposed） | `SessionStream` 终止重连（PERMANENT 码），页头状态徽章呈现 closed；页面数据保留最后一致视图 |

## 9. 资源约束

- 单页一次一条 WS 连接（单连接单 session，SPEC-501 §3）；卸载即 close。
- journal 尾窗仅渲染最近 N 条（页面常量，默认 50）；完整事件浏览不在本票。
- metrics 查询 `max_points` 页面缺省（默认 240/序列）；窗口/step 用户可调但受服务端范围上限约束。
- 无轮询定时器（除 run 状态轮询单一计时器：200ms 间隔、30s 超窗）；其余新鲜度全部走 hint 节流失效。

## 10. 依赖

- 上游规格：SPEC-200（生命周期穷举表）、SPEC-302（指标目录/缺失≠零）、SPEC-305（查询 API + hint→REST 矩阵）、SPEC-306（诊断 payload）、SPEC-307（排序矩阵/规则表）、SPEC-206（判定三态/判据闭集）。
- 上游实现（#61，禁第二通道）：`src/api` barrel 全部端点函数与 `ApiError`；`src/query`（`qk`/`attachHintBridge`/`applyJournalFrame`/`createThrottledInvalidator`/`HINT_THROTTLE_MS`）；`src/ws/SessionStream` + `closeCodes`/`topics`；`src/components/ui`（Badge/Panel/EmptyState）；`routes.tsx` 既有 `/monitor` 条目。
- 下游消费：SPEC-404（locator 点击导航）、SPEC-406（组件复用 + 场景语境叠加）——导出面 §6。
- **泵循环申报**：告警评估 tick（`bootstrap.app.ProductionStack.evaluate_alerts`）维持 #61 申报的未入泵状态，本票**不扩展** `src/bootstrap/asgi.py` 泵循环。理由：(a) `evaluate_alerts(session_id, now_ns, clock_domain, ...)` 需要显式时钟语义（now_ns/clock_domain/clock_epoch 的来源选择属告警域语义裁定，不是 UI 票的嵌入决定）；(b) 本票 alerts 呈现义务是「查询 + hint 重拉纪律」，可由契约/种子测试覆盖（AlertsDataDTO 渲染 + alert_changed→qk.alerts 失效行为测试）；(c) SPEC-305 §8 恢复协议保证 hint 丢失/未发射时重连全量拉取的正确性不依赖泵。若后续需要真流告警，属后端伴随票（时钟语义裁定 + 泵扩展 + ALLOWED_501/契约面），届时 additive 接入。

## 11. 测试向量

- **矩阵穷举单测**：九状态 × 六动作 enabled 断言表（§7.1 表逐格）；迁移表常量与 SPEC-200 §5 逐行对拍。
- **排序比较器**：priority 升序、severity 降序（critical 最前）、code 字典序、priority 缺省排尾、稳定性。
- **缺失≠零**：`value:null` 与 `quality:["missing"]` 两路均渲染缺失徽记、不渲染 0；`is_final:false` 标注。
- **verify 卡**：三态各一 fixture（PASS/FAIL/INCONCLUSIVE）；NOT_EVALUATED 行显式 reason 渲染；六 kind 字面串渲染；断言形状不快照 DOM。
- **诊断列表/候选**：wire 字段渲染断言（键名/枚举串）；locator 呈现位点击回调上抛三元组原样；confidence 徽章为枚举串（禁数字断言存在）。
- **节流重取行为（REQ-UI-403-007 验收锚）**：页面挂载 + 注入测试 stream（`ws/testSupport` 姿态）——(a) 5 条 journal 帧乱序到达 → 尾窗按 seq 升序、重复 seq 去重；(b) 同前缀 5 次 hint 在 250ms 窗内 → `invalidateQueries` 恰 1 次；(c) `observation.event_appended` → 0 次 REST 失效；(d) `alert_changed` → `qk.alerts` 前缀失效。
- **控制条 409 分支**：mock 409 信封 → 徽章回同步 `details.current`、`allowed` 提示渲染。
- **组件导出面**：barrel 冻结签名编译断言（typecheck 即门）+ 受控渲染冒烟。
- **E2E**：`closed-loop.spec.ts` 本票名下步骤翻转为 UI 驱动（Generate/Diagnose/Recover/Verify——文件标注 owner #64/#64/#64+#67/#64+#67；Inject owner #67、Inspect owner #65 维持 rest，禁动他票步骤与 Analyze 跳过标注）；新增 `e2e/monitor.spec.ts`（可选面）：控制条动作链（validate→start→pause→resume→stop→dispose）徽章/禁用矩阵真后端冒烟 + 概览卡字段呈现。

## 12. 验收标准

- **AC-403-01（REQ-001）**：控制条动作与状态徽章与 SPEC-200 §5 穷举表一致——九状态×六动作矩阵穷举单测绿；409 分支回同步行为测试绿；矩阵实现为表驱动（代码无逐按钮 if 链）。
- **AC-403-02（REQ-002）**：概览卡渲染 `SummaryDataDTO` 五字段 + snapshot 视图字段（wire 名原样）；Run 触发面可提交 empty-plan run 并轮询呈现终态与 artifacts 引用。
- **AC-403-03（REQ-003）**：指标表按扁平标量体查询（`clock_domain="sim:<session_id>"`）；15 项目录名称逐字呈现；`value=null`/`quality missing` 渲染缺失态禁 0；非终值/修订标注可见。
- **AC-403-04（REQ-004）**：诊断列表排序呈现与 SPEC-307 §5 矩阵一致（比较器单测绿）；severity 四档/confidence 三档枚举串原样徽章，confidence 无任何数值渲染；locator 呈现位可点击且回调上抛 `{artifact_id,pid,packet_index}` 原样；raised/cleared 语义正确（cleared 保留弱化）。
- **AC-403-05（REQ-005）**：verify 卡三态与判据明细渲染对齐 SPEC-206（三 fixture 单测绿）；NOT_EVALUATED 显式原因；页面无任何本地 verdict 推导路径（代码审查项：卡片仅消费 `VerificationResultDTO`）；判据 kind 输入限定六 kind 闭集。
- **AC-403-06（REQ-006）**：`src/features/monitor/components` 导出 barrel 冻结（§6 签名）；#65/#67 派工词可直接引用该清单；复用组件在无 context 时渲染默认形态。
- **AC-403-07（REQ-007）**：节流重取行为测试绿（合帧单失效/journal 有序去重/event_appended 零 REST 失效三断言）；页面无第二 WS 通道、无第二节流机制、无流式曲线/时间轴渲染。
- **AC-403-08（SPEC-408 §4.3 引导层，0.5.1 增）**：会话列表区三件套落位（最近会话列表主位 + 演示一键保留 + 手输 UUID 降级兜底）；未知/失效 session 显式「未知会话态」；「来源场景」回跳链接（增量①落地后）；verify 表单可编辑预填（scenario_id ← 会话详情、version/content_hash ← 场景详情、baseline/recovery ← run 列表 datalist）且 run 永不自动猜；空态三问文案按 SPEC-408 §4.6 Monitor 组落位——契约与验收细则以 SPEC-408 §4.3/§6/§12.1 为准。

## 13. 非目标

- 时间轴图表、事件浏览页、流式曲线图（SPEC-407 roadmap）。
- 独立告警中心页、自定义 dashboard。
- fault-plan 编辑器、场景库/开局（SPEC-406）；evidence 点击后的 hex/解码（SPEC-404）。
- 多 session 并发监控、session 搜索（0.5.1 修订：原「session 列表/搜索（无后端通路）」中列表半句已随 SPEC-408 §6.1 只读端点落地并由 §4.3 会话列表区承接，非目标撤销；搜索类能力仍不做）。
- 泵循环扩展（`evaluate_alerts` 入泵属后端伴随票，§10）。
- verdict 本地推导、confidence 概率化、「无告警=干净」呈现（UI 判定禁令，永久禁令非 MVP 裁量）。

## 14. 兼容性与交付要求

- 分支 `ticket/m5-64-stream-monitor`；合并序列与全门遵循 SPEC-005 §9 与派工词（前端五门 + 后端三门 + check_specs）。
- `routes.tsx` 共享壳零改动（`/monitor` 条目 #61 已注册）；`src/api`/`src/ws`/`src/query`/`src/components/ui` 只消费不修改；`features/topologies/**`、`features/lab/**` 不触碰（并行票文件面不相交）。
- 全部响应类型取自 `schema.gen.ts`；若实现期间发现类型缺口，走 `dto-supplement.ts` 收窄机制申报，禁手改生成文件。
- 交付物含：本规格文本（批准后转正）、SPEC-INDEX-FRONTEND 行链接、IMPLEMENTATION_REPORT（首节「下游接口清单」：#65 消费 locator 点击位签名、#67 消费组件复用签名 + 场景语境叠加点）。
- 文本/徽章一律渲染 wire 枚举串原样（snake_case）；禁前端自造别名、大小写转换或本地编码表之外的语义改写。

## Phase 2 定点修订（随落笔票 #119，DRAFT_FOR_REVIEW 0.6.0；依据：细裁 [#114](https://github.com/BingChaoLiu/DVB-Nexus/issues/114)）

- **view 参数透传句**：包检查器组件定义在 SPEC-404（复用边界既裁不变）；Monitor 侧深链/入口对 view 参数原样透传，不自造视图语义。
- **新命名空间事件呈现**：t2mi.*/bbframe.*/biss.* 事件（SPEC-303 Phase 2 修订章）进入 journal 尾窗与诊断候选明细的自然消费（注册表驱动，无面板新增）；「解扰失败 ≠ 码流损坏」「缺失 ≠ 零」诚实纪律句随事件文案落位。
- 观测类判据口径维持诚实 INCONCLUSIVE（SPEC-408 §10 申报 1 延续）。

## Phase 3 定点修订（随落笔票 #158，DRAFT_FOR_REVIEW 0.7.0；依据：细裁 [#152](https://github.com/BingChaoLiu/DVB-Nexus/issues/152) Q4/Q5、[#153](https://github.com/BingChaoLiu/DVB-Nexus/issues/153)）

- **Monitor 消费 `rf.*` / `sec.*` 事件**：`rf.state_observed` / `sec.state_observed` 进时间线（注册表驱动呈现、零特制视图，照 #114/#119 先例）；payload 为 NodeEvalResult 形状 JSON-safe metrics。
- **告警呈现两条**：`TUNER_UNLOCKED`（warning）/ `BER_SEVERE`（error）进既有告警面（SPEC-304 Phase 3 修订注册）；`elevated` 档不告警（留给 SPEC-307 诊断候选组合，两轴不混）。
- **诚实口径维持**：快照事件来源 = `state_evaluator`、置信度 = simulated——呈现层不得混标 parsed/measured（CONTEXT.md 观测轴纪律）；`topology.state_changed` 呈现照既有义务。
