# RF Spec Index（RF/SEC 沙盘状态模型，Phase 3）

**Package version:** 0.6.0（Phase 3 新增模块，随本批 DRAFT_FOR_REVIEW 落笔）
**Status:** APPROVED 0.6.0（Phase 3 地图 [#143](https://github.com/BingChaoLiu/DVB-Nexus/issues/143) 自动推进授权：check_specs 0 failed + 决议链对齐自检通过即翻批准，repo 主事后审计；2026-11-20）
**Normative parent:** DVB Sandbox SPEC-003（拓扑/平面/来源枚举）、SPEC-202 §6（L0 冻结求值接口）、SPEC-301+ADR-0006（事件信封）、SPEC-204（故障契约）；标准权威 = ETSI TS 101 964 §A.1 + TI SLVA863（22kHz 物理层/供电链，免费；EN 50494/50607 付费条款号「待原文核对」）

Phase 3 RF/SEC 沙盘状态模型两份规格（落笔票 [#154](https://github.com/BingChaoLiu/DVB-Nexus/issues/154)）：**不做连续 BER 数值仿真、不做时序过程仿真**（No fake evidence——simulated 域枚举档位由可判定事实推导，终态求值语义随 [#147](https://github.com/BingChaoLiu/DVB-Nexus/issues/147) L0 形态裁决）；14 态真值表逐格依据 = #146 research 分支（四源一致核实）。

| Spec ID | Document | Depends on | Priority | Primary output |
|---|---|---|---|---|
| SPEC-620 | [RF Simulation](SPEC-620-rf-simulation.md) | SPEC-621/003/202/301 | P2 | tuner 五组状态（lock_state 二态/if_frequency/ber_state 三档/错锁素材）、锁定求值规则表、rf.state_observed、A1/A2 症状承载 |
| SPEC-621 | [LNB Model](SPEC-621-lnb-model.md) | SPEC-003/202/301 | P2 | lnb 四组状态（电压/tone 双字段/band-LO/短路五态）、14 态 normative 真值表（附录 A）、lnb_kind 两变体、sec.state_observed、A2 注入缝 |
| SPEC-622 | [DiSEqC Controller](SPEC-622-diseqc-controller.md) | SPEC-003/202/301/621 | P2 | 1.x 单向命令子集（0x38/0x39 + framing/address 词汇）、committed/uncommitted 双寄存器终态化、port_selected 派生、时序常量参考表 |
| SPEC-623 | [Unicable](SPEC-623-unicable.md) | SPEC-622/620/003/202/301 | P2 | EN 50494/50607 位布局与频率公式（四实现共识标注）、ub_assignments 结构、UB 冲突判定（CauseRef 冲突对）、条款号缺口清单留档 |

## 裁决要点（详见各 spec 与 Phase 3 地图决议链）

- **L0 = 注册求值器，非新建引擎**（#147）：SPEC-202 冻结骨架（NodeEvaluator 注册制/确定性拓扑遍历/CauseRef 因果链/纯度纪律）MVP 已落地；SIM_STATE Run 一等公民、L0 不门控 L1。
- **状态语义经 metrics 承载**（#147 Q3）：SPEC-202 冻结接口零变更；`state_evaluator` 来源恒配 simulated 置信度（#152 Q1，SPEC-003 §2.4 修订）。
- **14 态真值表 normative**（SPEC-621 附录 A）：voltage 3 态 × tone 4 模式 + 2 复合态；13V→V/18V→H、无 tone→低段 LO 9750/持续 tone→高段 LO 10600；IF 重叠区 1100–1950 MHz 同槽位对应 850 MHz 相差——tone 唯一消歧，A2 症状链算术。
- **tone_commanded / tone_actual 分离**（#149/#151）：A2 原语 `TONE_RESIDUE` 的注入缝；故障经求值前纯变换进入，求值器不感知 fault。
- **ber_state 三档枚举**（#149 Q2）：可判定事实推导，无连续数值；`elevated` = 邻槽保护带（宽度实现票向量钉扎）；`severe` = 上游异常字段存在。
- **观测/告警/规则三轴分工**（#152/#151）：rf.*/sec.* 快照事件（303）、TUNER_UNLOCKED/BER_SEVERE 阈值告警（304）、TONE_RESIDUE_SUSPECT/UB_CONFLICT_SUSPECT 根因候选（307）——两轴不混。
- SPEC-622（DiSEqC Controller）/ SPEC-623（Unicable）随落笔票 [#155](https://github.com/BingChaoLiu/DVB-Nexus/issues/155) 并入本包索引。
