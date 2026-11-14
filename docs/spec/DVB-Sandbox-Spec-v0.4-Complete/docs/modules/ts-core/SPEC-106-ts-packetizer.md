---
spec_id: SPEC-106
title: PSI and PES to TS Packetization
version: 0.5.0
status: APPROVED
phase: MVP
owner: TS Core
priority: P0
depends_on: [SPEC-100, SPEC-101, SPEC-102, SPEC-104, SPEC-105, SPEC-004]
requirements: [REQ-TS-106-001, REQ-TS-106-002, REQ-TS-106-003, REQ-TS-106-004, REQ-TS-106-005, REQ-TS-106-006]
---

# SPEC-106 — TS Packetizer

## 1. 目标

将完整 PSI Section 和 PES byte sequence 分割为一系列固定 188-byte TS Packet，正确设置 PID、PUSI、Adaptation Field、Payload 边界和 CC。Packetizer 是 Section/PES 与 TS Packet 的唯一封装层。

## 2. 范围

**In Scope：** SectionPacketizer、PESPacketizer；跨 Packet 分片；Section pointer_field；PUSI；CCAllocator 集成；可配置 PCR/随机访问标记；adaptation-only PCR 包构造（`build_pcr_only_packet`）；AF stuffing；Packet count 和 packet index。  
**Out of Scope：** Mux 多 PID 调度/CBR；实际 Fault Injection；TS 文件存储；自动码率控制；输入流 Packet 修复；PCR 附着 PES 首 Packet 之后的 mid-PES 插入（MVP 不支持）；AF `discontinuity_indicator` 的策略性设置（字段模型由 SPEC-100 提供，MVP 由调用者/故障路由经 `CCAllocator.reset` 处理）。

## 3. 输入与输出

- 输入 PSI：经过 SPEC-102 验证/序列化的完整 Section bytes。
- 输入 PES：经过 SPEC-104 序列化的完整 PES bytes。
- 输出：`Iterator[TSPacket]`，每个对象均可序列化为 188 bytes。
- 同一个 Packetizer 实例不跨独立 Run 共享 CCAllocator 状态。

## 4. 公共接口

```python
class SectionPacketizer:
    def __init__(self, pid: int, cc_allocator: CCAllocator) -> None: ...
    def packetize(self, section: PSISection | bytes) -> Iterator[TSPacket]: ...

class PESPacketizer:
    def __init__(self, pid: int, cc_allocator: CCAllocator) -> None: ...
    def packetize(
        self,
        pes: PESPacket | bytes,
        *,
        random_access: bool = False,
        first_packet_pcr: PCR | None = None,
    ) -> Iterator[TSPacket]: ...

def build_pcr_only_packet(pid: int, pcr: PCR, cc_allocator: CCAllocator) -> TSPacket: ...
```

`build_pcr_only_packet` 是 adaptation-only PCR 包的唯一构造权威：AFC=10、AF 占满 Header 后 184 bytes、含 PCR 字段与 `0xFF` stuffing；CC 遵循 SPEC-100 adaptation-only 语义（重用该 PID 最近 CC、不推进）。SPEC-107 Mux 在调度需要 PCR-only 包时调用本函数，不自行构造或修改 AF。

实现可提供更一般的 `PacketizationOptions`，但默认行为必须与本 Spec 一致。

## 5. PSI Section 封装

### 5.1 首包

- 首包 `PUSI=1`。
- Payload 第一个 byte 是 `pointer_field`。
- MVP 每个 Section 从新 Packet 开始，`pointer_field=0`；因此首包的 Section data 从 Payload offset 1 开始。
- 后续 Section continuation Packet 的 `PUSI=0`，不包含 pointer_field。

### 5.2 跨包

- 首包有效 Section 容量最大为 183 bytes（含前置 pointer_field 后总 Payload 上限 184）；后续 Packet Payload 上限 184 bytes。
- Section 不得截断或重排；所有 bytes 顺序保持不变。
- MVP 默认一次 packetize 只承载一个 Section，不在同一 Packet 结束后拼接另一个 Section；如剩余空间不足，使用合法 AF stuffing 或 PSI payload stuffing，必须实现策略一致。推荐对尾部不足部分使用 Adaptation Field 填充，以避免 stuffing 被解析器误认成下一 Section；若使用 `0xFF` PSI stuffing，需要确保 SectionAssembler 将其识别为 stuffing。
- PUSI 只在包含 Section 起始位置的 Packet 设置，不在 continuation Packet 设置。

## 6. PES 封装

- 一个 PES Packet 的首个 TS Packet 设置 `PUSI=1`。
- continuation Packet 设置 `PUSI=0`。
- PES payload 不插入 PSI pointer_field。
- PES byte sequence 必须保持连续，不得在中间插入 TS stuffing bytes。
- 最后一个 TS Packet 不足 184 payload bytes 时，使用 Adaptation Field 填充到 188 bytes，不得把任意 `0xFF` 追加到 PES bytes。
- 若需要在首包附带 PCR，则使用 adaptation_field_control=11，PCR 放入 AF，Payload 从正确 offset 开始；若 AF 空间不足，配置应失败而不是覆盖 PES bytes。
- `random_access_indicator` 只能由调用者显式请求；Packetizer 不从 payload 猜测 Access Unit 边界。

## 7. AF Stuffing 计算

对于 AFC=11：4-byte Header + 1-byte `adaptation_field_length` + `adaptation_field_length` bytes AF body + `payload_length` = 188。故 `adaptation_field_length = 183 - payload_length`，当该值为 0 时 AF 只有长度字节；当不需要 AF 且 payload 为 184 bytes 时 AFC=01。包含 flags/optional fields 时，必须保证 AF body 至少容纳相应字段。所有 AF stuffing bytes 为 `0xFF`。

对于 AFC=10：无 Payload，AF 总区域必须占满 184 bytes，CC 不递增。

## 8. CC 分配

- 所有 Packet 通过 SPEC-100 的同一个 `CCAllocator` 分配。
- 有 Payload 的 Packet 更新对应 PID CC；adaptation-only Packet 使用该 PID 当前 CC 且不推进。
- Null Packet 由 Mux 管理，不由普通 PES/Section Packetizer 创建。
- Packetizer 不允许在序列化后修改已分配 Packet 的 CC。

## 9. 错误码

- `PACKETIZER_PID_INVALID`
- `PACKETIZER_EMPTY_SECTION`
- `PACKETIZER_EMPTY_PES`
- `PACKETIZER_SECTION_HEADER_INVALID`
- `PACKETIZER_PES_HEADER_INVALID`
- `PACKETIZER_AF_CAPACITY_EXCEEDED`
- `PACKETIZER_PCR_DOES_NOT_FIT`
- `PACKETIZER_PACKET_SIZE_INVARIANT_FAILED`

## 10. 测试规格

- Section 长度 1、183、184、跨 2 包、跨多包。
- Section 首包 pointer_field=0；首包 PUSI=1；Continuation PUSI=0。
- PES 长度 1、183、184、185、多包。
- PES 首包 PUSI=1，其他 PUSI=0。
- PCR 插入首包时 Payload 偏移正确，PES 起始字节不被破坏。
- 最后一包 AF length/flags/stuffing 正确，所有包恰好 188 bytes。
- CC 按 PID 独立，Payload 包递增，adaptation-only 不递增，15→0 wrap。
- 用 SPEC-102 SectionAssembler 和 SPEC-104 PESAssembler 反向重组，结果与原始输入 bytes 完全一致。
- Null packet 不由 Packetizer 生成。
- `build_pcr_only_packet`：AFC=10、恰好 188 bytes、PCR 可解码、CC 重用该 PID 最近 CC 且不推进。

## 11. 验收标准

- `REQ-TS-106-001`：Section packetization 的 pointer/PUSI 语义正确。
- `REQ-TS-106-002`：PES packetization 的 PUSI 和字节顺序正确。
- `REQ-TS-106-003`：所有输出 Packet 固定 188 bytes。
- `REQ-TS-106-004`：AF stuffing 和可选字段容量计算正确。
- `REQ-TS-106-005`：CCAllocator 状态在所有 packetization 路径一致。
- `REQ-TS-106-006`：Section/PES 双向重组 round-trip 通过。

## 12. 实现注意事项

MVP 每个 Section 独立起始 packet 是允许的效率折中，不要在没有 SectionAssembler 联合测试的情况下引入多 Section 同包优化。后续优化必须保持现有输出可解析。

## 13. 交付要求

建议文件：`ts/packetizer/section_packetizer.py`、`ts/packetizer/pes_packetizer.py`、`ts/packetizer/stuffing.py`。提交 `Packetizer Round-trip` 集成报告。
