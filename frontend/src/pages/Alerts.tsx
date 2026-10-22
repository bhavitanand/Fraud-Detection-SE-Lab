import { Link, useSearchParams } from "react-router-dom";
import { useAuth } from "../auth";
import { api } from "../api/client";
import type { Transaction } from "../api/types";
import { Badge, DecisionBadge, Empty, ErrorState, Loading, PageHead, ReviewBadge, Score, SourceBadge, useToast } from "../components/ui";
import { api as _api } from "../api/client";
import { errMsg, fmtMoney, fmtTime, useAsync } from "../lib";

const TABS = [["OPEN", "Open"], ["CONFIRMED_FRAUD", "Confirmed fraud"], ["FALSE_POSITIVE", "False positive"], ["ALL", "All"]] as const;

export default function Alerts() {
  const [sp, setSp] = useSearchParams();
  const status = sp.get("status") ?? "OPEN", assigned = sp.get("assigned") ?? "";
  const { me } = useAuth();
  const toast = useToast();
  const { data, error, loading, reload } = useAsync(() => api.get<Transaction[]>("/api/alerts", { status, decision: sp.get("decision"), assigned: assigned || undefined }), [sp.toString()]);
  return (
    <>
      <PageHead title="Alerts and cases" sub="Every held or declined transaction is an alert. Highest risk first (first 100 shown)." />
      <div className="tabs" role="group" aria-label="Alert status">{TABS.map(([v, text]) => <button key={v} aria-pressed={status === v} onClick={() => { const n = new URLSearchParams(sp); n.set("status", v); setSp(n, { replace: true }); }}>{text}</button>)}</div>
      <div className="tabs" role="group" aria-label="Assignment">{([["", "Everyone"], ["me", "Assigned to me"], ["unassigned", "Unassigned"]] as const).map(([v, text]) => <button key={v} aria-pressed={assigned === v} onClick={() => { const n = new URLSearchParams(sp); if (v) n.set("assigned", v); else n.delete("assigned"); setSp(n, { replace: true }); }}>{text}</button>)}</div>
      {loading && !data ? <Loading /> : error && !data ? <ErrorState message={error.message} onRetry={reload} /> : data && (
        data.length === 0 ? <div className="table-wrap"><Empty>{status === "OPEN" ? "No open alerts. The review queue is clear." : "No alerts in this view."}</Empty></div> : (
          <div className="table-wrap"><table><thead><tr><th>ID</th><th>Time</th><th>Token</th><th>Merchant</th><th className="num">Amount</th><th>Score</th><th>Decision</th><th>Status</th><th>Assigned</th><th>Cardholder</th><th /></tr></thead>
            <tbody>{data.map((t) => (
              <tr key={t.id}><td>#{t.id}</td><td>{fmtTime(t.created)}</td><td className="mono">{t.token}</td><td>{t.merchant}<span className="muted">{t.location ? ` · ${t.location}` : ""}</span> <SourceBadge s={t.source} /></td><td className="num">{fmtMoney(t.amount, t.currency)}</td><td><Score value={t.score} /></td>
                <td><DecisionBadge d={t.decision} /></td><td><ReviewBadge r={t.review} /></td><td>{t.assigned_to ?? <span className="muted">—</span>}{t.review === "OPEN" && me && !t.assigned_to ? <> <button className="btn small" onClick={() => void _api.post(`/api/alerts/${t.id}/assign`, { assignee: me.email }).then(() => { toast("Assigned to you"); reload(); }, (e: unknown) => toast(errMsg(e), true))}>Take</button></> : null}</td>
                <td>{t.cardholder_response === "NOT_ME" ? <Badge tone="red">Not me</Badge> : t.cardholder_response === "LEGIT" ? <Badge tone="green">Genuine</Badge> : <span className="muted">—</span>}</td>
                <td><Link className="btn small primary" to={`/transactions/${t.id}`} style={{ textDecoration: "none" }}>{t.review === "OPEN" ? "Investigate" : "View"}</Link></td></tr>))}</tbody></table></div>)
      )}
    </>
  );
}
