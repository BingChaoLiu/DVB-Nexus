# DVB Sandbox — Specification Baseline v0.4

> ## ⚠️ 归档说明（2026-11-14）
>
> 本包已归档为 DVB-Nexus 仓库的**只读参考底稿**（ADR-0001）。它不再演进：
>
> - **权威决策**：GitHub Issues（[Wayfinder Map #1](https://github.com/BingChaoLiu/DVB-Nexus/issues/1) 及其子 ticket）+ `docs/adr/`
> - **权威词汇表**：仓库根 `CONTEXT.md`
> - **远期路线**：`docs/roadmap.md`
> - 已知缺陷清单（编号双轨、事件信封三方冲突、故障管线缺口等）记录在 map 子 ticket 中，将以修订/补写方式落回本仓库文档，而非直接改本包
> - 本包引用的协议断言已做标准核查（见 `docs/research/standards-audit.md`）：ISO 位级断言全部核实一致；订正项见核查报告 §8
>
> 本包自身的 DRAFT/APPROVED 状态机与变更流程**不再使用**，由本仓库的 wayfinder + ADR 流程取代。

**Package type:** Product / Architecture / Engineering baseline  
**Baseline version:** 0.4.0-draft  
**Created:** 2026-11-13  
**Language:** 简体中文为主，接口和协议术语保留英文  
**Status:** 部分决策已确认；其余内容按本文标注为建议基线或待评审

## 1. 本包包含什么

本包建立后续 Agent 开发所需的规格管理骨架，包含：

- `SPEC-000`：产品需求与范围
- `SPEC-001`：系统总体架构
- `SPEC-002`：架构决策记录（ADR）
- `SPEC-003`：领域模型与跨模块数据契约
- `SPEC-004`：编码、测试与工程规范
- `SPEC-005`：Agent 开发协议与交付门禁
- `SPEC-INDEX.md`：Spec 索引、状态和依赖关系
- `modules/REGISTRY.md`：后续模块 Spec 注册表
- `REQ-REGISTRY.md`：需求 ID 与验收追踪表
- `templates/`：Module Spec、Agent Task、实施报告、变更申请模板

## 2. 重要说明

本包**不是所有模块的完整实现规格**。SPEC-000～SPEC-005 是项目级基线；`modules/REGISTRY.md` 只登记后续模块 Spec 的范围、依赖和顺序。每个模块在进入编码前，仍需单独生成完整 Module Spec、评审并批准。

## 3. 当前决策状态

### 已由项目方向明确

1. 仿真引擎采用 Hybrid：状态仿真 + 真实 MPEG-TS 仿真。
2. 优先码流为 MPEG-TS。
3. 后端主语言为 Python。
4. MVP 先建立真实 188-byte TS 数据闭环，再扩展 T2MI、BISS、RF/SEC 和 Live Mode。

### 作为建议基线、尚需项目负责人确认

1. 后端 Web 框架：FastAPI。
2. 前端：React + TypeScript，拓扑画布优先评估 React Flow。
3. 本地持久化：SQLite + 文件系统。
4. TSDuck：MVP 先以独立进程/CLI Worker 集成。
5. 工程形态：Modular Monolith + 独立 Worker Process。

未标记为“已确认”的建议，不应被 Agent 当作不可更改的既定决策。

## 4. 如何使用

1. 将本目录内容复制到项目仓库的 `docs/` 或按目录结构直接作为仓库根目录。
2. 项目负责人审阅 `SPEC-INDEX.md` 与 `SPEC-002`，确认建议基线。
3. 将需要开发的模块从 `modules/REGISTRY.md` 中选出。
4. 使用 `templates/MODULE-SPEC-TEMPLATE.md` 生成完整模块规格。
5. 将模块规格状态改为 `APPROVED` 后，才可生成 Agent Task。
6. Agent 必须按 `SPEC-005` 执行并提交实施报告。

## 5. 基本原则

**Spec 是需求与接口的权威来源；代码是 Spec 的实现；测试是实现符合 Spec 的证据。**

如代码、Agent 自行理解与已批准 Spec 冲突，以已批准 Spec 为准；如 Spec 本身存在缺陷，先提交变更申请，不允许静默改变接口或架构。
