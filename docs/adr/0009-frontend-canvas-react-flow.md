---
status: accepted
date: 2026-11-14
---

# 前端画布选型：React Flow（@xyflow/react 12.x）

评审对象是 MVP 拓扑画布（SPEC-401）的画布库选型与集成边界，前置为 [#18](https://github.com/BingChaoLiu/DVB-Nexus/issues/18) 前端切集（拖放建节点 + 端口级连线 + 默认端口自动生成 + 校验就地展示入 MVP）与 React Flow 现状调研（2026-11-14 实测核实：12.12.1、MIT、60KB gzip、~21M 周下载、活跃维护）。评审过程见 [#19](https://github.com/BingChaoLiu/DVB-Nexus/issues/19)。本 ADR 将 [ADR-0003](0003-frozen-tech-stack.md) 第 2 条的「拓扑画布优先评估 React Flow」正式冻结，其余 ADR 不受影响。

## 决定（六条，HITL 确认制按推荐全收）

### 1. 画布库 —— GO，React Flow

采用 `@xyflow/react` 12.x。与 SPEC-401 切集逐项映射：端口级连线 = `Handle id` + `Edge.sourceHandle/targetHandle`（SPEC-202 §4 `from_node/from_port → to_node/to_port` 四元组直接映射）；受控状态 = nodes/edges 作 props + 类型化 change intents（应用方过滤/拒绝，`onBeforeDelete` 可否决删除）；拖时校验 = `isValidConnection`（拖拽落点即判，官方建议挂 `<ReactFlow>` 层）；拖放建节点 = 官方 palette DnD 模式（pointer events + `screenToFlowPosition`）。

Considered-and-rejected：Cytoscape.js（图分析/可视化库，无节点编辑器语义：无类型化端口把手、无 React 自定义节点）；JointJS（节点编辑器级特性锁商业版 ~$2,990/dev，MPL 2.0）；自写 SVG（需重造 pan/zoom/把手命中/连线追踪全套，不抵 60KB gzip 依赖）。

### 2. 版本与 attribution —— 钉 ^12，保留角标

钉 `^12`（当前 12.12.1），不使用 13.0.0-next（pre-release 2026-10 起）；v13 升级按官方迁移指南另行评估。MIT 许可要求保留「React Flow」attribution 角标；移除需 Pro 订阅（纯资助性质，无功能门禁），单机内部工具不予购买。旧包 `reactflow`（v11，冻结于 2024-06）禁用。

### 3. 连线交互 —— 把手↔把手 only

默认端口自动生成（[ADR-0005](0005-architecture-baseline.md) 决策 5 既裁）落地为：NodeType 注册表端口模板渲染为可见 `Handle`，连线拖拽 = 把手到把手（`ConnectionMode.Strict` 保证 source→target，恰好承载 SPEC-202 方向规则）。节点体拖放自动选端口（`onConnectEnd` + `FinalConnectionState`）为交互增强，编写期再定（只影响前端逻辑，不动契约）。bidirectional 端口的把手映射（渲染为两个单向把手）编写期按 MVP NodeType 注册表实际清单定。

### 4. 集成边界 —— 受控纪律 + 最小客户端预校验

受控模式纪律：nodes/edges 为应用方 state，React Flow 只报 change intents（过滤 = 选择性应用，不应用 = 拒绝）；React Flow 内部 zustand store 不作事实源。编辑中草稿是客户端本地状态，保存 = PUT 新 revision（SPEC-500）才成为服务端事实——[#18](https://github.com/BingChaoLiu/DVB-Nexus/issues/18)「不自建第二事实源」纪律在画布上的延伸。

客户端预校验 = `isValidConnection` 做方向 + 自环 + 基数（maxConnections）三项 UX 预检（非法拖不上去），不在前端复制完整校验器；权威校验永远在后端——save validate / run prepare 422 path-addressed 错误按 node_id/port_id/connection_id 映射回画布实体就地高亮（SPEC-401 实体内容）。

### 5. 画布位置 —— MVP 不持久化

拓扑契约（SPEC-202 §4 + SPEC-500 DTO，0.5.0）无位置字段，MVP 不加：载入时确定性自动布局（手写拓扑序分列起步，不引第三方布局库；效果不满意编写期换 dagre/elkjs，非接口决策）；手动摆放 session 内有效，保存不带走位置。位置持久化留后续增强，届时走 additive 契约变更票。

### 6. 决策承载 —— 本 ADR

SPEC-401 实体文本编写时引用本 ADR 为 normative 依据；TASK-UI-401（[#60](https://github.com/BingChaoLiu/DVB-Nexus/issues/60) 补建）不再悬于选型票。

## Consequences

- 前端依赖面新增 `@xyflow/react`（运行时随附 zustand/classcat/@xyflow/system，peer react>=17）；lockfile 锁版本，旧包 `reactflow` 禁用。
- SPEC-401 编写时按本 ADR 条款落实体文本（把手交互/预校验范围/自动布局/受控纪律）。
- 画布位置不落库：拓扑 revision 不可变追加不包含视觉布局；后续如需持久化走 additive 契约变更票。
- v13 发布后升级须走官方迁移指南并复核 breaking changes，不静默升级。
