// deriveJourneyLocation exhaustive table (SPEC-408 §7.1 / §11.2): seven areas,
// per-URL positive and negative examples. The function derives position from
// the URL ONLY (§4.1: no stepper facts, no cross-module state) — expected
// values below are the spec's own decision table, not recomputed logic.
import { describe, expect, it } from "vitest";
import { deriveJourneyLocation } from "./journeyLocation";

describe("deriveJourneyLocation — seven areas per SPEC-408 §7.1", () => {
  it("maps / to the journey start", () => {
    expect(deriveJourneyLocation("/", "")).toMatchObject({ area: "start" });
    expect(deriveJourneyLocation("/", "?anything=1")).toMatchObject({ area: "start" });
  });

  it("maps /lab without params to the Lab scenario library", () => {
    expect(deriveJourneyLocation("/lab", "")).toMatchObject({ area: "lab-library" });
    // Unrelated params do not promote the library view (scenario absent).
    expect(deriveJourneyLocation("/lab", "?other=1")).toMatchObject({ area: "lab-library" });
    // session alone (no scenario) stays in the library (spec table: scenario required first).
    expect(deriveJourneyLocation("/lab", "?session=abc")).toMatchObject({ area: "lab-library" });
  });

  it("maps /lab?scenario= without session to the scenario detail", () => {
    expect(deriveJourneyLocation("/lab", "?scenario=SC-01")).toMatchObject({ area: "lab-detail" });
    expect(deriveJourneyLocation("/lab", "?scenario=SC-01&other=1")).toMatchObject({
      area: "lab-detail",
    });
  });

  it("maps /lab?scenario=&session= to the experiment console", () => {
    expect(deriveJourneyLocation("/lab", "?scenario=SC-01&session=6f0a-…")).toMatchObject({
      area: "lab-console",
    });
    // Parameter EXISTENCE decides (prototype §7.1 verbatim), not non-empty value:
    // empty strings still count as present.
    expect(deriveJourneyLocation("/lab", "?scenario=&session=")).toMatchObject({
      area: "lab-console",
    });
    expect(deriveJourneyLocation("/lab", "?scenario=SC-01&session=")).toMatchObject({
      area: "lab-console",
    });
  });

  it("maps /monitor to Monitor with or without a session param", () => {
    expect(deriveJourneyLocation("/monitor", "")).toMatchObject({ area: "monitor" });
    expect(deriveJourneyLocation("/monitor", "?session=abc")).toMatchObject({ area: "monitor" });
  });

  it("maps /topologies to Topologies", () => {
    expect(deriveJourneyLocation("/topologies", "")).toMatchObject({ area: "topologies" });
  });

  it("maps every other path to the fallback area", () => {
    expect(deriveJourneyLocation("/nope", "")).toMatchObject({ area: "other" });
    expect(deriveJourneyLocation("/lab/extra", "")).toMatchObject({ area: "other" });
    expect(deriveJourneyLocation("/LAB", "")).toMatchObject({ area: "other" });
  });

  it("carries a 你在 label and a one-line next-step hint for every area", () => {
    for (const [pathname, search] of [
      ["/", ""],
      ["/lab", ""],
      ["/lab", "?scenario=SC-01"],
      ["/lab", "?scenario=SC-01&session=x"],
      ["/monitor", "?session=x"],
      ["/topologies", ""],
      ["/nope", ""],
    ] as const) {
      const location = deriveJourneyLocation(pathname, search);
      expect(location.label).toBeTruthy();
      expect(location.next).toBeTruthy();
    }
  });
});
