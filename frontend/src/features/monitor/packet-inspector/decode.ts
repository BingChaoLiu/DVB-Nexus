// SPEC-404 §5.2/§7.1 — pure TS packet decoder (188 bytes → field view).
//
// Bit semantics are a verbatim mirror of SPEC-100 §3 (implementation anchor
// src/ts/packet.py L51-118); AF flag masks mirror src/ts/adaptation_field.py
// L237-244/367-369 and the PCR bit packing mirrors src/ts/pcr.py L9-14
// (SPEC-105). Pure frontend: no React, no third-party parsing dependency
// (SPEC-404 §2.2; ticket #18 backend-zero-change ruling).
//
// Wire-truth discipline: the decoder never throws on odd wire values — it
// renders facts (afc_reserved, sync_byte_ok=false, truncation note) and lets
// the presentation layer branch (SPEC-404 §4.5/§8).

/** Masks for the 8-bit AF flags byte (SPEC-100 §5.2; adaptation_field.py). */
const AF_FLAG_DISCONTINUITY = 0x80;
const AF_FLAG_RANDOM_ACCESS = 0x40;
const AF_FLAG_PRIORITY = 0x20;
const AF_FLAG_PCR = 0x10;
const AF_FLAG_OPCR = 0x08;
const AF_FLAG_SPLICE_COUNTDOWN = 0x04;
const AF_FLAG_PRIVATE_DATA = 0x02;
const AF_FLAG_EXTENSION = 0x01;

export const TS_PACKET_SIZE = 188;
export const TS_SYNC_BYTE = 0x47;
export const PID_NULL = 0x1fff;

export interface TsHeaderView {
  sync_byte: number;
  sync_byte_ok: boolean;
  transport_error_indicator: boolean;
  payload_unit_start_indicator: boolean;
  transport_priority: boolean;
  pid: number;
  pid_is_null: boolean;
  transport_scrambling_control: number;
  adaptation_field_control: number;
  afc_reserved: boolean;
  continuity_counter: number;
}

export interface PcrView {
  base: number;
  reserved_ok: boolean;
  extension: number;
  combined_ticks: number;
}

export interface AfView {
  af_length: number;
  flags_present: boolean;
  flags: number | null;
  discontinuity_indicator: boolean;
  random_access_indicator: boolean;
  elementary_stream_priority_indicator: boolean;
  pcr_flag: boolean;
  opcr_flag: boolean;
  splice_countdown_flag: boolean;
  transport_private_data_flag: boolean;
  adaptation_field_extension_flag: boolean;
  pcr: PcrView | null;
}

export interface TsPacketView {
  header: TsHeaderView;
  /** null for AFC=01 (no AF) and AFC=00 (reserved — not parsed, §4.5). */
  adaptation_field: AfView | null;
  /** Wire shorter than 188 bytes — decoder still reports what it saw. */
  truncated: boolean;
}

export interface HexRow {
  /** Byte offset of the row start (0, 16, 32, …). */
  offset: number;
  /** Two-char lowercase hex per byte cell. */
  hex: string[];
  /** Printable 0x20..0x7E verbatim, "." otherwise — one char per cell. */
  ascii: string;
}

/** 188 bytes → 12 structured hex rows (11×16 + 12; SPEC-404 §4.4). */
export function toHexDump(bytes: Uint8Array): HexRow[] {
  const rows: HexRow[] = [];
  for (let start = 0; start < bytes.length; start += 16) {
    const cells = Array.from(bytes.subarray(start, start + 16));
    rows.push({
      offset: start,
      hex: cells.map((b) => b.toString(16).padStart(2, "0")),
      ascii: cells.map((b) => (b >= 0x20 && b <= 0x7e ? String.fromCharCode(b) : ".")).join(""),
    });
  }
  return rows;
}

export function parseTsPacket(packet: Uint8Array): TsPacketView {
  const truncated = packet.length < TS_PACKET_SIZE;
  const sync_byte = packet[0] ?? 0;
  const b1 = packet[1] ?? 0;
  const b2 = packet[2] ?? 0;
  const b3 = packet[3] ?? 0;

  const header: TsHeaderView = {
    sync_byte,
    sync_byte_ok: sync_byte === TS_SYNC_BYTE,
    transport_error_indicator: ((b1 >>> 7) & 1) === 1,
    payload_unit_start_indicator: ((b1 >>> 6) & 1) === 1,
    transport_priority: ((b1 >>> 5) & 1) === 1,
    pid: ((b1 & 0x1f) << 8) | b2,
    pid_is_null: (((b1 & 0x1f) << 8) | b2) === PID_NULL,
    transport_scrambling_control: (b3 >>> 6) & 0x3,
    adaptation_field_control: (b3 >>> 4) & 0x3,
    afc_reserved: ((b3 >>> 4) & 0x3) === 0,
    continuity_counter: b3 & 0x0f,
  };

  const adaptation_field = parseAdaptationField(packet, header.adaptation_field_control);
  return { header, adaptation_field, truncated };
}

function parseAdaptationField(
  packet: Uint8Array,
  afc: number,
): AfView | null {
  // AFC=01 payload-only: no AF region. AFC=00 reserved/invalid: the AF
  // region is not parsed (SPEC-100 §3 — wire fact surfaced via afc_reserved).
  if (afc === 0b00 || afc === 0b01) return null;
  const af_length = packet[4] ?? 0;
  const base: AfView = {
    af_length,
    flags_present: false,
    flags: null,
    discontinuity_indicator: false,
    random_access_indicator: false,
    elementary_stream_priority_indicator: false,
    pcr_flag: false,
    opcr_flag: false,
    splice_countdown_flag: false,
    transport_private_data_flag: false,
    adaptation_field_extension_flag: false,
    pcr: null,
  };
  // af_length === 0 → no flags byte exists (SPEC-100 §5.2).
  if (af_length === 0) return base;
  const flags = packet[5] ?? 0;
  const view: AfView = {
    ...base,
    flags_present: true,
    flags,
    discontinuity_indicator: (flags & AF_FLAG_DISCONTINUITY) !== 0,
    random_access_indicator: (flags & AF_FLAG_RANDOM_ACCESS) !== 0,
    elementary_stream_priority_indicator: (flags & AF_FLAG_PRIORITY) !== 0,
    pcr_flag: (flags & AF_FLAG_PCR) !== 0,
    opcr_flag: (flags & AF_FLAG_OPCR) !== 0,
    splice_countdown_flag: (flags & AF_FLAG_SPLICE_COUNTDOWN) !== 0,
    transport_private_data_flag: (flags & AF_FLAG_PRIVATE_DATA) !== 0,
    adaptation_field_extension_flag: (flags & AF_FLAG_EXTENSION) !== 0,
  };
  if (view.pcr_flag) view.pcr = parsePcr(packet, 6);
  return view;
}

/** PCR 6-byte packing (SPEC-105; src/ts/pcr.py L9-14): bytes 0..3 carry
 * base bits 32..1 big-endian, byte 4 bit 7 = base bit 0, bits 6..1 =
 * reserved (must read 111111), bit 0 + byte 5 = extension bits 8..0. */
function parsePcr(packet: Uint8Array, at: number): PcrView {
  const b0 = packet[at] ?? 0;
  const b1 = packet[at + 1] ?? 0;
  const b2 = packet[at + 2] ?? 0;
  const b3 = packet[at + 3] ?? 0;
  const b4 = packet[at + 4] ?? 0;
  const b5 = packet[at + 5] ?? 0;
  // be32 is the unsigned 32-bit big-endian of base bits 32..1; multiply in
  // number space (base spans 33 bits — a 32-bit `<< 1` would drop bit 32).
  const be32 = (((b0 << 24) | (b1 << 16) | (b2 << 8) | b3) >>> 0);
  const base = be32 * 2 + (b4 >>> 7);
  const reserved = (b4 >>> 1) & 0x3f;
  const extension = ((b4 & 0x01) << 8) | b5;
  return {
    base,
    reserved_ok: reserved === 0x3f,
    extension,
    combined_ticks: base * 300 + extension,
  };
}
