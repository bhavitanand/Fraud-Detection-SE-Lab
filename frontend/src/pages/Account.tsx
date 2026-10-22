import { FormEvent, useState } from "react";
import { api } from "../api/client";
import { useAuth } from "../auth";
import { Field, PageHead, useToast } from "../components/ui";
import { errMsg } from "../lib";

export default function Account() {
  const { me } = useAuth();
  const toast = useToast();
  const [cur, setCur] = useState(""), [pw, setPw] = useState(""), [pw2, setPw2] = useState("");
  const [err, setErr] = useState<string | null>(null), [busy, setBusy] = useState(false);
  const mismatch = pw2 !== "" && pw !== pw2;
  const submit = async (e: FormEvent) => {
    e.preventDefault(); setBusy(true); setErr(null);
    try { await api.put("/api/auth/password", { current_password: cur, new_password: pw }); toast("Password changed."); setCur(""); setPw(""); setPw2(""); } catch (x) { setErr(errMsg(x)); } finally { setBusy(false); }
  };
  return (
    <>
      <PageHead title="Account" sub={<>{me?.name ?? me?.email} · {me?.email} · {me?.role}</>} />
      {!me?.auth_required ? <div className="banner">Local no-login mode: there is no password to change.</div> : (
        <form className="card" style={{ maxWidth: 420 }} onSubmit={submit}>
          <h2>Change password</h2>
          <div className="grid">
            <Field label="Current password"><input type="password" autoComplete="current-password" value={cur} onChange={(e) => setCur(e.target.value)} /></Field>
            <Field label="New password" hint="At least 10 characters."><input type="password" autoComplete="new-password" value={pw} onChange={(e) => setPw(e.target.value)} /></Field>
            <Field label="Repeat new password" error={mismatch ? "Passwords do not match." : undefined}><input type="password" autoComplete="new-password" value={pw2} onChange={(e) => setPw2(e.target.value)} /></Field>
          </div>
          {err && <p className="field-err" role="alert">{err}</p>}
          <div className="btn-row mt"><button className="btn primary" disabled={busy || !cur || pw.length < 10 || mismatch || !pw2}>{busy ? "Saving…" : "Change password"}</button></div>
        </form>
      )}
    </>
  );
}
