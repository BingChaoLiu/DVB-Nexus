---
spec_id: SPEC-400
title: Frontend Architecture
version: 0.5.1
status: APPROVED
phase: MVP
owner: Frontend
priority: P0
depends_on: [SPEC-001, SPEC-003]
requirements: [REQ-UI-400-001, REQ-UI-400-002, REQ-UI-400-003, REQ-UI-400-004]
---

# SPEC-400 — 前端架构（SPA 壳）

## 1. 目标

定义前端 SPA 的**架构权威冻结点**：单 SPA 工程与路由区骨架（#61 交付时三路由区；SPEC-408 增补主页 `/` 旅程门厅后为四路由区）、服务端状态模型（查询缓存 + WS journal/hint 触发重取）、TS 类型权威与 CI 漂移锁机制、最小测试面。本规格是 SPEC-401~406 实现票的**共享工程基座**：路由注册、DTO 对齐、api/ws/query 客户端核心与 E2E 骨架在本规格落定，后续票 additive 复用，禁另起第二机制。

依据：MVP 切集预批准（ticket #18）、ADR-0003 第 2 条（React + TypeScript 冻结）、ADR-0009（画布选型 @xyflow/react ^12，实体归属 SPEC-401）、SPEC-500 §3/§4/§6（REST 契约）、SPEC-501 §3/§4/§5/§8（WS 契约）、SPEC-305 §6/§8（观测信封与 hint→REST 矩阵）、CONTEXT.md「通关」「八步闭环」词条（UI 判定禁令）。

## 2. 范围

### 2.1 In Scope

- 单 SPA 工程骨架：`frontend/` 目录、构建链（Vite + TypeScript）、路由注册表模式、路由区壳导航（#61 交付时三路由区 Topologies / Monitor / Lab；SPEC-408 增补主页 `/` 后为四区，主页实体与导航徽标归 SPEC-408 §4.1/§4.2）。
- 服务端状态模型：TanStack Query 查询缓存 + WS journal/hint 触发重取；WS 客户端核心（连接、订阅、重连、close 码纪律）；hint→REST 失效桥（五主题）与节流钩子。
- TS 类型权威机制：OpenAPI codegen + 不可达模型手写补缺 + CI 漂移锁。
- 工程门禁：Node/包管理器版本钉扎、前端 lint/typecheck/test/build CI job、DTO 漂移锁 CI job、E2E 冒烟 CI job。
- 全栈 E2E 骨架：ASGI 服务入口（`src/bootstrap/asgi.py`，Python 侧唯一新增文件）+ Playwright 冒烟（一条八步闭环骨架）。

### 2.2 Out of Scope

- 拓扑画布与编辑交互（SPEC-401；ADR-0009 已裁 @xyflow/react ^12，依赖由该票引入）。
- 节点表单、Stream Monitor、证据下钻、CLI 对照台、Training Lab 的页面实体（SPEC-402~406）。
- React Flow 选型与画布状态纪律（ADR-0009 既裁，本规格仅引用其「React Flow 内部 store 不作事实源」条款为约束）。
- 组件库级 UI 体系（MVP 用最小自绘组件集，见 §8.3）；认证/多用户/部署编排（单机姿态，SPEC-500 §3）。
- 后端 Python 侧行为变更（本规格新增的 `src/bootstrap/asgi.py` 是组合根之上的**嵌入方薄入口**，不改任何既有 Python 公共接口）。

## 3. 术语

| 术语 | 定义 |
|---|---|
| 查询缓存 | TanStack Query 管理的服务端状态缓存；按查询键（query key）组织；**不是**事实源，只是 REST 重取结果的缓存投影 |
| 事实源 | journal（SPEC-502）；服务端事实的唯一权威。前端任何本地结构（查询缓存、WS 缓冲、画布 store、组件 state）都不得成为第二事实源 |
| journal 帧 | WS 下行 `{"type":"journal","envelope":{…}}`，携带 SPEC-301 信封原样 + `journal_seq`（SPEC-501 §4） |
| hint 帧 | WS 下行 `{"type":"hint","topic":…,"data":{…}}`，best-effort 指针，可丢（SPEC-501 §4/§6 背压：journal 不丢、hint 可丢） |
| 重取（refetch） | hint/journal 触发的对应 REST 查询失效与重新拉取（SPEC-305 §8 矩阵） |
| DTO 对齐 | 前端 TS 类型与后端 Pydantic DTO（SPEC-500）的一致性；机制见 §7，漂移由 CI 捕获（REQ-UI-400-003） |
| 八步闭环 | Create → Generate → Inject → Analyze → Diagnose → Inspect → Recover → Verify（CONTEXT.md 词条）；E2E 冒烟骨架按此链编排 |
| 四路由区 | 主页 `/`（旅程门厅，SPEC-408 §4.2 增补）+ Topologies / Monitor / Lab 三个一级路由区（#18 切集三区；#61 交付时为三路由区） |

## 4. 架构

### 4.1 工程形态

- 单 SPA（非微前端、非 MPA）：一个 Vite 工程，一个入口，构建产物为静态资源；API 与 WS 经同源反代（开发/预览态由 Vite server proxy 承担，`/api` 与 `/ws` 转发到本机后端）。
- 技术栈（版本随工程 lockfile 钉扎，CI 复现）：React 19 + TypeScript（~5.9 线）+ Vite 8 + TanStack Query 5 + react-router（library 模式）+ Vitest 5 + Testing Library + Playwright。组件库裁定：**不引入 MUI/AntD 级重组件库**；MVP 用最小自绘 UI 组件集（`components/ui/`），画布例外归 ADR-0009（SPEC-401 引入 `@xyflow/react`）。理由：MVP 面是表单/表格/徽章/卡片级数据展示，重库带来包体与样式体系成本；验收断言对象是 wire 字段名/枚举串（§10 纪律），与组件库无关；自绘集避免第二套全局状态体系（重库常自带 store，违反「不自建第二事实源」审计面）。
- 目录契约（后续票 additive 遵守，目录名词随本票 Implementation Plan 审定冻结）：

```text
frontend/
  src/app/        壳布局、路由注册表（appRoutes）、导航
  src/api/        REST 客户端核心：schema.gen.ts（生成，禁手改）、
                  dto-supplement.ts（不可达模型补缺，只可缩小）、
                  client.ts（错误信封解析 + ApiError）、endpoints（领域函数）
  src/ws/         WS 客户端核心：连接/订阅/重连状态机、五主题常量、close 码纪律
  src/query/      查询键词表（canonical query keys）、hint→失效桥、节流/合帧钩子
  src/features/   <area>/ 每路由区一个目录（#62/#64/#67 各自 OWN 自己的 area）
  src/components/ui/  最小自绘组件集
  src/lib/        env.ts（运行环境推导：API base / WS base）
  src/styles/     theme.css（全局主题样式）
  e2e/            Playwright 冒烟（shell 导航 + 八步闭环骨架）
  scripts/        工程脚本（后端起服、OpenAPI dump、补缺检查）
```

### 4.2 路由注册模式（REQ-UI-400-001）

- 一张路由注册表（`src/app/routes.tsx` 导出 `appRoutes` 数组）：每条目 = 一级路由区（path + 惰性加载的页面元素）。壳布局从注册表渲染导航与 `<Outlet/>`。
- 后续票增路由 = **追加一个条目 + 一行 import**，不触碰共享壳逻辑；共享面 additive-only（裁定 C）。
- 路由区（MVP 切集三区 + SPEC-408 增补主页）：`/`（主页旅程门厅，实体归 SPEC-408 §4.2）、`/topologies`、`/monitor`、`/lab`；#61 交付三区可导航占位（区域标识渲染即验收），页面实体归 SPEC-401/403/406/408。壳导航含「主页」入口，Lab 条目徽「主干」、Topologies 条目徽「进阶」（SPEC-408 §4.1）。

### 4.3 服务端状态模型（REQ-UI-400-002）

服务端状态 = **查询缓存 + WS 触发的重取**，纪律四条：

1. **journal 是唯一事实源**。查询缓存只是 REST 响应的投影；重取是唯一让缓存追赶事实的通道（全量拉或 cursor 增量拉），前端不做本地事件重放式状态机、不维护第二份「当前状态」对象。
2. **hint 只是失效指针**。五主题 hint 帧按 SPEC-305 §8 矩阵映射到对应 REST 重取（§6 表）；hint 丢失不补偿——hint 是 best-effort（SPEC-501 §1/§5），恢复靠重连后的全量重拉（或 `GET .../snapshot?journal_seq_cursor=` 全量视图）。
3. **journal 帧直接进事件查询缓存**：按 `journal_seq` 全序增量并入（排序只认 `journal_seq`，SPEC-301）；信封未知可选字段必须忽略（ADR-0006 决定 4）。
4. **UI 本地状态只承载 UI 事实**（草稿、折叠态、选中项、表单值）。通关判定等业务结论只能渲染服务端返回（§10 禁令）。

### 4.4 WS 客户端核心

- 连接模型：单连接单 session（SPEC-501 §3），路径 `/ws/v1/sessions/{session_id}`；上行仅 `subscribe`（带 `last_journal_seq` cursor）与 `ping`。
- 重连纪律（SPEC-501 §5/§8 close 码表）：
  - `1013` 慢消费：解析 reason `slow-consumer;journal_seq=<n>`，**重连带 `last_journal_seq=<n>`** 续传；
  - `4404` session 未知/DISPOSED：不重连（会话已终结）；
  - `4400` subscribe 与路由不符：不盲目重连（客户端缺陷，上报不重试）；
  - `1008` pong 超时 / `1011` 存储不可用 / 网络断开：指数退避重连（带上次 journal_seq cursor 或先快照拉全量）。
- 重连成功 = 重新 subscribe（带 cursor）→ `ready` 帧确认 → 触发受影响查询的全量重取（有损恢复协议，SPEC-501 §5）。

### 4.5 Python 侧嵌入入口（`src/bootstrap/asgi.py`）

- 组合根 `build_production_app` 不起服务、不建线程（驱动面留给嵌入方）。真实 HTTP 服务需要一个薄入口：模块持 `app = build_production_app(db_path=<env>).app`，并在 lifespan 内启动**泵循环**（asyncio 任务，周期调用 `drain_gateway()` / `process_observation()` —— 嵌入方泵纪律的异步形态），使 journal 提交、WS 帧扇出与 hint 发射在服务态真实流动。
- 环境变量契约：`DVBNEXUS_DB_PATH`（必填，缺失即拒启——SQLite 库与 artifacts 根落点）；可选 `DVBNEXUS_HOST` / `DVBNEXUS_PORT` / `DVBNEXUS_PUMP_INTERVAL_MS`。
- importlinter 合规：`bootstrap` 是组合根叶子（只出不进），asgi.py 只向下 import；无包回引 bootstrap（uvicorn 以字符串引用加载，不构成项目内 import 边）。

## 5. 数据模型

- **TS 类型权威 = SPEC-500 Pydantic DTO**（REQ-UI-400-003）。生成链：FastAPI `app.openapi()` dump（OpenAPI 3.1）→ `openapi-typescript` 生成 `src/api/schema.gen.ts`（生成物入库、禁手改）。
- **不可达模型补缺（现状事实）**：本规格编写时点 OpenAPI 可达 30 paths / 36 schemas；observation 八路由 handler 返回裸 dict、错误信封不经 response_model 声明 → 17 个模型不在 OpenAPI（`ObservationResponseDTO`/`SummaryDataDTO`/`EventsDataDTO`/`TimelineDataDTO`/`MetricPointDTO`/`MetricSeriesDTO`/`MetricsDataDTO`/`AlertRecordDTO`/`AlertsDataDTO`/`HealthDimensionDTO`/`HealthDataDTO`/`ExportDataDTO`/`ObservationScopeDTO`/`ObservationMetaDTO`/`TimelineLaneDTO`/`ErrorDetail`/`ErrorResponse`）。补缺机制：
  - `dto-supplement.ts` 手写补缺，**只允许缩小不允许扩大**：CI 校验补缺中每个名字仍不在 OpenAPI schemas 中；一旦后端把模型接进 OpenAPI（M5 伴随接线票范围），对应补缺条目必须删除、统一改用生成类型（防止双权威滞留）。
  - 手写补缺的形状权威 = SPEC-305 §4/§6/§7 与 `src/api/dto/*.py` wire 形状；wire 字段名 snake_case 原样。
- 查询键词表（canonical query keys，失效桥与后续票共同语言）：会话作用域前缀 `['session', sessionId, ...]`；观测面约定 `['events', sessionId, …]` / `['metrics', sessionId, …]` / `['alerts', sessionId, …]` / `['health', sessionId, …]` / `['export', sessionId, exportId, …]` / `['summary', sessionId]`；拓扑面 `['topologies']` / `['topology', topologyId, revision]`；场景面 `['scenarios']` / `['scenario', scenarioId]`。后续票消费词表 additive 扩展，禁另造平行键体系。
- 错误信封（全平台统一，SPEC-500 §6 / SPEC-305 §7）：`{error:{error_code,message,retryable,details}, request_id}`；api 客户端核心统一解析为 `ApiError`（携带 error_code/details/request_id），表单/页面按 `details.errors[]`（schema path 字符串）就地定位渲染（SPEC-402 消费面）。FastAPI 默认 422 已被后端覆盖为 400 `REQUEST_BODY_INVALID`——前端按信封渲染，不依赖框架原 422 形状。

## 6. 公开接口（前端核心对后续票的暴露面）

### 6.1 REST 客户端（`src/api/`）

- `client`：openapi-fetch 实例 + 统一错误信封解析；领域函数按 SPEC-500 §4 路由逐个封装（入参/返回为生成类型 + 补缺类型），后续票 import 领域函数，禁自拼 fetch。
- 会话面：createSession / validateSession / startSession / pauseSession / resumeSession / stopSession / deleteSession / getSnapshot；运行面：submitRun / getRun；artifact 面：getArtifactMeta / getArtifactContent(Range)；观测面：queryEvents / queryMetrics / queryAlerts / queryHealth / querySummary / queryTimeline / exports；诊断面：listDiagnoses / diagnoseRun；验证面：verifyRun。

### 6.2 WS 客户端（`src/ws/`）

- `SessionStream`（每 session 一实例）：`subscribe(topics?)` / `close()`；帧回调：`onJournal(envelope)` / `onHint(topic, data)` / `onReady(replayedFrom)`；连接状态机暴露 `status`（connecting/ready/reconnecting/closed）供 UI 呈现连接徽章。
- 五主题常量（精确串，与后端 `HINT_TOPICS` 一致）：`observation.event_appended` / `observation.metric_updated` / `observation.alert_changed` / `observation.health_changed` / `observation.export_progress`。

### 6.3 失效桥（`src/query/`）

- `hintInvalidationBridge(queryClient, stream)`：hint topic → query key 前缀失效矩阵（§5 词表）；带**节流/合帧**（同 topic 窗口期合并为一次重取；参数随实现钉扎并有测试）。
- journal 增量并入：`applyJournalFrame(queryClient, sessionId, envelope)` —— 追加进 `['events', sessionId]` 缓存（按 `journal_seq` 全序）。
- 后续票（#64）复用桥与节流钩子，不得另写第二失效通道。

## 7. 处理算法

### 7.1 DTO 对齐与漂移锁（REQ-UI-400-003 机制裁定）

- **机制 = OpenAPI codegen（openapi-typescript）+ 受控手写补缺**，非全手写镜像。理由：30 路径中 sessions/runs/artifacts/diagnosis/verification 面 response_model 齐全，codegen 零手写成本且天然精确；全手写镜像需要自造「TS↔OpenAPI 结构比对器」才能锁漂移，比对器本身成为新风险面；而 codegen 的漂移锁退化为「重新生成 + diff」，机械且零歧义。纯 codegen（无补缺）今天不可行的唯一原因是 17 个不可达模型（§5）——补缺面被 CI 钉死为只可缩小，伴随接线票落库后补缺归零、机制收敛为纯 codegen 全覆盖（该票验收明文「使 #61 的 DTO 对齐机制可选纯 OpenAPI codegen 且全覆盖」）。
- **CI 漂移锁设计**（每次 PR 运行）：
  1. 安装 Python 工程 → 以组合根路由面现场 dump `app.openapi()` 到临时文件（**现场 dump，不依赖仓库内快照文件**——快照仅为本规格编写期的探索产物）；
  2. 以该 dump 运行 openapi-typescript 重新生成 → `git diff --exit-code src/api/schema.gen.ts`：有差异即 FAIL（报出生成 diff，修复动作 = 本地重跑生成并提交）；
  3. 补缺只可缩小校验：dump 的 `components.schemas` 与补缺模块导出名求交，交集非空即 FAIL（报出「应从补缺删除、改用生成类型」的名字清单）。
- 后端演进时序（与 M5 伴随接线票并行，裁定 G）：本票机制针对**当前** OpenAPI（30/36）落定；伴随票合入后（拓扑/场景路由 live + 17 模型可达 + TSDuck/solution 新路由），任一前端票下一次触发生成链时 CI 即暴露 diff 与可删除补缺条目，按第 2/3 步输出机械收敛。此为设计行为（forcing function），不是缺陷。

### 7.2 hint→REST 重取矩阵（SPEC-305 §8 权威）

| hint topic（精确串） | data 键（发射点实测） | 重取动作 |
|---|---|---|
| `observation.event_appended` | journal_seq / event_id / event_type | journal 帧本身携带事实，直接增量并入事件缓存（§4.3 规则 3）；hint 仅作 cursor 兜底 |
| `observation.metric_updated` | session_id / journal_seq_watermark / previous_watermark / processed | 失效 `['metrics', sessionId]` → `POST .../metrics/query` 重拉 |
| `observation.alert_changed` | topic / session_id / alert_id / fingerprint / rule_id / state / severity | 失效 `['alerts', sessionId]` → `GET .../alerts` 重拉 |
| `observation.health_changed` | session_id / clock_domain / overall / previous | 失效 `['health', sessionId]` → `GET .../health` 重拉 |
| `observation.export_progress` | export_id / status / total_records | 失效 `['export', sessionId, exportId]` → `GET .../exports/{export_id}` 重拉 |

### 7.3 E2E 冒烟编排（REQ-UI-400-004）

- 双 webServer（Playwright）：后端 = uvicorn 加载 `src/bootstrap/asgi.py`（`DVBNEXUS_DB_PATH` 指向临时目录；Python 解释器解析顺序 = 显式环境变量 → 本树 `.venv` → 主仓共享 `.venv`，`PYTHONPATH=<本树>/src` 置前防 editable-install 指向主仓的共享 venv 陷阱）；前端 = 生产构建后的 `vite preview`（代理 `/api`、`/ws` 到后端）。CI 单 job 内同时具备 Python 与 Node。
- 冒烟骨架两文件：
  1. **shell 冒烟（本票即真实通过）**：加载 SPA → 路由区逐区导航断言（#61 交付时三路由区；SPEC-408 实施后主页 `/` 并入断言面）；建 session（REST 驱动）→ WS subscribe → `ready` 帧到达断言（验证 asgi 入口 + 泵循环 + 代理三条链路真实可用）。
  2. **八步闭环骨架（混合驱动收敛制，批准裁定）**：按 §3 八步编排 `test.step` 骨架，步骤映射镜像既有 API 级全链路先例（Create=POST /sessions；Generate=空 plan run；Inject=带 plan run 202；Analyze=进程内桥——REST analyze 冻结 501 不变；Diagnose=POST diagnose；Inspect=events+artifact content Range；Recover=再跑空 plan；Verify=POST verify 三态）。每步显式标注 `driver: "rest" | "ui"` + 归属票号：本票落地时 HTTP 面可真实驱动的步骤以 `driver: "rest"` 跑真实断言（Create/Generate/Recover/事件查询）；UI 面未落地的步骤同样允许 REST 驱动（同标注 + 归属票号），**归属票落地后 additive 翻转自己名下步骤为 `driver: "ui"`**（该 spec 文件自合入起为共享面）。例外：Analyze 步骤维持**跳过 + 标注**（M4 裁定 B 不变：进程内桥无 HTTP 面、REST analyze 冻结 501），待该面决策变化方可翻转。八步全程经 UI 通过是**验收时点属性**（后端全链路与各页面实体可用为前提），不是本票开工阻塞（票面验收明文）。

## 8. 错误处理

- REST 错误：api 客户端核心对非 2xx 统一解析信封 → 抛 `ApiError{error_code, message, retryable, details, request_id, status}`；页面按 `error_code` 家族渲染（404 会话/拓扑不存在、409 生命周期迁移非法——`details{current,target,allowed}`、422 plan/config 无效——`details.errors[]` schema path 逐条、416 Range 不可满足、503 存储不可用、501 冻结路由显式「未接线」呈现而非伪装成功）。
- WS 错误：close 码按 §4.4 状态机处理；连接状态经 `status` 暴露给 UI（重连中显式徽章，不静默）。
- **禁令**：任何 UI 本地状态不得推导业务结论（通关 = 仅渲染 `VerificationResultDTO.verdict` 三态 + 判据明细；「无告警」≠「干净」；诊断 confidence 三档是规则静态声明，禁渲染为概率/分数）。UI 状态不作通关证据（CONTEXT.md 通关词条；verify 请求体的 `ui_state` 引擎显式忽略不持久——前端不得以之为证据通道）。

## 9. 资源约束

- 部署姿态：单机单用户、`127.0.0.1` 绑定、无认证、`tenant_id` 恒 `"local"`（SPEC-500 §3 既有，前端不增设任何认证面）。
- 环境：Windows-first 开发环境（Git Bash + 原生 Python）；浏览器目标为桌面 Chromium 系（E2E CI 用 Chromium；Windows 桌面浏览器为验收环境）。CJK 文本渲染与 UTF-8 全链路保持（仓库统一 UTF-8 纪律适用于前端全部源文件）。
- 工程门禁：Node ≥ 22.12（CI 钉 22 LTS 线）+ npm ≥ 11（lockfile = `package-lock.json`，CI `npm ci`）；版本钉扎三件套 = `engines` + `.nvmrc` + CI `setup-node node-version-file`。
- `frontend/` 对既有门禁零影响：importlinter `root_packages` 全为 Python 包，不分析 frontend/；check_specs UTF-8 扫描面覆盖新增文本文件（须 UTF-8）；front-matter 校验面不含 frontend/。`node_modules/` 不入库（.gitignore 由本票建立）；每个 worktree 首次进入需重新 install。

## 10. 依赖

| 依赖 | 性质 | 消费点 |
|---|---|---|
| SPEC-001/002/003 | 领域权威（拓扑模型/事件族/结构校验） | 页面实体票消费，本规格钉词表与纪律 |
| SPEC-500 §3/§4/§6 | REST 契约（路由/信封/错误映射） | api 客户端核心 + DTO 生成链 |
| SPEC-501 §3/§4/§5/§8 | WS 契约（连接/帧/重连/close 码） | WS 客户端核心 |
| SPEC-305 §6/§8 | 观测信封形状 + hint→REST 矩阵 | 补缺类型 + 失效桥 |
| ADR-0003 第 2 条 | React + TypeScript 冻结 | 工程栈 |
| ADR-0009 | 画布纪律（@xyflow/react ^12；React Flow 内部 store 不作事实源；画布位置不持久化） | SPEC-401 normative 依据，本规格引用其 store 纪律 |
| CONTEXT.md 通关/八步闭环词条 | UI 判定禁令 | §8 错误处理禁令 |
| M5 伴随接线票（#80，裁定 E） | 17 模型入 OpenAPI + 拓扑/场景路由 live | §7.1 补缺收敛时序 |

## 11. 测试向量

- 组件/交互测试（Vitest + Testing Library，关键交互最小面）：
  - 壳导航：路由区可达（#61 交付时三区；SPEC-408 实施后含主页 `/` 与「主干/进阶」徽标）、注册表驱动渲染；
  - api 客户端：信封解析 → `ApiError` 字段（error_code/details.errors/request_id）逐键断言；501 冻结路由走「未接线」呈现分支；
  - WS 状态机：1013 慢消费 reason 解析 → 重连携带 `last_journal_seq`；4404 不重连；指数退避触发（fake WebSocket + fake timers）；
  - 失效桥：五主题 hint → 对应 query key 失效逐条断言；节流窗口内多帧合并为一次重取；journal 帧增量并入按 `journal_seq` 全序；
  - 断言纪律：断**形状**（wire 字段名/枚举串原样），不快照整页 DOM（tests/README §6 同源纪律）。
- E2E 冒烟（Playwright，§7.3 两文件）。
- Python 侧新增唯一测试：asgi 入口契约测试——**集成层**（`tests/integration/api/`，组合根整栈在导入时构建，属集成面；测试树卫生门禁 unit 层禁 I/O 即此分工）：环境变量缺省拒启语义（含 module 级 `app` 的导入时契约）、`app` 暴露 `/api/v1/version` canary、泵循环随 lifespan 启停并真实排空 journal，随既有 bootstrap 集成测试姿势（tmp db；sys.modules 快照-复原豁免形状）。

## 12. 验收标准

- **AC-400-01**（REQ-UI-400-001）：单 SPA 路由区可导航——注册表驱动，各区可达并有区域标识（#61 交付时三区；SPEC-408 增补主页 `/` 后为四区，主页实体与「主干/进阶」徽标按 SPEC-408 §4.1/§4.2 验收）；路由增量为「一条目 + 一行 import」模式且壳文件无逐票改动。
- **AC-400-02**（REQ-UI-400-002）：服务端状态 = 查询缓存 + WS journal/hint 触发重取——五主题失效矩阵逐条有测试；journal 增量并入按 `journal_seq` 全序；重连按 close 码纪律（1013 续传 cursor）有测试；前端无第二事实源结构（查询缓存外无服务端事实持有面，评审检查项）。
- **AC-400-03**（REQ-UI-400-003）：TS 类型权威机制在 CI 运行——漂移锁 job 现场 dump + 重新生成 + diff 断言（注入漂移时 CI 红）；补缺只可缩小校验在位（构造交集时 CI 红）；生成物入库且禁手改。
- **AC-400-04**（REQ-UI-400-004）：测试最小面在位——关键交互组件测试覆盖 §11 清单；E2E 冒烟骨架就位（shell 冒烟真实通过；八步骨架按 §7.3 混合驱动收敛制编排，每步 `driver` + 归属票号标注）；前端 CI 三 job（lint/test/build、DTO 漂移锁、E2E 冒烟）绿，既有 Python CI job 不受影响。

## 13. 非目标

- 不做：撤销/重做、多 tab、告警中心独立页、时间轴图表（SPEC-407 roadmap）、自定义 dashboard、流式曲线渲染；组件库级 UI 体系与主题系统；SSR/服务端渲染；i18n 框架（MVP 中文直接渲染）；移动端适配；离线模式；画布（SPEC-401）；表单引擎（SPEC-402 显式不做 rjsf 类）。
- 不冻结：节流参数具体数值（实现期钉扎并有测试）；自动布局算法（ADR-0009 交 SPEC-401 编写期）。
- 不引入：全局客户端状态库（zustand/redux 等）作为服务端事实面；第二套 WS/REST 客户端；任何绕过生成链的手写契约类型（补缺面除外，且受 §7.1 锁约束）。

## 14. 兼容性与交付要求

- SPEC-500 版本路径 `/api/v1` additive-only：生成链重跑即可吸收可选字段新增；删/改名/语义变化走 `/api/v2` 决策（届时漂移锁 CI 红，属预期捕获面）。
- 信封层兼容纪律：各层 additionalProperties=true——前端必须忽略未知可选字段（ADR-0006 决定 4）；WS 帧/journal 信封解析不得因未知字段失败。
- 交付物：`frontend/` 工程（含 CI 三 job）、`src/bootstrap/asgi.py` + 其单元测试、SPEC-INDEX-FRONTEND 本行链接更新；后续票共享面（路由注册表/dto barrel/生成配置/CI workflow/E2E 配置）改动 additive-only（裁定 C）；目录名词以本票 Implementation Plan 审定为准冻结。
- 既有 Python 门禁不变：pytest 必绿组合、`lint-imports`（分析面不含 frontend/，asgi.py 入 bootstrap 合约）、`python -I tools/check_specs.py`（SPEC-400 落盘后 NOTE 消除）。
