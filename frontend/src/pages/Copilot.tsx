import { useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { CopilotChat } from "../api/types";
import { Badge, DecisionBadge, ReviewBadge, Score } from "../components/ui";
import { errMsg, fmtMoney, fmtTime, useAsync } from "../lib";

const EXAMPLES = ["Show declined orders above ₹50,000 in Mumbai", "Open alerts online above 20k", "Held transactions at Amazon India", "Confirmed fraud in Delhi", "Anything with score over 0.9"];

interface Turn { q: string; res?: CopilotChat; error?: string }

export default function Copilot() {
  const { data: st } = useAsync(() => api.get<{ provider: string; model: string; note: string }>("/api/copilot/status"), []);
  const [text, setText] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);
  const end = useRef<HTMLDivElement>(null);

  const ask = async (q: string) => {
    q = q.trim();
    if (q.length < 2 || busy) return;
    setBusy(true); setText("");
    setTurns((t) => [...t, { q }]);
    try {
      const res = await api.post<CopilotChat>("/api/copilot/chat", { question: q });
      setTurns((t) => t.map((x, i) => (i === t.length - 1 ? { ...x, res } : x)));
    } catch (e) { setTurns((t) => t.map((x, i) => (i === t.length - 1 ? { ...x, error: errMsg(e) } : x))); }
    finally { setBusy(false); setTimeout(() => end.current?.scrollIntoView({ behavior: "smooth" }), 50); }
  };

  return (
    <>
      <div className="page-head"><div><h1>AI copilot</h1><p>Ask questions about your transactions in plain English. The question becomes a validated filter, never raw SQL.</p></div>
        {st && <Badge tone={st.provider === "gemini" ? "green" : "gray"}>{st.provider === "gemini" ? `Gemini · ${st.model}` : "Offline engine"}</Badge>}</div>
      {st && <div className="banner">{st.note}</div>}
      <div className="btn-row" style={{ marginBottom: 12 }}>{EXAMPLES.map((e) => <button key={e} className="btn small" onClick={() => void ask(e)} disabled={busy}>{e}</button>)}</div>
      <div style={{ display: "grid", gap: 12 }}>
        {turns.map((t, i) => (
          <div key={i} className="card">
            <p style={{ margin: "0 0 8px", fontWeight: 600 }}>{t.q}</p>
            {t.error && <p className="field-err" role="alert">{t.error}</p>}
            {!t.res && !t.error && <p className="muted">Thinking…</p>}
            {t.res && (
              <>
                <p style={{ margin: "0 0 8px" }}>{t.res.answer}</p>
                <p className="muted" style={{ fontSize: 12, margin: "0 0 8px" }}>Filter used: <code>{JSON.stringify(t.res.filter)}</code> · {t.res.provider === "gemini" ? "interpreted by Gemini" : "interpreted offline"}</p>
                {t.res.rows.length > 0 && (
                  <div className="table-wrap"><table><thead><tr><th>ID</th><th>Time</th><th>Merchant</th><th>City</th><th className="num">Amount</th><th>Score</th><th>Decision</th><th>Review</th></tr></thead>
                    <tbody>{t.res.rows.map((r) => <tr key={r.id}><td><Link to={`/transactions/${r.id}`}>#{r.id}</Link></td><td>{fmtTime(r.created)}</td><td>{r.merchant}</td><td>{r.location ?? "—"}</td>
                      <td className="num">{fmtMoney(r.amount, r.currency)}</td><td><Score value={r.score} /></td><td><DecisionBadge d={r.decision} /></td><td><ReviewBadge r={r.review} /></td></tr>)}</tbody></table></div>)}
              </>)}
          </div>))}
        <div ref={end} />
      </div>
      <form className="btn-row" style={{ marginTop: 12 }} onSubmit={(e) => { e.preventDefault(); void ask(text); }}>
        <input style={{ flex: 1, minWidth: 240 }} value={text} maxLength={300} onChange={(e) => setText(e.target.value)} placeholder="e.g. show declined orders above ₹50,000 in Mumbai" aria-label="Ask a question" />
        <button className="btn primary" disabled={busy || text.trim().length < 2}>Ask</button>
      </form>
    </>
  );
}
