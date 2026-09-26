import { NavLink, Navigate, Outlet, useNavigate, useOutletContext } from "react-router-dom";
import { ErrorBox, Loading } from "../components/ui";
import { useApi } from "../hooks/useApi";
import { useAuth } from "../hooks/useAuth";
import type { Profile } from "../types";

export interface UserCtx {
  profile: Profile;
  userId: string;
  reload: () => Promise<void>;
  setProfile: (p: Profile) => void;
}

export const useUser = () => useOutletContext<UserCtx>();

const NAV = [
  ["/app", "Dashboard", true],
  ["/app/score", "Score details", false],
  ["/app/products", "Products", false],
  ["/app/what-if", "What-If", false],
  ["/app/target", "Target", false],
  ["/app/offers", "Offers", false],
  ["/app/applications", "Applications", false],
  ["/app/report", "Report", false],
  ["/app/profile", "Profile", false],
] as const;

export function Brand({ sub }: { sub?: string }) {
  return (
    <span className="brand">
      <span className="brand-mark" aria-hidden>
        <svg width="16" height="16" viewBox="0 0 32 32">
          <path d="M8 23l8-15 8 15" stroke="white" strokeWidth="3.5" fill="none" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </span>
      AltCredit{sub && <small>{sub}</small>}
    </span>
  );
}

export default function UserLayout() {
  const { session, logout } = useAuth();
  const nav = useNavigate();
  const uid = session?.role === "user" ? session.user_id : null;
  const { data, error, loading, reload, setData } = useApi<Profile>(uid ? `/api/users/${uid}/score` : null);
  if (!session) return <Navigate to="/login" replace />;
  if (session.role !== "user" || !uid) return <Navigate to={session.role === "lender" ? "/lender" : "/admin"} replace />;
  return (
    <div>
      <header className="topbar">
        <div className="topbar-inner">
          <a href="/app" onClick={(e) => { e.preventDefault(); nav("/app"); }} style={{ textDecoration: "none" }}>
            <Brand />
          </a>
          <nav className="nav" aria-label="Main">
            {NAV.map(([to, label, end]) => (
              <NavLink key={to} to={to} end={end}>
                {label}
              </NavLink>
            ))}
          </nav>
          <div className="user-chip">
            <span>{session.display_name}</span>
            <button className="btn btn-sm" onClick={() => { logout(); nav("/login"); }}>
              Sign out
            </button>
          </div>
        </div>
      </header>
      <main className="page">
        {error && <ErrorBox error={error} onRetry={reload} />}
        {loading && !data && <Loading label="Computing your policy score…" />}
        {data && <Outlet context={{ profile: data, userId: uid, reload, setProfile: setData } satisfies UserCtx} />}
      </main>
      <footer className="page xs muted" style={{ paddingTop: 0 }}>
        Synthetic demo. All applicants, lenders and bank responses are simulated; no real bureau or banking API is called.
      </footer>
    </div>
  );
}
