import { FormEvent, useState } from "react";
import { api } from "../api/client";
import type { Health } from "../api/types";
import { OtpChallenge, useAuth } from "../auth";
import { useAsync, errMsg } from "../lib";

export default function Login() {
  const { login, verifyOtp } = useAuth();
  const { data: health } = useAsync(() => api.get<Health>("/api/health"), []);
  const [email, setEmail] = useState(""), [password, setPassword] = useState(""), [code, setCode] = useState("");
  const [challenge, setChallenge] = useState<OtpChallenge | null>(null);
  const [err, setErr] = useState<string | null>(null), [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault(); setBusy(true); setErr(null);
    try {
      if (challenge) await verifyOtp(challenge.challenge_id, code);
      else setChallenge(await login(email, password));
    } catch (x) { setErr(errMsg(x)); } finally { setBusy(false); }
  };
  return (
    <main className="login">
      <form className="card" onSubmit={submit}>
        <h1>Fraud Desk</h1>
        {!challenge ? (
          <>
            <p className="muted">Sign in with your work e-mail. Accounts are created by an administrator.</p>
            <div className="grid">
              <label className="f">E-mail<input type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required autoFocus /></label>
              <label className="f">Password<input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required /></label>
            </div>
          </>
        ) : (
          <>
            <p className="muted">We sent a 6-digit code to <strong>{challenge.email_hint}</strong>. It expires in {Math.round(challenge.expires_in / 60)} minutes.
              {health?.otp_delivery === "console" && " (Development mode: the code is printed in the server terminal.)"}</p>
            <label className="f">Sign-in code<input inputMode="numeric" pattern="\d{6}" maxLength={6} autoComplete="one-time-code" value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} required autoFocus /></label>
          </>
        )}
        {err && <p className="field-err" role="alert">{err}</p>}
        <div className="btn-row mt">
          <button className="btn primary" disabled={busy || (challenge ? code.length !== 6 : !email || !password)}>{busy ? "Please wait…" : challenge ? "Verify and sign in" : "Continue"}</button>
          {challenge && <button type="button" className="btn" onClick={() => { setChallenge(null); setCode(""); setErr(null); }}>Back</button>}
        </div>
      </form>
    </main>
  );
}
