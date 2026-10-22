import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { Report } from "../api/types";
import { DecisionBadge, Empty, ErrorState, Loading, PageHead, Score, SourceBadge } from "../components/ui";
import { fmtMoney, fmtPct, fmtTime, useAsync } from "../lib";

const COLORS: Record<string, string> = { APPROVE: "var(--green)", HOLD: "var(--amber)", DECLINE: "var(--red)" };

export function DecisionBar({ by }: { by: Record<string, number> }) {
  const total = Object.values(by).reduce((a, b) => a + b, 0);
  if (!total) return <Empty>No transactions yet.</Empty>;
  return (
    <div>
      <div className="stack" role="img" aria-label={Object.entries(by).map(([k, v]) => `${k} ${v}`).join(", ")}>
        {["APPROVE", "HOLD", "DECLINE"].map((k) => (by[k] ? <div key={k} style={{ width: `${(by[k]! / total) * 100}%`, background: COLORS[k] }} /> : null))}
      </div>
      <div className="legend">{["APPROVE", "HOLD", "DECLINE"].map((k) => <span key={k}><i className="dot" style={{ background: COLORS[k] }} />{k} {by[k] ?? 0} ({fmtPct((by[k] ?? 0) / total)})</span>)}</div>
    </div>
  );
}

export function Trend({ data }: { data: Report["trend"] }) {
  if (data.length < 2) return <Empty>A trend needs at least two days of data.</Empty>;
  const W = 560, H = 150, pad = 22, max = Math.max(...data.map((d) => d.total), 1), bw = (W - pad) / data.length;
  return (
    <svg viewBox={`0 0 ${W} ${H + 18}`} width="100%" style={{ maxWidth: 680, display: "block" }} role="img" aria-label="Daily transactions with the flagged portion highlighted">
      <line x1={pad} x2={W} y1={H} y2={H} stroke="var(--line-strong)" />
      <text x={0} y={12} fontSize="10" fill="var(--ink-3)">{max}</text>
      {data.map((d, i) => {
        const x = pad + i * bw + 2, h = (d.total / max) * (H - 16), ah = (d.alerts / max) * (H - 16);
        return (
          <g key={d.date}>
            <title>{`${d.date}: ${d.total} transactions, ${d.alerts} flagged`}</title>
            <rect x={x} y={H - h} width={Math.max(bw - 4, 2)} height={h} fill="var(--accent-soft)" stroke="var(--line-strong)" />
            <rect x={x} y={H - ah} width={Math.max(bw - 4, 2)} height={ah} fill="var(--amber)" />
            {(i === 0 || i === data.length - 1) && <text x={x} y={H + 13} fontSize="10" fill="var(--ink-3)">{d.date.slice(5)}</text>}
          </g>
        );
      })}
    </svg>
  );
}

export default function Overview() {
  const { data, error, loading, reload } = useAsync(() => api.get<Report>("/api/reports"), []);
  if (loading && !data) return <Loading />;
  if (error && !data) return <ErrorState message={error.message} onRetry={reload} />;
  if (!data) return null;
  const seed = data.by_source.SEED ?? 0, live = data.by_source.LIVE ?? 0, bench = data.by_source.BENCH ?? 0;
  return (
    <>
      <PageHead title="Overview" sub="Operational summary of all recorded transactions."><button className="btn" onClick={reload}>Refresh</button></PageHead>
      <div className="banner">Data mix: <strong>{seed}</strong> synthetic seeded (INR), <strong>{live}</strong> submitted live in this app and <strong>{bench}</strong> benchmark replays (EUR, public dataset). {data.note}</div>
      <div className="kpis">
        <div className="kpi"><div className="l">Transactions</div><div className="v">{data.transactions}</div><div className="s">avg score {data.average_score.toFixed(2)}</div></div>
        <div className="kpi"><div className="l">Open alert backlog</div><div className="v">{data.alert_backlog}</div><div className="s"><Link to="/alerts">Review queue</Link> · {data.unassigned_open} unassigned</div></div>
        <div className="kpi"><div className="l">Alert rate</div><div className="v">{fmtPct(data.alert_rate)}</div><div className="s">{data.alert_count} flagged · {fmtMoney(data.flagged_value_inr)} value</div></div>
        <div className="kpi"><div className="l">Confirmed fraud</div><div className="v">{data.confirmed_fraud}</div><div className="s">analyst verdicts</div></div>
        <div className="kpi"><div className="l">False positives</div><div className="v">{data.false_positives}</div><div className="s">confirmed share {fmtPct(data.confirmed_share)}</div></div>
      </div>
      <div className="grid g2">
        <div className="card"><h2>Transactions per day</h2><Trend data={data.trend} /><div className="legend"><span><i className="dot" style={{ background: "var(--accent-soft)", border: "1px solid var(--line-strong)" }} />All</span><span><i className="dot" style={{ background: "var(--amber)" }} />Flagged</span></div></div>
        <div className="card"><h2>Decisions</h2><DecisionBar by={data.by_decision} /><h3 className="mt">Review outcomes</h3>
          <dl className="dl"><dt>Open</dt><dd>{data.by_review.OPEN ?? 0}</dd><dt>Confirmed fraud</dt><dd>{data.by_review.CONFIRMED_FRAUD ?? 0}</dd><dt>False positive</dt><dd>{data.by_review.FALSE_POSITIVE ?? 0}</dd></dl></div>
      </div>
      <div className="card mt"><h2>Most recent flagged transactions</h2>
        {data.recent_suspicious.length === 0 ? <Empty>No flagged transactions.</Empty> : (
          <div className="table-wrap"><table><thead><tr><th>ID</th><th>Time</th><th>Token</th><th>Merchant</th><th className="num">Amount</th><th>Score</th><th>Decision</th><th>Source</th></tr></thead>
            <tbody>{data.recent_suspicious.map((t) => (
              <tr key={t.id}><td><Link to={`/transactions/${t.id}`}>#{t.id}</Link></td><td>{fmtTime(t.created)}</td><td className="mono">{t.token}</td><td>{t.merchant}</td><td className="num">{fmtMoney(t.amount, t.currency)}</td><td><Score value={t.score} /></td><td><DecisionBadge d={t.decision} /></td><td><SourceBadge s={t.source} /></td></tr>
            ))}</tbody></table></div>)}
      </div>
    </>
  );
}
