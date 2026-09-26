import { NavLink, Navigate, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";
import { Brand } from "./UserLayout";

const LENDER_NAV = [
  ["/lender", "Dashboard", true],
  ["/lender/candidates", "Candidates", false],
  ["/lender/offers", "Sent offers", false],
  ["/lender/analytics", "Analytics", false],
] as const;

const ADMIN_NAV = [
  ["/admin", "Platform", true],
  ["/admin/candidates", "Applicants", false],
  ["/admin/analytics", "Analytics", false],
] as const;

export default function LenderLayout({ role }: { role: "lender" | "admin" }) {
  const { session, logout } = useAuth();
  const nav = useNavigate();
  if (!session) return <Navigate to="/login" replace />;
  if (session.role !== role) return <Navigate to={session.role === "user" ? "/app" : session.role === "lender" ? "/lender" : "/admin"} replace />;
  const items = role === "lender" ? LENDER_NAV : ADMIN_NAV;
  return (
    <div className="shell">
      <aside className="sidebar">
        <Brand sub={role === "lender" ? "Lender" : "Admin"} />
        {items.map(([to, label, end]) => (
          <NavLink key={to} to={to} end={end}>
            {label}
          </NavLink>
        ))}
        <div className="foot">
          Candidates are ranked by the rule-based policy score. ML PD is a validation column only. Names and phone numbers stay masked until an applicant accepts your offer.
        </div>
      </aside>
      <div className="shell-main">
        <div className="shell-top">
          <b>{session.display_name}</b>
          <div className="user-chip">
            <span>{session.username}</span>
            <button className="btn btn-sm" onClick={() => { logout(); nav("/login"); }}>
              Sign out
            </button>
          </div>
        </div>
        <main className="page">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
