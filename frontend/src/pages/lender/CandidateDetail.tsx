import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { CashflowChart } from "../../components/Charts";
import { DataQualityPanel } from "../../components/DataQualityPanel";
import { FactorBreakdown } from "../../components/FactorBreakdown";
import { MLValidationPanel } from "../../components/MLValidationPanel";
import { Badge, ErrorBox, Loading, PolicyLabel, TierBadge, useToast } from "../../components/ui";
import { useApi } from "../../hooks/useApi";
import { useAuth } from "../../hooks/useAuth";
import { api } from "../../services/api";
import type { CatalogProduct, Profile } from "../../types";
import { dateTime, inr, OFFER_TONE } from "../../utils/format";
import { OfferForm, offerBody, offerDefaults } from "./Candidates";

interface DataSummary {
  monthly: { month: string; income: number; spend: number; discretionary: number; net: number }[];
  bills_last_12m: Record<string, { due: number; on_time: number; late: number }>;
}

export default function CandidateDetail({ base = "/lender" }: { base?: string }) {
  const { id = "" } = useParams();
  const { session } = useAuth();
  const toast = useToast();
  const { data: p, error, loading, reload } = useApi<Profile>(`/api/lenders/candidates/${id}`);
  const ds = useApi<DataSummary>(`/api/users/${id}/data-summary`);
  const catalog = useApi<CatalogProduct[]>("/api/products");
  const [offer, setOffer] = useState<ReturnType<typeof offerDefaults> | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  if (error) return <ErrorBox error={error} onRetry={reload} />;
  if (loading || !p) return <Loading label="Loading risk profile…" />;
  const own = (catalog.data ?? []).filter((x) => x.lender_id === session?.lender_id);
  const ownEligible = own.filter((x) => p.policy.score >= x.min_score);
  const isLender = session?.role === "lender";

  const send = async () => {
    if (!offer) return;
    setBusy(true);
    setErr(null);
    try {
      await api("/api/offers", { body: { ...offerBody(offer), user_id: id } });
      toast("Offer sent. The applicant sees it on their Offers page.");
      setOffer(null);
      await reload();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="stack">
      <Link to={`${base}/candidates`} className="small">← Candidates</Link>
      <div className="page-head">
        <div>
          <h1>{p.contact?.display_name}</h1>
          <p>
            <span className="mono">{p.user_id}</span> · {p.contact?.phone} · {p.contact?.locality}
          </p>
          {p.contact?.masked && <p className="xs">Contact details unlock when the applicant accepts one of your offers.</p>}
        </div>
        {isLender && (
          <button className="btn btn-primary" disabled={!ownEligible.length || p.policy.weak_id} onClick={() => { setOffer(offerDefaults(ownEligible)); setErr(null); }}
            title={!ownEligible.length ? "Policy score is below all of your product minimums" : undefined}>
            Send offer
          </button>
        )}
      </div>
      {isLender && !ownEligible.length && <div className="callout warn small">This applicant's policy score ({p.policy.score}) is below the minimum of every product you offer.</div>}

      <div className="grid g4">
        <div className="card card-pad stat">
          <PolicyLabel>Policy score</PolicyLabel>
          <div className="value">{p.policy.score}</div>
          <div className="sub"><TierBadge tier={p.policy.tier} /></div>
        </div>
        <div className="card card-pad stat">
          <div className="label">Decision</div>
          <div className="value" style={{ fontSize: 20 }}>{p.policy.decision.label}</div>
          <div className="sub">{p.recommendations.length} product(s) eligible</div>
        </div>
        <div className="card card-pad stat ml-card">
          <div className="label" style={{ color: "var(--ml)" }}>ML Risk Score (validation)</div>
          <div className="value" style={{ color: "var(--ml)" }}>{p.ml.ml_risk_score ?? "—"}</div>
          <div className="sub">PD {p.ml.pd_pct ?? "—"}% · {p.ml.band}</div>
        </div>
        <div className="card card-pad stat">
          <div className="label">Review flag</div>
          <div className="value" style={{ fontSize: 20 }}>{p.ml.agreement?.review_flag.replace("_", " ") ?? "—"}</div>
          <div className="sub">{p.ml.agreement?.label}</div>
        </div>
      </div>

      <div className="grid" style={{ gridTemplateColumns: "minmax(0, 3fr) minmax(0, 2fr)" }}>
        <div className="card">
          <div className="card-head">
            <div>
              <h2>Rule breakdown</h2>
              <p>{p.explanation.summary}</p>
            </div>
          </div>
          <div className="card-body"><FactorBreakdown policy={p.policy} /></div>
        </div>
        <div className="stack">
          <MLValidationPanel ml={p.ml} policy={p.policy} audience="lender" />
          <DataQualityPanel dq={p.policy.data_quality} weakId={p.policy.weak_id} blocked={p.policy.identity_blocked} />
        </div>
      </div>

      <div className="grid g2">
        <div className="card">
          <div className="card-head"><h2>Cash flow, last 12 months</h2></div>
          <div className="card-body">
            {ds.error && <ErrorBox error={ds.error} />}
            {ds.data && <CashflowChart months={ds.data.monthly} />}
          </div>
        </div>
        <div className="card">
          <div className="card-head"><h2>Product eligibility</h2></div>
          <div className="table-wrap">
            <table className="table">
              <tbody>
                {p.products.map((x) => (
                  <tr key={x.product_id}>
                    <td><b>{x.product_name}</b><div className="xs muted">{x.lender_name}</div></td>
                    <td className="small">min {x.min_score}</td>
                    <td>{x.eligible ? <Badge tone="pos">eligible</Badge> : <Badge>{x.gap} short</Badge>}</td>
                    <td className="r small" style={{ color: "var(--ml)" }}>{x.propensity !== undefined && x.propensity !== null ? `${(x.propensity * 100).toFixed(1)}% accept` : ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {isLender && (
        <div className="card">
          <div className="card-head"><h2>Your offers to this applicant</h2></div>
          {p.offers_from_you?.length ? (
            <div className="table-wrap">
              <table className="table">
                <thead><tr><th>Product</th><th>Amount</th><th>Rate</th><th>Status</th><th>Sent</th></tr></thead>
                <tbody>
                  {p.offers_from_you.map((o) => (
                    <tr key={o.offer_id}>
                      <td className="mono">{o.product_id}</td>
                      <td>{inr(o.amount)}</td>
                      <td>{o.interest_rate}%</td>
                      <td><Badge tone={OFFER_TONE[o.status]} dot>{o.status}</Badge></td>
                      <td className="small">{dateTime(o.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="card-body small muted">No offers sent yet.</div>
          )}
        </div>
      )}

      {offer && (
        <div className="modal-bg" onMouseDown={(e) => e.target === e.currentTarget && setOffer(null)}>
          <div className="modal" role="dialog" aria-modal="true" aria-label="Send offer">
            <div className="card-head"><h2>Send offer to {p.contact?.display_name}</h2></div>
            <div className="card-body stack">
              <OfferForm products={ownEligible} value={offer} onChange={setOffer} />
              {p.ml.agreement?.review_flag === "ENHANCED_REVIEW" && (
                <div className="callout warn small">ML flags elevated risk for this rule-eligible applicant. The offer is allowed; consider manual review before disbursal.</div>
              )}
              {err && <ErrorBox error={err} />}
            </div>
            <div className="card-head" style={{ borderTop: "1px solid var(--line)", borderBottom: 0, justifyContent: "flex-end" }}>
              <button className="btn" onClick={() => setOffer(null)}>Cancel</button>
              <button className="btn btn-primary" onClick={send} disabled={busy}>{busy ? "Sending…" : "Send offer"}</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
