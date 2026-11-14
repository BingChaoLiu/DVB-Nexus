---
spec_id: SPEC-505
title: Test Architecture
version: 0.5.0
status: APPROVED
phase: MVP
owner: Platform
priority: P0
depends_on: [SPEC-004]
requirements: [REQ-TST-505-001, REQ-TST-505-002, REQ-TST-505-003, REQ-TST-505-004, REQ-TST-505-005]
---

# SPEC-505 — Test Architecture

## 1. 目标

四层测试（SPEC-004 §7 既有分层）的工程落地契约：pytest 分层、fixture、标记与 CI 门、测试数据组织。本规格不发明新分层，只把 SPEC-004 的测试规范工程化。

## 2. 范围

### 2.1 In Scope

- 四层目录结构与 pytest markers。
- 核心 fixture 清单。
- CI 门与 skip 纪律。
- 测试数据来源纪律。

### 2.2 Out of Scope

- 具体测试向量与 golden 内容（SPEC-506 / golden streams 票 [#14](https://github.com/BingChaoLiu/DVB-Nexus/issues/14)）。
- 前端测试（SPEC-400 系批准时定义）。
- 性能基准测试（SPEC-507，P1；口径权威：[ADR-0008](../../../../adr/0008-mvp-performance-envelope.md)，随 OPEN-006 定档 [#16](https://github.com/BingChaoLiu/DVB-Nexus/issues/16) 冻结）。

## 3. 四层与目录

| 层 | 目录 | 内容 | I/O |
|---|---|---|---|
| Unit | `tests/unit/` | 纯函数、编解码、CRC、时钟、状态转换 | 无 I/O、无墙钟 |
| Integration | `tests/integration/` | Generator/TSRuntime、fault 过滤器 tee 双写、SPEC-502/503、TSDuck Adapter（真实子进程） | 真实/临时资源 |
| Conformance | `tests/conformance/` | 加载 SPEC-506 已登记向量断言 | 只读向量 |
| Scenario/E2E | `tests/e2e/` | **八步闭环 API 级**（ADR-0002）：create → generate → inject → analyze → diagnose → inspect → recover → verify，走 REST + WS 真链路 | 全栈 |

## 4. 核心 fixture（ticket #13 Q-E-①）

| fixture | 提供物 | 服务规格 |
|---|---|---|
| `journal` | tmp SQLite + 迁移后库（或内存实现，二选一实现期定） | SPEC-502 |
| `artifact_store` | tmp root + 索引库 | SPEC-503 |
| `tsduck` | 可用性探测：缺失 → `tsduck` 标记测试 skip，**报告显式可见** | SPEC-308 |
| `session_run` | 确定性 session/run factory（固定 seed、clock config） | SPEC-200/203 |
| `golden_loader` | 按 SPEC-506 manifest 登记格式加载向量与 expectations | SPEC-506 |
| `api_client` | FastAPI test client + DTO round-trip 断言 | SPEC-500 |

fixture 间不隐式共享可变状态；每个测试自建 tmp 资源。

## 5. 标记与 CI 门

- markers：`unit / integration / conformance / e2e / slow / tsduck / windows_only`。
- **CI 必绿 = unit + integration + conformance + e2e**；skip 必须有理由并在报告中显式可见（禁静默跳过，SPEC-004 §5 既有纪律）。
- `slow` 默认本地跑、CI 夜间跑；`windows_only` 在 Windows CI 必跑（ADR-0004：Windows 优先——路径分隔、GBK stderr、进程树清理断言不得在非 Windows 平台静默降级）。
- import-linter 边界契约作为门禁一部分（ADR-0005 决策 4 依赖规则）。

## 6. 测试数据纪律

- 静态数据入 `tests/data/`；TS 字节一律来自 SPEC-506 登记 golden 或**确定性场景生成器**（固定 seed），**禁手拼字节**。
- 测试断言不用墙钟等待（用 SPEC-201 可控时钟或事件驱动等待）。
- TSDuck 输出样例以 #3 实测资产为基准（`docs/research/`），不凭记忆编造 CLI 行为。

## 7. 错误处理

- fixture 初始化失败 = 测试失败（不降级跳过），除非命中显式 skip 条件（TSDuck 缺失）。
- 并发测试使用受控时钟与队列边界注入，不依赖真实时序。

## 8. 测试规格

- 分层互斥：unit 层出现 I/O 即结构违规。
- markers 声明完备性检查（无未登记 marker）。
- fixture 隔离：并行执行无串扰。
- 确定性：同 seed 两次全绿（无墙钟依赖断言）。

## 9. 验收标准

- `REQ-TST-505-001`：四层目录 + markers 落地，CI 门组合生效。
- `REQ-TST-505-002`：核心 fixture 六件齐备并与服务规格对齐。
- `REQ-TST-505-003`：skip 显式纪律与 tsduck 探测行为符合 §5。
- `REQ-TST-505-004`：测试数据来源纪律生效（无手拼 TS 字节）。
- `REQ-TST-505-005`：Windows-first 断言在 Windows CI 必跑。

## 10. 非目标与风险

- 不做覆盖率数字目标（SPEC-004 DoD 以 AC 测试证据为准）；不做变异测试。
- 风险：e2e 全栈测试时长膨胀——`slow` 标记 + 夜间跑控制；fixture 漂移随规格修订同步更新。

## 11. 交付要求

建议文件：`tests/`（四层目录 + `conftest.py` fixture 六件 + `pytest.ini` markers）；与 SPEC-506 golden loader 共享 `tests/data/`。

## 12. 参考

- SPEC-004 §7/§10/§11（测试规范、代码审查、DoD）。
- SPEC-506（向量管理机制）、SPEC-200/203/204（集成测试对象）、SPEC-500/501（e2e 链路）。
- [ADR-0004](../../../../adr/0004-windows-first-runtime.md)（Windows 优先）、[ADR-0005](../../../../adr/0005-architecture-baseline.md) 决策 4（import-linter）。
