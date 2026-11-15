// Node inspector driving helpers shared by the SPEC-401/402 E2E specs (the
// #63 accommodation: the save gate requires a complete generator config, so
// several specs fill the same 9-field minimal config through the inspector
// before saving — one shared seam instead of copied loops).
import type { Page } from "@playwright/test";

/** Fill every required field of a minimal generator config (defaults fill the
 * optional ones) and apply — the 配置待填 → gate-open transition. */
export async function fillMinimalGeneratorConfig(page: Page) {
  const required: [string, string][] = [
    ["seed", "20260101"],
    ["initial_media_clock_27mhz", "0"],
    ["target_bitrate_bps", "3008000"],
    ["output_packet_count", "1000"],
    ["program.transport_stream_id", "1"],
    ["program.program_number", "1"],
    ["program.pmt_pid", "4096"],
    ["program.pcr_pid", "256"],
    ["program.version_number", "0"],
  ];
  for (const [label, value] of required) {
    await page.getByLabel(label, { exact: true }).fill(value);
  }
  await page.getByRole("button", { name: "应用到草稿" }).click();
}
