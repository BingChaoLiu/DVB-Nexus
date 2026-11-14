---
status: accepted
date: 2026-11-14
---

# MVP 第一运行环境为 Windows，代码保持跨平台

开发者当前环境为 Windows（DVB 传统生态主战场是 Linux）。MVP 以 Windows 本机为第一运行/测试环境：TSDuck 用 Windows 构建、路径约定兼容 Windows、CI 可在 Windows runner 上跑；代码不使用 Linux 特化 API（如 DVB frontend ioctl——那属于远期 Live Mode）。

**Consequences**: 未来 Live Mode（依赖 Linux DVB API）落地时需补 Linux 兼容层，属 roadmap 范围；路径/子进程管理从第一天就按跨平台写法实现，避免后补。
