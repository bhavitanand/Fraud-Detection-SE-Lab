import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import Audit from "./pages/Audit";
import Cards from "./pages/Cards";
import TransactionDetail from "./pages/TransactionDetail";
import { me, mockApi, renderAt } from "./test-utils";

afterEach(() => vi.unstubAllGlobals());

const tx = (over = {}) => ({
  id: 7, token: "SYNTH-0007", amount: 2400, merchant: "<b>Evil</b> Shop", country: "US", channel: "ONLINE", created: "2026-10-01T10:00:00+00:00", score: 0.49,
  decision: "HOLD", reasons: [], factors: [{ code: "base", label: "Baseline risk", points: 0.04 }, { code: "high_amount", label: "Amount above 1500", points: 0.35 }, { code: "online_channel", label: "Online (card-not-present) channel", points: 0.1 }],
  review: "OPEN", scorer: "heuristic-v1", source: "LIVE", reviewed_at: null, reviewed_by: null, review_note: null, has_alert: true,
  card: { token: "SYNTH-0007", blocked: false }, token_history: [], audit: [], ...over,
});

describe("investigation flow", () => {
  it("records a confirmed-fraud verdict after confirmation and shows the card-block outcome", async () => {
    let reviewed = false;
    const calls = mockApi((url, init) => {
      if (url === "/api/auth/me") return { body: me("analyst") };
      if (url.startsWith("/api/alerts/7/review") && init?.method === "POST") { reviewed = true; return { body: { ok: true, transaction_id: 7, verdict: "CONFIRMED_FRAUD", card_blocked: true, card_token: "SYNTH-0007", card_currently_blocked: true } }; }
      if (url === "/api/transactions/7") return { body: reviewed ? tx({ review: "CONFIRMED_FRAUD", reviewed_by: "tester", reviewed_at: "2026-10-01T11:00:00+00:00", card: { token: "SYNTH-0007", blocked: true } }) : tx() };
      return { status: 404, body: { error: { code: "not_found", message: "?" } } };
    });
    renderAt(<TransactionDetail />, "/transactions/7", "/transactions/:id");
    expect(await screen.findByText("Amount above 1500")).toBeInTheDocument();
    const record = screen.getByRole("button", { name: /record verdict/i });
    expect(record).toBeDisabled();  // no verdict chosen yet
    await userEvent.click(screen.getByLabelText(/confirmed fraud/i));
    await userEvent.type(screen.getByLabelText(/note/i), "customer called");
    await userEvent.click(record);
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/blocks/i)).toBeInTheDocument();
    expect(calls.some((c) => c.url.includes("/review"))).toBe(false);  // nothing sent before confirmation
    await userEvent.click(within(dialog).getByRole("button", { name: /confirm fraud and block/i }));
    expect(await screen.findByText(/is now blocked/i)).toBeInTheDocument();
    expect(calls.find((c) => c.url.includes("/review"))?.body).toEqual({ verdict: "CONFIRMED_FRAUD", note: "customer called" });
    await waitFor(() => expect(screen.getByText(/A recorded verdict is final/i)).toBeInTheDocument());
  });

  it("shows a recoverable error when the alert was already reviewed", async () => {
    mockApi((url, init) => {
      if (url === "/api/auth/me") return { body: me("analyst") };
      if (init?.method === "POST") return { status: 409, body: { error: { code: "already_reviewed", message: "Alert already reviewed as FALSE_POSITIVE by sam." } } };
      return { body: tx() };
    });
    renderAt(<TransactionDetail />, "/transactions/7", "/transactions/:id");
    await userEvent.click(await screen.findByLabelText(/false positive/i));
    await userEvent.click(screen.getByRole("button", { name: /record verdict/i }));
    await userEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: /record false positive/i }));
    expect(await screen.findByText(/already reviewed as FALSE_POSITIVE by sam/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /cancel/i })).toBeEnabled();  // the user can back out
  });

  it("renders untrusted merchant text as text, not HTML", async () => {
    mockApi((url) => (url === "/api/auth/me" ? { body: me("analyst") } : { body: tx({ has_alert: false, decision: "APPROVE", review: "NOT_REQUIRED" }) }));
    const { container } = renderAt(<TransactionDetail />, "/transactions/7", "/transactions/:id");
    expect(await screen.findByText("<b>Evil</b> Shop")).toBeInTheDocument();
    expect(container.querySelector("b")).toBeNull();
  });

  it("shows a not-found state for a missing transaction", async () => {
    mockApi((url) => (url === "/api/auth/me" ? { body: me("analyst") } : { status: 404, body: { error: { code: "not_found", message: "Transaction 9 not found" } } }));
    renderAt(<TransactionDetail />, "/transactions/9", "/transactions/:id");
    expect(await screen.findByText(/does not exist/i)).toBeInTheDocument();
  });
});

describe("cards and audit", () => {
  const cards = [{ token: "SYNTH-A001", blocked: false, blocked_at: null, block_reason: null, blocked_by: null, tx_count: 2, alert_count: 1, last_seen: null }];
  it("disables blocking for analysts", async () => {
    mockApi((url) => (url === "/api/auth/me" ? { body: me("analyst") } : { body: cards }));
    renderAt(<Cards />, "/cards");
    expect(await screen.findByText("SYNTH-A001")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Block" })).toBeDisabled();
    expect(screen.getByText(/synthetic demo tokens/i)).toBeInTheDocument();
  });
  it("lets an admin block a card after confirming", async () => {
    const calls = mockApi((url) => (url === "/api/auth/me" ? { body: me("admin") } : url.includes("/block") ? { body: { token: "SYNTH-A001", blocked: true, changed: true } } : { body: cards }));
    renderAt(<Cards />, "/cards");
    await userEvent.click(await screen.findByRole("button", { name: "Block" }));
    await userEvent.type(within(await screen.findByRole("dialog")).getByLabelText(/reason/i), "lost card");
    await userEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: /block token/i }));
    await waitFor(() => expect(calls.find((c) => c.url.endsWith("/block"))?.body).toEqual({ reason: "lost card" }));
  });
  it("shows audit details containing markup as plain text", async () => {
    const page = { items: [{ id: 1, at: "2026-10-01T10:00:00+00:00", actor: "x", action: "transaction_scored", target: "transaction:7", detail: { note: "<img src=x onerror=alert(1)>" } }], total: 1, limit: 50, offset: 0, actions: ["transaction_scored"] };
    mockApi((url) => (url === "/api/auth/me" ? { body: me("analyst") } : { body: page }));
    const { container } = renderAt(<Audit />, "/audit");
    expect(await screen.findByText(/<img src=x onerror=alert\(1\)>/)).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
  });
  it("shows an error state with retry when the API fails", async () => {
    mockApi((url) => (url === "/api/auth/me" ? { body: me("analyst") } : { status: 503, body: { error: { code: "database_error", message: "The database is unavailable." } } }));
    renderAt(<Cards />, "/cards");
    expect(await screen.findByText(/database is unavailable/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /try again/i })).toBeInTheDocument();
  });
});
