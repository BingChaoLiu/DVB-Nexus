// SPEC-404 §4.3/§7.3/§7.4 — drill-down data hook (metadata-first, explicit
// branch machine). Seam: the src/api barrel only (getArtifactMeta /
// getArtifactContent / packetRange — no ad-hoc fetch, #61 contract). Artifact
// bytes are immutable → staleTime Infinity, no invalidation obligation; the
// query keys are component-local by design (plan-65.md D4: canonical
// keys.ts untouched).
//
// SPEC-404 §Phase2 (#132): the `view` param is additive. `ts` (default)
// keeps the EXACT MVP branch machine below (zero regression); `t2mi` /
// `bbframe` fetch the layered structure JSON instead (getArtifactStructure —
// the json_map chain wire; no meta/188 gate — layered artifacts honestly
// carry packet_size null) and land in the explicit structure-* states.
import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import {
  type ApiError,
  type ArtifactContentResult,
  type BBFrameStructureViewDTO,
  getArtifactContent,
  getArtifactMeta,
  getArtifactStructure,
  isApiError,
  packetRange,
  type T2miStructureViewDTO,
} from "../../../api";
import type { DiagnosisEvidenceDTO } from "../types";
import { type HexRow, parseTsPacket, type TsPacketView, toHexDump, TS_PACKET_SIZE } from "./decode";
import type { PacketInspectorView } from "./viewTypes";

export interface DrillDownError {
  source: "meta" | "content";
  status: number;
  errorCode: string;
  message: string;
}

/** The layered views' error face (structure fetch; SPEC-404 §8 explicit). */
export interface StructureErrorState {
  view: "t2mi" | "bbframe";
  status: number;
  errorCode: string;
  message: string;
}

export type PacketDrillDownState =
  | { phase: "idle" }
  | { phase: "loading-meta" }
  | { phase: "loading-content" }
  /** Meta gate §7.3 row 1: declared packet geometry is not 188. */
  | { phase: "meta-invalid"; packetSize: number | null }
  /** Meta gate §7.3 row 2: index beyond packet_count (416 pre-branch). */
  | { phase: "out-of-range"; packetIndex: number; packetCount: number }
  /** §7.3 row 6: 206 arrived but the body is not a full packet. */
  | { phase: "truncated"; byteCount: number; contentRange: string | null }
  /** §7.3 rows 4/5/7 + unexpected status — always explicit, never success. */
  | { phase: "error"; source: "meta" | "content"; status: number; errorCode: string; message: string }
  | {
      phase: "ready";
      view: TsPacketView;
      hexRows: HexRow[];
      byteCount: number;
      contentRange: string | null;
      acceptRanges: string | null;
    }
  // --- SPEC-404 §Phase2 layered structure faces (#132) ---------------------
  | { phase: "structure-loading"; view: "t2mi" | "bbframe" }
  | ({ phase: "structure-error" } & StructureErrorState)
  | { phase: "structure-ready"; view: "t2mi"; structure: T2miStructureViewDTO }
  | { phase: "structure-ready"; view: "bbframe"; structure: BBFrameStructureViewDTO };

const GATE_STALE_MS = Number.POSITIVE_INFINITY;

function toErrorState(source: "meta" | "content", error: unknown): PacketDrillDownState {
  if (isApiError(error)) {
    const apiError = error as ApiError;
    return {
      phase: "error",
      source,
      status: apiError.status,
      errorCode: apiError.errorCode,
      message: apiError.message,
    };
  }
  return {
    phase: "error",
    source,
    status: 0,
    errorCode: "UNKNOWN",
    message: error instanceof Error ? error.message : String(error),
  };
}

function toStructureErrorState(view: "t2mi" | "bbframe", error: unknown): PacketDrillDownState {
  if (isApiError(error)) {
    const apiError = error as ApiError;
    return {
      phase: "structure-error",
      view,
      status: apiError.status,
      errorCode: apiError.errorCode,
      message: apiError.message,
    };
  }
  return {
    phase: "structure-error",
    view,
    status: 0,
    errorCode: "UNKNOWN",
    message: error instanceof Error ? error.message : String(error),
  };
}

export function usePacketDrillDown(
  locator: DiagnosisEvidenceDTO | null,
  view: PacketInspectorView = "ts",
): PacketDrillDownState {
  const structureView = view === "t2mi" || view === "bbframe" ? view : null;

  const structureQuery = useQuery({
    queryKey: ["packet-inspector", locator === null ? null : locator.artifact_id, "structure", structureView],
    queryFn: () => getArtifactStructure(locator!.artifact_id, { view: structureView! }),
    enabled: locator !== null && structureView !== null,
    staleTime: GATE_STALE_MS,
    retry: false,
  });

  const metaQuery = useQuery({
    queryKey: ["packet-inspector", locator === null ? null : locator.artifact_id, "meta"],
    queryFn: () => getArtifactMeta(locator!.artifact_id),
    // Layered views skip the meta/Range face entirely (SPEC-404 §Phase2: the
    // structure JSON is the data source; layered artifacts have no 188
    // packet geometry — packet_size is honestly null there).
    enabled: locator !== null && structureView === null,
    staleTime: GATE_STALE_MS,
    retry: false,
  });

  const meta = metaQuery.data;
  // §7.3 row 1: only gate when the server declared a packet_size at all.
  const metaGateOk =
    meta === undefined ||
    meta.packet_size === undefined ||
    meta.packet_size === null ||
    meta.packet_size === TS_PACKET_SIZE;
  // §7.3 row 2: only pre-judge when packet_count is known; the wire stays
  // authoritative — a real 416 still lands in the error branch (§8).
  const inRange =
    meta === undefined ||
    meta.packet_count === undefined ||
    meta.packet_count === null ||
    (locator !== null && locator.packet_index < meta.packet_count);

  const contentQuery = useQuery({
    queryKey: ["packet-inspector", locator === null ? null : locator.artifact_id, locator === null ? null : locator.packet_index],
    queryFn: (): Promise<ArtifactContentResult> =>
      getArtifactContent(locator!.artifact_id, { range: packetRange(locator!.packet_index) }),
    // Metadata-first is a hard ordering (§4.3): the Range request must not
    // race the meta request — it waits for meta to arrive AND pass both gates.
    enabled: locator !== null && structureView === null && meta !== undefined && metaGateOk && inRange,
    staleTime: GATE_STALE_MS,
    retry: false,
  });

  return useMemo(() => {
    if (locator === null) return { phase: "idle" } as const;
    if (structureView !== null) {
      if (structureQuery.isError) return toStructureErrorState(structureView, structureQuery.error);
      const structure = structureQuery.data;
      if (structure === undefined) return { phase: "structure-loading", view: structureView } as const;
      if (structureView === "t2mi" && structure.view === "t2mi") {
        return { phase: "structure-ready", view: "t2mi", structure } as const;
      }
      if (structureView === "bbframe" && structure.view === "bbframe") {
        return { phase: "structure-ready", view: "bbframe", structure } as const;
      }
      // Wire/view mismatch — the discriminated union guards never fired:
      // explicit error, never a fabricated view (SPEC-404 §8).
      return {
        phase: "structure-error",
        view: structureView,
        status: 0,
        errorCode: "STRUCTURE_VIEW_MISMATCH",
        message: `requested view=${structureView}, wire answered view=${structure.view}`,
      } as const;
    }
    if (metaQuery.isError) return toErrorState("meta", metaQuery.error);
    if (meta === undefined) return { phase: "loading-meta" } as const;
    if (!metaGateOk) {
      return {
        phase: "meta-invalid",
        packetSize: meta.packet_size ?? null,
      } as const;
    }
    if (!inRange) {
      return {
        phase: "out-of-range",
        packetIndex: locator.packet_index,
        packetCount: meta.packet_count as number,
      } as const;
    }
    if (contentQuery.isError) return toErrorState("content", contentQuery.error);
    const content = contentQuery.data;
    if (content === undefined) return { phase: "loading-content" } as const;
    if (content.status === 206 && content.bytes.length === TS_PACKET_SIZE) {
      return {
        phase: "ready",
        view: parseTsPacket(content.bytes),
        hexRows: toHexDump(content.bytes),
        byteCount: content.bytes.length,
        contentRange: content.contentRange,
        acceptRanges: content.acceptRanges,
      } as const;
    }
    if (content.status === 206) {
      // §7.3 row 6 — a short body must never decode as a packet.
      return {
        phase: "truncated",
        byteCount: content.bytes.length,
        contentRange: content.contentRange,
      } as const;
    }
    return {
      phase: "error",
      source: "content",
      status: content.status,
      errorCode: "UNEXPECTED_STATUS",
      message: `expected 206 for the single-packet range, got ${content.status}`,
    } as const;
  }, [locator, structureView, structureQuery.isError, structureQuery.error, structureQuery.data, metaQuery.isError, metaQuery.error, meta, metaGateOk, inRange, contentQuery.isError, contentQuery.error, contentQuery.data]);
}
