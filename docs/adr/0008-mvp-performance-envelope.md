---
status: accepted
date: 2026-11-14
---

# MVP 性能定档（Performance Envelope）：离线批处理口径，码率 1~100 Mbps、默认 188 MB、上限 376 MB

裁决 OPEN-006：MVP 性能目标与最大 TS 文件大小定档。实测依据来自 [Python 性能可行性调研](https://github.com/BingChaoLiu/DVB-Nexus/issues/5)（报告 `../research/python-perf.md`，基准脚本 `../research/python-ts-bench/`）：AMD Ryzen 9 5900X 单线程 / Python 3.10 / Windows 实测端到端 2.19M 包/s ≈ 3.29 Gbps 等效，对 100 Mbps 余量 ≥ 30×，对 20 Mbps 实时档余量 ~164×。本 ADR 回填 SPEC-108 §5 的码率范围占位、为 SPEC-507（Performance & Resource Limits，P1）提供编写时的权威引用，并关闭 [ADR-0003](0003-frozen-tech-stack.md) 条件条款的最后一笔（第 1 条）。裁决过程见 [#16](https://github.com/BingChaoLiu/DVB-Nexus/issues/16)。

## 决定（逐条）

### 1. 定位口径：MVP 生成 = 离线批处理，不承诺实时

SPEC-107 §3.2 冻结的口径：CBR 是**媒体时间**调度定义，不要求 Generator 在真实墙钟上实时发送。20 Mbps CBR 实时只需 13,298 包/s（实测能力的 0.6%），"实时"在 MVP 中是伪需求——生成是离线批处理作业。**MVP 不承诺实时输出/低延迟**；若未来需要近实时生成预览，按 ≥ 50 Mbps 等效（33,300 包/s）设定即可，实测余量 ~66×。

### 2. 性能包络六项（冻结值）

| 项 | 冻结值 | 依据 |
|---|---|---|
| MVP 支持码率范围（进配置校验，超范围拒绝） | **1 ~ 100 Mbps** | SPEC-108 §5 占位回填；覆盖常见 DVB-S/S2 TS 速率，对上限余量 ≥ 30× |
| 默认生成 preset | **1,000,000 包 = 188 MB**（16 Mbps ≈ 94 s 媒体时长） | 与基准同口径；对自研 parser 与 TSDuck 分析都友好 |
| 单 artifact 硬上限 | **2,000,000 包 = 376 MB**（20 Mbps ≈ 150 s 媒体时长） | 满足分钟级样本分析，防 UI 误配超大任务 |
| 生成耗时验收上限（含 SHA-256） | **≤ 10 s（目标 ≤ 3 s）** | 实测简化管线 0.5 s、完整管线预估 1~4 s，留 ≥ 2.5× 余量 |
| 生成进程内存峰值 | **≤ 512 MB** | Iterator 模式不保留全量对象 |
| 实时承诺 | **不承诺** | 见第 1 条 |

**明确不做（防过度工程）**：实时流式输出 / RT 时钟同步、多线程/多进程生成、C 扩展、> 376 MB 单文件。

### 3. ADR-0003 第 1 条正式冻结（条件条款关闭）

[ADR-0003](0003-frozen-tech-stack.md) 条件条款要求第 1 条（纯 Python 吞吐）与第 6 条（自研 TS Core）经 research 复核后才算最终冻结：第 6 条已由 [ADR-0005](0005-architecture-baseline.md) 修正关闭，第 1 条由本 ADR 关闭——实测确认纯 Python 满足 MVP 全部性能目标，**七条技术选型至此全部最终冻结**，不引入 Cython/Rust/C++。

### 4. 热点迁移触发条件（显式条款）

**触发 = 以下两条件同时成立**：

1. 完整管线实测 100 万包 > 30 s（验收上限 3 倍）；
2. profiler 确认热点在 Python 层（而非 I/O 或 TSDuck 子进程）。

满足即启动原生扩展**评估**（以新 ADR 裁决），不是自动迁移；禁止凭直觉引入 C 扩展。当前实测距触发条件有 10 倍以上距离。

### 5. 测试与验收写法

- **CI 不做绝对墙钟断言**（跨机器 flaky）：功能测试只验正确性；
- **性能 smoke 阈值**：100 万包 ≤ 60 s（验收上限 6 倍余量，防数量级回归；实现随 TASK-TS-108 工作票落地）；
- 正式性能验收在本机按 `../research/python-perf.md` §8（bench.py）口径复测，数据记录于对应实现工作票；
- SPEC-505 的性能基准测试占位指向本 ADR；SPEC-507（P1）编写时直接引用本 ADR，不重开裁决。

## Consequences

- SPEC-108 §5 码率占位回填（1 ~ 100 Mbps + 本 ADR 指针），版本保持 0.5.0——占位回填由规格原文预留，非接口变更，随 [#16](https://github.com/BingChaoLiu/DVB-Nexus/issues/16) 记录非静默；
- SPEC-505 性能基准测试占位指向本 ADR，版本保持 0.5.0（同上）；
- 性能 smoke 阈值（100 万包 ≤ 60 s）归属 TASK-TS-108 验收测试；
- CONTEXT.md 增词条「性能包络（Performance Envelope）」；
- SPEC-507 编写时（P1，随 roadmap）直接引用本 ADR 数值，不重开裁决。
