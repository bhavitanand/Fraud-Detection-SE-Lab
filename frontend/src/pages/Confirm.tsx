import { useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../api/client";
import type { ConfirmInfo } from "../api/types";
import { ErrorState, Loading } from "../components/ui";
import { errMsg, fmtMoney, fmtTime, useAsync } from "../lib";

/** Public cardholder page (no sign-in). The long random token in the URL is the only credential. */
export default function Confirm() {
  const { token = "" } = useParams();
  const { data, error, loading, reload } = useAsync(() => api.get<ConfirmInfo>(`/api/public/confirm/${encodeURIComponent(token)}`), [token]);
  const [done, setDone] = useState<{ reply: string; blocked: boolean } | null>(null);
  const [err, setErr] = useState<string | null>(null), [busy, setBusy] = useState(false);
  const send = async (reply: "LEGIT" | "NOT_ME") => {
    setBusy(true); setErr(null);
    try { const r = await api.post<{ card_blocked: boolean }>(`/api/public/confirm/${encodeURIComponent(token)}`, { reply }); setDone({ reply, blocked: r.card_blocked }); } catch (e) { setErr(errMsg(e)); } finally { setBusy(false); }
  };
  return (
    <main className="login">
      <div className="card" style={{ width: "min(440px,100%)" }}>
        <h1>Was this you?</h1>
        {loading && !data ? <Loading /> : error ? <ErrorState message={error.message} onRetry={error.status === 404 ? undefined : reload} /> : data && (
          done || data.already_replied ? (
            <div className={`banner ${(done?.reply ?? data.reply) === "NOT_ME" ? "warn" : "ok"}`} role="status">
              {(done?.reply ?? data.reply) === "NOT_ME" ? "Thank you. We have blocked this card as a precaution and our team will contact you." : "Thank you. We have recorded that this payment was yours."}
            </div>
          ) : (
            <>
              <p>A payment on your card ending <strong>{data.card_last4}</strong> was flagged:</p>
              <dl className="dl"><dt>Amount</dt><dd>{fmtMoney(data.amount, data.currency)}</dd><dt>Merchant</dt><dd>{data.merchant}</dd>{data.location && <><dt>Place</dt><dd>{data.location}</dd></>}<dt>Time</dt><dd>{fmtTime(data.created)}</dd></dl>
              {err && <p className="field-err" role="alert">{err}</p>}
              <div className="btn-row mt"><button className="btn primary" disabled={busy} onClick={() => void send("LEGIT")}>Yes, this was me</button><button className="btn danger" disabled={busy} onClick={() => void send("NOT_ME")}>No, this was not me</button></div>
              <p className="muted" style={{ fontSize: 12 }}>Demonstration page with synthetic data. “Not me” blocks the card in this demo only.</p>
            </>
          )
        )}
      </div>
    </main>
  );
}
