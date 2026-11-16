---
spec_id: SPEC-408
title: UX Guidance（旅程与引导层）
version: 0.5.1
status: APPROVED
phase: MVP
owner: Frontend
priority: P0
depends_on: [SPEC-400, SPEC-401, SPEC-403, SPEC-406]
requirements: [REQ-UI-408-001, REQ-UI-408-002, REQ-UI-408-003, REQ-UI-408-004, REQ-UI-408-005, REQ-UI-408-006, REQ-UI-408-007, REQ-UI-408-008, REQ-UI-408-009, REQ-UI-408-010, REQ-UI-408-011, REQ-UI-408-012, REQ-UI-408-013, REQ-UI-408-014, REQ-UI-408-015, REQ-UI-408-016]
---

# SPEC-408 — UX Guidance（旅程与引导层）

## 1. 目标

定义前端**引导层（UX Guidance）**的实体权威冻结点：把 Topologies / Monitor / Lab 三个功能孤岛串成一条有路标的主干旅程，使**新入职工程师不看任何文档、30 分钟内独立走通八步闭环（Create → Generate → Inject → Analyze → Diagnose → Inspect → Recover → Verify）拿到 PASS**。本规格不推翻三模块划分，只补旅程呈现层。

病根（UX 现状调查，2026-11-16 代码核实）：无首页/onboarding，`/` 重定向 /topologies（链路外模块）；Topologies 零出链、编辑器产出无 UI 消费方；session 全前端仅 Lab「开始实验」可创建，Monitor 无列表、靠手抄 UUID；Lab 八步 Stepper 纯展示不可导航，三个 run 按钮顺序靠用户自悟，verify 表单手填；唯一跨模块链路 = Lab 诊断证据 → Monitor 深链。

**八步旅程总图**（每步的承载位置；Analyze 为永久缺口，诚实呈现，当前动作指针跳过）：

| 步 | 英文 | 中文 | 一句话说明 | 发生在哪 |
|---|---|---|---|---|
| 1 | Create | 建会话 | 选一个场景开局，得到 RUNNING 会话 | Lab·场景详情 → 实验台 |
| 2 | Generate | 生成基线 | 空 plan 跑出第一批真实码流（开局自动基线可代跑） | Lab·实验台 |
| 3 | Inject | 注入故障 | 按场景 fault_plan 注入，产出 faulted artifact | Lab·实验台 |
| 4 | Analyze | 分析 | 深度分析面（MVP REST 冻结 501，诚实呈现，指针跳过） | Lab·实验台 |
| 5 | Diagnose | 诊断 | 对注入 Run 出根因候选 | Lab·实验台 |
| 6 | Inspect | 检查证据 | 从候选定位直达包字节切片 | Monitor/包检查器（Lab 深链进入） |
| 7 | Recover | 恢复重跑 | 故障清除后新 Run——通关证据的载体 | Lab·实验台 |
| 8 | Verify | 通关判定 | 服务端三态判定；PASS 只认修复后新 Run 证据 | Lab·实验台（Monitor 同口径可用） |

验收主线钉 SC-01（认识闭环：PAT 缺失）——`pass_criteria` 仅单条 mandatory 结构性判据 `fault_inactive`（从真实 `fault.*` journal 生命周期评出，不需 `ts.*` 观测流），今日纯 REST 链路可达 PASS（后端 E2E `tests/e2e/test_e2e_fault_lab_pat_missing.py` 与前端 E2E `frontend/e2e/lab.spec.ts` 双证）。SC-02~05 带观测类 mandatory 判据（`psi_*`/`cc_continuous`/`no_unexpected_cc_error`），当前诚实 INCONCLUSIVE（§10 申报 1，禁绕行不注水）。验收协议见 §12.2。

依据：[UX 引导层地图 #84](https://github.com/BingChaoLiu/DVB-Nexus/issues/84) 六张前置裁决票（[研究 #85](https://github.com/BingChaoLiu/DVB-Nexus/issues/85)、[旅程起点原型 #86](https://github.com/BingChaoLiu/DVB-Nexus/issues/86)、[示例数据原型 #87](https://github.com/BingChaoLiu/DVB-Nexus/issues/87)、[Monitor 细裁 #88](https://github.com/BingChaoLiu/DVB-Nexus/issues/88)、[Lab 细裁 #89](https://github.com/BingChaoLiu/DVB-Nexus/issues/89)、[Topologies 细裁 #90](https://github.com/BingChaoLiu/DVB-Nexus/issues/90)、[规格形态 #91](https://github.com/BingChaoLiu/DVB-Nexus/issues/91)）；外部参考 `docs/research/onboarding-patterns.md`（Wireshark/DevTools/Grafana/Postman/PWK 五参照主旅程全用常驻静态路标而非弹窗 tour；空态 = 一句话 + 单动作按钮且直接消除空态成因；示例数据必须产品内一键可达——Wireshark 示例外置 wiki 为反例）；CONTEXT.md「通关」「八步闭环」词条；SPEC-400 §4 架构纪律全文适用。原型存档 branch `prototype/journey-start-wayfinding`（#86）与 `prototype/example-data-wayfinding`（#87，叠于前者之上），不合并，供实施对照。

## 2. 范围

### 2.1 In Scope

- 旅程骨架：主页旅程门厅（新路由 `/`）、全局旅程路标条（AppShell 层）、壳导航「主页」入口与「主干/进阶」徽标（§4.1/§4.2）。
- Monitor 引导层：会话列表区、未知会话态、来源场景回跳、verify 可编辑预填、演示会话一键开门（§4.3）。
- Lab 引导层：当前动作（指针 + 指引条）、Stepper 可点击定位、run 按钮三分立 + 主级化、hints localStorage 持久化、开局自动基线、场景库 row 单入口、initial_topology 可读化（§4.4）。
- Topologies 引导层：页内常驻说明条、画布空态三问覆盖层、保存 gate 说明区、连线落空反馈、保存成功声明（§4.5）。
- 后端只读增量四件契约（session 列表 / 会话详情读回 / run 列表 / 场景 content_hash）+ 前端消费面（§6）；可选增量逐项论证（§6.5）。
- 空态三问文案总表（§4.6，引导层文案落笔权威）；文案语言规范（§3 章首）。
- 验收协议：AC 清单（§12.1）+ 30 分钟实测脚本（§12.2）。
- E2E 修正面：closed-loop verify 手填假值改真实推导值（§11.1）。

### 2.2 Out of Scope

- 视觉美化 / 设计系统（配色、组件库美术）——只管交互结构。
- SPEC-407 Timeline & Replay UI、独立告警页、自定义 dashboard（SPEC-403 §13 既有）。
- Live Mode / 真实硬件接入；多用户 / 进度存档（SPEC-406 既裁不做）。
- 编辑器功能增强（撤销/重做、复制粘贴、多 tab、平面切换、拓扑 diff 五项，SPEC-401 §2.2/§13 既裁；AC-401-06 维持）。
- 「用户自定义拓扑进闭环」（Lab 消费编辑器拓扑 / Monitor 从拓扑开局）——进阶工具定位既裁绕开；roadmap 候选，未来独立 effort。
- 弹窗 tour / coach-mark / 游戏化 / 独立演示站点 / 示例外包外部 wiki（外部参考五参照无一使用或明确反例；§13 永久非目标）。
- 规格的实施本身（前端/后端改动）与实施后的 30 分钟实测执行——归实施 effort（可用 `docs/agents/implementation-dispatch.md` 配方）。

## 3. 术语

**文案语言规范**（本章首条，全规格强制，REQ-UI-408-015）：统一中文为主，术语首现附英文对照（与 CONTEXT.md 一致）；操作指引精确到按钮文案；诚实态句式用「X ≠ Y」；全文禁「满屏数据」类表述（当前后端不产 `ts.*` 观测流，告警/诊断表行为空是诚实态）；静态路标式——禁弹窗、禁 tour、禁 coach-mark。

| 术语 | 定义 |
|---|---|
| 旅程门厅（Journey Foyer） | 主页 `/` 的形态：hero 目标句 + 大 CTA + 八步旅程地图 + 三模块空态三问卡片（§4.2） |
| 旅程路标条（Journey Wayfinding Bar） | AppShell 页眉下常驻迷你路标条：八节点 + 「你在：<区域>」+ 免责声明；位置纯 URL 派生（§4.1） |
| 空态三问 | 空态/引导文案三问句式：这是什么 · 为什么空（空/失败 ≠ 干净）· 下一步去哪（CONTEXT.md 词条；总表 §4.6） |
| 当前动作（Current Action） | 规范顺序中第一个未完成步；乱序完成照常点亮、指针不回退；全部点亮落 Verify（§7.2；CONTEXT.md 词条） |
| 主干旅程（Main Journey） | 八步闭环所在的 Lab 场景旅程；导航徽「主干」 |
| 进阶工具（Advanced Tool) | Topologies 的定位：主干旅程绕开，拿到第一次 PASS 后再探索；导航徽「进阶」 |
| 会话列表（Session List） | Monitor 无 session 参数时的主位入口区：最近会话列表 + 演示一键 + 手输兜底（§4.3） |
| 未知会话态 | `?session=` 指向不存在/已清理/输入有误会话时的显式态（非报错堆栈；§4.6 行 0） |
| 来源场景（Source Scenario） | Monitor 页头/概览的「来源场景：<scenario_id> ↗」回跳链接（增量①落地后；仅回跳不带状态） |
| 演示会话（Demo Session） | 演示一键编排产生的真实沙盘会话；与真实会话唯一差别是入口；无服务端演示标识（#88 §7 撤） |
| 演示会话条 | 页眉演示期常驻条：真实性声明 + 再跑一个 Run + 结束演示并清理（§4.3） |
| 自动基线（Auto Baseline) | Lab 开局编排第三跳：进控制台自动提交空 plan 基线 Run；失败静默回退手动（§4.4） |
| 自动基线声明条 | 实验台常驻告示：声明自动化事实 + 「真实沙盘数据，非示例」 + 下一步路标（§4.4） |
| 已保存拓扑（Saved Topology） | 拓扑库条目，编辑器产物，snake_case wire；仅供本模块载入与校验（CONTEXT.md 词条） |
| 场景初始拓扑（Scenario Initial Topology） | `initial_topology`，场景文档组成部分，camelCase wire；Lab 开局由文档治理（CONTEXT.md 词条） |
| 静态路标（Static Wayfinding) | 常驻可见的引导元素（说明条/空态卡/路标条）；与弹窗 tour 相对；本规格唯一允许的引导形态 |

## 4. 架构

### 4.1 路由与全局旅程条（REQ-UI-408-002/003）

- 路由：`/` = 主页旅程门厅（`appRoutes` 追加一条目 + 一行 import，SPEC-400 §4.2 模式；不再重定向任何区）。四路由区 = `/`（主页）+ `/topologies` + `/monitor` + `/lab`（SPEC-400 §4.2 修订句同步）。
- 壳导航：三模块保持注册表原序，不重排不分组；新增「主页」入口；Lab 条目徽「主干」、Topologies 条目徽「进阶」。
- **旅程路标条**：AppShell 层页眉下常驻——八节点迷你路标（Create → … → Verify，CONTEXT.md 八步闭环逐字）+ 「你在：<区域>」+ 免责声明。免责声明定稿：「旅程路标条只指示当前位置，不指示完成进度；通关判定只认修复后新 Run 的服务端三态判定。」
- 位置判定 = **纯 URL 派生**（§7.1 `deriveJourneyLocation`；区域：起点 / Lab 场景库 / Lab 场景详情 / Lab 实验台 / Monitor / Topologies / 其他）；不接 Lab stepper 事实进度，**不引入任何跨模块状态传递机制**（URL 参数、全局查询缓存、WS 均不需要）；导航路标 ≠ 通关判定。
- 指南衔接 = 主页模块卡片内嵌一句话指南 + 页眉右侧「查看使用指南 ↗」外链 `docs/user-guide`；不做每页页脚。
- AppShell 既有 WS 连接状态显示维持 SPEC-400 既有计划，归实施。

### 4.2 主页门厅（REQ-UI-408-001）

- hero 一句话目标：「目标：不看任何文档，30 分钟内独立走通八步闭环，拿到 PASS。」大 CTA「从这里开始：选一个场景」→ `/lab` 场景库。
- 八步闭环旅程地图：§1 总图的 UI 呈现——每步：编号 / 英文名 / 中文名 / 一句话说明 / 发生在哪；Analyze 行如实标注「不可用（REST 冻结 501），旅程自动跳过」。
- 三模块卡片（空态三问；文案定稿，§4.6 引本节为权威）：
  - **Lab（主干）**：这是主干旅程所在：场景库列出五个场景，实验台走完八步。下一步 = 点击上方 CTA 选一个场景。
  - **Monitor（证据台）**：这是自由观测台（free observation deck），按 session 展示真实运行证据。需先有 session 才有内容：从 Lab 进入，或粘贴 UUID，或一键演示。下一步按钮 = 「一键演示」（演示门，§4.3）。
  - **Topologies（进阶）**：这是进阶工具：手工搭建与校验 MPEG-TS 拓扑。主干旅程使用场景自带初始拓扑，不读这里保存的拓扑。下一步 = 拿到第一次 PASS 之后再回来探索。

### 4.3 Monitor 引导层（REQ-UI-408-004/005/006/007）

- **会话列表区**（无 `session` 参数时的主位；组件名「会话列表」）：
  - 主位 = 最近会话列表（`GET /api/v1/sessions?limit=20`，§6.1）：每行 = 创建时间 / 生命周期徽（wire 串原样）/ 场景标注或「无场景」/「跟踪」按钮（点击 → `?session=<id>`）。
  - 演示一键按钮保留在主按钮位（§4.3 演示一键）。
  - 手输 UUID 降级为次要用（列表覆盖不到时的兜底），输入即跟踪。
  - 列表加载失败 → 错误态 + 重试；手输兜底仍可用。
- **未知会话态**（新增显式态，纯前端）：`?session=` 指向不存在/已清理/输入有误的会话（snapshot 404 或 WS 4404）→ 渲染显式态而非报错堆栈，文案见 §4.6 行 0；提供「从下方最近列表重新选择；或回 Lab 开新实验」动作。
- **来源场景**：增量①落地后，页头/概览显示「来源场景：<scenario_id> ↗」链接回 Lab 场景详情页（`/lab?scenario=<id>`）。仅来源回跳，不携带任何跨模块状态；Lab → Monitor 既有 `inspect_artifact/inspect_pid/inspect_packet` 三元组深链维持不变、不追加参数。
- **verify 表单（可编辑预填，run 不自动猜）**：scenario_id ← 会话详情（§6.2）；version / content_hash ← 场景详情（现有 + §6.4）；baseline / recovery_run_id ← run 列表（§6.3）提供 datalist。全部字段用户可改，提交即声明；**绝不自动猜**基线/恢复 run。Lab 实验台 verify 表单同口径（SPEC-406 §7.4 声明串口径随之停用）。E2E 假值修正见 §11.1。
- **演示会话一键开门（A 案；纯前端编排，零后端增量）**：
  - 入口 = 会话列表区主按钮「一键演示」+ 主页门厅 Monitor 卡按钮。
  - 编排（全部现有端点，原型实测通过）：取场景（SC-01）→ `POST /sessions`（201 ready）→ `POST /start`（running）→ 基线 / 注入 / 恢复三 Run（冻结 golden 几何常量，真实字节）→ 对注入 Run 诊断。每步诚实进度列表，失败明示（§8）。
  - 落地：Monitor 带 `inspect_artifact/inspect_pid/inspect_packet` 深链预锚定注入槽位真实字节（SC-01 = faulted_ts artifact · PID 0 · packet 202，由场景 fault_plan 解析；解析失败则不带——诚实缺省）。
  - **演示会话条**（页眉，演示期常驻）：声明「数据 = 沙盘真实生成；与真实会话唯一差别是入口」+「再跑一个 Run（看 journal 实时流动）」+「结束演示并清理」（生命层可见、一键清理，对应外部参考结论 6）。
  - verify 判定**故意不自动化**——通关 = 修复后新 Run 证据，PASS 要用户自己走。

### 4.4 Lab 引导层（REQ-UI-408-008~012）

- **当前动作**（REQ-UI-408-008）：规范顺序（Create → Generate → Inject → Diagnose → Inspect → Recover → Verify；**Analyze 为永久缺口，指针跳过**）中第一个未完成步；乱序完成的步照常点亮（事实就是事实），指针不回退；全部点亮时指针落在 Verify（或显示闭环完成）。判定算法 §7.2，叠于既有 `deriveStepState` 服务端事实推导之上（SPEC-406 §7.3 不动）；词条已入 CONTEXT.md。
- **当前动作指引条**：Stepper 下方常驻一行（复用自动基线声明条模式）：下一步名称 + **精确到按钮文案**（如「下一步：注入故障 → 点击『注入故障（Inject，场景 fault_plan）』」）；步完成后自动前移；开局自动基线生效时首条指引即 Inject。
- **Stepper 可点击 = 定位非打卡**（REQ-UI-408-009）：点击任一步**滚动定位**到控制台对应区块 + 高亮闪示；未完成步的区块内已含动作按钮与禁用原因（为什么还在等）；点击**永不改变点亮状态**（点亮只来自服务端事实，不伪造进度）；免责条「stepper 进度 ≠ 通关判定」原文保留。
- **run 按钮整合**（REQ-UI-408-010）：三按钮（生成基线 / 注入故障 / 恢复重跑）**全部常驻可见，不设「高级模式」开关**（隐藏按钮 = 多一层模式决策面，且与诚实纪律相悖）；「当前动作」对应按钮升**主级样式**，其余次级；主级化**跨区块一致**——当前动作落 Diagnose/Verify 时『对注入 Run 评估（diagnose）』/『提交判定（verify）』同样升主级；不设确认弹窗（沙盘 run 便宜、可重复）；不加编号装饰——顺序感由指引条承担。
- **hints 持久化**（REQ-UI-408-011）：揭示状态从页面内存改 **localStorage 按场景键**（`dvb-lab-hints:{scenario_id}`），刷新不丢；提示区明示「已揭示 N/M（本地记录，非服务端事实）」+ 提供「重置提示」控制（重做场景可清空）；揭示状态**永不参与任何通关证据**。实验台内嵌可折叠「分阶段提示」区块，与场景详情页同一 localStorage 状态源（详情页保留完整提示区；不用深链——控制台 URL 带 `?session=`，跳详情会丢会话锚）。
- **场景库 row 单入口**（REQ-UI-408-012 部分）：row 唯一动作「查看详情」，撤失实「开始实验」（现状两按钮同 handler，「开始实验」实际只开详情）；开局唯一入口保持详情页开局区（SPEC-406 §4.2「列表行不直接开局、开局前必见详情」纪律维持，零修订面——详情页 objectives/判据即「必见」教学内容）。
- **initial_topology 可读化**：顶部统计行（「N 节点 · M 连接 · topology_id/revision」）+ 节点/端口/连接用中文标签结构化行渲染（如「连接 A:p1 → B:p2」）；原始 camelCase 文档折叠进 `<details>`「查看原始文档（键名原样）」保真。只做排版翻译，**不做键名语义翻译**；SVG 迷你拓扑图不做（视觉美化出局）。
- **开局自动基线（B 案；示例/提效数据在 Lab 的唯一接入点）**：SPEC-406 §7.1 两跳编排追加第三跳——进控制台自动提交空 plan 基线 Run（`LAB_RUN_CONFIG` 冻结 golden 几何）；实验台打开时 run 注册表已有该 Run，轮询完成后 Generate 步自亮；常驻**自动基线声明条**（「开局已自动提交基线 Run——真实沙盘数据，非示例」+ 下一步路标「注入故障」）；失败**静默回退**按钮手动流程（诚实降级，不伪装成功；回退态空文案见 §4.6）。空面板**零示例骨架填充**（C 案维持落选）。

### 4.5 Topologies 引导层（REQ-UI-408-013；五项改动面定稿）

1. **页内常驻说明条**（页顶，静态路标、可关闭性不做）：「**进阶工具** —— 这里用于手工搭建和校验 MPEG-TS 拓扑（节点 + 连线）。主干旅程（Lab 八步闭环）使用**场景自带的初始拓扑**，不会读取这里保存的拓扑；拿到第一次 PASS 之后再回来探索不迟。[去 Lab →] [回主页 →]」
2. **画布空态三问覆盖层**（仅 `nodes.length === 0` 时显示，放下第一个节点即消失）：「**这是什么**：拓扑画布——搭建 MPEG-TS 链路结构的进阶工具。**为什么是空的**：你刚新建了草稿（或拓扑库还是空的），画布上还没有节点。**下一步**：从左侧『节点类型』面板拖一个『TS 生成器』进画布开始搭建；或在上方『拓扑』下拉打开已有拓扑。也可以跳过这里，直接[去 Lab 开始主干旅程 →]。」
3. **保存 gate 说明区**（保存按钮旁常驻说明区；撤现有 hover title「校验未通过：配置待填 / 存在校验违规或字段错误」——hover-only、触屏不可见，不满足诚实反馈）：
   - 校验 gate 时：「暂不能保存：{N} 处待处理」+ 分行指向：配置待填 → 右侧「节点属性」补全 / 校验违规 → 见下方「校验」面板 / 表单字段有误。
   - 无修改时：「没有待保存的修改」；保存中：「正在保存…」；可保存时**不显示**（零噪音）。
4. **连线反馈**：拖拽中非法把手降透明度（连接前即可看出兼容性，从源头消除错误期待）；落空后工具栏状态区**一行原因提示**（约 4 秒自动消失，内联非弹窗）。原因枚举：方向不符（需 输出/双向 → 输入/双向）/「{端口}」连接数已满（上限 N）/ 平面不符（当前仅支持 MPEG_TS）/ 不能连回同一端口。SPEC-401 §7.2/§8 口径修订随本规格生效。
5. **保存成功声明**（每次显示一行）：「已保存为 revision {N}。（此处保存的拓扑仅供本模块载入与校验；Lab 场景使用场景自带初始拓扑，不会自动使用它。）」

导航「进阶」徽标 = §4.1 定义，本模块引用不重复定义。词汇纪律：「已保存拓扑」与「场景初始拓扑」严格区分（CONTEXT.md 词条）；说明条与保存成功文案必须使用这两个词各自指代，不得混称「拓扑」。

### 4.6 空态三问文案总表（REQ-UI-408-014；引导层文案落笔权威）

本章为引导层空态/诚实态文案的**落笔权威总表**（repo 主逐组定案：Monitor 组 = 细裁票 [#88](https://github.com/BingChaoLiu/DVB-Nexus/issues/88)，Lab 组 = [#89](https://github.com/BingChaoLiu/DVB-Nexus/issues/89)，Topologies 画布 = [#90](https://github.com/BingChaoLiu/DVB-Nexus/issues/90)，主页 = [#86](https://github.com/BingChaoLiu/DVB-Nexus/issues/86)）：实现以本表 + §4.2/§4.5 定稿引文为准；既有规格内嵌的陈旧文案描述（如 SPEC-406 §4.2 空库句「Lab Pack 落位后此处列出 SC-01~05」——SC-01~05 已在库，句子陈旧）由本表承接替换。三问句式 = 这是什么 · 为什么空（空/失败 ≠ 干净）· 下一步去哪。

**Monitor 组**（11 面板全组）：

| # | 面板 | 这是什么 | 为什么空 | 下一步去哪 |
|---|---|---|---|---|
| 0 | 未知/失效 session 态（新增显式态） | 当前跟踪的 session 在服务端不存在 | 可能已清理、已过期或 id 输入有误 | 从下方最近列表重新选择；或回 Lab 开新实验 |
| 1 | 入口 SessionGuide（会话列表区） | Monitor 是自由观测台（free observation deck），按 session 作用域展示八步闭环的真实运行证据 | 尚未选择任何 session | 从 Lab 选场景开始实验后自动进入；或一键演示；或在最近列表选择；或手输 UUID |
| 2 | 概览 | 该会话的生命周期与快照摘要（lifecycle / snapshot） | 快照数据未到达（会话不存在、未启动或后端未运行） | 查看运行控制面板的生命周期状态；确认后端已启动（仓库根 `start.cmd`） |
| 3 | Run 触发 | 向该会话提交 Generate Run 的入口（空 plan 或含配置） | 本页尚无已注册的 run | 提交基线 Run 观察码流生成；或回 Lab 走主干旅程 |
| 4 | PID/指标 | MPEG-TS 包级指标序列查询窗口（PID = Packet Identifier） | 该窗口内查询无返回序列；当前后端阶段不产 ts.* 观测流（缺失 ≠ 零） | 先走 Generate/Inject 拿到 artifact；指标分析属进阶观测 |
| 5 | 告警 | 规则引擎产出的告警记录列表 | 无告警记录 ≠ 干净：MVP 阶段告警泵未接入（无观测） | 排障以诊断候选与包检查为准 |
| 6 | 诊断 | 诊断规则产出的根因候选列表（候选 ≠ 事实） | 该会话尚无 diagnose 报告（不代表码流干净） | 从 run 列表选 id 提交 diagnose；或从 Lab 诊断步深链进入 |
| 7 | 包检查（下钻） | 诊断定位器指向的 artifact 字节切片与结构解析 | 尚未从诊断候选点「定位」进入 | 先提交 diagnose，再点候选行的定位按钮 |
| 8 | verify | 通关判定提交口：以**修复后新 Run** 的证据换取服务端三态判定（PASS/FAIL/INCONCLUSIVE） | 尚无判定结果 | 跑基线+注入+恢复三个 Run 后提交；场景身份可自动预填 |
| 9 | journal 尾窗 | 该会话的 journal 流水尾窗（事件信封，per-session 单调流水号） | WS 未连接或该会话尚无事件 | 启动会话或跑一个 Run，观察帧流入 |
| 10 | CLI 对照 | 该会话的 TSDuck 调用记录与来源区分（来源标识 ≠ 双解析器 diff） | MVP 生产栈不产生真实 TSDuck 调用；空列表不是「无问题」信号 | 无需动作；接入实机/fixture 种子后此面板才有行 |

**Lab 组**（7 行全组）：

| 面板 | 标题 | 副文（为什么空 · 下一步） |
|---|---|---|
| 场景库·空库 | 注册表暂无场景文档 | 空库 ≠ 错误：服务端场景注册表为空。下一步：`start.cmd` 一键启动后端并完成场景扫描 |
| 场景库·读取失败 | 场景注册表读取失败 | 失败 ≠ 空库：GET /scenarios 请求失败。下一步：确认后端已运行，[重试] |
| Run 注册表·空（自动基线失败回退时才可见） | 尚无 Run | 本会话尚未触发任何 Run（开局自动基线未成功，回落手动流程，诚实态）。下一步：点击『生成基线（Generate，空 plan）』 |
| 诊断区·空（新增，现状无文案） | 尚无诊断报告 | 诊断不自动发生：注入 Run 完成后点击『对注入 Run 评估（diagnose）』；无观测 ≠ 干净，空表是诚实态 |
| 事件列表·零事件（新增，现状无文案） | 暂无 journal 事件 | 会话已建立但引擎尚未产生事件（空 ≠ 错误）。下一步：触发一个 Run 后回来查看 |
| HintsLadder·空 | 本场景未声明提示 | 维持现有文案不动（文档事实，无消除空态的动作可给） |
| 参考解·未声明 / VerifyResultCard 判据空 | — | 维持现状（后者为 Monitor 共享组件，#88 已定案，不重裁） |

**Topologies 组**：画布空态三问 = §4.5 第 2 项定稿引文（画布唯一空态；其余次级状态——如「尚未校验」「— 未选择 —」——是否调整归通读统一把关，本表不预改）。

**主页组**：三模块卡片三问 = §4.2 定稿引文。

## 5. 数据模型

- 本规格**不定义新业务实体**；新 wire 形状仅 §6 四件只读增量（additive）。前端类型权威 = 生成链 `schema.gen.ts`（SPEC-400 §5/§7.1，禁手写 mirror）；若某响应暂不可达 OpenAPI（handler 裸 dict），按 SPEC-400 补缺机制收窄申报，接线票落库后删除补缺。
- 新形状（wire snake_case 原样）：
  - `SessionListItemDTO`：`session_id / lifecycle / created_at_ms / scenario_id? / topology_revision`（§6.1）。
  - 会话详情扩展（既有 `SessionViewDTO` 或详情视图）：`scenario_id? / created_at_ms`（§6.2）。
  - `RunListItemDTO`：`run_id / status / submitted_at_ms / fault_plan_present / packet_count?`（§6.3）。
  - `ScenarioDetailDTO` 扩展：`content_hash`（§6.4）。
- **localStorage 键**：`dvb-lab-hints:{scenario_id}`（值 = 已揭示 hint 索引/计数）。属 UI 本地状态（SPEC-400 §4.3 规则 4：只承载 UI 事实），UI 明示「本地记录，非服务端事实」，**永不参与通关证据**。
- 演示编排、旅程路标条位置、当前动作指针均为纯派生或页面态——不新增服务端事实持有面（无跨模块状态传递机制，§4.1）。

## 6. 公开接口（后端只读增量契约，REQ-UI-408-005）

四件**全部只读**：零写路径、零状态迁移面；`/api/v1` additive-only（SPEC-400 §14 既有）。逐项论证见 §10。

### 6.1 session 列表（细裁票 #88 §1 裁决采纳）

```text
GET /api/v1/sessions?limit=<1..100，默认 20>
→ 200 SessionListItemDTO[]
```

按 `created_at` 倒序；默认 20 条、上限 100；**不分页**（MVP）；只读。代价 = 推翻 SPEC-403 §13「session 列表/搜索」non-goal 与 SPEC-406「无 session 列表端点」纪律句（修订面已随本落笔执行，§14）。

### 6.2 增量①：会话详情读回

`GET /api/v1/sessions/{id}` 现有视图 additive 扩展：`scenario_id?` + `created_at_ms`（若实现取独立详情视图，字段面同此）。scenario_id 目前 write-only，是「数据来历不明」的结构性根源；verify 预填、来源回跳（§4.3）、列表标注三处消费。

### 6.3 增量②：Run 列表

```text
GET /api/v1/sessions/{id}/runs
→ 200 RunListItemDTO[]
```

排序 = `submitted_at_ms` 升序（八步叙事序）；不分页（MVP，姿态同 §6.1）；上限随实现钉扎并申报；只读。现状 run 注册表是页内存，深链/刷新/手输进入后 datalist 全空；verify 的 baseline/recovery 与 diagnose 的 run id 全靠手抄；journal 无 REST 历史回读，前端解析 journal 属脆弱推断——一个只读列表解决三处。

### 6.4 增量③：场景 content_hash

`GET /api/v1/scenarios/{id}` 的 `ScenarioDetailDTO` additive 增加 `content_hash`（loader 钉扎哈希，SPEC-205 §5 语义）。SPEC-406 §10 申报 2 已预先申报的 additive 面被采纳兑现；verify 身份三要素（scenario_id/version/content_hash）中唯一完全不可得的字段；真实钉扎哈希比声明串更诚实；单字段只读。SPEC-406 §7.4 声明串 `lab-ui-unpinned` 口径随之停用。

### 6.5 可选增量（逐项论证，不列 MVP 必需）

- **服务端预热 demo session**（示例数据票 #87 遗留可选增量①）：收益 = A 案免等待落地；代价 = 启动时编排引入启动失败面 + 演示会话垃圾与清理策略。演示编排已实测纯前端数秒完成，故列为**可选优化**，由实施票实测后裁量，不做 MVP 验收门槛。
- **session 元数据演示标识 + 页眉演示徽**：已由细裁票 #88 §7 **撤销不采纳**（需写路径增量；演示会话与真实会话唯一差别是入口，列表中旧演示会话显示为普通会话并不失实）。

### 6.6 前端消费面

- `src/api` 领域函数 additive：`listSessions(limit?)` / `listSessionRuns(sessionId)`（落位 `src/api/endpoints/`，经 barrel 导出，SPEC-401 §6.1 先例）；会话详情扩展与 `content_hash` 经生成链重跑吸收（禁手改生成物）。
- 演示编排落位参考原型 `exampleDataOrchestrate.ts`（phase 化，复用 `labBodies`/`labGeometry`）。

## 7. 处理算法

### 7.1 旅程位置派生（`deriveJourneyLocation`，REQ-UI-408-002）

纯函数：URL → 区域枚举 `起点 / Lab 场景库 / Lab 场景详情 / Lab 实验台 / Monitor / Topologies / 其他`（判定规则：`/` = 起点；`/lab` 无参 = 库；`/lab?scenario=` 无 session = 详情；`/lab?scenario=&session=` = 实验台；`/monitor` = Monitor；`/topologies` = Topologies；其余 = 其他）。参照原型 `journeyPrototype.ts` 同名函数；单测逐区域正负例（§11.2）。

### 7.2 当前动作判定（REQ-UI-408-008）

叠于 `deriveStepState`（SPEC-406 §7.3 既有，服务端事实映射）之上的单一指针层：规范序 `[Create, Generate, Inject, (Analyze 恒缺), Diagnose, Inspect, Recover, Verify]` 中**第一个未完成步**即当前动作；乱序完成的步照常点亮、指针不回退；全部点亮 → 指针落 Verify（或显示闭环完成）。Analyze 永不在指针候选中（永久缺口）。纯函数单测穷举（§11.2）。

### 7.3 开局自动基线第三跳（REQ-UI-408-012）

SPEC-406 §7.1 两跳（create → start → 导航控制台）后追加：自动提交空 plan 基线 Run（`LAB_RUN_CONFIG` 冻结几何）→ 202 入 run 注册表 → 既有 200ms 轮询器接管 → completed 后 Generate 步自亮（§7.3 映射表既有事实源）→ 自动基线声明条常驻。**失败静默回退**：任一跳失败不阻断进入控制台、不伪装成功，Run 注册表空态文案（§4.6）如实呈现「自动基线未成功，回落手动流程」。

### 7.4 演示编排 phase 机（REQ-UI-408-007）

phase 序：`scenario → create → start → generate → inject → recover → diagnose → land`；每 phase 一行诚实进度（进行中/完成/失败三态，失败行显式原因 + 「后端未运行？`start.cmd`」指引）；任一 phase 失败即停在原地不落地、已建会话保留可手动清理；落地 = 导航 `?session=<demo-session-id>` + 预锚定深链（SC-01 = faulted_ts · PID 0 · packet 202，由场景 fault_plan 解析，解析失败不带）+ 页眉演示会话条。「结束演示并清理」= `DELETE /sessions/{id}`（204）+ 本地演示态清空。verify **不自动提交**。

### 7.5 verify 预填推导（REQ-UI-408-006）

三来源映射：`scenario_id` ← 会话详情（§6.2）；`version` / `content_hash` ← 场景详情（现有 + §6.4）；`baseline_run_id` / `recovery_run_id` 候选 ← run 列表（§6.3）渲染 datalist（Monitor 与 Lab 同口径）。预填全部可编辑；**run 永不自动猜**——用户未明确选择前不提交（声明语义保留：提交即声明）。

### 7.6 连线落空原因映射（REQ-UI-408-013）

复用 SPEC-401 §7.2 `isValidConnection` 四项预检的失败项生成原因文案：方向 → 「方向不符（需 输出/双向 → 输入/双向）」；基数 → 「“{端口}”连接数已满（上限 N）」；单平面 → 「平面不符（当前仅支持 MPEG_TS）」；自环 → 「不能连回同一端口」。拖拽中同步计算非法把手集降透明度（预览）。提示约 4 秒自动消失，内联非弹窗。

## 8. 错误处理

| 场景 | 处理 |
|---|---|
| 演示编排任一 phase 失败 | 进度行显式失败 + 「后端未运行？`start.cmd`」指引；不落地、不伪装成功；已建会话保留可清理（§7.4） |
| 开局自动基线失败 | 静默回退手动流程（诚实降级）；Run 注册表空态如实呈现回退事实（§4.6 Lab 组行 3） |
| 未知/失效 session（snapshot 404 / WS 4404） | 「未知会话态」显式态（§4.6 Monitor 组行 0），非报错堆栈 |
| 会话列表加载失败 | 列表区错误态 + 重试；手输 UUID 兜底仍可用 |
| localStorage 不可用（隐私模式等） | hints 退回页面内存态 + 明示「本地记录不可用，刷新将复位」（诚实降级） |
| 非法连线落空 | 一行原因提示约 4 秒自动消失（§7.6）；连接不建立，无弹窗 |
| 全部空态/失败面 | 诚实态纪律全文适用：无观测 ≠ 干净、缺失 ≠ 零、失败 ≠ 空库、空 ≠ 错误、进度 ≠ 通关判定（CONTEXT.md 通关词条；SPEC-400 §8 禁令） |

## 9. 资源约束

- **纯前端优先**（地图既裁偏好）：纯前端能解决的不动后端；本规格新增后端面仅 §6 四件只读（可选增量见 §6.5）；演示编排与自动基线均零后端增量。
- 静态路标式：禁弹窗、禁 tour、禁 coach-mark、禁模式开关式引导（§3 文案语言规范）；不引入全局客户端状态库（旅程条 URL 派生，无跨模块状态传递）。
- localStorage 仅 `dvb-lab-hints:{scenario_id}` 一键族；无其他新增持久化；无新增运行时依赖（自绘组件集延续，SPEC-400 §4.1）。
- 文案统一中文为主、UTF-8 全链路（check_specs 扫描面适用）；无移动端适配（SPEC-400 §9 既有）。

## 10. 依赖

| 依赖 | 性质 | 消费点 |
|---|---|---|
| SPEC-400（0.5.1） | SPA 基座：路由注册/壳导航/生成链/失效桥/错误信封 | §4.1/§5/§6.6 全部基础设施，禁另起第二机制 |
| SPEC-403（0.5.1） | Monitor 页面实体与导出组件 | §4.3 引导层叠加于其上；§4.1 入口句修订 |
| SPEC-406（0.5.1） | Lab 页面实体（开局编排/stepper 映射/hints/run 触发区） | §4.4 全部引导层叠加于其上 |
| SPEC-401（0.5.1） | 拓扑编辑器（预检四项/保存流/gate） | §4.5 反馈层；§7.6 原因映射复用预检结果 |
| SPEC-500 §4/§6 | REST 契约与错误信封 | §6 四件只读增量按 additive 落 `/api/v1` |
| SPEC-205 §5 | 场景 loader 钉扎哈希语义 | §6.4 `content_hash` 字段语义 |
| CONTEXT.md | 「通关」「八步闭环」「当前动作」「空态三问」「已保存拓扑/场景初始拓扑」词条 | 全文纪律与词汇 |
| 外部参考（#85） | `docs/research/onboarding-patterns.md` 五参照结论 | §1 依据；§13 永久非目标外部证据 |

**后端增量逐项论证**（repo 主逐项采纳裁决，#88 §3 + #87 遗留收敛；「纯前端能解决的不动后端」偏好遵守——演示编排/自动基线不在增量内）：

| 增量 | 内容 | 逐项论证 |
|---|---|---|
| session 列表 | `GET /api/v1/sessions`（§6.1） | Monitor 入口从手输 UUID 升级会话列表区的前提；代价 = 推翻 SPEC-403 §13 与 SPEC-406 纪律句（修订随本落笔执行，§14） |
| 增量① 会话详情读回 | `scenario_id?` + `created_at_ms`（§6.2） | scenario_id 目前 write-only，是「数据来历不明」的结构性根源；verify 预填、来源回跳、列表标注三处消费；深链塞 URL 参数的纯前端替代可伪造且手输场景无解，故走权威读回 |
| 增量② Run 列表 | `GET /sessions/{id}/runs`（§6.3） | run 注册表页内存在深链/刷新/手输场景全空；verify 与 diagnose 的 run id 全靠手抄；journal 无 REST 历史回读，前端解析属脆弱推断；一个只读列表解决三处 |
| 增量③ 场景 content_hash | 详情 DTO 加字段（§6.4） | SPEC-406 §10 申报 2 预先申报的 additive 面兑现；verify 身份三要素唯一完全不可得字段；真实钉扎哈希比声明串更诚实 |

可选增量（服务端预热）论证见 §6.5；演示标识已撤（#88 §7）。**申报 1（Analyze HTTP 面，沿 SPEC-406 §10 申报 1 立场）**：观测类判据（`psi_*`/`cc_continuous`/`no_unexpected_cc_error`）的 `ts.*` 证据无 HTTP 生产面（进程内桥、REST analyze 冻结 501），SC-02~05 诚实 INCONCLUSIVE；本规格禁任何绕行（禁伪造候选/禁本地观测推断/禁「满屏数据」措辞），观测类 PASS 可达性 = 后端伴随票决策。

## 11. 测试向量

### 11.1 事实记录（2026-11-16 核实，落笔前置调查）

- `frontend/e2e/closed-loop.spec.ts` 的「八步全绿」**并不断言 PASS**——verify 手填假值（`:205-210`）且断言容忍三态任意一种（`:214-217`）；真 PASS 断言在 `frontend/e2e/lab.spec.ts`（SC-01 断言真实服务端 PASS）。
- 修正面（REQ-UI-408-016）：closed-loop E2E verify 手填假值**改真实推导值**（推导源 = §7.5）；「断言容忍三态」的冒烟姿态维持（真 PASS 主线由 `lab.spec.ts` 与 §12.2 实测承载）。
- 生产组合事实：观测/诊断/场景/CLI 对照端口全部绑定（`bootstrap/app.py:437-441`），各面板生产上是「空 200 诚实态」而非 501；唯一无条件 501 = `POST /artifacts/{id}/analyze`；`ts.*` 序列为空是因无产出泵。

### 11.2 组件/交互测试（Vitest + Testing Library；断形状，不快照 DOM）

- `deriveJourneyLocation`：七区域逐 URL 正负例（含 `/`、`/lab` 三态、`/monitor?session=`、未知路由 → 其他）。
- 当前动作：乱序完成不回退、全 done 落 Verify、Analyze 恒不在候选、首条指引随自动基线为 Inject。
- Stepper 点击：滚动定位 + 高亮闪示回调；点亮状态不受点击影响。
- run 按钮主级化：当前动作按钮主级、其余次级；diagnose/verify 区块同规断言。
- hints：localStorage 读写按场景键；「重置提示」清空；「已揭示 N/M（本地记录，非服务端事实）」明示渲染；不可用降级内存态。
- 自动基线：成功并入注册表 + 声明条渲染；失败静默回退 + 回退态空文案。
- 演示编排：mock api phase 机逐步推进；失败行显式；清理清空本地态；**零 verify 提交断言**。
- verify 预填：三来源映射断言 + run datalist 渲染；无自动猜（未选择时不发 verify 请求）。
- Topologies：gate 说明区三类原因分行/无修改/保存中三态；落空提示文案与 4 秒消失；保存成功声明每次显示；说明条/画布空态渲染与消失时机。
- 文案总表：§4.6 + §4.2/§4.5 定稿文案逐行渲染断言（键句原样）。

### 11.3 E2E（Playwright，双 webServer 既有编排）

- 主干旅程：主页 → CTA → SC-01 开局（自动基线声明条可见）→ 八步（Analyze 诚实呈现、指针跳过）→ verify PASS → 参考解展开（`lab.spec.ts` 既有链 additive 扩展主页起点与指引条断言）。
- Monitor：会话列表跟踪（列表行 → `?session=`）；未知会话态显式呈现；演示一键全编排 → 预锚定字节 → 演示会话条 → 清理。
- Topologies：说明条常驻；画布空态覆盖层放下首节点消失；gate 说明区与落空提示。

## 12. 验收标准

### 12.1 AC 清单

- **AC-408-01**（REQ-001/002/003/015，旅程骨架）：主页门厅渲染（hero 目标句 + CTA + 八步旅程地图 + 三模块卡 + 指南衔接）；旅程路标条全局常驻且纯 URL 派生（七区域 + 免责声明原文）；导航含「主页」入口与「主干/进阶」徽标（不重排不分组）；无任何弹窗/tour/模式开关（评审检查项）。
- **AC-408-02**（REQ-004/006，Monitor 引导）：会话列表区三件套（列表主位 + 演示一键 + 手输兜底）；未知会话态显式呈现；「来源场景」回跳链接；verify 可编辑预填三来源 + run datalist 且无自动猜。
- **AC-408-03**（REQ-005，后端增量契约）：§6 四件只读增量在位，契约逐字段一致（后端契约/E2E 测试）；前端领域函数 additive、生成链吸收新字段（dto 漂移锁绿）。
- **AC-408-04**（REQ-007，演示一键）：一键编排全链真实落地（SC-01 会话 + 三 Run + 诊断，真实后端）；包检查器预锚定注入槽位字节；演示会话条声明 + 一键清理；verify 不自动化（测试断言零提交）。
- **AC-408-05**（REQ-008/009/010，Lab 当前动作）：指针规则单测穷举绿；指引条精确到按钮文案；Stepper 点击定位不打卡（点亮不受影响 + 免责条保留）；三分立常驻 + 主级化跨区块一致；零模式开关。
- **AC-408-06**（REQ-011，hints）：localStorage 按场景键刷新不丢；重置控制；「本地记录，非服务端事实」明示；揭示状态不参与任何通关证据（代码审查项）。
- **AC-408-07**（REQ-012，开局与场景库）：自动基线第三跳 + 声明条 + 失败静默回退；场景库 row 单入口「查看详情」；initial_topology 统计行 + 中文结构化渲染 + 原始文档折叠保真（键名原样断言）。
- **AC-408-08**（REQ-013，Topologies 五项）：说明条/画布空态/gate 说明区/连线反馈/保存成功声明落位；SPEC-401 §7.2/§8/§12/§13 修订生效（AC-401-07 绿）。
- **AC-408-09**（REQ-014，文案总表）：§4.6 + §4.2/§4.5 定稿文案逐行落位（三模块 + 主页）；陈旧文案被替换（场景库「Lab Pack 落位」句、场景库 row 失实「开始实验」、Monitor 失实入口句、gate hover title）；诚实纪律句（无观测 ≠ 干净等）完整保留（渲染断言）。
- **AC-408-10**（REQ-016，E2E 修正）：closed-loop verify 真实推导值；`lab.spec.ts` SC-01 UI 全链 PASS 维持绿；§11.3 引导层 E2E 绿。
- **AC-408-11**（全门）：前端六门（lint/typecheck/test:run/build/dto:check/e2e）+ 后端三门（pytest 必绿组合 / lint-imports / check_specs）全绿；`python -I tools/check_specs.py` 0 failed。

### 12.2 实测脚本（30 分钟验收协议，REQ-UI-408-015）

- **PASS 定义**（与 CONTEXT.md「通关」词条逐字对齐）：Verify 返回服务端三态中的 **PASS**，且证据为修复后新 Run 的真实 journal 证据。UI 变绿、流程走完、INCONCLUSIVE、超时、求助均不算 PASS。
- **实测人** = repo 主（地图既裁）；不设第二实测人门槛，可另邀一名未参与本 effort 者做加分观测。
- **计时零点** = `start.cmd` 后端 + 前端就绪、浏览器落在主页那一刻；环境准备不计入 30 分钟。
- **迷路兜底** = 允许使用产品内一切路标（它们正是被测对象）；求助文档/外部人员或超 30 分钟 = FAIL。
- **主线场景** = SC-01（认识闭环：PAT 缺失）。

任务单（每任务一个可观测判分点）：

| # | 任务 | 判分点 |
|---|---|---|
| 0 | 打开主页（start.cmd 就绪落主页） | 主页可见 hero 目标句 + 「从这里开始：选一个场景」CTA + 八步旅程地图 |
| 1 | 选场景开局 | 不看文档、仅凭页内路标 ≤3 次点击从主页进入 SC-01 详情并开局进实验台 |
| 2 | 观察开局自动基线 | 实验台可见自动基线声明条；Generate 步已点亮；指引条显示下一步「注入故障」 |
| 3 | 注入故障 | 点击指引条所指按钮；run 注册表出现注入 run 并到 completed |
| 4 | Analyze 诚实呈现 | 页内如实呈现 Analyze 不可用（REST 冻结 501 面）；当前动作指针已跳过该步；不阻塞主干 |
| 5 | 诊断 | 指引条指向 diagnose；「对注入 Run 评估（diagnose）」按钮为主级；点击后诊断区呈现候选或诚实空态 |
| 6 | 检查证据 | 从候选「定位」直达包检查器字节切片（字节可见）；或经旅程路标进 Monitor 查看 |
| 7 | 恢复重跑 | 「恢复重跑」新空 plan run completed |
| 8 | Verify 拿 PASS | verify 三要素已预填可编辑；从 datalist 选基线/恢复 run；提交后结果卡渲染服务端三态 = PASS；参考解解锁可展开 |
| 9 | 加分项（不计 PASS 门槛） | SC-04 走链得 INCONCLUSIVE 卡 + `NOT_EVALUATED`/`SIM_VERIF_EVIDENCE_MISSING` 明细行（训练「无观测 ≠ 干净」眼力）；体验 Monitor 旁路演示一键 |

全程 ≤ 30 分钟、零文档、零外部求助 = PASS。Monitor 告警/指标等面板判分只要求「如实呈现诚实态」（空面板是诚实态，非缺陷；任务单全文禁「满屏数据」措辞）。

## 13. 非目标

- 弹窗 tour / coach-mark / 游戏化 Arcade / 独立演示站点 / 云端限时强制销毁 / 示例外包外部 wiki（外部参考 #85 五参照无一使用或明确反例；永久禁令非 MVP 裁量）。
- 视觉美化 / 设计系统（配色、组件库美术、SVG 拓扑缩略图）；键名语义翻译（§4.4 只排版翻译）。
- SPEC-407 Timeline & Replay UI、事件浏览页、独立告警页、自定义 dashboard、流式曲线（SPEC-403/400 §13 既有）。
- Live Mode / 真实硬件接入；多用户 / 进度存档 / 计分（SPEC-406 既裁）。
- 编辑器功能增强五项（SPEC-401 §2.2/§13 既裁；AC-401-06 维持）；「用户自定义拓扑进闭环」（进阶定位既裁，roadmap 候选）。
- 「满屏数据」类观测承诺与观测类判据 PASS 可达性（§10 申报 1；后端伴随票决策）。
- verify 自动化判定、run 自动猜（§4.3 声明语义保留，永久）。
- 规格的实施本身与 30 分钟实测的执行（归实施 effort）。

## 14. 兼容性与交付要求

- **批准流**：本规格落笔 = DRAFT_FOR_REVIEW 0.5.1；repo 主通读确认后翻 APPROVED（与地图目的地「规格成文并通过通读确认即到达」对齐，[地图 #84](https://github.com/BingChaoLiu/DVB-Nexus/issues/84)）。
- **同批交付的既有文档修订面**（规格形态票 [#91](https://github.com/BingChaoLiu/DVB-Nexus/issues/91) 裁决清单，本落笔执行）：

| 文件 | 定点修订 |
|---|---|
| SPEC-400 → 0.5.1 | 「三路由区」句改四区（增主页 `/` 旅程门厅）；壳导航「主页」入口 + 「主干/进阶」徽标（§1/§2.1/§3/§4.2/§12） |
| SPEC-401 → 0.5.1 | §7.2 连线口径改「预览降透明 + 落空一行提示」；§8 提及落空提示；§12 增引导层 AC-401-07；§13 增非目标「编辑器拓扑接入主干旅程（消费方集成）」 |
| SPEC-403 → 0.5.1 | §4.1 入口句改会话列表区；§12 增引导层 AC-403-08；§13「session 列表/搜索（无后端通路）」非目标撤销改写 |
| SPEC-406 → 0.5.1 | §4.3「无 session 列表端点」纪律句改写；§7.4 content_hash 声明串口径停用；§10 申报 2 更新（增量③采纳）；§12 增引导层 AC-406-09 |
| CONTEXT.md | 词条「当前动作」「已保存拓扑」「场景初始拓扑」「空态三问」 |
| REGISTRY §D / SPEC-INDEX-FRONTEND | SPEC-408 行 + 包版本 0.5.0 → 0.5.1 |

- **实施归后续工单**（可用 `docs/agents/implementation-dispatch.md` 配方）：前端引导层实体 + §6 四件只读后端增量 + §11.1 E2E 修正；§12.2 实测执行归实施 effort。
- 共享面 additive-only：`appRoutes` 追加 `/` 条目 + AppShell 旅程条/导航徽标；`src/api` 领域函数 additive；生成链吸收新 DTO（漂移锁绿）；禁第二 WS/REST 通道、禁全局状态库（SPEC-400 纪律）。
- 组件复用边界维持既裁：Monitor = 自由观测台、Lab = 场景语境引导；诊断/verify 呈现组件定义在 SPEC-403、SPEC-406 复用（#18 Q5），本规格不重裁。
- 门禁：前端六门 + 后端三门 + `python -I tools/check_specs.py` 0 failed。
