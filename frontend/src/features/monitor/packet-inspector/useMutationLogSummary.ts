// SPEC-404 §Phase2 — the mutation-log summary face (#132; SPEC-304 §Phase2
// data-source contract: 结构 JSON + mutation log 摘要). The log is a LOG-kind
// artifact addressable by id (the `biss.*` `mutation_log_ref` binding);
// bytes are immutable → staleTime Infinity. Parsing is defensive: any shape
// mismatch renders the honest unknown face instead of fabricating fields.
// Key material never appears in mutation logs (SPEC-610 §9 — fingerprint
// only), so a key-name summary is leak-safe by construction.
import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { getArtifactContent, isApiError, type ApiError } from "../../../api";

export interface MutationLogSummary {
  log_kind: string | null;
  run_id: string | null;
  /** Layered wrapper face (#128): the layer names. */
  layers: string[] | null;
  /** Layered wrapper: per-layer §8.2 record counts (mutations length). */
  layer_record_counts: { layer: string; records: number }[] | null;
  /** Plain §8.2 document face: faults/mutations record counts. */
  fault_count: number | null;
  record_count: number | null;
}

export type MutationLogState =
  | { phase: "idle" }
  | { phase: "loading" }
  | { phase: "error"; status: number; errorCode: string; message: string }
  | { phase: "ready"; summary: MutationLogSummary };

function isRecordArray(value: unknown): value is Record<string, unknown>[] {
  return Array.isArray(value) && value.every((entry) => typeof entry === "object" && entry !== null);
}

function layerRecords(layerDoc: unknown): number | null {
  if (typeof layerDoc !== "object" || layerDoc === null) return null;
  const mutations = (layerDoc as Record<string, unknown>)["mutations"];
  return isRecordArray(mutations) ? mutations.length : null;
}

function summarize(bytes: Uint8Array): MutationLogSummary | null {
  try {
    const parsed: unknown = JSON.parse(new TextDecoder().decode(bytes));
    if (typeof parsed !== "object" || parsed === null) return null;
    const doc = parsed as Record<string, unknown>;
    const str = (key: string): string | null =>
      typeof doc[key] === "string" ? (doc[key] as string) : null;
    const summary: MutationLogSummary = {
      log_kind: str("log_kind") ?? str("schema"),
      run_id: str("run_id"),
      layers: null,
      layer_record_counts: null,
      fault_count: null,
      record_count: null,
    };
    const layerLogs = doc["layer_logs"];
    if (typeof layerLogs === "object" && layerLogs !== null) {
      const layers = Object.keys(layerLogs);
      summary.layers = layers;
      summary.layer_record_counts = layers.map((layer) => ({
        layer,
        records: layerRecords((layerLogs as Record<string, unknown>)[layer]) ?? 0,
      }));
    }
    const faults = doc["faults"];
    if (isRecordArray(faults)) summary.fault_count = faults.length;
    const mutations = doc["mutations"];
    if (isRecordArray(mutations)) summary.record_count = mutations.length;
    return summary;
  } catch {
    return null;
  }
}

export function useMutationLogSummary(artifactRef: string | null | undefined): MutationLogState {
  const query = useQuery({
    queryKey: ["packet-inspector", "mutation-log", artifactRef ?? null],
    queryFn: () => getArtifactContent(artifactRef!),
    enabled: typeof artifactRef === "string" && artifactRef !== "",
    staleTime: Number.POSITIVE_INFINITY,
    retry: false,
  });

  return useMemo(() => {
    if (artifactRef === null || artifactRef === undefined || artifactRef === "") {
      return { phase: "idle" } as const;
    }
    if (query.isError) {
      const error = query.error;
      if (isApiError(error)) {
        const apiError = error as ApiError;
        return { phase: "error", status: apiError.status, errorCode: apiError.errorCode, message: apiError.message };
      }
      return {
        phase: "error",
        status: 0,
        errorCode: "UNKNOWN",
        message: error instanceof Error ? error.message : String(error),
      };
    }
    if (query.data === undefined) return { phase: "loading" } as const;
    const summary = summarize(query.data.bytes);
    if (summary === null) {
      return {
        phase: "error",
        status: 0,
        errorCode: "MUTATION_LOG_UNPARSEABLE",
        message: "mutation log 字节不是可解析的 JSON 文档——诚实呈现，不伪造摘要",
      };
    }
    return { phase: "ready", summary } as const;
  }, [artifactRef, query.isError, query.error, query.data]);
}
