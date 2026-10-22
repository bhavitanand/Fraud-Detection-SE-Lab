import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "./api/client";

export function useAsync<T>(fn: () => Promise<T>, deps: unknown[]) {
  const [state, setState] = useState<{ data: T | null; error: ApiError | null; loading: boolean }>({ data: null, error: null, loading: true });
  const seq = useRef(0);
  const run = useCallback(() => {
    const id = ++seq.current;
    setState((s) => ({ ...s, loading: true, error: null }));
    fn().then(
      (data) => { if (id === seq.current) setState({ data, error: null, loading: false }); },
      (e: unknown) => { if (id === seq.current) setState((s) => ({ data: s.data, loading: false, error: e instanceof ApiError ? e : new ApiError(0, "unknown", String(e)) })); },
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  useEffect(run, [run]);
  return { ...state, reload: run };
}

export const fmtMoney = (n: number, currency = "INR") =>
  new Intl.NumberFormat(currency === "INR" ? "en-IN" : "en-US", { style: "currency", currency, maximumFractionDigits: currency === "INR" && Number.isInteger(n) ? 0 : 2 }).format(n);
export const fmtPct = (n: number | null | undefined) => (n === null || n === undefined ? "n/a" : `${(n * 100).toFixed(1)}%`);
export function fmtTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString(undefined, { year: "numeric", month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}
export const label = (s: string) => s.replace(/_/g, " ").toLowerCase().replace(/^\w/, (c) => c.toUpperCase());
export const errMsg = (e: unknown) => (e instanceof ApiError ? e.message : "Something went wrong.");
