---
spec_id: SPEC-101
title: MPEG-2 CRC-32 Core
version: 0.5.0
status: APPROVED
phase: MVP
owner: TS Core
priority: P0
depends_on: [SPEC-004]
requirements: [REQ-TS-101-001, REQ-TS-101-002, REQ-TS-101-003, REQ-TS-101-004]
---

# SPEC-101 — MPEG-2 CRC32

## 1. 目标

实现 CRC-32/MPEG-2（非反射、无最终异或）的纯函数、可增量计算接口和 CRC 字段追加/校验工具，供 PSI Section（SPEC-102）及后续表模块使用。

## 2. 范围

**In Scope：** CRC 参数固定、bytes 输入、增量 update、整数输出、big-endian CRC 追加、Section remainder 校验、测试向量。  
**Out of Scope：** Ethernet/ZIP CRC-32（IEEE reflected）、CRC-32C、纠错码、自动猜测 CRC 算法、硬件加速。

## 3. 算法参数

| 参数 | 值 |
|---|---|
| Name | CRC-32/MPEG-2 |
| Width | 32 |
| Polynomial | `0x04C11DB7` |
| Init | `0xFFFFFFFF` |
| RefIn | `false` |
| RefOut | `false` |
| XorOut | `0x00000000` |
| Check (`123456789`) | `0x0376E6E7` |

结果按 32-bit 无符号整数处理。超出 32-bit 的内部状态必须在每一步按 `0xFFFFFFFF` mask。

## 4. 公共接口

```python
CRC32_MPEG2_POLY = 0x04C11DB7
CRC32_MPEG2_INIT = 0xFFFFFFFF


def mpeg2_crc32(data: bytes, *, initial: int = CRC32_MPEG2_INIT) -> int: ...

def verify_mpeg2_crc32(data_including_crc: bytes) -> bool: ...

def append_mpeg2_crc32(data: bytes) -> bytes: ...

class MPEG2CRC32:
    def __init__(self, initial: int = CRC32_MPEG2_INIT) -> None: ...
    def update(self, data: bytes) -> None: ...
    def value(self) -> int: ...
    def copy(self) -> "MPEG2CRC32": ...
```

`mpeg2_crc32` 只计算指定 bytes，不自动 append。`append_mpeg2_crc32` 返回 `data + crc_be32`。`verify_mpeg2_crc32` 对整个 section（包含已附加 CRC）计算 remainder，remainder 为 0 返回 True。

## 5. 实现要求

- 首选 MSB-first、左移的 bitwise reference 实现作为清晰、可审查的基准。
- 可使用 256 项 lookup table 优化，但必须有与 bitwise reference 的交叉测试。
- 支持空输入；返回初始状态 `0xFFFFFFFF`。
- 支持增量输入：对 `A` 后接 `B` 的 update 结果必须等于一次性计算 `A+B`。
- 输出 CRC 按 big-endian：例如数值 `0x0376E6E7` 编码为 `03 76 E6 E7`。
- 不依赖 `zlib.crc32()` 作为实现，因为其常见参数/反射行为不是 MPEG-2 CRC 参数。

## 6. 错误处理

- 输入必须是 bytes-like（项目可明确支持 `bytes`、`bytearray`、`memoryview`）。
- `initial` 必须是 0..0xFFFFFFFF。
- 其他类型或非法初值抛 `TypeError` / `ValueError`，不得静默截断。
- 对空 payload 不视为错误。

## 7. 测试规格

1. Check vector：`b"123456789"` → `0x0376E6E7`。
2. Empty vector：空输入 → `0xFFFFFFFF`。
3. Append and verify：对任意数据 `verify(append(data))` 为 True。
4. Corruption：追加 CRC 后翻转任意一个 bit，校验为 False。
5. Endianness：CRC bytes 必须 big-endian。
6. Incremental：拆分点覆盖 0、1、中点、len(data)-1、len(data)。
7. Cross implementation：bitwise 与 table-driven 在固定随机 seed 的大量向量上一致。
8. Section fixture：PAT/PMT section 含 CRC 后 `verify` 为 True，破坏一个内容位则 False。

## 8. 验收标准

- `REQ-TS-101-001`：所有 CRC 参数与测试向量一致。
- `REQ-TS-101-002`：一次性和增量计算结果一致。
- `REQ-TS-101-003`：CRC append/verify 的端序和 remainder 语义正确。
- `REQ-TS-101-004`：无第三方运行时依赖，边界测试通过。

## 9. 交付要求

建议文件：`ts/crc.py`；测试：`tests/unit/ts/test_crc.py`；公共测试向量引用 `docs/test-vectors/CRC32-MPEG2.md`。CRC 实现必须与 PAT/PMT 生成逻辑解耦。

## 10. 参考

- ITU-T H.222.0 (04/2025), PSI section CRC syntax and CRC-32/MPEG-2 algorithm context。
- CRC-32/MPEG-2 parameters and check vector: <https://reveng.sourceforge.io/crc-catalogue/17plus.htm>（用于算法交叉检查；标准文本仍为规范性依据）。
