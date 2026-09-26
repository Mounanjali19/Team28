import { useState, type FormEvent } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { ErrorBox, Loading, TierBadge } from "../components/ui";
import { useApi } from "../hooks/useApi";
import { homeFor, useAuth } from "../hooks/useAuth";
import { titleCase } from "../utils/format";
import { Brand } from "../layouts/UserLayout";

interface DemoAccounts {
  demo_mode: boolean;
  users: { username: string; display_name: string; user_id: string; demo_label: string; score: number; tier: string }[];
  lenders: { username: string; display_name: string; lender_id: string; n_products: number }[];
  note: string;
}

export default function Login() {
  const { session, login, demoLogin } = useAuth();
  const nav = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const demo = useApi<DemoAccounts>("/api/auth/demo-accounts");
  if (session) return <Navigate to={homeFor(session)} replace />;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy("form");
    setErr(null);
    try {
      const s = await login(username, password);
      nav(homeFor(s));
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };
  const quick = async (u: string) => {
    setBusy(u);
    setErr(null);
    try {
      const s = await demoLogin(u);
      nav(homeFor(s));
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="login-wrap">
      <section className="login-side">
        <Brand sub="Alternative credit scoring" />
        <div className="stack" style={{ gap: 18, maxWidth: 460 }}>
          <h1>A credit score you can read line by line.</h1>
          <p>
            AltCredit scores applicants without a credit bureau file, using income regularity, bill payments, spending behaviour and savings habits.
            Fourteen published rules produce the 0–1000 policy score; a machine-learning model checks it and flags disagreements, but never changes it.
          </p>
          <ul className="list" style={{ color: "#cbd5e1" }}>
            <li>Every point traced to the rule and the data behind it</li>
            <li>What-If simulator and a verified plan to reach a target product</li>
            <li>Lender portal with anonymised candidates and offer workflow</li>
          </ul>
        </div>
        <p className="xs" style={{ color: "#94a3b8" }}>Synthetic demonstration data only. No real personal data, bureau or bank is involved.</p>
      </section>
      <section className="login-main">
        <div className="stack" style={{ maxWidth: 520, width: "100%", margin: "0 auto" }}>
          <div>
            <h1>Sign in</h1>
            <p className="muted">Applicants, lenders and administrators use the same sign-in.</p>
          </div>
          <form className="card card-pad stack" onSubmit={submit}>
            <label className="field">
              Username
              <input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" required />
            </label>
            <label className="field">
              Password
              <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required />
            </label>
            {err && <ErrorBox error={err} />}
            <div className="row between">
              <button className="btn btn-primary" disabled={busy !== null}>
                {busy === "form" ? "Signing in…" : "Sign in"}
              </button>
              <Link to="/register">New applicant? Create a profile</Link>
            </div>
          </form>

          {demo.loading && <Loading label="Loading demo accounts…" />}
          {demo.error && <ErrorBox error={`Demo accounts unavailable: ${demo.error}`} onRetry={demo.reload} />}
          {demo.data?.demo_mode && (
            <>
              <div>
                <h2>Demo applicants</h2>
                <p className="small muted">One click signs in as a seeded synthetic applicant. Scores are computed live by the rule engine.</p>
              </div>
              <div className="demo-grid">
                {demo.data.users.map((u) => (
                  <button key={u.username} className="demo-btn" onClick={() => quick(u.username)} disabled={busy !== null}>
                    <span>
                      <b>{titleCase(u.demo_label)}</b>
                      <div className="xs muted">{u.username}</div>
                    </span>
                    <span className="stack" style={{ gap: 2, alignItems: "flex-end" }}>
                      <span className="num"><b>{u.score}</b></span>
                      <TierBadge tier={u.tier} />
                    </span>
                  </button>
                ))}
              </div>
              <div>
                <h2>Demo lenders</h2>
              </div>
              <div className="demo-grid">
                {demo.data.lenders.map((l) => (
                  <button key={l.username} className="demo-btn" onClick={() => quick(l.username)} disabled={busy !== null}>
                    <span>
                      <b>{l.display_name}</b>
                      <div className="xs muted">{l.username}</div>
                    </span>
                    <span className="xs muted">{l.n_products} product{l.n_products === 1 ? "" : "s"}</span>
                  </button>
                ))}
              </div>
              <p className="xs muted">{demo.data.note} The admin account signs in with the form above.</p>
            </>
          )}
        </div>
      </section>
    </div>
  );
}
