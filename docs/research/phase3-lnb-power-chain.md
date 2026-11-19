# LNB 供电链物理语义与状态素材研究（GitHub Issue #146）

**研究对象**：LNB 供电语义的权威来源盘点——13/18V 极化电压、22kHz tone、band/polarization 选择矩阵、多路开关 22kHz 级联、短路保护等状态语义；来源权威度与可得性（付费/免费）。
**研究日期**：2026-11-20
**研究方式**：优先主源（免费正式标准交付件 + 厂商 datasheet/手册原文逐页核对），逐条标注来源与置信路径（**引用** = 已对原文逐页核对；**推断** = 由已核对原文推算/外推，标明推理链）。付费来源诚实标注「待原文核对」。
**目标读者**：细裁票 #149（SPEC-620/621 边界）、#147（L0 形态）；同时为靶场 A2（22kHz 持续音调残留）症状链提供物理依据（roadmap §4 领域 A）。
**方法与约束**：本机网络对部分源不可达（web.archive.org、analog.com、Wikipedia DNS、st.com datasheet 直链两次超时、cs-multimedia.de 403）——全部如实标注于 §8 来源清单，不做二手转述冒充原文核对（No fake evidence）。

---

## 0. 总览结论

| # | 问题 | 结论 | 置信 |
|---|---|---|---|
| 1 | 13/18V 与 band/polarization 的选择矩阵 | 四格真值表（13V/18V × 无 tone/22kHz → 低/高频段 × 垂直/水平）被 **TI 应用笔记、pabr 技术评述、Inverto 手册、Kathrein 手册四份独立原文一致核实**；多路开关语境下同一矩阵实现「每个接收机独立选择」（Inverto Legacy 端口表 + Kathrein 技术数据页） | 高（4 源引用一致） |
| 2 | 22kHz 物理层参数 | 免费权威 = **ETSI TS 101 964 §A.1（normative，22kHz 总线物理层）+ TI SLVA863**（引用 Eutelsat DiSEqC 规范的完整物理参数）：载波 22kHz±20%、音调电平 650mVpp±250mV、位定义 '0'=1.0ms tone+0.5ms 停 / '1'=0.5ms+1.0ms（两源逐字一致） | 高（2 独立原文交叉一致） |
| 3 | 22kHz 的语义是**上下文相关**的 | 同一音调：Universal LNB 直连/多路开关 Legacy 端口 = **低/高频段选择**；老式级联（band-fixed LNB）= **SAT A/B 选择**。SPEC-621 状态模型必须把「tone 语义」挂在拓扑上下文而非 LNB 节点自身 | 高（架构差异由原文架构图 + 教材佐证） |
| 4 | 短路保护状态语义 | 厂商 datasheet 给出完整状态机：限流钳位（≤4ms）→ hiccup 关断（128ms）→ 自动重试，可 I²C 配置；热关断 160°C 关/140°C 开；FAULT 锁存直至显式清除（EN 回收或读寄存器）。设备手册另证：端口短路 → 无供电 → 断电复位 | 高（TI TPS65235 引用 + Inverto 引用） |
| 5 | 权威来源可得性 | **付费**：EN 50494/50607（ETSI deliver 404 实测复核）、EN 60728 族（Part 5 headend / Part 11 safety，CENELEC/IEC 付费）；**Eutelsat DiSEqC 规范原文已无免费官方入口**。**免费权威替代充分**：ETSI TS 101 964（normative 物理层）+ TI SLVA863/SLVSBD0D + Inverto/Kathrein/Offel 原文手册 | 高（可得性均为本票实测） |
| 6 | A2 症状链（残留 22kHz → 低频段 BER 飙升） | 物理上成立且**不对称性有严格几何**：残留 tone 使 LO 停在 10600 MHz，接收机仍按 9750 计算 IF → 实际输出偏移 **850 MHz**（远超 LO 漂移 ±3MHz 与捕获范围）→ 低频段请求几乎必然失锁或错锁到同一 IF 槽位的高频段转发器（BER 飙升）；高频段请求因残留 tone 与意图恰好一致而正常 | 高（频段计划引用 + 偏移算术为推断） |

---

## 1. 状态真值表：电压 × 音调 14 组合逐格核实

**枚举逻辑**：供电电压 3 态 {0V, 13V, 18V} × 音调 4 模式 {无, 持续 22kHz, ToneBurst（mini-DiSEqC）, DiSEqC data burst} = 12 态；其中「持续 22kHz」与「DiSEqC data burst」可在同一输出上**复合存在**（先发消息再恢复持续 tone，TI SLVA863 Figure 3；音调与消息复用同一 22kHz 载波，TI TPS65235 §7.3.7），补 2 个复合态，共 **14 态**。ToneBurst 有 A/B 两种（TI SLVA863 §1 Figure 2：A = 非调制 12.5ms；B = 9×0.5ms 脉冲 + 8×1ms 间隙，容差 ±20%），二者仅是开关选择位（SA/SB）、对 band/polarization 正交，B 与 A 语义对称不单列。

| # | 供电电压 | 22kHz 音调状态 | LNB 实际输出选择 | 依据 | 置信路径 |
|---|---|---|---|---|---|
| 1 | 0V | 无 | **无 IF 输出**（未供电） | pabr §3.2："If one of the connectors does not receive power, it will not output an IF signal"（Twin 语境；Single 同理）；TPS65235 EN=0 → VLNB=0V（Table 7-3） | 引用 |
| 2 | 0V | 持续 22kHz | **无 IF 输出**；tone 无叠加载体 | TPS65235 §7.3.7：tone 是「superimposed at the LNB output voltage」（叠加在输出**电压**上）；无电压则无叠加 | 推断（由引用原文的叠加机制推算） |
| 3 | 0V | ToneBurst | 无 IF 输出 | 同 #2 | 推断 |
| 4 | 0V | DiSEqC data burst | 无 IF 输出 | 同 #2 | 推断 |
| 5 | 13V | 无 | **低频段（LO 9750）+ 垂直**（线极化 V；圆极化语境 = 右旋 RH） | TI SLVA863 Table 3（13V→Low→Vertical, right）；pabr §3.2（13V→vertical、no overtone→9.75GHz LO→低段）；Inverto Legacy 表（V/L = 13V/0kHz） | 引用（3 独立源一致） |
| 6 | 13V | 持续 22kHz | **高频段（LO 10600）+ 垂直** | TI Table 3（13V+22kHz→High→Vertical）；pabr §3.2（22kHz overtone→10.60GHz LO→高段）；Inverto（V/H = 13V/22kHz） | 引用（3 独立源一致） |
| 7 | 13V | ToneBurst（A） | 低频段+垂直 **不变**；burst 是开关选择信号（SA），不改 band | TI SLVA863 §1 Figure 2：burst "select Satellite A (SA)"，无 band 语义 | 引用 |
| 8 | 13V | DiSEqC data burst | 低频段+垂直 **不变**；data burst 是 DiSEqC 消息寻址 | TI SLVA863 §1 Figure 1/3（消息在 22kHz 载波上 PWK 编码）；TS 101 964 §A.1（同一位定义） | 引用 |
| 9 | 18V | 无 | **低频段（LO 9750）+ 水平**（圆极化语境 = 左旋 LH） | TI Table 3（18V→Low→Horizontal, left）；pabr §3.2（18V→horizontal）；Inverto（H/L = 18V/0kHz） | 引用（3 独立源一致） |
| 10 | 18V | 持续 22kHz | **高频段（LO 10600）+ 水平** | TI Table 3（18V+22kHz→High→Horizontal）；pabr §3.2；Inverto（H/H = 18V/22kHz） | 引用（3 独立源一致） |
| 11 | 18V | ToneBurst（A） | 低频段+水平+SA | 同 #7 | 引用 |
| 12 | 18V | DiSEqC data burst | 低频段+水平+DiSEqC 寻址 | 同 #8 | 引用 |
| 13 | 13V | 持续 22kHz + data burst 复合 | **高频段+垂直+DiSEqC 寻址**（时序：消息→SA/SB burst→>15ms 间隙→持续 tone 恢复，"Start of Continuous Tone if required"） | TI SLVA863 §1 Figure 3（完整时序图）+ TPS65235 §7.3.7（同一载波复用） | 引用组合 |
| 14 | 18V | 持续 22kHz + data burst 复合 | **高频段+水平+DiSEqC 寻址** | 同 #13 | 引用组合 |

**band/polarization 四格矩阵（上表 #5/6/9/10 的紧凑形）**——即 roadmap A2「训练目标：物理视图电压（13/18V）× 22kHz 组合逻辑排查」的训练素材本体：

| | 无 tone（低频段） | 22kHz 持续（高频段） |
|---|---|---|
| **13V** | V/L：LO 9750，垂直 | V/H：LO 10600，垂直 |
| **18V** | H/L：LO 9750，水平 | H/H：LO 10600，水平 |

多路开关语境的同一矩阵（Inverto Unicable II Multiswitch 手册 Technical parameters 页原文："Legacy port switching: V/L => 13 V/0 kHz, V/H => 13 V/22 kHz, H/L => 18 V/0 kHz, H/H => 18 V/22 kHz"）——**引用**。

---

## 2. 物理参数逐项证据表

### 2.1 极化电压（13/18V）

| 参数 | 数值 | 来源 | 置信路径 |
|---|---|---|---|
| 标称电压 | 13V=垂直、18V=水平 | TI SLVA863 §2 "the polarization is decided by the receiver through two different DC signal levels, normally a 13-V signal and a 18-V signal" + Table 3；pabr §3.2 | 引用 |
| 接收机判定窗口（多路开关） | 垂直 12–14V / 水平 16–19V（原文 "Vertical/horizontal input control: 12-14/15/16-19 V"；15V 边界记法系原表排版，垂直<15V<水平的判定语义为推断） | Kathrein EXR 2508/2554/2558 手册 Technical data 页 | 引用（窗口）/ 推断（边界语义） |
| 电压容差 | 13V/18V ±0.5V（手册该行排版为 "13 V/18 V ± 0.5 … 0/22 kHz"，±0.5 归属电压；页面排版噪声，归属判断为推断） | Inverto Unicable II Multiswitch 手册 | 引用（数值）/ 推断（归属） |
| 供电 IC setpoint | 13.4 / 14.6 / 18.2 / 19.4V（另有 I²C VSET[3:0] 可编程；19.4/14.6 为高输出档——Kathrein 手册用 14/18V 标称与此互证） | TI TPS65235 Table 7-3 Logic table | 引用 |
| 电压切换时间 | 13.4↔18.2V 过渡约 2ms（22nF TCAP，公式 t=0.8×C/I） | TPS65235 §7.3.5 | 引用 |
| ⚠️ 厂商 datasheet 瑕疵 | Offel 13-244 表行 "Legacy switch voltage control: H: 10÷14, V: 16÷20" 与全部其他源**字母互换**（其余源一致为 V≈13/H≈18）；判为该 datasheet 排版错误，交叉裁决依据 = TI Table 3 + pabr + Inverto + Kathrein | Offel datasheet | 引用（不一致本体）/ 推断（裁决） |

**圆极化注**：13V/18V 在圆极化语境（如部分区域 DVB）对应右旋/左旋（TI Table 3 将两列合并表述为 "Vertical, right" / "Horizontal, left"）——SPEC-621 若建 polarization 枚举，建议 {V, H} 为主、circular 语境注释化。**引用**。

### 2.2 22kHz 音调

| 参数 | 数值 | 来源 | 置信路径 |
|---|---|---|---|
| 载波频率与容差 | 22 kHz ± 20%（= ±4.4kHz） | ETSI TS 101 964 §A.1.1（normative） | 引用 |
| 载波频率（器件级） | 22 ± 4 kHz | Offel 13-244 datasheet（"Tone 22 K: 22 ± 4"）——与 ETSI ±20% 独立吻合 | 引用 |
| 音调电平 | 650 mVpp ± 250 mV；检测器须响应到约 300mV ±100mV；总线最大 1Vpp（TI 推荐） | TI SLVA863 §1 | 引用 |
| 音调电平（供电 IC 生成档） | 650 或 750 mV 可选 | TPS65235 Features §1 | 引用 |
| 音调注入方式 | 改变 LDO 基准电压把 tone 叠加在输出电压上（推挽输出，零负载下不失真）；EXT-M 逻辑门控（高=叠加、低=不叠加） | TPS65235 §7.3.7 | 引用 |
| 总线电流源幅度 | 43 mA ± 10%（源阻抗 >10kΩ） | TS 101 964 §A.1.1 | 引用 |
| 总线负载 | 15Ω ± 5%；负载电感 270µH ± 5%；负载电容典型 470nF；检测电阻 5–10kΩ；隔直电容时间常数约 100µs | TS 101 964 §A.1.1 | 引用 |
| 音调检测延迟 | 最大 1.5 个 tone 周期（DIN→DOUT 开漏输出） | TPS65235 §7.3.8 | 引用 |

### 2.3 DiSEqC 数据层（tone 上的 PWK 编码）

| 参数 | 数值 | 来源 | 置信路径 |
|---|---|---|---|
| 位时序 | 时基 0.5ms ± 0.1ms；位长 1.5ms；'0' = 1.0ms burst + 0.5ms pause；'1' = 0.5ms burst + 1.0ms pause | TS 101 964 §A.1.2 **与** TI SLVA863 Figure 1 逐字一致 | 引用（双源一致） |
| 载波周期/位 | '0' 位含约 22 个 22kHz 周期、'1' 位约 11 个 | TI SLVA863 §1 | 引用 |
| ToneBurst A/B | A = 非调制 22kHz 持续 12.5ms；B = 9×0.5ms 脉冲 + 8×1ms 间隙；容差 ±20% | TI SLVA863 §1 Figure 2 | 引用 |
| 消息时序 | DC 电压变化后须 >15ms 间隙；完整 DiSEqC 1.0 消息典型 54ms；消息→(>15ms)→SA/SB burst(12.5ms)→(>15ms)→持续 tone；从机应答 ≤150ms | TI SLVA863 §1 Figure 3 + §2 | 引用 |
| 帧结构 | Framing + P + Address + P + Command + P + Data + P（P=奇校验）；22kHz 总线字节纠错 = 每字节奇校验（按 DiSEqC 规范）；SMATV 扩展版帧含 3 字节 RUN-IN + CRC-16（X¹⁶+X¹²+X⁹+X⁸+X+1）、消息 ≤32 字节 | TI SLVA863 Figure 4/5；TS 101 964 §4.1 | 引用 |
| DiSEqC 版本语义 | Tone Burst=简单 2 态开关；1.0=单向（≥4 个 committed 开关）；1.1=+uncommitted/重复器；1.2=+定位器；2.0=双向（回传含 **LNB LO 频率读数**） | TI SLVA863 Table 1/Table 2 | 引用 |

**权威归属注**：以上数据层的原始出处是 Eutelsat《DiSEqC Bus Functional Specification》（TS 101 964 §2 引用其版本为 **v4.2, February 1998**；TI SLVA863 全文明确按该规范转述）。原规范本身已无免费官方入口（diseqc.org 站点失效；web.archive.org 本机不可达；narod.ru 镜像 SSL 失败；Scribd 有 v4.0 镜像但非干净获取）——**对 #149 的建议：引用落点用 TS 101 964 + TI SLVA863，勿引 Eutelsat 条款号（与「Do not invent ETSI/ITU clause numbers」纪律同构）**。

### 2.4 频段计划与 LO（band/polarization 矩阵的频率侧）

| 参数 | 数值 | 来源 | 置信路径 |
|---|---|---|---|
| Universal LNB 定义 | 4 子频段 = 2 极化 × 2 频段的全部组合 | pabr §3.1 | 引用 |
| 低频段 | RF 10.70–11.70 GHz → LO 9750 MHz → IF 950–1950 MHz | pabr §3.2（"No overtone selects the 9.75 GHz LO. This downconverts the low range (10.70..11.70 GHz) to 950..1950 MHz"） | 引用 |
| 高频段 | RF 11.70–12.75 GHz → LO 10600 MHz → IF 1100–2150 MHz | pabr §3.2 | 引用 |
| 总 IF 范围 | 950–2150 MHz（Offel："Output frequency range 950~2150"；Kathrein："950-2150"；Inverto："950 MHz ~ 2150 MHz"） | Offel/Kathrein/Inverto 三源一致 | 引用 |
| LO 精度/漂移 | 初始 ±1.0 MHz max、温度漂移 ±3.0 MHz max（器件级）；PLL 稳定度约 25kHz vs DRO 约 250kHz | Offel；pabr §3.4 | 引用 |
| 宽带 LNB（对照） | 10.70–12.75 GHz → 300–2350 MHz，LO 10.40/10.41 GHz，**无 tone/电压频段切换**（Inverto 手册 Wideband 模式 300–2350MHz 同证） | pabr §5；Inverto 手册 | 引用 |
| Quattro LNB | 4 输出各载一个 (极化×频段) 平面；"As long as at least one connector receives power, all four outputs are active" | pabr §3.2 | 引用 |

**推断（A2 关键算术）**：低/高频段 IF 区间重叠区为 1100–1950 MHz——同一 IF 槽位对应两个相差 **10600−9750 = 850 MHz** 的 RF 转发器。tone 是唯一的消歧器（两源频段计划相加的算术结论）。

### 2.5 电流（供电能力预算）

| 参数 | 数值 | 来源 | 置信路径 |
|---|---|---|---|
| LNB 典型功耗 | 120 mA @ 11–20V | Offel 13-244 | 引用 |
| LNB 内部线性稳压器档 | 78L06:100mA / 78N06:300mA / 78M06,78D06:500mA；6V 内部轨下 13V 供电浪费 1.4W、18V 供电浪费 2.4W（200mA 负载） | pabr §4.5 | 引用 |
| 接收机/多路开关供电能力 | 500 mA max @ 18VDC（Inverto）；总馈电 800 mA、每 trunk 1000 mA（Kathrein EXR） | Inverto/Kathrein 手册 Technical data | 引用 |
| LNB 供电 IC 限流上限 | ≤1000 mA，外接电阻设定，精度 ±10%（R_SET=117.08×I^(-1.267)；200kΩ→0.65A、110kΩ→约1A） | TPS65235 §1/§7.3.2 | 引用 |
| 每用户（级联 trunk 下端）消耗 | 20 mA | Kathrein EXR 手册 | 引用 |

---

## 3. 多路开关 22kHz 级联语义

### 3.1 架构 A：Quattro LNB + 多路开关（现代主流，tone = 频段语义）

- Quattro LNB 输出 4 个固定平面 V/L、V/H、H/L、H/H（pabr §3.2 **引用**；Inverto 手册端口命名 V/L,V/H,H/L,H/H **引用**）。
- 多路开关把每个接收机的 13/18V + 0/22kHz 映射到 4 平面之一："Independent selection of horizontal/vertical, low/high, for each receiver"（Kathrein **引用**）；Inverto Legacy 端口真值表逐格给出映射（§1 紧凑矩阵 **引用**）。
- **级联（trunk）语义**：trunk 电缆承载 4 平面 + 地面信号；级联单元（Kathrein EXR 2554/2558 "Multi-switch loop-through for system extension"）最多 **8 级**；每级在本地输出端口重新解释接收机的电压/tone（Kathrein 手册架构图与特性页 **引用**；「每级同语义重解释」由架构图推断——trunk 上无控制信号解释点，控制面终结于各分配开关）。
- **电源纪律（级联）**：只允许单点馈电——Inverto 手册："power supplied to the STB output ports can be passed on to power the LNB by setting the manual switch (SW2) to ON. **The switch shall be set to OFF in cascade installations** otherwise the switch will have to power the units it cascades to"（**引用**）；Kathrein：远程馈电经 **horizontal low 输入口**注入（"Can be remote fed via the horizontal low inputs. All other inputs are voltage-free"），每 trunk 1000 mA 上限（**引用**）。
- 控制协议自动识别：Inverto 端口自动检测 Legacy(13/18VDC, 0/22kHz) / DiSEqC 1.x/2.x / EN50494 / EN50607 并逐端口切换（**引用**）——对 SPEC-621/623 边界有价值：legacy 电压/tone 状态与 DiSEqC/Unicable 是同一端口上的并行控制面。

### 3.2 架构 B：老式 22kHz 级联（band-fixed LNB，tone = SAT A/B 语义）

- 教材《Digital Satellite TV Handbook》（Mark E. Long）记载 22kHz tone 沿同轴电缆上行至多路开关用于 Satellite A/B 切换，且该原理适用于每个级联级（Scribd 搜索摘录级证据，未通读全书——**教材层置信**）。
- 该架构下 LNB 为非 Universal（band-fixed），tone 语义从「频段」移位为「第二卫星」。**此语义差异是 SPEC-621 状态模型的必要输入**：tone→含义的映射必须由拓扑上下文（LNB 类型/开关架构）决定，不能内嵌在 LNB 节点里。

### 3.3 A2 与级联的衔接

roadmap A2 表述「LNB 供电/多路开关异常使低频段指令混入残留 22kHz」。物理机制候选（按证据层级排序）：
1. **接收机供电/音调发生器缺陷泄漏**：tone 发生器是独立模拟通路（EXT-M 门控叠加，TPS65235 §7.3.7），劣化后关断不净——机理成立但失效模式为推断（**推断**）。
2. **级联/分配设备隔离不良回窜**：trunk 多级馈电（Kathrein 经 H/L 口馈电、Inverto SW2 规则）中某级把自身/上游 tone 漏入接收机端口——机理与「单点馈电纪律」由手册支撑，回窜路径为推断（**引用+推断**）。
3. **LNB 内部 DC-DC/电源故障自激混入**：LNB 内部供电链（pabr §4.5 线性稳压器结构）异常自激——行业经验层（教材/论坛级，本票未获原文，**诚实标注：低置信，待引证**）。

---

## 4. 短路保护等状态语义（厂商级状态机）

### 4.1 供电 IC 状态机（TI TPS65235 SLVSBD0D，已逐页核对）

| 状态 | 语义 | 依据 |
|---|---|---|
| NOMINAL | 正常供电，tone 可叠加 | §7.3.1/§7.3.7 |
| CURRENT_LIMIT（钳流） | 短路/过流时输出电流钳在限流值（ISET 电阻设定，±10%）持续 ≤4ms（LDO 保持开启） | §7.3.6 "the output current is clamped at the current limit for 4 ms with LDO on" |
| HICCUP_OFF（打嗝关断） | 过流持续 >4ms → boost 关断 **128ms** 后自动重试；ON/OFF 时间可 I²C 配置为 4ms/128ms 或 8ms/256ms | §7.3.1/§7.3.6 |
| THERMAL_SHUTDOWN | 结温 >160°C 关断；<140°C（回滞）自动恢复 | §7.3.6 |
| LATCHED_FAULT（故障上报） | 过流/热关断期间 I²C 与逻辑仍活；FAULT 引脚拉低并**保持**，直到 EN 回收（非 I²C 应用）或主控读 Control Register 2（I²C 应用）才释放——「可观测、须显式清除」的锁存语义 | §7.3.6 后续段 |
| 二级保护 | boost 内管逐周期峰值限流（默认约 3.8A 上限） | §7.3.3 |

### 4.2 设备手册级行为

- Inverto 多路开关：端口短路 →「This will prevent power to the LNB」→ 排障流程 = 断主电、排除短路、重上电；另载「复位多路开关微处理器：断电 30 秒再上电」可清除故障态（**引用**：短路阻断供电 + 断电复位语义）。
- Kathrein EXR：保护等级 Class II / IP30；安全规范引用 **EN 60728-11 与 EN 60065**（**引用**——亦是 EN 60728-11 在该设备族中的实际角色 = 安全标准，非供电语义标准）。

### 4.3 对 SPEC-621 的状态集建议（供细裁票裁决）

`scp_state ∈ {NOMINAL, CURRENT_LIMIT, HICCUP_OFF, THERMAL_SHUTDOWN, LATCHED_FAULT}`，与供电电压/tone 状态**正交**（过流期间 I²C/逻辑仍活 = 控制面状态不因保护态丢失）；LATCHED_FAULT 需显式清除动作（对应手册「断电 30 秒复位」）。均为 **引用** 支撑的状态语义，数值（4ms/128ms/160°C 等）属实现细节，建议作 config 而非规格常数。

---

## 5. A2 症状链物理依据（逐环节）

**症状（roadmap §4）**：高频段正常、切低频段时 BER 飙升——LNB 错误切入高频本振。

| 环节 | 陈述 | 依据与置信 |
|---|---|---|
| 1 | 接收机要低频段转发器 → 移除 22kHz，按 LO 9750 计算 IF（IF = f_RF − 9750 ∈ [950,1950]） | 引用（TI Table 3 + pabr §3.2 频段计划） |
| 2 | 故障注入点：线路上残留持续 22kHz（实际 tone 状态 ≠ 接收机指令状态） | 症状定义（票面）+ tone 是叠加在供电线上的模拟信号（TPS65235 §7.3.7 引用） |
| 3 | LNB 音调检测器只看**线路实际状态**：检测延迟最大 1.5 tone 周期；检测阈值 ≥300mV——残留 tone 若高于阈值即被判「高频段指令」 | 引用（TPS65235 §7.3.8 + TI SLVA863 检测电平）；「LNB 无指令记忆、纯线路状态驱动」为推断 |
| 4 | LNB 维持 LO 10600 → 输出 IF = f_RF − 10600 = 接收机期望 IF **− 850 MHz** | 推断（两源频段计划相减的算术） |
| 5 | 接收机调谐窗 [950,2150]：期望 IF ∈ [1800,1950] 时实际输出 [950,1100] 恰落窗内 → 可能**错锁同一 IF 槽位的高频段转发器**（内容不同 → 解码垃圾 → BER 飙升）；其余期望频点实际输出 [100,1100) 在窗下方 → **失锁** | 推断（窗重叠算术；错锁行为属接收机实现层，仿真中以「错锁/失锁」两形态建模并诚实标注） |
| 6 | 高频段请求正常：残留 tone 与高频段意图恰好一致 → 无症状——与票面「高频段正常」吻合 | 推断（由真值表对称性直接推出） |
| 7 | LO 漂移（±3MHz max）与 850MHz 偏移相差两个数量级以上 → 失锁/错锁不是漂移可解释的，诊断面可干净区分「tone 残留」vs「LO 漂移」两类故障 | 引用（Offel 漂移值）+ 推断 |

**仿真建模建议（对 #147/#149 共同输入）**：A2 的唯一状态突变是 `tone_actual ≠ tone_commanded`（残留）——LNB 求值器**只消费 actual**（步骤 3），接收机侧 IF 计算**消费 commanded**（步骤 1），两侧分歧自然涌现症状；观测面建议拆 `lnb.tone_commanded / lnb.tone_actual / lnb.selected_lo` 三事件 + `rf.lock` 形态（失锁/错锁），全部 `confidence=simulated`（No fake evidence：不把状态求值结果标 parsed/measured）。

---

## 6. 权威来源可得性盘点（票面问题直答）

| 来源族 | 可得性 | 本票实测 | 免费权威替代 |
|---|---|---|---|
| EN 50494（Unicable）/ EN 50607（dCSS） | **付费**（CENELEC-only） | ETSI deliver 目录 `etsi_en/504900_504999/50494/` 与 `506000_506099/50607/` 均 HTTP 404（2026-11-20 实测，与 standards-audit.md §4 结论一致） | Inverto 手册（EN50494/50607 术语 + User Band 表 + legacy 对照）；前票已核 MuMuDVB 等实现文档 |
| EN 60728 族 | **付费**（CENELEC/IEC/国家采纳版） | Part 5:2016 = "Cable networks … Part 5: **Headend equipment**"（IEC 60728-5:2015 的 EN 采纳，scope 含卫星接收 headend）；Part 11（IEC 60728-11:2016 / EN IEC 60728-11:2023）= **安全要求**（Kathrein 手册实证引用）——**该族没有免费承载 13/18V/22kHz 语义的条款文本** | 无直接替代；语义层由 DiSEqC 生态（§2.2/2.3）+ 厂商文档覆盖 |
| Eutelsat DiSEqC Bus Functional Specification（v1.2/4.2） | **无免费官方入口**（diseqc.org 已失效） | narod.ru 镜像 SSL 失败；web.archive.org 本机不可达；Scribd 有 v4.0 镜像（非干净获取） | **ETSI TS 101 964 §A.1（normative 22kHz 总线物理层，免费）+ TI SLVA863（按规范转述的完整参数）** |
| 厂商 datasheet / 手册 | **充分可得** | TI SLVA863/SLVSBD0D 已逐页核对；Inverto/Kathrein/Offel 手册已逐页核对。⚠️ st.com（LNBH25 两次超时）与 analog.com（MAX19790）本机网络阻断，未获取——SCP 章由 TI 两份文档覆盖 | — |
| 教材/百科 | 部分可得 | en.wikipedia.org 本机 DNS 失败（两次），未核；pabr.org 技术评述（v1.4, 2020-02）已逐页核对；《Digital Satellite TV Handbook》仅搜索摘录级 | pabr.org（技术评述层） |

---

## 7. 对下游票的输入建议

### 7.1 对 #149（SPEC-620/621 边界细裁）

1. **SPEC-621（LNB Model）状态变量清单建议**（全部有引用支撑）：`supply_voltage ∈ {OFF, V13, V18}`（名义值；窗口 12–14/16–19 与 ±0.5V 作 config 容差）、`tone ∈ {NONE, CONTINUOUS, TONEBURST_A, TONEBURST_B, DATA_BURST}`、**`tone_commanded` 与 `tone_actual` 分离**（故障注入缝，A2 唯一突变点）、`selected_lo ∈ {LO9750, LO10600}`（由 tone_actual 决定）、`selected_polarization ∈ {V, H}`（由 voltage 决定）、`scp_state`（§4.3 五态）、`output_if_range`（由 selected_lo + 频段计划导出）。
2. **SPEC-620/621 边界划法建议**：SPEC-620（RF 仿真）拥有频段计划数字与 IF 数学（9750/10600、950–1950/1100–2150、850MHz 错位、锁/BER 代理形态）；SPEC-621 拥有供电/tone/LO 选择/极化/SCP **状态**与「actual 驱动」规则；DiSEqC 消息层（帧结构、奇校验、PWK 时序）归 SPEC-622。多路开关是独立节点类型：其「22kHz 语义 = 频段选择 vs SAT A/B」由拓扑上下文决定（§3.2），不可并入 LNB 节点。
3. **引用纪律**：SPEC 文本引用落点 = ETSI TS 101 964 + TI SLVA863/SLVSBD0D + 厂商手册；**禁引** Eutelsat DiSEqC 条款号与 EN 50494/50607/60728 条款号（原文付费未核，待原文核对项见 §6）。
4. **已知不一致须显式处置**：Offel datasheet 的 H/V 字母互换（§2.1 末行）——SPEC-621 写真值表时以四源多数裁决（13V=V），并把该不一致记入规格注记，防后续开发者被单源误导。

### 7.2 对 #147（L0 形态）

1. LNB 是**纯状态节点**（无 TS 字节参与）：`supply_voltage/tone/selected_lo/scp_state` 全部是标量状态 + 因果规则（tone_actual→LO、voltage→极化），是「最小状态求值器」候选的典型适配案例——不需要全拓扑健康求值。
2. 事件命名空间建议（供观测面扩容裁决参考）：`lnb.voltage_state`、`lnb.tone_commanded`、`lnb.tone_actual`、`lnb.selected_lo`、`lnb.scp_state`、`rf.lock_state`（失锁/错锁两形态）；全部 `source=rule_engine（或对应求值器）、confidence=simulated`。
3. 故障原语候选：`tone_residue`（tone_actual ≠ tone_commanded，A2 本体）与 `scp_short_circuit`（进入 CURRENT_LIMIT/HICCUP_OFF，§4 状态机支撑）——两者都是 state 层机制，佐证地图「FaultDefinition layer 枚举扩 {RF, SEC}」的 open 项按「状态故障原语」路线裁。
4. 无包流可保持时的证据形态：LNB 故障场景下不存在 TS 字节证据，通关证据 = 状态求值观测 + 修复后新 Run 的状态序列（等位替换不变式在状态层的表达需 #147 裁决，本票提供的状态模型即其素材）。

---

## 8. 来源清单（含可得性与抓取状态）

**正式标准层**
- ETSI TS 101 964 V1.1.1 (2001-08)《DVB; Control Channel for SMATV/MATV distribution systems; Baseline Specification》——免费，已逐页核对（§4 消息结构、Annex A normative 物理层）：https://www.etsi.org/deliver/etsi_ts/101900_101999/101964/01.01.01_60/ts_101964v010101p.pdf
- Eutelsat《DiSEqC Bus Functional Specification》v4.2 (1998-02)（TS 101 964 §2 [2] 所引版本）——**原文未能免费获取**（diseqc.org 失效；web.archive.org 不可达；narod.ru 镜像 SSL 失败，URL https://affon.narod.ru/difst/diseqc31.pdf 抓取失败；Scribd v4.0 镜像未采用）
- EN 50494 / EN 50607——**付费，待原文核对**；ETSI deliver 目录 404 实测：https://www.etsi.org/deliver/etsi_en/504900_504999/50494/ 、https://www.etsi.org/deliver/etsi_en/506000_506099/50607/
- EN 60728-5:2016（IEC 60728-5:2015 EN 采纳，"Part 5: Headend equipment"，scope 含卫星接收 headend）与 EN/IEC 60728-11（安全要求）——**付费，待原文核对**（条目经 iTeh/BSI/In Compliance 检索核实标题与 scope：https://standards.iteh.ai/catalog/standards/clc/8e6df7e4-81e5-4e51-9663-f2bff894243b/en-iec-60728-11-2023 ；iTeh 详情页本机为 JS 门禁，逐条内容未核）

**厂商 datasheet / 应用笔记（均已逐页核对原文 PDF）**
- TI SLVA863《DiSEqC Protocol and Low-Noise Block Voltage Regulator TPS65235 for Satellite – STB/TV》(2016-12)：https://www.ti.com/lit/pdf/slva863
- TI TPS65235 datasheet SLVSBD0D (2015-11, Rev 2021-05)：https://www.ti.com/lit/ds/symlink/tps65235.pdf
- Inverto Unicable II Multiswitch 安装手册（IDLU-UST110-CU080-32P, item 5458）：https://www.inverto.tv/download/file/59f9814ec5d89-1509523790.pdf
- Kathrein EXR 2508/2554/2558《Sat-IF distribution system (4x sat-IF) Multi-switch》手册（德英双语，检索所得 Amazon CDN 镜像）：https://m.media-amazon.com/images/I/C1UiRtGct0L.pdf
- Offel 13-244 LNB QUAD PREMIUM datasheet Rev.4 (2018-10)：https://www.offel.it/upload/prodotti/allegati/schede-tecniche/DataSheet_13-244_EN.pdf
- ⚠️ 未获取（网络阻断）：ST LNBH25（https://www.st.com/resource/en/datasheet/lnbh25.pdf 两次超时）、ADI/Maxim MAX19790（analog.com 不可达）——该 URL 抓取失败，SCP/器件语义已由 TI 两份文档覆盖

**行业白皮书 / 技术评述**
- pabr.org《Ku-band LNB line-up》v1.4 (2020-02-26)：https://www.pabr.org/radio/lnblineup/lnblineup.en.pdf （在线版 http://www.pabr.org/radio/lnblineup/lnblineup.en.html ）

**教材/百科层**
- 《Digital Satellite TV Handbook》(Mark E. Long)——Scribd 摘录级（级联 22kHz=Satellite A/B 语义佐证）：https://www.scribd.com/doc/140187926/Digital-Satellite-Tv-Handbook-Marck-E-Long
- ⚠️ Wikipedia（Universal_LNB/DiSEqC）——en.wikipedia.org 本机 DNS 失败（两次），该 URL 抓取失败，未引用其内容
- ⚠️ CS Multiplex EXD1532 手册——https://www.cs-multimedia.de/mediafiles/BDA/EXD1532.pdf 抓取失败（403 拒绝，两次含浏览器 UA），未引用

**项目内既有结论（本票继承，未重开）**
- `docs/research/standards-audit.md` §4（EN 50494/50607 付费 + 二手交叉验证方法先例）、roadmap §4 领域 A（A2 口径）、roadmap §5 Unicable 条

**方法说明**：14 态真值表与四格矩阵为多源一致（TI/pabr/Inverto/Kathrein/Offel 中至少 3 源逐字吻合者标「引用」，单一源者逐条标明）；全部推断均已注明推理链；§2.3 数据层的原始规范（Eutelsat）不可免费获取，以「免费 normative 交付件 + 引用该规范的厂商应用笔记」双路径覆盖，未引任何未核条款号。
