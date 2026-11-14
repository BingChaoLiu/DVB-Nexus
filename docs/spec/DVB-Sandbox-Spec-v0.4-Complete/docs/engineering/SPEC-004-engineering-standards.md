---
spec_id: SPEC-004
title: Engineering and Quality Standards
version: 0.4.0
status: DRAFT
phase: BASELINE
owner: Engineering
depends_on:
  - SPEC-001
  - SPEC-003
---

# SPEC-004 — 工程开发与质量规范

## 1. 目标

建立跨 Agent 一致的代码风格、模块边界、异常处理、日志、测试和交付标准。具体工具版本在项目初始化时写入锁定文件，不在本 Spec 中虚构版本号。

## 2. 技术约定

### 后端

- 主语言：Python（已确认方向）。
- 类型注解：公共接口和核心数据模型必须提供完整类型注解。
- 数据模型：优先使用明确的 dataclass / Pydantic Model；避免无约束的 `dict[str, Any]` 穿透多个模块。
- 异步：I/O-bound API 和 Worker 协作用 async；CPU-heavy 长任务需评估独立进程，禁止阻塞 API Event Loop。
- 依赖：使用项目统一依赖管理和 lock 文件；Agent 不得未经批准新增运行时依赖。
- 框架：FastAPI 为建议项，待 ADR 批准后冻结。

### 前端

- React + TypeScript 为建议项，待 SPEC-400 批准。
- TS 严格类型；网络 DTO 与 UI ViewModel 分离。
- 前端仅负责呈现和交互，不成为协议校验/拓扑求值的权威实现。

## 3. 模块设计原则

- 依赖方向从 API/Application 指向 Domain/Ports，再由 Adapter 实现 Ports。
- `ts` 不得依赖 FastAPI、React、SQLite 或 TSDuck。
- `diagnosis` 不得直接启动 TSDuck 或打开 Artifact 文件；通过 Observation/Repository 接口消费数据。
- `faults` 不得直接修改 UI Node Health；必须改变受控数据或状态模型并产出事件/证据。
- 外部进程和文件系统访问集中在 Adapter/Infrastructure。
- 避免循环依赖；发现循环依赖必须调整边界，不能通过局部 import hack 掩盖。

## 4. 命名与格式

- Python：遵循 PEP 8；函数/变量 `snake_case`，类 `PascalCase`，常量 `UPPER_SNAKE_CASE`。
- 公共类、函数和非显然算法必须有 docstring。
- 协议字段名在代码中优先使用标准字段英文名称，并在注释/文档解释单位和语义。
- PID、长度、时钟计数等字段必须明确 bit width、范围和单位。
- 不用模糊的 `time` 字段；区分 wall-clock、simulation clock、PCR/PTS 时基。

## 5. 错误处理

- 不允许吞异常后继续返回看似成功的默认值。
- 对外错误需有稳定错误码、可读消息和可选上下文。
- 解析不可信 TS 输入时，所有长度、偏移、表计数和分片边界必须先验证再访问。
- 对畸形输入要定义 reject / skip / recover 策略，不得由实现者自行选择而不记录。
- 不在错误信息或日志中输出未来密钥类数据。

## 6. 日志与可观测性

- 使用结构化日志；必须可关联 `session_id`、`run_id`、`task_id`（适用时）。
- 记录 Worker 启停、退出码、耗时、超时、取消和错误摘要。
- 大块 TS Payload 不直接写入常规日志；通过 Artifact/Evidence 引用。
- 诊断信息必须能追溯到 Observation ID 或 Artifact。
- 模拟输出和真实工具输出必须明显标识。

## 7. 测试规范

### 测试分层

1. Unit：纯函数、Packet 编解码、CRC、时钟、状态转换。
2. Integration：TS Generator、Fault Injector、Storage、TSDuck Worker。
3. Conformance：标准字段、标准测试向量、边界与畸形数据。
4. Scenario/E2E：创建 Run → 生成 → 注入 → 分析 → 诊断 → 修复验证。

### 必须覆盖的 TS Core 边界

- Packet 长度和 Sync Byte。
- PID/字段位宽和保留值。
- Adaptation Field 长度边界。
- Section 跨 Packet 分片和重组。
- MPEG-2 CRC32。
- CC 的 PID 独立状态、payload/adaptation-only 行为、15→0 回绕、discontinuity indicator 语义。
- PCR 编码、扩展字段、回绕与时钟转换。
- PES PTS/DTS 编码边界。
- 空输入、截断输入、错误同步字节和恶意长度字段。

具体规范性测试向量由 SPEC-506 管理。

## 8. TS 数据实现要求

- MVP 生成标准 188-byte TS Packet；除非批准的 Spec 明确允许，不生成混合包长文件。
- Section、PES 和 TS Packet 是不同抽象层，不把 PSI Section 生成逻辑塞入 TSPacket 类。
- TS Packetizer 负责 Section/PES 到 Packet 的分片和 PUSI 处理。
- CC 不能简单对所有 PID Packet 无条件递增；需遵循 MPEG-TS 连续性规则，并处理 Adaptation Field 与 discontinuity 情形。
- PCR 必须按标准编码在 Adaptation Field 中。
- 不将墙钟直接写入 PCR/PTS。
- `analysis_only` 输出不声称可被播放器解码。

## 9. 第三方工具与子进程

- 通过 `asyncio.create_subprocess_exec` 或等效安全 API 使用参数数组。
- 禁止 `shell=True` 和字符串拼接 shell 命令。
- 读取 stdout/stderr 必须防止 pipe 填满导致死锁。
- 要求 timeout、取消、进程树清理、输出大小限制和错误退出码处理。
- 可执行文件路径和插件必须来自配置/白名单，不接受不可信任的任意参数。

## 10. 代码审查与合并

每个 PR/MR 至少检查：

- 对应 Approved Spec 和 Requirement ID。
- 修改文件是否在 Task Allowlist 中。
- 是否引入接口/数据模型偏差。
- 单测/集成测试是否执行。
- 是否更新测试向量、文档和 Spec Index。
- 是否存在资源泄漏、阻塞、未处理异常和安全问题。

## 11. Definition of Done

一个任务只有同时满足以下条件才可标记完成：

- 所有任务范围内需求均实现，或明确记录未实现项。
- 所有 Acceptance Criteria 有测试证据。
- 测试通过；跳过项有理由和批准。
- 无未批准的公共接口/依赖/架构变化。
- 代码格式、静态检查和类型检查通过（项目启用的检查项）。
- 更新实现报告、模块状态和 Spec Index。
- 已知问题、限制和后续工作已记录。
