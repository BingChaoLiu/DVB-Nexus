# TS Core Requirement Traceability

**Status:** DRAFT  
**Scope:** SPEC-100～SPEC-108  
**Rule:** 一个 Requirement 至少映射到一个自动化测试；没有证据不得标记 PASS。

## SPEC-100 — TS Packet

| Requirement ID | Requirement | Primary test |
|---|---|---|
| REQ-TS-100-001 | 有效 188-byte Packet parse/serialize round-trip | `test_packet_round_trip` |
| REQ-TS-100-002 | Header 字段位宽和 bit layout 正确 | `test_header_fields` |
| REQ-TS-100-003 | Adaptation Field parse/serialize 和 opaque extension 保留 | `test_adaptation_field_round_trip` |
| REQ-TS-100-004 | 长度/偏移校验安全 | `test_packet_malformed_boundaries` |
| REQ-TS-100-005 | CCAllocator PID 独立、payload 规则和 wrap | `test_cc_allocator` |
| REQ-TS-100-006 | fuzz/property test 稳定 | `test_packet_fuzz_safety` |

## SPEC-101 — CRC32

| Requirement ID | Requirement | Primary test |
|---|---|---|
| REQ-TS-101-001 | MPEG-2 CRC 参数和 check vector 正确 | `test_crc32_mpeg2_check_vector` |
| REQ-TS-101-002 | 增量与一次性计算一致 | `test_crc_incremental_equivalence` |
| REQ-TS-101-003 | append/verify big-endian/remainder 语义正确 | `test_crc_append_verify` |
| REQ-TS-101-004 | 标准库独立、边界测试通过 | `test_crc_input_validation` |

## SPEC-102 — PSI Section

| Requirement ID | Requirement | Primary test |
|---|---|---|
| REQ-TS-102-001 | Section Header/length 正确 | `test_section_header_and_length` |
| REQ-TS-102-002 | Long-form 公共字段 round-trip | `test_long_section_round_trip` |
| REQ-TS-102-003 | CRC policy 正确 | `test_section_crc_policy` |
| REQ-TS-102-004 | PUSI/pointer/跨包/多 Section 组装正确 | `test_section_assembler` |
| REQ-TS-102-005 | discontinuity/EOF partial 显式处理 | `test_section_assembler_recovery` |
| REQ-TS-102-006 | 畸形长度安全 | `test_section_malformed_lengths` |

## SPEC-103 — PAT/PMT

| Requirement ID | Requirement | Primary test |
|---|---|---|
| REQ-TS-103-001 | PAT 正确编解码 | `test_pat_round_trip` |
| REQ-TS-103-002 | PMT 正确编解码 | `test_pmt_round_trip` |
| REQ-TS-103-003 | CRC/version/section number 正确 | `test_table_metadata_and_crc` |
| REQ-TS-103-004 | program 0 与 PAT→PMT→ES 关联正确 | `test_program_pid_mapping` |
| REQ-TS-103-005 | loop length 越界安全 | `test_table_loop_bounds` |
| REQ-TS-103-006 | 多 Section 不混合版本 | `test_table_version_aggregation` |

## SPEC-104 — PES

| Requirement ID | Requirement | Primary test |
|---|---|---|
| REQ-TS-104-001 | PES Header 正确编码/解析 | `test_pes_header_round_trip` |
| REQ-TS-104-002 | PTS/DTS 33-bit marker/prefix 正确 | `test_pes_pts_dts` |
| REQ-TS-104-003 | packet_length 语义正确 | `test_pes_packet_length` |
| REQ-TS-104-004 | PUSI/跨包组装正确 | `test_pes_assembler` |
| REQ-TS-104-005 | 畸形输入和 buffer 上限安全 | `test_pes_malformed_and_limits` |
| REQ-TS-104-006 | synthetic payload 不标为 playback-ready | `test_analysis_only_profile_metadata` |

## SPEC-105 — PCR/Clock

| Requirement ID | Requirement | Primary test |
|---|---|---|
| REQ-TS-105-001 | PCR 6-byte 编码/解码正确 | `test_pcr_round_trip` |
| REQ-TS-105-002 | reserved bits 和 ext range 校验 | `test_pcr_invalid_fields` |
| REQ-TS-105-003 | PTS/DTS 编码/解码正确 | `test_pts_encoding` |
| REQ-TS-105-004 | 整数 27MHz/90kHz 换算 | `test_clock_integer_conversion` |
| REQ-TS-105-005 | wrap/modular delta 正确 | `test_clock_wrap` |
| REQ-TS-105-006 | 无 wall-clock 耦合 | `test_media_clock_is_pure` |

## SPEC-106 — Packetizer

| Requirement ID | Requirement | Primary test |
|---|---|---|
| REQ-TS-106-001 | Section pointer/PUSI 正确 | `test_section_packetizer` |
| REQ-TS-106-002 | PES PUSI 和顺序正确 | `test_pes_packetizer` |
| REQ-TS-106-003 | 每个输出固定 188 bytes | `test_packetizer_packet_size` |
| REQ-TS-106-004 | AF stuffing 容量正确 | `test_packetizer_adaptation_stuffing` |
| REQ-TS-106-005 | CCAllocator 一致使用 | `test_packetizer_cc` |
| REQ-TS-106-006 | Section/PES 重组 round-trip | `test_packetizer_round_trip` |

## SPEC-107 — Mux

| Requirement ID | Requirement | Primary test |
|---|---|---|
| REQ-TS-107-001 | packet slot 数和 188 bytes 正确 | `test_mux_packet_count` |
| REQ-TS-107-002 | CBR slot 使用精确整数时间 | `test_mux_no_float_drift` |
| REQ-TS-107-003 | PAT/PMT 周期正确 | `test_mux_table_repetition` |
| REQ-TS-107-004 | PCR 插入不破坏 Payload | `test_mux_pcr_insertion` |
| REQ-TS-107-005 | Null Packet 补齐 | `test_mux_null_padding` |
| REQ-TS-107-006 | 超载/过期显式报错 | `test_mux_overcommit` |
| REQ-TS-107-007 | 调度顺序确定性 | `test_mux_determinism` |

## SPEC-108 — Generator

| Requirement ID | Requirement | Primary test |
|---|---|---|
| REQ-TS-108-001 | GeneratorConfig 校验 | `test_generator_config_validation` |
| REQ-TS-108-002 | 生成 188-byte TS | `test_generator_packet_format` |
| REQ-TS-108-003 | PAT/PMT/PES/PCR 可回读 | `test_generator_self_parse` |
| REQ-TS-108-004 | CBR/packet slot 符合配置 | `test_generator_mux_integration` |
| REQ-TS-108-005 | 相同输入 SHA-256 相同 | `test_generator_determinism` |
| REQ-TS-108-006 | Generator 与 Fault Injector 解耦 | `test_generator_clean_baseline` |
| REQ-TS-108-007 | analysis_only 边界明确 | `test_generator_profile` |
| REQ-TS-108-008 | TSDuck 集成报告有真实证据 | `test_tsduck_integration` |

## 测试证据最低要求

实现报告必须逐项列出：Requirement ID、Test Case ID、执行命令、通过/失败/跳过、测试环境和日志/报告 Artifact。TSDuck 未安装或无法执行时只能标记 `BLOCKED` / `NOT RUN`。
