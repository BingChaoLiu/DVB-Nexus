// REST client core (SPEC-400 §4.1/§8): one openapi-fetch instance over the
// generated SPEC-500 types, plus the unified error-envelope parsing. Every
// non-2xx becomes an ApiError carrying the envelope's exact keys — pages
// branch on error_code (404/409/422 details.errors[]/416/501/503), never on
// ad-hoc body sniffing.
import createClient from "openapi-fetch";
import { apiBaseUrl } from "../lib/env";
import type { ErrorResponse } from "./dto-supplement";
import type { paths } from "./schema.gen";

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

function asEnvelope(body: unknown): ErrorResponse | null {
  if (typeof body !== "object" || body === null || !("error" in body)) return null;
  const error = (body as { error: unknown }).error;
  if (typeof error !== "object" || error === null || !("error_code" in error)) return null;
  return body as ErrorResponse;
}

export async function errorFromResponse(response: Response): Promise<ApiError> {
  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    // non-JSON body (proxy/infra pages) — fall through to HTTP_<status>
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

// openapi-fetch's result triple, loosened so supplement-typed casts happen at
// the call site (observation routes generate untyped bodies until the
// companion ticket wires their response models — SPEC-400 §7.1 convergence).
interface FetchResultLike {
  data?: unknown;
  error?: unknown;
  response: Response;
}

export async function unwrap<TData>(promise: Promise<FetchResultLike>): Promise<TData> {
  const result = await promise;
  if (result.response.ok) return result.data as TData;
  throw await errorFromResponse(result.response);
}
