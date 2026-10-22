import { createContext, ReactNode, useCallback, useContext, useEffect, useState } from "react";
import { api, ApiError, session } from "./api/client";
import type { Me } from "./api/types";

export interface OtpChallenge { otp_required: true; challenge_id: number; email_hint: string; expires_in: number }
interface AuthState {
  me: Me | null; status: "loading" | "anon" | "ready" | "down"; error: string | null;
  login: (email: string, password: string) => Promise<OtpChallenge | null>; verifyOtp: (challengeId: number, code: string) => Promise<void>; logout: () => void; isAdmin: boolean;
}
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

  const login = async (email: string, password: string): Promise<OtpChallenge | null> => {
    const r = await api.post<{ access_token?: string } & Partial<OtpChallenge>>("/api/auth/login", { email, password });
    if (r.otp_required) return r as OtpChallenge;
    session.set(r.access_token ?? "");
    load();
    return null;
  };
  const verifyOtp = async (challengeId: number, code: string) => {
    const r = await api.post<{ access_token: string }>("/api/auth/otp", { challenge_id: challengeId, code });
    session.set(r.access_token);
    load();
  };
  const logout = () => { session.clear(); setMe(null); setStatus("anon"); };
  return <Ctx.Provider value={{ me, status, error, login, verifyOtp, logout, isAdmin: me?.role === "admin" }}>{children}</Ctx.Provider>;
}
