// REST client core (SPEC-400 §4.1/§8): one openapi-fetch instance over the
// generated SPEC-500 types, plus the unified error-envelope parsing. Every
// non-2xx becomes an ApiError carrying the envelope's exact keys — pages
// branch on error_code (404/409/422 details.errors[]/416/501/503), never on
// ad-hoc body sniffing.
import createClient from "openapi-fetch";
import { apiBaseUrl } from "../lib/env";
import type { components, paths } from "./schema.gen";

export const client = createClient<paths>({ baseUrl: apiBaseUrl() });

export class ApiError extends Error {
  readonly status: number;
  readonly errorCode: string;
  readonly retryable: boolean;
  readonly details: Record<string, unknown>;
  readonly requestId: string | null;

  constructor(init: {
    status: number;
    errorCode: string;
    message: string;
    retryable?: boolean;
    details?: Record<string, unknown>;
    requestId?: string | null;
  }) {
    super(init.message);
    this.name = "ApiError";
    this.status = init.status;
    this.errorCode = init.errorCode;
    this.retryable = init.retryable ?? false;
    this.details = init.details ?? {};
    this.requestId = init.requestId ?? null;
  }
}

export function isApiError(value: unknown): value is ApiError {
  return value instanceof ApiError;
}

function asEnvelope(body: unknown): components["schemas"]["ErrorResponse"] | null {
  if (typeof body !== "object" || body === null || !("error" in body)) return null;
  const error = (body as { error: unknown }).error;
  if (typeof error !== "object" || error === null || !("error_code" in error)) return null;
  return body as components["schemas"]["ErrorResponse"];
}

// `preparsedBody`: openapi-fetch consumes the body of every non-ok response
// itself (coreFetch's error branch does response.text() → the body is used up
// and a re-read via response.json() always rejects, degrading every real-flow
// ApiError to the HTTP_<status> fallback with envelope keys lost). Callers
// holding the already-parsed error payload pass it here; the re-read runs only
// when no preparsed body was handed over (ticket #62, ruling I on #15).
export async function errorFromResponse(response: Response, preparsedBody?: unknown): Promise<ApiError> {
  let body: unknown = preparsedBody;
  if (body === undefined) {
    try {
      body = await response.json();
    } catch {
      // non-JSON body (proxy/infra pages) — fall through to HTTP_<status>
    }
  }
  const envelope = asEnvelope(body);
  if (envelope) {
    return new ApiError({
      status: response.status,
      errorCode: envelope.error.error_code,
      message: envelope.error.message,
      retryable: envelope.error.retryable,
      details: envelope.error.details,
      requestId: envelope.request_id,
    });
  }
  return new ApiError({
    status: response.status,
    errorCode: `HTTP_${response.status}`,
    message: `HTTP ${response.status}`,
  });
}

// openapi-fetch's result triple, narrowed to its data payload: since the
// companion ticket (#80) wired response models onto every route, TData
// infers straight from the generated path types — no call-site casts.
interface FetchResultLike<TData> {
  data?: TData;
  error?: unknown;
  response: Response;
}

export async function unwrap<TData>(promise: Promise<FetchResultLike<TData>>): Promise<TData> {
  const result = await promise;
  if (result.response.ok) return result.data as TData;
  // result.error is the body openapi-fetch already parsed for non-ok
  // responses — hand it over instead of re-reading the used-up body (#62/裁定 I).
  throw await errorFromResponse(result.response, result.error);
}
