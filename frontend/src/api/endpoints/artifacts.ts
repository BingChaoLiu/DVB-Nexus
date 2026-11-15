// Artifact face (SPEC-500 §4.4; Range semantics = SPEC-305-adjacent §2.4 of
// the M5 brief: single range only, 206 + Content-Range, 400 malformed,
// 416 unsatisfiable). The content call is raw fetch (octet-stream bytes, not
// a JSON DTO) — the /analyze route stays frozen 501 (M4 裁定 B) and is
// deliberately not wrapped.
import { apiBaseUrl } from "../../lib/env";
import { client, errorFromResponse, unwrap } from "../client";
import type { components } from "../schema.gen";

export type ArtifactMetaDTO = components["schemas"]["ArtifactMetaDTO"];

export interface ArtifactContentResult {
  status: number;
  bytes: Uint8Array;
  contentRange: string | null;
  acceptRanges: string | null;
}

export function getArtifactMeta(artifactId: string) {
  return unwrap<ArtifactMetaDTO>(
    client.GET("/api/v1/artifacts/{artifact_id}", {
      params: { path: { artifact_id: artifactId } },
    }),
  );
}

export async function getArtifactContent(
  artifactId: string,
  options: { range?: string } = {},
): Promise<ArtifactContentResult> {
  const url = `${apiBaseUrl()}/api/v1/artifacts/${encodeURIComponent(artifactId)}/content`;
  const headers: Record<string, string> = {};
  if (options.range !== undefined) headers.Range = options.range;
  // Authorized seam: openapi-fetch returns no byte body (octet-stream here),
  // so the api barrel owns this one raw fetch — SPEC-404 AC-404-6「禁自拼
  // fetch」binds feature code; this endpoint function is the授权缝.
  const response = await fetch(url, { headers });
  if (!response.ok) throw await errorFromResponse(response);
  const bytes = new Uint8Array(await response.arrayBuffer());
  return {
    status: response.status,
    bytes,
    contentRange: response.headers.get("Content-Range"),
    acceptRanges: response.headers.get("Accept-Ranges"),
  };
}

/** Single-packet Range header (188-byte packets; SPEC-100 §3). */
export function packetRange(packetIndex: number): string {
  const start = 188 * packetIndex;
  return `bytes=${start}-${start + 187}`;
}
