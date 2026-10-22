import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import App from "./App";
import { session } from "./api/client";
import Confirm from "./pages/Confirm";
import Models from "./pages/Models";
import Users from "./pages/Users";
import { me, mockApi, renderAt } from "./test-utils";

afterEach(() => { vi.unstubAllGlobals(); session.clear(); });

describe("sign-in with e-mail and one-time code", () => {
  it("asks for the code after the password and then signs in", async () => {
    let signedIn = false;
    const calls = mockApi((url, init) => {
      if (url === "/api/auth/me") return signedIn ? { body: me("analyst") } : { status: 401, body: { error: { code: "unauthorized", message: "no" } } };
      if (url === "/api/health") return { body: { status: "ok", login_otp: true, otp_delivery: "console" } };
      if (url === "/api/auth/login") return { body: { otp_required: true, challenge_id: 5, email_hint: "an*@example.com", expires_in: 300 } };
      if (url === "/api/auth/otp" && init?.method === "POST") { signedIn = true; return { body: { access_token: "tok" } }; }
      if (url === "/api/reports") return { body: { transactions: 0, alert_count: 0, alert_backlog: 0, confirmed_fraud: 0, false_positives: 0, reviewed: 0, alert_rate: 0, confirmed_share: null, average_score: 0, fraud_rate: 0, false_positive_share: null, flagged_value_inr: 0, unassigned_open: 0, productivity: [], by_decision: {}, by_review: {}, by_channel: {}, by_source: {}, trend: [], recent_suspicious: [], range: {}, note: "", limitations: [] } };
      return { body: { items: [], total: 0, page: 1, page_size: 1, pages: 1 } };
    });
    render(<MemoryRouter><App /></MemoryRouter>);
    await userEvent.type(await screen.findByLabelText(/e-mail/i), "ana@example.com");
    await userEvent.type(screen.getByLabelText(/password/i), "secret-password");
    await userEvent.click(screen.getByRole("button", { name: /continue/i }));
    expect(await screen.findByText(/an\*@example.com/)).toBeInTheDocument();
    expect(screen.getByText(/printed in the server terminal/i)).toBeInTheDocument();
    const verify = screen.getByRole("button", { name: /verify and sign in/i });
    expect(verify).toBeDisabled();  // needs all six digits
    await userEvent.type(screen.getByLabelText(/sign-in code/i), "12ab3456");  // letters are dropped
    await userEvent.click(verify);
    await waitFor(() => expect(calls.find((c) => c.url === "/api/auth/otp")?.body).toEqual({ challenge_id: 5, code: "123456" }));
    expect(session.get()).toBe("tok");
  });

  it("shows the server's message for a wrong password", async () => {
    mockApi((url) => (url === "/api/auth/me" ? { status: 401, body: { error: { code: "unauthorized", message: "no" } } }
      : url === "/api/auth/login" ? { status: 401, body: { error: { code: "unauthorized", message: "Invalid email or password." } } } : { body: { login_otp: false } }));
    render(<MemoryRouter><App /></MemoryRouter>);
    await userEvent.type(await screen.findByLabelText(/e-mail/i), "ana@example.com");
    await userEvent.type(screen.getByLabelText(/password/i), "x");
    await userEvent.click(screen.getByRole("button", { name: /continue/i }));
    expect(await screen.findByText("Invalid email or password.")).toBeInTheDocument();
  });
});

describe("cardholder reply page", () => {
  const info = { amount: 90000, currency: "INR", merchant: "Tanishq", location: "Mumbai", created: "2026-10-01T10:00:00+00:00", card_last4: "1001", already_replied: false, reply: null };
  const renderConfirm = () => render(<MemoryRouter initialEntries={["/confirm/abcdefghij1234"]}><Routes><Route path="/confirm/:token" element={<Confirm />} /></Routes></MemoryRouter>);

  it("shows the payment in rupees and records a 'not me' reply without needing sign-in", async () => {
    const calls = mockApi((_url, init) => (init?.method === "POST" ? { body: { ok: true, reply: "NOT_ME", card_blocked: true } } : { body: info }));
    renderConfirm();
    expect(await screen.findByText(/₹90,000/)).toBeInTheDocument();
    expect(screen.getByText("1001")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /not me/i }));
    expect(await screen.findByText(/blocked this card as a precaution/i)).toBeInTheDocument();
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({ reply: "NOT_ME" });
  });

  it("shows an expired or invalid link as an error and an answered link as final", async () => {
    mockApi(() => ({ status: 404, body: { error: { code: "not_found", message: "This link is not valid." } } }));
    const { unmount } = renderConfirm();
    expect(await screen.findByText("This link is not valid.")).toBeInTheDocument();
    unmount(); vi.unstubAllGlobals();
    mockApi(() => ({ body: { ...info, already_replied: true, reply: "LEGIT" } }));
    renderConfirm();
    expect(await screen.findByText(/recorded that this payment was yours/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /not me/i })).toBeNull();
  });
});

describe("users page", () => {
  const users = [{ email: "boss@example.com", name: "Boss", role: "admin", disabled: false }, { email: "ana@example.com", name: "Ana", role: "analyst", disabled: false }];
  it("is closed to analysts", async () => {
    mockApi((url) => (url === "/api/auth/me" ? { body: me("analyst") } : { body: users }));
    renderAt(<Users />, "/users");
    expect(await screen.findByText(/only administrators can manage users/i)).toBeInTheDocument();
  });
  it("lets an administrator create a user and surfaces field errors", async () => {
    let created = false;
    const calls = mockApi((url, init) => {
      if (url === "/api/auth/me") return { body: me("admin") };
      if (url === "/api/users" && init?.method === "POST") return created ? { status: 201, body: {} } : (created = true, { status: 422, body: { error: { code: "validation_error", message: "bad", details: [{ field: "password", message: "String should have at least 10 characters" }] } } });
      return { body: users };
    });
    renderAt(<Users />, "/users");
    await userEvent.click(await screen.findByRole("button", { name: /add user/i }));
    const dlg = await screen.findByRole("dialog");
    await userEvent.type(within(dlg).getByLabelText(/full name/i), "New Person");
    await userEvent.type(within(dlg).getByLabelText(/^e-mail/i), "new@example.com");
    await userEvent.type(within(dlg).getByLabelText(/initial password/i), "short");
    await userEvent.click(within(dlg).getByRole("button", { name: /create user/i }));
    expect(await within(dlg).findByText(/at least 10 characters/i)).toBeInTheDocument();
    await userEvent.type(within(dlg).getByLabelText(/initial password/i), "-long-enough");
    await userEvent.click(within(dlg).getByRole("button", { name: /create user/i }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(2);
  });
});

describe("model page", () => {
  const model = {
    model_id: 1, name: "ulb_random_forest_v1", version: "v1", algorithm: "random_forest", status: "active", pr_auc: 0.78, precision_score: 0.85, recall_score: 0.77, f1_score: 0.81, trained_at: "2026-10-22T04:00:00+00:00",
    metrics: { sklearn: "1.5", limitations: ["Trained on 2013 European data in EUR, not Indian transactions."],
      dataset: { name: "ULB Credit Card Fraud Detection", rows_raw: 284807, duplicates_dropped: 1081, rows_used: 283726, frauds: 473, currency: "EUR", citation: "" },
      split: { method: "chronological 60/20/20", train: { rows: 1, frauds: 1 }, val: { rows: 1, frauds: 1 }, test: { rows: 56746, frauds: 74 } },
      metrics: { validation_pr_auc_by_candidate: { random_forest: 0.76 }, test: { pr_auc: 0.7817, roc_auc: 0.954, prevalence: 0.0013, at_app_threshold: { precision: 0.85, recall: 0.77, f1: 0.81, tp: 57, fp: 10, fn: 17, tn: 56662, threshold: 0.22 }, at_validation_f1_threshold: { precision: 0.88, recall: 0.72, f1: 0.79, tp: 53, fp: 7, fn: 21, tn: 56665, threshold: 0.5 } } } },
  };
  const resp = { items: [model], ml_available: true, training_note: "Training runs offline.", benchmark: { replayed: 0, tp: 0, fp: 0, fn: 0, tn: 0, precision: null, recall: null, note: "Sample is enriched." } };

  it("states held-out metrics with their caveats and lets an admin retire the model after confirming", async () => {
    const calls = mockApi((url, init) => (url === "/api/auth/me" ? { body: me("admin") } : init?.method === "POST" ? { body: {} } : { body: resp }));
    renderAt(<Models />, "/models");
    expect(await screen.findByText(/78\.\d?%|0\.782/)).toBeInTheDocument();
    expect(screen.getByText(/only 74 frauds were in the test split/i)).toBeInTheDocument();
    expect(screen.getByText(/not Indian transactions/i)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Retire" }));
    expect(calls.some((c) => c.method === "POST")).toBe(false);
    await userEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Retire" }));
    await waitFor(() => expect(calls.find((c) => c.url === "/api/models/1/retire")).toBeDefined());
  });
  it("hides deploy/retire/replay controls from analysts", async () => {
    mockApi((url) => (url === "/api/auth/me" ? { body: me("analyst") } : { body: resp }));
    renderAt(<Models />, "/models");
    await screen.findByText("ulb_random_forest_v1");
    expect(screen.queryByRole("button", { name: "Retire" })).toBeNull();
    expect(screen.queryByRole("button", { name: /replay/i })).toBeNull();
  });
});

describe("unexpected server data", () => {
  it("shows a recoverable message instead of a blank page when a page cannot render the response", async () => {
    mockApi((url) => (url === "/api/auth/me" ? { body: me("analyst") } : url === "/api/reports" ? { body: { transactions: 1 } } : { body: { items: [], total: 0, page: 1, page_size: 1, pages: 1 } }));
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    render(<MemoryRouter><App /></MemoryRouter>);
    expect(await screen.findByText(/could not be displayed/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /reload/i })).toBeInTheDocument();
  });
});
