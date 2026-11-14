---
status: accepted
date: 2026-11-14
---

# 采用 ChatGPT v0.4 规格包为底稿，治理融合到本仓库流程

项目从一份 ChatGPT 生成的规格包（`DVB-Sandbox-Spec-v0.4-Complete`，69 个文件）起步。经四路独立调研：包内部协议算术全部正确、单模块质量高，但模块间缝合差（编号双轨、事件信封三方冲突、故障管线缺口），且其治理体系（SPEC 状态机、TASK-ID、Allowlist、实施报告模板）与本仓库已有的 wayfinder + GitHub Issues + ADR 流程重叠。

**决定**：该包整体归档为 `docs/spec/` 只读参考底稿，实质内容（ADR 主张、模块边界、工程红线）逐份修订后批准为本仓库基线；治理走本仓库流程——决策记录进 GitHub Issues 与 `docs/adr/`，不照搬其状态机与模板体系。采纳其精神红线：Spec 权威、No fake evidence、禁止静默改接口、通关由新观测证明。

**Consequences**: 归档完成后 `temp/` 中的原包不再演进；所有修订以 diff/变更记录方式落到本仓库文档与 issue；发现底稿缺陷走本仓库决策流程而非其 Change Request 模板。
