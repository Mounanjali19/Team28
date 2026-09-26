import { Fragment, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { Badge, ErrorBox, Loading } from "../../components/ui";
import { useApi } from "../../hooks/useApi";
import { api } from "../../services/api";
import { dateTime } from "../../utils/format";

interface Run {
  run_id: number;
  source: string;
  started_at: string;
  finished_at: string | null;
  status: string;
  stats: Record<string, unknown>;
  issues: { file: string; check_code: string; severity: string; count: number; row_ref: string | null; message: string }[];
}
interface AuditRow { id: number; ts: string; actor: string; action: string; entity: string; entity_id: string; rule_version: string | null; detail_json: string }
interface Rules { rule_version: string; rules: { id: string; name: string; component: string; max_points?: number; input?: string; status?: string; [k: string]: unknown }[]; open_decisions: Record<string, unknown> }

export default function AdminHome() {
  const runs = useApi<Run[]>("/api/admin/ingestion-runs");
  const audit = useApi<AuditRow[]>("/api/admin/audit?limit=60");
  const rules = useApi<Rules>("/api/rules");
  const [open, setOpen] = useState<number | null>(null);

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Platform</h1>
          <p>Data ingestion and validation, the rule catalog, and the audit trail.</p>
        </div>
      </div>
      <IngestForm onDone={() => { void runs.reload(); void audit.reload(); }} />
      <div className="card">
        <div className="card-head"><div><h2>Ingestion runs</h2><p>Every file is validated before it is used; findings are kept per run.</p></div></div>
        {runs.error && <div className="card-body"><ErrorBox error={runs.error} onRetry={runs.reload} /></div>}
        {runs.loading && !runs.data && <Loading />}
        {runs.data && (
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Run</th><th>Source</th><th>Status</th><th>Started</th><th>Findings</th><th /></tr></thead>
              <tbody>
                {runs.data.map((r) => (
                  <Fragment key={r.run_id}>
                    <tr>
                      <td className="mono">#{r.run_id}</td>
                      <td className="small">{r.source}</td>
                      <td><Badge tone={r.status === "completed" ? "pos" : r.status === "failed" ? "neg" : "warn"}>{r.status}</Badge></td>
                      <td className="small">{dateTime(r.started_at)}</td>
                      <td className="small">{r.issues.length} check{r.issues.length === 1 ? "" : "s"} flagged</td>
                      <td className="r"><button className="btn btn-sm" onClick={() => setOpen(open === r.run_id ? null : r.run_id)}>{open === r.run_id ? "Hide" : "Details"}</button></td>
                    </tr>
                    {open === r.run_id && (
                      <tr>
                        <td colSpan={6} style={{ background: "var(--sunk)" }}>
                          <pre className="mono" style={{ margin: 0, whiteSpace: "pre-wrap" }}>{JSON.stringify(r.stats, null, 1)}</pre>
                          {r.issues.length > 0 && (
                            <table className="table" style={{ marginTop: 8 }}>
                              <thead><tr><th>File</th><th>Check</th><th>Severity</th><th className="r">Rows</th><th>Message</th></tr></thead>
                              <tbody>
                                {r.issues.map((i, k) => (
                                  <tr key={k}><td className="small">{i.file}</td><td className="mono">{i.check_code}</td><td><Badge tone={i.severity === "error" ? "neg" : "warn"}>{i.severity}</Badge></td><td className="r num">{i.count}</td><td className="small">{i.message}</td></tr>
                                ))}
                              </tbody>
                            </table>
                          )}
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="card">
        <div className="card-head"><div><h2>Rule catalog</h2><p>{rules.data?.rule_version}</p></div><Link to="/admin/analytics">Model validation →</Link></div>
        {rules.data && (
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Rule</th><th>Component</th><th>Details</th></tr></thead>
              <tbody>
                {rules.data.rules.map((r) => (
                  <tr key={r.id}>
                    <td><b>{r.id}</b> {r.name}</td>
                    <td className="small">{r.component}</td>
                    <td className="xs muted">{Object.entries(r).filter(([k]) => !["id", "name", "component"].includes(k)).map(([k, v]) => `${k}: ${typeof v === "string" ? v : JSON.stringify(v)}`).join(" · ")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="card">
        <div className="card-head"><h2>Audit trail</h2><button className="btn btn-sm" onClick={audit.reload}>Refresh</button></div>
        {audit.error && <div className="card-body"><ErrorBox error={audit.error} /></div>}
        {audit.data && (
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Time</th><th>Actor</th><th>Action</th><th>Entity</th><th>Detail</th></tr></thead>
              <tbody>
                {audit.data.map((a) => (
                  <tr key={a.id}>
                    <td className="small">{dateTime(a.ts)}</td>
                    <td className="small">{a.actor}</td>
                    <td className="small"><b>{a.action}</b></td>
                    <td className="xs mono">{a.entity}:{a.entity_id}</td>
                    <td className="xs muted" style={{ maxWidth: 420, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={a.detail_json}>{a.detail_json}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

function IngestForm({ onDone }: { onDone: () => void }) {
  const [uid, setUid] = useState("");
  const [profile, setProfile] = useState(
    JSON.stringify({ display_name: "Test Applicant", age: 30, education_level: "Bachelor", employment_status: "salaried", monthly_income: 32000, city_tier: 1, housing_status: "rent", monthly_rent: 9000, months_in_current_job: 18, months_at_address: 14 }, null, 1),
  );
  const [txn, setTxn] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [res, setRes] = useState<{ score: number; tier: { name: string }; ingestion: { stats: Record<string, unknown>; issues: unknown[] } } | null>(null);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!txn) return;
    setBusy(true);
    setErr(null);
    setRes(null);
    const f = new FormData();
    f.append("user_id", uid);
    f.append("profile", profile);
    f.append("transactions", txn);
    try {
      setRes(await api("/api/ingestion", { form: f, method: "POST" }));
      onDone();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <form className="card" onSubmit={submit}>
      <div className="card-head"><div><h2>Ingest one applicant</h2><p>Profile JSON + transaction CSV/JSON. Validated, stored, and scored immediately.</p></div></div>
      <div className="card-body grid g2">
        <div className="stack">
          <label className="field">Applicant ID<input value={uid} onChange={(e) => setUid(e.target.value)} pattern="[A-Za-z0-9_\-]{3,40}" required placeholder="e.g. USR_TEST01" /></label>
          <label className="field">Transactions file<input type="file" accept=".csv,.json" onChange={(e) => setTxn(e.target.files?.[0] ?? null)} required /></label>
          <a className="small" href="/sample_transactions.csv" download>Synthetic sample file</a>
          <button className="btn btn-primary" disabled={busy || !txn}>{busy ? "Ingesting…" : "Validate, ingest and score"}</button>
          {err && <ErrorBox error={err} />}
          {res && (
            <div className="callout pos small">
              Scored <b>{res.score}</b> ({res.tier.name}). {String(res.ingestion.stats.transactions)} transactions, {String(res.ingestion.stats.obligations)} bills, {res.ingestion.issues.length} validation finding(s).{" "}
              <Link to={`/admin/candidates/${uid}`}>Open profile</Link>
            </div>
          )}
        </div>
        <label className="field">Profile JSON<textarea rows={12} className="mono" value={profile} onChange={(e) => setProfile(e.target.value)} /></label>
      </div>
    </form>
  );
}
