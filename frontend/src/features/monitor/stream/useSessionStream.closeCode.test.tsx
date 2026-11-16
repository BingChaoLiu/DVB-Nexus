// useSessionStream hook close-code surfacing (SPEC-408 §4.3 未知会话态,
// ticket #95): the page-level unknown-session state needs the WS close code
// — 4404 CLOSE_SESSION_UNKNOWN is the permanent session-unknown signal.
// The socket is injected (the hook's additive test seam); the live stream is
// the E2E suite's job on the real backend.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { FakeSocketHandle } from "../../../ws/testSupport";
import { useSessionStream } from "./useSessionStream";

let queryClient: QueryClient;
let handle: FakeSocketHandle;

beforeEach(() => {
  queryClient = new QueryClient();
  handle = new FakeSocketHandle("ws://test/ws/v1/sessions/s-1");
});

afterEach(() => {
  queryClient.clear();
});

function renderTrackedSession() {
  return renderHook(() => useSessionStream("s-1", { socketFactory: () => handle }), {
    wrapper: ({ children }) => <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>,
  });
}

describe("useSessionStream — close-code surfacing", () => {
  it("surfaces the 4404 close with status closed (mount effect subscribes synchronously)", () => {
    const { result } = renderTrackedSession();
    // The mount effect subscribes before the first assertion lands, so the
    // stream is already "connecting"; no close has been observed yet.
    expect(result.current.closeCode).toBeNull();

    // Server accepts then closes with the permanent session-unknown code.
    act(() => {
      handle.serverAccept();
      handle.serverClose(4404, "session unknown");
    });
    expect(result.current.status).toBe("closed");
    expect(result.current.closeCode).toBe(4404);
  });

  it("surfaces transient close codes too, but the stream keeps reconnecting (not unknown)", () => {
    const { result } = renderTrackedSession();
    act(() => {
      handle.serverAccept();
      handle.serverClose(1006, "abnormal");
    });
    expect(result.current.closeCode).toBe(1006);
    expect(result.current.status).toBe("reconnecting");
  });
});
