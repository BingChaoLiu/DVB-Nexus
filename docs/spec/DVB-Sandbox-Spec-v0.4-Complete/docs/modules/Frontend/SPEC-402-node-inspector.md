---
spec_id: SPEC-402
title: Node Inspector
version: 0.5.0
status: APPROVED
phase: MVP
owner: Frontend
priority: P0
depends_on: [SPEC-401, SPEC-500]
requirements: [REQ-UI-402-001, REQ-UI-402-002, REQ-UI-402-003]
---

# SPEC-402 — 节点表单（Node Inspector）

## 1. 目标

定义 MVP 拓扑画布的**节点属性表单**实体权威冻结点：每节点类型声明式字段清单 → 控件映射（数据源 = SPEC-108 §4 JSON↔DTO 映射 + NodeType 注册表 `config_schema` 指针 + 生成类型，前端不自造字段）；校验错误按 schema path 定位到字段展示（两口径：保存路径 400 `REQUEST_BODY_INVALID` loc 链 + run prepare 422 自由文本串）；draft 编辑与**校验门**（校验不通过时保存/启动 session 入口禁用）。

依据：MVP 切集预批准（ticket #18）、SPEC-401 §6.2（#62 对 #63 的共享面：注册表 / graphMapping / violations / ViolationPanel）、SPEC-108 §4（`GeneratorConfig` 配置模型 + JSON 字段级映射表 + §5 配置校验约束）与 §4 权威 wire 映射（`src/api/dto/generator.py` ↔ 生成类型 `schema.gen.ts` 的 `GeneratorConfigDTO`/`ProgramDTO`/`ElementaryStreamDTO`）、SPEC-500 §4.1（topology 路由）/§6（错误信封；`REQUEST_BODY_INVALID` 400 的 path-addressed `details.errors[].loc` 链）、ADR-0008 第 2 条（码率包络 1~100 Mbps）、ADR-0009（画布受控纪律，本表单为草稿组合面）。

**MVP 后端现实下的诚实边界**（本规格的立论前提，报批核心）：后端对拓扑**结构**的校验入口 = `POST /topologies/{id}/validate`（存储图，保存流固定第三步，SPEC-401 §7.4）与 session VALIDATING（SPEC-200 §6，#64 面）；对 generator **config 内容**的唯一校验入口 = run prepare（422 `SIM_TS_CONFIG_INVALID`/`SIM_TS_PLAN_INVALID`，#64 提交面触发）。持久化路由（POST/PUT topology）不跑业务校验器（SPEC-401 §7.4 第 4 条）。因此「表单级校验通过」在 MVP 不存在单一服务端判定，本规格以**三元联合门**（§7.6）显式组合现有信号，不为过门禁发明前端 JSON Schema 校验器（§2.2）。

## 2. 范围

### 2.1 In Scope

- 节点属性表单组件（选中画布节点 → 侧栏表单）：声明式渲染字段清单，清单来源唯一 = `config_schema` 指针（MVP 仅 `ts_generator` → `GeneratorConfigDTO`）。
- `GeneratorConfigDTO` 全字段（含 `ProgramDTO`/`ElementaryStreamDTO` 嵌套）的**冻结描述符表**：类型 / wire 默认值 / 控件形态 / SPEC-108 §4~§5 约束注记，逐字段列出（§5.1）。
- 控件形态闭集六种：数字输入 / 文本输入 / 冻结枚举下拉 / 契约单值锁定勾选 / 嵌套分组 / 行列表编辑（§5.2）——手写描述符表直配控件，非通用引擎。
- `config_schema = null` 类型（ts_mux/ts_demux/ts_monitor）与未注册 node_type 的**诚实态**：「该类型无配置字段（config 恒 `{}`）」，零字段渲染。
- 编辑流：表单本地编辑 → 显式「应用到草稿」→ additive action 写入画布草稿 `node.config`（opaque 载荷原样，SPEC-401 §2.2 既述）→ dirty。
- 校验错误字段级定位（REQ-UI-402-002）两口径：
  - **口径 A**：保存（POST/PUT）400 `REQUEST_BODY_INVALID` 的 `ApiError.details.errors[].loc` 链 → 节点索引解析 → 表单字段/节点级回填（§7.4）；
  - **口径 B**：run prepare 422 `SIM_TS_CONFIG_INVALID`/`SIM_TS_PLAN_INVALID` 的 `details.errors[]` 自由文本串 → 声明式字段路径词边界匹配尽力落字段，未命中降级面板/节点级，不伪造映射（§7.5；触发面归 SPEC-403/406，本规格交付匹配器 + 字段错误呈现，模式同 SPEC-401 §7.5 触发归属）。
- 校验门（REQ-UI-402-003）：三元联合门纯函数（§7.6）——保存入口禁用联动 + 门判定导出供 session 入口所有票（SPEC-403/406）消费；编辑器自身不渲染 session 入口。
- 约束注记呈现：SPEC-108 §4/§5 权威约束（如 `target_bitrate_bps` 1~100 Mbps）以**静态提示文本**呈现——仅注记，不做客户端强制（§2.2）。

### 2.2 Out of Scope

- **通用 JSON Schema 动态表单引擎（rjsf 类）**：不做 schema 解析器、不做运行时内省、不做 schema→控件自动推导。本规格的描述符表是**手写的单 schema 冻结表**（恰一个非 null `config_schema`），渲染器只认 §5.2 六种控件 kind——引擎特征（解析/推导/通用布局）一项都不存在。
- **字段级实时校验**：字段编辑不触发任何校验调用、不执行任何本地约束判定（含范围/交叉检查）；完备性标记是「填没填」的编辑态陈述，不是正确性结论（§7.3 论证）。权威校验永远在后端（SPEC-401 §4.1 第 4 条同源纪律）。
- **自定义表单布局**：单一标准布局（字段清单垂直分组 + `program` 嵌套一组 + `streams` 行列表），无布局系统、无主题机制、无用户可配置布局。
- session/run 控制入口（SPEC-403/406 各票）：本规格只导出门判定纯函数；编辑器内不出现「启动 session」入口（断言于 AC-402-04）。
- config 内容的业务校验前置（无 dry-run 端点可前置；prepare 是唯一内容校验面且归 #64）。
- 通用 JSON Schema 校验器实现（为过门禁造轮子，双重不做：引擎类 + 实时校验类）。

## 3. 术语

| 术语 | 定义 |
|---|---|
| 节点表单（Node Inspector） | 画布选中节点的属性侧栏表单；draft 的组合面（不持服务端事实，SPEC-400 §4.3） |
| 字段清单描述符表 | 手写冻结表：`GeneratorConfigDTO` 每字段的类型/默认值/控件 kind/约束注记一行（§5.1）；组件声明式消费，禁在组件内写字段字面量 |
| `config_schema` 指针 | `NodeTypeSpec.config_schema`（SPEC-401 §5.1）：`"GeneratorConfigDTO"` 或 `null`；null = config 恒 opaque `{}`，表单呈现「无配置字段」（REQ-UI-402-001 的「不自造字段」机制） |
| 控件 kind 闭集 | §5.2 六种：number / text / select / locked-checkbox / group / rows；渲染器 switch 直配，无第四方控件体系 |
| 完备性标记（G1） | 编辑态陈述：无默认值的描述符字段「已填/未填」；≠ 业务有效性结论（§7.3） |
| 口径 A | 400 `REQUEST_BODY_INVALID` 的 `details.errors[].loc` 链（path-addressed，SPEC-500 §6 / `src/api/errors.py` RequestValidationError 覆盖）；保存路径触发，字段定位第一口径 |
| 口径 B | run prepare 422 `SIM_TS_CONFIG_INVALID`/`SIM_TS_PLAN_INVALID` 的**自由文本通道**（PLAN = `details.errors[]` 串；CONFIG = 信封 `message`，违规字段在冻结槽位 `（field '<name>';` 内为裸字段串；`tests/integration/api/test_rest_runs.py` + `src/ts/generator/validator.py` 实测形状）；字段定位第二口径，尽力匹配不伪造 |
| 三元联合门 | G1 完备性（编辑态）∧ G2 结构校验报告（服务端 validate 面板状态）∧ G3 字段错误（口径 A/B 当前展示者）；全部为纯函数输入（§7.6） |
| FieldError | 字段级错误条目 `{nodeId, fieldPath\|null, message}`；fieldPath=null = 节点级；渲染于表单对应字段下方或节点级横幅 |
| 应用到草稿 | 表单显式提交动作：类型化投影按 wire 形状序列化为 plain object 写入 `node.config` + dirty（additive action `configApplied`） |

## 4. 架构

### 4.1 组件分解（`src/features/topologies/inspector/`，#63 OWN 子目录；#62 既有文件的 additive 接线见 §4.2）

```text
src/features/topologies/
  TopologyEditorPage.tsx    #62 面：additive 接线（选中派生 + <NodeInspector> 宿主 + 门合流进保存入口禁用）——申报
  editorState.ts            #62 面：additive action `configApplied` 一例（config 写入 node.data.node.config + dirty）——申报
  inspector/                #63 OWN（新增）
    fieldInventory.ts       描述符表 + 完备性判定 + 字段路径工具（纯函数，零 React）
    locChain.ts             口径 A：ApiError.details.errors[] → FieldError[]（纯函数）
    schemaPathMatch.ts      口径 B：自由文本串 → 字段命中（复用 #62 mapPlanErrors 做节点归属，纯函数）
    inspectorGate.ts        三元联合门（纯函数，输入为 EditorState 形状投影）
    NodeInspector.tsx       表单组件（声明式渲染描述符 + FieldError 就地 + 应用按钮）
    inspector.css           表单样式（dvb-inspector-* 命名域，新增文件）
    *.test.ts(x)            上述逐一对应测试（§11）
```

表单不引入新路由（`routes.tsx` 禁动，#61 面）；不新增 npm 依赖；不新建共享 barrel（`src/api` 零改动——本票不新增端点，消费既有 `saveTopologyRevision` 抛出的 `ApiError`）。

### 4.2 与 #62 面的接线契约（additive，逐项申报）

| #62 文件 | additive 改动 | 规模 |
|---|---|---|
| `editorState.ts` | action union 增员 `{type:"configApplied"; nodeId; config: Record<string,unknown>}` + reducer 一例（定点更新 `node.data.node.config`，`dirty: true`） | ~6 行 |
| `TopologyEditorPage.tsx` | import `NodeInspector`/`inspectorGate`/`mapLocChain`；选中派生（`state.nodes.find(n => n.selected)`）；400 保存失败的 loc 链回填 state；保存按钮 `disabled` 表达式追加 `|| gate.reasons.length > 0`；画布右栏宿主 `<NodeInspector>` | ~20 行 |

选择语义复用 React Flow 既有 `select` change（已经 `nodesChanged` 进 reducer，零新增）；`configApplied` 是本票对 editorState 的唯一 additive action（申报项，无删改既有 case）。

### 4.3 事实源纪律

- 表单是**草稿的组合面**：显示 = 选中节点 `node.config` 的类型化投影；编辑 = 本地表单 state；只有「应用到草稿」经 `configApplied` 落入画布草稿（与 SPEC-400 §4.3 规则 4 + ADR-0009 决定 4 同源：React Flow 内部 store 与表单本地 state 均不作服务端事实源）。
- 应用后表单与 `node.config` 分歧时呈现「有未应用修改」提示位（不加锁、不自动应用）。
- 服务端事实（拓扑/校验报告）只经查询缓存与 editorState（#62 既立），表单零直连查询。

## 5. 数据模型

### 5.1 字段清单描述符表（`GeneratorConfigDTO` 全字段，REQ-UI-402-001 验收锚）

数据源：① 生成类型 `frontend/src/api/schema.gen.ts` 的 `GeneratorConfigDTO`/`ProgramDTO`/`ElementaryStreamDTO`（wire 权威，键集与 @default 逐字）；② SPEC-108 §4 JSON↔DTO 映射表（语义 + 约束列）；③ §5 配置校验约束（**仅作注记呈现**）。行内「初值」= 表单新建时的填充值：有 wire 默认者填默认值，无默认者留空（完备性 G1 的「未填」对象）。

**顶层 `GeneratorConfigDTO`（12 字段）**：

| # | 字段（wire 逐字） | 类型 | wire 默认 | SPEC-108 权威约束（仅注记） | 控件 kind |
|---|---|---|---|---|---|
| 1 | `schema_version` | number(int) | —（必填） | 受支持版本（后端 §5 校验受支持集；生成 DTO `ge=1`；现行值 1 = `examples/ts-generator-minimal.json`） | number（初值 1） |
| 2 | `profile` | string | `"analysis_only"` | MVP 仅 `analysis_only`（§4 映射表） | select（单选项 `analysis_only`，契约冻结值） |
| 3 | `deterministic` | boolean | `true` | 必须为 true（§4 映射表） | locked-checkbox（锁定 true） |
| 4 | `seed` | number(int) | —（必填） | 进入生成指纹；不读墙钟字段（§5） | number |
| 5 | `initial_media_clock_27mhz` | number(int) | —（必填） | 非负（§4 映射表） | number |
| 6 | `target_bitrate_bps` | number(int) | —（必填） | > 0；冻结范围 1~100 Mbps（ADR-0008 第 2 条） | number |
| 7 | `output_packet_count` | number(int) | —（必填） | > 0（§5） | number |
| 8 | `program` | ProgramDTO | —（必填） | 见嵌套表 | group |
| 9 | `pat_period_ms` | number(int) | `101` | > 0；#72 错相裁决默认 | number（初值 101） |
| 10 | `pmt_period_ms` | number(int) | `103` | > 0；#72 错相裁决默认 | number（初值 103） |
| 11 | `pcr_interval_ms` | number(int) | `40` | > 0 | number（初值 40） |
| 12 | `pcr_insertion_policy` | enum string | `"payload_packet_first"` | 枚举 `payload_packet_first` / `adaptation_only_fallback`（§5） | select（两选项，初值默认项） |

**嵌套 `ProgramDTO`（`program`，7 字段）**：

| # | 字段 | 类型 | wire 默认 | 约束注记 | 控件 kind |
|---|---|---|---|---|---|
| 8.1 | `transport_stream_id` | number(int) | —（必填） | 按字段位宽校验（§5） | number |
| 8.2 | `program_number` | number(int) | —（必填） | ≠ 0（§5） | number |
| 8.3 | `pmt_pid` | number(int) | —（必填） | PID 不得冲突/保留（§5） | number |
| 8.4 | `pcr_pid` | number(int) | —（必填） | 可复用 ES PID（§5） | number |
| 8.5 | `version_number` | number(int) | —（必填） | 位宽校验（§5） | number |
| 8.6 | `program_descriptors` | string(hex) | `""` | bytes→hex 编码（SPEC-500 §5） | text（初值 `""`） |
| 8.7 | `streams` | ElementaryStreamDTO[] | —（必填；可为空数组，§5 无最少流数约束——不发明） | ES PID 程序内唯一；ES 码率 + 表/PCR overhead 须装入 target（§5） | rows |

**行 `ElementaryStreamDTO`（每行 6 字段）**：

| # | 字段 | 类型 | wire 默认 | 约束注记 | 控件 kind |
|---|---|---|---|---|---|
| R1 | `pid` | number(int) | —（必填） | 程序内唯一（§5） | number |
| R2 | `stream_type` | number(int) | —（必填） | 位宽校验（§5） | number |
| R3 | `stream_id` | number(int) | —（必填） | 位宽校验（§5） | number |
| R4 | `bitrate_bps` | number(int) | —（必填） | > 0；装入 target 码率（§5） | number |
| R5 | `payload_profile` | string | `"synthetic_test_data"` | （无客户端枚举声明——§5 未枚举值集，不发明） | text（初值默认） |
| R6 | `payload_seed_offset` | number(int) | `0` | — | number（初值 0） |

一致性护栏：描述符表键集/默认值与生成类型**逐键相等**有测试（TV-402-05，AC-402-01 锚）——生成类型漂移即测试失败，防表↔类型分叉。

### 5.2 控件 kind 闭集（渲染器直配，防引擎化）

| kind | 渲染 | 输入语义 |
|---|---|---|
| `number` | `<input type="number">` | 本地字符串暂存；应用时转 number（空串 = 未填） |
| `text` | `<input type="text">` | 原样字符串（hex 串不做客户端格式判定） |
| `select` | `<select>`（选项 = 描述符冻结枚举） | 选项集 = SPEC-108 权威枚举/契约单值，非猜测 |
| `locked-checkbox` | 禁用勾选 + 注记 | 契约单值字段（`deterministic`=true、`profile` 单选项同理走 select 单选项）——控件只提供契约合法值，属控件形态选择，非客户端校验执行 |
| `group` | 字段子分组（`program`） | 嵌套一层，固定深度（描述符静态结构，非递归树） |
| `rows` | 行列表（`streams`）：增行/删行 + 行内六字段 | 行数据本地暂存；应用时整表序列化 |

无第五种形态、无控件注册表机制、无 schema 驱动推导——三项不做清单的结构性保证。

### 5.3 序列化形状（应用 → 草稿 → wire）

「应用到草稿」将类型化投影序列化为 plain object：键名 snake_case **逐字**（断 wire 字段名纪律）、数字为 number、`streams` 为数组（可为空）、无 undefined 字段（有默认者带默认值写入）。`node.config` 全程 opaque 载荷（`TopologyNodeDTO.config?: { [key: string]: unknown }`），`toWire` 原样带回（#62 不可变 revision 语义）。载入存量 revision：`node_type=ts_generator` 且 config 为 object → 投影回表单（缺失键留空 = G1 未填；非 object → 节点级错误态呈现，保持 opaque 不清洗）。

## 6. 公开接口

### 6.1 上游消费面（#62 共享面，只读）

- `nodeTypeSpec(nodeType).config_schema` —— 字段清单唯一指针。
- `mapPlanErrors(errors, nodeIds)` —— 口径 B 节点归属复用（词边界规则不重写）。
- `editorReducer`/`EditorState`/`ValidationView` —— 草稿与校验报告状态（additive action 见 §4.2）。
- `ViolationPanel` —— 非 FieldError 条目的既有同口径面板（口径 B 未命中字段者留此）。
- `saveTopologyRevision`/`createTopology` 抛出的 `ApiError.details` —— 口径 A 数据源。

### 6.2 对下游导出面（SPEC-403/406 与后续票，签名级冻结）

```ts
// fieldInventory.ts
interface FieldDescriptor { path: string; kind: ControlKind; wireDefault?: unknown; required: boolean;
                            label: string; hint?: string; options?: string[]; initial?: unknown;
                            children?: FieldDescriptor[]; rowFields?: FieldDescriptor[] }
const GENERATOR_FIELD_INVENTORY: FieldDescriptor[];          // §5.1 表的唯一代码化身
function isConfigComplete(nodeType: string, config: unknown): boolean;   // G1 纯判定
// locChain.ts
interface FieldError { nodeId: string; fieldPath: string | null; message: string }  // fieldPath=null → 节点级
function mapLocChain(details: unknown, draftNodeIds: string[]): FieldError[];
// schemaPathMatch.ts
function matchSchemaPathErrors(errors: string[], draftNodeIds: string[]): { fieldHits: FieldError[]; rest: string[] };
// inspectorGate.ts
interface GateInput { nodes: { node_id: string; node_type: string; config: unknown }[];
                      validation: { status: "idle" | "done"; entries: unknown[]; graphEntries: unknown[]; planErrors: unknown[] };
                      fieldErrors: FieldError[] }
interface GateResult { reasons: { kind: "config_incomplete" | "structural_violations" | "field_errors";
                                  nodeIds?: string[] }[] }
function computeInspectorGate(input: GateInput): GateResult;   // reasons 空 = 门通过
// NodeInspector.tsx
function NodeInspector(props: { node: TopologyFlowNode | null; fieldErrors: FieldError[];
                                onApply: (nodeId: string, config: Record<string, unknown>) => void }): JSX.Element;
```

- **启动 session 入口禁用**的实现归属：编辑器内不存在该入口（AC-402-04 断言）；`computeInspectorGate` 为纯函数导出，SPEC-403 monitor / SPEC-406 lab 的 session 入口启用态可 additive 消费（与其自身 SPEC-200 §5 穷举表禁用矩阵**取交集**，拓扑维度信号）。本票不改 `features/monitor/**`（NOT-TOUCH）。
- #64 monitor 的 run 触发面现用 golden JSON 文本缺省（`OverviewCard.DEFAULT_RUN_CONFIG_JSON`，#64 既落）——与本表单并存（NOT-TOUCH 不合并）；后续如需结构化化，由 #64 所在票 additive 采纳本导出面，非本票义务。

## 7. 处理算法

### 7.1 选中 → 表单（REQ-UI-402-001）

1. 画布选中（React Flow `select` change → `nodesChanged` 既有通路）→ 页面派生 `selected = state.nodes.find(n => n.selected) ?? null`。
2. `nodeTypeSpec(selected.data.node.node_type)`：`config_schema === "GeneratorConfigDTO"` → 渲染 §5.1 描述符表；`null` → 「该类型无配置字段（config 恒 `{}`）」诚实态（零输入控件）；未注册类型（存量 revision 携带外语汇）→ 同诚实态 + 「未注册类型」注记——不猜测字段。
3. 无选中 → 空态「未选中节点」。

### 7.2 编辑 → 草稿（REQ-UI-402-003 前半）

1. 表单本地 state 承载编辑（§4.3）；「应用到草稿」→ 序列化（§5.3）→ `dispatch({type:"configApplied", nodeId, config})` → `node.config` 更新 + `dirty`。
2. 应用不触发任何校验（无实时校验义务）；保存路径的门判定是唯一的通过/禁用机制（§7.6）。
3. 未应用分歧提示位（§4.3）；切换选中节点丢弃本地未应用编辑（提示位明示，不做跨节点暂存）。

### 7.3 完备性判定（G1，编辑态门——§5 禁令边界论证）

`isConfigComplete(nodeType, config)`：`config_schema = null` → 恒 true；`GeneratorConfigDTO` → 描述符中 `required`（wire 无默认）字段全部「已填」（number = 已输入有限数值；text = 非空；`program.group` 递归其 required 子字段；`streams` = 键存在即可，**可为空数组**——SPEC-108 §5 无最少流数约束，发明 minLength 即自造约束）。**只判存在性，不判值域、不判交叉关系**——那些是 §5 业务校验，唯一权威在后端。

禁令边界论证（报批要求）：CONTEXT.md §5 禁令禁的是「用 UI 状态判定**通关**/把 UI 变绿当证据」——即以界面状态替代 `POST .../verify` 三态判定这类**业务结论推断**。G1 输出的命题是「操作者尚未填完必填字段」（编辑事实陈述），不是「配置合法」（业务结论）；呈现措辞钉死为「配置待填」，禁用「配置有效/校验通过」字样。G1 不产生任何证据、不进入任何判定链，只是保存入口的编辑完备性前提——与 #62 面板「尚未校验」空态同类的诚实状态呈现。判据：G1=false 仅在字段缺输入时成立，且永远可被用户通过填字段消除，无需 UI 之外信息。

### 7.4 口径 A：400 loc 链回填（REQ-UI-402-002 第一口径，保存路径触发）

1. 触发：`createTopology`/`saveTopologyRevision` 抛 `ApiError{status:400, errorCode:"REQUEST_BODY_INVALID"}` → `details.errors[] = [{loc, msg, type}, ...]`（SPEC-500 §6 path-addressed；`src/api/errors.py` RequestValidationError 覆盖）。
2. 解析（`mapLocChain` 纯函数）：loc 内定位 `"nodes"` 段 → 其后必须为数字索引 `i` → `nodeId = draftNodeIds[i]`（**顺序耦合声明**：`toWire` 按草稿数组原序输出节点，索引 i ↔ `state.nodes[i]`，测试钉住；防御：越界/非数字索引 → 全图级条目不落表单）。
3. 字段落位：nodes[i] 之后的段（如 `["config"]`）→ 表单根错误横幅；更深段与 §5.1 描述符 path 声明式匹配（如 `program`）→ 对应 group 下方 FieldError；未匹配段 → 节点级（fieldPath=null）。**精度上限诚实声明**：wire 对 `config` 的类型是 object（不深入内容），故 400 loc 链最深落至「节点的 config 占位」——config **内容**级字段错误在保存路径不可达，只能来自口径 B（§7.5）。loc 不含 `"nodes"`（如顶层 body 形状错）→ 全图级条目进 ViolationPanel，不落表单。
4. `msg` 逐字展示（snake_case wire 纪律）；成功保存清空口径 A 回填。

### 7.5 口径 B：prepare 422 自由文本尽力落字段（REQ-UI-402-002 第二口径）

1. 形状（**实现期实测订正**，`src/bootstrap/backends.py` L590-597 + `src/simulation/ts_runtime.py` L500-509 + `src/ts/generator/validator.py`）：`ApiError{status:422, errorCode ∈ {SIM_TS_CONFIG_INVALID, SIM_TS_PLAN_INVALID}}` 均为自由文本通道——`SIM_TS_PLAN_INVALID` 携带 `details.errors[]`（逐元素自由文本串，含违规参数键/target node_id 词样，`tests/integration/api/test_rest_runs.py` 实测）；`SIM_TS_CONFIG_INVALID` **无 `details`**，违规字段名嵌在信封 `message` 的冻结槽位 `（field '<name>'; ...）` 中，且 `<name>` 为校验器的**裸字段串**（如 `target_bitrate_bps`、`pid`、`stream_type`——非完整点路径）。调用方据此组装匹配器入参：PLAN 喂 `details.errors[]`，CONFIG 喂 `[error.message]`。
2. 节点归属：**复用 #62 `mapPlanErrors(errors, draftNodeIds)`**（词边界规则原样，禁另写）；另加**单候选规则**（证据门控）：串内未提及任何候选 node_id 且候选集恰为一个时，字段证据（冻结槽位解析命中）成立方可归属该唯一候选（调用方声明的 config 所属语境，非文本伪造）；候选集多个且未提及 → 留 rest（歧义不裁决）。无字段证据的串永不钉到节点。
3. 字段匹配（`matchSchemaPathErrors` 纯函数）：主解析 = 冻结槽位 `(field '<name>';` → 裸名按描述符路径**末段唯一解析**（全部发射名跨层级唯一；`（pid 256）` 类正文括注不匹配槽位）；防御性次解析 = 描述符 path 词边界子串匹配（具索引 `program.streams[0].pid` 归一化为 `[]` 占位，最长匹配）。命中 → FieldError 就地于字段下方（message 原文逐字）；未命中字段但有节点归属 → 节点级；两者皆无 → `rest` 串留既有 ViolationPanel（source `run_prepare`，#62 同口径）。**不解析语义、不伪造实体映射**（#62 §7.5 同源纪律）。
4. 触发面归属：run prepare 提交在 monitor 区（SPEC-403/406，#64 既落，NOT-TOUCH）。本票交付匹配器 + FieldError 呈现组件，行为以真实 wire 形状 fixture 的组件测试钉住（TV-402-03）；触发票 additive 接线（模式与 SPEC-401 §7.5 完全同构）。

### 7.6 三元联合门（REQ-UI-402-003 后半——报批核心项）

`computeInspectorGate(input): GateResult`，reasons 非空 = 门不通过：

| 门 | 判定 | 数据源 | 性质 |
|---|---|---|---|
| G1 完备性 | 任一 `ts_generator` 节点 `!isConfigComplete(...)` | 草稿 | 编辑态陈述（§7.3）；`config_schema=null` 类型恒过 |
| G2 结构校验报告 | `validation.status === "done"` 且 `entries + graphEntries + planErrors` 非空 | #62 editorState（validate 面板既有状态） | 服务端报告（存储图结构违规 + prepare 422 同面板条目） |
| G3 字段错误 | `fieldErrors` 非空（口径 A 回填 + 口径 B fieldHits 当前展示者） | §7.4/§7.5 输出 | 服务端错误的字段级投影 |

- **保存入口**：`disabled={!state.dirty || saving || gate.reasons.length > 0}`（对 #62 既有按钮 additive 一项）。
- **未保存新草稿的诚实语义**：`validation.status=idle` 时 G2 不阻（尚无服务端报告可依据；首存是获得报告的唯一路径——SPEC-401 §7.4 第 3/4 条：validate 是保存流的固定第三步）。门在「已验证后有违规」「字段错误未清」「配置未填完」三态下禁保存。
- **启动 session 入口**：编辑器内不存在（§6.2）；门判定纯函数导出，session 入口所有票 additive 消费并与其 SPEC-200 §5 禁用矩阵取交集。
- 门**不产生**「配置合法」结论：reasons 空 = 「当前无已知阻断信号」，服务端在 session VALIDATING / run prepare 仍是权威拒绝者（双层纪律，SPEC-401 §7.4 第 4 条同构）。

## 8. 错误处理

- 口径 A/B 之外的 REST 错误分支全部沿 SPEC-401 §8 既有家族分支（404/`HTTP_501`/503），表单零新增错误面。
- `details` 形状防御：loc 链缺失/畸形（非数组、缺 loc 键）→ 整体降级为面板级原始信封展示（errorCode/message），不抛渲染错——错误呈现路径自身不得成为新错误源。
- 表单序列化防御：config 非 object（存量脏数据）→ 节点级错误态 + 保持 opaque（§5.3）；数字输入非法暂存值（如空串）应用时按未填处理（G1 拦截），不静默转 0。
- 「应用到草稿」永不抛错（纯本地序列化）；保存失败的错误面 = 既有页面 `role="alert"` 横幅 + 口径 A 回填（§7.4）。

## 9. 资源约束

- 零新 npm 依赖；零新路由；零 `src/api` 改动；零 Python 侧改动。
- 描述符表为静态常量（模块级，可 tree-shake）；匹配/门/映射全为纯函数（无 effect、无定时器）。
- 表单重渲染范围 = 选中节点变更或 FieldError 变更；不订阅画布全局状态。

## 10. 依赖

| 依赖 | 性质 |
|---|---|
| SPEC-401（0.5.0 APPROVED）：注册表/graphMapping/violations/ViolationPanel/editorState/topology 端点 | 已落地（#62，bd0bd59） |
| SPEC-500 §4.1/§6 + 生成类型 `schema.gen.ts`（DTO 权威） | 已落地（#61/#80） |
| SPEC-108 §4/§5（配置模型/约束语义权威）+ ADR-0008（码率包络） | APPROVED 既有 |
| #64 monitor 面（prepare 422 触发面、session 入口所有者） | 已落地（#64）；本票只读、不接线其内部 |
| 后端全链路 #58（E2E 真浏览器腿） | 验收时点前提，非开工阻塞（SPEC-400 §1.1 同注） |

## 11. 测试向量

- **TV-402-01**：`examples/ts-generator-minimal.json` 逐字 fixture → 表单填充 → 应用 → `node.config` 与 fixture 逐键相等（round-trip）。
- **TV-402-02**（口径 A）：`details.errors` fixture `[{loc:["body","nodes",1,"config"], msg:"…", type:"…"}]` + 三节点草稿 → FieldError{nodeId=nodes[1], fieldPath="config"}（根横幅）；loc 越界索引 → 全图级降级；缺 loc 键 → 信封级降级。
- **TV-402-03**（口径 B）：prepare 422 真实形状 fixture（CONFIG = 信封 message 含冻结槽位 `(field 'pid';`/`(field 'target_bitrate_bps';` 裸字段串，含 `(pid 256)` 类括注诱饵；PLAN = `details.errors[]` 串含 `bogus_key`/`mux-0` 节点词）→ 裸名末段解析落行级/字段级 FieldError + 节点归属（mapPlanErrors 复用断言 + 单候选证据门控规则）+ 无命中串入 rest。
- **TV-402-04**（G1 真值表）：`{}` → 未填；全 required 填 + 默认补齐 → 完备；`streams: []` → 完备（无 minLength 发明）；非 generator 类型 → 恒完备。
- **TV-402-05**（AC-402-01 锚）：描述符表键集/默认值 ↔ 生成类型 `GeneratorConfigDTO`（12 键）/`ProgramDTO`（7 键）/`ElementaryStreamDTO`（6 键）逐键相等断言。
- **TV-402-06**（门真值表）：G1/G2/G3 组合 2³ 用例 → reasons 逐项相等；`configApplied` 后 dirty=true 且 config 定点更新（editorState additive case 测试）。
- **TV-402-07**（E2E，`e2e/node-inspector.spec.ts` 新文件）：拖 generator → 选中 → 表单呈现字段清单 → 留空必填时保存入口禁用（可见禁用态断言）→ 填最小配置 → 应用 → 保存 → 重载回显 stored config；拖 `ts_monitor` → 「无配置字段」诚实态。既有 `closed-loop.spec.ts`/`topology.spec.ts` 零改动。

## 12. 验收标准

- **AC-402-01**（REQ-UI-402-001）：每类 MVP 节点字段清单与 Config Schema 一致——TV-402-05 键集相等测试 + `config_schema=null` 三类型诚实态渲染断言 + 组件零字段字面量（组件仅消费描述符表，评审检查项）。
- **AC-402-02**（REQ-UI-402-002 口径 A）：400 loc 链字段级落位——TV-402-02 全分支（索引解析/根横幅/未匹配节点级/全图降级）。
- **AC-402-03**（REQ-UI-402-002 口径 B）：prepare 422 尽力落字段——TV-402-03（冻结槽位裸名解析行级/字段级命中 + 词边界节点归属与单候选证据门控 + rest 面板降级），复用 #62 归属规则有断言。
- **AC-402-04**（REQ-UI-402-003）：校验不通过时保存入口禁用——TV-402-06 门真值表 + 保存按钮禁用联动组件测试 + TV-402-07 E2E 可见禁用态；编辑器内无 session 入口断言 + `computeInspectorGate` 导出契约测试。
- **AC-402-05**（REQ-UI-402-003）：draft 编辑链路——应用→草稿逐字段相等 + dirty（TV-402-06 后半）+ E2E 保存/重载回显（TV-402-07，后端全链路前提注 §10）。
- **AC-402-06**（不做清单）：无 schema 解析器/运行时内省/引擎式推导、无字段级实时校验调用与本地约束强制、无自定义布局机制——测试断言（描述符表为唯一字段源 + 约束仅注记文本）+ 评审检查项。

## 13. 非目标

- 不做（票面三项）：通用 JSON Schema 动态表单引擎（rjsf 类）、字段级实时校验、自定义表单布局（§2.2 逐项结构性论证）。
- 不做：config 内容业务校验前置（无 dry-run 面；prepare 唯一且归 #64）、session/run 控制入口（SPEC-403/406）、monitor golden JSON 触发面的结构化改造（#64 既落，后续票 additive 采纳）、撤销/重做与跨节点表单暂存（SPEC-401 不做清单同源）、config 内容的 hex/PID 客户端格式判定（注记呈现 + 后端权威）。
- 不冻结：表单 CSS 细节（dvb-inspector-* 命名域内自由）；FieldError 的 UI 文案排布（字段下方/横幅的视觉细节）。

## 14. 兼容性与交付要求

- 对 #62 面全部为 additive（§4.2 两处申报，逐行评审；既有 12 个测试文件零改动且必须继续绿）。
- 对 #64 monitor 面、`src/api/**`、`routes.tsx`、后端：零改动零接线。
- 交付物：`inspector/` 子目录（5 源文件 + 测试 + css）、additive 接线两处、SPEC-402 本文本、INDEX 行链接更新、E2E 新文件；`python -I tools/check_specs.py` 0 failed。
- 下游承诺：`computeInspectorGate`/`matchSchemaPathErrors`/`GENERATOR_FIELD_INVENTORY` 签名级冻结（§6.2）——#67 场景initial_topology 的 config 预填可复用描述符表初值；#64 后续结构化化可复用而不需本票返工。
