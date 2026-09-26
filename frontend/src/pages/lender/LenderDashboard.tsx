import { Link } from "react-router-dom";
import { HBars } from "../../components/Charts";
import { ErrorBox, Loading, Stat } from "../../components/ui";
import { useApi } from "../../hooks/useApi";
import type { PolicySnapshot } from "../../types";
import { pct } from "../../utils/format";

interface Dash {
  candidates: number;
  eligible_for_your_products: number;
  above_default_filter: number;
  pending_offers: number;
  offers_by_status: Record<string, number>;
  acceptance_rate: number | null;
  enhanced_review: number;
  second_look: number;
  tier_counts: Record<string, number>;
  your_products: { product_id: string; product_name: string; min_score: number }[];
}

export default function LenderDashboard() {
  const { data: d, error, loading, reload } = useApi<Dash>("/api/lenders/dashboard");
  const policy = useApi<PolicySnapshot>("/api/policy");
  if (error) return <ErrorBox error={error} onRetry={reload} />;
  if (loading || !d) return <Loading />;
  const tiers = policy.data?.tiers ?? [];
  const [lo, hi] = policy.data?.lender_default_score_range ?? [650, 1000];
  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Dashboard</h1>
          <p>Scored applicant pool (live, uploaded and official-sample applicants). Scores are the rule-based policy score.</p>
        </div>
        <Link className="btn btn-primary" to="/lender/candidates">Find candidates</Link>
      </div>
      <div className="grid g4">
        <Stat label="Scored applicants" value={d.candidates.toLocaleString("en-IN")} />
        <Stat label={`Default filter (${lo}–${hi})`} value={d.above_default_filter.toLocaleString("en-IN")} sub="policy score in range" />
        <Stat label="Eligible for your products" value={d.eligible_for_your_products.toLocaleString("en-IN")} sub="score ≥ your lowest product minimum" />
        <Stat label="Offer acceptance" value={d.acceptance_rate === null ? "—" : pct(d.acceptance_rate, 0)} sub={`${d.pending_offers} awaiting a response`} />
      </div>
      <div className="grid g2">
        <div className="card">
          <div className="card-head"><h2>Pool by risk tier</h2></div>
          <div className="card-body">
            <HBars
              items={tiers.map((t) => ({ label: `${t.code} ${t.name}`, value: d.tier_counts[t.code] ?? 0, color: t.color, sub: `${t.min_score}–${t.max_score}` }))}
              format={(v) => v.toLocaleString("en-IN")}
            />
          </div>
        </div>
        <div className="card">
          <div className="card-head"><h2>Your products</h2></div>
          <div className="card-body stack">
            {d.your_products.length ? (
              <table className="table">
                <tbody>
                  {d.your_products.map((p) => (
                    <tr key={p.product_id}>
                      <td><b>{p.product_name}</b></td>
                      <td className="small muted">min score {p.min_score}</td>
                      <td className="r">
                        <Link className="btn btn-sm" to={`/lender/candidates?eligible_for=${p.product_id}&score_min=${p.min_score}`}>Eligible candidates</Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <div className="small muted">Your institution has no products in the catalog, so you can review candidates but not send offers.</div>
            )}
            <div className="row">
              <div className="callout warn small" style={{ flex: 1 }}>
                <b>{d.enhanced_review}</b> rule-eligible applicants carry an ML <b>enhanced review</b> flag.{" "}
                <Link to="/lender/candidates?review_flag=ENHANCED_REVIEW">Review them</Link>
              </div>
              <div className="callout small" style={{ flex: 1 }}>
                <b>{d.second_look}</b> applicants below the cut-off look lower-risk to the ML model (<b>second look</b>).{" "}
                <Link to="/lender/candidates?review_flag=SECOND_LOOK&score_min=0">See them</Link>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
