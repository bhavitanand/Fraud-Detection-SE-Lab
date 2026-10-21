import { validate } from "./pages/Rules";

const ok = { approve_max: "0.25", hold_max: "0.65", high_amount: "1500", blocked_countries: "XX,RU", velocity_limit: "4" };

describe("rule form validation", () => {
  it("accepts the defaults", () => expect(validate(ok)).toEqual({}));
  it("rejects approve >= hold", () => expect(validate({ ...ok, approve_max: "0.7" }).hold_max).toMatch(/higher/));
  it("rejects out-of-range and non-numeric thresholds", () => {
    expect(validate({ ...ok, approve_max: "1" }).approve_max).toBeDefined();
    expect(validate({ ...ok, hold_max: "abc" }).hold_max).toBeDefined();
    expect(validate({ ...ok, hold_max: "" }).hold_max).toBeDefined();
  });
  it("rejects bad amount, velocity and country codes", () => {
    expect(validate({ ...ok, high_amount: "0" }).high_amount).toBeDefined();
    expect(validate({ ...ok, velocity_limit: "2.5" }).velocity_limit).toBeDefined();
    expect(validate({ ...ok, blocked_countries: "XX,USA" }).blocked_countries).toMatch(/USA/);
  });
});
