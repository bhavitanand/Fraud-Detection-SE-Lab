import { FormEvent, useState } from "react";
import { api, fieldErrors } from "../api/client";
import type { Role, UserRow } from "../api/types";
import { useAuth } from "../auth";
import { Badge, ConfirmDialog, Empty, ErrorState, Field, Loading, Modal, PageHead, useToast } from "../components/ui";
import { errMsg, useAsync } from "../lib";

export default function Users() {
  const { me, isAdmin } = useAuth();
  const toast = useToast();
  const { data, error, loading, reload } = useAsync(() => (isAdmin ? api.get<UserRow[]>("/api/users") : Promise.resolve([] as UserRow[])), [isAdmin]);
  const [adding, setAdding] = useState(false);
  const [reset, setReset] = useState<UserRow | null>(null);
  const [toggle, setToggle] = useState<UserRow | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  if (!isAdmin) return <><PageHead title="Users" /><div className="banner warn">Only administrators can manage users.</div></>;
  if (loading && !data) return <Loading />;
  if (error && !data) return <ErrorState message={error.message} onRetry={reload} />;

  const patch = async (u: UserRow, body: Record<string, unknown>, done: string) => {
    setBusy(true); setErr(null);
    try { await api.patch(`/api/users/${encodeURIComponent(u.email)}`, body); toast(done); setToggle(null); reload(); } catch (e) { setErr(errMsg(e)); } finally { setBusy(false); }
  };
  return (
    <>
      <PageHead title="Users" sub="Analysts and administrators. The e-mail address is the sign-in name."><button className="btn primary" onClick={() => setAdding(true)}>Add user</button></PageHead>
      {data && data.length === 0 ? <Empty>No users yet.</Empty> : (
        <div className="table-wrap"><table><thead><tr><th>Name</th><th>E-mail</th><th>Role</th><th>Status</th><th /></tr></thead>
          <tbody>{data?.map((u) => (
            <tr key={u.email}><td>{u.name ?? "—"}</td><td className="mono">{u.email}{u.email === me?.email ? " (you)" : ""}</td>
              <td>
                <select aria-label={`Role for ${u.email}`} value={u.role} onChange={(e) => void patch(u, { role: e.target.value as Role }, `Role updated for ${u.email}`).catch(() => undefined)} disabled={busy}>
                  <option value="analyst">Analyst</option><option value="admin">Administrator</option>
                </select>
              </td>
              <td>{u.disabled ? <Badge tone="red">Disabled</Badge> : <Badge tone="green">Active</Badge>}</td>
              <td><div className="btn-row"><button className="btn small" onClick={() => { setErr(null); setReset(u); }}>Reset password</button>
                <button className="btn small" onClick={() => { setErr(null); setToggle(u); }}>{u.disabled ? "Enable" : "Disable"}</button></div></td></tr>))}</tbody></table></div>
      )}
      {err && !toggle && !reset && <div className="banner err" role="alert">{err}</div>}
      {adding && <AddUser onClose={() => setAdding(false)} onDone={() => { setAdding(false); reload(); toast("User created."); }} />}
      {reset && <ResetPassword user={reset} onClose={() => setReset(null)} onDone={() => { setReset(null); toast("Password reset."); }} />}
      {toggle && <ConfirmDialog title={`${toggle.disabled ? "Enable" : "Disable"} ${toggle.email}?`} danger={!toggle.disabled} confirmLabel={toggle.disabled ? "Enable" : "Disable"} busy={busy} error={err}
        body={<p>{toggle.disabled ? "They will be able to sign in again." : "They are signed out immediately and cannot sign in until re-enabled."}</p>} onCancel={() => setToggle(null)}
        onConfirm={() => void patch(toggle, { disabled: !toggle.disabled }, `${toggle.email} ${toggle.disabled ? "enabled" : "disabled"}`)} />}
    </>
  );
}

function AddUser({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [f, setF] = useState({ email: "", name: "", role: "analyst", password: "" });
  const [err, setErr] = useState<unknown>(null), [busy, setBusy] = useState(false);
  const fe = fieldErrors(err);
  const set = (k: string) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  const submit = async (e: FormEvent) => { e.preventDefault(); setBusy(true); setErr(null); try { await api.post("/api/users", f); onDone(); } catch (x) { setErr(x); } finally { setBusy(false); } };
  return (
    <Modal title="Add user" onClose={onClose}>
      <form onSubmit={submit} noValidate>
        <div className="form-grid">
          <Field label="Full name" error={fe.name}><input value={f.name} onChange={set("name")} /></Field>
          <Field label="E-mail" error={fe.email}><input type="email" value={f.email} onChange={set("email")} /></Field>
          <Field label="Role"><select value={f.role} onChange={set("role")}><option value="analyst">Analyst</option><option value="admin">Administrator</option></select></Field>
          <Field label="Initial password" hint="At least 10 characters. Share it securely; the user can change it." error={fe.password}><input type="password" autoComplete="new-password" value={f.password} onChange={set("password")} /></Field>
        </div>
        {!!err && Object.keys(fe).length === 0 && <p className="field-err" role="alert">{errMsg(err)}</p>}
        <div className="btn-row"><button type="button" className="btn" onClick={onClose}>Cancel</button><button className="btn primary" disabled={busy}>{busy ? "Creating…" : "Create user"}</button></div>
      </form>
    </Modal>
  );
}

function ResetPassword({ user, onClose, onDone }: { user: UserRow; onClose: () => void; onDone: () => void }) {
  const [pw, setPw] = useState(""), [err, setErr] = useState<string | null>(null), [busy, setBusy] = useState(false);
  const submit = async (e: FormEvent) => { e.preventDefault(); setBusy(true); setErr(null); try { await api.put(`/api/users/${encodeURIComponent(user.email)}/password`, { new_password: pw }); onDone(); } catch (x) { setErr(errMsg(x)); } finally { setBusy(false); } };
  return (
    <Modal title={`Reset password for ${user.email}`} onClose={onClose}>
      <form onSubmit={submit}><Field label="New password" hint="At least 10 characters."><input type="password" autoComplete="new-password" value={pw} onChange={(e) => setPw(e.target.value)} /></Field>
        {err && <p className="field-err" role="alert">{err}</p>}
        <div className="btn-row"><button type="button" className="btn" onClick={onClose}>Cancel</button><button className="btn primary" disabled={busy || pw.length < 10}>Reset password</button></div></form>
    </Modal>
  );
}
