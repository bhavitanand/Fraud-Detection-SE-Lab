import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { session } from "./api/client";
import Copilot from "./pages/Copilot";
import Live from "./pages/Live";
import { me, mockApi, renderAt } from "./test-utils";

afterEach(() => { vi.unstubAllGlobals(); session.clear(); });

const kpis = { transactions: 500, frauds: 20, frauds_caught: 18, frauds_missed: 2, false_alarms: 3, precision_pct: 85.7, recall_pct: 90, false_positive_rate_pct: 0.6, fraud_inr_prevented: 500000, fraud_inr_held: 0,
  fraud_inr_missed: 20000, prevented_pct: 96, alerts: 21, alerts_open: 4, alerts_auto_resolved: 17, autonomy_pct: 81, human_queue: 4, avg_latency_ms: 2.1, p95_latency_ms: 3.3, note: "n" };
const status = (over = {}) => ({ state: "idle", running: false, run: "", processed: 0, approved: 0, held: 0, declined: 0, gate_rejected_fraud: 0, gate_rejected_genuine: 0, replies: 0, auto_blocked: 0, sim_time: null, rate: 0, cards: 0, error: null,
  feed: [], autopilot: false, auto_block_score: 0.9, model: { name: "india_xgboost_v1", algorithm: "xgboost", pr_auc: 0.934 }, kpis: null, ...over });

describe("Live mode", () => {
  it("lets an admin start the simulation with the chosen settings", async () => {
    const calls = mockApi((url) => (url === "/api/auth/me" ? { body: me("admin") } : url === "/api/live/status" ? { body: status() } : { body: status({ state: "starting", running: true }) }));
    renderAt(<Live />, "/live");
    await userEvent.click(await screen.findByRole("button", { name: /start simulation/i }));
    await waitFor(() => expect(calls.find((c) => c.url === "/api/live/start")?.body).toMatchObject({ cards: 150, autopilot: true }));
  });

  it("shows simulated precision, recall, autonomy and the honesty note", async () => {
    mockApi((url) => (url === "/api/auth/me" ? { body: me("analyst") } : { body: status({ state: "running", running: true, processed: 500, kpis, autopilot: true,
      feed: [{ at: "2026-11-17T10:00:00Z", text: "DECLINE: ₹90,000 at Tanishq", level: "decline", tx_id: 7 }] }) }));
    renderAt(<Live />, "/live");
    expect(await screen.findByText("85.7%")).toBeInTheDocument();
    expect(screen.getByText("81.0%")).toBeInTheDocument();
    expect(screen.getByText(/not real-world accuracy/i)).toBeInTheDocument();
    expect(screen.getByText(/DECLINE: ₹90,000 at Tanishq/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /start simulation|stop/i })).toBeNull();  // analysts cannot control it
  });
});

describe("AI copilot", () => {
  it("sends a question and shows the interpreted filter and matching rows", async () => {
    const calls = mockApi((url) => url === "/api/auth/me" ? { body: me("analyst") } : url === "/api/copilot/status" ? { body: { provider: "offline", model: "rule-based", note: "n" } }
      : { body: { provider: "offline", question: "q", filter: { decision: "DECLINE" }, answer: "Found 1 transaction (decline) worth ₹90,000 in total.", count: 1, total_amount: 90000,
        rows: [{ id: 7, token: "T", amount: 90000, currency: "INR", merchant: "Tanishq", location: "Mumbai", channel: "POS", score: 0.9, decision: "DECLINE", review: "OPEN", created: "2026-11-17T10:00:00Z" }] } });
    renderAt(<Copilot />, "/copilot");
    await userEvent.type(await screen.findByLabelText(/ask a question/i), "declined orders");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));
    expect(await screen.findByText(/Found 1 transaction/)).toBeInTheDocument();
    expect(screen.getByText("Tanishq")).toBeInTheDocument();
    expect(calls.find((c) => c.url === "/api/copilot/chat")?.body).toEqual({ question: "declined orders" });
  });
});
