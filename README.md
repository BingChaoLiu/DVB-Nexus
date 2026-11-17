# DVB-Nexus（DVB 数字沙盘）

简体中文 | [English](docs/user-guide/README.en.md)

DVB 数字沙盘与码流可视化分析平台：集**实时码流排查**与**交互式协议演练**于一体的单机工程平台。MVP 聚焦 TS-first 八步闭环：Create → Generate → Inject → Analyze → Diagnose → Inspect → Recover → Verify；Phase 2 高级封装层已落地——T2-MI 三级封装（T2-MI → BBFrame → Inner TS）与 BISS 加解扰（Mode 1 / Mode E）。

## 📖 使用文档 / Documentation

| 语言 / Language | 入口 / Entry |
|---|---|
| 简体中文 | **[使用文档（快速开始 · 界面导览 · 八步闭环 · 靶场 · FAQ）](docs/user-guide/README.zh-CN.md)** |
| English | **[User Guide (quick start · UI tour · eight-step loop · lab · FAQ)](docs/user-guide/README.en.md)** |

> 使用文档随软件功能迭代逐步完善，两语言内容保持同步更新。
> The user guide evolves with the software; both languages are kept in sync.

## 功能一览 / Highlights

- **拓扑编辑（Topologies）**：React Flow 画布编排 TS 生成器 / 复用器 / 解复用器 / 监测器，及 Phase 2 的 T2-MI 封装器 / 解封装器（三级封装子图），后端校验违规。
- **码流监控（Monitor）**：会话生命周期控制、PID 级指标与告警、根因候选诊断、包检查器下钻原始码流（`view=t2mi|bbframe|ts` 三视图）、Journal 事件尾流（含 gen.*/t2mi.*/bbframe.*/biss.* 构造与封装事件）、TSDuck CLI 调用台。
- **训练靶场（Lab）**：九套预置故障场景（SC-01 ~ SC-09，Lab Pack v1 + v2）、八步 Stepper、提示阶梯、PASS 门控的答案揭示、生成过程只读折叠区。
- **分层流水线**：每层「生成 → 本层故障过滤 → 封装/传递」；T2-MI/BBFRAME/BISS 作用层故障原语与等位替换逐层不变式。
- **BISS 加解扰**：Mode 1（libdvbcsa SSE2 批处理，DLL 缺失显式降级）与 Mode E（ESW + Injected ID 派生 + CISSA 纯 Python）；密钥本体只以指纹痕迹出现在证据面。
- **八步闭环**：全程真实数据与可追溯证据，通关以修复后的新 Run 证据判定。

## 快速开始 / Quick Start

```bash
# 后端 / backend（Python ≥ 3.10）
pip install -e .
pip install "websockets>=14,<16"
DVBNEXUS_DB_PATH="D:/dvbnexus-data/dvbnexus.db" python -m uvicorn bootstrap.asgi:app --port 8765

# 前端 / frontend（Node ≥ 22.12, npm ≥ 11）
cd frontend && npm install && npm run dev   # http://localhost:5173
```

**Windows 一键启动**：双击仓库根目录的 [`start.cmd`](start.cmd)——自动检查依赖、启动后端（127.0.0.1:8765）与前端（固定 127.0.0.1:5188，strictPort，避开易被占用的 5173），服务就绪后自动打开浏览器。重复运行安全（已启动的服务自动跳过）；停止 = 关闭对应服务窗口；自动化场景可 `start.cmd -NoOpen` 跳过开浏览器。

完整步骤见[使用文档](docs/user-guide/README.zh-CN.md) / full steps in the [user guide](docs/user-guide/README.en.md)。

## 编译与构建

本项目是纯 Python 包（setuptools 后端，PEP 517/518 构建，`pyproject.toml` 为唯一配置入口），无二进制编译步骤；"编译"即打包与可编辑安装。

### 环境要求

| 项 | 要求 |
| --- | --- |
| Python | >= 3.10（CI 使用 3.12） |
| Node.js / npm | >= 22.12 / >= 11（仅前端构建需要） |
| 操作系统 | Windows-first（ADR-0004；Linux CI 跑核心组合） |
| 包管理 | pip（setuptools >= 68 自动作为构建后端） |
| websockets（Python 包） | >= 14, < 16（WS 推送必需，见[使用文档 FAQ](docs/user-guide/README.zh-CN.md#9-常见问题faq)） |
| TSDuck（可选） | 本地跑 `tsduck` 标记测试需要 `tsp` CLI；Windows 可 `winget install --id TSDuck.TSDuck` |

### 安装（开发态，推荐）

```bash
python -m venv .venv
source .venv/Scripts/activate       # Git Bash;.venv\Scripts\activate.ps1 / activate.bat
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

- 运行时依赖：`pydantic>=2,<3`、`fastapi>=0.110,<1`、`uvicorn>=0.30,<1`、`pycryptodome>=4.5,<5`（BISS Mode E/CISSA）
- dev 依赖组：`pytest`、`import-linter`、`httpx2`、`pyyaml` 等（测试与契约检查工具链）
- WS 推送（前端实时事件）另需：`python -m pip install "websockets>=14,<16"`

### 前端构建

```bash
cd frontend
npm install                # 依赖安装
npm run build              # 产物输出 dist/（typecheck 与 lint 见 package.json scripts）
npm run preview            # 本地预览构建产物（端口 4173，同带 /api /ws 代理）
```

### 构建分发包

```bash
python -m pip install build
python -m build            # 产出 sdist + wheel 到 dist/
```

## 测试

测试架构见 SPEC-505（`tests/` 四层树 + 严格 marker）。本地默认：

```bash
pytest                                            # 全量（缺 TSDuck 时 tsduck 用例显式 skip）
pytest -m unit                                    # 只跑单元层
pytest -m "(unit or integration or conformance or e2e) and not (tsduck or slow)" -ra   # CI 必绿组合
pytest -m "windows_only or tsduck" -ra            # Windows-first + TSDuck（CI Windows job 同款）
pytest -m slow -ra                                # 慢测试（本地可选，CI 夜间跑）
```

常用 marker：`unit` / `integration` / `conformance` / `e2e` / `slow` / `tsduck` / `windows_only`（全表见 `pyproject.toml` 的 `[tool.pytest.ini_options]`）。

前端测试：

```bash
cd frontend
npm run test:run           # Vitest 组件/单元测试
npm run typecheck          # TypeScript 类型检查
npm run lint               # ESLint
npm run e2e                # Playwright 端到端（构建 + 起后端 + 跑 e2e）
```

## 静态检查（CI 同款）

```bash
lint-imports                     # 模块依赖契约（ADR-0005 decision 4，import-linter）
python -I tools/check_specs.py   # docs/spec/ 规格一致性检查（编辑 spec 后必跑）
```

## 运行 API

单机、单用户、无鉴权（SPEC-500 §3 部署姿态），固定前缀 `/api/v1`：

```bash
# 完整功能栈（业务路由 + WebSocket 推送，生产组装入口）
DVBNEXUS_DB_PATH="D:/dvbnexus-data/dvbnexus.db" python -m uvicorn bootstrap.asgi:app --host 127.0.0.1 --port 8765
curl http://127.0.0.1:8765/api/v1/version

# 应用工厂冒烟（仅版本探针等骨架路由，无业务路由与 WS）
uvicorn --factory api.app:create_app --host 127.0.0.1 --port 8000
```

环境变量契约与交互式文档（`/docs`）见[使用文档](docs/user-guide/README.zh-CN.md#7-rest-api-与-websocket)。

## 目录结构

```
src/
  api/          FastAPI 层（应用工厂 + 路由 + 错误信封，冻结前缀 /api/v1）
  application/  应用层（唯一可依赖全部包的组合层，禁 import api）
  adapters/     外部适配（TSDuck CLI 子进程、存储）
  domain/       领域模型（observation / diagnosis / topology 等）
  ts/           TS Core：自研 MPEG-TS 语义层核心（Packet/Section/PSI/PCR/Mux/Generator；Phase 2 增 T2-MI/BBFrame/PLP/Inner TS 封装解封装链与 BISS 加解扰 biss/）
  faults/       故障定义与双路由（语义级过滤器 / 传输级 TSDuck inject；Phase 2 四原语按作用层路由）
  simulation/   仿真运行时（L0 State Runtime / L1 TS Runtime / 分层流水线）
  knowledge/    静态参考数据（供诊断解释消费）
  bootstrap/    生产组装根（只向下依赖，无人可反向 import）
frontend/       React 19 + Vite 前端（Topologies / Monitor / Lab 三页）
scenarios/      训练靶场预置场景（SC-01 ~ SC-09：Lab Pack v1 + v2）
tests/          四层测试树（unit / integration / conformance / e2e）+ _support
tools/          golden 向量生成与规格一致性检查脚本
docs/           ADR、规格、测试向量、路线图、使用文档
examples/       示例
```

## CI 一览

| Workflow | 触发 | 内容 |
| --- | --- | --- |
| `tests.yml` | push/PR | Linux：CI 必绿组合；Windows：winget 装 TSDuck + `windows_only or tsduck` 全量 |
| `tests-nightly.yml` | 每日 03:30 UTC | `pytest -m slow` |
| `lint-imports.yml` | push/PR | `lint-imports` 依赖契约 |
| `check-specs.yml` | push/PR | `python -I tools/check_specs.py` |
| `frontend.yml` | push/PR | 前端 typecheck / lint / vitest / 构建 |

## 文档地图 / Docs Map

| 路径 / Path | 内容 / Content |
|---|---|
| [`docs/user-guide/README.zh-CN.md`](docs/user-guide/README.zh-CN.md) | 使用文档（中文）/ user guide (Chinese) |
| [`docs/user-guide/README.en.md`](docs/user-guide/README.en.md) | 使用文档（English）/ user guide (English) |
| [`CONTEXT.md`](CONTEXT.md) | 领域词汇权威来源 / authoritative domain glossary |
| [`docs/adr/`](docs/adr/) | 架构决策记录 / architecture decision records |
| [`docs/roadmap.md`](docs/roadmap.md) | MVP 之外的远期路线图 / post-MVP roadmap |
| [`docs/spec/`](docs/spec/) | 规格参考底稿（只读）/ spec reference archive (read-only) |

## 项目状态 / Status

MVP（TS-first 八步闭环）与 Phase 2 高级封装层（T2-MI 三级封装、BBFrame/PLP、BISS Mode 1 / Mode E、分层流水线、Lab Pack v2）均已实现（2026-11-17）；沙盘模式为单机单用户、无认证，生成档为 `analysis_only`（结构合规可分析，不承诺可播放）。远期规划（RF/SEC 沙盘、Live Mode、Time Machine 等）见 [roadmap](docs/roadmap.md)。
