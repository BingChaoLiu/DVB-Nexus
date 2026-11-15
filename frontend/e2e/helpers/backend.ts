// REST driver helpers for the eight-step closed loop (SPEC-400 §7.3). The
// step map mirrors the #58 API-level harness verbatim (tests/e2e/_fault_lab.py
// header): Create → Generate → Inject → Analyze → Diagnose → Inspect →
// Recover → Verify. Wire shapes follow SPEC-500 §4 and the golden geometry
// (tests/_support/fault_lab_materials.py GOLDEN_GEOMETRY — the #58 frozen
// pull-safe config) and the cc-discontinuity fault plan (the SPEC-506
// registered fixture).
import type { APIRequestContext, Page } from "@playwright/test";

export interface SessionIds {
  sessionId: string;
}

const SESSION_BODY = {
  topology_id: "topo-1",
  topology_revision: 1,
  seed: 1234567,
  deterministic: true,
  clock_config: {
    mode: "deterministic",
    start_time_ns: 0,
    speed_num: 1,
    speed_den: 1,
    tick_quantum_ns: 1000000,
  },
};

// The frozen golden geometry as the SPEC-108 §4 wire body (two elementary
// streams; program_descriptors is the hex string — empty here).
export const GOLDEN_RUN_CONFIG = {
  schema_version: 1,
  profile: "analysis_only",
  deterministic: true,
  seed: 1234567,
  initial_media_clock_27mhz: 0,
  target_bitrate_bps: 3008000,
  output_packet_count: 600,
  program: {
    transport_stream_id: 1,
    program_number: 1,
    pmt_pid: 4096,
    pcr_pid: 256,
    version_number: 0,
    program_descriptors: "",
    streams: [
      {
        pid: 256,
        stream_type: 27,
        stream_id: 224,
        bitrate_bps: 120320,
        payload_profile: "synthetic_test_data",
        payload_seed_offset: 0,
      },
      {
        pid: 257,
        stream_type: 3,
        stream_id: 192,
        bitrate_bps: 60160,
        payload_profile: "synthetic_test_data",
        payload_seed_offset: 1,
      },
    ],
  },
  pat_period_ms: 101,
  pmt_period_ms: 103,
  pcr_interval_ms: 40,
  pcr_insertion_policy: "payload_packet_first",
};

// The fault-lab-cc-discontinuity single-fault plan (SPEC-506 fixture).
export const CC_DISCONTINUITY_FAULT_PLAN = [
  {
    fault_id: "fd000000-0000-4000-8000-00000000f103",
    fault_type: "CC_DISCONTINUITY",
    target_id: "mux-0:pid:0x0100",
    parameters: { delta: 3 },
    activation: { kind: "packet_index", packet_index: 30 },
    expected_observations: ["ts.continuity_error"],
  },
];

async function postJson(request: APIRequestContext, path: string, body?: unknown) {
  const response = await request.post(path, body === undefined ? undefined : { data: body });
  const text = await response.text();
  const json = text ? JSON.parse(text) : null;
  return { status: response.status(), json };
}

async function getJson(request: APIRequestContext, path: string) {
  const response = await request.get(path);
  const text = await response.text();
  const json = text ? JSON.parse(text) : null;
  return { status: response.status(), json };
}

export async function createStartedSession(request: APIRequestContext): Promise<string> {
  const created = await postJson(request, "/api/v1/sessions", SESSION_BODY);
  if (created.status !== 201) throw new Error(`create session failed: ${created.status} ${JSON.stringify(created.json)}`);
  const sessionId = created.json.session_id as string;

  const validated = await postJson(request, `/api/v1/sessions/${sessionId}/validate`);
  if (validated.status !== 200 || validated.json.ok !== true) {
    throw new Error(`validate failed: ${validated.status} ${JSON.stringify(validated.json)}`);
  }
  const started = await postJson(request, `/api/v1/sessions/${sessionId}/start`);
  if (started.status !== 200 || started.json.lifecycle !== "running") {
    throw new Error(`start failed: ${started.status} ${JSON.stringify(started.json)}`);
  }
  return sessionId;
}

export interface RunHandle {
  runId: string;
  status: string;
  artifacts: { artifact_id: string; kind: string; byte_size?: number; packet_count?: number }[];
}

async function pollRun(request: APIRequestContext, sessionId: string, runId: string): Promise<RunHandle> {
  const deadline = Date.now() + 30_000;
  while (Date.now() < deadline) {
    const view = await getJson(request, `/api/v1/sessions/${sessionId}/runs/${runId}`);
    if (view.status !== 200) throw new Error(`run poll failed: ${view.status} ${JSON.stringify(view.json)}`);
    if (view.json.status !== "running") {
      if (view.json.status !== "completed") {
        throw new Error(`run reached ${view.json.status}: ${JSON.stringify(view.json)}`);
      }
      const wire = view.json as { run_id: string; status: string; artifacts: RunHandle["artifacts"] };
      // Wire is snake_case (SPEC-500 DTO) — map explicitly so a silent
      // undefined can never reach a URL again.
      return { runId: wire.run_id, status: wire.status, artifacts: wire.artifacts ?? [] };
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`run ${runId} never completed within 30s`);
}

export async function submitAndAwaitRun(
  request: APIRequestContext,
  sessionId: string,
  faultPlan: unknown[],
): Promise<RunHandle> {
  const accepted = await postJson(request, `/api/v1/sessions/${sessionId}/runs`, {
    config: GOLDEN_RUN_CONFIG,
    fault_plan: faultPlan,
  });
  if (accepted.status !== 202) {
    throw new Error(`run submit failed: ${accepted.status} ${JSON.stringify(accepted.json)}`);
  }
  return pollRun(request, sessionId, accepted.json.run_id as string);
}

export async function queryEvents(
  request: APIRequestContext,
  sessionId: string,
  params: Record<string, string | number> = {},
) {
  const search = new URLSearchParams(Object.entries(params).map(([k, v]) => [k, String(v)]));
  return getJson(request, `/api/v1/sessions/${sessionId}/events?${search.toString()}`);
}

export async function diagnoseRun(request: APIRequestContext, sessionId: string, runId: string) {
  // The report becomes answerable once the pump has committed the run's
  // terminal events into the journal (404 = run observations not yet
  // committed). The endpoint is idempotent (SPEC-306 §5) — retry on 404
  // within a bound instead of sleeping a fixed wall clock.
  const deadline = Date.now() + 10_000;
  let last = await postJson(request, `/api/v1/sessions/${sessionId}/runs/${runId}/diagnose`);
  while (last.status === 404 && Date.now() < deadline) {
    await new Promise((resolve) => setTimeout(resolve, 50));
    last = await postJson(request, `/api/v1/sessions/${sessionId}/runs/${runId}/diagnose`);
  }
  return last;
}

export async function verifyRun(
  request: APIRequestContext,
  sessionId: string,
  runId: string,
  baselineRunId: string,
  faultPlan: unknown[],
) {
  const faultId = (faultPlan[0] as { fault_id: string }).fault_id;
  return postJson(request, `/api/v1/sessions/${sessionId}/runs/${runId}/verify`, {
    baseline_run_id: baselineRunId,
    scenario: {
      scenario_id: "cc-discontinuity-lab",
      version: "1.0.0",
      content_hash: "e2e-smoke",
    },
    pass_criteria: [{ criterion_id: "cc-ok", kind: "cc_continuous", mandatory: true, fault_id: faultId }],
  });
}

/** Artifact content via Range (single packet, 188 bytes — SPEC-100 §3). */
export async function fetchPacket(request: APIRequestContext, artifactId: string, packetIndex: number) {
  const start = 188 * packetIndex;
  const response = await request.get(`/api/v1/artifacts/${artifactId}/content`, {
    headers: { Range: `bytes=${start}-${start + 187}` },
  });
  return response;
}

/** Open a session WebSocket through the same-origin proxy and await the
 * first server frame (ready after subscribe — SPEC-501 §4). */
export async function subscribeAndWaitReady(page: Page, sessionId: string) {
  return page.evaluate(async (sid) => {
    return await new Promise<{ type: string; replayed_from?: number }>((resolve, reject) => {
      const socket = new WebSocket(`ws://${location.host}/ws/v1/sessions/${sid}`);
      let open = false;
      const timer = setTimeout(() => {
        socket.close();
        reject(new Error("no ready frame within 5s"));
      }, 5000);
      socket.onmessage = (ev) => {
        clearTimeout(timer);
        resolve(JSON.parse(ev.data as string));
        socket.close();
      };
      socket.onclose = (ev) => {
        clearTimeout(timer);
        reject(new Error(`ws closed before ready: code=${ev.code} reason=${ev.reason || "<none>"} (opened=${open})`));
      };
      socket.onerror = () => {
        // the close event carries the code; wait for it
        void open;
      };
      socket.onopen = () => {
        open = true;
        socket.send(JSON.stringify({ type: "subscribe", session_id: sid }));
      };
    });
  }, sessionId);
}
