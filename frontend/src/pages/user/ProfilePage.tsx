import { CashflowChart } from "../../components/Charts";
import { Empty, ErrorBox, Loading, TierBadge } from "../../components/ui";
import { useApi } from "../../hooks/useApi";
import { useUser } from "../../layouts/UserLayout";
import { dateTime, inr, titleCase } from "../../utils/format";

interface UserRow {
  user_id: string;
  age: number | null;
  education_level: string | null;
  employment_status: string | null;
  monthly_income: number | null;
  city_tier: number | null;
  housing_status: string | null;
  cohort: string;
  as_of_date: string;
  match_confidence: number;
  contact: { display_name: string; phone: string; locality: string };
}
interface HistoryRow { score_id: number; as_of: string; score: number; tier: string; decision: string; data_quality: string; trigger: string; computed_at: string; latency_ms: number }
interface DataSummary {
  as_of: string;
  monthly: { month: string; income: number; spend: number; discretionary: number; net: number }[];
  bills_last_12m: Record<string, { due: number; on_time: number; late: number }>;
  record_counts: Record<string, number>;
}
interface AuditRow { id: number; ts: string; action: string; actor: string; detail_json: string }

export default function ProfilePage() {
  const { profile: p, userId } = useUser();
  const u = useApi<UserRow>(`/api/users/${userId}`);
  const hist = useApi<HistoryRow[]>(`/api/users/${userId}/history`);
  const ds = useApi<DataSummary>(`/api/users/${userId}/data-summary`);
  const audit = useApi<AuditRow[]>(`/api/admin/audit?limit=15`);

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Profile and data</h1>
          <p>What AltCredit holds about you, the data the score was computed from, and every time it was recalculated.</p>
        </div>
      </div>
      <div className="grid g2">
        <div className="card">
          <div className="card-head"><h2>Your details</h2></div>
          <div className="card-body">
            {u.error && <ErrorBox error={u.error} />}
            {u.data ? (
              <dl className="kv">
                <dt>Name</dt><dd>{u.data.contact.display_name}</dd>
                <dt>Phone</dt><dd>{u.data.contact.phone}</dd>
                <dt>Locality</dt><dd>{u.data.contact.locality}</dd>
                <dt>Age</dt><dd>{u.data.age ?? "—"}</dd>
                <dt>Education</dt><dd>{u.data.education_level ?? "—"}</dd>
                <dt>Employment</dt><dd>{titleCase(u.data.employment_status)}</dd>
                <dt>Declared income</dt><dd>{inr(u.data.monthly_income)} / month</dd>
                <dt>Income used</dt><dd>{inr(p.policy.income.value)} ({p.policy.income.source})</dd>
                <dt>City tier</dt><dd>{u.data.city_tier ?? "—"}</dd>
                <dt>Housing</dt><dd>{titleCase(u.data.housing_status)}</dd>
                <dt>Identity match</dt><dd>{u.data.match_confidence.toFixed(2)}</dd>
                <dt>Record</dt><dd className="mono">{u.data.user_id} · {u.data.cohort}</dd>
              </dl>
            ) : u.loading && <Loading />}
            <div className="xs muted" style={{ marginTop: 10 }}>All people and contact details in this demo are synthetic.</div>
          </div>
        </div>
        <div className="card">
          <div className="card-head">
            <h2>Income and spending, last 12 months</h2>
          </div>
          <div className="card-body stack">
            {ds.error && <ErrorBox error={ds.error} />}
            {ds.data ? (
              <>
                <CashflowChart months={ds.data.monthly} />
                <div className="table-wrap">
                  <table className="table">
                    <thead><tr><th>Bill type</th><th className="r">Due</th><th className="r">On time</th><th className="r">Late</th></tr></thead>
                    <tbody>
                      {Object.entries(ds.data.bills_last_12m).map(([k, b]) => (
                        <tr key={k}><td>{titleCase(k)}</td><td className="r num">{b.due}</td><td className="r num pos">{b.on_time}</td><td className={`r num ${b.late ? "neg" : ""}`}>{b.late}</td></tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div className="xs muted">
                  Records: {Object.entries(ds.data.record_counts).map(([k, v]) => `${v.toLocaleString("en-IN")} ${k.replace("_", " ")}`).join(" · ")}
                </div>
              </>
            ) : ds.loading && <Loading />}
          </div>
        </div>
      </div>

      <div className="card">
        <div className="card-head">
          <div>
            <h2>Score history</h2>
            <p>Every stored calculation. Simulations are never written here.</p>
          </div>
        </div>
        {hist.error && <ErrorBox error={hist.error} />}
        {hist.data && !hist.data.length && <Empty>No stored scores.</Empty>}
        {hist.data && hist.data.length > 0 && (
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Computed</th><th>As of</th><th className="r">Score</th><th>Tier</th><th>Decision</th><th>Data</th><th>Trigger</th></tr></thead>
              <tbody>
                {hist.data.map((h) => (
                  <tr key={h.score_id}>
                    <td className="small">{dateTime(h.computed_at)}</td>
                    <td className="small">{h.as_of}</td>
                    <td className="r num"><b>{h.score}</b></td>
                    <td><TierBadge tier={h.tier} /></td>
                    <td className="small">{h.decision}</td>
                    <td className="small">{h.data_quality}</td>
                    <td className="small muted">{h.trigger}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="grid g2">
        <div className="card">
          <div className="card-head"><h2>Policy decisions applied</h2></div>
          <div className="card-body">
            <dl className="kv small">
              {Object.entries(p.policy.open_decisions).map(([k, v]) => (
                <div key={k} style={{ display: "contents" }}>
                  <dt className="mono">{k}</dt>
                  <dd>{String(v)}</dd>
                </div>
              ))}
            </dl>
            <div className="xs muted" style={{ marginTop: 8 }}>Defaults where the official scoring table was silent (rulebook v0.1). All live in one configuration file.</div>
          </div>
        </div>
        <div className="card">
          <div className="card-head"><h2>Recent activity on your record</h2></div>
          {audit.error && <div className="card-body"><ErrorBox error={audit.error} /></div>}
          {audit.data && (
            <div className="table-wrap">
              <table className="table">
                <tbody>
                  {audit.data.map((a) => (
                    <tr key={a.id}>
                      <td className="small">{dateTime(a.ts)}</td>
                      <td className="small"><b>{a.action.replace(/_/g, " ")}</b></td>
                      <td className="small muted">{a.actor}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
