// Minimal self-drawn UI kit (SPEC-400 §8.3 ruling R3: no heavyweight
// component library — the MVP surface is data display; ADR-0009's store
// discipline applies to any third-party component with an internal store).
import type { ReactNode } from "react";

export type BadgeTone = "neutral" | "good" | "warn" | "bad" | "info";

const TONE_CLASS: Record<BadgeTone, string> = {
  neutral: "dvb-badge-neutral",
  good: "dvb-badge-good",
  warn: "dvb-badge-warn",
  bad: "dvb-badge-bad",
  info: "dvb-badge-info",
};

export function Badge({ tone = "neutral", children }: { tone?: BadgeTone; children: ReactNode }) {
  return <span className={`dvb-badge ${TONE_CLASS[tone]}`}>{children}</span>;
}
