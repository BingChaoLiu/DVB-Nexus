# tests/ — 测试架构（SPEC-505，ticket #22）

本目录是 SPEC-505 Test Architecture 0.5.0 的工程落地。规格权威：
`docs/spec/DVB-Sandbox-Spec-v0.4-Complete/docs/modules/Platform/SPEC-505-test-architecture.md`。

## 1. 四层目录（SPEC-505 §3）

| 层 | 目录 | 内容 | I/O | marker |
|---|---|---|---|---|
| Unit | `tests/unit/` | 纯函数、编解码、CRC、时钟、状态转换 | 无 I/O、无墙钟 | `unit` |
| Integration | `tests/integration/` | Generator/TSRuntime、fault 过滤器 tee 双写、SPEC-502/503、TSDuck Adapter（真实子进程） | 真实/临时资源 | `integration` |
| Conformance | `tests/conformance/` | 加载 SPEC-506 已登记向量断言 | 只读向量 | `conformance` |
| Scenario/E2E | `tests/e2e/` | 八步闭环 API 级（ADR-0002）：create → generate → inject → analyze → diagnose → inspect → recover → verify，REST + WS 真链路 | 全栈 | `e2e` |

分层互斥纪律（SPEC-505 §8）：

- **目录是分层事实源**。根 `conftest.py` 在收集期把目录对应的 layer marker
  注入每个测试；测试代码显式标注了与所在目录**矛盾**的 layer marker
  （例如 `tests/unit/` 里标注 `integration`）视为结构违规，收集期硬失败。
- unit 层出现 I/O 即结构违规：unit 测试不请求 `tmp_path` / `monkeypatch`
  等资源类 fixture，不落盘、不起子进程、不碰墙钟。

**可执行强制**（SPEC-505 §8，review-fix #6）：`tests/_support/io_rules.py`
AST 检测器（风格与 data_rules 一致：违规形态、`io-ok:` 逐行豁免、保守
启发式边界），由 `tests/integration/test_unit_io_rules.py` 在必绿组合中
扫描整个 `tests/unit/` 树执行。

- 标记为违规的形态：资源类 fixture 形参（`tmp_path` / `tmp_path_factory`
  / `tmpdir` / `monkeypatch`；`caplog`/`capsys` 捕获类不算资源 I/O）；
  内建 `open()`；Path 式落盘/探测方法（`write_text`/`unlink`/`exists`
  等；纯规范化 `resolve` 不算）；`os.<io>` 调用（文件增删改、列举、
  `system`/`popen`/exec/spawn 族；`os.path` 纯运算不算）；I/O 模块导入
  与裸名调用（subprocess/shutil/tempfile/socket/httpx/requests/urllib/
  ftplib/smtplib）；首参为非 `:memory:` 字符串常量的 `connect(...)`。
- 放行的既有姿态：内存态 SQLite（`:memory:`，无文件 I/O——unit 层
  journal/repository 切片的既定形态）、Path 值对象构造、`importlib`
  进程内导入。
- 豁免机制：行尾注释 `# io-ok: <理由>` 逐行豁免（豁免面为零是常态目标，
  出现即 review 关注点）。动态参数的 `connect(path)` 逃逸启发式（保守
  边界，同 data_rules 阈值哲学）。
- 墙钟断言归确定性纪律（§5/§8 确定性项），不在本检测器范围。

## 2. markers（SPEC-505 §5，全部 strict 注册于 pyproject）

| marker | 语义 | CI 策略 |
|---|---|---|
| `unit` / `integration` / `conformance` / `e2e` | 四层（目录注入 + 矛盾硬失败） | **必绿组合**：CI PR 门 `pytest -m "(unit or integration or conformance or e2e) and not (tsduck or slow)"` |
| `slow` | 慢测试 | 本地默认跑；CI 夜间 workflow `pytest -m slow` |
| `tsduck` | 需要 TSDuck CLI（SPEC-308） | CI 主路径 Windows runner 安装 TSDuck 后全量跑（安装失败 = CI 失败，#14）；ubuntu PR 门排除；本地缺失 → `tsduck` fixture 显式 skip（理由可见，禁静默跳过） |
| `windows_only` | Windows-first 断言（ADR-0004：路径分隔、GBK stderr、进程树清理） | 非 Windows 平台显式 skip（守卫 fixture 给出理由）；Windows CI 必跑 |

未注册 marker 一律 collection 硬失败（`--strict-markers`）。skip 理由经
`-ra`（全局 addopts）在测试摘要中显式可见。

## 3. CI 门（SPEC-505 §5、#13、#14）

- `.github/workflows/tests.yml`
  - `pytest-core`（ubuntu，Python 3.12）：必绿组合 = unit + integration +
    conformance + e2e（排除 `tsduck`）。
  - `pytest-windows-first`（windows-latest，Python 3.12）：winget 安装
    TSDuck（`TSDuck.TSDuck`，失败即 job 失败）→ `tsp --version` 记录日志 →
    `pytest -m "windows_only or tsduck"`。
- `.github/workflows/tests-nightly.yml`（scheduled）：`pytest -m slow`。
- 本地裸 `pytest`：全量收集（含 slow），testpaths 锁定 `tests/`。

## 4. 核心 fixture 六件（SPEC-505 §4，定义于 `tests/conftest.py`）

| fixture | 提供物 | 服务规格 | 备注 |
|---|---|---|---|
| `journal` | tmp SQLite 文件库 + WAL/foreign_keys pragma 策略 + 编号 `.sql` 迁移 applier | SPEC-502 | "tmp SQLite + 迁移后库（或内存实现，二选一实现期定）" → 选文件库：WAL 与迁移语义只在文件库可验 |
| `artifact_store` | tmp root（`artifacts/` + `tmp/` 骨架）+ 内容寻址路径助手 | SPEC-503 | `<root>/artifacts/<sha256[:2]>/<sha256>.<ext>` |
| `tsduck` | 可用性探测（PATH + `DVB_NEXUS_TSP_PATH` 覆盖），缺失 → 显式 skip | SPEC-308 | 探测结果不可变缓存，报告显式可见 |
| `session_run` | 确定性 session/run 工厂（固定 seed、SPEC-201 frozen clock config） | SPEC-200/203 | 同 seed ⇒ 同 id/配置；每次调用产生新不可变对象 |
| `golden_loader` | 按 SPEC-506 §4 登记格式加载向量 + expectations（sha256 校验、三件套完整性） | SPEC-506 | 默认根 `docs/test-vectors/golden/`（#14 Q4），参数可覆盖 |
| `api_client` | FastAPI test client 工厂 + Pydantic DTO round-trip 断言 | SPEC-500 | 工厂式：测试传入 ASGI app；SPEC-500 实现票落地后派生默认 client fixture |

fixture 间不隐式共享可变状态；每个测试自建 tmp 资源（fixture 均为
function scope，探测结果为不可变缓存）。

## 5. 测试数据纪律 —— 禁手拼字节（可执行规则集，SPEC-505 §6 + #14 裁决延伸）

**规则**：测试中的 TS/位级字节只允许来自以下三类来源，**禁止在测试代码里
手拼字节字面量**：

1. **SPEC-506 登记 golden**——经 `golden_loader` 从
   `docs/test-vectors/golden/` 加载（sha256 校验强制）；
2. **确定性场景生成器**——固定 seed 经 `tests/_support/deterministic.py`
   程序化构造（同 seed + 同参数 ⇒ 同字节）；
3. **入库资产**——以文件形式 checked-in 的资产（golden 三件套、
   `tests/data/` 下的样本），逐资产注明来源与登记锚点。

**可执行强制**（`tests/_support/data_rules.py`，由
`tests/integration/test_test_data_tree_rules.py` 在必绿组合中扫描整个
`tests/` 树执行）：

- 标记为违规的形态：
  - 内容长度 > `MAX_BYTES_LITERAL`（默认 16 字节）的 bytes 字面量；
  - `bytes([...])` / `bytearray([...])` 且元素数 ≥ `MIN_INT_LIST`（默认 16）；
  - `bytes.fromhex("…")` 且 hex 长度 ≥ `MIN_HEX_CHARS`（默认 32，即 ≥16 字节）。
- 豁免机制：行尾注释 `# testdata-ok: <理由>` 逐行豁免；豁免必须写明理由
  （豁免面为零是常态目标，出现即 review 关注点）。
- `tests/_support/` 本身不参与扫描——它是获准的**程序化构造器区**（规则
  来源 2 的实现地）；其自身正确性由 unit 层测试约束。
- 阈值为保守启发式常量（模块顶部可调）；上调阈值须在 PR 中说明。

**目录组织**：

- `tests/data/` — 静态测试数据根（checked-in 资产）。
  - `tests/data/malformed/` — 畸形输入集（#14：不入 golden，expectations
    只承载正向断言；畸形资产注明来源与构造方式，unit 层消费）。
- `docs/test-vectors/golden/` — SPEC-506 登记 golden（仓库级，#14 Q4）；
  tests/ 经 `golden_loader` 只读消费，tests/ 内不复制 golden 字节。

**断言时钟纪律**（SPEC-505 §6）：测试断言不用墙钟等待——用可控时钟
（SPEC-201）或事件驱动等待；slow 测试允许长计算但不得 sleep 等真实时序。

## 6. Windows-first 测试基建（ADR-0004）

- 路径：一律 `pathlib` + `tests/_support/paths.py` 派生仓库位置；禁 `/tmp`
  假设；pytest `tmp_path`（Windows 下即真实盘符路径）承载临时资源。
- 编码：所有 `open()`/`read_text()`/`write_text()` 显式 `encoding="utf-8"`。
- 子进程：禁 shell=True（ADR-0003）；`windows_only` 标记的断言（路径分隔、
  GBK stderr、进程树清理）在 Windows CI 必跑，非 Windows 显式 skip 不降级。
- TSDuck stderr 为 GBK 本地化输出：只日志展示、显式 `errors="replace"` 解码，
  不做语义解析（SPEC-308）。
- **实机测试断言形状，禁钉环境字面值**：`tsduck` / `windows_only` 等真环境
  测试断言版本 token 形状（`^\d+\.\d+-\d+$`）且 parsed components 与 raw
  line 自洽、路径形状（`…\TSDuck\bin\tsp.exe`，盘符无关、大小写不敏感）与
  存在性——CI runner 与参考机的安装版本、盘符、盘上 casing 都不同（#69 CI
  首跑：winget 装 3.45-4798 vs 参考机 3.40-4165）。字面钉扎（3.40-4165 等
  锁定基线）只属于单测/fake 的合成 fixture——那里它们是输入数据，不是环境
  假设。

**可执行强制**（`tests/_support/env_rules.py`，由
`tests/integration/test_real_env_rules.py` 在必绿组合中扫描整个 `tests/`
树执行，ticket #70）：

- 扫描面：静态携带真环境 marker（`tsduck` / `windows_only`，模块级
  `pytestmark` 或函数级装饰器均可判读）的测试文件；`tests/_support/`
  本身不参与扫描（获准的构造器区，同 §5 纪律）。
- 标记为违规的形态（仅编译期 str 常量，docstring 豁免）：
  - `env_version_literal`——版本 token 形状（`\d+\.\d+-\d+`）出现在
    `==`/`!=`/`in`/`not in` 比较中（长文本包含也算：#69 噪声行类）；
  - `env_drive_path_literal`——盘符绝对路径（`[A-Za-z]:[\/]`）出现在
    任意上下文（fixture 都在 `tmp_path`，盘符字面必是钉扎）；
  - `env_executable_name_comparison`——可执行后缀文件名字面（
    `.exe`/`.cmd`/`.bat`/`.ps1`/`.dll`/`.com`）做大小写敏感比较；比较双
    方任一侧调用 `lower()`/`upper()`/`casefold()` 即为 §6 形状断言形态，
    豁免；字面-字面比较（两侧均为常量的合成自洽）亦豁免。数据文件后缀
    （golden/资产名）是合成 fixture 锚点，不扫。
- 注意：带 marker 的 fake/合成文件（如 `test_probe_fakes.py`，模块级
  `windows_only`）**同样入扫**——其中的裸版本字面也须改用派生/named
  常量承载（§6「字面钉扎只属于合成 fixture」的合成锚点在扫面内以
  派生形式表达，见 fakes 的 `extract_version(CANONICAL_VERSION_LINE)`
  先例）。
- 豁免机制：行尾/邻行注释 `# env-ok: <理由>` 逐行豁免（同 §5 窗口纪律）；
  **豁免面为零是常态目标**——零豁免本身有机械审计（同 gate 文件），
  出现即 review 关注点。
- 形状为保守启发式常量（模块顶部可调）；收紧/放宽须在 PR 中说明。已
  知保守边界：f-string 内嵌常量、命名常量比较、整数组件钉扎、赋值位
  字面不在扫描形状内（review 可见性靠人读，机械面故意保守）。

## 7. 常用命令

```bash
# 全量（本地默认，含 slow）
pytest
# CI 必绿组合（同 ubuntu PR 门；slow 归夜间、tsduck 归 Windows TSDuck job）
pytest -m "(unit or integration or conformance or e2e) and not (tsduck or slow)"
# Windows-first + TSDuck（Windows runner 形态）
pytest -m "windows_only or tsduck"
# 夜间（slow）
pytest -m slow
# 依赖边界门（与测试门并行，ADR-0005 D4）
lint-imports
```

## 8. 备注

- 规则集落点：SPEC-505 未指定测试数据纪律文档的文件位置，本 README 为
  实现选择（假设，报告记录）。
- `tests/_support/` 以 `tests.` 包前缀导入（pyproject `pythonpath` 提供
  rootdir）；测试文件全树唯一命名 + 包限定收集，杜绝同名冲突。
