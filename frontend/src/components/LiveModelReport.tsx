import type { LiveMeta } from "../api/types";

const pct = (x: number, d = 1) => `${(x * 100).toFixed(d)}%`;

function Bars({ rows, max, fmt }: { rows: { label: string; v: number }[]; max?: number; fmt: (v: number) => string }) {
  const m = max ?? Math.max(...rows.map((r) => r.v), 0.0001);
  return (
    <div>{rows.map((r) => (
      <div key={r.label} style={{ display: "grid", gridTemplateColumns: "minmax(120px, 230px) 1fr 52px", gap: 8, alignItems: "center", padding: "3px 0", fontSize: 12.5 }}>
        <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={r.label}>{r.label}</span>
        <span className="stack" style={{ height: 10 }}><i style={{ width: `${(100 * r.v) / m}%`, background: "var(--accent)" }} /></span>
        <span className="mono" style={{ textAlign: "right" }}>{fmt(r.v)}</span>
      </div>))}</div>
  );
}

function PrCurve({ curves }: { curves: Record<string, [number, number][]> }) {
  const W = 300, H = 190, P = 28;
  const colors: Record<string, string> = { rules_only: "#a15c07", model_only: "#1f3a5f", rules_plus_model: "#7b5ea7" };
  const names: Record<string, string> = { rules_only: "Rules only", model_only: "Model", rules_plus_model: "Rules+model" };
  const x = (r: number) => P + r * (W - P - 6), y = (p: number) => H - P - p * (H - P - 8);
  return (
    <svg viewBox={`0 0 ${W} ${H + 20}`} role="img" aria-label="Precision-recall curves" style={{ width: "100%", maxWidth: 420 }}>
      {[0, 0.5, 1].map((t) => <g key={t}><line x1={P} x2={W - 6} y1={y(t)} y2={y(t)} stroke="var(--line)" /><text x={P - 4} y={y(t) + 3} fontSize="9" textAnchor="end" fill="var(--ink-3)">{t}</text>
        <text x={x(t)} y={H - P + 12} fontSize="9" textAnchor="middle" fill="var(--ink-3)">{t}</text></g>)}
      {Object.entries(curves).map(([k, pts]) => <polyline key={k} fill="none" stroke={colors[k] ?? "#000"} strokeWidth="2" points={pts.map(([p, r]) => `${x(r).toFixed(1)},${y(p).toFixed(1)}`).join(" ")} />)}
      <text x={(P + W) / 2} y={H + 6} fontSize="10" textAnchor="middle" fill="var(--ink-3)">Recall →  (vertical axis: precision)</text>
      {Object.keys(curves).map((k, i) => <g key={k}><rect x={P + 4 + i * 105} y={H + 10} width="9" height="9" fill={colors[k]} /><text x={P + 17 + i * 105} y={H + 18} fontSize="9.5" fill="var(--ink-2)">{names[k] ?? k}</text></g>)}
    </svg>
  );
}

export default function LiveModelReport({ meta }: { meta: LiveMeta }) {
  const t = meta.metrics.test, a = t.at_app_threshold, c = t.comparison;
  const rows: [string, typeof c.rules_only][] = [["Rules only (baseline)", c.rules_only], ["Model only (deployed)", c.model_only], ["Rules + model combined", c.rules_plus_model]];
  const pat = Object.entries(t.per_pattern_recall);
  return (
    <>
      <div className="kpis" style={{ gridTemplateColumns: "repeat(5, 1fr)" }}>
        {[["PR-AUC", t.pr_auc.toFixed(3)], ["ROC-AUC", t.roc_auc.toFixed(3)], ["Precision", pct(a.precision)], ["Recall", pct(a.recall)], ["False alarm rate", pct(c.model_only.at_app_threshold.false_positive_rate, 2)]].map(([l, v]) => <div className="kpi" key={l}><div className="v">{v}</div><div className="l">{l}</div></div>)}
      </div>
      <div className="banner warn" style={{ fontSize: 12.5 }}>Measured on {meta.split.test.rows.toLocaleString()} held-out <strong>simulated</strong> transactions ({meta.split.test.frauds.toLocaleString()} frauds), the chronological last 20%. This is a measure of how well the system finds the simulated patterns, not real-world accuracy.</div>
      <div className="grid g-eq2">
        <div>
          <h3>Why a model, not just rules</h3>
          <div className="table-wrap"><table><thead><tr><th>Scorer</th><th className="num">PR-AUC</th><th className="num">Precision</th><th className="num">Recall</th><th className="num">False alarms</th></tr></thead>
            <tbody>{rows.map(([n, r]) => <tr key={n}><td>{n}</td><td className="num">{r.pr_auc.toFixed(3)}</td><td className="num">{pct(r.at_app_threshold.precision)}</td><td className="num">{pct(r.at_app_threshold.recall)}</td><td className="num">{r.at_app_threshold.fp.toLocaleString()}</td></tr>)}</tbody></table></div>
          <p className="muted" style={{ fontSize: 12 }}>Same test set, same flag threshold. Rules alone catch most fraud but wrongly flag about 1 in 5 genuine payments; adding the model removes almost all of that noise.</p>
          <h3 style={{ marginTop: 14 }}>Model selection (validation PR-AUC)</h3>
          <Bars rows={Object.entries(meta.metrics.validation_pr_auc_by_candidate).sort((x, y) => y[1] - x[1]).map(([k, v]) => ({ label: k.replace(/_/g, " "), v }))} max={1} fmt={(v) => v.toFixed(3)} />
        </div>
        <div><h3>Precision–recall curve</h3><PrCurve curves={t.pr_curves} /></div>
      </div>
      <div className="grid g-eq2 mt">
        <div><h3>Recall by fraud pattern</h3><Bars rows={pat.map(([k, v]) => ({ label: `${k.replace(/_/g, " ")} (${v.count})`, v: v.flagged_by_model }))} max={1} fmt={(v) => pct(v, 0)} />
          <p className="muted" style={{ fontSize: 12 }}>Low-and-slow fraud (small purchases that look normal) is the weak spot; the report keeps that visible rather than hiding it.</p></div>
        <div><h3>What drives the model</h3><Bars rows={t.feature_importance.slice(0, 8).map((f) => ({ label: f.feature, v: f.pr_auc_drop }))} fmt={(v) => v.toFixed(2)} />
          <p className="muted" style={{ fontSize: 12 }}>Drop in PR-AUC when that group of inputs is shuffled (permutation importance).</p></div>
      </div>
      <div className="mt"><h3>Calibration: predicted risk versus what actually happened</h3>
        <div className="table-wrap"><table><thead><tr><th>Predicted band</th><th className="num">Transactions</th><th className="num">Mean predicted</th><th className="num">Observed fraud rate</th></tr></thead>
          <tbody>{t.calibration.map((b) => <tr key={b.bin}><td>{b.bin}</td><td className="num">{b.n.toLocaleString()}</td><td className="num">{pct(b.mean_predicted)}</td><td className="num">{pct(b.observed_rate)}</td></tr>)}</tbody></table></div></div>
      <div className="grid g-eq2 mt">
        <div><h3>Data and method</h3><dl className="dl"><dt>Dataset</dt><dd>{meta.dataset.name}: {meta.dataset.rows.toLocaleString()} rows, {meta.dataset.cards.toLocaleString()} cards, {meta.dataset.days} days</dd><dt>Fraud patterns</dt><dd>{meta.dataset.fraud_patterns.map((p) => p.replace(/_/g, " ")).join(", ")}</dd><dt>Split</dt><dd>{meta.split.method}</dd></dl></div>
        <ul className="muted" style={{ fontSize: 12, paddingLeft: 18, margin: 0 }}>{meta.limitations.map((l) => <li key={l}>{l}</li>)}</ul>
      </div>
    </>
  );
}
