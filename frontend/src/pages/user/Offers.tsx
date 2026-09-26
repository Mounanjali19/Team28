import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Badge, Empty, ErrorBox, Loading, Modal, useToast } from "../../components/ui";
import { useApi } from "../../hooks/useApi";
import { useUser } from "../../layouts/UserLayout";
import { api } from "../../services/api";
import type { Offer } from "../../types";
import { dateTime, inr, OFFER_TONE } from "../../utils/format";

export default function Offers() {
  const { userId, reload: reloadProfile } = useUser();
  const { data, error, loading, reload } = useApi<Offer[]>(`/api/users/${userId}/offers`);
  const toast = useToast();
  const nav = useNavigate();
  const [confirm, setConfirm] = useState<Offer | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const act = async (o: Offer, action: "accept" | "reject" | "view") => {
    setBusy(o.offer_id + action);
    setErr(null);
    try {
      await api(`/api/offers/${o.offer_id}/respond`, { body: { action } });
      if (action !== "view") toast(action === "accept" ? `Accepted. ${o.lender_name} can now see your name and phone number.` : "Offer declined.");
      setConfirm(null);
      await reload();
      if (action === "accept") void reloadProfile();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
      await reload();
    } finally {
      setBusy(null);
    }
  };

  const applyWith = async (o: Offer) => {
    setBusy(o.offer_id + "apply");
    try {
      const r = await api<{ status: string }>("/api/applications", { body: { product_id: o.product_id, offer_id: o.offer_id } });
      toast(`Submitted to the partner bank: ${r.status.replace("_", " ")}`);
      nav("/app/applications");
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Offers from lenders</h1>
          <p>Lenders see you anonymously. Your name and phone number are shared with a lender only when you accept its offer.</p>
        </div>
      </div>
      {err && <ErrorBox error={err} />}
      {error && <ErrorBox error={error} onRetry={reload} />}
      {loading && !data && <Loading />}
      {data && !data.length && (
        <div className="card">
          <Empty>No offers yet. Lenders can send you offers for products your policy score qualifies for.</Empty>
        </div>
      )}
      <div className="grid g2">
        {data?.map((o) => (
          <div key={o.offer_id} className="card card-pad stack" style={{ gap: 10 }}>
            <div className="row between" style={{ alignItems: "flex-start" }}>
              <div>
                <div className="eyebrow">{o.lender_name}</div>
                <h3 style={{ fontSize: 15 }}>{o.product_name}</h3>
              </div>
              <Badge tone={OFFER_TONE[o.status]} dot>{o.status}</Badge>
            </div>
            <dl className="kv">
              <dt>Amount</dt>
              <dd>{inr(o.amount)}</dd>
              <dt>Interest rate</dt>
              <dd>{o.interest_rate}%</dd>
              <dt>Product minimum</dt>
              <dd>{o.min_score} (your score when sent: {o.score_at_offer})</dd>
              <dt>Expires</dt>
              <dd>{dateTime(o.expires_at)}</dd>
            </dl>
            {o.message && <div className="callout small">{o.message}</div>}
            <div className="row">
              {(o.status === "sent" || o.status === "viewed") && (
                <>
                  <button className="btn btn-primary btn-sm" onClick={() => setConfirm(o)} disabled={busy !== null}>Accept</button>
                  <button className="btn btn-danger btn-sm" onClick={() => act(o, "reject")} disabled={busy !== null}>
                    {busy === o.offer_id + "reject" ? "Declining…" : "Decline"}
                  </button>
                  {o.status === "sent" && (
                    <button className="btn btn-ghost btn-sm" onClick={() => act(o, "view")} disabled={busy !== null}>Mark as read</button>
                  )}
                </>
              )}
              {o.status === "accepted" && (
                <button className="btn btn-primary btn-sm" onClick={() => applyWith(o)} disabled={busy !== null}>
                  {busy === o.offer_id + "apply" ? "Submitting…" : "Apply with the bank"}
                </button>
              )}
            </div>
          </div>
        ))}
      </div>
      {confirm && (
        <Modal
          title="Accept this offer?"
          onClose={() => setConfirm(null)}
          footer={
            <>
              <button className="btn" onClick={() => setConfirm(null)}>Cancel</button>
              <button className="btn btn-primary" onClick={() => act(confirm, "accept")} disabled={busy !== null}>
                {busy ? "Checking your score…" : "Accept and share my contact"}
              </button>
            </>
          }
        >
          <p>
            {confirm.lender_name} will see your name, phone number and locality. Your policy score is re-checked now; if it has dropped below {confirm.min_score}, the
            offer is withdrawn.
          </p>
        </Modal>
      )}
    </div>
  );
}
