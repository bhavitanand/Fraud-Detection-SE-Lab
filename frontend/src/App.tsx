import { NavLink, Navigate, Outlet, Route, Routes } from "react-router-dom";
import { api } from "./api/client";
import type { Transaction, Page } from "./api/types";
import { AuthProvider, useAuth } from "./auth";
import { ErrorState, Loading, ToastProvider } from "./components/ui";
import { useAsync } from "./lib";
import Alerts from "./pages/Alerts";
import Audit from "./pages/Audit";
import Cards from "./pages/Cards";
import Login from "./pages/Login";
import Overview from "./pages/Overview";
import Reports from "./pages/Reports";
import Rules from "./pages/Rules";
import TransactionDetail from "./pages/TransactionDetail";
import Transactions from "./pages/Transactions";

function Shell() {
  const { me, logout } = useAuth();
  const { data } = useAsync(() => api.get<Page<Transaction>>("/api/transactions", { review: "OPEN", page_size: 1 }), []);
  const links: [string, string][] = [["/", "Overview"], ["/transactions", "Transactions"], ["/alerts", "Alerts and cases"], ["/cards", "Cards"], ["/rules", "Fraud rules"], ["/reports", "Reports"], ["/audit", "Audit log"]];
  return (
    <div className="shell">
      <a className="skip" href="#main">Skip to content</a>
      <aside className="side">
        <div className="brand">Fraud Desk<small>Synthetic-data demonstrator</small></div>
        <nav className="nav" aria-label="Primary">
          {links.map(([to, text]) => <NavLink key={to} to={to} end={to === "/"}>{text}{to === "/alerts" && data && data.total > 0 ? <span className="count" aria-label={`${data.total} open`}>{data.total}</span> : null}</NavLink>)}
        </nav>
        <div className="side-foot">{me?.username} · {me?.role}{me?.auth_required ? <> · <button className="btn small" onClick={logout}>Sign out</button></> : <><br />Local demo mode (no sign-in)</>}</div>
      </aside>
      <main className="main" id="main"><Outlet /></main>
    </div>
  );
}

function Gate() {
  const { status, error } = useAuth();
  if (status === "loading") return <Loading text="Connecting…" />;
  if (status === "down") return <ErrorState message={`Cannot load the application: ${error}`} onRetry={() => window.location.reload()} />;
  if (status === "anon") return <Login />;
  return (
    <Routes>
      <Route element={<Shell />}>
        <Route index element={<Overview />} />
        <Route path="transactions" element={<Transactions />} />
        <Route path="transactions/:id" element={<TransactionDetail />} />
        <Route path="alerts" element={<Alerts />} />
        <Route path="cards" element={<Cards />} />
        <Route path="rules" element={<Rules />} />
        <Route path="reports" element={<Reports />} />
        <Route path="audit" element={<Audit />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}

export default function App() {
  return <AuthProvider><ToastProvider><Gate /></ToastProvider></AuthProvider>;
}
