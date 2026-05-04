/**
 * Base fetch wrapper.
 *
 * Two modes (chosen automatically):
 *   1. `NEXT_PUBLIC_GATEWAY_URL` set → call gateway directly (browser → Caddy).
 *      Used in dev to bypass Next.js dev's internal rewrite proxy, which
 *      drops connections (`socket hang up` / `ECONNRESET`) on long-running
 *      LLM calls (campaign upload parse, graph build, sim prepare).
 *      Caddy has CORS allow for `http://localhost:5173`.
 *
 *   2. Env var unset → relative `/api/*` path. Next.js `rewrites` proxies
 *      server-side to `GATEWAY_UPSTREAM` (used in Docker). Same-origin in
 *      browser, no CORS preflight.
 *
 * Throws `ApiError` on non-2xx; returns parsed JSON on success.
 */

const GATEWAY_BASE =
  // Stripped of trailing slash so `${BASE}${path}` works when path begins with /
  (process.env.NEXT_PUBLIC_GATEWAY_URL || '').replace(/\/+$/, '')

export class ApiError extends Error {
  readonly status: number
  readonly body: string
  constructor(status: number, body: string, message?: string) {
    super(message || `HTTP ${status}`)
    this.name = 'ApiError'
    this.status = status
    this.body = body
  }
}

export interface ApiOptions extends Omit<RequestInit, 'body'> {
  body?: unknown
  /** If true, body is FormData / raw — do NOT JSON.stringify or set content-type. */
  raw?: boolean
}

export async function apiFetch<T>(
  path: string,
  opts: ApiOptions = {},
): Promise<T> {
  const { body, raw, headers, ...rest } = opts

  const init: RequestInit = {
    ...rest,
    headers: raw
      ? (headers as HeadersInit)
      : { 'Content-Type': 'application/json', ...(headers || {}) },
    body: raw
      ? (body as BodyInit)
      : body !== undefined
        ? JSON.stringify(body)
        : undefined,
  }

  // Resolve URL: absolute if NEXT_PUBLIC_GATEWAY_URL set, else relative.
  const url = GATEWAY_BASE && path.startsWith('/') ? GATEWAY_BASE + path : path

  let res: Response
  try {
    res = await fetch(url, init)
  } catch (e) {
    throw new ApiError(0, String(e), 'Network error')
  }

  const text = await res.text()
  if (!res.ok) {
    let msg = `HTTP ${res.status}`
    try {
      const parsed = JSON.parse(text)
      msg = parsed?.error || parsed?.message || msg
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, text, msg)
  }

  if (!text) return undefined as T
  try {
    return JSON.parse(text) as T
  } catch {
    return text as unknown as T
  }
}
