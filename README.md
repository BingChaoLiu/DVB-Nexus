# DVB-Nexus(DVB 数字沙盘)

DVB 数字沙盘与码流可视化分析平台:集"实时码流排查"与"交互式协议演练"于一体的单机工程平台。MVP 聚焦 TS-first 八步闭环:Create → Generate → Inject → Analyze → Diagnose → Inspect → Recover → Verify。

- 领域术语权威词汇表:[CONTEXT.md](CONTEXT.md)
- 架构决策记录:[docs/adr/](docs/adr/)(ADR-0001 ~ ADR-0009)
- 规格底稿:[docs/spec/](docs/spec/)

## 编译与构建

本项目是纯 Python 包(setuptools 后端,PEP 517/518 构建,`pyproject.toml` 为唯一配置入口),无二进制编译步骤;"编译"即打包与可编辑安装。

### 环境要求

| 项 | 要求 |
| --- | --- |
| Python | >= 3.10(CI 使用 3.12) |
| 操作系统 | Windows-first(ADR-0004;Linux CI 跑核心组合) |
| 包管理 | pip(setuptools >= 68 自动作为构建后端) |
| TSDuck(可选) | 本地跑 `tsduck` 标记测试需要 `tsp` CLI;Windows 可 `winget install --id TSDuck.TSDuck` |

### 安装(开发态,推荐)

```bash
python -m venv .venv
source .venv/Scripts/activate       # Git Bash;.venv\Scripts\activate.ps1 / activate.bat
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

- 运行时依赖:`pydantic>=2,<3`、`fastapi>=0.110,<1`、`uvicorn>=0.30,<1`
- dev 依赖组:`pytest`、`import-linter`、`httpx2`、`pyyaml` 等(测试与契约检查工具链)

### 构建分发包

```bash
python -m pip install build
python -m build            # 产出 sdist + wheel 到 dist/
```

## 测试

测试架构见 SPEC-505(`tests/` 四层树 + 严格 marker)。本地默认:

```bash
pytest                                            # 全量(缺 TSDuck 时 tsduck 用例显式 skip)
pytest -m unit                                    # 只跑单元层
pytest -m "(unit or integration or conformance or e2e) and not (tsduck or slow)" -ra   # CI 必绿组合
pytest -m "windows_only or tsduck" -ra            # Windows-first + TSDuck(CI Windows job 同款)
pytest -m slow -ra                                # 慢测试(本地可选,CI 夜间跑)
```

常用 marker:`unit` / `integration` / `conformance` / `e2e` / `slow` / `tsduck` / `windows_only`(全表见 `pyproject.toml` 的 `[tool.pytest.ini_options]`)。

## 静态检查(CI 同款)

```bash
lint-imports                     # 模块依赖契约(ADR-0005 decision 4,import-linter)
python -I tools/check_specs.py   # docs/spec/ 规格一致性检查(编辑 spec 后必跑)
```

## 运行 API

单机、单用户、无鉴权(SPEC-500 §3 部署姿态),固定前缀 `/api/v1`:

```bash
uvicorn --factory api.app:create_app --host 127.0.0.1 --port 8000
curl http://127.0.0.1:8000/api/v1/version
```

## 目录结构

```
src/
  api/          FastAPI 层(应用工厂 + 路由 + 错误信封,冻结前缀 /api/v1)
  application/  应用层(唯一可依赖全部包的组合层,禁 import api)
  adapters/     外部适配(TSDuck CLI 子进程、存储)
  domain/       领域模型(observation / diagnosis / topology 等)
  ts/           TS Core:自研 MPEG-TS 语义层核心(Packet/Section/PSI/PCR/Mux/Generator)
  faults/       故障定义与双路由(语义级过滤器 / 传输级 TSDuck inject)
  simulation/   仿真运行时(L0 State Runtime / L1 TS Runtime)
  knowledge/    静态参考数据(供诊断解释消费)
  bootstrap/    生产组装根(只向下依赖,无人可反向 import)
tests/          四层测试树(unit / integration / conformance / e2e)+ _support
tools/          golden 向量生成与规格一致性检查脚本
docs/           ADR、规格、测试向量、路线图
examples/       示例
```

## CI 一览

| Workflow | 触发 | 内容 |
| --- | --- | --- |
| `tests.yml` | push/PR | Linux:CI 必绿组合;Windows:winget 装 TSDuck + `windows_only or tsduck` 全量 |
| `tests-nightly.yml` | 每日 03:30 UTC | `pytest -m slow` |
| `lint-imports.yml` | push/PR | `lint-imports` 依赖契约 |
| `check-specs.yml` | push/PR | `python -I tools/check_specs.py` |
