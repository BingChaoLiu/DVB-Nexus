# Simulation Engine Spec Index

**Package version:** 0.5.0  
**Status:** MVP_BASELINE_APPROVED  
**Normative parent:** DVB Sandbox SPEC-001/003；事件信封 SPEC-301（ADR-0006）；故障管线 ADR-0007

[ticket #12 缝合批准](https://github.com/BingChaoLiu/DVB-Nexus/issues/12)（2026-11-14）：七份规格逐份修订后批准为 MVP 基线；包级依赖方向以各 spec 自身职责推导（Q5 裁决），REGISTRY §B 与本表一致。

| Spec ID | Document | Depends on | MVP priority | Primary output |
|---|---|---|---|---|
| SPEC-200 | [Simulation Runtime](SPEC-200-simulation-runtime.md) | SPEC-003/201/202/203 | P0 | 会话生命周期状态机、命令串行、snapshot 拉取 API |
| SPEC-201 | [Simulation Clock](SPEC-201-simulation-clock.md) | SPEC-003/105 | P0 | 整数纳秒虚拟时钟、有理数倍速、确定性调度器 |
| SPEC-202 | [L0 State Engine](SPEC-202-state-engine.md) | SPEC-003 | P0 | 端口级拓扑验证与纯函数状态求值（SIM_STATE） |
| SPEC-203 | [L1 TS Runtime](SPEC-203-ts-runtime.md) | SPEC-003/100..108/201/204 | P0 | prepare 绑定 fault plan、tee 双写、确定性生成编排 |
| SPEC-204 | [Fault Injection](SPEC-204-fault-injection.md) | SPEC-003/100/102/103/106 | P0 | 语义流式过滤器、四类故障语义、等位替换不变式 |
| SPEC-205 | [Scenario Engine](SPEC-205-scenario-engine.md) | SPEC-003/200/204 | P0 | 声明式场景文档、白名单执行、版本钉扎 |
| SPEC-206 | [Recovery Verification](SPEC-206-recovery-verification.md) | SPEC-205/306/308 | P0 | PASS/FAIL/INCONCLUSIVE 三态通关判定 |

集成契约：[SIMULATION-INTEGRATION-CONTRACT.md](SIMULATION-INTEGRATION-CONTRACT.md)（spec_id `SIMULATION-IC-001`，APPROVED 0.5.0）——依赖方向、ID 策略、事件义务、snapshot/Artifact 契约、版本策略。

## Dependency graph

```text
SPEC-003 Domain Model
    ├── SPEC-201 Clock ── SPEC-105（PCR 换算）
    ├── SPEC-202 L0 State Engine
    └── SPEC-200 Runtime（编排 201/202/203）
              │
              ├── SPEC-203 L1 TS Runtime ── SPEC-100..108（TS Core 公共契约）
              │         └── SPEC-204 Fault Injection ── SPEC-100/102/103/106（faults → ts）
              └── SPEC-205 Scenario Engine ── SPEC-200/204
                        └── SPEC-206 Recovery Verification ── SPEC-205/306/308
```

## 批准要点（详见各 spec 与 ticket #12 决议）

- 生命周期迁移表穷举（VALIDATING→FAILED、FAILED→DISPOSED 直达）；pause/resume 与时钟同临界区联动。
- fault plan 在 prepare 绑定进确定性指纹；artifacts 列表化 + tee 双写；baseline SHA-256 内容寻址去重。
- activation 收窄 packet_index + session_start；等位替换不变式冻结 CBR 与共用包序 frame。
- 两包事件信封义务由包级契约承载；生产者不自造全序号（journal_seq 权威）。
