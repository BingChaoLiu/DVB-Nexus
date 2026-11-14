---
spec_id: SPEC-308
title: TSDuck Adapter
version: 0.5.0
status: APPROVED
phase: MVP
owner: Platform
priority: P0
depends_on: [SPEC-503, SPEC-500]
requirements: [REQ-TSK-308-001, REQ-TSK-308-002, REQ-TSK-308-003, REQ-TSK-308-004, REQ-TSK-308-005, REQ-TSK-308-006]
---

# SPEC-308 — TSDuck Adapter

## 1. 目标

TSDuck CLI 子进程的统一封装——**不让 TSDuck 成为后端的黑盒**（chatgpt-v04 §7）。接口面 = 三操作 + 进程管理（[ADR-0005](../../../../adr/0005-architecture-baseline.md) 第 6 条裁决）；MVP **只启用 analyze**：inject（传输级故障路由）与 generate（生成兜底）接口预留不启用（CONTEXT.md 故障双路由：MVP 只启用语义级）。

## 2. 范围

### 2.1 In Scope

- 五模块结构与公开接口。
- 白名单 argv 构建与命令可见性。
- JSON 内容门、报告归一化、日志采集。
- 超时/取消/进程树清理与并发控制。
- 版本检测与调用记录。

### 2.2 Out of Scope

- 语义级故障注入（自研流式过滤器，SPEC-204/ADR-0007）。
- 分析触发的业务编排（Application 层；本模块只暴露操作）。
- 报告内容的诊断解释（SPEC-306 只消费观测事件）。
- generate/inject 的启用策略（归 golden streams 与 conformance 策略票据 [#14](https://github.com/BingChaoLiu/DVB-Nexus/issues/14)）。

## 3. 五模块结构（ADR-0005 §6 定死）

建议 `app/adapters/tsduck/`：

| 模块 | 职责 |
|---|---|
| `process.py` | spawn（`asyncio.create_subprocess_exec`）/ 超时 / cancel / **进程组清理**（Windows 无孤儿进程） |
| `client.py` | 三操作编排 |
| `command_builder.py` | **白名单 argv** 构建 |
| `report_parser.py` | JSON → `AnalysisReport` 归一化 |
| `version.py` | `tsp --version` 正则提取并缓存；可执行文件 PATH 优先 + fallback 探测 |

## 4. 公开接口

```python
class TSDuckClient(Protocol):
    async def get_version(self) -> TSDuckVersion: ...
    async def analyze(self, artifact_id: str) -> AnalysisResult: ...    # MVP 唯一启用
    async def inject(self, spec: InjectSpec) -> InjectResult: ...       # 预留：MVP 调用即 NotEnabled 拒绝
    async def generate(self, spec: GenerateSpec) -> GenerateResult: ... # 预留（使用策略归 #14）
```

- `analyze(artifact_id)`：经 SPEC-503 读取输入 TS，执行 `tsanalyze --json`，产出归一化报告 + 日志。
- 预留操作不实现逻辑，只签名 + 显式拒绝（防静默半实现）。

## 5. 白名单 argv

- MVP 白名单（[#4](https://github.com/BingChaoLiu/DVB-Nexus/issues/4) 实测插件集 + #3 golden 链路）：`fuzz / craft / filter / slice / pcredit / inject / null / file` + 生成链 `tsxml / tstabcomp / tsp`。
- 用户配置**不得直通**任意 CLI 插件；白名单外插件一律拒绝（`TSDUCK_PLUGIN_NOT_ALLOWED`）。
- **参数数组启动、禁 `shell=True`**（ADR-0003 第 4 条）；每次调用记录完整 argv（§7 调用记录）——命令可见性是本模块的存在理由之一。

## 6. 触发模型（ticket #13 Q-D-①）

- **自动**：Application 层 run 完成后对 baseline 与 faulted 产物各执行一次 analyze（八步闭环 Analyze 步，ADR-0002）。
- **显式**：`POST /api/v1/artifacts/{id}/analyze`（SPEC-500 §4.6）幂等重分析——每次产生**新** report artifact，不改写旧报告。
- 分析输入 = baseline（kind=generated_ts）或 faulted（kind=faulted_ts）产物；分析范围不限于 run 产物（任意 TS artifact 可显式分析）。

## 7. 调用记录与环境事实

每次调用记录（SPEC-001 §7 义务）：**版本 / 可执行路径 / argv / 起止时间 / 退出码 / stdout / stderr / 输入 Artifact SHA-256**，关联 `run_id`（有则填）。

环境事实直接进契约（[TSDuck Windows 环境验证 #3](https://github.com/BingChaoLiu/DVB-Nexus/issues/3)）：

- **exit 0 ≠ 内容有效**：JSON 内容门 `ts.bytes > 0 && ts.services.total >= 1`，门失败即 `TSDUCK_JSON_GATE_FAILED`（垃圾输入也 exit 0 的实测结论）。
- stderr 为 **GBK 本地化输出**：只做日志展示，**不做语义解析**。
- 注入环境变量 `TSDUCK_NO_VERSION_CHECK=1`。

## 8. 输出边界（ticket #13 Q-D-②）

- **归一化报告**：`AnalysisReport` → kind=report artifact（SPEC-503 协议落盘 + SPEC-502 索引）。
- **观测事件**：报告异常发现映射到**已注册事件类型**（SPEC-301 §4 `ts.*` 家族），`source=tsduck, confidence=parsed`（CONTEXT.md 禁标 measured）；**未映射发现只留在 report artifact，不造新事件类型**——扩注册表须走 SPEC-301 §4 兼容评审。
- **指标**：汇总指标（per-service/PID bitrate、packet counts）进 SPEC-302（`quality=valid`）。
- **CLI 日志**：stdout/stderr → kind=log artifact，供 CLI Console（SPEC-405）展示**来源标识**（真实 TSDuck 输出 vs 模拟日志，禁混标）。

## 9. 并发、超时与错误

- 并发：信号量限并发（默认 1，可配置，随 OPEN-006 定档 [#16](https://github.com/BingChaoLiu/DVB-Nexus/issues/16) 复核）；排队 FIFO。
- 超时：默认 120s（可配置）→ kill **进程树** → `TSDUCK_TIMEOUT`；partial 日志 artifact 保留（排查依据）。
- 取消：session dispose / 用户取消 → 进程组 kill → `TSDUCK_CANCELLED`。

| 错误码 | 场景 | HTTP 映射（SPEC-500 §6） |
|---|---|---|
| `TSDUCK_NOT_FOUND` | PATH 与 fallback 探测均失败 | 503（服务未就绪） |
| `TSDUCK_VERSION_UNSUPPORTED` | 版本低于最低基线（3.40，#3 实测版本） | 503 |
| `TSDUCK_SPAWN_FAILED` | 进程启动失败 | 500 |
| `TSDUCK_TIMEOUT` | 超时 kill | 500 |
| `TSDUCK_CANCELLED` | 用户/dispose 取消 | 409 |
| `TSDUCK_JSON_GATE_FAILED` | exit 0 但内容门不过 | 500 |
| `TSDUCK_PLUGIN_NOT_ALLOWED` | 白名单外插件 | 422 |

## 10. 测试规格

- 版本探测：PATH 命中 / fallback / 双失败三路径。
- 内容门：合法 JSON / 空 bytes / 零 services / 非 JSON 输出四态。
- 白名单：合法插件通过、白名单外拒绝、argv 数组无 shell 拼接。
- 超时/取消：进程树清理后无孤儿（Windows 进程断言）。
- 调用记录完整性九字段断言；GBK stderr 只入日志不进解析路径。
- 报告归一化 round-trip 与观测事件 `source/confidence` 标记断言。

## 11. 验收标准

- `REQ-TSK-308-001`：三操作接口 + 五模块结构落地；预留操作显式拒绝。
- `REQ-TSK-308-002`：白名单 argv 生效，调用记录九字段完整关联 run_id。
- `REQ-TSK-308-003`：JSON 内容门拦截无效输出（exit 0 ≠ 有效）。
- `REQ-TSK-308-004`：观测/指标输出 source=tsduck、confidence=parsed，未映射发现不进事件流。
- `REQ-TSK-308-005`：超时/取消完成进程树清理，无孤儿进程。
- `REQ-TSK-308-006`：错误码族与 HTTP 映射一致（§9 表）。

## 12. 非目标与风险

- 不实现 inject/generate 逻辑（接口预留）；不做 TSDuck 版本自动升级；不做远程 TSDuck。
- 不承诺 TSDuck 输出为绝对真值（CONTEXT.md 既有禁令）；双解析器对照（ANALYZER_DISAGREEMENT）归 SPEC-309（P1）。
- 风险：TSDuck 版本升级改变 JSON 报告结构——report_parser 按 schema_version 防御 + 契约测试锁样例。

## 13. 交付要求

建议文件：`app/adapters/tsduck/`（五模块，§3 表）；集成测试与 SPEC-203（tee 双写产物分析）、SPEC-505 共享 fixture；#3 实测命令样例进测试资产。

## 14. 参考

- [ADR-0005](../../../../adr/0005-architecture-baseline.md) 第 3/6 条（三重角色、三操作五模块）、[ADR-0007](../../../../adr/0007-fault-injection-pipeline-contract.md)（双路由——语义级归自研过滤器）。
- SPEC-500 §4.6/§6（analyze 端点与错误映射）、SPEC-503（落盘协议）、SPEC-502（索引）、SPEC-302（指标）。
- chatgpt-v04 §7（Adapter 设计底稿：独立进程四理由、asyncio 子进程纪律）。
- 调研底档：TSDuck Windows 环境验证（[#3](https://github.com/BingChaoLiu/DVB-Nexus/issues/3)）、生态与替代方案（[#4](https://github.com/BingChaoLiu/DVB-Nexus/issues/4)）。
