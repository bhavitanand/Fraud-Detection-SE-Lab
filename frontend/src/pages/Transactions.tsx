import { FormEvent, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, ApiError, fieldErrors } from "../api/client";
import type { Page, Transaction } from "../api/types";
import { DecisionBadge, Empty, ErrorState, Field, Loading, Modal, PageHead, Pager, ReviewBadge, Score, SourceBadge, useToast } from "../components/ui";
import { errMsg, fmtMoney, fmtTime, useAsync } from "../lib";

const COLS: [string, string, boolean?][] = [["id", "ID"], ["created", "Time"], ["token", "Token"], ["merchant", "Merchant"], ["amount", "Amount", true], ["score", "Score"], ["decision", "Decision"]];

export default function Transactions() {
  const [sp, setSp] = useSearchParams();
  const [showNew, setShowNew] = useState(false);
  const p = Object.fromEntries(sp.entries());
  const sort = p.sort ?? "id", order = p.order ?? "desc", page = Number(p.page ?? 1) || 1;
  const { data, error, loading, reload } = useAsync(() => api.get<Page<Transaction>>("/api/transactions", { ...p, sort, order, page, page_size: 20 }), [sp.toString()]);
  const set = (k: string, v: string) => { const n = new URLSearchParams(sp); if (v) n.set(k, v); else n.delete(k); if (k !== "page") n.delete("page"); setSp(n, { replace: true }); };
  const toggleSort = (c: string) => { const n = new URLSearchParams(sp); n.set("sort", c); n.set("order", sort === c && order === "desc" ? "asc" : "desc"); n.delete("page"); setSp(n, { replace: true }); };

  return (
    <>
      <PageHead title="Transactions" sub="Search, filter and open any scored transaction."><button className="btn primary" onClick={() => setShowNew(true)}>Submit synthetic transaction</button></PageHead>
      <div className="filters" role="search">
        <Field label="Search"><input aria-label="Search" placeholder="Token, merchant or #id" value={p.q ?? ""} onChange={(e) => set("q", e.target.value)} /></Field>
        <Field label="Decision"><select value={p.decision ?? ""} onChange={(e) => set("decision", e.target.value)}><option value="">All</option><option>APPROVE</option><option>HOLD</option><option>DECLINE</option></select></Field>
        <Field label="Review"><select value={p.review ?? ""} onChange={(e) => set("review", e.target.value)}><option value="">All</option><option value="OPEN">Open</option><option value="CONFIRMED_FRAUD">Confirmed fraud</option><option value="FALSE_POSITIVE">False positive</option><option value="NOT_REQUIRED">No alert</option></select></Field>
        <Field label="Channel"><select value={p.channel ?? ""} onChange={(e) => set("channel", e.target.value)}><option value="">All</option><option>POS</option><option>ONLINE</option><option>ATM</option><option>WALLET</option></select></Field>
        <Field label="Source"><select value={p.source ?? ""} onChange={(e) => set("source", e.target.value)}><option value="">All</option><option value="LIVE">Live</option><option value="SEED">Demo seed</option></select></Field>
        <Field label="Min score"><input type="number" min={0} max={1} step={0.05} style={{ width: 80 }} value={p.min_score ?? ""} onChange={(e) => set("min_score", e.target.value)} /></Field>
        {sp.toString() && <button className="btn" onClick={() => setSp({}, { replace: true })}>Clear filters</button>}
      </div>
      {loading && !data ? <Loading /> : error && !data ? <ErrorState message={error.message} onRetry={reload} /> : data && (
        <>
          {error && <div className="banner err" role="alert">{error.message} Showing the last loaded results.</div>}
          <div className="table-wrap" aria-busy={loading}>
            <table>
              <thead><tr>
                {COLS.map(([c, text, num]) => <th key={c} className={num ? "num" : ""} aria-sort={sort === c ? (order === "asc" ? "ascending" : "descending") : "none"}><button onClick={() => toggleSort(c)}>{text}{sort === c ? (order === "asc" ? " ▲" : " ▼") : ""}</button></th>)}
                <th>Review</th><th>Source</th>
              </tr></thead>
              <tbody>{data.items.map((t) => (
                <tr key={t.id}>
                  <td><Link to={`/transactions/${t.id}`}>#{t.id}</Link></td><td>{fmtTime(t.created)}</td><td className="mono">{t.token}</td><td>{t.merchant}</td>
                  <td className="num">{fmtMoney(t.amount)}</td><td><Score value={t.score} /></td><td><DecisionBadge d={t.decision} /></td><td><ReviewBadge r={t.review} /></td><td><SourceBadge s={t.source} /></td>
                </tr>))}</tbody>
            </table>
            {data.items.length === 0 && <Empty>No transactions match these filters.</Empty>}
          </div>
          <Pager page={data.page} pages={data.pages} total={data.total} onPage={(n) => set("page", String(n))} />
        </>
      )}
      {showNew && <NewTransaction onClose={() => setShowNew(false)} onDone={() => { setShowNew(false); reload(); }} />}
    </>
  );
}

function NewTransaction({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const toast = useToast();
  const [f, setF] = useState({ card_token: "SYNTH-DEMO-0001", amount: "250", merchant: "Demo Merchant", country: "US", channel: "ONLINE" });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const fe = fieldErrors(err);
  const set = (k: string) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  const submit = async (e: FormEvent) => {
    e.preventDefault(); setBusy(true); setErr(null);
    try {
      const r = await api.post<{ id: number; decision: string; score: number }>("/api/transactions", { ...f, amount: Number(f.amount) });
      toast(`Scored #${r.id}: ${r.decision} (${r.score.toFixed(2)})`); onDone();
    } catch (x) { setErr(x); } finally { setBusy(false); }
  };
  const general = err && Object.keys(fe).length === 0 ? errMsg(err) : null;
  return (
    <Modal title="Submit synthetic transaction" onClose={onClose}>
      <p className="muted">Use synthetic tokens only. Never enter a real card number; those are rejected.</p>
      <form onSubmit={submit} noValidate>
        <div className="form-grid">
          <Field label="Card token" error={fe.card_token}><input value={f.card_token} onChange={set("card_token")} aria-invalid={!!fe.card_token} /></Field>
          <Field label="Amount (USD)" error={fe.amount}><input inputMode="decimal" value={f.amount} onChange={set("amount")} aria-invalid={!!fe.amount} /></Field>
          <Field label="Merchant" error={fe.merchant}><input value={f.merchant} onChange={set("merchant")} aria-invalid={!!fe.merchant} /></Field>
          <Field label="Country (2 letters)" error={fe.country}><input value={f.country} maxLength={2} onChange={set("country")} aria-invalid={!!fe.country} /></Field>
          <Field label="Channel"><select value={f.channel} onChange={set("channel")}><option>POS</option><option>ONLINE</option><option>ATM</option><option>WALLET</option></select></Field>
        </div>
        {general && <p className="field-err" role="alert">{general}{err instanceof ApiError && err.code === "card_blocked" ? " Unblock it on the Cards page (admin) to continue." : ""}</p>}
        <div className="btn-row"><button type="button" className="btn" onClick={onClose}>Cancel</button><button className="btn primary" disabled={busy}>{busy ? "Scoring…" : "Score transaction"}</button></div>
      </form>
    </Modal>
  );
}
