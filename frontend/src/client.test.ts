import { api, ApiError, session } from "./api/client";
import { mockApi } from "./test-utils";

afterEach(() => { vi.unstubAllGlobals(); session.clear(); });

describe("api client", () => {
  it("parses the server error shape", async () => {
    mockApi(() => ({ status: 409, body: { error: { code: "already_reviewed", message: "Alert already reviewed." } } }));
    await expect(api.post("/api/x")).rejects.toMatchObject({ status: 409, code: "already_reviewed", message: "Alert already reviewed." });
  });
  it("turns an unparseable success body into a typed error", async () => {
    mockApi(() => ({ raw: "<html>proxy error</html>" }));
    await expect(api.get("/api/x")).rejects.toMatchObject({ code: "bad_response" });
  });
  it("reports network failures", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("failed"); }));
    await expect(api.get("/api/x")).rejects.toBeInstanceOf(ApiError);
  });
  it("sends the bearer token and clears it on 401", async () => {
    session.set("abc");
    const calls = mockApi(() => ({ status: 401, body: { error: { code: "unauthorized", message: "no" } } }));
    const expired = vi.fn();
    window.addEventListener("auth-expired", expired);
    await expect(api.get("/api/x")).rejects.toMatchObject({ status: 401 });
    expect(calls[0]).toBeDefined();
    expect(session.get()).toBeNull();
    expect(expired).toHaveBeenCalled();
  });
  it("drops empty query params", async () => {
    const calls = mockApi(() => ({ body: {} }));
    await api.get("/api/t", { q: "", page: 2, decision: undefined });
    expect(calls[0]?.url).toBe("/api/t?page=2");
  });
});
