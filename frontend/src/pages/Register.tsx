import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ErrorBox } from "../components/ui";
import { useAuth } from "../hooks/useAuth";
import { api, type Session } from "../services/api";
import { Brand } from "../layouts/UserLayout";

interface RegisterOut {
  session: Session;
  ingestion: { stats: Record<string, unknown>; issues: { check_code: string; severity: string; message: string; count: number }[] };
  score: number;
  tier: { name: string };
}

export default function Register() {
  const { adopt } = useAuth();
  const nav = useNavigate();
  const [f, setF] = useState({
    username: "",
    password: "",
    display_name: "",
    age: "28",
    education_level: "Bachelor",
    employment_status: "salaried",
    monthly_income: "32000",
    city_tier: "1",
    housing_status: "rent",
    monthly_rent: "9000",
    months_in_current_job: "18",
    months_at_address: "14",
  });
  const [txn, setTxn] = useState<File | null>(null);
  const [bills, setBills] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [result, setResult] = useState<RegisterOut | null>(null);
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!txn) {
      setErr("Upload a transaction file (CSV or JSON).");
      return;
    }
    setBusy(true);
    setErr(null);
    const form = new FormData();
    form.append("username", f.username);
    form.append("password", f.password);
    form.append(
      "profile",
      JSON.stringify({
        display_name: f.display_name || f.username,
        age: Number(f.age),
        education_level: f.education_level,
        employment_status: f.employment_status,
        monthly_income: Number(f.monthly_income),
        city_tier: Number(f.city_tier),
        housing_status: f.housing_status,
        monthly_rent: f.housing_status === "rent" ? Number(f.monthly_rent) : null,
        months_in_current_job: f.employment_status === "student" || f.employment_status === "unemployed" ? null : Number(f.months_in_current_job),
        months_at_address: Number(f.months_at_address),
      }),
    );
    form.append("transactions", txn);
    if (bills) form.append("bills", bills);
    try {
      const r = await api<RegisterOut>("/api/auth/register", { form, method: "POST" });
      setResult(r);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="page" style={{ maxWidth: 860 }}>
      <div className="page-head">
        <div>
          <Link to="/login" style={{ textDecoration: "none" }}>
            <Brand />
          </Link>
          <h1 style={{ marginTop: 16 }}>Create your AltCredit profile</h1>
          <p>Tell us about yourself and upload 6–12 months of bank transactions. The rule engine scores you immediately.</p>
        </div>
      </div>
      {result ? (
        <div className="card card-pad stack">
          <h2>Your profile is scored</h2>
          <p>
            Policy score <b className="num">{result.score}</b> / 1000 ({result.tier.name}). {String(result.ingestion.stats.transactions)} transactions and{" "}
            {String(result.ingestion.stats.obligations)} bills were read; score as of {String(result.ingestion.stats.as_of)}.
          </p>
          {result.ingestion.issues.length > 0 && (
            <div className="callout warn small">
              <b>Validation notes</b>
              <ul className="list">
                {result.ingestion.issues.slice(0, 8).map((i, k) => (
                  <li key={k}>
                    <span className="mono">{i.check_code}</span> ({i.severity}, {i.count}): {i.message}
                  </li>
                ))}
              </ul>
            </div>
          )}
          <div>
            <button className="btn btn-primary" onClick={() => { adopt(result.session); nav("/app"); }}>
              Go to my dashboard
            </button>
          </div>
        </div>
      ) : (
        <form className="stack" onSubmit={submit}>
          <div className="card card-pad stack">
            <h2>Account</h2>
            <div className="grid g3">
              <label className="field">Username<input value={f.username} onChange={set("username")} minLength={3} maxLength={40} required /></label>
              <label className="field">Password (8+ characters)<input type="password" value={f.password} onChange={set("password")} minLength={8} required /></label>
              <label className="field">Display name<input value={f.display_name} onChange={set("display_name")} placeholder="Shown to you; masked for lenders" /></label>
            </div>
          </div>
          <div className="card card-pad stack">
            <h2>About you</h2>
            <div className="grid g3">
              <label className="field">Age<input type="number" min={18} max={80} value={f.age} onChange={set("age")} required /></label>
              <label className="field">
                Education
                <select value={f.education_level} onChange={set("education_level")}>
                  {["Below High School", "High School", "Diploma", "Bachelor", "Master", "PhD"].map((x) => <option key={x}>{x}</option>)}
                </select>
              </label>
              <label className="field">
                Employment
                <select value={f.employment_status} onChange={set("employment_status")}>
                  {[["salaried", "Salaried"], ["self_employed", "Self-employed"], ["gig", "Gig worker"], ["freelancer", "Freelancer"], ["student", "Student"], ["unemployed", "Unemployed"]].map(([v, l]) => (
                    <option key={v} value={v}>{l}</option>
                  ))}
                </select>
              </label>
              <label className="field">Monthly income (₹)<input type="number" min={0} value={f.monthly_income} onChange={set("monthly_income")} required /></label>
              <label className="field">
                City tier
                <select value={f.city_tier} onChange={set("city_tier")}>
                  <option value="1">Tier 1</option>
                  <option value="2">Tier 2</option>
                  <option value="3">Tier 3</option>
                </select>
              </label>
              <label className="field">Months in current job<input type="number" min={0} value={f.months_in_current_job} onChange={set("months_in_current_job")} /></label>
              <label className="field">
                Housing
                <select value={f.housing_status} onChange={set("housing_status")}>
                  <option value="own">Own home</option>
                  <option value="rent">Renting</option>
                  <option value="family">Living with family</option>
                </select>
              </label>
              {f.housing_status === "rent" && (
                <label className="field">Monthly rent (₹)<input type="number" min={0} value={f.monthly_rent} onChange={set("monthly_rent")} /></label>
              )}
              <label className="field">Months at this address<input type="number" min={0} value={f.months_at_address} onChange={set("months_at_address")} /></label>
            </div>
          </div>
          <div className="card card-pad stack">
            <h2>Bank statement</h2>
            <p className="small muted">
              CSV or JSON with columns <span className="mono">date, amount, category, type</span> (CREDIT/DEBIT), optionally{" "}
              <span className="mono">status, subtype, balance_after</span>. Rent, Utility Bill, Telecom and Loan EMI debits are treated as bills; status "Late" marks a late payment.{" "}
              <a href="/sample_transactions.csv" download>Download a synthetic sample file</a>.
            </p>
            <div className="grid g2">
              <label className="field">Transactions (required)<input type="file" accept=".csv,.json" onChange={(e) => setTxn(e.target.files?.[0] ?? null)} required /></label>
              <label className="field">Bills with due dates (optional)<input type="file" accept=".csv,.json" onChange={(e) => setBills(e.target.files?.[0] ?? null)} /></label>
            </div>
          </div>
          {err && <ErrorBox error={err} />}
          <div className="row">
            <button className="btn btn-primary" disabled={busy}>{busy ? "Scoring…" : "Create profile and score me"}</button>
            <Link to="/login">Cancel</Link>
          </div>
        </form>
      )}
    </div>
  );
}
