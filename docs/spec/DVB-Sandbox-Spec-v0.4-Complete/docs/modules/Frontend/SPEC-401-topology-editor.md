---
spec_id: SPEC-401
title: Topology Editor
version: 0.5.2
status: APPROVED
phase: MVP
owner: Frontend
priority: P0
depends_on: [SPEC-003, SPEC-500]
requirements: [REQ-UI-401-001, REQ-UI-401-002, REQ-UI-401-003, REQ-UI-401-004, REQ-UI-401-005, REQ-UI-401-006, REQ-UI-401-007]
---

# SPEC-401 — 拓扑画布（Topology Editor）

## 1. 目标

定义 MVP 拓扑画布的**实体权威冻结点**：节点面板（声明式类型清单）、拖放建节点、端口级连线（ADR-0005 决策 5 四元组）、默认端口自动生成、MPEG_TS 单平面纪律、校验错误就地展示（SPEC-202 path-addressed + run prepare 422 同口径）与保存 = PUT 新 revision（不可变追加）。

依据：MVP 切集预批准（ticket #18）、[ADR-0009](../../../../../adr/0009-frontend-canvas-react-flow.md)（画布选型 @xyflow/react ^12，六条决定，本规格的 normative 依据）、ADR-0005 决策 5（端口级拓扑 + 默认端口自动生成 + MPEG_TS 单平面）、SPEC-003 §2.1（拓扑领域模型）/§6（NodeType 注册表待明确项 → 本规格落定为前端共享工件，见 §5.1）、SPEC-202 §4/§5（图契约与 path-addressed 验证规则）、SPEC-500 §4.1（topology 五路由）/§6（错误信封）。

## 2. 范围

### 2.1 In Scope

- MVP NodeType 注册表工件（前端共享工件，类型集/端口模板/默认端口/generator Config Schema 引用，见 §5.1——类型集经实现票草案报批后冻结）。
- 节点面板：声明式渲染注册表类型清单，前端组件不自造节点类型。
- 拖放建节点（palette DnD + `screenToFlowPosition`）与默认端口自动生成（端口模板渲染为可见 Handle）。
- 端口级连线：Handle↔Handle 拖拽（`ConnectionMode.Strict`），`Edge.sourceHandle/targetHandle` ↔ `from_port/to_port` 四元组映射。
- 连线 UX 预检：`isValidConnection` 方向/自环/maxConnections 三项（ADR-0009 决定 4）+ MPEG_TS 单平面预检（REQ-UI-401-005）；权威校验永远在后端。
- 校验错误就地展示：`POST /topologies/{id}/validate` 的 `TopologyViolationDTO{code,path,message}` 按 path 定位到节点/端口/连线高亮 + 校验面板逐条罗列；run prepare 422（`SIM_TS_PLAN_INVALID`/`SIM_TS_CONFIG_INVALID`）错误串同口径进同一面板。
- 保存流：POST 建图（server uuid4）/ PUT 追加不可变新 revision → 随后对存储图跑 validate → 违规就地展示。
- 画布 E2E（Playwright）：拖放 → 连线 → 保存 → 新 revision 浏览器级全链路 + 未启用平面双层拒绝的就地呈现。
- topology 面前端 api 领域函数（`src/api/endpoints/topologies.ts`，经 barrel 导出）。

### 2.2 Out of Scope

- 节点属性/配置表单（SPEC-402；本规格只把 config 作为 opaque 载荷保存，字段级展示与编辑归 #63）。
- 撤销/重做、复制粘贴、多 tab 并行编辑、平面切换 UI、拓扑 diff（#18 不做清单，五项全部不做）。
- 画布位置持久化（ADR-0009 决定 5：契约无位置字段；后续增强走 additive 契约变更票）。
- 会话/运行控制 UI（session 生命周期与 run 提交归 SPEC-403/406 各票；本规格只提供 prepare 422 错误的**展示契约**，见 §7.5）。
- bidirectional 端口的把手双渲染（§5.1 注册表 MVP 类型集不含 bidirectional 端口，该 ADR-0009 决定 3 悬项因清单为空而 MVP 不触发；未来类型入表时随注册表变更票裁定）。
- 自动布局第三方库（dagre/elkjs）——手写拓扑序分列起步（ADR-0009 决定 5）。

## 3. 术语

| 术语 | 定义 |
|---|---|
| 草稿（draft） | 画布编辑期的应用方本地 state（nodes/edges + dirty 标记）；不是事实源，保存（PUT 新 revision）才成为服务端事实（ADR-0009 决定 4） |
| 受控模式 | React Flow 的 nodes/edges 作 props 由应用方持有，React Flow 只报 change intents（选择性应用；内部 zustand store 不作事实源）（ADR-0009 决定 4） |
| NodeType 注册表 | 前端共享工件 `nodeTypes.ts`：MVP 节点类型 + 端口模板 + 默认端口 + Config Schema 引用的唯一声明点；组件声明式消费，禁自造类型（REQ-UI-401-001） |
| 端口模板 | 注册表内每类型的端口清单（port_id/direction/plane/max_connections）；拖放建节点时按模板自动生成默认端口（REQ-UI-401-004） |
| Handle id 映射 | React Flow `Handle id` = `port_id` 原样（MVP 无 bidirectional 端口，每端口恰一 Handle）；`Edge.sourceHandle/targetHandle` = `from_port/to_port`，与 `node_id` 合成 SPEC-202 §4 四元组 |
| path-addressed | SPEC-202 §5 违规定位形状 `TopologyViolationDTO{code,path,message}`；path 语法见 §7.4 映射表 |
| 不可变追加 | PUT /topologies/{id} 永远新增 revision 行（server 端 revision = latest+1），旧行永久可取（SPEC-500 §4.1；客户端永不自选 revision） |
| 单平面纪律 | MVP 仅启用 `MPEG_TS`（SPEC-003 §2.1 `MVP_ENABLED_PLANES`）；未启用平面的连线被前端预检 + 后端 validate 双层拒绝 |
| 同口径展示 | run prepare 422 的 `details.errors[]` 错误串与 topology validate 违规共用同一校验面板与就地高亮子系统（呈现口径一致；解析规则见 §7.5） |

## 4. 架构

### 4.1 ADR-0009 六决定落点（normative）

1. **画布库 = `@xyflow/react` ^12**（禁旧包 `reactflow` v11；禁 13.0.0-next）。端口级连线 = `Handle id` + `Edge.sourceHandle/targetHandle`；拖时校验挂 `<ReactFlow>` 层 `isValidConnection`；拖放建节点 = palette DnD（pointer events + `screenToFlowPosition`）。
2. **版本与 attribution**：钉 `^12`，lockfile 锁定；保留「React Flow」attribution 角标（MIT，不购买 Pro）。
3. **连线交互 = 把手↔把手 only**：`ConnectionMode.Strict`（保证 source→target 承载 SPEC-202 方向规则）；节点体拖放自动选端口（`onConnectEnd` + `FinalConnectionState`）为交互增强，MVP 不做。
4. **集成边界 = 受控纪律 + 最小客户端预校验**：nodes/edges 为应用方 state（§3 草稿），React Flow 只报 change intents；内部 store 不作事实源。客户端预检 = 方向 + 自环 + 基数（maxConnections）三项 UX 预检 + REQ-UI-401-005 单平面预检；不在前端复制完整校验器，权威校验永远在后端。
5. **画布位置不持久化**：载入时确定性自动布局（手写拓扑序分列，见 §7.3）；手动摆放仅草稿内有效，保存不带走位置（wire 无位置字段，不加）。
6. **决策承载 = ADR-0009** 本体；本规格为其实体文本。

### 4.2 组件分解（`src/features/topologies/`，#62/#63 共用目录、各票 OWN 自己子面）

```text
src/features/topologies/
  Region.tsx              路由区入口（/topologies，#61 占位的实体化）
  TopologyEditorPage.tsx  画布页：拓扑选择/新建 → 载入 → 草稿 → 保存/校验
  nodeTypes.ts            MVP NodeType 注册表（§5.1；#63 同样消费）
  NodePalette.tsx         节点面板（声明式渲染注册表清单 + HTML5 DnD 源）
  TopologyNode.tsx        自定义节点（按端口模板渲染 Handle：input 左 / output 右）
  graphMapping.ts         wire DTO ↔ React Flow nodes/edges 纯映射 + isValidConnection + 确定性布局
  violations.ts           path 语法解析 + 违规 → 画布实体映射 + prepare 422 同口径条目
  ViolationPanel.tsx      校验面板（逐条 code/path/message 原样 + 点击定位实体）
```

路由注册零改动：`/topologies` 条目与惰性 import 已由 #61 在 `src/app/routes.tsx` 落位（additive-only 共享面，本规格无壳文件变更）。

### 4.3 事实源纪律

- 服务端拓扑事实只经查询缓存（`qk.topologies` / `qk.topology(topologyId, revision)` 词表，SPEC-400 §5）；保存成功后失效对应键重取。
- 画布 nodes/edges 是**编辑期 UI state**（草稿）；React Flow 内部 store、组件 state 均不得承载服务端事实（SPEC-400 §4.3 规则 4 + ADR-0009 决定 4）。
- 保存 = PUT 新 revision；草稿 dirty 标记在保存成功后清除并回填 server revision。

## 5. 数据模型

### 5.1 MVP NodeType 注册表（工件规范 + 类型集草案，报批后冻结）

工件形态：TS 模块 `src/features/topologies/nodeTypes.ts`（单一声明点；不采 JSON——类型化、可 tree-shake、无 loader 成本）。形状：

```ts
export interface NodeTypePortSpec {
  port_id: string;        // 注册表内该类型唯一；即 Handle id 与 wire port_id
  direction: "input" | "output" | "bidirectional";
  plane: "RF" | "SEC_CONTROL" | "MPEG_TS" | "T2MI" | "IP";
  max_connections: number; // 注册表恒钉具体数值（≥1），使基数预检全判定
}

export interface NodeTypeSpec {
  node_type: string;       // 权威 wire 串（TopologyNodeDTO.node_type 唯一合法取值源）
  id_prefix: string;       // 拖放时 node_id 语义 slug 前缀（§7.1）
  label: string;           // 面板显示名
  description: string;     // 面板提示
  ports: NodeTypePortSpec[]; // 默认端口模板（REQ-UI-401-004 的生成源）
  config_schema: "GeneratorConfigDTO" | null; // #63 控件清单数据源指针；null = config 恒 opaque {}
}

export const MVP_NODE_TYPES: NodeTypeSpec[];
export const MVP_ENABLED_PLANES: readonly ["MPEG_TS"]; // 镜像 domain MVP_ENABLED_PLANES（SIM_TOPO 纪律同源）
```

类型集草案（MVP 四类型；依据 = 八步闭环语义 + ADR-0005 决策 5 多端口组件 + SPEC-108 §4 唯一冻结 Config Schema；**测试/示例出现过的 tuner/mux/demux/monitor/generator/gain/muxer/ts_mux 串均非权威**，本表为唯一权威源）：

| node_type | label | id_prefix | ports（port_id: direction, plane, max_connections） | config_schema |
|---|---|---|---|---|
| `ts_generator` | TS 生成器 | `gen` | `ts_out`: output, MPEG_TS, 1 | `GeneratorConfigDTO` |
| `ts_mux` | TS 复用器 | `mux` | `ts_in_1`: input, MPEG_TS, 1；`ts_in_2`: input, MPEG_TS, 1；`ts_out`: output, MPEG_TS, 1 | null |
| `ts_demux` | TS 解复用器 | `demux` | `ts_in`: input, MPEG_TS, 1；`ts_out_1`: output, MPEG_TS, 1；`ts_out_2`: output, MPEG_TS, 1 | null |
| `ts_monitor` | TS 监测器 | `mon` | `ts_in`: input, MPEG_TS, 1 | null |

裁定依据与排除项：`ts_generator`（八步 Generate 锚 + 唯一冻结 config 面）；`ts_mux`（ADR-0005 决策 5 动机组件多端口入线；fault target 语法 `mux-0:pid:0x0100` 的 node_id 语义锚）；`ts_demux`（接收侧拆流教学锚）；`ts_monitor`（八步 Analyze/Inspect 沉淀端；SPEC-202 允许孤立/终端节点 idle）。排除 `tuner`/`gain`（RF 平面语义，平面未启用，随平面扩面入表）；排除 `bidirectional` 端口（无类型需要，ADR-0009 决定 3 悬项 MVP 不触发）。类型集与命名（`ts_*` 前缀 vs 既有 fixture 串）随实现票草案报 orchestrator 批准后冻结；批准变更走注册表变更 + 本规格版本递增。

### 5.2 草稿 state（应用方持有，受控模式）

```ts
interface TopologyDraft {
  topologyId: string | null;   // null = 未保存（首存走 POST → server uuid4）
  revision: number | null;     // server 最新 revision；POST 后为 1，PUT 后递增
  dirty: boolean;
  nodes: TopologyFlowNode[];   // TopologyNodeDTO 本体（node_id/node_type/config/ports 原样）+ RF 位置
  connections: TopologyFlowEdge[]; // connection_id + 四元组 + plane 原样
}
```

- 每个草稿节点在 `data` 携带其**建点时的端口集**（注册表模板生成或 GET 载入的存量 ports 原样）；保存按节点 data 的 ports 原样上报，不按当前注册表重导（不可变 revision 语义：旧 revision 载入不因注册表演进而变形）。
- 连线 `plane` 字段为派生值 = 两端端口 plane（预检保证相等，MVP 恒 `MPEG_TS`）；保存时原样写入 wire。

### 5.3 wire 映射（graphMapping.ts 纯函数对）

- `fromWire(topology: TopologyDTO) → {nodes, connections}`：`Handle id = port_id`；`Edge.source/target = node_id`、`sourceHandle/targetHandle = from_port/to_port`；随后跑确定性布局（§7.3）。
- `toWire(draft) → TopologyCreateRequest`：`nodes[] = {node_id, node_type, config, ports[]}`；`connections[] = {connection_id, from_node, from_port, to_node, to_port, plane}`——ADR-0005 决策 5 四元组逐字段，无 node-pair 二元组形态。
- 生成类型权威 = `src/api/schema.gen.ts`（`TopologyDTO`/`TopologyNodeDTO`/`TopologyPortDTO`/`TopologyConnectionDTO`/`TopologyCreateRequest`/`TopologySummaryDTO`/`TopologyValidationDTO`/`TopologyViolationDTO`），禁手写平行类型（SPEC-400 §5 纪律）。

## 6. 公开接口

### 6.1 topology REST 领域函数（`src/api/endpoints/topologies.ts`，经 `src/api` barrel additive 导出）

```ts
createTopology(body: TopologyCreateRequest): Promise<TopologyDTO>            // POST /api/v1/topologies → 201
listTopologies(limit?: number): Promise<TopologySummaryDTO[]>                // GET  /api/v1/topologies（1..1000，默认 100）
getTopology(topologyId: string, revision?: number): Promise<TopologyDTO>     // GET  /api/v1/topologies/{id}（缺省 latest）
saveTopologyRevision(topologyId: string, body: TopologyCreateRequest): Promise<TopologyDTO> // PUT → 200 新 revision
validateTopology(topologyId: string, revision?: number): Promise<TopologyValidationDTO>     // POST …/validate?revision=
```

非 2xx 一律抛 `ApiError{status, errorCode, message, retryable, details, requestId}`（SPEC-400 客户端纪律；`501` errorCode=`HTTP_501` →「未接线」呈现）。

### 6.2 对 #63（SPEC-402）的共享面

- `MVP_NODE_TYPES` / `MVP_ENABLED_PLANES`（注册表本体；#63 字段清单跟随 `config_schema` 指针）。
- `graphMapping` 纯函数对与 `violations` 解析器（节点表单的实体语境复用，禁另写映射）。
- `ViolationPanel` 组件（含 prepare 422 同口径条目输入，§7.5）。

## 7. 处理算法

### 7.1 拖放建节点（REQ-UI-401-002/004）

1. 面板条目 `dragstart` 写入 `node_type`（dataTransfer；条目清单 = 注册表声明式渲染，组件零类型字面量）。
2. 画布 `onDrop`：`screenToFlowPosition` 得落点；按 `node_type` 查注册表得模板。
3. 生成 `node_id = <id_prefix>-<n>`：n 为该前缀在草稿（含已载入节点）内未占用的最小非负整数——确定性、测试稳定、语义 slug（SPEC-202 §4 / ADR-0006 决定 3 同源词汇）。
4. 默认端口自动生成：`ports = 模板.ports` 原样深拷贝（REQ-UI-401-004；与注册表一致性的验收锚）；`config = {}`（opaque；编辑归 SPEC-402）。
5. `config_schema` 非 null 的类型在节点角落渲染「配置待填」提示位（仅指示，不构成表单）。

### 7.2 连线与预检（REQ-UI-401-003/005）

- `ConnectionMode.Strict` + 把手↔把手拖拽；`onConnect` 生成 `connection_id = conn-<n>`（草稿内最小未占用序数），四元组 + plane 落草稿。
- `isValidConnection` 四项预检（全为纯查表，无副本校验器）：
  1. **方向**：source 端口 direction ∈ {output, bidirectional} 且 target ∈ {input, bidirectional}；
  2. **自环**：同节点且同 port_id 拒绝（与 SPEC-202 §5 自环规则同口径）；
  3. **基数**：两端端口草稿内既有连线数 + 1 ≤ `max_connections`；
  4. **单平面**：两端端口 plane 相等且 ∈ `MVP_ENABLED_PLANES`（REQ-UI-401-005；后端 validate 媒体规则 + 未启用平面纪律的双层前端腿）。
- 任一预检不过：连接不建立（拖拽落空），**不弹错误**——引导层反馈口径（SPEC-408 §4.5/§7.6 修订）：拖拽中非法把手降透明度（预览），落空后工具栏状态区一行原因提示（约 4 秒自动消失，内联非弹窗；原因枚举见 SPEC-408 §4.5）——「非法拖不上去即 UX」（ADR-0009 决定 4）细化为可诊断反馈；后端仍是权威（§7.4 双层语义）。

### 7.3 确定性自动布局（ADR-0009 决定 5）

- Kahn 分层拓扑序：列 = 层深；同层按 `node_id` 字典序 tie-break（与 SPEC-202 §6.2 确定性全序同口径）；x/y = 固定列距/行距常量。同图同草稿必得同布局（纯函数，测试钉确定性）。
- 存量图含环（SIM_TOPO_CYCLE 待后端裁决时）：布局退化为 `node_id` 字典序网格（画布仍可渲染，违规由校验面板 graph 级条目承载）——布局函数对不可拓扑图 total。

### 7.4 保存流与 path-addressed 就地展示（REQ-UI-401-006/007）

保存流（不可变追加，客户端永不自选 revision）：

1. 未保存草稿 → `createTopology(toWire(draft))` → 201 得 `topology_id`（server uuid4）与 `revision = 1`；
2. 已存草稿 → `saveTopologyRevision(topologyId, toWire(draft))` → 200 得 `revision = latest + 1`；
3. 保存成功后立即 `validateTopology(topologyId, 新 revision)` → 违规进面板就地展示；失效 `qk.topologies`/`qk.topology` 键重取（查询缓存追赶事实）；
4. PUT/POST 不因图不合法被拒（后端 persistence 不跑校验器，SPEC-200 §6 姿态：拒绝发生在 session VALIDATING）——因此 validate 是保存流的固定第三步，不是可选项。

path 语法 → 画布实体映射（权威 = `src/simulation/state/validate.py` 现行发射；逐字匹配）：

| path 形状 | 实体 | 就地呈现 |
|---|---|---|
| `nodes[<node_id>]` | 节点 | 节点体错误描边 + 面板条目 |
| `nodes[<node_id>].ports[<port_id>]` | 端口 | 对应 Handle 错误描边 + 节点体描边 + 面板条目 |
| `connections[<connection_id>]` | 连线 | 边错误着色 + 面板条目 |
| `topology` | 全图 | 面板 graph 级条目（环路等无单实体归属者）+ 顶部横幅计数 |
| 其余（防御） | 全图 | 面板条目原样展示，不做实体映射 |

- 面板条目 = `code/path/message` 三键**逐字原样**（snake_case wire 纪律）；点击条目选中并居中对应实体。
- 未解析到实体的 path（如引用已删除实体）降级为 graph 级条目，不静默丢弃。
- 载入存量 revision 时同样跑 `validateTopology` 初始展示（打开即真实状态）。

### 7.5 run prepare 422 同口径（REQ-UI-401-006 第二通道）

- 形状权威 = SPEC-500 §6 信封 + 实测（`tests/integration/api/test_rest_runs.py`）：`ApiError.errorCode ∈ {SIM_TS_PLAN_INVALID, SIM_TS_CONFIG_INVALID}`；`details.errors[]` 为**自由文本错误串**（含违规参数名，非可解析实体路径）。
- 展示规则：错误串逐条原样进同一 ViolationPanel（source 标记 `run_prepare`，与 topology 条目视觉同口径）；**尽力高亮** = 串内词边界命中草稿 `node_id` 者点亮对应节点（如 target 串含 `mux-0`），无命中则仅面板条目——不伪造实体映射、不解析语义。
- 触发归属：run 提交面在 SPEC-403/406（session/run 控制票）；本规格交付 ViolationPanel + 条目输入契约（§6.2），由触发票 additive 接线；画布自身的第二通道演示经组件测试以真实 wire 形状 fixture 钉住（§11）。

### 7.6 载入流

`listTopologies` 列存量（id-ASC）→ 选中项 `getTopology(id, revision?)` → `fromWire` + 布局 → validate 初始展示。新建入口 = 面板「新建拓扑」（首存 POST）。

## 8. 错误处理

- REST 错误按 SPEC-400 §8 家族分支：404 `SIM_TOPOLOGY_NOT_FOUND`（列表项失效 → 刷新列表 + 面板提示）；400（`REQUEST_BODY_INVALID`/identity keys → 面板提示，属前端缺陷类）；`HTTP_501` →「未接线」显式呈现（不伪装成功）；503 存储不可用 → 重试提示（`retryable`）。
- 预检拒绝无弹窗错误面（§7.2）：拖拽中非法把手降透明度，落空后一行原因提示约 4 秒自动消失（SPEC-408 §4.5/§7.6 口径）；保存/校验的网络失败不丢草稿（dirty 保持，重试幂等——PUT 每次成功都会产生新 revision，属不可变追加的既定语义，面板提示 revision 已递增）。
- 禁令：UI 本地状态不得推导业务结论——画布显示的 ok/违规一律来自服务端 validate 响应，前端预检通过 ≠ 服务端合法（§5 禁令在本画布的落实）。

## 9. 资源约束

- 单机单用户、`127.0.0.1`、无认证（SPEC-500 §3 既有）；桌面 Chromium 系浏览器（E2E CI Chromium；Windows 桌面为验收环境）。
- `@xyflow/react ^12` 为本规格唯一新增运行时依赖（lockfile 锁定；package.json additive 一行，#62 唯一允许的 package.json 改动）；随附 zustand 等传递依赖不作事实源（ADR-0009 决定 4 审计面）。
- attribution 角标保留（MIT）；画布区域尺寸随路由区布局，无移动端适配。
- `features/topologies/` 内全部文件 UTF-8；`check_specs` 扫描面适用（`.tsx` 文本被扫）。

## 10. 依赖

| 依赖 | 性质 | 消费点 |
|---|---|---|
| SPEC-003 §2.1/§6 | 拓扑领域模型 + NodeType 待明确项落定 | §5.1 注册表；wire 字段权威 |
| SPEC-202 §4/§5 | 图契约 + 验证规则 + path 语法 | §7.2 预检口径；§7.4 映射表 |
| SPEC-500 §4.1/§6 | topology 五路由 + 错误信封 | §6.1 领域函数；§8 分支 |
| SPEC-400（APPROVED 0.5.1） | SPA 基座：路由注册/DTO 生成/查询词表/客户端纪律 | 全部基础设施，禁另起第二机制 |
| ADR-0005 决策 5 | 端口级四元组 + 默认端口自动生成 + 单平面 | §5/§7 全局 |
| ADR-0009 | 画布六决定（normative） | §4.1 |
| #80 后端面（topology 路由 live + session 绑定） | REST 通路 | 保存/校验/载入全链路真实可用 |
| #63（SPEC-402） | 下游消费注册表与映射面 | §6.2 共享契约 |

## 11. 测试向量

- 组件/交互测试（Vitest + Testing Library + React Flow 测试姿势，断**形状**不快照 DOM——tests/README §6 同源纪律）：
  - nodeTypes：四类型字段形状逐键断言（node_type/id_prefix/ports 模板键名与值域）；`MVP_ENABLED_PLANES` 恒 `["MPEG_TS"]`；组件侧零类型字面量（面板渲染源 = 注册表）。
  - graphMapping：`toWire`/`fromWire` 往返逐字段（四元组 + plane + ports 原样）；Handle id = port_id；布局确定性（同输入两次布局全等；含 tie-break 乱序输入）；环退化网格。
  - isValidConnection：方向/自环/基数/单平面四项逐项正负例（含 max_connections 边界相等放行、超 1 拒绝；非 MPEG_TS fixture 端口拒绝）。
  - violations：§7.4 表逐形状解析（含防御分支）；prepare 422 fixture（SIM_TS_PLAN_INVALID details.errors 实测形状）→ 同口径条目 + node_id 词边界高亮/无命中降级。
  - TopologyEditor 交互：拖放（注册表条目）→ 建点含默认端口；onConnect 落草稿；保存流调用序列（POST/PUT → validate → 键失效）以 mocked api 断言；不做清单五项无入口（无 undo/copy/tab/plane-switch/diff 的交互面）。
- E2E（Playwright，`e2e/topology.spec.ts` 新文件，双 webServer 既有编排）：拖放 → 连线 → 保存 → 断言 revision 递增 + 重载后节点/连线持久；非 MPEG_TS 连线经 REST 直写后 validate 违规就地呈现（后端双层腿）；全链路真浏览器。

## 12. 验收标准

- **AC-401-01**（REQ-UI-401-002/003/007）：拖放 → 连线 → 保存 → 新 revision 全链路走通——E2E 真浏览器断言保存响应 revision = 载入 revision + 1（或新建首存 = 1），重载画布与保存内容一致（节点/连线逐字段）。
- **AC-401-02**（REQ-UI-401-001/004）：默认端口自动生成与注册表一致——拖放产物的 ports 与注册表模板逐字段相等；面板清单与注册表清单一致且组件无自造类型。
- **AC-401-03**（REQ-UI-401-005）：未启用平面禁连线——isValidConnection 单平面预检有正负例测试；后端层经 validate 违规就地呈现（E2E 双层腿）。
- **AC-401-04**（REQ-UI-401-006 前半）：path-addressed 校验错误定位到节点/端口/连线就地展示——§7.4 映射表逐形状有测试；面板逐字 code/path/message。
- **AC-401-05**（REQ-UI-401-006 后半）：prepare 422 错误同口径展示——真实 wire 形状 fixture 进同一面板 + 尽力高亮规则有测试。
- **AC-401-06**（不做清单）：撤销/重做、复制粘贴、多 tab 并行编辑、平面切换 UI、拓扑 diff 五项无任何交互入口（测试断言 + 评审检查项）。
- **AC-401-07**（SPEC-408 §4.5 引导层，0.5.1 增）：五项引导面落位——页内常驻说明条（进阶定位 + Lab 关系声明 + 去 Lab/回主页链接）/ 画布空态三问覆盖层（`nodes.length === 0` 显示、放下首节点消失）/ 保存 gate 说明区（三类原因分行指向、无修改、保存中；hover title 撤除）/ 连线反馈（拖拽中非法把手降透明度 + 落空一行原因提示约 4 秒）/ 保存成功声明每次显示——文案与验收细则以 SPEC-408 §4.5/§12.1 为准。

## 13. 非目标

- 不做（#18 五项 + ADR-0009 既裁）：撤销/重做、复制粘贴、多 tab 并行编辑、平面切换 UI、拓扑 diff、画布位置持久化、节点体拖放自动选端口、bidirectional 双把手渲染、第三方布局库、节点配置表单（SPEC-402）、session/run 控制 UI（SPEC-403/406）。
- **编辑器拓扑接入主干旅程（消费方集成）**：非目标（SPEC-408 §4.5 既裁升格）——Lab 场景使用场景自带初始拓扑、不读取本编辑器保存的拓扑，前端 5 个拓扑领域函数唯一调用方是编辑器自身；「无消费方」是有意的边界声明而非遗漏；未来接入属 roadmap 候选独立 effort。
- 不引入：全局客户端状态库承载画布草稿以外的服务端事实；第二 WS/REST 通道；绕过生成链的手写契约类型。
- 不冻结（编写期钉扎并有测试）：布局列距/行距常量；`conn-<n>`/`<prefix>-<n>` 具体格式若实现期发现与 fault target 语法冲突可调（变更随报告申报）。

## 14. 兼容性与交付要求

- 共享面 additive-only：`src/api/endpoints/topologies.ts` 新文件 + barrel 一行导出；`package.json` 仅 `@xyflow/react` 依赖一行；`routes.tsx` 零改动（条目已存在）；`schema.gen.ts` 禁手改（类型缺口走 `dto:sync` 并申报）。
- 注册表工件为 #63 前置共享面：批准前不实现（两阶段协议）；批准后类型集变更须同步本规格 §5.1 与 INDEX/REGISTRY 语义行。
- 后端 `/api/v1` additive-only：拓扑面字段新增经 `dto:sync` 吸收；删除/改名走 `/api/v2` 决策（漂移锁 CI 捕获）。
- 交付物：SPEC-401 本文（批准翻 APPROVED）、`features/topologies/**`、`endpoints/topologies.ts` + barrel 行、`e2e/topology.spec.ts`、SPEC-INDEX-FRONTEND 本行链接更新。
- 门禁：前端 lint/typecheck/test:run/build/dto:check/e2e + Python 三门（pytest 必绿组合 / `PYTHONPATH=$PWD/src lint-imports` / `python -I tools/check_specs.py`）全绿。

## Phase 2 定点修订（随落笔票 #119，DRAFT_FOR_REVIEW 0.5.2；依据：细裁 [#110](https://github.com/BingChaoLiu/DVB-Nexus/issues/110)）

- **§5.1 NodeType 注册表新增两类型**（机制零改动，仅类型集扩面）：

| node_type | label | id_prefix | ports（port_id: direction, plane, max_connections） | config_schema |
|---|---|---|---|---|
| `t2mi_encapsulator` | T2-MI 封装器 | `enc` | `inner_in`: input, MPEG_TS, 1；`t2mi_out`: output, T2MI, 1 | T2miEncapsulatorConfigDTO（bbframe_params + plp_assignment，SPEC-600/602） |
| `t2mi_demux` | T2-MI 解封装器 | `dmx` | `t2mi_in`: input, T2MI, 1；`inner_out`: output, MPEG_TS, 1 | T2miDemuxConfigDTO（plp_filter，SPEC-602） |

- **MVP_ENABLED_PLANES 镜像扩容**：`readonly ["MPEG_TS", "T2MI"]`（镜像 domain MVP_ENABLED_PLANES，同源纪律；连线预检四项之平面项随扩容自动放行 T2MI 连线——「平面不符」原因枚举文案改为「平面不符（当前支持 MPEG_TS / T2MI）」）。
- **BBFrame 词汇纪律**：面板/画布文案不得出现「BBFrame 平面」（BBFrame = 节点内部层次，[#110] 裁决）；两类型 label/description 文案以 CONTEXT.md「Phase 2 封装层」词条组为准。
- 既有排除项延续：RF 面 tuner/gain 随 Phase 3 平面扩面入表；编辑器功能增强五项与「用户自定义拓扑进闭环」非目标不变。
