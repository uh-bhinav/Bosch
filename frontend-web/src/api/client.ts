/**
 * The one HTTP boundary. No component may call `fetch` directly (F1 spec,
 * "API CLIENT") -- every backend call, now and in every later phase, goes
 * through `apiGet`/`apiPost`/`apiUpload` here so the request/error shape
 * stays uniform as endpoints.ts grows.
 *
 * Base path: in dev, `/api` is proxied to the real backend by Vite
 * (vite.config.ts `server.proxy`) so the browser never makes a cross-origin
 * request and backend/api/main.py needs no CORS middleware added for F1. In
 * a production build, set `VITE_BACKEND_URL` to the real backend origin at
 * build time; requests then go directly there.
 */

const DEV_PROXY_BASE = '/api';
const BACKEND_URL = import.meta.env.VITE_BACKEND_URL as string | undefined;

export const API_BASE = BACKEND_URL && BACKEND_URL.length > 0 ? BACKEND_URL : DEV_PROXY_BASE;

/**
 * Matches `_error_detail()` in backend/api/main.py -- every structured
 * error response body's `error` field.
 */
export interface BackendErrorDetail {
  code: string;
  message: string;
  operation: string;
  recovery_hint: string;
  details: Record<string, unknown>;
}

export class ApiError extends Error {
  readonly status: number;
  readonly endpoint: string;
  /** Populated whenever the backend returned its structured `{status, error}` body. */
  readonly detail: BackendErrorDetail | null;

  constructor(message: string, status: number, endpoint: string, detail: BackendErrorDetail | null = null) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.endpoint = endpoint;
    this.detail = detail;
  }
}

async function toApiError(response: Response, path: string): Promise<ApiError> {
  try {
    const body = (await response.clone().json()) as { error?: BackendErrorDetail };
    if (body?.error?.message) {
      return new ApiError(body.error.message, response.status, path, body.error);
    }
  } catch {
    // Non-JSON or unstructured error body -- fall through to the generic message.
  }
  return new ApiError(`HTTP ${response.status} from ${path}`, response.status, path);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const url = `${API_BASE}${path}`;
  let response: Response;
  try {
    response = await fetch(url, init);
  } catch {
    throw new ApiError(`Could not reach the backend at ${url}. Is it running?`, 0, path);
  }
  if (!response.ok) {
    throw await toApiError(response, path);
  }
  return (await response.json()) as T;
}

function toQueryString(params?: Record<string, string | number | boolean>): string {
  return params
    ? '?' + new URLSearchParams(Object.entries(params).map(([k, v]) => [k, String(v)])).toString()
    : '';
}

export function apiGet<T>(path: string, params?: Record<string, string | number | boolean>): Promise<T> {
  return request<T>(`${path}${toQueryString(params)}`, { method: 'GET' });
}

export function apiPost<T>(path: string, params?: Record<string, string | number | boolean>): Promise<T> {
  return request<T>(`${path}${toQueryString(params)}`, { method: 'POST' });
}

/** Multipart POST -- the one exception to "every request is query params only" (file uploads). */
export function apiUpload<T>(path: string, formData: FormData): Promise<T> {
  return request<T>(path, { method: 'POST', body: formData });
}

/**
 * F6: POST that returns a binary body (`application/pdf`), not JSON --
 * `/export/report`'s own response shape. Structured JSON errors (the
 * backend's `{status, error}` body) are still parsed and surfaced via
 * `ApiError` exactly like every other call; only a genuinely successful
 * response is read as a `Blob`.
 */
export async function apiPostBinary(path: string, params?: Record<string, string | number | boolean>): Promise<Blob> {
  const url = `${API_BASE}${path}${toQueryString(params)}`;
  let response: Response;
  try {
    response = await fetch(url, { method: 'POST' });
  } catch {
    throw new ApiError(`Could not reach the backend at ${url}. Is it running?`, 0, path);
  }
  if (!response.ok) {
    throw await toApiError(response, path);
  }
  return response.blob();
}
