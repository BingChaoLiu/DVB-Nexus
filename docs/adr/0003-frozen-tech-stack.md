---
status: accepted
date: 2026-11-14
---

# 技术栈冻结（Python/FastAPI、React+TS、SQLite、TSDuck CLI 子进程、Modular Monolith、188-byte）

**决定**：采纳 ChatGPT v0.4 的全部七条技术选型，作为 MVP 基线冻结：

1. 后端主语言 Python（FastAPI + Pydantic）
2. 前端 React + TypeScript，最小 UI 入 MVP，拓扑画布优先评估 React Flow
3. 本地持久化 SQLite + 文件系统（TS 资产走文件系统 + 元数据表）
4. TSDuck 以 CLI 子进程集成（`asyncio.create_subprocess_exec`，禁 shell=True），不用 binding/ABI
5. 工程形态 Modular Monolith + 独立 Worker Process，不引入消息队列/微服务
6. 自研 Python TS Core 为核心技术资产，TSDuck 只做外部验证（**已由 [ADR-0005](0005-architecture-baseline.md) 修正**：自研收窄为语义层，TSDuck 扩为验证器 + 传输层注入器 + MVP 期生成兜底三重角色）
7. MVP 只生成 188-byte 包长（RS204/M2TS 后置）

**条件**：第 6 条（自研 TS Core）与第 1 条（纯 Python 吞吐）在 map 的"生态与替代方案调研"、"Python 性能可行性调研"两张 research ticket 复核后才算最终冻结——若调研推翻自研必要性或 Python 性能不可行，本 ADR 相应条款由新 ADR 取代。

**Considered Options**: TSDuck binding/ABI 集成（拒绝：MVP 阶段引入 ABI 维护成本，Python binding 覆盖不全）；微服务拆分（拒绝：本地单机工具，调试与复现优先）。
