import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ProductCard } from "../../components/ProductCard";
import { ErrorBox, Modal, useToast } from "../../components/ui";
import { useUser } from "../../layouts/UserLayout";
import { api } from "../../services/api";
import type { Product } from "../../types";
import { inr } from "../../utils/format";

interface ApplyOut {
  id: number;
  status: string;
  preapproval: { status: string; message?: string; reasons?: string[] };
}

export default function Products() {
  const { profile: p } = useUser();
  const toast = useToast();
  const nav = useNavigate();
  const [applying, setApplying] = useState<Product | null>(null);
  const [amount, setAmount] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const recIds = new Set(p.recommendations.map((r) => r.product_id));
  const others = p.products.filter((x) => !recIds.has(x.product_id));

  const submit = async () => {
    if (!applying) return;
    setBusy(true);
    setErr(null);
    try {
      const r = await api<ApplyOut>("/api/applications", {
        body: { product_id: applying.product_id, requested_amount: amount ? Number(amount) : null },
      });
      toast(`Partner bank response: ${r.preapproval.status.replace("_", " ")} (application ${r.status}).`);
      setApplying(null);
      nav("/app/applications");
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Products</h1>
          <p>Eligibility is decided only by your policy score against each product's published minimum. Nothing here is hard-coded.</p>
        </div>
      </div>
      <h2>Recommended for you</h2>
      {p.recommendations.length ? (
        <>
          <p className="small muted">{p.recommendations[0].ordering_basis}</p>
          <div className="grid g3">
            {p.recommendations.map((x) => (
              <ProductCard
                key={x.product_id}
                p={x}
                showPropensity
                actions={
                  <button className="btn btn-primary btn-sm" onClick={() => { setApplying(x); setAmount(String(x.amount_min ?? "")); setErr(null); }}>
                    Apply with partner bank
                  </button>
                }
              />
            ))}
          </div>
        </>
      ) : (
        <div className="callout warn">
          {p.policy.identity_blocked
            ? "No product can be offered until your identity is confirmed."
            : "You don't qualify for any product yet."}{" "}
          {p.next_locked_product && (
            <Link to={`/app/target?product=${p.next_locked_product.product_id}`}>See what it takes to reach {p.next_locked_product.product_name}</Link>
          )}
        </div>
      )}
      {others.length > 0 && (
        <>
          <h2>Other products in the catalog</h2>
          <div className="grid g3">
            {others.map((x) => (
              <ProductCard
                key={x.product_id}
                p={x}
                actions={
                  !x.eligible && (
                    <Link className="btn btn-sm" to={`/app/target?product=${x.product_id}`}>
                      How do I unlock this?
                    </Link>
                  )
                }
              />
            ))}
          </div>
        </>
      )}
      {applying && (
        <Modal
          title={`Apply: ${applying.product_name}`}
          onClose={() => setApplying(null)}
          footer={
            <>
              <button className="btn" onClick={() => setApplying(null)}>Cancel</button>
              <button className="btn btn-primary" onClick={submit} disabled={busy}>{busy ? "Contacting bank…" : "Submit to bank"}</button>
            </>
          }
        >
          <p className="small">
            AltCredit sends the partner bank ({applying.lender_name}) your policy score, risk tier and review flag with a pseudonymous reference. Your name and
            phone number are not sent. The bank's response is simulated.
          </p>
          <label className="field">
            Requested amount (₹{(applying.amount_min ?? 0).toLocaleString("en-IN")} – {inr(applying.amount_max)})
            <input type="number" value={amount} min={applying.amount_min ?? 0} max={applying.amount_max ?? undefined} onChange={(e) => setAmount(e.target.value)} />
          </label>
          {err && <ErrorBox error={err} />}
        </Modal>
      )}
    </div>
  );
}
