import { FormEvent, useState } from "react";
import { useAuth } from "../auth";
import { errMsg } from "../lib";

export default function Login() {
  const { login } = useAuth();
  const [u, setU] = useState(""), [p, setP] = useState("");
  const [err, setErr] = useState<string | null>(null), [busy, setBusy] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault(); setBusy(true); setErr(null);
    try { await login(u, p); } catch (x) { setErr(errMsg(x)); } finally { setBusy(false); }
  };
  return (
    <main className="login">
      <form className="card" onSubmit={submit}>
        <h1>Fraud Desk</h1><p className="muted">Sign in to review transactions. Accounts are created by an administrator with <code>python -m app.cli create-user</code>.</p>
        <div className="grid">
          <label className="f">Username<input autoComplete="username" value={u} onChange={(e) => setU(e.target.value)} required autoFocus /></label>
          <label className="f">Password<input type="password" autoComplete="current-password" value={p} onChange={(e) => setP(e.target.value)} required /></label>
        </div>
        {err && <p className="field-err" role="alert">{err}</p>}
        <div className="btn-row mt"><button className="btn primary" disabled={busy || !u || !p}>{busy ? "Signing in…" : "Sign in"}</button></div>
      </form>
    </main>
  );
}
