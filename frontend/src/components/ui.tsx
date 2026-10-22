import { Component, createContext, ReactNode, useCallback, useContext, useEffect, useRef, useState } from "react";
import type { Decision, Review, Source } from "../api/types";
import { label } from "../lib";

export function Badge({ tone, children }: { tone: "red" | "amber" | "green" | "gray" | "blue"; children: ReactNode }) {
  return <span className={`badge b-${tone}`}>{children}</span>;
}
export const DecisionBadge = ({ d }: { d: Decision }) => <Badge tone={d === "DECLINE" ? "red" : d === "HOLD" ? "amber" : "green"}>{d}</Badge>;
export const ReviewBadge = ({ r }: { r: Review }) => (
  <Badge tone={r === "OPEN" ? "amber" : r === "CONFIRMED_FRAUD" ? "red" : r === "FALSE_POSITIVE" ? "blue" : "gray"}>{r === "NOT_REQUIRED" ? "No alert" : label(r)}</Badge>
);
export const SourceBadge = ({ s }: { s: Source }) => <Badge tone={s === "LIVE" ? "blue" : "gray"}>{s === "SEED" ? "Demo seed" : s === "BENCH" ? "Benchmark" : "Live"}</Badge>;

export function Score({ value }: { value: number }) {
  const color = value > 0.65 ? "var(--red)" : value > 0.25 ? "var(--amber)" : "var(--green)";
  return (
    <span className="score" title={`Risk score ${value.toFixed(2)}`}>
      <span className="bar" aria-hidden><i style={{ width: `${Math.round(value * 100)}%`, background: color }} /></span>{value.toFixed(2)}
    </span>
  );
}

export const Spinner = () => <span className="spinner" role="status" aria-label="Loading" />;
export const Loading = ({ text = "Loading…" }: { text?: string }) => <div className="state"><Spinner /> <span style={{ marginLeft: 8 }}>{text}</span></div>;
export const Empty = ({ children }: { children: ReactNode }) => <div className="empty">{children}</div>;
export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return <div className="state err" role="alert"><p>{message}</p>{onRetry && <button className="btn" onClick={onRetry}>Try again</button>}</div>;
}

export function PageHead({ title, sub, children }: { title: string; sub?: ReactNode; children?: ReactNode }) {
  return <div className="page-head"><div><h1>{title}</h1>{sub && <p>{sub}</p>}</div><div className="btn-row">{children}</div></div>;
}

export function Pager({ page, pages, total, onPage }: { page: number; pages: number; total: number; onPage: (p: number) => void }) {
  return (
    <div className="pager">
      <span>{total.toLocaleString()} result{total === 1 ? "" : "s"} · page {page} of {pages}</span>
      <span className="btn-row">
        <button className="btn small" disabled={page <= 1} onClick={() => onPage(page - 1)}>Previous</button>
        <button className="btn small" disabled={page >= pages} onClick={() => onPage(page + 1)}>Next</button>
      </span>
    </div>
  );
}

export function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null;
    ref.current?.querySelector<HTMLElement>("input,select,textarea,button")?.focus();
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("keydown", onKey); prev?.focus(); };
  }, [onClose]);
  return (
    <div className="overlay" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="modal" role="dialog" aria-modal="true" aria-label={title} ref={ref}><h2>{title}</h2>{children}</div>
    </div>
  );
}

export function ConfirmDialog(props: { title: string; body: ReactNode; confirmLabel: string; danger?: boolean; busy?: boolean; error?: string | null; onConfirm: () => void; onCancel: () => void }) {
  return (
    <Modal title={props.title} onClose={props.onCancel}>
      <div>{props.body}</div>
      {props.error && <p className="field-err" role="alert">{props.error}</p>}
      <div className="btn-row">
        <button className="btn" onClick={props.onCancel} disabled={props.busy}>Cancel</button>
        <button className={`btn ${props.danger ? "danger" : "primary"}`} onClick={props.onConfirm} disabled={props.busy}>{props.busy ? "Working…" : props.confirmLabel}</button>
      </div>
    </Modal>
  );
}

interface Toast { id: number; text: string; err: boolean }
const ToastCtx = createContext<(text: string, err?: boolean) => void>(() => undefined);
export const useToast = () => useContext(ToastCtx);
export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback((text: string, err = false) => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, text, err }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 5000);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="toasts" aria-live="polite">{toasts.map((t) => <div key={t.id} className={`toast ${t.err ? "err" : ""}`}>{t.text}</div>)}</div>
    </ToastCtx.Provider>
  );
}

export function Field({ label: text, hint, error, children }: { label: string; hint?: string; error?: string; children: ReactNode }) {
  return <label className="f"><span>{text}</span>{children}{hint && !error && <span className="hint">{hint}</span>}{error && <span className="field-err" role="alert">{error}</span>}</label>;
}

/** Last line of defence: an unexpected response shape or render bug shows a recoverable message instead of a blank page. */
export class ErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch(error: unknown) { console.error("render error", error); }
  render() {
    return this.state.failed
      ? <div className="state err" role="alert"><p>This page could not be displayed. The server may have sent data in an unexpected format.</p><button className="btn" onClick={() => window.location.reload()}>Reload</button></div>
      : this.props.children;
  }
}
