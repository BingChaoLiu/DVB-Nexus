# 标准条款引用事实核查报告（GitHub Issue #6）

**核查对象**：`temp/DVB-Sandbox-Spec-v0.4-Complete/`（v0.4 规格包，重点 docs/modules/ts-core/SPEC-100/102/103/104/105/107/108）与 `temp/v03.md`（案例库 A1/B1/B2/C1/D2）
**核查日期**：2026-11-14
**核查方式**：优先对照标准原文 PDF（ITU-T H.222.0 官方免费版 = ISO/IEC 13818-1 的 ITU 版本；ETSI TR 101 290 v1.3.1、TS 102 773 v1.4.1、EN 300 468 v1.20.1、EN 302 755 v1.3.1 均从 etsi.org 免费下载并逐条 grep 核对原文；EBU TECH 3292 / 3292-s1 从 tech.ebu.ch 下载），无法免费获取的（EN 50494/EN 50607）使用权威二手来源交叉验证。TSDuck 对照使用本机安装的 3.40-4165（`D:\Program Files\TSDuck\doc\tsduck.html` + 插件 `--help` 实测输出）。

**包内契约**：SIMULATION 契约（docs/modules/simulation/SPEC-205-scenario-engine.md 第 14 行）规定 "Do not invent ETSI/ITU clause numbers"。本次核查检验该约束是否被遵守。

---

## 0. 总览结论

| # | 核查项 | 结论 |
|---|---|---|
| 1 | ISO/IEC 13818-1 vs SPEC-100/102/103/104/105 位级断言 | **核实一致**（32 项关键断言全部与原文吻合；2 处措辞级偏差见 §1.6/§1.7） |
| 2 | ETSI TS 102 773 vs v03 案例 B1（T2MI/BBFrame/PLP） | **核实一致** |
| 3 | ETSI TS 102 773 vs v03 案例 B2（BBHEADER/SYNCD 归属） | **有偏差**（BBHEADER/SYNCD 不在 TS 102 773 中，出处应为 EN 302 755 §5.1.7；SYNCD 术语理解错误） |
| 4 | ETSI TR 101 290 优先级归属 | **核实一致**（包内未编造优先级；本报告补齐权威归属：CC=P1、PAT/PMT=P1、PCR 重复率/抖动=P2） |
| 5 | PAT/PMT 100ms 与 PCR 40ms 的性质 | **核实一致**（包内自我声明为项目默认值，属实；100ms ≈ TS 101 154 §4.1.7 建议，40ms = 旧 DVB 建议保留在 TR 101 290 P2 表中、2005 年已放宽为 100ms） |
| 6 | EN 50494/EN 50607 vs v03 案例 A1 | **有偏差**（SCR 展开名错误；槽位冲突模型本身正确） |
| 7 | BISS vs v03 案例 C1 | **有偏差**（"16 字节密钥"、"流内含动态 Injected ID"两处与 EBU TECH 3292/3292-s1 不符） |
| 8 | v03 案例 D2（PCR/Jitter>500ms 违反 ISO 13818-1） | **有偏差**（ISO 规范限值为 0.1s=100ms；500ms 混淆了间隔限值与 TR 101 290 的 ±500ns 抖动限值） |
| 9 | TSDuck 文档/能力对照 | **核实一致**（t2mi 插件、pcrverify 插件、ts::TSPacket 均存在；注意 descrambler 插件**不支持 BISS**） |

**总体评价**：规格包（v0.4）没有发现编造条款号或虚构标准条目的行为——它对不确定的地方反而系统性地声明"以标准原文为准/这是项目配置不是标准值"，符合其自设契约。需要订正的偏差集中在 **v0.3 案例库的白话描述**（B2 的标准归属、A1 的术语、C1 的密钥长度、D2 的数值）和 **SPEC-100 一处表格措辞**。

---

## 1. ISO/IEC 13818-1（ITU-T H.222.0）对照核实

**证据源**：ITU-T H.222.0 (05/2006) 官方免费 PDF（= ISO/IEC 13818-1:2007 (E)，itu.int dologin 直下）。相关位级条款自 1994 年以来稳定；包内引用的 "ITU-T H.222.0 (04/2025)" 经查证为真实存在的现行第 10 版（ISO/IEC 13818-1:2025 同文）。
2025 版全文因 ITU 站点限制未能获取，本节以 2006 版原文逐条核对，并注明对现行版仍成立的理由（这些条款在历版中未变）。

### 1.1 TS 包与 CC 规则（SPEC-100）——核实一致

| SPEC-100 断言 | 标准原文 | 结论 |
|---|---|---|
| 188-byte 包，sync_byte=0x47 | 2.4.3.1 "Transport Stream packets shall be 188 bytes long"；2.4.3.2 "sync_byte is a fixed 8-bit field whose value is '0100 0111' (0x47)" | 一致 |
| Header 位域表（TEI/PUSI/priority/PID 13/TSC 2/AFC 2/CC 4） | Table 2-2 完全一致 | 一致 |
| CC：仅带 payload 的包推进；AF-only（AFC=10）复用最近 CC 不推进；15→0 回绕 | 2.4.3.2："continuity_counter is a 4-bit field incrementing with each Transport Stream packet with the same PID … wraps around to 0 after its maximum value … **shall not be incremented when the adaptation_field_control of the packet equals '00' or '10'**" | 一致（AFC='01'/'11' 才递增 ⇔ "仅 payload 推进"；AF-only 不递增 ⇔ 复用；回绕明文） |
| AFC 表：00 保留/01 仅 payload/10 仅 AF/11 两者 | Table 2-5 完全一致；且 "In the case of a null packet the value of the adaptation_field_control shall be set to '01'"（与 SPEC-107 Null 包 AFC=payload-only 一致） | 一致 |
| AF length 0..183；AFC=11 时至少 1 byte payload；AFC=10 时必须占满 184 bytes | 2.4.3.5："When AFC='11', adaptation_field_length … 0 to 182. When AFC='10' … shall be 183"（183+1 长度字节 = 184） | 一致（见 §1.6 措辞提示） |
| AF stuffing 用 0xFF；AF length=0 仅一个 stuffing 字节 | 2.4.3.5/2.4.3.3："stuffing_byte … fixed 8-bit value '1111 1111'"；"The value '0' is for inserting a single stuffing byte" | 一致 |
| 重复包：同 CC 连发两次 | 2.4.3.2 "duplicate packets shall have the same continuity_counter value … two, and only two, consecutive" | 一致 |

### 1.2 PCR 编码（SPEC-105）——核实一致

| SPEC-105 断言 | 标准原文 | 结论 |
|---|---|---|
| PCR = 33-bit base + 6-bit reserved('111111') + 9-bit extension，共 6 字节 | Table 2-6（adaptation field 语法表）：program_clock_reference_base 33 uimsbf / Reserved 6 bslbf / program_clock_reference_extension 9 uimsbf；2.4.3.5 "The program_clock_reference (PCR) is a 42-bit field coded in two parts" | 一致 |
| reserved 6 bits 必须为 '111111' | 2.1.64 "reserved" 定义："Unless otherwise specified … **all reserved bits shall be set to '1'**"（2006 版由此推出 6 位全 1；新版表格直接印 '111111'） | 一致 |
| extension 合法 0..299 | 方程 2-3：PCR_ext(i) = ((27MHz × t(i)) mod 300) → 0..299 | 一致 |
| 组合 27MHz tick = base×300 + ext；base 按 2^33 回绕；模数 2^33×300 | 方程 2-1/2-2：PCR = PCR_base×300 + PCR_ext；PCR_base = ((27MHz×t) DIV 300) mod 2^33 | 一致 |
| 90 kHz（base）/27 MHz（ext）时基 | 2.4.3.5 及 Annex D.0.3 | 一致 |

### 1.3 PSI Section（SPEC-102）——核实一致

| SPEC-102 断言 | 标准原文 | 结论 |
|---|---|---|
| 3-byte header：table_id 8 + SSI/0/reserved/section_length 12 | Table 2-30（private/PSI section 语法） | 一致 |
| section_length 计数从 section_length 字段之后开始（含 CRC）→ 总长 = 3 + section_length | 2.4.4.x："section_length … specify the number of bytes of the section, **starting immediately following the section_length field, and including the CRC**" | 一致 |
| PAT/PMT 单 Section 上限 1021 | 2.4.4.3/2.4.4.8（PAT、PMT 语义）："The value in this field **shall not exceed 1021 (0x3FD)**"（CAT 同） | 一致 |
| PSI 整体 1024 字节上限（区别于 DVB SI 4096） | 2.4.4.1 注/Annex："There is a maximum limit on the length of a section of 1024 bytes"；"The maximum number of bytes in a private_section is 4096 bytes" | 一致 |
| pointer_field 语义：PUSI=1 时首个 payload 字节是 pointer，值为到第一 section 的偏移；0x00 表示紧随其后 | 2.4.4.1："pointer_field – … shall be the number of bytes, immediately following the pointer_field until the first byte of the first section … (a value of 0x00 indicates that the section starts immediately after the pointer_field) …" | 一致（逐句吻合） |
| Section 后 0xFF stuffing 须识别为 stuffing | 2.4.4.1："the remaining bytes … shall also be stuffing bytes of value 0xFF … next packet … begins with a pointer_field of value 0x00" | 一致 |
| Short-form 不代表无 CRC；DVB TOT 是 table-specific 例外 | EN 300 468 V1.20.1 time_offset_section（TOT）：**section_syntax_indicator = 0b0 且末尾有 CRC_32**；TDT 无 CRC。SPEC-102 的"例外"说法准确 | 一致 |
| 参考文献引 RFC 4259 解释 PUSI/pointer_field | RFC 4259 "A Framework for Transmission of IP Datagrams over MPEG-2 Networks" 定义 Payload Pointer (PP) | 引用恰当 |

### 1.4 PAT/PMT（SPEC-103）——核实一致（1 处项目收紧需标注）

| SPEC-103 断言 | 标准原文 | 结论 |
|---|---|---|
| PAT 固定 PID 0x0000，table_id 0x00 | 2.4.3.2 "PID value 0x0000 is reserved for the Program Association Table"；2.4.4.3 "table_id … shall be set to 0x00" | 一致 |
| PMT table_id 0x02 | Table 2-30："0x02 TS_program_map_section"；2.4.4.8 同 | 一致 |
| program_number=0 → network_PID（NIT 项，非 PMT 项） | 2.4.4.3 PAT 语义："If the value of program_number is '0000', then the program_map_PID … indicates the PID … containing the Network Information Table"（语法表中该位置字段名即 network_PID） | 一致 |
| PAT section_length = 9 + 4×N | 由 Table 2-30 语法推算：TSID(2)+ver(1)+sn(1)+lsn(1)=5，+4N，+CRC(4) → 9+4N | 一致 |
| PMT section_length = 13 + program_desc + Σ(5+es_desc) | 由 2.4.4.8 语法推算：固定 9 + prog_desc + Σ(5+es_desc) + CRC(4) → 13+… | 一致 |
| 上限 1021 | 同 §1.3，normative | 一致 |
| version_number 5 bits 0..31；section/last_section_number 8 bits | 2.4.4.2/2.4.4.3（"version_number – This 5-bit field…incremented by 1 modulo 32"） | 一致 |
| PCR_PID=0x1FFF | 2.4.4.8（PMT 语义）："If no PCR is associated with a program definition for private streams, then this field **shall take the value of 0x1FFF**" | **注意**：SPEC-103 §8.6 的校验规则 "PCR_PID 不等于 Null PID" 是**项目收紧**，与标准的显式许可（无 PCR 的私有流允许 0x1FFF）不一致。作为 MVP 生成器约束可接受，但 validator 文案应标注"项目规则，标准允许 0x1FFF"，避免被当作标准断言。 |

### 1.5 PES 与 PTS/DTS（SPEC-104/105）——核实一致

| SPEC-104 断言 | 标准原文 | 结论 |
|---|---|---|
| start code prefix = 00 00 01 + 8-bit stream_id + 16-bit PES_packet_length（big-endian） | 2.4.3.6："packet_start_code_prefix is the bit string '0000 0000 0000 0000 0000 0001' (0x000001)"；Table 2-19 语法一致 | 一致 |
| PES_packet_length 统计紧随 length 字段之后的字节 | 2.4.3.6："specifying the number of bytes in the PES packet **following the last byte of the** [PES_packet_length] **field**" | 一致 |
| PES_packet_length=0 仅允许特定视频 PES（TS 中） | 2.4.3.6："A value of 0 … is allowed only in PES packets whose payload consists of bytes from a video elementary stream contained in Transport Stream packets" | 一致（SPEC-104 表述逐字对应） |
| PTS_DTS_flags：10=仅 PTS，11=PTS+DTS，00=无，01 禁止 | 2.4.3.7："When the PTS_DTS_flags field is set to '10' … '11' … '00' … **The value '01' is forbidden**" | 一致 |
| PTS/DTS 33-bit、90 kHz、5 字节分段编码（prefix 4-bit + 3+15+15 位 + 3 个 marker bit） | Table 2-21（PES optional header 语法）：'0010'(4)+PTS[32..30](3)+marker_bit(1)+PTS[29..15](15)+marker_bit(1)+PTS[14..0](15)+marker_bit(1) = 40 bits = 5 bytes | 一致 |
| PTS-only prefix '0010'；PTS+DTS 时 PTS='0011'、DTS='0001'，两者 prefix 不同 | Table 2-21：if (PTS_DTS_flags=='10') 用 '0010'；if (=='11') PTS 用 '0011'、DTS 用 '0001' | 一致 |
| 所有 marker bit 必须为 1，Parser 校验 | 2.4.3.6："marker_bit – … shall have the value '1'"（1-bit "1" 常量字段） | 一致 |
| 时间比较考虑 33-bit 回绕 | 33-bit 计数器语义（Annex D.0.3 "counting the 90-kHz results in a 33-bit counter"） | 一致 |

### 1.6 措辞级偏差 1：SPEC-100 的 adaptation_field_length 通域表述

SPEC-100 §5.2 先写 "adaptation_field_length … 范围 0..183"，随后用 AFC 分支给出正确约束（AFC=11 至少 1 payload 字节 ⇒ ≤182；AFC=10 占满 184 ⇒ =183）。与标准（AFC='11' 时 0..182、AFC='10' 时恒 183）语义一致，但 §9 测试规格写 "AF length：0、1、183" 未标注 183 仅在 AFC=10 合法。**建议**：在 §5.2 通域句后括注 "AFC=11 时上限 182"。

### 1.7 措辞级偏差 2：SPEC-100 的 transport_scrambling_control 描述

SPEC-100 §3 表格写 "00 clear；01 reserved；10/11 scrambled parity"。ISO/IEC 13818-1:2007 Table 2-4 实际为：

- '00' Not scrambled
- '01' **User-defined**
- '10' **User-defined**
- '11' **User-defined**

即 ISO 表格不区分 01/10/11（均为 User-defined）；"01 保留""10/11 偶/奇钥"是 DVB/行业惯用解读（如 BISS2 规范 EBU Tech 3292 明文要求 TSC 置 '10'(even)/'11'(odd)；DVB TS 100 289/ETR 289 语境同）。**结论：轻微偏差**——实用上没错，但作为"标准结构"表述与包内引用的 H.222.0 表格不一致，建议改为 "00 Not scrambled；01/10/11 User-defined（DVB 惯例 10/11 = 偶/奇钥）"。

---

## 2. ETSI TS 102 773（T2-MI）对照核实

**证据源**：ETSI TS 102 773 V1.4.1 (2016-03) 原文（etsi.org 免费）。

### 2.1 案例 B1（T2MI PLP ID 映射错位）——核实一致

- "T2MI 三级子图（外层 TS Packet → BBFrame → Inner TS）"：TS 102 773 §5.1 规定 T2-MI 包 = 6 字节头（packet_type 8 + packet_count 8 + superframe_idx 4 + rfu 9 + t2mi_stream_id 3 + payload_len 16）+ payload + pad(0..7 bit) + CRC-32。T2-MI 流本身承载于 TS；packet_type=0x01₆ "Baseband Frame" 载荷为 frame_idx(8)+plp_id(8)+intl_frame_start(1)+rfu(7)+BBFRAME(Kbch bits)，且 "It shall be encapsulated into exactly one T2-MI packet"。BBFRAME 数据字段承载内层 TS。三级展开模型与标准吻合。
- plp_id 为 8-bit、每 BBFRAME 一个 PLP："plp_id (8 bits) signals the PLP_ID … in which the Baseband Frame is to be carried in the DVB-T2 signal"。PLP（Physical Layer Pipe）术语正确；"PLP 0 数据/PLP 1 业务"的示例与 T2 的 PLP 概念兼容。TSDuck `t2mi` 插件帮助亦印证："Extract encapsulated TS packets **from one PLP** of a T2-MI stream"。
- "前端 Demux/PLP 分流器错误锁定 PLP 0"场景成立（PLP 选择发生在 T2-MI 解封装/链路层，与内层 TS 解析分层解耦）。

### 2.2 案例 B2（BBHEADER/SYNCD 归属）——有偏差（需订正）

v03 B2 原文："BBHEADER 的长度字段或同步字节（SYNCD）由于传输抖动发生错位……学习 **ETSI TS 102 773** 标准中帧头同步机制与错误传播路径"。

问题：

1. **标准归属错误**：TS 102 773 全文（V1.4.1）**不含** "BBHEADER"、"SYNCD"、"DFL"、"SYNC" 任何一处。BBHEADER 定义在 **EN 302 755（DVB-T2）§5.1.7 "Baseband Header (BBHEADER) insertion"**（Table 2：MATYPE 2 + UPL 2 + DFL 2 + SYNC 1 + SYNCD 2 + CRC-8 1 = 10 bytes；与 DVB-S2 EN 302 307 同构）。TS 102 773 只规定 T2-MI 封装，并把 BBFRAME 原样引用至 EN 302 755 §5.1.7（"shall carry Baseband Frames, in accordance with ETSI EN 302 755 [1], clause 5.1.7"）。案例的知识卡片若引用 TS 102 773 解释 BBHEADER/SYNCD，属于引用错位。
2. **SYNCD 术语理解错误**：SYNCD（2 字节）不是"同步字节"，而是 "**The distance in bits from the beginning of the DATA FIELD to the beginning of the first transmitted UP**"（同步字节距离；SYNCD=0 表示 UP 与数据字段对齐；=65535 表示数据字段内无 UP 起始）。真正的"同步字节"是 1 字节的 SYNC 字段（TS 流时为 0x47 的副本）。案例把 SYNCD 当作"同步字节"应订正。
3. 场景机制层面的提示（错位导致解析边界紊乱、可被 CRC 检出）方向正确：T2-MI 包级有 CRC-32（§5.1/Annex A），BBHEADER 有 CRC-8；"传输抖动导致字段错位"的因果描述偏含糊（抖动不改字节序，应改为"封装端错位/损坏"），但作为教学场景可接受。

**建议订正**：B2 底层根因改为 "BBHEADER（定义于 EN 302 755 §5.1.7）的 DFL/SYNCD 字段或 T2-MI 包头（TS 102 773 §5.1）的 payload_len/packet_count 错位/损坏，CRC-8/CRC-32 校验失败"；标准引用改为 "EN 302 755 §5.1.7（BBHEADER）+ TS 102 773 §5.1（T2-MI 包封装）"。

---

## 3. ETSI TR 101 290：优先级归属与 100ms/40ms 的性质

**证据源**：ETSI TR 101 290 V1.3.1 (2014-07) 原文（etsi.org 免费，链接与包内 TS-CORE-PACKAGE-README 所引完全一致）。v1.3+ 为现行版本线（包内 SPEC-105/107 仅作"后续测量规范参考"，未引具体版本号，无版本引用风险）。

### 3.1 三个优先级的权威归属（Table 5.0a/5.0b/5.0c，V1.3.1）

- **P1（1st priority, necessary for de-codability / basic monitoring）**：
  - 1.1 TS_sync_loss、1.2 Sync_byte_error
  - **1.3 PAT_error**："PID 0x0000 does not occur at least every **0,5 s**"
  - **1.4 Continuity_count_error（CC error）**："Incorrect packet order / a packet occurs more than twice / lost packet"（引 ISO/IEC 13818-1 clauses 2.4.3.2, 2.4.3.3）
  - **1.5 PMT_error**："Sections with table_id 0x02 … do not occur at least every **0,5 s**"
  - 1.6 PID_error
- **P2（2nd priority, recommended for continuous or periodic monitoring）**：
  - 2.1 Transport_error、2.2 CRC_error
  - **2.3 PCR_error / 2.3a PCR_repetition_error**："Time interval between two consecutive PCR values more than **40 ms**"（引 ISO/IEC 13818-4 §9.11.3、**TS 101 154 §4.1.5.3**）
  - 2.3b PCR_discontinuity_indicator_error（">100 ms without discontinuity_indicator"）
  - **2.4 PCR_accuracy_error**："PCR accuracy … not within **±500 ns**"（PCR 抖动测量细节在 §5.3.2：PCR_FO/PCR_DR/PCR_OJ/PCR_AC）
  - 2.5 PTS_error（">700 ms"）、2.6 CAT_error
- **P3（3rd priority, application dependant）**：3.1 NIT_error、3.2 SI_repetition_error、3.3 Buffer_error、3.4 Unreferenced_PID、3.5 SDT_error、3.6 EIT_error、3.8 TDT_error 等 SI 类。

**结论**：CC error → **P1**；PAT/PMT 重复率 → **P1**（阈值 0.5 s）；PCR 重复率 → **P2**（表中阈值 40 ms）；PCR 抖动/准确度 → **P2**（±500 ns）；SI 表重复率 → **P3**。规格包 v0.4 本身未做任何 P1/P2/P3 断言（无编造风险）；以上供 Observation-Metrics（SPEC-301/302/304）实现时引用。

### 3.2 PAT/PMT 100ms、PCR 40ms 与标准限值的关系（Issue #6 的核心疑问）

包内两处出现（均已自我声明为项目值）：

- SPEC-107 §5.2："PAT/PMT period 是仿真配置，不在本 Spec 声称为所有标准 profile 的统一固定值……建议 PAT/PMT 均 **100 ms** 作为初始默认"；§5.3："MVP 建议初始 PCR 目标周期 **40 ms**，预留测量裕量；**这是项目配置建议，不是本模块宣称的标准强制常数**"。SPEC-108 默认 `pat_period_ms=100`、`pmt_period_ms=100`、`pcr_interval_ms=40`。

对照标准原文的准确关系：

| 数值 | 性质 | 标准出处 |
|---|---|---|
| PAT/PMT **0.5 s** | **TR 101 290 P1 报警阈值**（标准值） | TR 101 290 V1.3.1 Table 5.0a（1.3/1.5） |
| PAT/PMT **100 ms** | **TS 101 154 §4.1.7 的建议**（"the interval between two sections should not exceed 100 ms. For many applications it may be sufficient to check that the interval is not longer than 0,5 s"——见 TR 101 290 Table 5.0a Note 3）；比 TR 101 290 P1 阈值严格 | TS 101 154 §4.1.7（经 TR 101 290 注释引用） |
| PCR **100 ms** | **ISO/IEC 13818-1 规范限值**（2.7.2 "Frequency of coding the program clock reference"："the time interval … successive occurrences of the PCRs … **shall be less than or equal to 0.1 s**"）；现行 DVB 也回归此值 | ISO/IEC 13818-1 §2.7.2；TR 101 290 Table 5.0b Note 2 |
| PCR **40 ms** | **旧 DVB 建议**：TS 101 154 §4.1.5.3（2005 年前版本），**2005 年已从 TS 101 154 移除**、放宽为引用 ISO 的 100 ms（TR 101 290 Note 2 原文："The limitation to 40 ms … was removed from TS 101 154 in 2005. The respective clause there now refers only to the 100 ms limitation in [i.1] which is recommended to be applied generally"；正文 "In DVB a repetition period of not more than 100 ms is permitted, previously a maximum of 40 ms was recommended"）。但 TR 101 290 V1.3.1 Table 5.0b 的 2.3/2.3a 前置条件仍印 40 ms 并附上述 Note 2 | TS 101 154 §4.1.5.3（已改）；TR 101 290 V1.3.1 Table 5.0b + Note 2 |

**结论**：
1. PCR 40ms 与 TR 101 290 的关系 = **"TR 101 290 P2 (2.3/2.3a) 表内阈值，但源自已废止的旧 DVB 建议，现行 DVB/ISO 限值为 100 ms"**。包内把它作为生成端默认目标周期（比现行限值更严，保证合规且留测量裕量）并明确声明"不是标准强制常数"——**表述属实、无不实引用**。
2. PAT/PMT 100ms 是**项目自选默认值**（恰好与 TS 101 154 §4.1.7 的 100 ms 建议一致、比 TR 101 290 P1 的 0.5 s 严格），同样已自我声明。**核实一致**。
3. 建议在 SPEC-107 §5.2/5.3 补一句出处注释（"100 ms ≈ TS 101 154 §4.1.7；0.5 s = TR 101 290 P1 阈值；40 ms = 旧 DVB 建议已放宽为 100 ms（ISO 13818-1 §2.7.2）"），把"项目值与标准值的对应关系"写死，防止后续开发者误读。

---

## 4. EN 50494 / EN 50607（Unicable）对照核实

**证据源**：CENELEC 标准正文为付费文档，无法获取原文；采用多来源交叉验证（标准条目页、厂商白皮书/数据表、开源实现文档）。可信度：术语与架构层面**高**；具体条款号**不可核实**（报告中不引用）。

### 4.1 案例 A1（SCR 槽位冲突）——概念核实一致，术语有偏差

v03 A1 原文："两个 Tuner 被分配了相同的 **SCR（Subscriber Channel Radio）** 槽位频率（例如均占用 1210 MHz），导致下发单向 DiSEqC 调谐指令时发生本振频率冲突"。

| 断言 | 核查结果 | 结论 |
|---|---|---|
| SCR 展开名 "Subscriber Channel Radio" | **错误**。SCR = **Satellite Channel Router**（EN 50494 术语；Unicable 为 Inverto 注册商标）。Televes 目录词条："SCR: Satellite Channel Router EN 50494 (Unicable)" | **偏差**（术语） |
| "槽位频率"（User Band 槽位）模型 | 正确。EN 50494 定义固定 User Band（UB）频率；EN 50607（dCSS/Unicable II）扩展至最多 **32 个 user band**、IF 范围扩展至 950–2400 MHz；EN 50494 通常 4–8 个 UB、950–2150 MHz | 一致 |
| 1210 MHz 示例 | 合理。EN 50494 典型 UB 频率即包含 1210 MHz（常见出厂默认组 1210/1420/1680/2040 MHz） | 一致 |
| 两个 tuner 占同一 UB → 冲突/No Lock | 正确。SCR 设备每个 UB 同一时间只能堆叠一个 transponder；两接收机共享同一 UB 会互相干扰，属经典 Unicable 配置故障 | 一致 |
| "下发单向 DiSEqC 调谐指令" | 基本正确：EN 50494 使用单向 DiSEqC 消息承载 UB 频率+卫星/极化/频段；EN 50607 dCSS 引入双向（ODU_reply）。v1 描述偏向 EN 50494 | 一致（措辞可细化） |
| "本振频率冲突" | 措辞欠精确：冲突本质是**两个接收机的 IF 请求落在同一 UB 上导致堆叠互相破坏**，不是 LNB 本振冲突 | 措辞建议 |

**建议订正**：把 "SCR（Subscriber Channel Radio）" 改为 "SCR（Satellite Channel Router，EN 50494）/ User Band（EN 50607 dCSS 语境下称 UB 槽位）"；"本振频率冲突"改为 "同一 User Band 被两个接收端同时占用，SCR 堆叠的 IF 信号互相干扰导致无法锁定"。

---

## 5. BISS 对照核实（v03 案例 C1）

**证据源**：EBU Tech 3292 v3（BISS2）与 EBU Tech 3292-s1（BISS-CA）原文（tech.ebu.ch 免费下载）；MediaKind/Advantech 设备文档、Wikipedia（BISS-E）、TSDuck 3.40 实测。可信度：EBU 原文层面**高**；BISS1（原始 BISS/BISS-E）的 12 位密钥惯例为多来源一致的**行业事实**（原始 BISS1 详细规范未公开发布，公开资料有限——按任务要求标注可信度）。

### 5.1 案例核查

| v03 C1 断言 | 核查结果 | 结论 | 可信度 |
|---|---|---|---|
| "输入了 16 **字节** BISS 密钥" | **不符**。BISS Mode 1（BISS1）密钥为 **12 位十六进制 session word（48 bit = 6 字节）**；BISS-E 下发/输入的 ESW 为 16 位十六进制（64 bit = 8 字节）；BISS2 Mode 1 的 SW 为 32 位十六进制（128 bit = 16 字节）。"16 字节" 只对 BISS2 的 SW/Injected ID 成立，对最常见的 BISS1/BISS-E 密钥均错误 | **偏差** | 高（EBU 原文 + 设备手册一致） |
| "BISS Mode E：除了基础密钥（Session Word）外，还**包含一个动态的注入私有数据（Injected ID / Buried ID）**" | **不符（两处）**：① Injected/Buried ID 是**预置在接收端**的静态 128-bit 标识（Tech 3292-s1: "The Injected ID or Buried ID … a 128 bit unique identifier … This ID remains unchanged and inaccessible to the operators once inserted"），**不在流中传输**、不是"动态"的；流中传输的是 **ESW**（加密后的 SW）。② Mode E 的机制 = SW 用固定 Session Key 加密成 ESW 后带外下发，接收端用 ID 解出 SW | **偏差** | 高 |
| "PES Start Code Valid: Failed" 作为解密失败的证据症状 | 方向正确：错误密钥解出的数据无法呈现合法 PES 头（0x000001 前缀校验失败是合理观测点） | 一致（合理的教学叙事） | — |
| "掌握 BISS Mode 1 与 Mode E 的底层密钥结构差异" | 差异真实存在：Mode 1 明文 SW；Mode E 加密 SW（ESW）+ 接收端 ID 解密 | 一致（教学目标成立） | — |
| 案例 C2 提到 "ECM（群控信息）" | "群控"为对 Conditional Access 的不准确翻译（ECM = Entitlement Control Message，授权控制信息）；且 BISS 无 ECM（Tech 3292: BISS2 Mode 1/E 的 CA_PID 固定 0x1FFF，"no ECM information is required"）——C2 场景混入 ECM 概念与 BISS 语境不符 | 轻微偏差 | 高 |

### 5.2 补充事实（供知识卡片使用，均出自 EBU 原文）

- 底层加扰算法：BISS1 = **DVB-CSA1**（加扰）+ DES（session word 加密）；BISS2 = **DVB-CISSA**（ETSI TS 103 127）+ **AES-128**（Tech 3292 §定义表）。
- BISS 模式族（Tech 3292-s1）：Mode 0 / Mode 1 / Mode E / Mode CA（BISS-CA）。
- BISS2 的 CA_system_ID = 0x2602，Mode 1/E 无 ECM（CA_PID=0x1FFF）。
- Injected ID 可多机注入（冗余）、不可读回（Tech 3292 §4.3.1）；Buried ID 由厂商与设备唯一绑定。
- **TSDuck 3.40-4165 的 descrambler 插件不支持 BISS**（实测 `tsp -P descrambler --help`：仅 DVB-CSA2（默认）、AES-CBC/CTR、ATIS-IDSA、DVB-CISSA）。v0.3 "实况模式复用 TSDuck 解 BISS" 的设想不成立：BISS1 是 CSA1，可经 libdvbcsa（CSA 实现）配合固定 CW 实现；BISS2 需 CISSA/AES 实现。这对 v0.3/v0.4 的技术选型叙述（G4 案例、R4 风险项）是必要订正。

---

## 6. TSDuck 官方文档对照

| 机制 | TSDuck 侧证据（本机 3.40-4165 实测 + tsduck.html） | 与规格包一致性 |
|---|---|---|
| TS Packet / 188B / CC | tsduck.html 及 doxy 提供 `ts::TSPacket`（SPEC-100 引用链接存在且指向正确文档族）；`tsplugin_descrambler.dll` 等插件齐备 | 一致 |
| T2MI | `tsp -P t2mi --help`："Extract T2-MI (DVB-T2 Modulator Interface) packets"；`--extract`："Extract encapsulated TS packets from one PLP of a T2-MI stream"；`--identify` 列出 PID/PLP。与 v03 B1 的三级模型一致 | 一致 |
| PCR 校验 | `tsp -P pcrverify`："Verify PCR's from TS packets"（另有 pcrcopy/pcrbitrate/pcradjust）。TSDuck 生态确实把 PCR repetition/accuracy 视为**分析/测量**功能而非编码规则——与 SPEC-105/107 "不在编码层硬编码 TR 101 290 阈值" 的职责划分一致 | 一致 |
| BISS | descrambler **无 BISS 选项**（DVB-CSA2/AES-CBC/CTR/ATIS-IDSA/DVB-CISSA） | v0.3 设想需修正（见 §5.2） |
| PAT/PMT/PSI | `pat`/`pmt`/`psi`/`tables` 插件与 `tsanalyze` 存在，与 SPEC-103 交付要求（"可被 TSDuck 识别的 .ts fixture"）兼容 | 一致 |

---

## 7. v0.3 案例 D2（顺带核查）——有偏差

D2 原文："PCR 间隔严重违反 ISO/IEC 13818-1 标准（**Jitter > 500ms**），导致解码器 PLL 失锁"。

- ISO/IEC 13818-1 对 PCR **间隔**的规范限值是 **0.1 s = 100 ms**（§2.7.2，normative；Annex D.0.3 同样给出 100 ms）。
- **500 ms 不对应任何 ISO 间隔限值**；±500 ns 是 TR 101 290 **PCR_accuracy_error**（P2）的**抖动/准确度**阈值——比间隔限值小六个数量级，是另一个量。D2 把 "间隔违反" 与 "Jitter" 混用，且数值两头不靠。
- 建议改为："PCR 间隔超过 ISO/IEC 13818-1 §2.7.2 的 100 ms 限值（或 PCR 抖动超出 TR 101 290 P2 ±500 ns）"。

---

## 8. 需订正清单（汇总，供基线批准 ticket 逐条处理）

1. **v03 B2**：BBHEADER/SYNCD 出处由 "TS 102 773" 改为 "EN 302 755 §5.1.7"；SYNCD 改述为"数据字段内首个 UP 的位距离（sync distance）"，非"同步字节"；T2-MI 包级机制（packet_count/payload_len/CRC-32）可补充为 TS 102 773 §5.1 的正确引用点。
2. **v03 A1**：SCR 展开名改为 "Satellite Channel Router"；"本振频率冲突"改为"同一 User Band 被两个接收端占用导致堆叠干扰"。
3. **v03 C1**："16 字节 BISS 密钥"改为 "BISS Mode 1：12 位十六进制（48-bit）session word；BISS-E：16 位十六进制 ESW + 静态 128-bit Injected/Buried ID（预置于接收端，不在流中）"；删除 "动态注入私有数据（流内）" 表述；C2 的 "ECM（群控信息）" 与 BISS 无 ECM 语境冲突。
4. **v03 D2**："Jitter > 500ms" 改为 "PCR 间隔 > 100 ms（ISO/IEC 13818-1 §2.7.2）"，或单独用 "PCR 抖动 > ±500 ns（TR 101 290 P2）"。
5. **SPEC-100 §3 表格**：transport_scrambling_control 行改为 ISO Table 2-4 措辞（00 Not scrambled；01/10/11 User-defined，注 DVB 惯例 10/11=偶/奇钥）；§5.2 通域 AF length 句补 "AFC=11 时 ≤182"；§9 测试项 183 标注仅 AFC=10。
6. **SPEC-103 §8.6**："PCR_PID 不等于 Null PID" 标注为项目收紧规则（标准 2.4.4.8 明确允许无 PCR 私有流取 0x1FFF），避免被当作标准断言。
7. **SPEC-107 §5.2/5.3**（可选增强）：为 100ms/40ms 补标准值对照注释（见 §3.2 结论 3），写明 "0.5 s = TR 101 290 P1 阈值；100 ms = TS 101 154 §4.1.7 建议与 ISO §2.7.2 限值；40 ms = 已废止旧 DVB 建议（TR 101 290 P2 表内保留）"。
8. **技术选型叙述（v03/R1-R4 相关）**：TSDuck descrambler 不支持 BISS；BISS1 可经 libdvbcsa（CSA1）实现，BISS2 需 CISSA/AES-128 自研或第三方实现。

---

## 9. 来源

**标准原文（本次逐条核对）**
- ITU-T H.222.0 (05/2006) = ISO/IEC 13818-1:2007（itu.int 官方免费）：https://www.itu.int/rec/dologin_pub.asp?lang=e&id=T-REC-H.222.0-200605-S!!PDF-E&type=items （现行版 H.222.0 (04/2025) 第 10 版存在性经检索确认：https://www.itu.int/rec/T-REC-H.222.0 ）
- ETSI TR 101 290 V1.3.1 (2014-07)：https://www.etsi.org/deliver/etsi_tr/101200_101299/101290/01.03.01_60/tr_101290v010301p.pdf
- ETSI TS 102 773 V1.4.1 (2016-03)：https://www.etsi.org/deliver/etsi_ts/102700_102799/102773/01.04.01_60/ts_102773v010401p.pdf
- ETSI EN 302 755 V1.3.1（BBHEADER §5.1.7）：https://www.etsi.org/deliver/etsi_en/302700_302799/302755/01.03.01_60/en_302755v010301p.pdf
- ETSI EN 300 468 V1.20.1（TOT 短格式+CRC 例外）：https://www.etsi.org/deliver/etsi_en/300400_300499/300468/01.20.01_60/en_300468v012001p.pdf
- EBU Tech 3292 v3（BISS2，Mode 1/E/CA、Injected/Buried ID、CA_system_ID 0x2602）：https://tech.ebu.ch/docs/tech/tech3292.pdf
- EBU Tech 3292-s1（BISS-CA，128-bit Injected/Buried ID 定义）：https://tech.ebu.ch/docs/tech/tech3292s1.pdf
- RFC 4259 "A Framework for Transmission of IP Datagrams over MPEG-2 Networks"：https://www.rfc-editor.org/rfc/rfc4259.txt

**Unicable / BISS 二手权威来源（EN 50494/50607 原文付费，BISS1 公开资料有限）**
- EN 50607:2015 条目（up to 32 receivers，256 IF banks，DiSEqC/JESS/dCSS）：https://standards.iteh.ai/catalog/standards/clc/1fe0792f-0ad5-4f1f-bb40-f3a9a47790dc/en-50607-2015
- Televes 目录（"SCR: Satellite Channel Router EN 50494 (Unicable)"）：https://docs.televes.com/web/catalogo/pdf/katalog_2014_15_de_1.pdf
- Inverto Unicable II 32-UB 设备数据表（950–2400 MHz）：https://www.inverto.tv/download/file/598c924eb6bb1-1502384718.pdf
- MuMuDVB Unicable/EN 50494 实现（UB 0 = 1210 MHz 示例）：https://github.com/braice/MuMuDVB/issues/46
- Wikipedia BISS-E（12-hex SW 概述）：https://en.wikipedia.org/wiki/BISS-E
- MediaKind BISS 解密模式文档（BISS1 12-digit CSW；BISS-E ESW）：https://docs.mediakind.com/beam/receiver/decryption/biss-decryption-modes
- Helion DVB-CSA 核（"CSA (BISS) Mode 1 and Mode E"）：行业佐证，BISS 基于 CSA

**本地核对对象**
- `temp/DVB-Sandbox-Spec-v0.4-Complete/docs/modules/ts-core/SPEC-100/102/103/104/105/107/108`、`TS-CORE-PACKAGE-README.md`、`docs/modules/REGISTRY.md`、`docs/modules/simulation/SPEC-205-scenario-engine.md`（"Do not invent ETSI/ITU clause numbers"）
- `temp/v03.md`（案例 A1/B1/B2/C1/C2/D2）
- TSDuck 3.40-4165：`D:\Program Files\TSDuck\doc\tsduck.html`、`tsp -P t2mi/descrambler/pcrverify --help` 实测输出

**方法说明**：ISO/IEC 13818-1 的 ISO 付费版本未使用；ITU-T H.222.0 为 JTC1 联合文本（内容同一），且包内自身引用的即 H.222.0，以官方免费 2006 版逐条核对（相关位级条款历版稳定）。EN 50494/EN 50607 正文付费，相关结论标注为二手来源交叉验证；TR 101 290/TS 102 773/EN 302 755/EN 300 468/EBU 3292 系列均为原文核对。
