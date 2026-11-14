# Test Vectors — CRC-32/MPEG-2

**Algorithm:** CRC-32/MPEG-2  
**Poly:** `0x04C11DB7`  
**Init:** `0xFFFFFFFF`  
**RefIn/RefOut:** false/false  
**XorOut:** `0x00000000`

## 1. Published check value

| Input bytes | Expected CRC |
|---|---|
| ASCII `123456789` (`31 32 33 34 35 36 37 38 39`) | `0x0376E6E7` |

Expected big-endian CRC bytes: `03 76 E6 E7`.

## 2. Semantic check

For `message = b"123456789"`:

1. `mpeg2_crc32(message) == 0x0376E6E7`。
2. `append_mpeg2_crc32(message)` ends with `03 76 E6 E7`。
3. `verify_mpeg2_crc32(message + 03 76 E6 E7) is True`。
4. Flip any one bit of the combined byte sequence; verification must be False.

## 3. Important distinction

Do not compare this value with `zlib.crc32()` without accounting for the different reflection/final XOR parameters. The production implementation must follow SPEC-101 exactly.
