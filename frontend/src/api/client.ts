const BASE: string = import.meta.env.VITE_API_BASE ?? "";
const TOKEN_KEY = "fraud-desk-token";

export const session = {
  get: () => sessionStorage.getItem(TOKEN_KEY),
  set: (t: string) => sessionStorage.setItem(TOKEN_KEY, t),
  clear: () => sessionStorage.removeItem(TOKEN_KEY),
};

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public details: { field: string; message: string }[] = []) {
    super(message);
  }
}

type Params = Record<string, string | number | boolean | undefined | null>;

export function qs(params: Params = {}): string {
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") u.set(k, String(v));
  const s = u.toString();
  return s ? `?${s}` : "";
}

async function raw(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  const token = session.get();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body) headers.set("Content-Type", "application/json");
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, { ...init, headers });
  } catch {
    throw new ApiError(0, "network_error", "Cannot reach the server. Check that the API is running.");
  }
  if (!res.ok) {
    let body: unknown = null;
    try { body = await res.json(); } catch { /* non-JSON error body */ }
    const err = (body as { error?: { code?: string; message?: string; details?: { field: string; message: string }[] } } | null)?.error;
    if (res.status === 401 && token) { session.clear(); window.dispatchEvent(new Event("auth-expired")); }
    throw new ApiError(res.status, err?.code ?? "http_error", err?.message ?? `Request failed (${res.status})`, err?.details ?? []);
  }
  return res;
}

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await raw(path, init);
  try { return (await res.json()) as T; } catch { throw new ApiError(res.status, "bad_response", "The server sent a response the app could not read."); }
}

export const api = {
  get: <T>(path: string, params?: Params) => json<T>(path + qs(params)),
  post: <T>(path: string, body?: unknown) => json<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) }),
  put: <T>(path: string, body: unknown) => json<T>(path, { method: "PUT", body: JSON.stringify(body) }),
  async download(path: string, params: Params, filename: string) {
    const res = await raw(path + qs(params));
    const url = URL.createObjectURL(await res.blob());
    const a = document.createElement("a");
    a.href = url; a.download = filename; a.click();
    URL.revokeObjectURL(url);
  },
};

export function fieldErrors(e: unknown): Record<string, string> {
  const out: Record<string, string> = {};
  if (e instanceof ApiError) for (const d of e.details) out[d.field] = d.message;
  return out;
}
