import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type { Card } from "../api/types";
import { useAuth } from "../auth";
import { Badge, ConfirmDialog, Empty, ErrorState, Field, Loading, PageHead, useToast } from "../components/ui";
import { errMsg, fmtTime, useAsync } from "../lib";

export default function Cards() {
  const [sp, setSp] = useSearchParams();
  const { isAdmin } = useAuth();
  const toast = useToast();
  const q = sp.get("q") ?? "", blocked = sp.get("blocked") ?? "";
  const { data, error, loading, reload } = useAsync(() => api.get<Card[]>("/api/cards", { q, blocked: blocked || undefined }), [q, blocked]);
  const [target, setTarget] = useState<{ card: Card; block: boolean } | null>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const set = (k: string, v: string) => { const n = new URLSearchParams(sp); if (v) n.set(k, v); else n.delete(k); setSp(n, { replace: true }); };

  const run = async () => {
    if (!target) return;
    setBusy(true); setErr(null);
    try {
      const path = `/api/cards/${encodeURIComponent(target.card.token)}/${target.block ? "block" : "unblock"}`;
      const r = await api.post<{ changed: boolean }>(path, target.block ? { reason: reason.trim() || undefined } : undefined);
      toast(r.changed ? `${target.card.token} ${target.block ? "blocked" : "unblocked"}` : "No change; the token was already in that state.");
      setTarget(null); setReason(""); reload();
    } catch (e) { setErr(errMsg(e)); } finally { setBusy(false); }
  };

  return (
    <>
      <PageHead title="Cards" sub="Synthetic card tokens seen by this application." />
      <div className="banner">These are synthetic demo tokens. Blocking a token only changes this application's local behavior (new transactions on it are rejected). It does not contact any bank or payment network.</div>
      {!isAdmin && <div className="banner warn">Blocking and unblocking requires the administrator role. You can view status only.</div>}
      <div className="filters">
        <Field label="Search token"><input value={q} onChange={(e) => set("q", e.target.value)} placeholder="SYNTH-…" /></Field>
        <Field label="Status"><select value={blocked} onChange={(e) => set("blocked", e.target.value)}><option value="">All</option><option value="true">Blocked</option><option value="false">Active</option></select></Field>
      </div>
      {loading && !data ? <Loading /> : error && !data ? <ErrorState message={error.message} onRetry={reload} /> : data && (
        <div className="table-wrap">
          {data.length === 0 ? <Empty>No card tokens match.</Empty> : (
            <table><thead><tr><th>Token</th><th>Status</th><th>Block details</th><th className="num">Transactions</th><th className="num">Alerts</th><th>Last seen</th><th /></tr></thead>
              <tbody>{data.map((c) => (
                <tr key={c.token}><td className="mono">{c.token}</td><td>{c.blocked ? <Badge tone="red">Blocked</Badge> : <Badge tone="green">Active</Badge>}</td>
                  <td className="wrap">{c.blocked ? <>{c.block_reason ?? "—"}<br /><span className="muted">{c.blocked_by} · {fmtTime(c.blocked_at)}</span></> : "—"}</td>
                  <td className="num">{c.tx_count}</td><td className="num">{c.alert_count}</td><td>{fmtTime(c.last_seen)}</td>
                  <td><button className="btn small" disabled={!isAdmin} title={isAdmin ? "" : "Administrator role required"} onClick={() => { setErr(null); setTarget({ card: c, block: !c.blocked }); }}>{c.blocked ? "Unblock" : "Block"}</button></td></tr>))}</tbody></table>)}
        </div>
      )}
      {target && (
        <ConfirmDialog title={`${target.block ? "Block" : "Unblock"} ${target.card.token}?`} danger={target.block} confirmLabel={target.block ? "Block token" : "Unblock token"} busy={busy} error={err} onConfirm={run} onCancel={() => setTarget(null)}
          body={target.block ? <><p>New transactions on this token will be rejected in this demo.</p><Field label="Reason (optional)"><input maxLength={200} value={reason} onChange={(e) => setReason(e.target.value)} /></Field></> : <p>This token will accept new transactions again.</p>} />
      )}
    </>
  );
}
