import type { MLValidation, Policy } from "../types";
import { AGREEMENT_TONE } from "../utils/format";
import { Badge, MLLabel } from "./ui";

/**
 * Secondary ML layer. Always shown separately from the policy score and always
 * labelled "ML Risk Score" / "ML Validation Signal"; it never changes the policy decision.
 */
export function MLValidationPanel({ ml, policy, audience = "user" }: { ml: MLValidation; policy: Policy; audience?: "user" | "lender" }) {
  if (!ml.available) {
    return (
      <div className="card ml-card">
        <div className="card-head">
          <MLLabel />
        </div>
        <div className="card-body muted">ML validation is unavailable for this applicant: {ml.reason ?? "model not loaded"}. The policy decision stands on its own.</div>
      </div>
    );
  }
  const ag = ml.agreement;
  return (
    <div className="card ml-card">
      <div className="card-head">
        <div>
          <MLLabel />
          <p>Case 1 probability-of-default model ({ml.model_version}). Secondary check only; it never overrides the policy score.</p>
        </div>
        {ag && (
          <Badge tone={AGREEMENT_TONE[ag.status] ?? ""} dot>
            {ag.label}
          </Badge>
        )}
      </div>
      <div className="card-body stack">
        <div className="grid g3">
          <div>
            <div className="xs muted">12-month default probability</div>
            <div className="big-num" style={{ fontSize: 28, color: "var(--ml)" }}>
              {ml.pd_pct?.toFixed(1)}%
            </div>
            <div className="xs muted">band: {ml.band}</div>
          </div>
          <div>
            <div className="xs muted">ML Risk Score</div>
            <div className="big-num" style={{ fontSize: 28, color: "var(--ml)" }}>
              {ml.ml_risk_score}
            </div>
            <div className="xs muted">= 1000 × (1 − PD); not the credit score</div>
          </div>
          <div>
            <div className="xs muted">Policy score (authoritative)</div>
            <div className="big-num" style={{ fontSize: 28 }}>
              {policy.score}
            </div>
            <div className="xs muted">{policy.tier.name}</div>
          </div>
        </div>
        {ag && (
          <div className={`callout ml`}>
            <b>{ag.label}.</b> {ag.text}
            {ag.review_flag !== "NONE" && (
              <div className="small" style={{ marginTop: 4 }}>
                Review flag: <b>{ag.review_flag.replace("_", " ")}</b>
                {audience === "user"
                  ? ". A lender may take a closer look before approving; your policy score and eligibility are unchanged."
                  : ". Route to manual review; eligibility still follows the policy score."}
              </div>
            )}
            <div className="xs muted" style={{ marginTop: 4 }}>
              Policy decision changed by ML: <b>{ag.rule_changed ? "yes" : "no"}</b>
            </div>
          </div>
        )}
        {!ml.confident && (
          <div className="callout warn small">
            ML confidence is limited{ml.confidence_reasons?.length ? `: ${ml.confidence_reasons.join("; ")}` : ""}. Treat this signal with caution.
          </div>
        )}
        <div className="stack" style={{ gap: 12 }}>
          <div>
            <h3 style={{ marginBottom: 6 }}>Raises estimated risk</h3>
            <SignalList items={ml.risk_increasing_signals ?? []} tone="neg" />
          </div>
          <div>
            <h3 style={{ marginBottom: 6 }}>Lowers estimated risk</h3>
            <SignalList items={ml.risk_reducing_signals ?? []} tone="pos" />
          </div>
        </div>
        <div className="xs muted">
          Holdout AUC {ml.holdout_auc?.toFixed(3)} on a temporal split. Contributions are logistic-regression coefficient × standardised value (log-odds).
        </div>
      </div>
    </div>
  );
}

function SignalList({ items, tone }: { items: { label: string; contribution: number; value: number | null }[]; tone: string }) {
  if (!items.length) return <div className="xs muted">None material.</div>;
  const max = Math.max(...items.map((i) => Math.abs(i.contribution)), 0.01);
  return (
    <div>
      {items.map((s) => (
        <div key={s.label} className="hbar" style={{ gridTemplateColumns: "1fr 90px 48px" }}>
          <span className="small">
            {s.label}
            {s.value !== null && <span className="xs muted"> ({Number.isInteger(s.value) ? s.value : s.value.toFixed(2)})</span>}
          </span>
          <div className={`bar ${tone}`}>
            <span style={{ width: `${(Math.abs(s.contribution) / max) * 100}%`, background: "var(--ml)" }} />
          </div>
          <span className="num xs r">{s.contribution > 0 ? "+" : ""}{s.contribution.toFixed(2)}</span>
        </div>
      ))}
    </div>
  );
}
