---
spec_id: SPEC-406
title: Training Lab
version: 0.5.0
status: APPROVED
phase: MVP
owner: Frontend
priority: P0
depends_on: [SPEC-205, SPEC-206]
requirements: [REQ-UI-406-001, REQ-UI-406-002, REQ-UI-406-003, REQ-UI-406-004, REQ-UI-406-005, REQ-UI-406-006, REQ-UI-406-007]
---

# SPEC-406 — Training Lab（训练实验页）

## 1. 目标

定义 `/lab` 路由区的页面实体：场景库列表（`GET /api/v1/scenarios`，Lab Pack v1 SC-01~05）、场景详情渲染（目标/分阶段 hints/步骤/pass_criteria，消费 `GET /api/v1/scenarios/{id}` 导出面——`hidden_reference_solution` 结构性缺席）、建实验 session（`POST /api/v1/sessions` 携 `scenario_id`，topology/seed/clock/deterministic 全部由场景文档治理——请求内同名字段 permissive-ignored）、hints 渐进揭示（点击展开下一层，纯前端组件态、无后端参与）、通关结果卡（复用 SPEC-403 §6 导出的 `VerifyResultCard`/`DiagnosisList`/`DiagnosisCandidateList` 并经 `context` 叠加场景语境 + 诊断候选跳转接线）、八步闭环 stepper（Create→Generate→Inject→Analyze→Diagnose→Inspect→Recover→Verify 顶部指示，状态源 = 可观测服务端事实映射）、`hidden_reference_solution` 通关后展开（PASS 门控 + `GET /api/v1/scenarios/{id}/solution?session_id=` 后端 reveal 通路）。

通关纪律（CONTEXT.md「通关」词条 + SPEC-400 §8，全文适用）：UI 只渲染 SPEC-206 三态判定与判据明细；verdict 只读服务端 `VerificationResultDTO.verdict`；UI 状态、按钮变绿、stepper 步进都**不是**通关证据；「无告警/无记录」≠「干净」适用一切空态文案；通关（PASS）前不请求、不渲染 `hidden_reference_solution`。

范围级预批准：ticket [#18](https://github.com/BingChaoLiu/DVB-Nexus/issues/18)；实现票 #67。消费契约：SPEC-205 §3/§4/§5/§6/§7（场景文档格式/安全校验/执行模型/hints/错误码）、SPEC-206 §4/§6/§7（三态判定/观测语义对偶/判据六 kind 闭集）、SPEC-500 §4.7（scenario 三路由）+ §4.2/§4.3/§4.5/§4.6（session/run/diagnose/verify）、SPEC-403 §6（可复用组件导出面）、SPEC-400 §4/§5/§6.3（架构/查询词表/失效桥）。

## 2. 范围

### 2.1 In Scope

- `/lab` 路由区页面实体（`src/features/lab/`，SPEC-400 §4.1 目录契约下本票 OWN；占位 Region 原地实体化，`routes.tsx` 共享壳零改动）。
- 场景库列表（REQ-UI-406-001）：`qk.scenarios()` 查询缓存 + `GET /api/v1/scenarios`（`ScenarioSummaryDTO[]`：`scenario_id/version/title/difficulty`），逐行渲染四字段 + 「开始实验」入口；空库渲染显式空态（注册表无文档 ≠ 错误）。
- 场景详情渲染（REQ-UI-406-002）：`qk.scenario(id)` + `GET /api/v1/scenarios/{id}`（`ScenarioDetailDTO` 导出面）；渲染 `title/difficulty`、`objectives[]`（实验步骤编号列）、`hints[]`（分阶段揭示梯子，§4.4）、`pass_criteria[]`（`criterion_id/kind/mandatory/fault_id` 逐行，kind 六 kind 闭集串原样）；`initial_topology` 的 camelCase 岛（`nodeId/nodeType/ports[].portId/direction/plane/maxConnections`、`from/to{nodeId,portId}`）以只读结构视图呈现（#45 canonical-example 权威，禁键名转写）。
- 建实验 session（REQ-UI-406-003）：「开始实验」动作 = `POST /api/v1/sessions`（body 携 `scenario_id` + 场景文档自身 `simulation_config`/`initial_topology` 投影值——服务端场景分支文档治理、请求同名字段 permissive-ignored）→ 201 `lifecycle:"ready"` → `POST .../start` → `running`（runs 面要求 RUNNING session；两跳均为可观测服务端事实）。
- hints 渐进揭示（REQ-UI-406-004）：「揭示下一条提示」按钮按文档数组顺序逐条展开（一层 = 一条 hint）；揭示计数为纯前端组件态（无后端参与、无持久化）；`level/trigger/content/requirement_ids[]/standard_ref` 渲染文档原文。
- 通关结果卡（REQ-UI-406-005）：`POST .../runs/{run_id}/verify`（请求体 = §7.4 形状）→ 复用 SPEC-403 `VerifyResultCard`（`context` 叠加场景语境）三态只读渲染 + `DiagnosisList`/`DiagnosisCandidateList`（diagnose 报告候选 + diagnoses 表行）；诊断候选 `onEvidenceSelect` 跳转接线（§7.6 双预案）。
- 八步闭环 stepper（REQ-UI-406-006）：页面顶部八步指示条（Create→Generate→Inject→Analyze→Diagnose→Inspect→Recover→Verify，CONTEXT.md 八步闭环逐字）；状态映射表 §7.3——每步布尔值来源于持有的服务端 DTO/wire 事实，禁任何本地业务推断。
- `hidden_reference_solution` 通关后展开（REQ-UI-406-007）：参考解面板默认锁定；仅当页面持有的 `VerificationResultDTO.verdict === "PASS"`（即结果卡渲染的同一 verdict 字段）时解锁「展开参考解」；点击 → `GET /api/v1/scenarios/{scenario_id}/solution?session_id=`（裁定 F 后端门）→ 200 渲染 `hidden_reference_solution`（`null` 显式「本场景未声明参考解」）；非 PASS 不发请求。
- Lab Pack v1 场景文件创作（#17 结构冻结即预批准；票面 REQ-UI-406-001 创作义务）：仓库顶层 `scenarios/` 五文件 SC-01~05（§4.7 创作规约；每文件过生产 loader 校验）。
- API 端点面 additive：`src/api/endpoints/scenarios.ts`（三函数）+ `src/api/index.ts` 一行 barrel 导出（#62 topologies.ts 先例）。
- E2E：`e2e/closed-loop.spec.ts` 仅 Create/Inject 两步 additive 翻转（owner #67，文件头映射注释同步）；新增 `e2e/lab.spec.ts`（全链真后端）。
- SPEC-406 实体文本（本文件）+ SPEC-INDEX-FRONTEND 行链接更新。

### 2.2 Out of Scope

- 计分、进度存档、多用户（#18/#17 既裁不做；揭示计数与 run 注册表均为页面内存态，刷新即复位——诚实呈现，不伪装续接）。
- 场景编辑器（#17 既裁；场景编写归实现流程，本票只交付 Lab Pack v1 五文件）。
- fault-plan 编辑器（Inject 提交的 plan = 场景文档 `fault_plan` 原文，禁 UI 改写）。
- 证据 hex/解码呈现（SPEC-404 面；本票只交付 locator 跳转接线）。
- topology/seed/clock 的 UI 编辑（文档治理；permissive-ignored 字段不做表单）。
- 场景文档 `scenario.step_started/step_completed` 事件消费 stepper（SPEC-205 §5 发射面无 REST/WS 直读行；本票 stepper 状态源 = §7.3 REST 事实映射）。
- Python 侧任何变更（`src/bootstrap/**`、`src/simulation/**`、`src/api/**` Python 侧零改动；ALLOWED_501 收缩已随 #80 完成，与本票无关）。

## 3. 术语

| 术语 | 定义 |
|---|---|
| Lab Pack v1 | 仓库顶层 `scenarios/` 的五个场景文件 SC-01~05（#17 结构冻结即预批准；注册表根 = repo 顶层 `scenarios/`，CWD-relative，裁定 F/OQ-4） |
| 文档治理 | scenario session 的 topology/seed/clock/deterministic 全部取自场景文档（加载即建，SPEC-205 §5）；`CreateSessionRequest` 的同名请求字段被服务端 permissive-ignored（OQ-6，DTO docstring 声明） |
| camelCase 岛 | `initial_topology` 内 `nodeId/nodeType/portId/direction/plane/maxConnections/connectionId/from/to` 键名（SPEC-205 §3 wire 形态，#45 canonical-example 权威），与其外层 REST snake_case 并存 |
| 揭示梯子 | `hints[]` 按文档数组顺序的逐条展开序列；「下一层」= 数组中下一条未揭示 hint（本票不发明 level 语义排序——`level` 串原样渲染为徽章） |
| reveal 门 | `GET /api/v1/scenarios/{id}/solution?session_id=`（必填）的后端 PASS 门（裁定 F）：该 (session, scenario) 存在 verdict=PASS 判定行才 200；否则 403 `SIM_SCENARIO_SOLUTION_LEAK`（拒并审计） |
| 三态 verdict | `PASS/FAIL/INCONCLUSIVE`（SPEC-206 §4）；UI 只渲染 `POST .../verify` 返回值 |
| 判据六 kind 闭集 | `fault_inactive/psi_pat_valid/psi_pmt_valid/pat_pmt_mapping_valid/cc_continuous/no_unexpected_cc_error`（SPEC-206 §7 冻结枚举；`VERIFY_CRITERION_KINDS` 复用） |
| 八步闭环 | Create → Generate → Inject → Analyze → Diagnose → Inspect → Recover → Verify（CONTEXT.md 逐字；REST 映射先例 = `tests/e2e/_fault_lab.py` 头注） |
| run 注册表 | 页面内存态：本页触发 run 的 `{run_id, RunStatusDTO}` 列表（事实以 `getRun` 应答为准，非第二事实源；供 verify/诊断表单取值与 §7.3 步进推导） |
| 观测类判据 | 六 kind 中除 `fault_inactive` 外的五种（证据 = normalized `ts.*` observations，发布面 = 进程内 Analyze 桥）；`fault_inactive` = 声明+生命周期类（SPEC-206 §7/#59） |

## 4. 页面架构

### 4.1 路由区与页面骨架

- 路由注册沿用 SPEC-400 §4.2：`/lab` 条目已由 #61 注册（`appRoutes` → `features/lab/Region` 惰性加载），本票**原地替换占位 Region**，不改 `routes.tsx`。
- URL 方案（`useSearchParams`，Monitor 先例）：
  - `/lab` — 场景库列表；
  - `/lab?scenario=<scenario_id>` — 场景详情；
  - `/lab?scenario=<id>&session=<session_id>` — 实验控制台（刷新后按 session 重挂：snapshot + run 注册表重建，提示/参考解揭示态复位为锁定——诚实呈现，不伪装续接）。
- 控制台骨架（自上而下）：八步 stepper → 实验 header（scenario 标题 + session 徽章 + 生命周期徽章）→ run 触发区（Generate/Inject/Recover 三动作）→ 诊断区（diagnose 触发 + 列表/候选）→ 证据/事件区（Inspect 承载）→ verify 区（提交 + 结果卡）→ 参考解面板（锁定态默认）。

### 4.2 场景库列表（REQ-UI-406-001）

- 数据 = `useQuery(qk.scenarios(), listScenarios)`；`ScenarioSummaryDTO[]` 逐行渲染 `title/difficulty/version/scenario_id` 原样（禁自造别名字段）。
- 行动作 = 「查看详情」（→ `?scenario=`）与「开始实验」（→ 详情页 §4.3 开局动作；列表行不直接开局，开局前必见详情）。
- 空态文案显式「注册表暂无场景文档（空库 ≠ 错误；Lab Pack 落位后此处列出 SC-01~05）」——禁渲染为加载失败。
- 排序 = 服务端 filename-ASC 注册表序（裁定 F 确定序），前端**不重排**（禁第二排序语义）。

### 4.3 场景详情与开局（REQ-UI-406-002 / REQ-UI-406-003）

- 详情数据 = `useQuery(qk.scenario(id), () => getScenario(id))`；渲染分区：
  1. **目标/步骤**：`objectives[]` 编号列（文档原文逐条）；
  2. **分阶段 hints**：揭示梯子组件（§4.4；未揭示条数显式计数）；
  3. **pass_criteria**：逐行 `criterion_id` + kind 六闭集串徽章 + `mandatory` 徽章 + `fault_id`（有则显引用）——通关判据的**声明呈现**（非结果）；
  4. **初始拓扑**：`initial_topology` 只读结构视图（camelCase 岛键名原样；节点/端口/连线三层缩进呈现，禁画布编辑语义）。
- 「开始实验」动作编排：
  1. `POST /api/v1/sessions`，body = `{scenario_id, topology_id, topology_revision, seed, deterministic, clock_config}`——`scenario_id` 为文档值；其余字段取场景文档投影（`initial_topology.topology_id/revision`、`simulation_config.seed/mode/clock`）。服务端场景分支按文档治理（请求同名字段 permissive-ignored，OQ-6）；请求体携带文档投影值是**自文档化**姿态，不构成第二治理源。
  2. 201 应答 `lifecycle:"ready"` → 自动 `POST .../start` → `running`（runs 面要求 RUNNING session；两跳应答的 `SessionViewDTO` 均为步进事实）。
  3. 成功 → 导航 `?scenario=<id>&session=<session_id>` 进控制台；422 `SIM_VALIDATION_FAILED`（过闸失败）按 §8 渲染 path-addressed violations。
- session 存在性纪律：一次一个作用域 experiment（无 session 列表端点；`?session=` 深链重挂以 `GET .../snapshot` 为准）；404 `SIM_SESSION_NOT_FOUND` → 回列表 + 显式错误态。

### 4.4 hints 渐进揭示（REQ-UI-406-004）

- 揭示梯子组件（`HintsLadder`）：`hints[]` 逐条渲染为可展开卡；已揭示卡显示 `level` 徽章（串原样）+ `trigger` + `content` + `requirement_ids[]` chips + `standard_ref`（null 显式「无」）。
- 「揭示下一条提示」按钮：点击揭示数组中下一条未揭示 hint（一层 = 一条）；全部揭示后按钮禁用 + 文案「本场景提示已全部揭示」。揭示计数 = 纯前端组件态（`useState`，per 挂载；无后端参与、无持久化——刷新复位，诚实呈现）。
- 禁发明 level 语义排序/阈值：揭示顺序恒为数组序；`level` 是文档内容（渲染原文），不是 UI 排序键。
- 揭示面与 `hidden_reference_solution` 无关：hints 是文档明载内容；参考解只走 §4.7 门控通路。

### 4.5 run 触发区与 run 注册表（REQ-UI-406-003/006 承载面）

- 三动作（均 = `POST .../runs` + 202 轮询 `GET .../runs/{run_id}` 至终态）：
  1. **Generate（基线）**：`fault_plan: []`；
  2. **Inject（注入）**：`fault_plan` = 场景详情 `fault_plan` 原文（`FaultDefinitionDTO` 形状直通，禁改写）；
  3. **Recover（恢复）**：`fault_plan: []`（新 Run——重跑 = 新 run_id，SPEC-205 §5）。
- `config` = 教学几何常量（§4.8）：冻结 golden geometry 的 SPEC-108 §4 wire 形状（模块常量 `labGeometry.ts`，出处注释锚定 `tests/_support/fault_lab_materials.py GOLDEN_GEOMETRY` / SPEC-506 §7 注册几何）；无 REST 几何面（申报 §10）。
- run 注册表（页面内存态）：`{run_id, status, artifacts[]}` 追加记录 + 轮询更新；呈现列 `run_id/status/packet_count/artifacts[]{artifact_id,kind}`；`completed/cancelled/failed` 终态原样徽章。非空 plan 的 run 预期产出 `faulted_ts` artifact、空 plan 仅 `generated_ts`——这是 §7.3 步进的观测面（artifacts kind 是服务端事实）。

### 4.6 诊断区与通关结果卡（REQ-UI-406-005）

- **Diagnose**：`POST .../runs/{run_id}/diagnose`（run 选择器预填 Inject run，可改选注册表内 run）→ `DiagnosisReportDTO`；404-until-drained 有界重试（复用 SPEC-403 §7.5 姿态）。
- 呈现复用 SPEC-403 §6 导出组件（受控纯呈现——Lab 取数后传入）：
  - `DiagnosisList({diagnoses, context})`：`GET .../diagnoses`；
  - `DiagnosisCandidateList({candidates, onEvidenceSelect, context})`：报告 `candidates[]`；
  - `VerifyResultCard({result, context})`：verify 应答只读渲染。
- `context` 叠加（场景语境槽，`dvb-mon-context`）：场景标题徽章 + scenario 版本串；**禁**经 context 注入任何 verdict/判定语义（SPEC-403 §4.9 纪律）。
- 排序 = 组件内置 `orderDiagnoses`（SPEC-307 §5 矩阵）；confidence 三档枚举串原样（禁概率化）；空态文案沿用组件（「无诊断记录 ≠ 码流干净」/「candidates 空 = 诚实结果」）。
- **诊断候选跳转**：`onEvidenceSelect(locator, row)` 原样上抛 `{artifact_id, pid, packet_index}`；Lab 接线导航（§7.6 双预案）。MVP 无 Analyze HTTP 面 → 真实链路 candidates 恒空（诚实空态）；跳转接线以组件级测试断言（§11），E2E 不伪造候选。
- **verify 提交**：`POST .../runs/{run_id}/verify`，recovery run 选择器（预填最新空-plan completed run）+ baseline run 选择器（预填 Inject run——fault 生命周期锚所在的 faulted run，SPEC-206 §7 segment 1）；请求体形状 §7.4。`ui_state` 不使用。
- 结果卡：三态 verdict + `criteria[]{criterion_id,kind,mandatory,result,reason_code?,reason?}` + `evidence_refs` + `summary`，全部渲染服务端返回值；`NOT_EVALUATED` 行显式原因（禁静默）。禁本地推导/聚合/改写。

### 4.7 参考解面板（REQ-UI-406-007）

- 默认锁定态：「参考解保持锁定——通关判定为 PASS 后展开（后端 reveal 门核验）」。
- 解锁条件 = 页面持有的 `VerificationResultDTO.verdict === "PASS"`——**读结果卡渲染的同一 verdict 字段**（复用面纪律；禁另做本地判定）。非 PASS（FAIL/INCONCLUSIVE/无判定）恒锁定，按钮禁用，不发请求。
- 解锁后「展开参考解」点击 → `GET /api/v1/scenarios/{scenario_id}/solution?session_id=<本 experiment session>`：
  - 200 → 渲染 `hidden_reference_solution` 文本（`null` → 显式「本场景未声明参考解」）；
  - 403 `SIM_SCENARIO_SOLUTION_LEAK` → 保持锁定 + 渲染服务端 `error.message`（服务端门是权威，客户端解锁条件只是前置门槛，两者不一致时以服务端为准）；
  - 其他错误按 §8 通用分支。
- 请求纪律：PASS 前该端点**一次都不请求**（E2E 断言 §11）；应答文本不缓存进查询词表（一次性动作取数，页面态持有）。

### 4.8 教学几何（Lab Pack 与 run config 的对齐锚）

- Lab Pack v1 五场景的 `fault_plan.target_id` PID 与激活槽位对齐冻结 golden geometry（SPEC-506 §7 注册几何：600 包、ES1 PID 256/ES2 PID 257/PMT 4096/PAT PID 0、seed 1234567），使 Inject 症状真实落在 §4.5 常量 config 生成的码流上。
- 几何常量的**漂移申报**：前端常量无 REST 对账面（geometry 无 API 行）；若后续后端提供几何查询面，属 additive 后端票（§10）。

### 4.9 Lab Pack v1 场景文件创作规约（#17 结构冻结即预批准）

- 落点 = 仓库顶层 `scenarios/`（裁定 F/OQ-4 注册表根；`GET /scenarios` 即列出）；文件名 `SC-0<n>-<slug>.json`（filename-ASC 即库序）。
- 结构权威 = `src/simulation/scenario/schema.py` 解析器；每文件必须过生产 loader（composition fail-fast 纪律——畸形文件是部署错误）；Phase 2 以真实 loader 校验实证（后端测试或脚本）。
- 字段规约：`schema_version: 1`；`scenario_id` 固定 uuid4（创作时定死，入库即身份）；`initial_topology` camelCase 岛、`nodeType` 用 #62 冻结四类型串（`ts_generator/ts_mux/ts_demux/ts_monitor`）、plane 恒 `MPEG_TS`、`maxConnections: 1`、拓扑过 SPEC-202 §5 门（DAG、方向/平面/基数合法）；`simulation_config` 与教学几何同 seed（1234567）+ deterministic；`fault_plan[]` 每项 `expected_observations` 必填（registered 词表）；`pass_criteria` kind 只用六 kind 闭集、`fault_inactive` 的 `fault_id` 必在本场景 plan；hints 梯子每场景 ≥3 条（`level` ∈ `nudge/direction/walkthrough`，数组序 = 揭示序）；`standard_ref` 恒 null（禁编造 ETSI/ITU 条款号，SPEC-205 §6）；`requirement_ids` 只引用真实 REQ id（沿 #58 fixture 先例 `REQ-SIM-204-001..004`）；**五文件全部声明 `hidden_reference_solution`**（reveal 面的内容载体）。
- 判据 mandatory 设计（M4 裁定 B 姿态申报，§10）：
  - **SC-01（入门）**：`pass_criteria` 仅 `fault_inactive` 一条（mandatory）——纯 REST 全链（无 Analyze HTTP 面）可达 PASS，承载 REQ-UI-406-007 全链验收（开局→verify PASS→参考解展开）；
  - **SC-02~05**：`fault_inactive`（mandatory）+ 观测类症状判据（mandatory，SPEC-206 §7 症状兜底意图）——当前纯 REST 链路诚实答 **INCONCLUSIVE**（观测类判据证据缺失 → `NOT_EVALUATED` + 显式 reason）；结果卡如实渲染三态与明细，参考解保持锁定。这是 SPEC-206 §6「无观测 ≠ 干净」纪律的**可见教学面**，不是缺陷；观测类判据可达 PASS 须待 Analyze HTTP 面（后端伴随票，本票禁入）。

## 5. 数据模型（消费 DTO 逐字段，wire snake_case 原样）

本票不定义新 wire 类型；全部响应类型取自 `src/api/schema.gen.ts`（生成权威，禁手改；scenario 三 DTO 已随 #80 生成）。关键形状：

- `ScenarioSummaryDTO`：`scenario_id/version/title/difficulty`。
- `ScenarioDetailDTO` 精确字段集 = `schema_version/scenario_id/version/title/difficulty/required_engine_versions{}/initial_topology{}/simulation_config{}/fault_plan[]/objectives[]/hints[]/pass_criteria[]`；`hidden_reference_solution` **结构性缺席**（export 面默认剥离，REQ-SIM-205-003）。
- `ScenarioSolutionDTO`：`scenario_id/hidden_reference_solution(string|null)`。
- `CreateSessionRequest`/`SessionViewDTO`：SPEC-403 §5 同面（本票新增消费 `scenario_id` 入参；201 应答 `lifecycle` 起点为 `ready`）。
- `RunSubmitRequest{config, fault_plan[]}`/`RunAcceptedDTO{run_id, config_hash, status}`/`RunStatusDTO{run_id, status, packet_count?, byte_count?, artifacts?[]{artifact_id, kind, sha256, byte_size, packet_count?, partial}, warnings?}`。
- `DiagnosisDTO`/`DiagnosisCandidateDTO`/`DiagnosisReportDTO`/`VerifyRunRequest`/`VerificationResultDTO`：SPEC-403 §5 同面。
- `initial_topology` camelCase 岛（只读呈现面）：`nodeId/nodeType/config/ports[]{portId,direction,plane,maxConnections}`、`connections[]{connectionId,plane,from{nodeId,portId},to{nodeId,portId}}`。

## 6. 公开接口（本票对共享面的 additive 贡献）

```ts
// src/api/endpoints/scenarios.ts —— SPEC-500 §4.7 三路由的消费面（additive；
// barrel 一行导出，#62 topologies.ts 先例）。非 2xx 抛 ApiError（client 核心）；
// errorCode SIM_SCENARIO_SOLUTION_LEAK = 403 reveal 门呈现分支。
export function listScenarios(): Promise<ScenarioSummaryDTO[]>;
export function getScenario(scenarioId: string): Promise<ScenarioDetailDTO>;
export function revealScenarioSolution(
  scenarioId: string,
  sessionId: string,
): Promise<ScenarioSolutionDTO>;
```

- 类型别名取自 `schema.gen.ts`（`components["schemas"][...]`），禁手写 mirror。
- 查询词表：列表/详情复用 `qk.scenarios()` / `qk.scenario(id)`（禁另造键系）；solution 是 PASS 门控的一次性动作取数，**不进查询缓存、不设键**。
- Lab 页面组件（列表/详情/控制台/梯子/stepper/参考解面板）**不在**导出面——SPEC-406 无下游消费票（M5 终票）；共享面接触 = §6 三函数 + barrel 行 + 五个场景 JSON。

## 7. 处理算法

### 7.1 开局编排（REQ-UI-406-003）

1. 详情页「开始实验」→ busy 锁 → `createSession({scenario_id, ...文档投影})`。
2. 201 → `startSession(sessionId)` → 200 `lifecycle:"running"` → 导航控制台。
3. 任何一跳失败：busy 释放 + §8 错误分支（422 过闸失败渲染 `SessionValidationDTO.violations[]` path-addressed 列表——`SIM_VALIDATION_FAILED` 信封 details 内 violations 逐条原样）；不进入控制台。
4. 201 应答 `lifecycle:"ready"` 是服务端事实；禁跳过 start 直认「可跑」。

### 7.2 run 触发与轮询（REQ-UI-406-003/006 承载面）

- 触发 → 202 `run_id` 入注册表 → 单一 200ms 间隔轮询器（30s 超窗，SPEC-403 §9 同参数）→ 终态回填注册表行。
- 三动作在途互斥（busy 锁禁并发提交——确定性链路姿态，非业务规则）；Inject 的 plan 取自详情查询缓存（详情未就绪时按钮禁用）。

### 7.3 八步 stepper 状态映射表（REQ-UI-406-006，可观测服务端事实）

| 步 | 服务端事实源（本页持有的 DTO/wire 数据） | done 条件 |
|---|---|---|
| Create | experiment session 的 `SessionViewDTO`（create/start 应答 + snapshot 重挂） | 持有 session 且 `lifecycle ∈ {running, paused}` |
| Generate | run 注册表（`RunStatusDTO.artifacts[].kind`） | ∃ completed run：含 `generated_ts` 且不含 `faulted_ts` |
| Inject | run 注册表 | ∃ completed run：含 `faulted_ts` |
| Analyze | ——（无 HTTP 面） | **恒不 done**：渲染「不可用（进程内 Analyze 桥，M4 裁定 B——REST analyze 冻结 501）」中性徽章；禁伪进度 |
| Diagnose | 页面持有的 `DiagnosisReportDTO`（POST diagnose 应答） | 已取得 Inject run（或用户选定 run）的报告 |
| Inspect | 证据/事件区取数（`GET .../events` 应答 items + 候选 locator 呈现位） | 事件查询已应答且 `items.length ≥ 1` |
| Recover | run 注册表 | ∃ 第二个 completed 空-plan run，`run_id` ≠ Generate 步所用 run |
| Verify | 页面持有的 `VerificationResultDTO`（POST verify 应答） | 已取得任一 verdict 应答 |

- 步进推导为纯函数（`deriveStepState(facts): EightStepBooleans`），单测对表穷举（§11）；步进**不是**通关证据（结果卡旁注显式声明「stepper 进度 ≠ 通关判定」）。
- pending/done 徽章渲染禁止第三态猜测（未知 = pending）。

### 7.4 verify 请求体形状（REQ-UI-406-005）

```text
POST /api/v1/sessions/{session_id}/runs/{recovery_run_id}/verify
{
  "baseline_run_id":  <Inject run（fault 生命周期锚 run）>,
  "scenario": {
    "scenario_id":   <详情 scenario_id（真实值）>,
    "version":       <详情 version（真实值）>,
    "content_hash":  "lab-ui-unpinned"   // 见下方申报句
  },
  "pass_criteria": <详情 pass_criteria[] 逐条直通（criterion_id/kind/mandatory/fault_id）>,
  "ui_state": 不发送
}
```

- **content_hash 申报句**：loader 钉扎的内容哈希（SPEC-205 §5）无 REST 回读面（详情导出剥离 hidden 后不可重算 canonical 哈希）；`content_hash` 按引擎语义为**声明性标识**（服务端核验面 = run↔session 归属 `SIM_VERIF_RUN_MISMATCH`；reveal 门匹配 = `scenario_id`）。Lab 发送固定声明串 `lab-ui-unpinned`，禁伪造哈希。钉扎哈希的 API 回读属 additive 后端面（§10 申报）。
- 判据直通禁改写：Lab 不增删改 `pass_criteria`（通关口径 = 文档声明，非 UI 编排）。

### 7.5 参考解门控编排（REQ-UI-406-007）

1. 结果卡渲染 verdict（复用组件）；`SolutionPanel` 读同一 `result.verdict`。
2. `verdict !== "PASS"` → 锁定（按钮 disabled + 原因文案），**不发请求**。
3. `verdict === "PASS"` → 解锁；点击 → `revealScenarioSolution(scenario_id, session_id)` → 200 渲染 / 403 服务端门否决（§4.7）/ 其他错误 §8。
4. 会话切换（`?session=` 变化）→ 面板复位锁定 + 已取文本丢弃（per-session 事实，禁跨会话残留）。

### 7.6 诊断候选跳转接线（REQ-UI-406-005；双预案）

- 回调面：`onEvidenceSelect(locator, row)`——locator 三元组 `{artifact_id, pid, packet_index}` 原样上抛（组件契约，SPEC-403 §6）；Lab 不解码、不裁剪。
- **预案 A（#65 已落）**：消费其报告 §0 导出（packet-inspector 消费面/深链参数），跳转直达证据下钻视图。
- **预案 B（#65 未落）**：跳转 `/monitor?session=<sessionId>`（本 experiment session 的 Monitor 视图，#64 诊断面板所在），locator 经组件呈现位可见；接线终态在期末核 merge 时对齐 #65 导出并申报。
- 两预案均不改 Lab OWN 文件以外的面；实际生效预案在 IMPLEMENTATION_REPORT 申报。

## 8. 错误处理

| 场景 | 处理 |
|---|---|
| 422 `SIM_VALIDATION_FAILED`（开局过闸失败） | 详情页内联渲染 violations（path-addressed `code/path/message` 逐条）；不导航进控制台 |
| 404 `SIM_SCENARIO_NOT_FOUND` | 列表/详情显式错误态（场景被移除的诚实呈现）；禁渲染为空列表 |
| 404 `SIM_SESSION_NOT_FOUND`（深链重挂） | 回列表 + 错误条 |
| 409 `SIM_INVALID_LIFECYCLE_TRANSITION` | 渲染 `details{current,target,allowed}`；以 `details.current` 回同步生命周期徽章 |
| run 终态 `failed/cancelled` | 注册表行原样徽章 + warnings 列表；步进不 advance（事实驱动）；禁重试掩盖 |
| diagnose 404-until-drained | 有界重试后显式失败态（SPEC-403 §7.5 姿态） |
| verify 4xx（`SIM_VERIF_RUN_MISMATCH`/`SIM_VERIF_CRITERION_INVALID` 等） | 错误条渲染 `errorCode + message`；结果卡不渲染（请求成功前无任何结论态） |
| solution 403 `SIM_SCENARIO_SOLUTION_LEAK` | §4.7 锁定 + 服务端 message；审计在后端（UI 无义务） |
| 查询失败（网络） | 分区错误态 + 重试；禁把失败渲染为「零值/干净/空库」 |
| ApiError 通用 | `ApiError{status,errorCode,message,retryable,details,requestId}` 错误条；`retryable` 决定重试按钮 |

## 9. 资源约束

- 单页一次一个作用域 experiment session；run 轮询单一计时器（200ms/30s 超窗）；无其他轮询。
- 列表/详情查询走查询缓存（`staleTime` 页面常量）；solution 取数不入缓存。
- 揭示梯子/run 注册表为页面内存态；无 localStorage/持久化（不做清单边界）。
- 事件区拉取 `limit` 页面缺省（默认 100，SPEC-500 §4.5 上限内），供 Inspect 步事实与引用 chip 呈现。

## 10. 依赖

- 上游规格：SPEC-205（文档格式/加载即建/版本钉扎/reveal 政策）、SPEC-206（三态/判据闭集/观测对偶）、SPEC-500 §4.2/§4.3/§4.5/§4.6/§4.7、SPEC-403 §6（复用组件 + context 槽 + `orderDiagnoses`/`VERIFY_CRITERION_KINDS`）、SPEC-400（架构/词表/失效桥）、SPEC-200 §5（生命周期表）、SPEC-506 §7（注册几何出处）。
- 上游实现：`src/api` barrel（`createSession/startSession/submitRun/getRun/diagnoseRun/listDiagnoses/verifyRun` + 本票新增三函数）；`src/query/keys.ts` `qk.scenarios/qk.scenario`；`src/components/ui`（Badge/Panel/EmptyState）；`routes.tsx` 既有 `/lab` 条目；`features/monitor/components` barrel（三组件导出）。
- 下游消费：无（M5 终票）。共享面接触 = §6 + Lab Pack 五 JSON；跳转接线对 #65 导出的单向消费（§7.6）。
- **申报 1（Analyze HTTP 面）**：M4 裁定 B 冻结 REST analyze 501、Analyze 桥进程内——观测类判据（`psi_*`/`cc_continuous`/`no_unexpected_cc_error`）的 normalized `ts.*` 证据无 HTTP 生产面，纯 REST 链路诚实 INCONCLUSIVE（§4.9）。LAB 不做、也禁做任何绕行（禁伪造候选/禁本地观测推断）。观测类 PASS 可达性 = 后端伴随票决策（本票无后端面）。
- **申报 2（钉扎哈希回读面）**：`ScenarioDetailDTO` 不含 loader `content_hash`；verify `scenario.content_hash` 为声明串（§7.4）。若需真实钉扎哈希上卡 = additive 后端小票（详情 DTO 加字段），本票禁入。
- **申报 3（起服 CWD 核验结论）**：`frontend/scripts/start-backend.mjs` 以 `cwd: TREE_ROOT`（= worktree 仓库根）spawn uvicorn `bootstrap.asgi:app`，而 `build_production_app` 缺省 `scenario_dir = Path("scenarios")`（CWD-relative，裁定 F）——**CWD 已是仓库根，`scenarios/` 可被扫描，start-backend 零改动**。已实机验证：worktree 起服 + `GET /api/v1/scenarios` 200 列出置入文件、detail 200、reveal 无 PASS 403、`POST /sessions{scenario_id}` 201 `ready`、start→runs 202→completed、verify（`fault_inactive` 单判据、baseline=Inject run）200 PASS、reveal 200。**无需 start-backend additive 方案。**

## 11. 测试向量

- **场景库**：列表渲染 summary 四字段 wire 名；空库显式空态文案（≠ 错误）；服务端序不重排。
- **详情渲染**：objectives 编号列；pass_criteria kind 六闭集串原样徽章 + mandatory/fault_id；camelCase 岛键名原样呈现（断言 `nodeId/nodeType/portId/direction/plane/maxConnections/from/to` 字面出现）。
- **开局**：请求体断言（`scenario_id` = 文档值在位）；201→start→running 两跳编排；422 过闸失败分支 violations 渲染（mock 信封）。
- **揭示梯子**：数组序逐条揭示；`level/trigger/content/requirement_ids` 原文渲染；全揭示后禁用文案；无任何网络请求随揭示发出。
- **run 触发**：Inject plan = 详情 `fault_plan` 直通（请求体断言）；Generate/Recover 恒空 plan；轮询终态回填。
- **stepper 纯函数**：§7.3 映射表穷举单测（含 Analyze 恒不 done、Recover 与 Generate 同 run 不 advance、终态 failed 不 advance）。
- **通关结果卡**：三态 fixture 各一（复用 SPEC-403 卡组件断言姿态）；`NOT_EVALUATED` reason 显式；context 叠加渲染场景徽章且不触碰事实行；confidence 枚举串禁数字。
- **诊断候选跳转**：组件级——fixture 候选传入，点击 locator 按钮回调上抛三元组原样 + 跳转目标按生效预案断言。
- **参考解门控**：verdict=PASS 前零 `/solution` 请求（请求监听断言）；PASS 后点击 → 200 渲染文本；`null` 显式文案；403 分支锁定 + message；`?session=` 切换复位。
- **verify 请求体**：§7.4 形状断言（criteria 直通、content_hash 声明串、无 `ui_state` 键）。
- **Lab Pack 五文件**：每文件过生产 loader（Phase 2 后端测试实证：`parse_scenario_document(raw)` 无异常）；断言五 `scenario_id` 唯一、difficulty 梯度、SC-01 判据集 = `fault_inactive` 单条、SC-02~05 含观测类 mandatory 判据、hidden 字段五文件齐备。
- **组件导出面**：barrel 三函数 typecheck 即门；`scenarios.ts` 单测镜像 `topologies.test.ts` 姿态（路径/方法/查询参数断言）。
- **E2E（真后端，`npm run e2e` 双 webServer）**：
  - `e2e/lab.spec.ts`（新）：库列表 5 行（SC-01~05 title 断言）→ SC-01 详情渲染 → 揭示梯子逐层（含零 solution 请求断言）→ 开局（Create 步进）→ Generate/Inject/Recover（步进推进）→ verify → **PASS** 结果卡 → 参考解展开（200 文本渲染）；SC-04 全链 → **INCONCLUSIVE** 卡 + NOT_EVALUATED reason 行 + 参考解保持锁定（无请求）+ 请求级 403 断言（`solution?session_id=<无 PASS session>` → 403）。
  - `e2e/closed-loop.spec.ts`：仅 Create/Inject 两步 driver 翻转 `rest → ui`（owner 注释改 #67；Create = Lab 开局取 session；Inject = Lab 注入按钮取 faulted run）；其余六步与 Analyze 跳过标注**零改动**。

## 12. 验收标准

- **AC-406-01（REQ-001）**：SC-01~05 场景库可浏览——列表五行（title/difficulty/version/scenario_id wire 名原样）、服务端序、空态纪律；五文件全部过生产 loader（composition fail-fast 不触发）。
- **AC-406-02（REQ-002）**：详情渲染目标/步骤（objectives）、分阶段 hints、pass_criteria（六 kind 串 + mandatory + fault_id）、initial_topology camelCase 岛只读视图（键名原样）。
- **AC-406-03（REQ-003）**：开局 = `POST /sessions{scenario_id}` 201 ready → start running；文档治理生效（服务端文档投影；请求同名字段 permissive-ignored 由后端契约承担）；422 过闸分支 violations 可见。
- **AC-406-04（REQ-004）**：hints 逐层揭示（数组序、点击一层、纯前端零请求）；揭示态刷新复位诚实呈现。
- **AC-406-05（REQ-005）**：通关卡三态/判据明细渲染与 SPEC-403 组件一致（复用导出面 + context 场景徽章）；诊断候选跳转接线（§7.6 生效预案申报）；无本地 verdict 推导路径（代码审查项：卡片仅消费 `VerificationResultDTO`）。
- **AC-406-06（REQ-006）**：八步 stepper 与 CONTEXT.md 闭环逐字对应；状态映射 = §7.3 表（纯函数单测穷举绿）；Analyze 步不可用徽章诚实；「stepper 进度 ≠ 通关判定」旁注可见。
- **AC-406-07（REQ-007）**：通关（verdict=PASS）前 `/solution` 零请求（E2E 请求监听断言）且面板锁定；PASS 后展开渲染服务端文本（或 null 显式文案）；403 服务端门分支锁定 + message；SC-01 全链 E2E（开局→三 run→verify PASS→展开）真后端绿；SC-04 INCONCLUSIVE 诚实卡 + 锁定保持。
- **AC-406-08（全门）**：`npm run lint/typecheck/test:run/build/dto:check/e2e` 绿 + 后端三门绿 + `python -I tools/check_specs.py` 0 failed；closed-loop 八步全绿（Create/Inject 翻转后）。

## 13. 非目标

- 计分/进度存档/多用户/场景编辑器（不做清单，永久非 MVP 裁量）。
- fault-plan 编辑、场景创作 UI、拓扑编辑（复用面只读）。
- 证据 hex/解码呈现（SPEC-404）；事件浏览页（observation_refs 静态 chip，SPEC-403 同姿态）。
- 观测类判据的 PASS 可达性（申报 1；后端伴随票决策）。
- verdict 本地推导、hints 语义排序、参考解前端预持（永久禁令：reveal 政策外 `hidden_reference_solution` 不经任何客户端路径存在——详情导出面结构性缺席，客户端**从未持有**，无从泄露）。

## 14. 兼容性与交付要求

- 分支 `ticket/m5-67-training-lab`；合并序列与全门遵循 SPEC-005 §9 与派工词（前端六门 + 后端三门 + check_specs）。
- `routes.tsx` 共享壳零改动；`features/monitor/**`（含 #65 并行面）、`features/topologies/**`、`src/api/**` 其余、`src/query/**`、`src/ws/**`、`schema.gen.ts`、后端全部、`.github/workflows/**` 不触碰。
- 全部响应类型取自 `schema.gen.ts`；类型缺口走 `dto-supplement.ts` 收窄机制申报，禁手改生成文件。
- 并行裁定知悉：#65（证据下钻）面 = `features/monitor/packet-inspector/**` + monitor Region additive——与 `features/lab/**` 不相交；merge tip 收尾时 §7.6 双预案对齐，INDEX 预导言冲突按裁定 J（#15）机械并集。
- 交付物含：本规格文本（批准后转正）、SPEC-INDEX-FRONTEND 行链接 + 预导言并集、Lab Pack v1 五文件、`src/api/endpoints/scenarios.ts` + barrel 行、`features/lab/**` 实体、closed-loop Create/Inject 翻转、`e2e/lab.spec.ts`、IMPLEMENTATION_REPORT（首节「共享面接触与跳转接线终态」——终票无下游）。
- 文本/徽章一律渲染 wire 枚举串原样（snake_case / camelCase 岛各守其位）；禁前端自造别名或语义改写。
