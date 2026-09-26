// Thin fetch wrapper for the AltCredit API. All scores, tiers, products and ML
// results shown in the UI come from these calls; nothing is computed client-side.

const TOKEN_KEY = "altcredit.session";

export interface Session {
  token: string;
  role: "user" | "lender" | "admin";
  username: string;
  user_id: string | null;
  lender_id: string | null;
  display_name: string;
}

export function loadSession(): Session | null {
  try {
    const raw = sessionStorage.getItem(TOKEN_KEY);
    return raw ? (JSON.parse(raw) as Session) : null;
  } catch {
    return null;
  }
}

export function saveSession(s: Session | null) {
  try {
    if (s) sessionStorage.setItem(TOKEN_KEY, JSON.stringify(s));
    else sessionStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable: session lives in memory only */
  }
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

function detail(body: unknown, fallback: string): string {
  if (body && typeof body === "object" && "detail" in body) {
    const d = (body as { detail: unknown }).detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d)) return d.map((x) => (x && typeof x === "object" && "msg" in x ? String((x as { msg: unknown }).msg) : String(x))).join("; ");
  }
  return fallback;
}

export async function api<T = unknown>(path: string, opts: { method?: string; body?: unknown; form?: FormData } = {}): Promise<T> {
  const s = loadSession();
  const headers: Record<string, string> = {};
  if (s) headers.Authorization = `Bearer ${s.token}`;
  let body: BodyInit | undefined;
  if (opts.form) body = opts.form;
  else if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.body);
  }
  const res = await fetch(path, { method: opts.method ?? (body ? "POST" : "GET"), headers, body });
  if (res.status === 401 && s) {
    saveSession(null);
    window.location.assign("/");
  }
  const type = res.headers.get("content-type") ?? "";
  const data = type.includes("application/json") ? await res.json() : await res.text();
  if (!res.ok) throw new ApiError(res.status, detail(data, `Request failed (${res.status})`));
  return data as T;
}

export async function download(path: string, filename: string) {
  const s = loadSession();
  const res = await fetch(path, { headers: s ? { Authorization: `Bearer ${s.token}` } : {} });
  if (!res.ok) throw new ApiError(res.status, `Download failed (${res.status})`);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}
