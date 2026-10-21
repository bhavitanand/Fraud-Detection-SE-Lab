import { createContext, ReactNode, useCallback, useContext, useEffect, useState } from "react";
import { api, ApiError, session } from "./api/client";
import type { Me } from "./api/types";

interface AuthState { me: Me | null; status: "loading" | "anon" | "ready" | "down"; error: string | null; login: (u: string, p: string) => Promise<void>; logout: () => void; isAdmin: boolean }
const Ctx = createContext<AuthState | null>(null);
export const useAuth = () => { const v = useContext(Ctx); if (!v) throw new Error("AuthProvider missing"); return v; };

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [status, setStatus] = useState<AuthState["status"]>("loading");
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api.get<Me>("/api/auth/me").then(
      (m) => { setMe(m); setStatus("ready"); },
      (e: unknown) => {
        if (e instanceof ApiError && e.status === 401) setStatus("anon");
        else { setError(e instanceof ApiError ? e.message : "Unexpected error"); setStatus("down"); }
      },
    );
  }, []);
  useEffect(load, [load]);
  useEffect(() => { const h = () => { setMe(null); setStatus("anon"); }; window.addEventListener("auth-expired", h); return () => window.removeEventListener("auth-expired", h); }, []);

  const login = async (username: string, password: string) => {
    const r = await api.post<{ access_token: string }>("/api/auth/login", { username, password });
    session.set(r.access_token);
    load();
  };
  const logout = () => { session.clear(); setMe(null); setStatus("anon"); };
  return <Ctx.Provider value={{ me, status, error, login, logout, isAdmin: me?.role === "admin" }}>{children}</Ctx.Provider>;
}
