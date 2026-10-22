import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type { AuditEvent, AuditPage, AuditVerify } from "../api/types";
import { useAuth } from "../auth";
import { Empty, ErrorState, Field, Loading, PageHead, Pager, useToast } from "../components/ui";
import { errMsg, fmtTime, label, useAsync } from "../lib";

// Values are rendered as React text children, never as HTML.
function Detail({ d }: { d: Record<string, unknown> }) {
  const parts = Object.entries(d).map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : String(v)}`);
  return <>{parts.join(" · ") || "—"}</>;
}
function targetLink(t: string | null) {
  const m = t?.match(/^transaction:(\d+)$/);
  return m ? <Link to={`/transactions/${m[1]}`}>{t}</Link> : <>{t ?? "—"}</>;
}

export function AuditList({ items, compact }: { items: AuditEvent[]; compact?: boolean }) {
  if (items.length === 0) return <Empty>No audit events.</Empty>;
  return (
    <div className="table-wrap"><table>
      <thead><tr><th>Time</th><th>Actor</th><th>Action</th>{!compact && <th>Target</th>}<th>Details</th><th>Hash</th></tr></thead>
      <tbody>{items.map((e) => <tr key={e.id}><td>{fmtTime(e.at)}</td><td>{e.actor}</td><td>{label(e.action)}</td>{!compact && <td className="mono">{targetLink(e.target)}</td>}<td className="wrap"><Detail d={e.detail} /></td><td className="mono muted">{e.hash}</td></tr>)}</tbody>
    </table></div>
  );
}

const SIZE = 50;
export default function Audit() {
  const [sp, setSp] = useSearchParams();
  const [q, setQ] = useState(sp.get("q") ?? "");
  const { isAdmin } = useAuth();
  const toast = useToast();
  const verify = async () => { try { const r = await api.get<AuditVerify>("/api/audit/verify"); toast(r.ok ? `Audit chain intact: ${r.checked} entries verified.` : `Audit chain BROKEN at entry #${r.first_broken_id}.`, !r.ok); } catch (e) { toast(errMsg(e), true); } };
  const page = Number(sp.get("page") ?? 1) || 1;
  const { data, error, loading, reload } = useAsync(() => api.get<AuditPage>("/api/audit", { action: sp.get("action"), actor: sp.get("actor"), q: sp.get("q"), limit: SIZE, offset: (page - 1) * SIZE }), [sp.toString()]);
  const set = (k: string, v: string) => { const n = new URLSearchParams(sp); if (v) n.set(k, v); else n.delete(k); if (k !== "page") n.delete("page"); setSp(n, { replace: true }); };
  return (
    <>
      <PageHead title="Audit log" sub="Every state-changing action, newest first. Entries are hash-chained, so edits or deletions in the database are detectable.">{isAdmin && <button className="btn" onClick={() => void verify()}>Verify integrity</button>}<button className="btn" onClick={reload}>Refresh</button></PageHead>
      <form className="filters" onSubmit={(e) => { e.preventDefault(); set("q", q.trim()); }}>
        <Field label="Action"><select value={sp.get("action") ?? ""} onChange={(e) => set("action", e.target.value)}><option value="">All</option>{data?.actions.map((a) => <option key={a} value={a}>{label(a)}</option>)}</select></Field>
        <Field label="Actor"><input value={sp.get("actor") ?? ""} onChange={(e) => set("actor", e.target.value)} placeholder="username" /></Field>
        <Field label="Search details"><input value={q} onChange={(e) => setQ(e.target.value)} placeholder="token, id…" /></Field>
        <button className="btn">Search</button>
      </form>
      {loading && !data ? <Loading /> : error && !data ? <ErrorState message={error.message} onRetry={reload} /> : data && (
        <><AuditList items={data.items} /><Pager page={page} pages={Math.max(1, Math.ceil(data.total / SIZE))} total={data.total} onPage={(n) => set("page", String(n))} /></>
      )}
    </>
  );
}
