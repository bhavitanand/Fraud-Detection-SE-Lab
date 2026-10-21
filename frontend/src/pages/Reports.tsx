import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type { Report } from "../api/types";
import { ErrorState, Field, Loading, PageHead, useToast } from "../components/ui";
import { errMsg, fmtPct, label, useAsync } from "../lib";
import { DecisionBar, Trend } from "./Overview";

function Counts({ title, data }: { title: string; data: Record<string, number> }) {
  const rows = Object.entries(data);
  return <div className="card"><h3>{title}</h3>{rows.length === 0 ? <p className="muted">No data.</p> : <dl className="dl">{rows.map(([k, v]) => <><dt key={k}>{label(k)}</dt><dd key={k + "v"}>{v}</dd></>)}</dl>}</div>;
}

export default function Reports() {
  const [sp, setSp] = useSearchParams();
  const toast = useToast();
  const from = sp.get("date_from") ?? "", to = sp.get("date_to") ?? "", source = sp.get("source") ?? "";
  const bad = from && to && from > to;
  const { data, error, loading, reload } = useAsync(() => (bad ? Promise.reject(new Error("range")) : api.get<Report>("/api/reports", { date_from: from, date_to: to, source })), [from, to, source]);
  const [busy, setBusy] = useState(false);
  const set = (k: string, v: string) => { const n = new URLSearchParams(sp); if (v) n.set(k, v); else n.delete(k); setSp(n, { replace: true }); };
  const exportCsv = async () => {
    setBusy(true);
    try { await api.download("/api/reports/export.csv", { date_from: from, date_to: to }, "transactions.csv"); } catch (e) { toast(errMsg(e), true); } finally { setBusy(false); }
  };
  return (
    <>
      <PageHead title="Reports" sub="Descriptive statistics from recorded data."><button className="btn" onClick={exportCsv} disabled={busy}>Export transactions (CSV)</button></PageHead>
      <div className="filters">
        <Field label="From"><input type="date" value={from} onChange={(e) => set("date_from", e.target.value)} /></Field>
        <Field label="To"><input type="date" value={to} onChange={(e) => set("date_to", e.target.value)} /></Field>
        <Field label="Source"><select value={source} onChange={(e) => set("source", e.target.value)}><option value="">All</option><option value="LIVE">Live</option><option value="SEED">Demo seed</option></select></Field>
      </div>
      {bad && <div className="banner err" role="alert">The start date must not be after the end date.</div>}
      {!bad && (loading && !data ? <Loading /> : error && !data ? <ErrorState message={error.message} onRetry={reload} /> : data && (
        <>
          <div className="banner warn"><strong>Read with care.</strong><ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>{data.limitations.map((l) => <li key={l}>{l}</li>)}</ul></div>
          <div className="grid g3">
            <div className="card"><h3>Totals</h3><dl className="dl"><dt>Transactions</dt><dd>{data.transactions}</dd><dt>Flagged</dt><dd>{data.alert_count} ({fmtPct(data.alert_rate)})</dd><dt>Open backlog</dt><dd>{data.alert_backlog}</dd><dt>Reviewed</dt><dd>{data.reviewed}</dd><dt>Confirmed fraud</dt><dd>{data.confirmed_fraud}</dd><dt>False positives</dt><dd>{data.false_positives}</dd><dt>Confirmed share</dt><dd>{fmtPct(data.confirmed_share)} <span className="muted">of reviewed</span></dd></dl></div>
            <div className="card"><h3>Decisions</h3><DecisionBar by={data.by_decision} /></div>
            <Counts title="By channel" data={data.by_channel} />
          </div>
          <div className="card mt"><h2>Daily trend</h2><Trend data={data.trend} />
            {data.trend.length > 0 && <div className="table-wrap mt"><table><thead><tr><th>Date</th><th className="num">Total</th><th className="num">Flagged</th><th className="num">Holds</th><th className="num">Declines</th></tr></thead><tbody>{data.trend.map((d) => <tr key={d.date}><td>{d.date}</td><td className="num">{d.total}</td><td className="num">{d.alerts}</td><td className="num">{d.holds}</td><td className="num">{d.declines}</td></tr>)}</tbody></table></div>}</div>
        </>
      ))}
    </>
  );
}
