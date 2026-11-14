---
status: accepted
date: 2026-11-14
---

# MVP 收敛为 TS-first 传输层闭环，射频与高级封装延后

项目愿景（v0.3）包含 RF/LNB/DiSEqC 沙盘、T2MI、BISS 等完整 DVB 链路教学；ChatGPT v0.4 建议把 MVP 收敛到传输层八步闭环（Create → Generate → Inject → Analyze → Diagnose → Inspect → Recover → Verify）。

**决定**：接受 TS-first 收敛。MVP 只做 MPEG-TS 传输层闭环（含最小前端 UI）；RF/Unicable、T2MI/BISS/CA、Live Mode、Time Machine 全部移入远期路线，由 `docs/roadmap.md` 承载——v0.3 的故障案例库（A 射频 / B T2MI / C BISS / D SI-PSI 八大案例）与 ChatGPT 包的 SPEC-600+ 目录全部保留在 roadmap 中，保证 MVP 完成后这些 idea 有直接的继续条件。

**Consequences**: MVP 验收不含任何 RF 教学场景；拓扑模型保留 `SignalPlane` 扩展位但 MVP 只启用 `MPEG_TS` 平面；roadmap.md 是远期工作的唯一权威索引。
