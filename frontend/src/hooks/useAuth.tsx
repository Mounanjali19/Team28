import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import { api, loadSession, saveSession, type Session } from "../services/api";

interface AuthCtx {
  session: Session | null;
  login: (username: string, password: string) => Promise<Session>;
  demoLogin: (username: string) => Promise<Session>;
  adopt: (s: Session) => void;
  logout: () => void;
}

const Ctx = createContext<AuthCtx | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(() => loadSession());

  const adopt = useCallback((s: Session) => {
    saveSession(s);
    setSession(s);
  }, []);

  const login = useCallback(
    async (username: string, password: string) => {
      const s = await api<Session>("/api/auth/login", { body: { username, password } });
      adopt(s);
      return s;
    },
    [adopt],
  );

  const demoLogin = useCallback(
    async (username: string) => {
      const s = await api<Session>("/api/auth/demo-login", { body: { username } });
      adopt(s);
      return s;
    },
    [adopt],
  );

  const logout = useCallback(() => {
    saveSession(null);
    setSession(null);
  }, []);

  const value = useMemo(() => ({ session, login, demoLogin, adopt, logout }), [session, login, demoLogin, adopt, logout]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth() {
  const c = useContext(Ctx);
  if (!c) throw new Error("useAuth outside AuthProvider");
  return c;
}

export const homeFor = (s: Session) => (s.role === "lender" ? "/lender" : s.role === "admin" ? "/admin" : "/app");
