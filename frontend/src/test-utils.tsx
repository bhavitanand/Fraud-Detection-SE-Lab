import { render } from "@testing-library/react";
import { ReactElement } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { vi } from "vitest";
import { AuthProvider } from "./auth";
import { ToastProvider } from "./components/ui";

type Handler = (url: string, init?: RequestInit) => { status?: number; body?: unknown; raw?: string };

export function mockApi(handler: Handler) {
  const calls: { url: string; method: string; body: unknown }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url, method: init?.method ?? "GET", body: init?.body ? JSON.parse(String(init.body)) : undefined });
    const r = handler(url, init);
    const status = r.status ?? 200;
    return new Response(r.raw ?? JSON.stringify(r.body ?? {}), { status, headers: { "Content-Type": "application/json" } });
  }));
  return calls;
}

export const me = (role: "analyst" | "admin") => ({ username: "tester", role, auth_required: true });

export function renderAt(ui: ReactElement, path: string, route = "*") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider><ToastProvider><Routes><Route path={route} element={ui} /></Routes></ToastProvider></AuthProvider>
    </MemoryRouter>,
  );
}
