# DVB-Nexus 使用文档（简体中文）

[English](README.en.md) | 简体中文

> **文档状态**：随软件功能迭代逐步完善。当前覆盖 MVP（TS-first 八步闭环）与 Phase 2 高级封装层（T2-MI 三级封装、BISS 加解扰）的全部用户可见功能。
> 术语以根目录 [`CONTEXT.md`](../../CONTEXT.md) 为权威；本文只讲"怎么用"，不重复"是什么"的定义。

## 目录

1. [项目简介](#1-项目简介)
2. [环境要求](#2-环境要求)
3. [安装与启动](#3-安装与启动)
   - 3.1 [启动后端](#31-启动后端)
   - 3.2 [启动前端](#32-启动前端)
4. [界面导览](#4-界面导览)
   - 4.1 [Topologies — 拓扑编辑](#41-topologies--拓扑编辑)
   - 4.2 [Monitor — 码流监控](#42-monitor--码流监控)
   - 4.3 [Lab — 训练靶场](#43-lab--训练靶场)
5. [核心工作流：八步闭环](#5-核心工作流八步闭环)
6. [训练场景一览](#6-训练场景一览)
7. [REST API 与 WebSocket](#7-rest-api-与-websocket)
8. [环境变量参考](#8-环境变量参考)
9. [常见问题（FAQ）](#9-常见问题faq)
10. [文档完善计划](#10-文档完善计划)

---

## 1. 项目简介

DVB-Nexus（DVB Sandbox）是集**实时码流排查**与**交互式协议演练**于一体的单机工程平台：

- **沙盘模式**：脱离真实硬件与直播源，由仿真引擎自主产生链路状态。MVP 聚焦 MPEG-TS 传输层：188-byte 包长、`analysis_only` 生成档（结构合规、可解析可分析；负载为确定性合成数据，不承诺可播放）。Phase 2 扩展高级封装层：T2-MI → BBFrame → Inner TS 三级封装与 BISS Mode 1 / Mode E 加解扰。
- **八步闭环**：Create → Generate → Inject → Analyze → Diagnose → Inspect → Recover → Verify，全程有真实数据和可追溯证据。
- **训练靶场**：预置故障场景（SC-01 ~ SC-09），注入故障后由学员修复，以修复后的新 Run 证据判定通关（PASS / FAIL / INCONCLUSIVE）。

单机单用户、无认证（本机 `127.0.0.1` 部署姿态），不面向多用户或公网部署。

## 2. 环境要求

| 组件 | 版本要求 | 说明 |
|---|---|---|
| Python | ≥ 3.10 | 后端运行时 |
| Node.js | ≥ 22.12 | 前端构建与开发服务器 |
| npm | ≥ 11 | 前端包管理 |
| websockets（Python 包） | ≥ 14, < 16 | WebSocket 推送必需，见 [FAQ](#9-常见问题faq) |
| TSDuck CLI（可选） | 本机可用即可 | 双解析器对照、传输级故障注入、生成兜底；未安装时相关功能不可用，其余功能不受影响 |

运行姿态为 **Windows 优先**（ADR-0004）：其他平台可运行，但问题排查与 CI 以 Windows 为第一目标。

## 3. 安装与启动

以下命令均在仓库根目录执行（Windows 示例使用 Git Bash）。

### 3.1 启动后端

```bash
# 1) 创建并激活虚拟环境（可选但推荐）
python -m venv .venv
source .venv/Scripts/activate        # Git Bash / Windows
# source .venv/bin/activate          # Linux / macOS

# 2) 安装后端（editable 模式，便于开发）
pip install -e .

# 3) 安装 WebSocket 服务支持（uvicorn 缺它时拒绝所有 WS 握手）
pip install "websockets>=14,<16"

# 4) 启动 API 服务（必须显式指定 SQLite 数据库路径）
DVBNEXUS_DB_PATH="D:/dvbnexus-data/dvbnexus.db" \
python -m uvicorn bootstrap.asgi:app --host 127.0.0.1 --port 8765
```

也可使用等价的便捷入口（读取 `DVBNEXUS_HOST` / `DVBNEXUS_PORT`，默认 `127.0.0.1:8765`）：

```bash
DVBNEXUS_DB_PATH="D:/dvbnexus-data/dvbnexus.db" python -m bootstrap.asgi
```

要点：

- `DVBNEXUS_DB_PATH` **必须显式提供**，缺失时后端拒绝启动（显式契约优于静默建库）。
- Artifact 存储目录由数据库路径推导：`<db 所在目录>/artifacts/`。
- 启动成功后，`GET http://127.0.0.1:8765/api/v1/version` 应返回版本信息。

### 3.2 启动前端

```bash
cd frontend
npm install
npm run dev          # Vite 开发服务器，默认 http://localhost:5173
```

Vite 开发服务器把 `/api` 与 `/ws` 代理到后端 `http://127.0.0.1:8765`（保持 SPA 同源，前端无需处理 CORS）。后端不在默认地址时，用环境变量覆盖代理目标：

```bash
DVBNEXUS_BACKEND_ORIGIN="http://127.0.0.1:9000" npm run dev
```

浏览器打开 `http://localhost:5173` 即可使用。生产构建用 `npm run build`，本地预览构建产物用 `npm run preview`（固定端口 4173，同样带代理）。

## 4. 界面导览

顶部导航三个页面：**Topologies**（拓扑编辑）→ **Monitor**（码流监控）→ **Lab**（训练靶场）。

### 4.1 Topologies — 拓扑编辑

基于 React Flow 画布的链路拓扑编辑器：

- **节点面板**：从左侧面板添加节点类型——
  | 节点类型 | 说明 |
  |---|---|
  | `ts_generator`（TS 生成器） | 按 GeneratorConfig 产出 MPEG-TS 码流，八步闭环 Generate 的锚点 |
  | `ts_mux`（TS 复用器） | 多路 TS 输入复用为单路输出 |
  | `ts_demux`（TS 解复用器） | 单路 TS 拆分为两路输出（接收侧拆流） |
  | `ts_monitor`（TS 监测器） | 被动观测端点，Analyze/Inspect 证据沉淀端 |
  | `t2mi_encapsulator`（T2-MI 封装器） | Inner TS 经 BBFrame 封装段包化为 T2-MI 包流（Phase 2） |
  | `t2mi_demux`（T2-MI 解封装器） | T2-MI 包流 → BBFrame 解析 → Inner TS 重建（Phase 2） |

- **连线**：端口有方向（input/output）与最大连接数约束，非法连线会被前置拦截。启用的信号平面：`MPEG_TS` 与 `T2MI`（Phase 2 起；RF / SEC_CONTROL / IP 平面模型保留扩展位）。三级封装子图 = 生成器 → 封装器 → 解封装器 → 监测器。
- **校验**：拓扑提交后端校验，违规以面板列出（缺失监测端、端口失配等），按提示修正后重提交。
- 拓扑保存后进入会话（Session），在 Monitor 页驱动生命周期。

### 4.2 Monitor — 码流监控

会话作用域的码流监控台（URL 带 `?session=<id>`），页面分两个页签：

**Stream 页签**（八步闭环的主操作面）：

- **生命周期控制条**：start / pause / resume / validate / stop / dispose（删除会话）。
- **总览卡与 Run 触发**：查看会话概要，触发新 Run（Generate）。
- **指标面板**：PID 级观测指标。
- **告警面板**：规则引擎产生的告警。
- **诊断列表**：根因候选（按规则静态置信度 high / medium / low 排序），每条候选可携带证据链接。
- **包检查器（Packet Inspector）**：从观测/诊断一键下钻到原始码流——PID + packet index + Artifact 三元组定位，查看 188-byte 包与表解码详情；`view=t2mi|bbframe|ts` 参数切换三视图（T2-MI 包头 6 字节逐字段 + CRC-32、BBHEADER 10 字节逐字段 + UP 边界、Inner TS 结构），默认 `ts`。
- **Journal 尾流**：事件流水（含流水号盖章），实时节流刷新；Phase 2 起 `gen.*`（构造阶段与抽样包）、`t2mi.*` / `bbframe.*` / `biss.*`（封装与加解扰事件）注册表驱动呈现，密钥只以指纹形式出现。
- **Verify 表单与结果卡**：提交修复声明，以新 Run 证据判定 PASS / FAIL / INCONCLUSIVE。

**CLI Console 页签**：TSDuck 子进程调用记录（命令行、状态、输出），用于核对双解析器对照与传输级注入的实际执行。

### 4.3 Lab — 训练靶场

预置场景的交互式训练区：

- **场景库**：九套内置场景（见 [第 6 节](#6-训练场景一览)），含难度分级、目标描述与初始拓扑。
- **实验控制台**：从场景开局两跳进入实验，自动装配会话与故障计划。
- **八步 Stepper**：把八步闭环映射为可跟踪的步骤条，逐步推进。
- **生成过程折叠区**：只读展示分层流水线各阶段进度（Inner TS / BBFrame / T2-MI）与抽样包卡片，点击可携带 `view` 参数跳包检查器。
- **提示阶梯（Hints Ladder）**：卡住时逐级揭示提示，鼓励先自诊再求助。
- **答案揭示（Solution Panel）**：仅当验证结果为 **PASS** 时解锁——修复动作本身、UI 变绿都不算通关证据。

## 5. 核心工作流：八步闭环

一次完整实验对应闭环的八步：

| 步骤 | 动作 | 所在页面 | 产出 |
|---|---|---|---|
| 1 Create | 创建会话并绑定拓扑 | Topologies / Lab | Session |
| 2 Generate | 触发 Run 生成基线码流 | Monitor | baseline TS Artifact |
| 3 Inject | 注入故障（等位替换，不增删包） | Monitor / Lab | faulted TS Artifact |
| 4 Analyze | 对码流执行结构分析 | Monitor | 观测 + 告警 |
| 5 Diagnose | 产出根因候选 | Monitor | 诊断列表（置信度分档） |
| 6 Inspect | 下钻原始码流核对证据 | Monitor | PID + packet index + Artifact |
| 7 Recover | 实施修复（变更拓扑/配置重新生成） | Monitor / Lab | 修复后的新 Run |
| 8 Verify | 以新 Run 证据判定通关 | Monitor / Lab | PASS / FAIL / INCONCLUSIVE |

两条纪律贯穿全程（详见 `CONTEXT.md`）：

- **观测不混标**：每条观测必带来源（generator / internal_parser / tsduck / …）与置信度（simulated / parsed / measured / inferred）；仿真产物不会标成 parsed。
- **通关看证据**：判定以修复后的新 Run 证据为准，不以 UI 状态为准；"无告警"不等于"干净"。

## 6. 训练场景一览

内置场景分两包（`scenarios/` 目录）：

**Lab Pack v1（TS 层基础）**：

| 场景 | 标题 | 难度 | 考察点 |
|---|---|---|---|
| SC-01 | 认识闭环：PAT 缺失 | 入门 | 走通八步闭环；从"无节目"现象定位 PSI 根表缺失 |
| SC-02 | CRC 防线：PMT 校验和失效 | 入门 | 表 CRC 校验失败的症状与证据核对 |
| SC-03 | 声明失配：PMT PID 重指向 | 中级 | PMT 声明与实际包流不一致的定位 |
| SC-04 | 连续性破坏：CC 相对偏移 | 中级 | 连续性计数器（CC）异常与丢包症状排查 |
| SC-05 | 双故障靶场：组合症状 | 高级 | 两类故障叠加的组合症状诊断 |

**Lab Pack v2（Phase 2 高级封装层）**：

| 场景 | 标题 | 难度 | 考察点 |
|---|---|---|---|
| SC-06 | 封装错位：T2MI PLP 映射 | 中级 | 期望 PLP 与实际 PLP 漂移——外层绿灯但 Inner TS 无业务（"缺失 ≠ 零"） |
| SC-07 | 封装错位：BBHEADER 同步 | 中级 | SYNCD 位距错配的定位（"SYNCD 是位距离，不是同步字节"） |
| SC-08 | 加扰错位：BISS 密钥 | 中级 | session word 错配的解扰证据链（"解扰失败 ≠ 码流损坏"，密钥只看指纹） |
| SC-09 | 时序错位：PMT 版本更新后 PID 漂移 | 高级 | PMT 版本更新而 Demux 过滤表未同步的漂移定位 |

建议按 SC-01 → SC-05 顺序练习 TS 层基础（先闭环、后单故障、再组合故障），再进入 SC-06 → SC-09 高级封装层。

## 7. REST API 与 WebSocket

- 基础前缀：`/api/v1`（additive-only 版本策略）。
- 交互式文档：`http://127.0.0.1:8765/docs`（Swagger UI，由 OpenAPI 生成；前端类型即从 `/openapi.json` 同步）。
- 版本探针：`GET /api/v1/version`。
- 资源组：`sessions`（生命周期）、`topologies`（拓扑 CRUD + 校验）、`runs`（生成）、`scenarios`（靶场场景）、`artifacts`（产物元数据与内容 + `GET /artifacts/{id}/structure?view=t2mi|bbframe|ts` 结构视图）、observation 组（指标 / 告警 / 快照 / 诊断 / 验证）、`tsduck_calls`（CLI 调用记录）。
- WebSocket：`/ws/v1/sessions/{session_id}`，会话级事件推送（journal / 提示）。注意 `/ws/v1` 不在 `/api/v1` 前缀下。

单机单用户姿态：无认证、固定本机租户身份，请勿直接暴露公网。

## 8. 环境变量参考

| 变量 | 默认值 | 作用 |
|---|---|---|
| `DVBNEXUS_DB_PATH` | 无（必填） | SQLite 数据库路径；artifact 目录推导为其父目录下的 `artifacts/` |
| `DVBNEXUS_HOST` | `127.0.0.1` | 便捷入口绑定主机 |
| `DVBNEXUS_PORT` | `8765` | 便捷入口绑定端口（与 Vite 代理默认值一致） |
| `DVBNEXUS_PUMP_INTERVAL_MS` | `50` | 服务模式下泵 tick 间隔（journal 落库 / WS 扇出） |
| `DVBNEXUS_BACKEND_ORIGIN` | `http://127.0.0.1:8765` | 前端 Vite 代理的后端源 |

## 9. 常见问题（FAQ）

**Q1：前端页面收不到实时事件，后端日志显示 WS 握手 404？**
uvicorn 缺少 WebSocket 服务库时会拒绝所有 WS 握手（404）。安装并重启后端：
`pip install "websockets>=14,<16"`。

**Q2：后端启动报 "DVBNEXUS_DB_PATH is required"？**
数据库路径是显式契约，不提供默认值。设置环境变量后启动，例如
`DVBNEXUS_DB_PATH="D:/dvbnexus-data/dvbnexus.db"`。目录不存在时会自动创建数据库文件；产物落在同目录 `artifacts/` 下。

**Q3：前端代理连不上后端？**
确认后端在 `127.0.0.1:8765` 运行；换了端口时同步设置 `DVBNEXUS_BACKEND_ORIGIN` 再启动前端。

**Q4：没装 TSDuck 会怎样？**
核心闭环（自研 TS Core 语义层）不受影响；双解析器对照、传输级故障注入、生成兜底三类能力不可用，相关测试显式跳过。安装 TSDuck（≥ 3.40 建议版本）后自动启用。

**Q5：生成的 TS 能直接播放吗？**
不能。MVP 只承诺 `analysis_only`：结构合规、可解析可分析，负载是确定性合成数据；可播放档（`playback_ready`）在远期路线图。

**Q6：为什么我修复了问题，实验还是没通关？**
通关以**修复后的新 Run 证据**判定，需要走完 Recover（重新生成）与 Verify（提交验证）；UI 上组件变绿、告警消失都不是证据。

## 10. 文档完善计划

本手册与软件功能同步迭代，当前覆盖 MVP 与 Phase 2 全部用户可见功能。规划中的后续章节：

- 示例配置说明（`examples/ts-generator-minimal.json` 字段逐项解释）
- 场景编写指南（`scenarios/*.json` schema 与故障计划语法）
- Artifact 与证据链详解（SHA-256、配置哈希、故障档案）
- TSDuck 集成进阶（双解析器对照解读、CLI Console 输出分析）

发现文档缺口或错误请提 [GitHub Issue](https://github.com/BingChaoLiu/DVB-Nexus/issues)。
