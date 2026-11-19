# DiSEqC 总线与命令模型调研报告（Phase 3，GitHub Issue #144）

- **调研票**：[#144](https://github.com/BingChaoLiu/DVB-Nexus/issues/144)（Phase 3 地图 [#143](https://github.com/BingChaoLiu/DVB-Nexus/issues/143) 子票）
- **调研日期**：2026-11-20
- **调研方式**：本机（Windows 10.0.26300 x64，TSDuck 3.45-4798）实测 + TSDuck 上游源码核查（GitHub tsduck/tsduck）+ Eutelsat DiSEqC Bus Functional Specification v4.2 原文逐条抽取（免费镜像 PDF，已完整性核验）+ 免费二级权威交叉验证（TI 应用报告）
- **置信标注纪律**：每条结论标注证据路径——`[实测]` = 本机命令行实测；`[原文]` = 标准原文逐条核对（本次已下载核验完整性）；`[文档]` = 文档/源码引用（未在本地复核原文）；`[推断]` = 由以上推出的工程判断。三者不混标。
- **诚实门标注**：本机无 DVB 硬件，一切依赖调谐设备的路径标 **NOT RUN**（照 CI 诚实门先例）。
- **前次执行说明**：本票为第二次执行，前次会话因网络截断中断；本次所有下载产物均按「Content-Length 一致 + PDF 页数>0 + 文本非空」核验后才使用。

---

## 0. 结论速览

| # | 问题 | 结论 | 置信 |
|---|---|---|---|
| 1 | DiSEqC 1.x/2.x 命令字节集权威出处 | **Eutelsat DiSEqC Bus Functional Specification v4.2（1998-02-25）是唯一权威原文**；1.0/1.1/1.2/2.0 是规范内的 Implementation Levels，不是四份独立文档。免费镜像可得（本会话已下载核验，222KB / 28 页） | [原文] |
| 2 | 原版 Eutelsat 下载 URL | TSDuck 源码注释引用的 `eutelsat.com/files/PDF/DiSEqC-documentation.zip` **已 404**（HEAD 实测）；spec 文本靠镜像存续 | [实测] |
| 3 | 总线语义 | 单 master 单/多 slave；1.x 单向（无 reply），2.x 双向（slave reply ≤150ms）；报文 = framing + address + command (+ data)，每字节 + 奇校验，MSB 先 | [原文] |
| 4 | 时序常量 | 位时序 500µs PWK（'0'=1.0ms/'1'=0.5ms）；报文结束 ≥6ms 静默；组合信令间隙 >15ms；级联 bus 供电远端从机 ≥100ms 初始化；双向 reply 等待窗口 150ms | [原文] |
| 5 | 多路开关/tuner 供电交界 | 13V/18V × 22kHz 连续音 = 供电+频段+极化的模拟交界（v4.2 §5.1 兼容语义 + TI 交叉验证）；Tone Burst（A/B）= 前数字化兼容信号；「至多一条 DC 通路」规则（§7.1）是多路开关的硬约束 | [原文] |
| 6 | EN 50494/50607（Unicable） | 正文付费（roadmap §5 既裁）；命令级细节可由 TSDuck 上游源码（tsUnicable.h + configUnicableSwitch）佐证：EN50494 = 0xE0 0x00 0x5A + 调谐字公式，EN50607 = 0x70 无框架字节；具体条款号**待原文核对** | [文档] |
| 7 | TSDuck 插件面（Windows 实测） | 112 个插件（13 input + 13 output + 86 processor）与 43 个命令行工具中**无任何 DiSEqC/SEC 专用插件或工具**；SEC 语义只存在于 `dvb` 输入插件的卫星调谐选项内 | [实测] |
| 8 | TSDuck Windows 实现行为 | **Windows 上不发送真实 DiSEqC 命令**：`--satellite-number` 仅映射为 BDA locator 属性（上游源码注释直言 "most drivers ignore it"）；Unicable 命令构造仅存在于 Linux 实现 | [文档]（源码）+ [实测]（无硬件，NOT RUN） |
| 9 | TSDuck 适用性结论（照 #104 收窄先例） | TSDuck **不能**作为 SPEC-622 DiSEqC Controller 的实现参考或验证器（无插件面、无 TS/事件/JSON 观测面、Windows 不发命令）；可借鉴的只有 `tsduck.lnbs.xml` / `tsLNB.h` 的 LNB 波段转置模型（对 SPEC-621 更有价值） | [推断] |
| 10 | 硬件路径 | 本机 `tslsdvb` 报 "no DVB device found"——全部硬件行为实测 **NOT RUN** | [实测] |

---

## 1. 标准原文可得性盘点（逐项核实）

### 1.1 Eutelsat DiSEqC 文档族

v4.2 规范首页给出的 DiSEqC 系统定义文档与关联文档（[原文]，bus_spec.pdf 参考文档页）：

| 文档 | 版本 | 日期 | 可得性（本次核实） |
|---|---|---|---|
| DiSEqC Bus Functional Specification | **4.2** | 1998-02-25 | ✅ **免费镜像可得**：https://educypedia.org/library/bus_spec.pdf （222KB/28 页，Content-Length 一致、PDF 头完好、文本抽取正常，本会话逐条抽取） |
| DiSEqC Bus Specification | 4.2 | 1998-02-25 | 未单独核验（与上为姊妹文档） |
| DiSEqC Slave Microcontroller Specification | 1.0 | 1998-02-25 | ❌ 免费镜像未核验到（educypedia 仅 bus_spec.pdf） |
| DiSEqC Logos and Their Conditions of Use | — | 1998-02-25 | ❌ 同上 |
| Update and Recommendations for Implementation | 2.1 | 1998-02-25 | ❌ 原文引用多处（§5.3/§9.2），免费镜像未核验（narod.ru 镜像连接被 reset） |
| Application Information for Tuner-Receiver/IRDs | — | 1996-04-12 | ❌ 免费镜像未核验（v4.2 §5.4 引用其 §5.2） |
| Application Information for LNBs and Switchers | 2 | 1998-02-25 | ❌ 免费镜像未核验 |
| Positioner Application Note | 1.0 | 1998-03-15 | ❌ 未核验 |

关键澄清（订正票面表述）：

- **「DiSEqC 1.0/1.1/1.2/2.0」是 Implementation Levels（实现级别），不是四份可分别下载的规范文档**。同一份 Bus Functional Specification v4.2 的 §8.3 命令表按 Level 标注每个命令的 M/R/S 地位（M = 该 Level 强制），全部 level（1.0/1.1/1.2/2.0/2.1/2.2）由这一份文档定义。[原文]
- Implementation Level 谱系（v4.2 文档 + TI slva863 表 1 交叉验证，[原文]+[文档]）：
  - **1.0**：单向，committed switches（4 端口），与 13/18V、22kHz 向后兼容
  - **1.1**：单向，增加 uncommitted switches（16 端口）与重复报文机制
  - **1.2**：单向，增加单轴位置器（positioner）命令族（0x60~0x6F）
  - **2.0/2.1/2.2**：分别为 1.0/1.1/1.2 增加双向（reply）能力
  - 3.0：广播机房远端管理（Wikipedia 谱系；v4.2 文档未含 3.0——其后发布，来源待考，不引条款）
- Bus Functional Specification 的**文档**版本史至 v4.2 为最终发布版（v4.2 §0 自述："minor corrections and some additions to the Version 4.1 Specification dated April 18th, 1997"；历史版本 3.x 1996-03 的镜像存在但本次连接被 reset 未核验）。
- **原版下载 URL 已死**：TSDuck 上游源码注释引用的 `https://www.eutelsat.com/files/PDF/DiSEqC-documentation.zip` 实测 **HTTP 404**（HEAD，2026-11-20）[实测]。Eutelsat 站点重组后该文档族不再官网提供；Wikipedia 外链记录了 Internet Archive 存档路径 [文档]，但 archive.org 在本机当前网络不可达（连接超时，未核验——此为本机网络事实，非存档不存在）。

### 1.2 相关标准与权威二手来源

| 文档 | 主题 | 可得性 | 置信 |
|---|---|---|---|
| CENELEC EN 50494（Unicable I） | SCR/User Band | **正文付费**（roadmap §5 既裁）；术语层已核实（Satellite Channel Router、UB 槽位） | 待原文核对条款号 |
| CENELEC EN 50607（Unicable II / dCSS） | 32 UB | 同上（扩展至 32 UB、950–2400 MHz） | 待原文核对条款号 |
| CEI EN 61319-1:1999 | 接收设备互连；**table ZB.1** = tone burst / DiSEqC 1.0 组合编号建议 | TSDuck 源码引用其 table ZB.1（tone burst A/B 与 satellite-number 低位组合惯例）；IEC/CENELEC 正文本会话未获取 | [文档]；原文**待核对** |
| ETSI TR 102 252 V1.1.1 | SMATV/MATV DiSEqC 控制信道指南（informative），引用 Bus Functional Spec v4.2 | ETSI 免费模式成立，但本会话 etsi.org 两次连接失败（SSL 超时/reset），未完成下载核验；标题/版本经检索确认 | [文档]（未本地复核） |
| TI SLVA863 "DiSEqC Protocol and LNB Voltage Regulator TPS65235" | 厂商应用报告：level 阶梯、13/18V×22kHz 矩阵、帧结构、时序 | ✅ 免费下载（ti.com，1.3MB/11 页，本会话核验完整） | [文档]（原文级二手权威） |
| Linux DVB API（linuxtv.org V3/V5 文档） | `FE_SET_TONE`/`FE_SET_VOLTAGE`/`FE_DISEQC_SEND_BURST`/`FE_DISEQC_SEND_MASTER_CMD` ioctl 与 `dvb_diseqc_master_cmd` 结构 | 免费在线；本会话经 TSDuck 源码注释核实其接口形态（Phase 4 才相关） | [文档] |

> **Unicable 免费替代来源缺口**：EN 50494/50607 付费的结论维持 roadmap §5 不变；本调研新增的补偿来源是 TSDuck 上游源码的命令构造实现（§5），其注释明确引用 EN 50494/50607 的调谐字公式——条款号级引用仍须购买原文核对。

---

## 2. DiSEqC 命令字节集（SPEC-622 命令状态机素材）

以下全部为 Bus Functional Specification v4.2 原文抽取（[原文]；对应条款见行内）。

### 2.1 报文结构（§6）

```
Master 命令:  FRAMING P  ADDRESS P  COMMAND P  DATA P ...
Slave 回复:   FRAMING P  DATA P ...
```

- 每字节后随**奇校验位**；MSB 先发（§6）。
- **Framing byte（§6.1/§8.1）**：高 4 位恒 `'1110'`；bit5 保留 '0'；bit6 = 0 master 命令 / 1 slave 回复；bit7 = 1 要求回复 / 0 不要求；bit8 = 1 重发（master）/ 回复失败原因限定（slave）。

| Framing | 含义 |
|---|---|
| `0xE0` | Master 命令，无需回复，首次发送 |
| `0xE1` | Master 命令，无需回复，重发 |
| `0xE2` | Master 命令，要求回复，首次发送 |
| `0xE3` | Master 命令，要求回复，重发 |
| `0xE4` | Slave 回复，OK |
| `0xE5` | Slave 回复，命令不被支持 |
| `0xE6` | Slave 回复，奇校验错——请求重发 |
| `0xE7` | Slave 回复，命令不能识别——请求重发 |

- **Address byte（§6.2/§8.2）**：高 nibble = family（LNB/开关/SMATV=1x，极化器=2x，位置器=3x，安装辅助=4x，OEM=Fx），低 nibble = sub-type；`0` = wildcard。常用：`0x00`（所有设备）、`0x10`（任何 LNB/开关/SMATV）、`0x71`（智能从机接口）。
- **Command byte（§8.3）**：核心子集（完整表见原文 §8.3，28 条 + 保留位）：

| 命令 | 名称 | Level 地位 | 功能 | 总字节数 |
|---|---|---|---|---|
| `0x00` | Reset | M/1.0 | 复位从机微控制器 | 3 |
| `0x02`/`0x03` | Standby / Power on | R/1.0 | 外设电源关/开 | 3 |
| `0x10` | Status | R/2.0 | 读状态寄存器（reply = Status byte） | 3 |
| `0x11` | Config | R/2.0 | 读配置寄存器 | 3 |
| `0x14`/`0x15` | Switch 0 / Switch 1 | R/2.0 | 读 committed / uncommitted 开关状态 | 3 |
| `0x20`~`0x27` | Set Lo/VR/PosA/S0A/Hi/HL/PosB/S0B | R/1.0 | 单开关位置位族（本振/极化/卫星位/选项位） | 3 |
| `0x28`~`0x2F` | Set S1A~S4B | R/1.1 | 单开关位置位族（S1~S4） | 3 |
| `0x38` | **Write N0** | **M/1.0** | 写 Port Group 0（committed switches） | 4 |
| `0x39` | **Write N1** | **M/1.1** | 写 Port Group 1（uncommitted switches） | 4 |
| `0x48`/`0x49` | Write A0/A1 | R/1.2 | 写模拟量（极化 skew） | 4 |
| `0x58` | Write Freq | M/1.1 | 写信道频率（BCD，addr 0x71） | 5/6 |
| `0x60` | Halt | M/1.2 | 位置器停转 | 3 |
| `0x63`/`0x66`/`0x67` | Limits Off / Limit E / Limit W | M/1.2 | 软限位管理 | 3 |
| `0x68`/`0x69` | Drive East / Drive West | M/1.2 | 驱动电机（参数 = 秒数或步数） | 4 |
| `0x6A`/`0x6B` | Store nn / Goto nn | M/1.2 | 存储/前往卫星位置 nn | 4 |

- **Write Port Group 数据字节语义（§9.1）**：高 nibble 先应用 = **清零**对应开关线；低 nibble 后应用 = **置位**。惯用法：高 nibble 写 `1111` 全清后由低 nibble 定义目标态（TSDuck Linux 实现即用 `0xF0 | bits` 形态，两方互证）。
- **回复语义（2.x）**：reply framing `E4`（OK）+ 0~N 数据字节；§6 规定 slave 应在命令报文结束后 **≤150ms** 内回复；失败命令建议重发一次。

### 2.2 上游实现佐证（TSDuck Linux dishControl，[文档]）

TSDuck `src/libtsduck/dtv/broadcast/linux/tsTunerDevice.cpp`（3.42 起）的实际命令构造与 v4.2 一致：

- DiSEqC 1.1 未提交端口：`E0 10 39 F0|(satnum>>2)`（16 端口）
- DiSEqC 1.0 已提交端口：`E0 10 38 F0|(satnum<<2)|(H?2:0)|(band?1:0)`（极化=bit1、频段=bit0 的编码与 v4.2 §8.3 `2x` 族语义一致）
- Tone burst A/B：在 DiSEqC 命令之后发送（注释引用 v4.2 §5.3）；`satnum & 0x01` 组合惯例引用 CEI EN 61319-1:1999 table ZB.1
- 时序：命令间 15ms 静默；1.1 命令后 100ms（注释引用 v4.2 §5.4 级联 bus 供电从机初始化）

---

## 3. 总线语义：单向/双向与 reply 时序

[原文] 全部来自 v4.2（条款见行内）：

| 语义点 | 规范内容 | 条款 |
|---|---|---|
| 主从模型 | **单 master、单/多 slave**；只有 master 发起通信（slave 永不主动） | §2 |
| 单向（1.x） | master 不要求 reply（framing bit7=0），bus 保持空闲；1.x 接收机收不到从机通信 | §6、§5.3 |
| 双向（2.x） | framing bit7=1 要求 reply；slave **≤150ms** 回复；正常 reply = 单 acknowledge 字节（`E4`），带数据命令再加数据字节 | §6 |
| 位时序 | 22kHz（±20%）载波上的 PWK：位周期 500µs±100µs；`'0'` = 1.0ms 音（22 cycles）、`'1'` = 0.5ms（11 cycles）；报文结束 ≥6ms 静默 | §5 |
| 组合信令时序（1.0 与模拟信令共存） | 电压切换 → >15ms 间隙 → DiSEqC 报文（典型 54ms）→ >15ms → Tone Burst（12.5ms）→ >15ms → 恢复连续音；双向时 master 为等 reply 须留 ≥150ms 间隙（实际通常更早回，此后 Tone Burst 可在 15ms 后发） | §5.3 Figure 3 |
| 级联开关 | 「近端」开关可能切掉「远端」设备供电/总线 → 远端命令需**重复发送**；bus 供电的远端从机须 ≥100ms 初始化暂停 | §5.4 |
| 碰撞仲裁（2.x） | 同址从机回复前随机监听 15~115ms；检测到他人 reply 则设 Contention flag；flag 置位期间延后 ~130ms 再回 | §7.3 |
| 电源/Standby | **至多一条 DC 通路**（多路开关必须断 DC 转接），防止 master 电源过载；从机上电即正常模式（1.0 无需 Standby Off） | §7.1 |
| 总线硬件 | DC 供电长期推荐 12±1V（intro 期容忍至 20V；保留 13/18V 兼容）；master 供电能力 ≤500mA；22kHz 信号 650mV±250mV pp；双向时 master 源阻抗 15Ω；总线负载 ≤250nF | §4 |

**对 L0 的含义**（[推断]）：1.x 的命令模型是**纯单向投影**——master 发出命令即完成语义（无 ACK 通道），L0 求值器可将其建模为「命令 → 状态迁移」的确定性函数；2.x 才引入异步 reply 窗口（150ms）与仲裁语义，可作为后续扩容。

---

## 4. 多路开关与 tuner 供电交界（A2 靶场素材）

### 4.1 模拟交界：13/18V × 22kHz（[原文]+[文档] 交叉）

DiSEqC 的全部信令都叠加在供电与 22kHz 音调的模拟交界上（v4.2 §5.1「DiSEqC 数据可叠加在 13 或 18V 供电上，也可插在连续 22kHz 音调之间，前后须留短静默间隙」）。供电矩阵（TI SLVA863 表 4 交叉验证，与 Universal LNB 行业惯例一致）：

| 供电 | 频段 | 极化 |
|---|---|---|
| 13V | Low band | Vertical / Right |
| 18V | Low band | Horizontal / Left |
| 13V + 22kHz 连续音 | **High band** | Vertical / Right |
| 18V + 22kHz 连续音 | High band | Horizontal / Left |

- Tone Burst（"Mini DiSEqC"）：unmodulated burst = Satellite A、modulated（0xFF 形态，12.5ms）= Satellite B；**在 DiSEqC 数据 burst 之后、连续音恢复之前**发送（§5.2）——TSDuck Linux 实现顺序与此一致。
- 22kHz 信令幅度：650mV±250mV pp；检测下限 ~300mV；≥100mV 的噪声不得误检（§4）。

### 4.2 多路开关的状态要素（SPEC-622 端口模型素材）

多路开关（multi-switch）的受控状态由四层正交要素组成（[原文] v4.2 §9.9/§9.10 的 Committed/Uncommitted 寄存器位定义）：

1. **Committed switches**（0x38 可控）：本振高低（Low/Hi）、极化（V/H）、卫星位置 A/B、选项开关 A/B——对应 13/18V×22kHz 模拟交界的数字化扩展
2. **Uncommitted switches**（0x39 可控）：S1~S4 四条通用开关线（16 端口级联）
3. **Positioner**（0x6x 族，1.2）：东/西驱动、软限位、位置存储
4. **电源管理**（0x02/0x03 Standby/Power on + §7.1 单 DC 通路规则）

**A2 案例（22kHz 持续音调残留）的标准级解释链**（[推断]，机制各步为 [原文]）：低频段正常 → 切低频段时供电/开关异常使 22kHz 残留 → 依据 §5.1 的兼容语义「连续 22kHz = 高波段选择」→ LNB 错误切入高频本振 → IF 频率整体漂移 → 锁定失败/BER 飙升。教学引用可标注 v4.2 §5.1（兼容语义）与 §4（22kHz 幅度/检测阈值）。

---

## 5. Unicable（EN 50494/50607）与 DiSEqC 的交界（SPEC-623 素材）

- EN 50494/50607 复用 DiSEqC 硬件层（22kHz 调制）承载 UB 调谐命令：**EN50494 的信道切换命令 = DiSEqC 报文 `E0 00 5A`（command 0x5A）+ 2 数据字节**；**EN50607 = 4 字节无 framing/address**（命令 `0x70`）。[文档]（TSDuck tsUnicable.h 类注释 + linux/tsTunerDevice.cpp `configUnicableSwitch` 实现；条款号待原文核对）
- 调谐字公式（[文档]，TSDuck 源注释）：
  - EN50494：`T = round((|Ft − Fo| + Fub) / 4) − 350`（Ft=转发器频率、Fo=本振、Fub=UB 频率，单位 MHz，步长 4MHz）
  - EN50607：`T = IF − 100`（IF = 用户带中频 MHz）
- UB 槽位：Unicable I = 1~8 个 UB / 2 个卫星位；Unicable II = 1~32 个 UB / 最多 64 卫星位。[文档]（tsUnicable.h；与 roadmap §4 领域 A1 的 EN 50607 32 UB 说法一致）
- 总线复用时序（[文档]，tsUnicable.h 注释；与 DiSEqC v4.2 时序语义同构）：空闲态 13V 无音调 → 发令前置 18V → settle 15ms → 发命令 → （双向 reply 不支持）→ 清信道等待 → 回落 13V 维持 UB 输出；两接收端命令碰撞的随机退避机制规范有建议、TSDuck 未实现。
- EN 50607 的 dCSS 双向能力（ODU_reply）与 DiSEqC 2.x reply 属同一方向性问题：L0 建模时 1.x/50494 优先，双向留扩容。[推断]

---

## 6. TSDuck 对 SEC/DiSEqC 控制的支持面核查（Windows 可用面内）

### 6.1 本机实测（TSDuck 3.45-4798，Windows 10.0.26300 x64，2026-11-20）

| 核查项 | 结果 | 置信 |
|---|---|---|
| 版本 | 3.45-4798（较 #6 调研基线 3.40-4165 已升级，覆盖 CHANGELOG 3.42 新增项） | [实测] |
| tsp 插件清单（`tsp --list-plugins`） | input 13 + output 13 + processor 86 = **112 个插件，无 DiSEqC/SEC 专用插件**（大小写不敏感检索仅命中 SRT=Secure Reliable Transport、SECTIONS 假阳性） | [实测] |
| 命令行工具（bin 目录 43 个 .exe） | 无 DiSEqC/SEC 工具；`tslsdvb` 本机输出 "no DVB device found" → **硬件路径全部 NOT RUN** | [实测] |
| `dvb` 输入插件选项面（唯一硬件入口） | 卫星相关选项：`--lnb`（tsduck.lnbs.xml 预置 LNB）、`--polarity`、`--satellite-number`（0~63，级联说明内嵌 DiSEqC 1.1/1.0 语义）、`--unicable`（`<version>,<userband slot>,<userband frequency>`，version 1=EN50494 / 2=EN50607）；`--isi/--plp/--pls-*` 明确标注 "supported on Linux only"；**无 `--diseqc` 类原生命令选项** | [实测] |
| 离线 User Guide（tsduck.html 3.2MB） | DiSEqC 仅 3 处，全部是 `--satellite-number` 选项描述的重复；dev 文档（tsduck-dev.html）**零提及**——无公开 API 类暴露 SEC 控制 | [实测] |
| `tsduck.lnbs.xml` / `tsduck.lnbs.model.xml` | LNB 波段模型：`<band low/high/oscillator/switch/polarity>`；注释明示 polarization-controlled（"stacked"）LNB 不需要 tone/voltage/DiSEqC 命令 | [实测] |
| CHANGELOG（本地 doc/CHANGELOG.txt） | 3.42-4421（2025-08）："Satellite reception: added support for **DiSEqC 1.1 and Unicable on Linux**." | [实测] |

### 6.2 上游源码核查（GitHub tsduck/tsduck，文档引用级 [文档]）

| 文件 | 发现 |
|---|---|
| `dtv/broadcast/linux/tsTunerDevice.cpp` | `dishControl()`：完整 DiSEqC 命令构造（§2.2 所引）+ 15ms/100ms 时序 + 22kHz 音调管理——**仅 Linux 路径**；`configUnicableSwitch()`：EN50494/50607 命令构造——**仅 Linux 路径** |
| `dtv/broadcast/windows/tsTunerDevice.cpp` | 无 diseqc/unicable 命令发送；satellite_number 仅参与属性复位逻辑 |
| `dtv/broadcast/windows/tsDirectShowUtils.cpp` | `CreateLocatorDVBS()`：`--satellite-number` → BDA locator `LNB_Source` A/B/C/D 映射；源码注释原文 "**Note however that most drivers ignore it...**" |
| `libtscore/system/windows/tsComIds.h` | 含 `IID_IBDA_DiseqCommand` GUID（微软 BDA 标准接口）——TSDuck 仅枚举其存在（能力探测），**未实现经它发送命令** |
| `dtv/broadcast/tsUnicable.h` / `tsLNB.h` | 类注释完整记录 Unicable 七步总线时序、UB 模型、碰撞退避未实现、PIN 扩展命令未使用（§5 所引） |

### 6.3 适用性结论（照 #104 收窄先例，NOT TRUSTED）

1. **TSDuck 无 SEC/DiSEqC 插件面**：SEC 控制只是 `dvb` 输入插件调谐的内部前置步骤——不产生 TS 字节、不进 tsp 管线、无 JSON 观测面、无故障注入语义。对以 TS 处理为界的 DVB-Nexus，TSDuck 在 SEC 域**没有可集成面**。[实测]+[文档]
2. **Windows 实现不发 DiSEqC 命令**：即使有 BDA 硬件，`--satellite-number` 仅是 locator 属性（驱动多忽略）；真实命令构造只在 Linux ioctl 路径。Windows 上「用 TSDuck 演示 DiSEqC 命令」**不成立**。[文档]
3. **本机实测边界**：无 DVB 硬件 → 全部硬件行为 NOT RUN（诚实门）；插件/帮助文本/离线文档/CHANGELOG 层面的实测结论不受影响。[实测]
4. **对 SPEC-622/623 的定位建议**（[推断]）：SPEC-622 命令状态机的权威素材 = Eutelsat v4.2 原文（§1~§4）；TSDuck 降级为**第二意见实现注释**（Linux 构造代码可作字节级互证，NOT TRUSTED）；`tsduck.lnbs.xml` 波段模型（low/high/oscillator/switch/polarity + stacked 语义）是 SPEC-621 LNB Model 的现成借鉴对象——其 XML 数据文件本机即可复用。

---

## 7. 对下游票的输入建议

### 7.1 对 #150（SPEC-622/623 边界细裁）

1. **SPEC-622 命令状态机素材**直接取材 v4.2 §8：framing E0~E7 八态、地址族、命令表（M/R/S 分级）。建议 SPEC-622 首版只收录 **1.x 单向命令子集**（`0x38`/`0x39` Write N0/N1 为 M 级、`0x20`~`0x2F` Set 族、`0x02`/`0x03` 电源族），2.x 读命令（`0x10`/`0x11`/`0x14`/`0x15`）与 reply 语义列为扩展位——与「最小状态求值器」候选谱系相容。[推断]
2. **边界切分建议**（[推断]，供裁决）：
   - 13/18V × 22kHz 供电/频段/极化模拟交界 + Tone Burst → **SPEC-621（LNB Model）**
   - DiSEqC 消息层（framing/address/command/时序/级联重发）→ **SPEC-622（DiSEqC Controller）**
   - UB 槽位/调谐字/堆叠干扰（A1）→ **SPEC-623（Unicable）**
   - 依据：v4.2 §5.1/§5.2 的兼容信令语义在物理上属于供电侧（LNB/开关执行），DiSEqC 报文才属于控制器；三者通过「电压/音调/报文三轨状态」关联——SPEC-622 的输出状态应含 voltage/tone 轨以支撑 A2 排查叙事。
3. **时序常量进规格**：150ms reply 上限、15ms 间隙、100ms 级联初始化、6ms 静默、500µs 位周期——建议作为 SPEC-622 的 L0 求值常量（引用 v4.2 §5/§6 条款号），不做实时模拟承诺。[推断]
4. **「待原文核对」清单**：EN 50494/50607 条款号、EN 61319-1 table ZB.1、TR 102 252 下载核验（本会话 etsi.org 网络失败）、Eutelsat 配套文档族免费镜像。这些都阻塞条款级引用，不阻塞状态机设计。[推断]

### 7.2 对 #147（L0 形态）

1. DiSEqC 1.x 命令模型天然是**单向确定性状态投影**（命令 → 状态迁移，无 reply 通路），是最适配「最小状态求值器」候选（#143 Q3）的域之一：sec.* 命名空间事件可从「命令序列 + 供电/音调/开关状态机」直接求值，无需全拓扑健康求值。[推断]
2. 观测置信轴：DiSEqC 求值产物一律 `source=rule_engine, confidence=simulated`（CONTEXT.md 观测纪律；v4.2 的 2.x reply 在 L0 中无真实从机，若建模 reply 只能是 simulated 推断，禁止标 parsed）。[推断]
3. SEC 状态枚举建议（供 L0 节点注册表）：`voltage(13/18V)` × `tone(22kHz on/off)` × `committed_ports` × `uncommitted_ports` × `positioner` × `power(standby/on)`——全部可由 1.x 命令集驱动，与 #143「Not yet specified」中 sec.* 事件命名空间条目衔接。[推断]

---

## 8. 来源

**标准原文（本会话下载并逐条抽取）**
- Eutelsat DiSEqC Bus Functional Specification v4.2（1998-02-25）：https://educypedia.org/library/bus_spec.pdf （226,994 字节 / 28 页 / PDF-1.2，Content-Length 与 ETag 一致，pdfinfo 28 页，pdftotext 抽取 76KB 非空文本；镜像 last-modified 2008-06-09）
- TI SLVA863 "DiSEqC™ Protocol and Low-Noise Block Voltage Regulator TPS65235 for Satellite – STB/TV"：https://www.ti.com/lit/pdf/slva863 （1,353,038 字节 / 11 页，ti.com 官方）

**付费/未核验来源（条款号待原文核对）**
- CENELEC EN 50494 / EN 50607：正文付费（roadmap §5 既裁）
- CEI EN 61319-1:1999（table ZB.1）：经 TSDuck 源码引用，原文本会话未获取
- ETSI TR 102 252 V1.1.1（https://www.etsi.org/deliver/etsi_tr/102200_102299/102252/01.01.01_60/tr_102252v010101p.pdf ）：本会话两次抓取失败（SSL 超时 / 连接 reset——该域名既往调研可下载，属本机当前网络闪断）
- Eutelsat 原站：`https://www.eutelsat.com/files/PDF/DiSEqC-documentation.zip` **实测 404**（TSDuck 源码注释引用的 URL 已失效）
- 历史版本镜像 affon.narod.ru（diseqc31.pdf，1996-03 版）：连接被 reset，未核验
- Internet Archive 存档路径：本机网络不可达（连接超时），未核验

**TSDuck 证据（本机实测 + 上游源码）**
- 本机 TSDuck 3.45-4798（`D:\Program Files\TSDuck\bin`）：`tsp --list-plugins`（112 插件清单）、`tsp -I dvb --help`、`tslsdvb`（no DVB device found）、`doc/tsduck.html`（3 处 DiSEqC）、`doc/tsduck-dev.html`（0 处）、`doc/CHANGELOG.txt`（3.42-4421 条目）、`bin/tsduck.lnbs.xml` + `tsduck.lnbs.model.xml`
- 上游源码（GitHub tsduck/tsduck，本会话经 gh api 读取）：`src/libtsduck/dtv/broadcast/linux/tsTunerDevice.cpp`（dishControl / configUnicableSwitch）、`src/libtsduck/dtv/broadcast/windows/tsTunerDevice.cpp`、`src/libtsduck/dtv/broadcast/windows/tsDirectShowUtils.cpp`（CreateLocatorDVBS）、`src/libtscore/system/windows/tsComIds.h`（IID_IBDA_DiseqCommand）、`src/libtsduck/dtv/broadcast/tsUnicable.h`、`src/libtsduck/dtv/broadcast/tsLNB.h`、`doc/user/plugins/dvb-input.adoc`

**网络故障记录（防坑纪律执行情况）**：本会话下载产物 2 件（bus_spec.pdf、slva863.pdf）均核验通过；失败读操作各至多重试一次——WebFetch Wikipedia（超时，改走 web_reader 成功）、archive.org（直连超时 ×2，放弃）、etsi.org（超时 + reset ×2，放弃）、affon.narod.ru（reset，放弃）、educypedia 其余文件名探测（404，非故障）。

**仓库内关联文档**：`docs/research/standards-audit.md`（§4 Unicable 术语核查、EN 50494/50607 付费结论）、`docs/research/tsduck-env.md`（Windows BDA 限制、Worker 契约）、`docs/roadmap.md` §4 领域 A（A1/A2 订正）、§5 技术事实备忘。
