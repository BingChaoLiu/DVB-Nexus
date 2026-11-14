# TSDuck Spec Index

**Package version:** 0.5.0
**Status:** MVP_BASELINE_APPROVED
**Normative parent:** [ADR-0005](../../../../adr/0005-architecture-baseline.md) 第 3/6 条（三重角色、三操作五模块）；观测标记纪律归 CONTEXT.md（禁标 measured）

[ticket #13 补写批准](https://github.com/BingChaoLiu/DVB-Nexus/issues/13)（2026-11-14）：SPEC-308 接口级成文并批准为 MVP 基线（APPROVED 0.5.0）。

| Spec ID | Document | Depends on | MVP priority | Primary output |
|---|---|---|---|---|
| SPEC-308 | [TSDuck Adapter](SPEC-308-tsduck-adapter.md) | SPEC-503/500 | P0 | 三操作接口、五模块结构、白名单 argv、JSON 内容门、调用记录 |

## 批准要点（详见 spec 与 ticket #13 决议）

- **三操作 + 进程管理**（ADR-0005 §6）：MVP 只启用 analyze；inject/generate 接口预留、显式拒绝（使用策略归 #14）。
- **五模块定死**：process / client / command_builder / report_parser / version（`app/adapters/tsduck/`）。
- **环境事实进契约**（#3 实测）：exit 0 ≠ 有效（JSON 内容门 `ts.bytes > 0 && ts.services.total >= 1`）、stderr GBK 只展示不解析、`TSDUCK_NO_VERSION_CHECK=1`、参数数组禁 shell=True。
- **输出边界**：报告异常发现映射到已注册 `ts.*` 事件类型（`source=tsduck, confidence=parsed`）；未映射发现只留 report artifact，不造新事件类型；CLI 日志供 SPEC-405 来源标识展示。
- 白名单 argv = `fuzz/craft/filter/slice/pcredit/inject/null/file` + 生成链 `tsxml/tstabcomp/tsp`；用户配置不得直通任意插件。
