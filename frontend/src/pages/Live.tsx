import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { LiveStatus } from "../api/types";
import { useAuth } from "../auth";
import { Badge, ErrorState, Loading, PageHead, useToast } from "../components/ui";
import { errMsg, fmtMoney } from "../lib";

const n = (x: number | null | undefined, d = 1) => (x === null || x === undefined ? "–" : x.toFixed(d));
const STATE: Record<string, [string, "green" | "amber" | "gray" | "red" | "blue"]> = {
  idle: ["Idle", "gray"], starting: ["Starting", "amber"], warming: ["Warming up", "amber"], running: ["Running", "green"], completed: ["Completed", "blue"], stopped: ["Stopped", "gray"], error: ["Error", "red"],
};

function Kpi({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: "good" | "bad" }) {
  return <div className="kpi"><div className="v" style={tone ? { color: tone === "good" ? "var(--green)" : "var(--red)" } : undefined}>{value}</div><div className="l">{label}</div>{sub && <div className="s">{sub}</div>}</div>;
}

function Funnel({ s }: { s: LiveStatus }) {
  const total = Math.max(s.approved + s.held + s.declined + s.gate_rejected_fraud + s.gate_rejected_genuine, 1);
  const parts: [string, number, string][] = [["Approved", s.approved, "var(--green)"], ["Held", s.held, "var(--amber)"], ["Declined", s.declined, "var(--red)"], ["Refused at gate", s.gate_rejected_fraud + s.gate_rejected_genuine, "#7b5ea7"]];
  return (
    <div>
      <div className="stack" role="img" aria-label="Decision mix">{parts.map(([l, v, c]) => <i key={l} style={{ width: `${(100 * v) / total}%`, background: c }} title={`${l}: ${v}`} />)}</div>
      <div className="legend">{parts.map(([l, v, c]) => <span key={l}><span className="dot" style={{ background: c }} />{l} {v.toLocaleString()}</span>)}</div>
    </div>
  );
}

export default function Live() {
  const { isAdmin } = useAuth();
  const toast = useToast();
  const [s, setS] = useState<LiveStatus | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [cfg, setCfg] = useState({ cards: 150, rate: 3, fraud_boost: 3, autopilot: true });
  const alive = useRef(true);

  const load = async () => { try { const r = await api.get<LiveStatus>("/api/live/status"); if (alive.current) { setS(r); setErr(null); } } catch (e) { if (alive.current) setErr(errMsg(e)); } };
  useEffect(() => { alive.current = true; void load(); const t = setInterval(() => void load(), 1500); return () => { alive.current = false; clearInterval(t); }; }, []);

  const act = async (fn: () => Promise<unknown>, ok?: string) => { setBusy(true); try { await fn(); if (ok) toast(ok); await load(); } catch (e) { toast(errMsg(e), true); } finally { setBusy(false); } };
  if (!s) return err ? <ErrorState message={err} onRetry={() => void load()} /> : <Loading />;
  const k = s.kpis;
  const [stateText, tone] = STATE[s.state] ?? [s.state, "gray"];
  return (
    <>
      <PageHead title="Live mode" sub="A simulated stream of Indian card transactions runs through the real pipeline: score, block, message the cardholder, close the case. Only grey cases reach a person.">
        <Badge tone={tone}>{stateText}</Badge>
        {isAdmin && (s.running
          ? <button className="btn danger" disabled={busy} onClick={() => void act(() => api.post("/api/live/stop"), "Simulation stopped.")}>Stop</button>
          : <button className="btn primary" disabled={busy} onClick={() => void act(() => api.post("/api/live/start", cfg), "Simulation started.")}>Start simulation</button>)}
      </PageHead>
      {s.error && <div className="banner err" role="alert">Engine error: {s.error}</div>}
      <div className="banner">Everything here is <strong>synthetic</strong>. Precision and recall are measured against the simulator’s own ground truth, so they show how well the system finds the simulated fraud patterns, not real-world accuracy.</div>

      {isAdmin && !s.running && (
        <div className="card" style={{ marginBottom: 14 }}>
          <div className="filters" style={{ marginBottom: 0 }}>
            <label className="f">Cardholders<input type="number" min={20} max={600} value={cfg.cards} onChange={(e) => setCfg({ ...cfg, cards: +e.target.value })} /></label>
            <label className="f">Speed (tx per second)<input type="number" min={0.5} max={25} step={0.5} value={cfg.rate} onChange={(e) => setCfg({ ...cfg, rate: +e.target.value })} /></label>
            <label className="f">Fraud intensity (×)<input type="number" min={0.5} max={10} step={0.5} value={cfg.fraud_boost} onChange={(e) => setCfg({ ...cfg, fraud_boost: +e.target.value })} /></label>
            <label className="f" style={{ flexDirection: "row", alignItems: "center", gap: 6 }}><input type="checkbox" checked={cfg.autopilot} onChange={(e) => setCfg({ ...cfg, autopilot: e.target.checked })} />Autopilot</label>
          </div>
        </div>)}

      <div className="kpis">
        <Kpi label="Transactions scored" value={s.processed.toLocaleString()} sub={s.sim_time ? `simulated time ${new Date(s.sim_time).toLocaleString(undefined, { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "UTC" })}` : "waiting to start"} />
        <Kpi label="Precision (simulated)" value={k?.precision_pct != null ? `${n(k.precision_pct)}%` : "–"} sub={k ? `${k.false_alarms} false alarms` : undefined} tone={k?.precision_pct != null && k.precision_pct >= 80 ? "good" : undefined} />
        <Kpi label="Recall (simulated)" value={k?.recall_pct != null ? `${n(k.recall_pct)}%` : "–"} sub={k ? `${k.frauds_caught} of ${k.frauds} frauds caught` : undefined} tone={k?.recall_pct != null && k.recall_pct >= 80 ? "good" : undefined} />
        <Kpi label="Handled without a human" value={k?.autonomy_pct != null ? `${n(k.autonomy_pct)}%` : "–"} sub={k ? `${k.alerts_auto_resolved} of ${k.alerts} alerts` : undefined} />
        <Kpi label="Scoring time" value={k?.avg_latency_ms != null ? `${n(k.avg_latency_ms, 1)} ms` : "–"} sub={k?.p95_latency_ms != null ? `p95 ${n(k.p95_latency_ms, 1)} ms` : undefined} />
      </div>

      <div className="grid g2">
        <div className="grid" style={{ alignContent: "start" }}>
          <div className="card">
            <h2>Money protected</h2>
            <div className="grid g3" style={{ marginBottom: 10 }}>
              <div><div className="muted">Fraud stopped</div><strong style={{ fontSize: 20, color: "var(--green)" }}>{fmtMoney(k?.fraud_inr_prevented ?? 0)}</strong></div>
              <div><div className="muted">Held for review</div><strong style={{ fontSize: 20, color: "var(--amber)" }}>{fmtMoney(k?.fraud_inr_held ?? 0)}</strong></div>
              <div><div className="muted">Missed</div><strong style={{ fontSize: 20, color: "var(--red)" }}>{fmtMoney(k?.fraud_inr_missed ?? 0)}</strong></div>
            </div>
            <Funnel s={s} />
          </div>
          <div className="card">
            <h2>What the autopilot did</h2>
            <dl className="dl" style={{ gridTemplateColumns: "190px 1fr" }}>
              <dt>Autopilot</dt><dd>{s.autopilot ? <Badge tone="green">On</Badge> : <Badge tone="gray">Off</Badge>} <span className="muted">blocks declines scoring ≥ {s.auto_block_score.toFixed(2)}</span></dd>
              <dt>Cards blocked automatically</dt><dd>{s.auto_blocked.toLocaleString()}</dd>
              <dt>Cardholder replies handled</dt><dd>{s.replies.toLocaleString()} <span className="muted">(simulated customers answering the alert message)</span></dd>
              <dt>Fraud refused at the gate</dt><dd>{s.gate_rejected_fraud.toLocaleString()} <span className="muted">attempts on already-blocked cards</span></dd>
              <dt>Genuine payments refused</dt><dd>{s.gate_rejected_genuine.toLocaleString()} <span className="muted">customer friction while a card was blocked</span></dd>
              <dt>Waiting for a human</dt><dd><strong>{k?.human_queue ?? 0}</strong> {(k?.human_queue ?? 0) > 0 && <Link to="/alerts">open the queue</Link>}</dd>
            </dl>
          </div>
          <div className="card">
            <h2>Model in use</h2>
            {s.model ? <p style={{ margin: 0 }}><code>{s.model.name}</code> · {s.model.algorithm.replace(/_/g, " ")} · held-out PR-AUC {s.model.pr_auc.toFixed(3)} · <Link to="/models">see model report</Link></p>
              : <p className="muted" style={{ margin: 0 }}>No live model is active, so scoring uses the rule baseline.</p>}
          </div>
        </div>
        <div className="card" style={{ minHeight: 360 }}>
          <h2>Live feed {s.running && <span className="spinner" style={{ width: 12, height: 12, marginLeft: 6 }} aria-hidden />}</h2>
          {s.feed.length === 0 ? <p className="muted">Nothing yet. Start the simulation to watch decisions arrive.</p> : (
            <ul style={{ listStyle: "none", margin: 0, padding: 0 }} aria-live="polite">
              {s.feed.map((f, i) => (
                <li key={`${f.at}-${i}`} style={{ padding: "6px 0", borderBottom: "1px solid var(--line)", fontSize: 13, display: "flex", gap: 8 }}>
                  <span className="dot" style={{ marginTop: 5, flexShrink: 0, background: f.level === "decline" ? "var(--red)" : f.level === "hold" ? "var(--amber)" : f.level === "block" ? "#7b5ea7" : f.level === "reply" ? "var(--accent)" : "var(--ink-3)" }} />
                  <span>{f.tx_id ? <Link to={`/transactions/${f.tx_id}`}>{f.text}</Link> : f.text}</span>
                </li>))}
            </ul>)}
        </div>
      </div>
    </>
  );
}
