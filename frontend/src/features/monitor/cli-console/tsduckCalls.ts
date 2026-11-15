// Data face for the CLI console (SPEC-405 §4.2/§7.1). The SPEC-500 §4.8
// route IS the SPEC-308 §7 TSDuck call-record channel — every row it returns
// is tagged source=tsduck HERE, at the data-face boundary (channel→source is
// a property of the channel, never inferred from record content). Domain
// function shape mirrors src/api/endpoints/*: the shared typed client +
// unwrap from the api barrel, no hand-rolled fetch. (Promotion candidate to
// api/endpoints/tsduck.ts — registered in the #66 report; this file is the
// ticket-OWN holding face while src/api/** is NOT-TOUCH for #66.)
import { client, unwrap } from "../../../api";
import type { SourceTaggedCall } from "./sources";

export async function listTSDuckCalls(
  sessionId: string,
  runId?: string,
): Promise<SourceTaggedCall[]> {
  const calls = await unwrap(
    client.GET("/api/v1/sessions/{session_id}/tsduck/calls", {
      params: {
        path: { session_id: sessionId },
        ...(runId !== undefined ? { query: { run_id: runId } } : {}),
      },
    }),
  );
  return (calls ?? []).map((call) => ({ source: "tsduck", call }));
}
