# unicable-tuning-message-bit-layout · 独立验证注记

- **vector_id**: `unicable-tuning-message-bit-layout`（kind `state_eval`，#172 登记，2026-11）
- **规格权威**: SPEC-623 §6 调谐消息位布局表（normative，逐字段 verbatim）。
  EN 50494:2007 / EN 50607:2015 正文付费——**条款号一律不写**（#145 缺口留档；
  四实现源码级共识 = tvheadend `linuxdvb_en50494.c` / VDR `diseqc.c` /
  MuMuDVB `tune.c` / minisatip `dvb.cpp` 交叉一致）。
- **数据文件**: `unicable-tuning-message-bit-layout.ts` = 向量表的 canonical JSON
  序列化（indent=2 / sort_keys / ensure_ascii=False + 尾随换行；UTF-8）。
  `frame_bytes` 为十进制整数列表（JSON 无 hex 字面）；hex 形见下方对照。
  sha256 即身份；字节冻结。

## 独立验证路径（SPEC-506 §5 红线）

1. **位布局手推（L1，无 src 参与）**：21 组 case 的期望帧逐字段手推自 SPEC-623
   §6 表——字段槽位（EN 50494 data1 `[UB:7-5|position:4|polarization:3|band:2|t:1-0]`、
   EN 50607 data1/data2/data3）+ 位约定（polarization 0=V/1=H、band 0=low/1=high、
   position 0=A/1=B；EN 50607 data3 bits 1-0 钉零）。PIN 变体命令字节 0x5C/0x71
   与追加 PIN 字节按 §6 表原样。手推先于实现（#162 向量先钉纪律）。
2. **第二独立转录互证**：#162 的向量测试常量（`tests/unit/simulation/state/
   test_unicable.py` 五个帧向量类）是另一次独立手推；本 golden 表与其逐字节一致
   即两份独立手推互证。conformance 测试驱动生产 `build_tuning_message`
   纯函数对拍 golden——实现对拍的是规格手推转录，不是自身输出。
3. **TSDuck 交叉**：不适用（DiSEqC/SCR 调谐消息非码流域；沙盘内仅消息构造面）。

## 代表性帧 hex 对照（十进制表 ↔ hex 形）

| case | frame_bytes (hex) | t |
|---|---|---|
| en50494-baseline-all-zero-bits | E0 10 5A 00 CB | 203 |
| en50494-all-bits-set | E0 10 5A FD FF | 511 |
| en50494-pin-variant-command-0x5c | E0 10 5C 61 32 6B | 306 (PIN 107) |
| en50494-pin-zero-is-six-byte | E0 10 5C 00 CB 00 | 203 (PIN 0) |
| en50494-abs-max-t-1023 | E0 10 5A FF FF | 1023 |
| en50494-field-isolation-ub-bits-7-5 | E0 10 5A A0 CB | 203 (UB 5) |
| en50494-field-isolation-position-bit-4 | E0 10 5A 10 CB | 203 (pos B) |
| en50494-field-isolation-polarization-bit-3 | E0 10 5A 08 CB | 203 (H) |
| en50494-field-isolation-band-bit-2 | E0 10 5A 04 CB | 203 (high) |
| en50494-field-isolation-t-low-byte | E0 10 5A 00 CC | 204 |
| en50494-field-isolation-t-high-bits | E0 10 5A 01 61 | 353 |
| en50607-baseline-small-values | 70 03 84 00 | 900 |
| en50607-all-bits-set | 70 FF 3A FC | 1850 |
| en50607-abs-max-t-2047 | 70 FF FF FC | 2047 |
| en50607-t-zero-boundary | 70 00 00 00 | 0 |
| en50607-pin-variant-command-0x71 | 71 8D 78 A8 FF | 1400 (PIN 255) |
| en50607-field-isolation-ub-bits-7-3 | 70 0B 84 00 | 900 (UB 1) |
| en50607-field-isolation-position-bits-7-2 | 70 03 84 04 | 900 (pos 1) |
| en50607-field-isolation-t-low-byte | 70 03 E8 00 | 1000 |
| en50607-polarization-invariant-vertical | 70 03 84 00 | 900 |
| en50607-polarization-invariant-horizontal | 70 03 84 00 | 900 |

最后两行 = EN 50607 帧不含 polarization/band 槽位的独立 UB 空间钉扎
（两意图同帧）。

## A16 边界声明

`tuning_message` 不进 `sec.state_observed` payload 注册（裁定 A16——SPEC-303
为事件面权威）；本向量的 conformance 消费面 = 生产 `build_tuning_message`
纯函数（能力面 #162），expectations 的 `event_type` 标 `sec.state_observed`
仅表示向量事实所属的 state 域家族面（登记校验器的事件类型合法性门）。

## 登记校验

- `tools/validate_golden_registration.py` PASS。
- conformance 门：`tests/conformance/test_state_eval_golden_vectors.py` 逐 case
  驱动生产 `build_tuning_message(protocol, ub_assignment, tuning_request,
  if_frequency_mhz)` 对拍 frame_bytes/t + canonical 序列化往返稳定。
