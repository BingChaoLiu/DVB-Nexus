# Test Vectors — PCR / PTS / DTS

这些向量用于位编码、marker、reserved bits、边界和 wrap 测试。实现仍需以 ITU-T H.222.0 适用版本为规范性依据。

## 1. PCR vectors

PCR encoding bytes for `base=0`, `extension=0`:

```text
00 00 00 00 7E 00
```

PCR encoding bytes for `base=1`, `extension=0`:

```text
00 00 00 00 FE 00
```

最大合法字段值 `base=2^33-1`, `extension=299`：

```text
FF FF FF FF FF 2B
```

注：第五字节中 reserved six bits 必须为 `111111`；extension=299 (`0x12B`)。

## 2. PTS vectors

使用 PTS-only prefix `0010`：

| Value (90 kHz ticks) | Encoded bytes |
|---:|---|
| 0 | `21 00 01 00 01` |
| 1 | `21 00 01 00 03` |
| 2^33-1 | `2F FF FF FF FF` |

使用 PTS prefix `0011`（PTS+DTS 情况）时，除最高 nibble 外编码结构相同；DTS prefix 为 `0001`。

## 3. Wrap vector

`previous = 2^33 - 1`, `current = 0`, `modulus = 2^33`，前向 modular delta 应为 1。

PCR combined wrap modulus：`2^33 * 300` 27-MHz ticks。

## 4. Validation vectors

- PCR extension 300 或 511：拒绝。
- PCR reserved bits 不全为 1：拒绝。
- PTS 任意 marker bit 为 0：拒绝。
- PTS/DTS 传入负值或 `2^33`：编码 API 拒绝，不静默 mask。
