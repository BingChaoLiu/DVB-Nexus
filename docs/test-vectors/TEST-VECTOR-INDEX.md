# TS Core Test Vector Index

位级向量与 golden 向量的权威索引（仓库级 `docs/test-vectors/`，SPEC-506 0.6.0 起）。golden 目录布局、登记格式、独立验证规则与 CI 门见 SPEC-506（Conformance Suite）；本索引每行指向一个向量文档或 `golden/<vector_id>/` 三件套目录（`<id>.ts` + `manifest.json` + `expectations.json`，另附 `<id>.verification.md` 实测证据注记）。

## 位级向量文档（L1 外部独立向量）

| Vector | Related Spec | Purpose | Status |
|---|---|---|---|
| `CRC32-MPEG2.md` | SPEC-101/102/103 | MPEG-2 CRC algorithm/check/remainder | Initial vector |
| `PCR-PTS.md` | SPEC-105/104 | PCR/PTS bit packing, boundary and wrap | Initial vector |
| `PACKET-HEADER-SET.md` | SPEC-100 | TS packet header wire-table derivation for `golden/packet-header-set/` | Initial vector |

## golden 向量（SPEC-506 §7 首批清单，#14 决议——全部 registered）

| vector_id | Kind | Purpose | 独立验证路径 | Status |
|---|---|---|---|---|
| `packet-header-set` | bit_level | 188-byte 包头样本集 ×10（TEI/PUSI/优先级/PID 边界/scrambling/AFC/CC 边沿，SPEC-100） | L1：spec 表推导脚本 + 人工评审（`PACKET-HEADER-SET.md`） | registered |
| `pat-minimal` | generated_ts | 最小合法 TS：PAT+PMT 单节目，50 包（SPEC-103/108） | L2：tsduck-generate→self-parse（tsxml→tstabcomp→inject） | registered |
| `pat-pmt-multi` | generated_ts | PAT/PMT 变体：双节目、4 种流类型，60 包（SPEC-103/108） | L2：tsduck-generate→self-parse | registered |
| `cc-wrap` | generated_ts | CC 15→0 回绕序列：单 PID 18 payload 包（SPEC-100 §5.4） | L2：script-construct→tsduck-analyze（continuity 静默） | registered |
| `pcr-wrap` | generated_ts | PCR 回绕边界：2³³−δ 手工置值 ×6，modular_delta 半周期窗口（SPEC-105） | L2：script-construct→tsduck-analyze（pcrextract 读回） | registered |
| `section-fragmentation` | generated_ts | PUSI/pointer、section 跨 3 包：100 程序 PAT（412 字节）（SPEC-102/106） | L2：script-construct→tsduck-analyze（tstables 重组） | registered |
| `pat-missing-baseline` | generated_ts | PAT_MISSING 对的 baseline：SPEC-108 pull-safe 几何 600 包 | L2：self-generate→tsduck-analyze | registered |
| `pat-missing` | faulted_ts | PAT_MISSING：activation=202 起窗内 PID 0 → Null 顶替（SPEC-204 §6.1），`fault_plan_ref=pat-missing-baseline` | L2：独立变换脚本→tsduck-analyze（PID 0 包数 3→1） | registered |
| `pmt-invalid-crc-baseline` | generated_ts | PMT_INVALID_CRC 对的 baseline（同上几何） | L2：self-generate→tsduck-analyze | registered |
| `pmt-invalid-crc` | faulted_ts | PMT_INVALID_CRC：persistent + invert，3 个 PMT 实例 CRC 反转（SPEC-204 §6.2），ref 同上 | L2：独立变换脚本→tsduck-analyze（PMT 被独立 demuxer 拒收） | registered |
| `cc-discontinuity-baseline` | generated_ts | CC_DISCONTINUITY 对的 baseline（同上几何） | L2：self-generate→tsduck-analyze | registered |
| `cc-discontinuity` | faulted_ts | CC_DISCONTINUITY：相对偏移 delta=3，落点 slot 50，偏移持续（SPEC-204 §6.3），ref 同上 | L2：独立变换脚本→tsduck-analyze（continuity 报 slot 50 missing 3） | registered |
| `pmt-pid-mismatch-baseline` | generated_ts | PMT_PID_MISMATCH 对的 baseline（同上几何） | L2：self-generate→tsduck-analyze | registered |
| `pmt-pid-mismatch` | faulted_ts | PMT_PID_MISMATCH：PAT `program_map_PID` 4096→4100 + CRC 重算（SPEC-204 §6.4），ref 同上 | L2：独立变换脚本→tsduck-analyze（tstables 见 PAT 指向 4100、PMT 孤儿在 4096） | registered |
| `t2mi-minimal` | generated_ts | 最小合法 T2-MI 流：3 BBFRAME 包（NM UP、BBHEADER 10B、多 UP 尾包形态 [20,20,12]、PLP [0,0,1]、背靠背紧排）（SPEC-600 §11.1，#122） | L1：TS 102 773 §5.1 表推导脚本（无 src 参与）+ TSDuck 3.45-4798 HEM 交叉**NOT TRUSTED**（尾包静默丢失复现，裁定 §10-9） | registered |
| `t2mi-crc-corrupt` | faulted_ts | T2MI CRC-32 位翻转：包 0 坏包显式标记 + 继续解析、静默丢弃为零（SPEC-600 §8），`fault_plan_ref=t2mi-minimal` | L1：独立变换脚本→self-parse（坏包标记/继续解析逐字节钉扎，TSDuck 3.45 静默丢弃教训 #104） | registered |
| `bbframe-nups3` | generated_ts | BBFRAME 背靠背帧流（层间交接形态）：3 帧 N_UPS=3 批量 + 尾帧 [3,3,2]（尾帧 2 UP + 188B 0xFF stuffing、DFL 只计实载荷）（SPEC-601 §7/§11，#123） | L1：EN 302 755 §5.1.7 表推导脚本（无 src 参与）+ TSDuck 3.45 零 BBFrame 用户侧能力（#104）**NOT TRUSTED** 无 L2 对拍（裁定 §10-9） | registered |
| `bbframe-b2-corrupt` | faulted_ts | BBHEADER_SYNC_FAULT corrupt（SYNCD 位翻转、CRC-8 不重算）：帧 0 `crc8_valid=false` + UP 边界扣留 → recovery_failed 证据（SPEC-601 §8），`fault_plan_ref=bbframe-nups3` | L1：独立变换脚本→self-parse（CRC-8 强制校验钉扎，TSDuck 3.45 静默传播缺陷 #104 反转为显式标记） | registered |
| `bbframe-b2-shift` | faulted_ts | BBHEADER_SYNC_FAULT shift（SYNCD +1 位、CRC-8 重算 MODE 保持）：帧 0 `crc8_valid=true` + `syncd_misaligned`（UP 边界错位；教学点 SYNCD=位距离非同步字节），`fault_plan_ref=bbframe-nups3` | L1：独立变换脚本→self-parse（与 corrupt 对成两种可区分证据形态，逐字节钉扎） | registered |
| `biss-j96-mode1` | bit_level | BISS Mode 1：J.96 §8 示例 SW `A13DBC42908F`→CW `A13DBC9A42908F61` 派生钉扎 + CSA1 加扰 roundtrip（SPEC-610）；DLL 依赖面 CI 诚实 NOT RUN（ADR-0011 §5） | L1：标准向量推导脚本（`tools/make_golden_biss_j96.py`，纯 Python CSA1 oracle，无 src 参与）+ 人工评审；DLL 对拍本地绿/CI NOT RUN | registered |
| `biss-mode-e-derive` | bit_level | BISS Mode E：J.96 §9.3 派生链（injected_id 128-bit + ESW 16 hex → SW `A13DBC42908F` → CW `A13DBC9A42908F61` → CISSA roundtrip 一条端到端，SPEC-611）；`CW‖CW` 沙箱组合钉扎；每包重启独立性；零原生依赖（pycryptodome，CI 全测可跑） | L1：标准算法内联重实现脚本（`tools/make_golden_biss_mode_e.py`，pycryptodome 原语，无 src 参与）+ 人工评审 | registered |
| `inner-ts-roundtrip` | generated_ts | Inner TS 重建 expected 侧基准：research 分支 `expected_inner.ts` 原样入册（2×HEM BBFrame ×3 UP = 6 包 PAT/PMT/null，SPEC-603 §11 正向，#125）；链输入 `tests/data/t2mi/inner_ts_roundtrip_input.bin`（同源 provenance，README 三问登记） | L1：外部独立生成器基线（research/ffmpeg-t2mi-demuxer @ 2935ab68，无 src 参与，`git show` 只读取材）+ L2 TSDuck live cross **NOT TRUSTED**（3.45 多 UP 尾包丢失复现，裁定 §10-9；trusted registry 空直至复测矩阵过） | registered |

### #14 Q3 三 TODO 落实路径（已闭环）

1. **packet-header.bin → `golden/packet-header-set/`**（SPEC-100 已批准即做）：位级手造三件套，字节由 `tools/make_golden_packet_header_set.py` 从 SPEC-100 §3 wire 表逐位推导；L1 验证（推导脚本 + 评审 + 自解析器逐字段对拍），无需 TSDuck。
2. **pat-minimal.ts → tsxml→tstabcomp 链路生成**：tsxml 源在 `tools/tsduck-tsxml/pat-minimal-*.xml`，经 `tstabcomp --output` + `tsp -I null -P inject --stuffing -O file` 产出 50 包（#3 实测链路）；Generator（SPEC-108）对同配置流断言同一 expectations 可观测、不做字节比对（#14 Q3 原文）。
3. **section-fragmentation.json → 标准 golden 三件套**：`golden/section-fragmentation/`（"json"意图由 expectations.json 承载），字节由 `tools/make_golden_ts_vectors.py section-fragmentation` 构造（独立 CRC 实现，对拍 CRC32-MPEG2.md check value），tstables 跨 3 包重组 100 程序。

- Status 取值：`planned`（批准、待产出）→ `registered`（三件套入库，sha256 门生效）→ `deprecated`（失效保留，provenance 纪律）。首批 10 条目经 #14 决议打包预批准，全部 registered（14 trios，digest 冻结表见 `tests/conformance/test_first_batch_registry.py`）。
- faulted 向量由 tools/ **独立变换脚本**（`tools/golden_fault_transform.py`，无 src/ts 参与）从 baseline 生成（变换语义照 SPEC-204 §6/§7 冻结条款），不经自研 Generator、不经过滤器——并兼任过滤器集成测试的字节级 oracle（输出 SHA 与 golden faulted 一致断言）。
- 自研 Generator（SPEC-108）实现后，对同配置流断言**同一 expectations 可观测**，不做字节比对（四 baseline 即 SPEC-108 pull-safe 几何产物，同时承担该对照的 baseline 形态）。
- 负向畸形输入集不入 golden（expectations 机制只承载正向观测断言）：落 `tests/data/malformed/`，unit 层测试（SPEC-102 错误码、SPEC-308 JSON 内容门）。
- 构造/变换脚本（`tools/make_golden_packet_header_set.py`、`tools/make_golden_ts_vectors.py`、`tools/make_golden_tsduck_vectors.py`、`tools/make_golden_baseline.py`、`tools/golden_fault_transform.py`）确定性可重跑（同脚本 + 同版本 + 同参数 ⇒ 同字节，有 conformance 断言）；CI 只验 sha，永不重新生成覆盖（SPEC-506 §6）。
- 登记校验器：`tools/validate_golden_registration.py`（三件套/sha/事件类型合法性/pair 链接/索引一致性，conformance 门断言其 PASS）。

## 独立验证红线（升格条款，SPEC-506 §5）

Golden files generated by implementation Agent must not be accepted solely because the same implementation parses its own output. At least one independent validation path (TSDuck analysis in either direction, or independently-reviewed bit-level vector) is required.

三层验收地位：**L1 外部位级向量 = 权威基准；L2 TSDuck 双向交叉 = 合格独立验证路径；L3 自研 round-trip = 仅回归覆盖**，永不构成独立验收证据。每向量方向与证据锚点登记于 manifest `verification` 字段与 `golden/<id>/<id>.verification.md`（TSDuck 3.40-4165 实测）。
