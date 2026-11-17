# biss-j96-mode1 — 实测证据注记（SPEC-506 §4/§5，ticket #126）

## 向量身份

| 项 | 值 |
|---|---|
| vector_id | `biss-j96-mode1` |
| kind | `bit_level`（L1 外部权威向量） |
| related specs | SPEC-610（BISS Mode 1）、SPEC-204（BISS_KEY_MISMATCH 原语） |
| 生成脚本 | `tools/make_golden_biss_j96.py`（独立构造脚本，无 `src/` 参与） |
| CSA1 变换源 | 纯 Python CSA1 oracle（`tests/_support/csa1_oracle.py`，research #106 移植；**禁进运行时**，ADR-0011 §1） |

## 独立验证链（bit-level-review 路径）

1. **SW → CW 派生（标准权威）**：session word `A13DBC42908F` 为 **ITU-T J.96 §8 示例常量**（公开标准测试向量，非密钥材料）。派生公式（Tech 3292 / J.96，research #106 三个独立实现交叉印证一致：oscam `set_cw_checksum`、dvbipitools `biss1e.c`、DVBStreamer5 `Biss1Key.h`）：

   `CW[0..2]=SW[0..2]；CW[3]=(CW[0]+CW[1]+CW[2]) mod 256；CW[4..6]=SW[3..5]；CW[7]=(CW[4]+CW[5]+CW[6]) mod 256`

   实测：`A13DBC42908F → A13DBC9A42908F61`（`0xA1+0x3D+0xBC=0x9A`、`0x42+0x90+0x8F=0x61`）。本向量由脚本**内联重实现**该公式并断言钉扎；`src/ts/biss/biss1.derive_cw` 由 conformance 测试对拍本 manifest 的 `derived_cw`。

2. **CSA1 payload 变换（oracle 独立性）**：字节由 `tests/_support/csa1_oracle.py`（libdvbcsa 单包路径的忠实移植）生成。该 oracle 的独立正确性证据 = libdvbcsa 自带静态测试向量 2/2 PASS（generic DLL 与纯 Python 双向互证，research #106 §3.2/§4.2；向量入库 `tests/data/biss/csa1_static_vectors.json`）。

3. **DLL 交叉对拍（本地实测，CI NOT RUN）**：libdvbcsa_bs.dll（SSE2 bitslice 构建，`tools/build_dvbcsa_dll.sh` 照 research 报告 §2.1 命令确定性重建）与本 oracle 对静态向量与随机 payload 集双向对拍全绿（`tests/unit/adapters/dvbcsa/test_dvbcsa_binding.py`，DVB_NEXUS_DVBCSA_DLL 门控）。**CI（ubuntu）无 MSYS2 构建面 → 该对拍 NOT RUN（诚实 skip，理由 `-ra` 可见，ADR-0011 §5；裁定 §10-2：产物不入库、CI 不构建）。**

4. **结构自检语义**：每包 PUSI 载荷携带完整 PAT 段（table_id 0x00，CRC-32 由脚本内独立 MPEG-2 CRC 实现 `mpeg2_crc32` 计算并校验）——声明密钥解扰后全部 CRC 通过（`biss` 自检绿）；错密钥解扰即结构自检失败证据（C1 形态，conformance 测试钉扎）。

## 钉扎摘要

| 面 | 值 |
|---|---|
| packets | 6 × PID 0x0100，PUSI=1，AFC=01，CC 0..5 |
| TSC | `10`（J.96 Mode 1 只定义偶键；Tech 3292） |
| sha256 | `9647d274cc8a96b73f4f6b4aaabeaa1c9227935bc2a2294c5e596e6a81db9f94` |

## 密钥纪律注记

session word 出现在本 manifest 属**公开标准常量**（J.96 §8 示例），不是运行时密钥材料。运行时密钥纪律（SPEC-610 §9 / 简报 §5-6）：密钥本体不进 mutation log / journal / artifact / 断言，只落 `key_fingerprint`（SHA-256 前缀）——审计由 `tests/unit/faults/test_biss_key_mismatch_transform.py` 与 #126 REPORT 的 grep 审计承载。
