import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Badge, Empty, ErrorBox, Loading, TierBadge } from "../../components/ui";
import { useApi } from "../../hooks/useApi";
import type { Offer } from "../../types";
import { dateTime, inr, OFFER_TONE } from "../../utils/format";

interface Out {
  offers: Offer[];
  campaigns: { campaign_id: string; name: string; product_id: string; created_at: string; n_targeted: number; n_sent: number }[];
}

export default function SentOffers() {
  const { data, error, loading, reload } = useApi<Out>("/api/lenders/offers");
  const nav = useNavigate();
  const [status, setStatus] = useState("");
  if (error) return <ErrorBox error={error} onRetry={reload} />;
  if (loading || !data) return <Loading />;
  const offers = status ? data.offers.filter((o) => o.status === status) : data.offers;
  const counts = data.offers.reduce<Record<string, number>>((a, o) => ({ ...a, [o.status]: (a[o.status] ?? 0) + 1 }), {});
  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Sent offers</h1>
          <p>Contact details appear once an applicant accepts.</p>
        </div>
        <button className="btn" onClick={reload}>Refresh</button>
      </div>
      <div className="chip-select">
        <button className={!status ? "on" : ""} onClick={() => setStatus("")}>All ({data.offers.length})</button>
        {Object.entries(counts).map(([s, n]) => (
          <button key={s} className={status === s ? "on" : ""} onClick={() => setStatus(s)}>{s} ({n})</button>
        ))}
      </div>
      <div className="card">
        {!offers.length ? (
          <Empty>No offers yet. Send one from a candidate's page or select several candidates for a campaign.</Empty>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr><th>Applicant</th><th>Product</th><th className="r">Score at offer</th><th>Tier now</th><th>Amount · rate</th><th>Status</th><th>Sent</th><th>Campaign</th></tr>
              </thead>
              <tbody>
                {offers.map((o) => (
                  <tr key={o.offer_id} className="clickable" onClick={() => nav(`/lender/candidates/${o.user_id}`)}>
                    <td>
                      <b>{o.contact?.display_name}</b>
                      <div className="xs muted">{o.contact?.masked ? <span className="mono">{o.user_id}</span> : o.contact?.phone}</div>
                    </td>
                    <td>{o.product_name}</td>
                    <td className="r num">{o.score_at_offer}</td>
                    <td>{o.tier && <TierBadge tier={o.tier} />}</td>
                    <td className="small">{inr(o.amount)} · {o.interest_rate}%</td>
                    <td><Badge tone={OFFER_TONE[o.status]} dot>{o.status}</Badge></td>
                    <td className="small">{dateTime(o.created_at)}</td>
                    <td className="xs mono">{o.campaign_id ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      <div className="card">
        <div className="card-head"><h2>Campaigns</h2></div>
        {!data.campaigns.length ? (
          <Empty>No campaigns yet.</Empty>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Campaign</th><th>Product</th><th className="r">Targeted</th><th className="r">Sent</th><th>Created</th></tr></thead>
              <tbody>
                {data.campaigns.map((c) => (
                  <tr key={c.campaign_id}>
                    <td><b>{c.name}</b><div className="xs mono muted">{c.campaign_id}</div></td>
                    <td className="mono">{c.product_id}</td>
                    <td className="r num">{c.n_targeted}</td>
                    <td className="r num">{c.n_sent}</td>
                    <td className="small">{dateTime(c.created_at)}</td>
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
