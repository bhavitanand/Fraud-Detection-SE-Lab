import { FormEvent, useEffect, useState } from "react";
import { api, fieldErrors } from "../api/client";
import type { RiskConfig, Rules as RulesT } from "../api/types";
import { useAuth } from "../auth";
import { ErrorState, Field, Loading, PageHead, useToast } from "../components/ui";
import { errMsg, useAsync } from "../lib";

export function validate(f: Record<keyof RiskConfig, string>): Record<string, string> {
  const e: Record<string, string> = {};
  const a = Number(f.approve_max), h = Number(f.hold_max), amt = Number(f.high_amount), v = Number(f.velocity_limit);
  if (f.approve_max.trim() === "" || Number.isNaN(a) || a < 0 || a >= 1) e.approve_max = "Enter a number from 0 up to (not including) 1.";
  if (f.hold_max.trim() === "" || Number.isNaN(h) || h <= 0 || h > 1) e.hold_max = "Enter a number above 0 and up to 1.";
  if (!e.approve_max && !e.hold_max && a >= h) e.hold_max = "Hold threshold must be higher than the approve threshold.";
  if (f.high_amount.trim() === "" || Number.isNaN(amt) || amt <= 0) e.high_amount = "Enter an amount greater than 0.";
  if (!Number.isInteger(v) || v < 1 || v > 1000) e.velocity_limit = "Enter a whole number from 1 to 1000.";
  const bad = f.blocked_countries.split(",").map((c) => c.trim()).filter(Boolean).filter((c) => !/^[A-Za-z]{2}$/.test(c));
  if (bad.length) e.blocked_countries = `Use two-letter codes separated by commas (invalid: ${bad.slice(0, 3).join(", ")}).`;
  return e;
}

export default function Rules() {
  const { isAdmin } = useAuth();
  const toast = useToast();
  const { data, error, loading, reload } = useAsync(() => api.get<RulesT>("/api/rules"), []);
  const [f, setF] = useState<Record<keyof RiskConfig, string> | null>(null);
  const [serverErr, setServerErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (data) setF({ approve_max: String(data.config.approve_max), hold_max: String(data.config.hold_max), high_amount: String(data.config.high_amount), blocked_countries: data.config.blocked_countries, velocity_limit: String(data.config.velocity_limit) }); }, [data]);
  if (loading && !data) return <Loading />;
  if (error && !data) return <ErrorState message={error.message} onRetry={reload} />;
  if (!data || !f) return null;
  const local = validate(f), server = fieldErrors(serverErr);
  const errs = { ...server, ...local };
  const submit = async (e: FormEvent) => {
    e.preventDefault(); setServerErr(null);
    if (Object.keys(local).length) return;
    setBusy(true);
    try {
      await api.put("/api/config", { approve_max: Number(f.approve_max), hold_max: Number(f.hold_max), high_amount: Number(f.high_amount), blocked_countries: f.blocked_countries, velocity_limit: Number(f.velocity_limit) });
      toast("Configuration saved. New transactions use these values."); reload();
    } catch (x) { setServerErr(x); } finally { setBusy(false); }
  };
  const set = (k: keyof RiskConfig) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  const general = serverErr && Object.keys(server).length === 0 ? errMsg(serverErr) : null;
  return (
    <>
      <PageHead title="Fraud rules" sub={<>Scorer: <code>{data.scorer}</code>. A transparent rule baseline, not a trained model.</>} />
      {!isAdmin && <div className="banner warn">Only administrators can change these values.</div>}
      <div className="grid g-eq2">
        <form className="card" onSubmit={submit} noValidate>
          <h2>Thresholds and limits</h2>
          <div className="form-grid">
            <Field label="Approve up to score" hint="Scores at or below this are approved." error={errs.approve_max}><input value={f.approve_max} onChange={set("approve_max")} disabled={!isAdmin} aria-invalid={!!errs.approve_max} inputMode="decimal" /></Field>
            <Field label="Hold up to score" hint="Above approve, up to here: held. Above: declined." error={errs.hold_max}><input value={f.hold_max} onChange={set("hold_max")} disabled={!isAdmin} aria-invalid={!!errs.hold_max} inputMode="decimal" /></Field>
            <Field label="High amount (USD)" hint="Amounts strictly above this add risk." error={errs.high_amount}><input value={f.high_amount} onChange={set("high_amount")} disabled={!isAdmin} aria-invalid={!!errs.high_amount} inputMode="decimal" /></Field>
            <Field label="Velocity limit" hint="Earlier transactions on a token in 24h." error={errs.velocity_limit}><input value={f.velocity_limit} onChange={set("velocity_limit")} disabled={!isAdmin} aria-invalid={!!errs.velocity_limit} inputMode="numeric" /></Field>
            <div className="full"><Field label="Blocked countries" hint="Comma-separated two-letter codes, e.g. XX,RU" error={errs.blocked_countries}><input value={f.blocked_countries} onChange={set("blocked_countries")} disabled={!isAdmin} aria-invalid={!!errs.blocked_countries} /></Field></div>
          </div>
          {general && <p className="field-err" role="alert">{general}</p>}
          {isAdmin && <div className="btn-row mt"><button className="btn primary" disabled={busy || Object.keys(local).length > 0}>{busy ? "Saving…" : "Save changes"}</button><button type="button" className="btn" onClick={reload}>Reset</button></div>}
        </form>
        <div className="card">
          <h2>How a score is built</h2>
          <div className="table-wrap"><table><thead><tr><th>Factor</th><th className="num">Points</th><th>Applies when</th></tr></thead>
            <tbody>{data.factors.map((x) => <tr key={x.code}><td>{x.label}</td><td className="num">+{x.points.toFixed(2)}</td><td className="wrap">{x.applies_when}</td></tr>)}</tbody></table></div>
          <p className="muted">{data.decision_rule} Factor weights are fixed in code; only the values on the left are configurable.</p>
        </div>
      </div>
    </>
  );
}
