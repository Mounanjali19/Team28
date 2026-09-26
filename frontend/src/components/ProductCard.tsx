import type { ReactNode } from "react";
import type { Product } from "../types";
import { inr } from "../utils/format";
import { Badge } from "./ui";

export function ProductCard({ p, actions, showPropensity = false }: { p: Product; actions?: ReactNode; showPropensity?: boolean }) {
  return (
    <div className="card card-pad stack" style={{ gap: 10, opacity: p.eligible ? 1 : 0.92 }}>
      <div className="row between" style={{ alignItems: "flex-start" }}>
        <div>
          <div className="eyebrow">{p.type} · {p.lender_name}</div>
          <h3 style={{ fontSize: 15, marginTop: 2 }}>{p.product_name}</h3>
        </div>
        {p.eligible ? <Badge tone="pos" dot>Eligible</Badge> : <Badge tone="" dot>Locked · {p.gap} pts short</Badge>}
      </div>
      <dl className="kv">
        <dt>Minimum score</dt>
        <dd className="num">{p.min_score}</dd>
        <dt>Rate</dt>
        <dd>{p.interest_rate}</dd>
        <dt>Amount</dt>
        <dd>
          {inr(p.amount_min)} – {inr(p.amount_max)}
        </dd>
        {p.tenure_months ? (
          <>
            <dt>Tenure</dt>
            <dd>{p.tenure_months} months</dd>
          </>
        ) : null}
        {p.annual_fee !== null && p.annual_fee !== undefined ? (
          <>
            <dt>Annual fee</dt>
            <dd>{inr(p.annual_fee)}</dd>
          </>
        ) : null}
        {showPropensity && p.propensity !== undefined && p.propensity !== null && (
          <>
            <dt>Predicted acceptance</dt>
            <dd style={{ color: "var(--ml)" }}>{(p.propensity * 100).toFixed(1)}% <span className="xs muted">(Case 2 model)</span></dd>
          </>
        )}
      </dl>
      <div className="xs muted">{p.why_recommended ?? p.reason}</div>
      {actions && <div className="row">{actions}</div>}
    </div>
  );
}
