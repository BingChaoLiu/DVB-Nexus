---
spec_id: SPEC-202
title: L0 State Engine and Topology Evaluation
version: 0.5.0
status: APPROVED
phase: MVP
owner: Simulation Engine
priority: P0
depends_on: [SPEC-003]
requirements: [REQ-SIM-202-001, REQ-SIM-202-002, REQ-SIM-202-003, REQ-SIM-202-004, REQ-SIM-202-005]
---

# SPEC-202 — L0 State Engine 与拓扑求值（SIM_STATE Runtime）

## 1. 目标

定义 SIM_STATE 保真级（L0，CONTEXT.md）的状态求值：对逻辑拓扑做纯函数式状态传播，产出节点健康、输出状态、指标与因果引用，**不生成任何 TS 字节**。L0 是"只算状态不产字节"的 Runtime，与 L1（SPEC-203）是同一业务系统的两种保真实现。

## 2. 范围

### 2.1 In Scope

- 拓扑图契约：节点、命名端口、端口级连线（ADR-0005 端口级拓扑）。
- 拓扑验证规则与 path-addressed 错误。
- 节点求值器（pure evaluator）与确定性拓扑序。
- 严重度优先级与下游因果引用。
- `topology.state_changed` 事件的发射义务（包级契约承载信封）。

### 2.2 Out of Scope

- TS 字节生成与包级语义（TS Core 100~108 / SPEC-203）。
- 故障注入（SPEC-204；L0 场景的故障语义由 fault plan 声明、经求值器结果表达，不产生字节变更）。
- 画布渲染与交互（前端；ADR-0005 决策 2 已将画布健康显示降级为 Run 状态 + 诊断事件映射）。
- 增量求值的具体算法（MVP 全量重算即可，见第 7 节）。
- RF/T2MI 等非 MPEG_TS 平面语义（roadmap；平面枚举见 SPEC-003 §2.1，MVP 仅启用 `MPEG_TS`）。

## 3. 架构位置与依赖

仅依赖 SPEC-003（拓扑配置模型、时间模型）。求值是纯函数：无 IO、无墙钟读取、无随机数、不修改其他节点状态。SPEC-200 编排本模块；本模块不感知 Runtime 生命周期。

## 4. 图契约

- 节点有稳定 `nodeId`（拓扑内语义 slug，ADR-0006 第 3 条）、类型、config 与**命名端口**。
- 连接必须标识 `from_node/from_port → to_node/to_port` 四元组；仅 node-to-node 的两端连线**不合法**——Mux 等多端口组件（ADR-0005 决策 5）无法用二元组无歧义表达。
- 端口声明方向（input/output/bidirectional）、媒体类型（plane）与最大连接数。
- 配置模型版本化并做 schema 校验（SPEC-003 §2.1 约束）。

## 5. 验证规则

拒绝并返回 path-addressed 结构化错误（定位到 node/port/connection）：

| 规则 | 说明 |
|---|---|
| 重复 ID | nodeId / portId / connectionId 冲突 |
| 端点缺失 | 连接引用的 node/port 不存在 |
| 方向非法 | output→output、input→input |
| 媒体类型不兼容 | plane 不匹配的连线（MVP 全为 MPEG_TS，规则仍保留供扩面） |
| 基数违规 | 超出 maxConnections |
| 自环 | from == to（同节点同端口） |
| 环路 | 拓扑含环（MVP 拒绝；DAG 才可确定性求值） |

- **允许孤立节点**（未连接）：合法，报告为 idle。
- 验证是非变异操作：不修改拓扑，可重复执行。
- 全部拒绝项有稳定错误码，前缀 `SIM_TOPO_*`。

## 6. 求值语义

### 6.1 节点求值器

求值器是纯函数：

```python
def evaluate(node: NodeConfig, inputs: Mapping[PortId, PortState],
             context: EvalContext) -> NodeEvalResult: ...
```

- `NodeEvalResult` 包含：health（ok/warn/error/idle）、各输出端口状态、节点指标、因果引用（causes）。
- **禁止**：IO、墙钟读取、随机操作、修改其他节点。相同输入必得相同输出。
- EvalContext 携带拓扑 revision、虚拟时间域引用与节点配置版本；不得携带墙钟。

### 6.2 确定性拓扑序与严重度

- 拓扑序唯一化：合法拓扑为 DAG；同层并列节点按 **nodeId 字典序** tie-break，保证全序确定。
- 严重度优先级：`error > warn > idle > ok`。
- **下游因果引用**：下游节点的异常状态必须携带指向上游根因节点/端口的引用链，画布"Run 状态 + 诊断映射"与 SPEC-306 诊断都消费该引用。

### 6.3 事件与快照

- 状态变化经包级契约发射 `topology.state_changed`（ADR-0006 信封；node_id 语义寻址，ADR-0006 第 3 条 target 双形式之节点级）。
- 求值结果进入 SPEC-200 快照；观测面按 SPEC-300 数据所有权表镜像，Observation 不反向修改求值状态。

## 7. 增量模式

- **MVP 允许全量重算**：每次输入变化后重算全图。图规模（MVP 沙盘拓扑 ≤ 数十节点）下全量重算满足性能。
- 若未来引入增量求值，必须满足等价约束：**对相同输入，增量输出与全量输出完全相等**（含因果引用与事件序）；该约束作为增量模式的准入验收。

## 8. 错误与诊断码

| Code | 条件 | 处理 |
|---|---|---|
| `SIM_TOPO_DUPLICATE_ID` | ID 冲突 | 拒绝 |
| `SIM_TOPO_ENDPOINT_MISSING` | 端点/端口不存在 | 拒绝 |
| `SIM_TOPO_DIRECTION_INVALID` | 方向非法 | 拒绝 |
| `SIM_TOPO_MEDIA_INCOMPATIBLE` | plane 不匹配 | 拒绝 |
| `SIM_TOPO_CARDINALITY` | 超 maxConnections | 拒绝 |
| `SIM_TOPO_SELF_LOOP` | 自环 | 拒绝 |
| `SIM_TOPO_CYCLE` | 环路 | 拒绝 |
| `SIM_EVAL_NODE_FAILED` | 求值器内部异常 | 隔离该节点为 error 态并报告；不得使全图求值崩溃 |

## 9. 测试规格

- 第 5 节全部规则的负向样例（每条规则至少一个最小反例）与 path 定位断言。
- 环路检测：2 节点环、自环、经多端口的隐式环。
- 确定性：同图同配置多次求值，除 operational 时间戳外逐字段相等；tie-break 用乱序输入节点列表验证。
- 严重度传播：error/warn/idle/ok 组合的优先级与因果引用链完整性。
- 孤立节点 idle 语义。
- 纯函数性：求值器内 monkeypatch 墙钟/随机源的检测性测试（实现用依赖注入保证可测）。

## 10. 验收标准

- `REQ-SIM-202-001`：端口级四元组连线契约与全部验证规则实现并有负向测试。
- `REQ-SIM-202-002`：环路拒绝且拓扑序确定（nodeId tie-break）。
- `REQ-SIM-202-003`：同图同配置求值结果确定（排除 operational 时间戳）。
- `REQ-SIM-202-004`：下游异常状态携带到根因的因果引用。
- `REQ-SIM-202-005`：若存在增量模式，增量与全量输出等价（本 MVP 允许仅全量）。

## 11. 非目标与风险

- 不评估字节级正确性——L0 的"正常"只意味着逻辑状态传播健康，与真实码流合规无关；两类结论不得互证（观测来源纪律，CONTEXT.md）。
- 不做节点类型注册表（NodeType 清单与 Config Schema 归 SPEC-003 §6 待明确项 + 节点 Module Spec）。
- 风险：求值器接入真实节点语义时引入隐式全局状态——以纯函数签名 + 依赖注入评审约束。

## 12. 交付要求

建议文件：`app/simulation/state/`（graph.py / validate.py / evaluate.py）；测试置于 `tests/unit/simulation/state/`。`topology.state_changed` payload schema 随实现按 SPEC-301 §7 注册。

## 13. 参考

- ADR-0005（端口级拓扑、多端口 Mux、画布降级裁决）。
- SPEC-003 §2.1 Topology、§3 状态模型。
- SPEC-300 §5 数据所有权表（L0 状态的权威归属）。
