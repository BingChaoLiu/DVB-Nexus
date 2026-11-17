# biss-mode-e-derive — 实测证据注记（SPEC-506 §4/§5，ticket #127）

## 向量身份

| 项 | 值 |
|---|---|
| vector_id | `biss-mode-e-derive` |
| kind | `bit_level`（L1 外部权威向量） |
| related specs | SPEC-611（BISS Mode E）、SPEC-610（共享加扰器纪律）、SPEC-204（BISS_KEY_MISMATCH 原语） |
| 生成脚本 | `tools/make_golden_biss_mode_e.py`（独立构造脚本，无 `src/` 参与） |
| 密码原语 | pycryptodome 4.5.0（外部独立验证库——research #106 全密钥面 roundtrip PASS），**非运行时实现** |
| 依赖面 | 零 DLL/原生依赖（AES/DES 走 pycryptodome；与 SPEC-610 的 DLL 面 CI 门差异即在此，SPEC-611 §9） |

## 独立验证链（bit-level-review 路径）

1. **Mode E 派生（标准权威）**：ITU-T J.96 §9.3 逐 bit 规范（BISS Mode E 完整规范性定义，EBU Tech 3292 rev.2 公开等价文本）。派生链：
   - Injected ID（128-bit，32 hex）→ DES 密钥面取**低 56 bit**（末 14 hex 字符，Tech 3292-s1 session key 语义的沙箱钉扎）；
   - §9.3.3 a / Table 2 映射：56 bit 填入 8 字节高 7 bit，每字节 LSB 奇校验 → Mapped Active ID；
   - `SW' = DES-ECB-decrypt(Mapped Active ID, ESW)`（§9.3.3 b，FIPS 46-3/81）；
   - Table 3 缩减：每字节删 MSB/LSB，中 6 bit 级联 → SW"（48 bit）；
   - §9.3.4 P()：injected ID ⇒ 恒等（buried ID 旋转出界——场景只载 `injected_id`）。
   三实现交叉印证（research #106）：dvbipitools `biss1e.c`、oscam、DVBStreamer5。
2. **生成脚本独立重实现**：脚本内联实现 §9.3 **加密方向**（标准只规范解密方向；加密侧 SW' 缩减位的丢弃 MSB 钉 0、LSB 钉低 7 bit 奇校验——确定性生成器钉扎，解密面按 Table 3 忽略两者）+ §8 校验和公式 + TS 103 127 §6.3 CISSA 规则，全部经脚本内断言钉扎（J.96 §9.3 roundtrip、§8 `A13DBC42908F→A13DBC9A42908F61`、IV、176/8 尾部明文）。
3. **向量常量来源**：session word = **J.96 §8 示例常量** `A13DBC42908F`（与 `biss-j96-mode1` 同源，公开标准测试向量，非密钥材料）；Injected ID 由固定 ASCII 标签 SHA-256 确定性导出（`biss-mode-e-derive injected ID constant` → 前 32 hex）——无密钥材料出处。
4. **沙箱组合钉扎**：Mode E → CISSA 密钥组合 = `CW ‖ CW`（8 字节控制词重复为 16 字节 AES-128 密钥）。**这是文档化的沙箱组合规则，不是标准运算**（SPEC-611 §4 派生链 + §5 BISS2 信令的教学合成；manifest `ciss_key_composition` 键钉扎）。理由：ESW=16 hex（64-bit DES 面）派生的 CW 无法直接作 AES-128 密钥；组合保持派生链全程指纹可追溯且零造密。
5. **CISSA（TS 103 127 §6.3，规范原文留档）**：AES-128-CBC + 固定 IV `0x445642544d4350544145534349535341`（ASCII `DVBTMCPTAESCISSA`）+ 每包重启 + `encrypted_payload_size = payload − payload mod 16`（无 AF ⇒ 176 加密 + 尾 8 字节明文）。运行时实现 `src/ts/biss/cissa` 由 conformance 测试对拍本 manifest 派生链与注册字节。
6. **每包重启独立性**（SPEC-611 §11）：改包 k 不影响包 k+1 输出（包间无链）——conformance 测试在注册字节上钉扎。

## 钉扎摘要

| 面 | 值 |
|---|---|
| packets | 6 × PID 0x0100，PUSI=1，AFC=01，CC 0..5 |
| TSC | `10`（BISS 加扰标记；TS 103 127 不钉 TSC，沙箱沿用族标记） |
| 派生链 | `injected_id 596E…F2B4` + `ESW BCD10F7EA1978B2C` → SW `A13DBC42908F` → CW `A13DBC9A42908F61` → CISSA roundtrip |
| sha256 | `eda260a4e579a6d209f94fb4a71e4130ae23e58c29e564b77094baf069218a60` |

## 密钥纪律注记

本 manifest 出现的 ESW / Injected ID / SW / CW 均为**合成向量常量**（第 3 条出处），不是运行时密钥材料。运行时密钥纪律（SPEC-610 §9 / SPEC-611 继承 / 简报 §5-6 硬红线）：密钥本体不进 mutation log / journal / artifact / 断言，只落 `key_fingerprint`（SHA-256 前缀）——#127 的 grep 审计见票面 REPORT。
