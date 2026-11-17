import { useState } from "react";
import { api } from "../api/client";
import type { CopilotCase } from "../api/types";
import { errMsg } from "../lib";
import { Badge, useToast } from "./ui";

export default function CaseCopilot({ txId }: { txId: number }) {
  const toast = useToast();
  const [r, setR] = useState<CopilotCase | null>(null);
  const [busy, setBusy] = useState(false);
  const run = async () => { setBusy(true); try { setR(await api.get<CopilotCase>(`/api/transactions/${txId}/copilot`)); } catch (e) { toast(errMsg(e), true); } finally { setBusy(false); } };
  const copy = async () => { try { await navigator.clipboard.writeText(r?.customer_message ?? ""); toast("Message copied."); } catch { toast("Copy is not available in this browser.", true); } };
  return (
    <div className="card mt">
      <div className="page-head" style={{ marginBottom: 8 }}>
        <div><h2 style={{ marginBottom: 2 }}>AI case summary</h2><span className="muted">A short briefing, a recommended action and a draft message for the cardholder.</span></div>
        <button className="btn" onClick={() => void run()} disabled={busy}>{busy ? "Working…" : r ? "Regenerate" : "Summarise this case"}</button>
      </div>
      {r && (
        <dl className="dl" style={{ gridTemplateColumns: "150px 1fr" }}>
          <dt>Summary</dt><dd>{r.summary}</dd>
          <dt>Suggested action</dt><dd>{r.recommendation}</dd>
          <dt>Message draft</dt><dd>{r.customer_message} <button className="btn small" onClick={() => void copy()}>Copy</button></dd>
          <dt>Written by</dt><dd><Badge tone={r.provider === "gemini" ? "green" : "gray"}>{r.provider === "gemini" ? `Gemini · ${r.model}` : "Offline engine"}</Badge> <span className="muted">{r.fallback_reason ? `(Gemini unreachable: ${r.fallback_reason})` : "Draft only, a person decides."}</span></dd>
        </dl>)}
    </div>
  );
}
