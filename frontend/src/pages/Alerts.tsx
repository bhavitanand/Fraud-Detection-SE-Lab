import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type { Transaction } from "../api/types";
import { DecisionBadge, Empty, ErrorState, Loading, PageHead, ReviewBadge, Score, SourceBadge } from "../components/ui";
import { fmtMoney, fmtTime, useAsync } from "../lib";

const TABS = [["OPEN", "Open"], ["CONFIRMED_FRAUD", "Confirmed fraud"], ["FALSE_POSITIVE", "False positive"], ["ALL", "All"]] as const;

export default function Alerts() {
  const [sp, setSp] = useSearchParams();
  const status = sp.get("status") ?? "OPEN";
  const { data, error, loading, reload } = useAsync(() => api.get<Transaction[]>("/api/alerts", { status, decision: sp.get("decision") }), [sp.toString()]);
  return (
    <>
      <PageHead title="Alerts and cases" sub="Every held or declined transaction is an alert. Highest risk first (first 100 shown)." />
      <div className="tabs" role="group" aria-label="Alert status">{TABS.map(([v, text]) => <button key={v} aria-pressed={status === v} onClick={() => { const n = new URLSearchParams(sp); n.set("status", v); setSp(n, { replace: true }); }}>{text}</button>)}</div>
      {loading && !data ? <Loading /> : error && !data ? <ErrorState message={error.message} onRetry={reload} /> : data && (
        data.length === 0 ? <div className="table-wrap"><Empty>{status === "OPEN" ? "No open alerts. The review queue is clear." : "No alerts in this view."}</Empty></div> : (
          <div className="table-wrap"><table><thead><tr><th>ID</th><th>Time</th><th>Token</th><th>Merchant</th><th className="num">Amount</th><th>Score</th><th>Decision</th><th>Status</th><th>Source</th><th /></tr></thead>
            <tbody>{data.map((t) => (
              <tr key={t.id}><td>#{t.id}</td><td>{fmtTime(t.created)}</td><td className="mono">{t.token}</td><td>{t.merchant}</td><td className="num">{fmtMoney(t.amount)}</td><td><Score value={t.score} /></td>
                <td><DecisionBadge d={t.decision} /></td><td><ReviewBadge r={t.review} /></td><td><SourceBadge s={t.source} /></td>
                <td><Link className="btn small primary" to={`/transactions/${t.id}`} style={{ textDecoration: "none" }}>{t.review === "OPEN" ? "Investigate" : "View"}</Link></td></tr>))}</tbody></table></div>)
      )}
    </>
  );
}
