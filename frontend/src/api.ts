import { useEffect, useState } from "react";

// All data comes from the FastAPI backend (bmw_feedback/api.py); nothing is hard-coded here.

/** An API error with the backend's machine-readable code when it sends one (e.g. "llm_unavailable"). */
export class ApiError extends Error {
  constructor(message: string, public status: number, public code: string | null = null) {
    super(message);
  }
}

async function failure(res: Response): Promise<ApiError> {
  let message = `${res.status} ${res.statusText}`;
  let code: string | null = null;
  try {
    const j = await res.json();
    const d = j.detail;
    if (typeof d === "string") message = d;
    else if (d && typeof d === "object" && !Array.isArray(d)) {
      message = d.message ?? JSON.stringify(d);
      code = d.code ?? null;
    } else if (Array.isArray(d)) message = d.map((e: { loc?: unknown[]; msg?: string }) => `${(e.loc ?? []).join(".")}: ${e.msg}`).join("; ");
  } catch {
    /* keep the status text */
  }
  return new ApiError(message, res.status, code);
}

export async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(path);
  if (!res.ok) throw await failure(res);
  return res.json() as Promise<T>;
}

export async function postJSON<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!res.ok) throw await failure(res);
  return res.json() as Promise<T>;
}

export function useApi<T>(path: string | null) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(Boolean(path));
  useEffect(() => {
    if (!path) return;
    let live = true;
    setLoading(true);
    setError(null);
    getJSON<T>(path)
      .then((d) => live && setData(d))
      .catch((e: Error) => live && setError(e.message))
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
  }, [path]);
  return { data, error, loading };
}

export const fmtInt = (v: number | null | undefined) => (v === null || v === undefined ? "–" : Math.round(v).toLocaleString("en-GB"));
export const fmtNum = (v: number | null | undefined, d = 2) => (v === null || v === undefined || Number.isNaN(v) ? "–" : v.toFixed(d));
export const fmtEur = (v: number | null | undefined) => (v === null || v === undefined ? "–" : `EUR ${Math.round(v).toLocaleString("en-GB")}`);
export const fmtPct = (v: number | null | undefined, d = 0) => (v === null || v === undefined ? "–" : `${(v * 100).toFixed(d)}%`);

export const MODEL_NAMES: Record<string, string> = { F70: "1 Series", G60: "5 Series", G70: "7 Series" };
export const SERIES_LABELS: Record<string, string> = { F70: "1 Series (F70)", G60: "5 Series (G60)", G70: "7 Series (G70)" };
export const MARKET_NAMES: Record<string, string> = { EU: "Europe", US: "United States", CN: "China", RoW: "Rest of world" };
export const MOVE_LABELS: Record<string, string> = {
  fix_existing: "Fix or improve what exists",
  make_standard: "Make it standard equipment",
  new_option: "Offer it as a new option",
  price_change: "Change the price",
  introduce_on_series: "Introduce it on another series",
  unspecified: "Not specified",
};
