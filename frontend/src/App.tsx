import { NavLink, Navigate, Outlet, Route, Routes, useLocation } from "react-router-dom";
import { api } from "./api/client";
import type { Page, Transaction } from "./api/types";
import { AuthProvider, useAuth } from "./auth";
import { ErrorBoundary, ErrorState, Loading, ToastProvider } from "./components/ui";
import { useAsync } from "./lib";
import Account from "./pages/Account";
import Alerts from "./pages/Alerts";
import Audit from "./pages/Audit";
import Cards from "./pages/Cards";
import Confirm from "./pages/Confirm";
import Login from "./pages/Login";
import Models from "./pages/Models";
import Outbox from "./pages/Outbox";
import Overview from "./pages/Overview";
import Reports from "./pages/Reports";
import Rules from "./pages/Rules";
import TransactionDetail from "./pages/TransactionDetail";
import Transactions from "./pages/Transactions";
import Users from "./pages/Users";

function Shell() {
  const { me, logout, isAdmin } = useAuth();
  const loc = useLocation();
  const { data } = useAsync(() => api.get<Page<Transaction>>("/api/transactions", { review: "OPEN", page_size: 1 }), [loc.pathname]);
  const links: [string, string][] = [["/", "Overview"], ["/transactions", "Transactions"], ["/alerts", "Alerts and cases"], ["/cards", "Cards"], ["/outbox", "Cardholder messages"],
    ["/rules", "Fraud rules"], ["/models", "ML model"], ["/reports", "Reports"], ["/audit", "Audit log"], ...(isAdmin ? [["/users", "Users"] as [string, string]] : [])];
  return (
    <div className="shell">
      <a className="skip" href="#main">Skip to content</a>
      <aside className="side">
        <div className="brand">Fraud Desk<small>India card-fraud demonstrator · synthetic data</small></div>
        <nav className="nav" aria-label="Primary">
          {links.map(([to, text]) => <NavLink key={to} to={to} end={to === "/"}>{text}{to === "/alerts" && data && data.total > 0 ? <span className="count" aria-label={`${data.total} open`}>{data.total}</span> : null}</NavLink>)}
        </nav>
        <div className="side-foot">
          <NavLink to="/account">{me?.name ?? me?.email}</NavLink> · {me?.role}
          {me?.auth_required ? <> · <button className="btn small" onClick={logout}>Sign out</button></> : <><br />Local demo mode (no sign-in)</>}
        </div>
      </aside>
      <main className="main" id="main"><ErrorBoundary key={loc.pathname}><Outlet /></ErrorBoundary></main>
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
        <Route path="outbox" element={<Outbox />} />
        <Route path="rules" element={<Rules />} />
        <Route path="models" element={<Models />} />
        <Route path="reports" element={<Reports />} />
        <Route path="audit" element={<Audit />} />
        <Route path="users" element={<Users />} />
        <Route path="account" element={<Account />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}

export default function App() {
  return (
    <ToastProvider>
      <Routes>
        <Route path="/confirm/:token" element={<Confirm />} />
        <Route path="*" element={<AuthProvider><Gate /></AuthProvider>} />
      </Routes>
    </ToastProvider>
  );
}
