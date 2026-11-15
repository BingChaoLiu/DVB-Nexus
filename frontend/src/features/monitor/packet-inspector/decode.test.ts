// SPEC-404 §10 golden-driven decoder tests (REQ-UI-404-002/004).
//
// Fixture discipline (plan-65.md §4.1): every expected value comes from the
// registered golden vectors' real bytes + expectations.json — never from
// recomputing the way the decoder does. The 188×index offset proof rides on
// the slice boundary: every sliced packet must start with the sync byte and
// be exactly 188 bytes.
//
// Assertion face = decodable fields (tei/pusi/priority/pid/scrambling/afc/cc
// + af_length/discontinuity_indicator/pcr{base,extension}). Annotation-only
// keys in expectations.json (`pointer_field`/`payload_fill`/
// `validation_issue`/`cc_rule`) document generator intent, not wire-decodable
// fields, and are deliberately skipped (declared, not silently dropped).
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { parseTsPacket, toHexDump } from "./decode";

const REPO_ROOT = resolve(import.meta.dirname, "../../../../..");
const GOLDEN_DIR = resolve(REPO_ROOT, "docs/test-vectors/golden");

function goldenBytes(vectorId: string): Uint8Array {
  const raw = readFileSync(resolve(GOLDEN_DIR, vectorId, `${vectorId}.ts`));
  return new Uint8Array(raw.buffer, raw.byteOffset, raw.byteLength);
}

interface HeaderExpectation {
  locator: { packet_index: number };
  detail: {
    tei: number;
    pusi: number;
    priority: number;
    pid: number;
    scrambling: number;
    afc: number;
    cc: number;
    af_length?: number;
    discontinuity_indicator?: boolean;
    pcr?: { base: number; extension: number };
    /** pcr-wrap expectations carry flat PCR keys instead of a pcr object. */
    pcr_base?: number;
    pcr_extension?: number;
  };
}

function goldenExpectations(vectorId: string): HeaderExpectation[] {
  const doc = JSON.parse(
    readFileSync(resolve(GOLDEN_DIR, vectorId, "expectations.json"), "utf-8"),
  ) as { expectations: HeaderExpectation[] };
  return doc.expectations;
}

describe("parseTsPacket — golden packet-header-set (SPEC-100 §3 wire table)", () => {
  const bytes = goldenBytes("packet-header-set");
  const expectations = goldenExpectations("packet-header-set");

  it("fixture is 10 aligned 188-byte packets, every slice boundary on sync", () => {
    expect(expectations).toHaveLength(10);
    expect(bytes.length).toBe(188 * 10);
    for (const e of expectations) {
      const slice = bytes.subarray(188 * e.locator.packet_index, 188 * e.locator.packet_index + 188);
      expect(slice.length).toBe(188); // 188×index offset lands exactly on a packet
      expect(slice[0]).toBe(0x47); // TS_SYNC_BYTE at every 188×index boundary
    }
  });

  for (const e of expectations) {
    it(`packet ${e.locator.packet_index} header fields match the golden expectation`, () => {
      const slice = bytes.subarray(188 * e.locator.packet_index, 188 * e.locator.packet_index + 188);
      const view = parseTsPacket(slice);
      expect(view.header.sync_byte).toBe(0x47);
      expect(view.header.sync_byte_ok).toBe(true);
      expect(view.header.transport_error_indicator).toBe(e.detail.tei === 1);
      expect(view.header.payload_unit_start_indicator).toBe(e.detail.pusi === 1);
      expect(view.header.transport_priority).toBe(e.detail.priority === 1);
      expect(view.header.pid).toBe(e.detail.pid);
      expect(view.header.pid_is_null).toBe(e.detail.pid === 8191);
      expect(view.header.transport_scrambling_control).toBe(e.detail.scrambling);
      expect(view.header.adaptation_field_control).toBe(e.detail.afc);
      expect(view.header.afc_reserved).toBe(e.detail.afc === 0);
      expect(view.header.continuity_counter).toBe(e.detail.cc);
    });
  }
});

describe("parseTsPacket — AF face over golden packet-header-set (SPEC-100 §5.2)", () => {
  const bytes = goldenBytes("packet-header-set");

  function packetView(index: number) {
    return parseTsPacket(bytes.subarray(188 * index, 188 * index + 188));
  }

  it("packet 0 AFC=01 payload-only → no adaptation field", () => {
    expect(packetView(0).header.adaptation_field_control).toBe(1);
    expect(packetView(0).adaptation_field).toBeNull();
  });

  it("packet 6 AFC=11 both → flags present + PCR 12345/0 (golden)", () => {
    const af = packetView(6).adaptation_field;
    expect(af).not.toBeNull();
    expect(af!.flags_present).toBe(true);
    expect(af!.pcr_flag).toBe(true);
    expect(af!.pcr).toEqual({ base: 12345, reserved_ok: true, extension: 0, combined_ticks: 12345 * 300 });
  });

  it("packet 7 AFC=10 adaptation-only → AF present", () => {
    const af = packetView(7).adaptation_field;
    expect(af).not.toBeNull();
    expect(af!.flags_present).toBe(true);
  });

  it("packet 8 AF length 183 with discontinuity_indicator=true (golden)", () => {
    const af = packetView(8).adaptation_field;
    expect(af).not.toBeNull();
    expect(af!.af_length).toBe(183);
    expect(af!.discontinuity_indicator).toBe(true);
    expect(af!.random_access_indicator).toBe(false);
  });

  it("packet 9 AFC=11 with AF length 0 → no flags byte (SPEC-100 §5.2)", () => {
    const af = packetView(9).adaptation_field;
    expect(af).not.toBeNull();
    expect(af!.af_length).toBe(0);
    expect(af!.flags_present).toBe(false);
    expect(af!.flags).toBeNull();
    expect(af!.pcr_flag).toBe(false);
    expect(af!.pcr).toBeNull();
  });
});

describe("parseTsPacket — golden pcr-wrap (SPEC-105 packing, 2^33 boundary)", () => {
  const bytes = goldenBytes("pcr-wrap");
  const expectations = goldenExpectations("pcr-wrap");

  it("fixture is 6 aligned 188-byte packets on sync boundaries", () => {
    expect(expectations).toHaveLength(6);
    expect(bytes.length).toBe(188 * 6);
    for (const e of expectations) {
      const slice = bytes.subarray(188 * e.locator.packet_index, 188 * e.locator.packet_index + 188);
      expect(slice.length).toBe(188);
      expect(slice[0]).toBe(0x47);
    }
  });

  for (const e of expectations) {
    it(`packet ${e.locator.packet_index} PCR base/extension match the golden expectation`, () => {
      const pcrBase = e.detail.pcr_base;
      const pcrExtension = e.detail.pcr_extension;
      expect(pcrBase).toBeDefined();
      expect(pcrExtension).toBeDefined();
      const view = parseTsPacket(bytes.subarray(188 * e.locator.packet_index, 188 * e.locator.packet_index + 188));
      const af = view.adaptation_field;
      expect(af).not.toBeNull();
      expect(af!.pcr_flag).toBe(true);
      expect(af!.pcr!.base).toBe(pcrBase!);
      expect(af!.pcr!.extension).toBe(pcrExtension!);
      expect(af!.pcr!.reserved_ok).toBe(true);
      expect(af!.pcr!.combined_ticks).toBe(pcrBase! * 300 + pcrExtension!);
    });
  }

  it("boundary packet 2 reads base 2^33-1 exactly (32-bit-safe arithmetic)", () => {
    const view = parseTsPacket(bytes.subarray(188 * 2, 188 * 2 + 188));
    expect(view.adaptation_field!.pcr!.base).toBe(2 ** 33 - 1);
  });
});

describe("parseTsPacket — golden cc-discontinuity pair (equal-slot geometry)", () => {
  const faulted = goldenBytes("cc-discontinuity");
  const baseline = goldenBytes("cc-discontinuity-baseline");

  it("both streams slice into aligned 188-byte packets starting on sync", () => {
    for (const bytes of [faulted, baseline]) {
      expect(bytes.length % 188).toBe(0);
      for (let i = 0; i < bytes.length / 188; i++) {
        const slice = bytes.subarray(188 * i, 188 * i + 188);
        expect(slice[0]).toBe(0x47); // same index = same slot, offsets verified per slice
      }
    }
  });

  it("packet counts match across the pair (shared packet order, ADR-0007 item 4)", () => {
    expect(faulted.length).toBe(baseline.length);
  });

  it("header decode at slot 0 agrees between the streams (pre-fault slots are identical)", () => {
    const f = parseTsPacket(faulted.subarray(0, 188));
    const b = parseTsPacket(baseline.subarray(0, 188));
    expect(f.header).toEqual(b.header);
  });
});

describe("toHexDump — golden packet-header-set packet 0 (SPEC-404 §4.4 format)", () => {
  const bytes = goldenBytes("packet-header-set");

  it("row 0 opens 47 40 00 10 — hand-derived from the SPEC-100 §3 table (pusi=1→0x40, afc=1→0x10)", () => {
    const rows = toHexDump(bytes.subarray(0, 188));
    expect(rows[0].hex.slice(0, 4)).toEqual(["47", "40", "00", "10"]);
    expect(rows[0].ascii.slice(0, 4)).toBe("G@..");
  });

  it("188 bytes → 12 rows (11×16 + 12), offsets step by 16 from 0", () => {
    const rows = toHexDump(bytes.subarray(0, 188));
    expect(rows).toHaveLength(12);
    for (let r = 0; r < 11; r++) {
      expect(rows[r].offset).toBe(r * 16);
      expect(rows[r].hex).toHaveLength(16);
    }
    expect(rows[11].offset).toBe(176);
    expect(rows[11].hex).toHaveLength(12);
  });

  it("hex cells are the wire bytes verbatim (2-char lowercase, null-packet body reads ff)", () => {
    // packet 3 = canonical null packet (pid 8191, afc=1, cc=0, body 0xff fill
    // per expectations payload_fill note): hand-derived header 47 1f ff 10,
    // then the payload starts at byte 4 directly (AFC=01 → no AF length byte).
    const rows = toHexDump(bytes.subarray(188 * 3, 188 * 3 + 188));
    expect(rows[0].hex.slice(0, 4)).toEqual(["47", "1f", "ff", "10"]);
    expect(rows[0].hex.slice(4, 8)).toEqual(["ff", "ff", "ff", "ff"]); // 0xff payload fill
    expect(rows[0].ascii).not.toMatch(/[\x00-\x1f\x7f-\xff]/); // non-printable → "." only
  });

  it("ascii column keeps printable bytes verbatim and dots the rest", () => {
    const rows = toHexDump(bytes.subarray(0, 188));
    for (const row of rows) {
      expect(row.ascii).toHaveLength(row.hex.length);
      for (let c = 0; c < row.ascii.length; c++) {
        const code = row.ascii.charCodeAt(c);
        expect(code === 0x2e || (code >= 0x20 && code <= 0x7e)).toBe(true);
      }
    }
  });
});

describe("parseTsPacket — truncation guard (wire shorter than 188)", () => {
  it("185-byte wire marks truncated=true and still decodes the header", () => {
    const full = goldenBytes("packet-header-set").subarray(0, 185);
    const view = parseTsPacket(full);
    expect(view.truncated).toBe(true);
    expect(view.header.sync_byte).toBe(0x47);
  });

  it("full 188-byte wire marks truncated=false", () => {
    const view = parseTsPacket(goldenBytes("packet-header-set").subarray(0, 188));
    expect(view.truncated).toBe(false);
  });

  it("toHexDump on a truncated wire still formats what arrived", () => {
    const rows = toHexDump(goldenBytes("packet-header-set").subarray(0, 185));
    expect(rows).toHaveLength(12);
    expect(rows[11].hex).toHaveLength(9); // 176..184 inclusive
  });
});
