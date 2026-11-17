// BissEvidence derivation (#134 seam): the journal face's hand-off to the
// packet inspector's BissAnnotation (#132 BissEvidenceAnnotation prop). The
// derivation reads journal FACTS only — biss.* envelope payloads verbatim
// (mode / key_fingerprint[_ref] / mutation_log_ref); key material never
// crosses this face because the wire payloads never carry it (SPEC-610 §9).
import { describe, expect, it } from "vitest";
import type { JournalEnvelope } from "../../../ws/SessionStream";
import { deriveBissEvidence } from "./bissEvidence";

const bissScramble = (seq: number, overrides: Record<string, unknown> = {}): JournalEnvelope => ({
  journal_seq: seq,
  event_type: "biss.scramble_applied",
  payload: {
    pid_scope: [256],
    packet_count: 10,
    key_fingerprint: "sha256:fp1",
    mutation_log_ref: "ml-1",
    mode: "1",
    ...overrides,
  },
});

const bissDescrambleFailed = (seq: number, overrides: Record<string, unknown> = {}): JournalEnvelope => ({
  journal_seq: seq,
  event_type: "biss.descramble_failed",
  payload: {
    pid_scope: [256],
    failed_indices_sample: [3],
    self_check_kind: "structure_probe",
    key_fingerprint_ref: "sha256:fp1",
    mode: "E",
    ...overrides,
  },
});

describe("deriveBissEvidence — journal facts → BissEvidenceAnnotation", () => {
  it("returns null on an empty journal (honest absence, no fabricated annotation)", () => {
    expect(deriveBissEvidence([])).toBeNull();
  });

  it("returns null when no biss.* event exists (other namespaces are not BISS evidence)", () => {
    const others: JournalEnvelope[] = [
      { journal_seq: 1, event_type: "ts.generated", payload: { sha256: "a".repeat(64) } },
      { journal_seq: 2, event_type: "gen.packet_sampled", payload: { layer: "BISS", packet_index: 0, byte_size: 1, sha256: "b".repeat(64) } },
    ];
    expect(deriveBissEvidence(others)).toBeNull();
  });

  it("derives mode/fingerprint/mutation-log from the newest scramble_applied verbatim", () => {
    const annotation = deriveBissEvidence([
      bissScramble(1, { key_fingerprint: "sha256:old", mutation_log_ref: "ml-0" }),
      bissScramble(5),
    ]);
    expect(annotation).toEqual({ mode: "1", key_fingerprint_ref: "sha256:fp1", mutation_log_ref: "ml-1" });
  });

  it("prefers the newest descramble_failed for mode/fingerprint; mutation log falls back to the newest scramble_applied", () => {
    const annotation = deriveBissEvidence([
      bissScramble(3),
      bissDescrambleFailed(7, { key_fingerprint_ref: "sha256:fp9", mode: "2" }),
    ]);
    expect(annotation).toEqual({ mode: "2", key_fingerprint_ref: "sha256:fp9", mutation_log_ref: "ml-1" });
  });

  it("omits mutation_log_ref when no scramble_applied ever carried one (undefined, not fabricated)", () => {
    const annotation = deriveBissEvidence([
      bissScramble(1, { mutation_log_ref: null }),
      bissDescrambleFailed(2),
    ]);
    expect(annotation).toEqual({ mode: "E", key_fingerprint_ref: "sha256:fp1" });
    expect(annotation?.mutation_log_ref).toBeUndefined();
  });

  it("skips malformed biss payloads honestly (shape guard, never a guess)", () => {
    const malformed: JournalEnvelope[] = [
      { journal_seq: 1, event_type: "biss.scramble_applied", payload: { packet_count: 1 } },
      { journal_seq: 2, event_type: "biss.descramble_failed", payload: { pid_scope: [1] } },
    ];
    expect(deriveBissEvidence(malformed)).toBeNull();
  });

  it("ignores journal_seq that is not a number (gateway stamps the order, facts only)", () => {
    const annotation = deriveBissEvidence([
      bissScramble(1),
      { ...bissDescrambleFailed(Number.MAX_SAFE_INTEGER), journal_seq: "not-a-seq" },
    ]);
    // The malformed-seq envelope is still a biss fact — seq ordering only
    // decides precedence among well-formed seqs; this shape asserts the
    // guard does not crash on it.
    expect(annotation).not.toBeNull();
  });
});
