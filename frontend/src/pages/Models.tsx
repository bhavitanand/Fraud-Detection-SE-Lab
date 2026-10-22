import { useState } from "react";
import { api } from "../api/client";
import type { ModelRow, ModelsResponse } from "../api/types";
import { useAuth } from "../auth";
import { Badge, ConfirmDialog, Empty, ErrorState, Loading, PageHead, useToast } from "../components/ui";
import { errMsg, fmtPct, fmtTime, useAsync } from "../lib";

const pct = (n: number) => `${(n * 100).toFixed(1)}%`;

export default function Models() {
  const { isAdmin } = useAuth();
  const toast = useToast();
  const { data, error, loading, reload } = useAsync(() => api.get<ModelsResponse>("/api/models"), []);
  const [action, setAction] = useState<{ m: ModelRow; kind: "deploy" | "retire" } | null>(null);
  const [busy, setBusy] = useState(false), [err, setErr] = useState<string | null>(null);

  if (loading && !data) return <Loading />;
  if (error && !data) return <ErrorState message={error.message} onRetry={reload} />;
  if (!data) return null;
  const run = async () => {
    if (!action) return;
    setBusy(true); setErr(null);
    try { await api.post(`/api/models/${action.m.model_id}/${action.kind}`); toast(action.kind === "deploy" ? "Model deployed." : "Model retired. Scoring is now rules-only."); setAction(null); reload(); } catch (e) { setErr(errMsg(e)); } finally { setBusy(false); }
  };
  const replay = async () => {
    setBusy(true);
    try { const r = await api.post<{ replayed: number; flagged: number; remaining: number }>("/api/models/benchmark/replay?count=25"); toast(`Replayed ${r.replayed} benchmark rows: ${r.flagged} flagged, ${r.remaining} left.`); reload(); } catch (e) { toast(errMsg(e), true); } finally { setBusy(false); }
  };
  const bm = data.benchmark;
  return (
    <>
      <PageHead title="ML model" sub="Offline-trained classifier combined with the rules for transactions that carry the benchmark features.">
        <button className="btn" onClick={reload}>Refresh</button>
      </PageHead>
      {!data.ml_available && <div className="banner warn">scikit-learn is not installed on the server, so no model can be loaded. Scoring uses rules only.</div>}
      <div className="banner">{data.training_note} Live Indian transactions have no anonymised features, so they are scored by the rules; the model applies to benchmark replays and to any gateway that supplies the 28 features.</div>
      {data.items.length === 0 ? <Empty>No models registered.</Empty> : data.items.map((m) => {
        const t = m.metrics.metrics.test, a = t.at_app_threshold;
        return (
          <div className="card mt" key={m.model_id}>
            <div className="page-head" style={{ marginBottom: 8 }}>
              <div><h2 style={{ marginBottom: 2 }}>{m.name} <Badge tone={m.status === "active" ? "green" : m.status === "retired" ? "gray" : "blue"}>{m.status}</Badge></h2>
                <span className="muted">{m.algorithm.replace(/_/g, " ")} · trained {fmtTime(m.trained_at)} · scikit-learn {m.metrics.sklearn}</span></div>
              {isAdmin && (m.status === "active"
                ? <button className="btn" onClick={() => { setErr(null); setAction({ m, kind: "retire" }); }}>Retire</button>
                : <button className="btn primary" onClick={() => { setErr(null); setAction({ m, kind: "deploy" }); }}>Deploy</button>)}
            </div>
            <div className="grid g2">
              <div>
                <h3>Held-out test results (chronological last 20%)</h3>
                <dl className="dl"><dt>PR-AUC</dt><dd>{t.pr_auc.toFixed(3)} <span className="muted">(random guessing ≈ {t.prevalence.toFixed(4)})</span></dd><dt>ROC-AUC</dt><dd>{t.roc_auc.toFixed(3)}</dd>
                  <dt>Precision</dt><dd>{pct(a.precision)}</dd><dt>Recall</dt><dd>{pct(a.recall)}</dd><dt>F1</dt><dd>{a.f1.toFixed(3)}</dd>
                  <dt>Confusion</dt><dd>{a.tp} frauds caught, {a.fn} missed, {a.fp} false alarms, {a.tn.toLocaleString()} correctly passed</dd></dl>
                <p className="muted" style={{ fontSize: 12 }}>Measured at the app’s own flag threshold (score above {0.25}). Only {m.metrics.split.test.frauds} frauds were in the test split, so these figures are uncertain.</p>
              </div>
              <div>
                <h3>Data and method</h3>
                <dl className="dl"><dt>Dataset</dt><dd>{m.metrics.dataset.name} ({m.metrics.dataset.currency}, 2013, European cardholders)</dd><dt>Rows</dt><dd>{m.metrics.dataset.rows_raw.toLocaleString()} raw, {m.metrics.dataset.duplicates_dropped} duplicates dropped, {m.metrics.dataset.frauds} frauds</dd>
                  <dt>Split</dt><dd>{m.metrics.split.method}</dd><dt>Selection</dt><dd>{Object.entries(m.metrics.metrics.validation_pr_auc_by_candidate).map(([k, v]) => `${k.replace(/_/g, " ")} ${v.toFixed(3)}`).join(" vs ")} (validation PR-AUC)</dd></dl>
                <ul className="muted" style={{ fontSize: 12, paddingLeft: 18, margin: 0 }}>{m.metrics.limitations.map((l) => <li key={l}>{l}</li>)}</ul>
              </div>
            </div>
          </div>);
      })}
      <div className="card mt">
        <div className="page-head" style={{ marginBottom: 8 }}><div><h2 style={{ marginBottom: 2 }}>Benchmark replay</h2><span className="muted">Send held-out benchmark rows through the live scoring path and compare with their known labels.</span></div>
          {isAdmin && <button className="btn primary" onClick={() => void replay()} disabled={busy}>Replay 25 rows</button>}</div>
        {bm.replayed === 0 ? <Empty>Nothing replayed yet.</Empty> : (
          <dl className="dl"><dt>Replayed</dt><dd>{bm.replayed} rows (filter Source = Benchmark on the Transactions page)</dd><dt>Caught</dt><dd>{bm.tp} of {bm.tp + bm.fn} frauds (recall {fmtPct(bm.recall)})</dd><dt>False alarms</dt><dd>{bm.fp} (precision {fmtPct(bm.precision)})</dd><dt>Correctly passed</dt><dd>{bm.tn}</dd></dl>
        )}
        <p className="muted" style={{ fontSize: 12, marginBottom: 0 }}>{bm.note}</p>
      </div>
      {action && <ConfirmDialog title={`${action.kind === "deploy" ? "Deploy" : "Retire"} ${action.m.name}?`} danger={action.kind === "retire"} confirmLabel={action.kind === "deploy" ? "Deploy" : "Retire"} busy={busy} error={err} onConfirm={() => void run()} onCancel={() => setAction(null)}
        body={action.kind === "deploy" ? <p>This model will score benchmark-feature transactions from now on. The previous active model is retired.</p> : <p>Scoring falls back to rules only until a model is deployed again.</p>} />}
    </>
  );
}
