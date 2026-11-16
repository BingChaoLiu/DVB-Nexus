# T2MI Spec Index（T2-MI 链，Phase 2）

**Package version:** 0.5.1（Phase 2 新增模块，随本批 DRAFT_FOR_REVIEW 落笔）
**Status:** APPROVED 0.5.1（repo 主审计确认翻批准，2026-11-17；批准流：Phase 2 地图 [#103](https://github.com/BingChaoLiu/DVB-Nexus/issues/103) 既裁）
**Normative parent:** DVB Sandbox SPEC-003（拓扑/平面）、SPEC-301+ADR-0006（事件信封）、SPEC-204（故障契约）；标准权威 = TS 102 773 §5.1（T2-MI 包）与 EN 302 755 §5.1.7（BBHEADER）

Phase 2 高级封装层 T2-MI 链四份规格（落笔票 [#115](https://github.com/BingChaoLiu/DVB-Nexus/issues/115)）：**解析与封装双向均为必修**（开图既裁 + [#104](https://github.com/BingChaoLiu/DVB-Nexus/issues/104) 实测证据）；分层流水线与自研边界随 [细裁 #108](https://github.com/BingChaoLiu/DVB-Nexus/issues/108)；拓扑节点随 [#110](https://github.com/BingChaoLiu/DVB-Nexus/issues/110)；故障原语随 [#111](https://github.com/BingChaoLiu/DVB-Nexus/issues/111)；观测事件随 [#113](https://github.com/BingChaoLiu/DVB-Nexus/issues/113)；验证层证据 = #104/#105/#107 research 分支。

| Spec ID | Document | Depends on | Priority | Primary output |
|---|---|---|---|---|
| SPEC-600 | [T2MI Parser](SPEC-600-t2mi-parser.md) | SPEC-100/107/301/003 | P2 | T2-MI 包双向接口、两类节点 config schema、t2mi.stage_summary 事件、背靠背纪律 |
| SPEC-601 | [BBFrame Parser](SPEC-601-bbframe-parser.md) | SPEC-600/100 | P2 | BBHEADER 10B 双向接口（HEM/NM 子集 + ISSY/NPD）、CRC-8 强制校验、bbframe.* 事件、B2 原语挂钩 |
| SPEC-602 | [PLP Extractor](SPEC-602-plp-extractor.md) | SPEC-600/601 | P2 | PLP 过滤/分配/统计三接口、B1 原语 T2MI_PLP_MISMATCH 语义、t2mi.plp_mismatch 事件 |
| SPEC-603 | [Inner TS Reconstruction](SPEC-603-inner-ts-reconstruction.md) | SPEC-600/601/602/100 | P2 | UP 拼装与 SYNCD carry-over、Inner TS 输出（artifact kind=inner_ts）、TSDuck 第二意见对拍协议（升级复测前置） |

## 裁决要点（详见各 spec 与 Phase 2 地图决议链）

- **双向必修**：TSDuck 无封装能力（#104 留证）、FFmpeg 无 t2mi demuxer（#105 证伪）→ 自研 Python 为主路径；TSDuck 收窄为第二意见验证器（前置 = 升级含 master 147deab3 的发布版并复测 NM/ISSY/NPD 与多 UP 尾包，未过复测标注 NOT TRUSTED）；dvb-t2mi crate 不进运行时/CI，仅开发期 oracle（#107）。
- **BBFrame = 节点内部层次**，非独立信号平面（#110）：五平面枚举无 BBFrame；`SignalPlane.T2MI` 启用，BBHEADER 教学点「SYNCD 是位距不是同步字节」入包检查器文案。
- **强制超越点**（相对 TSDuck 3.45-4798 实测缺陷）：CRC-8/CRC-32 显式校验不静默、多 UP 尾包确定性、失败路径显式证据（Worker 内容校验义务契约化）。
- **背靠背紧排纪律**：T2-MI 包间不插段间 padding（#104 实测 padding 使下游 demux 永久停摆）——构造侧违反即构造期拒绝。
- 观测面：t2mi.*/bbframe.* 命名空间 additive（#113）；`ts.*` 申报 1 口径维持诚实 INCONCLUSIVE。
