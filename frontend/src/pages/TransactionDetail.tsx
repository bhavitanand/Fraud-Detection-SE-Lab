import { useState } from "react";
import { useAuth } from "../auth";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { ReviewResult, TransactionDetail as TD } from "../api/types";
import { Badge, ConfirmDialog, DecisionBadge, ErrorState, Field, Loading, PageHead, ReviewBadge, Score, SourceBadge, useToast } from "../components/ui";
import { errMsg, fmtMoney, fmtTime, label, useAsync } from "../lib";
import { AuditList } from "./Audit";

export default function TransactionDetail() {
  const { id } = useParams();
  const nav = useNavigate();
  const toast = useToast();
  const { me } = useAuth();
  const { data: t, error, loading, reload } = useAsync(() => api.get<TD>(`/api/transactions/${id}`), [id]);
  const [verdict, setVerdict] = useState<"CONFIRMED_FRAUD" | "FALSE_POSITIVE" | "">("");
  const [note, setNote] = useState("");
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [actionErr, setActionErr] = useState<string | null>(null);
  const [outcome, setOutcome] = useState<ReviewResult | null>(null);

  if (loading && !t) return <Loading />;
  if (error && !t) return <ErrorState message={error.status === 404 ? "This transaction does not exist." : error.message} onRetry={error.status === 404 ? undefined : reload} />;
  if (!t) return null;

  const submit = async () => {
    setBusy(true); setActionErr(null);
    try {
      const r = await api.post<ReviewResult>(`/api/alerts/${t.id}/review`, { verdict, note: note.trim() || undefined });
      setOutcome(r); setConfirm(false); toast(`Verdict recorded: ${label(r.verdict)}`); reload();
    } catch (e) { setActionErr(errMsg(e)); } finally { setBusy(false); }
  };
  const open = t.has_alert && t.review === "OPEN";
  const assign = async (assignee: string | null) => {
    try { await api.post(`/api/alerts/${t.id}/assign`, { assignee }); toast(assignee ? `Assigned to ${assignee}` : "Alert unassigned"); reload(); } catch (e) { toast(errMsg(e), true); }
  };

  return (
    <>
      <PageHead title={`Transaction #${t.id}`} sub={<>Scored {fmtTime(t.created)} by <code>{t.scorer}</code></>}>
        <button className="btn" onClick={() => nav(-1)}>Back</button><Link className="btn" to="/transactions">All transactions</Link>
      </PageHead>
      {outcome && (
        <div className={`banner ${outcome.card_blocked ? "warn" : "ok"}`} role="status">
          Verdict <strong>{label(outcome.verdict)}</strong> recorded. {outcome.card_blocked ? <>Card token <code>{outcome.card_token}</code> is now blocked (local demo only).</> : outcome.card_currently_blocked ? <>No new block was applied; <code>{outcome.card_token}</code> is already blocked.</> : "The card token was not blocked."}
        </div>
      )}
      <div className="grid g-eq2">
        <div className="card">
          <h2>Details</h2>
          <dl className="dl">
            <dt>Decision</dt><dd><DecisionBadge d={t.decision} /> <ReviewBadge r={t.review} /> <SourceBadge s={t.source} /></dd>
            <dt>Risk score</dt><dd><Score value={t.score} /></dd>
            <dt>Amount</dt><dd>{fmtMoney(t.amount, t.currency)}</dd>
            <dt>Merchant</dt><dd>{t.merchant}{t.merchant_info?.category_label ? <span className="muted"> · {t.merchant_info.category_label} (MCC {t.merchant_info.category_code}), {t.merchant_info.risk_level.toLowerCase()} risk</span> : null}</dd>
            <dt>Place / channel</dt><dd>{t.location ? `${t.location}, ` : ""}{t.country} / {t.channel}</dd>
            {t.customer && <><dt>Cardholder</dt><dd>{t.customer.name} <span className="muted">· home {t.customer.city ?? "—"}{t.customer.state ? `, ${t.customer.state}` : ""}</span></dd></>}
            {t.card.issuer && <><dt>Card</dt><dd>{t.card.issuer} {t.card.card_network} {t.card.card_type?.toLowerCase()}{t.card.credit_limit ? ` · limit ${fmtMoney(t.card.credit_limit)}` : ""}</dd></>}
            {t.has_alert && <><dt>Assigned to</dt><dd>{t.assigned_to ?? <span className="muted">Unassigned</span>}{open && me && (t.assigned_to === me.email
              ? <> <button className="btn small" onClick={() => void assign(null)}>Unassign</button></>
              : <> <button className="btn small" onClick={() => void assign(me.email)}>Assign to me</button></>)}</dd></>}
            {t.cardholder_response && <><dt>Cardholder said</dt><dd>{t.cardholder_response === "NOT_ME" ? <Badge tone="red">Not me</Badge> : <Badge tone="green">This was me</Badge>}</dd></>}
            <dt>Card token</dt><dd><span className="mono">{t.token}</span> {t.card.blocked ? <Badge tone="red">Blocked</Badge> : <Badge tone="green">Active</Badge>} <Link to={`/cards?q=${t.token}`}>manage</Link></dd>
            {t.reviewed_at && <><dt>Reviewed</dt><dd>{fmtTime(t.reviewed_at)} by {t.reviewed_by}</dd></>}
            {t.review_note && <><dt>Analyst note</dt><dd>{t.review_note}</dd></>}
          </dl>
        </div>
        <div className="card">
          <h2>Why this score</h2>
          {t.factors.map((f) => (
            <div className="factor" key={f.code}><span>{f.label}</span><span className="num mono" style={{ textAlign: "right" }}>{f.points > 0 ? "+" : ""}{f.points.toFixed(2)}</span>
              <div className="track"><i style={{ width: `${Math.min(100, Math.abs(f.points) * 100)}%` }} /></div></div>
          ))}
          <p className="muted" style={{ marginBottom: 0 }}>Transparent rule-based baseline. Contributions add up to the score; this is not a trained model.</p>
        </div>
      </div>

      <div className="card mt">
        <h2>Analyst review</h2>
        {!t.has_alert ? <p className="muted">This transaction was approved, so no alert exists and no review is required.</p>
          : !open ? <p className="muted">Review completed: <ReviewBadge r={t.review} /> by {t.reviewed_by} on {fmtTime(t.reviewed_at)}. A recorded verdict is final.</p>
          : (
            <>
              <fieldset style={{ border: 0, padding: 0, margin: 0 }}>
                <legend className="sr-only">Verdict</legend>
                <div className="btn-row">
                  <label><input type="radio" name="v" checked={verdict === "CONFIRMED_FRAUD"} onChange={() => setVerdict("CONFIRMED_FRAUD")} /> Confirmed fraud <span className="muted">(blocks the card token)</span></label>
                  <label><input type="radio" name="v" checked={verdict === "FALSE_POSITIVE"} onChange={() => setVerdict("FALSE_POSITIVE")} /> False positive</label>
                </div>
              </fieldset>
              <div style={{ maxWidth: 520, margin: "10px 0" }}><Field label="Note (optional, max 500 characters)"><textarea rows={2} maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} /></Field></div>
              {actionErr && !confirm && <p className="field-err" role="alert">{actionErr}</p>}
              <button className="btn primary" disabled={!verdict} onClick={() => { setActionErr(null); setConfirm(true); }}>Record verdict…</button>
            </>
          )}
      </div>

      <div className="grid g-eq2 mt">
        <div className="card"><h2>Other activity on this token</h2>
          {t.token_history.length === 0 ? <p className="muted">No other transactions for this token.</p> : (
            <div className="table-wrap"><table><thead><tr><th>ID</th><th>Time</th><th className="num">Amount</th><th>Score</th><th>Decision</th></tr></thead>
              <tbody>{t.token_history.map((h) => <tr key={h.id}><td><Link to={`/transactions/${h.id}`}>#{h.id}</Link></td><td>{fmtTime(h.created)}</td><td className="num">{fmtMoney(h.amount, h.currency)}</td><td><Score value={h.score} /></td><td><DecisionBadge d={h.decision} /></td></tr>)}</tbody></table></div>)}
        </div>
        <div className="card"><h2>Audit trail</h2><AuditList items={t.audit} compact /></div>
      </div>

      {confirm && (
        <ConfirmDialog title={verdict === "CONFIRMED_FRAUD" ? "Confirm fraud and block card token?" : "Record false positive?"} danger={verdict === "CONFIRMED_FRAUD"}
          confirmLabel={verdict === "CONFIRMED_FRAUD" ? "Confirm fraud and block" : "Record false positive"} busy={busy} error={actionErr} onConfirm={submit} onCancel={() => setConfirm(false)}
          body={verdict === "CONFIRMED_FRAUD" ? <p>This marks transaction #{t.id} as fraud and blocks <code>{t.token}</code> in this demo application. The verdict cannot be changed afterwards.</p> : <p>This marks transaction #{t.id} as a false positive. The card token stays active. The verdict cannot be changed afterwards.</p>} />
      )}
    </>
  );
}
