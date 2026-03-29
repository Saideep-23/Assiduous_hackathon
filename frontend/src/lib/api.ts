/**
 * API base URL for browser fetches.
 *
 * - **Production** (`next start`, Docker): defaults to `/api` — Next.js rewrites proxy to FastAPI (see `next.config.js`).
 *   Set `BACKEND_INTERNAL_URL` on the Node process (e.g. `http://backend:8000` in Compose).
 * - **Development** (`next dev`): defaults to `http://127.0.0.1:8000` (direct to FastAPI).
 *
 * Overrides: `NEXT_PUBLIC_API_URL` (full origin) or `NEXT_PUBLIC_API_BASE` (path prefix e.g. `/api`).
 */

function resolveApiBase(): string {
  const url = process.env.NEXT_PUBLIC_API_URL?.trim();
  if (url) return url.replace(/\/$/, "");

  const basePath = process.env.NEXT_PUBLIC_API_BASE?.trim();
  if (basePath) return basePath.replace(/\/$/, "");

  if (process.env.NODE_ENV === "development") {
    return "http://127.0.0.1:8000";
  }
  return "/api";
}

export const API_BASE = resolveApiBase();

/** Absolute URL for an API path (e.g. `/financials/msft`). */
export function apiUrl(path: string): string {
  const p = path.startsWith("/") ? path : `/${path}`;
  const base = API_BASE.replace(/\/$/, "");
  return `${base}${p}`;
}

export async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const url = apiUrl(path);
  const res = await fetch(url, {
    ...init,
    headers: {
      Accept: "application/json",
      ...((init?.headers as Record<string, string>) || {}),
    },
  });
  const text = await res.text();
  if (!res.ok) {
    throw new Error(text ? `HTTP ${res.status}: ${text.slice(0, 400)}` : `HTTP ${res.status} ${res.statusText}`);
  }
  if (!text) return {} as T;
  try {
    return JSON.parse(text) as T;
  } catch {
    throw new Error(`Invalid JSON from ${url}`);
  }
}
