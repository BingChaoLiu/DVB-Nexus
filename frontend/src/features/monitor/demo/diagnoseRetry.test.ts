// Shared diagnose 404-until-drained retrier (review-fix F4 单一实现): the
// demo orchestration and the Monitor page's diagnose trigger consumed two
// byte-identical inline loops; the extraction keeps ONE implementation. The
// seam is the wrapper's timing contract only — diagnoseRun stays the sole
// authority call, the wrapper adds timing and nothing else.
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../api")>();
  return {
    ...actual,
    diagnoseRun: vi.fn(),
  };
});

import { diagnoseRun, type DiagnosisReportDTO } from "../../../api";
import { ApiError } from "../../../api/client";
import {
  DIAGNOSE_404_RETRY_INTERVAL_MS,
  DIAGNOSE_404_RETRY_WINDOW_MS,
  diagnoseWith404Retry,
} from "./diagnoseRetry";

const diagnoseRunMock = vi.mocked(diagnoseRun);

const SESSION = "aa990000-0000-4000-8000-000000009901";
const RUN = "run-inject";

function report(): DiagnosisReportDTO {
  return { session_id: SESSION, run_id: RUN, evaluated_at_utc_ms: 1, candidates: [], warnings: [] };
}

const notYet = () => new ApiError({ status: 404, errorCode: "SIM_NO_DIAGNOSIS", message: "not drained yet" });

beforeEach(() => {
  vi.clearAllMocks();
});

describe("diagnoseWith404Retry — the 404-until-drained window (one shared implementation)", () => {
  it("retries a fresh 404 inside the window and lands the report", async () => {
    diagnoseRunMock.mockRejectedValueOnce(notYet()).mockResolvedValueOnce(report());

    const answer = await diagnoseWith404Retry(SESSION, RUN);

    expect(answer.run_id).toBe(RUN);
    expect(diagnoseRunMock).toHaveBeenCalledTimes(2);
    expect(diagnoseRunMock).toHaveBeenCalledWith(SESSION, RUN);
  });

  it("a non-404 failure surfaces immediately (no retry)", async () => {
    diagnoseRunMock
      .mockRejectedValueOnce(notYet())
      .mockRejectedValueOnce(new ApiError({ status: 503, errorCode: "SIM_BACKEND_UNAVAILABLE", message: "down" }));

    await expect(diagnoseWith404Retry(SESSION, RUN)).rejects.toThrow(/SIM_BACKEND_UNAVAILABLE|down/);
    expect(diagnoseRunMock).toHaveBeenCalledTimes(2);
  });

  it("404s past the window surface instead of looping forever", async () => {
    vi.useFakeTimers();
    try {
      diagnoseRunMock.mockRejectedValue(notYet());
      const settled = expect(diagnoseWith404Retry(SESSION, RUN)).rejects.toThrow(/not drained yet/);
      // Walk past the 10 s window in 100 ms strides — the loop must give up.
      await vi.advanceTimersByTimeAsync(DIAGNOSE_404_RETRY_WINDOW_MS + DIAGNOSE_404_RETRY_INTERVAL_MS * 2);
      await settled;
      expect(diagnoseRunMock.mock.calls.length).toBeGreaterThan(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it("pins the #99 pacing constants (10 s window / 100 ms stride)", () => {
    expect(DIAGNOSE_404_RETRY_WINDOW_MS).toBe(10_000);
    expect(DIAGNOSE_404_RETRY_INTERVAL_MS).toBe(100);
  });
});
