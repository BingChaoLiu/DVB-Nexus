# Test Vectors — TS Packet Header Sample Set (`packet-header-set`)

**L1 bit-level golden vector**（SPEC-506 §7 #1 / §5：权威基准，独立评审推导脚本即可，无需 TSDuck）。

**Wire table authority:** SPEC-100 §3（H.222.0 Table 2-2 同构）：

| Byte/Bit | 字段 | 位宽 | 说明 |
|---|---|---:|---|
| 0 | `sync_byte` | 8 | 固定 `0x47` |
| 1[7] | `transport_error_indicator` | 1 | TEI |
| 1[6] | `payload_unit_start_indicator` | 1 | PUSI |
| 1[5] | `transport_priority` | 1 | 优先级 |
| 1[4:0] + 2 | `PID` | 13 | Packet Identifier |
| 3[7:6] | `transport_scrambling_control` | 2 | 00 Not scrambled；01 reserved；10/11 user-defined |
| 3[5:4] | `adaptation_field_control` | 2 | 00 reserved；01 payload only；10 adaptation only；11 both |
| 3[3:0] | `continuity_counter` | 4 | 0..15 |

## 1. 推导脚本

`tools/make_golden_packet_header_set.py`（无 `src/ts` 参与）：每个样本的 4 字节头由本表逐位推导（bit-shift 表达式在脚本内逐样本注明），payload 区用确定性填充（0x00 或 0xFF，见样本说明）。三件套登记于 `golden/packet-header-set/`；digest 冻结表见 `tests/conformance/test_first_batch_registry.py`。

## 2. 样本清单（10 条，均为 strict-parse 合法包）

| # | 目的 | TEI | PUSI | Prio | PID | TSC | AFC | CC | 备注 |
|---|---|---|---|---|---|---|---|---|---|
| 0 | 最小 section 起始包（PAT 形态） | 0 | 1 | 0 | 0x0000 | 00 | 01 | 0 | payload[0]=pointer_field 0 |
| 1 | TEI 置位 | 1 | 0 | 0 | 0x0000 | 00 | 01 | 1 | |
| 2 | 优先级置位 + CC 上边沿 | 0 | 0 | 1 | 0x0001 | 00 | 01 | 15 | |
| 3 | Null PID 0x1FFF | 0 | 0 | 0 | 0x1FFF | 00 | 01 | 0 | 规范 Null 包形态（0xFF body） |
| 4 | 最大非保留 PID 0x1FFE + PUSI | 0 | 1 | 0 | 0x1FFE | 00 | 01 | 8 | |
| 5 | reserved scrambling 01 | 0 | 0 | 0 | 0x0010 | 01 | 01 | 3 | §5.3：原值保留 + `TS_SCRAMBLING_RESERVED` |
| 6 | even scrambling + AFC=11 带 PCR | 0 | 0 | 0 | 0x0100 | 10 | 11 | 4 | AF 内 PCR(base 12345, ext 0)，AF len 180 |
| 7 | odd scrambling + adaptation-only CC 重用 | 0 | 0 | 0 | 0x0100 | 11 | 10 | 4 | §5.4：与 #6 同 PID 连续，CC 不推进 |
| 8 | adaptation-only + discontinuity 标志 + AF len 183 上边沿 | 0 | 0 | 0 | 0x0011 | 00 | 10 | 9 | flags=0x80 |
| 9 | AFC=11 零长 adaptation field 下边沿 | 0 | 1 | 0 | 0x0012 | 00 | 11 | 10 | AF length byte 0 |

## 3. 语义检查（conformance 断言，`test_packet_header_set_vector.py`）

1. 每个样本 strict parse 成功，8 个头字段与上表逐项一致。
2. 样本 5：`validate()` 产生 `TS_SCRAMBLING_RESERVED`；wire 字节保留 01（无静默改写）。
3. 样本 6/7：同 PID 连续，#7 adaptation-only 重用 #6 的 CC=4（§5.4 规则）。
4. 样本 6：AF 内 PCR 解码为 base=12345 / ext=0（与 `PCR-PTS.md` 位打包互证）。
5. 样本 8：`discontinuity_indicator == True`；样本 9：AF length byte == 0。
